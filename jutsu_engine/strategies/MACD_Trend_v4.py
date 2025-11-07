"""
Goldilocks Strategy (V8.0): Simple 3-regime system using QQQ signals.

This strategy trades TQQQ/QQQ/CASH based on:
- Primary Trend Filter: 100-day EMA (Risk-On vs Risk-Off)
- Momentum Signal: MACD crossover (determines leverage level)

Strategy Logic:
- Calculates EMA and MACD on QQQ data only (signal asset)
- Trades TQQQ (3x bull), QQQ (1x defensive), or CASH based on 3 hierarchical regimes
- ATR-based position sizing for TQQQ (2.5% portfolio risk, 3.0 ATR stop)
- Flat 60% allocation for QQQ (NO ATR stop, regime-managed exits)

More Info: MACD_Trend-v4.md
"""
from decimal import Decimal
from typing import Optional
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import macd, ema, atr


class MACD_Trend_v4(Strategy):
    """
    Goldilocks Strategy: 3-regime trend-following using QQQ signals.

    Trades TQQQ (3x bull), QQQ (1x defensive), or CASH based on:
    - Primary Trend Filter: 100-day EMA (Price > EMA = Risk-On, Price < EMA = Risk-Off)
    - Momentum Signal: MACD Line vs Signal Line (Strong vs Pause)
    - Position Sizing: DUAL MODE
      * ATR-based for TQQQ (2.5% risk, 3.0 ATR stop)
      * Flat 60% allocation for QQQ (NO ATR stop, regime-managed exit)

    3 regimes with hierarchical priority (checked top to bottom):
    1. RISK-OFF: Price < EMA → CASH 100%
    2. RISK-ON (STRONG): Price > EMA AND MACD_Line > Signal_Line → TQQQ 2.5% risk
    3. RISK-ON (PAUSE): Price > EMA AND MACD_Line <= Signal_Line → QQQ 60% flat

    Entry Conditions by Regime:
    - Regime CASH: Price < 100-EMA
    - Regime TQQQ: Price > 100-EMA AND MACD_Line > Signal_Line
    - Regime QQQ: Price > 100-EMA AND MACD_Line <= Signal_Line

    Exit Conditions:
    - TQQQ: Regime change OR ATR stop hit
    - QQQ: Regime change ONLY (NO ATR stop)

    Rebalances only on regime changes.
    Stop-Loss: 3.0 ATR from entry for TQQQ (allows trend to breathe).
    """

    def __init__(
        self,
        macd_fast_period: int = 12,
        macd_slow_period: int = 26,
        macd_signal_period: int = 9,
        ema_period: int = 100,
        atr_period: int = 14,
        atr_stop_multiplier: Decimal = Decimal('3.0'),
        tqqq_risk: Decimal = Decimal('0.025'),
        qqq_allocation: Decimal = Decimal('0.60'),
    ):
        """
        Initialize Goldilocks strategy.

        Args:
            macd_fast_period: Period for fast MACD EMA (default: 12)
            macd_slow_period: Period for slow MACD EMA (default: 26)
            macd_signal_period: Period for MACD signal line (default: 9)
            ema_period: Period for trend EMA (default: 100)
            atr_period: Period for ATR calculation (default: 14)
            atr_stop_multiplier: Stop-loss distance in ATR units (default: 3.0)
            tqqq_risk: Portfolio risk for TQQQ trades (default: 2.5%)
            qqq_allocation: Flat allocation for QQQ trades (default: 60%)
        """
        super().__init__()
        self.macd_fast_period = macd_fast_period
        self.macd_slow_period = macd_slow_period
        self.macd_signal_period = macd_signal_period
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.tqqq_risk = tqqq_risk
        self.qqq_allocation = qqq_allocation

        # Trading symbols (2 symbols: signal + 2 vehicles)
        self.signal_symbol = 'QQQ'    # Calculate indicators on QQQ (also trades QQQ)
        self.bull_symbol = 'TQQQ'     # 3x leveraged long
        self.defensive_symbol = 'QQQ'  # 1x defensive (same as signal)

        # State tracking
        self.current_regime: Optional[str] = None  # 'CASH', 'TQQQ', or 'QQQ'
        self.current_position_symbol: Optional[str] = None  # 'TQQQ', 'QQQ', or None
        self.tqqq_entry_price: Optional[Decimal] = None
        self.tqqq_stop_loss: Optional[Decimal] = None
        self._symbols_validated: bool = False  # Track if symbol validation completed

    def init(self):
        """Initialize strategy state."""
        self.current_regime = None
        self.current_position_symbol = None
        self.tqqq_entry_price = None
        self.tqqq_stop_loss = None
        self._symbols_validated = False

    def _validate_required_symbols(self) -> None:
        """
        Validate that all required symbols are present in data handler.

        This method checks that both required symbols (QQQ, TQQQ)
        are available in the loaded market data. If any symbols are missing,
        it raises a ValueError with a clear, actionable error message.

        Raises:
            ValueError: If any required symbol is missing from available symbols

        Note:
            This validation runs lazily on the first on_bar() call once enough
            bars are available, since symbols aren't known at __init__ time.
        """
        required_symbols = [
            self.signal_symbol,  # QQQ - signal calculations and defensive trading
            self.bull_symbol,    # TQQQ - leveraged long
        ]

        # Get unique symbols from loaded bars
        available_symbols = list(set(bar.symbol for bar in self._bars))

        # Check for missing symbols
        missing_symbols = [s for s in required_symbols if s not in available_symbols]

        if missing_symbols:
            raise ValueError(
                f"MACD_Trend_v4 requires symbols {required_symbols} but "
                f"missing: {missing_symbols}. Available symbols: {available_symbols}. "
                f"Please include all required symbols in your backtest command."
            )

    def on_bar(self, bar):
        """
        Process each bar and generate signals based on regime.

        Processes:
        - QQQ bars: Regime detection (MACD, EMA evaluation)
        - TQQQ bars: Stop-loss checking (ATR stop for TQQQ only)

        Args:
            bar: Market data bar (MarketDataEvent)

        Raises:
            ValueError: If required symbols are missing from loaded data

        Note:
            QQQ position has NO stop-loss checking (regime-managed exit only).
        """
        # Perform symbol validation once we have enough bars
        # Wait until we have enough bars for EMA calculation to ensure all symbols loaded
        lookback = max(self.ema_period, self.atr_period) + 10
        if not self._symbols_validated and len(self._bars) >= lookback:
            self._validate_required_symbols()
            self._symbols_validated = True
            self.log(f"Symbol validation passed: All required symbols present")

        # Check stop-loss on TQQQ (NOT QQQ)
        if bar.symbol == self.bull_symbol:
            self._check_tqqq_stop_loss(bar)
            return

        # Only process QQQ bars for regime calculation
        if bar.symbol != self.signal_symbol:
            return

        # Need enough bars for indicators
        if len(self._bars) < lookback:
            return

        # Get historical data for QQQ ONLY (filter out other symbols)
        closes = self.get_closes(lookback=lookback, symbol=self.signal_symbol)

        # Calculate MACD on QQQ data
        macd_line, signal_line, histogram = macd(
            closes,
            fast_period=self.macd_fast_period,
            slow_period=self.macd_slow_period,
            signal_period=self.macd_signal_period
        )

        # Calculate 100-day EMA on QQQ data
        ema_values = ema(closes, period=self.ema_period)

        # Get current values
        current_price = closes.iloc[-1]
        current_ema = Decimal(str(ema_values.iloc[-1]))
        current_macd_line = Decimal(str(macd_line.iloc[-1]))
        current_signal_line = Decimal(str(signal_line.iloc[-1]))

        # Store current bar and indicator values for context logging
        self._current_bar = bar
        self._last_indicator_values = {
            'Price': current_price,
            'EMA_100': current_ema,
            'MACD_Line': current_macd_line,
            'Signal_Line': current_signal_line
        }
        self._last_threshold_values = {
            'EMA_Period': self.ema_period,
            'ATR_Stop_Multiplier': self.atr_stop_multiplier,
            'TQQQ_Risk': self.tqqq_risk,
            'QQQ_Allocation': self.qqq_allocation
        }

        # Build decision reason
        trend_status = f"Price({current_price:.2f}) {'>' if current_price > current_ema else '<='} EMA({current_ema:.2f})"
        momentum_status = f"MACD({current_macd_line:.4f}) {'>' if current_macd_line > current_signal_line else '<='} Signal({current_signal_line:.4f})"
        self._last_decision_reason = f"{trend_status}, {momentum_status}"

        # Determine current regime ('CASH', 'TQQQ', or 'QQQ')
        new_regime = self._determine_regime(
            current_price, current_ema, current_macd_line, current_signal_line
        )

        # Log indicator calculation
        self.log(
            f"Indicators: {trend_status}, {momentum_status} | "
            f"Regime={new_regime} | Bars used={len(closes)}"
        )

        # Check if regime changed
        if new_regime != self.current_regime:
            # Log regime transition
            if self.current_regime is not None:
                self.log(
                    f"REGIME CHANGE: {self.current_regime} → {new_regime} | "
                    f"{self._last_decision_reason}"
                )

            # Handle regime transition (liquidate then enter new)
            self._handle_regime_transition(bar, new_regime)

            # Update regime tracker
            self.current_regime = new_regime

    def _determine_regime(
        self,
        price: Decimal,
        ema_value: Decimal,
        macd_line: Decimal,
        signal_line: Decimal
    ) -> str:
        """
        Determine current regime ('CASH', 'TQQQ', or 'QQQ') based on priority order.

        Priority Order (CRITICAL - checked top to bottom):
        1. Price < EMA → RISK-OFF (CASH)
        2. Price > EMA AND MACD_Line > Signal_Line → RISK-ON STRONG (TQQQ)
        3. Price > EMA AND MACD_Line <= Signal_Line → RISK-ON PAUSE (QQQ)

        Args:
            price: Current QQQ price
            ema_value: Current 100-day EMA value
            macd_line: Current MACD line value
            signal_line: Current MACD signal line value

        Returns:
            Regime string: 'CASH', 'TQQQ', or 'QQQ'
        """
        # Priority 1: RISK-OFF
        if price < ema_value:
            return 'CASH'

        # Priority 2: RISK-ON (STRONG)
        if price > ema_value and macd_line > signal_line:
            return 'TQQQ'

        # Priority 3: RISK-ON (PAUSE) - includes MACD == Signal case
        if price > ema_value and macd_line <= signal_line:
            return 'QQQ'

        # Fallback (should never reach here given conditions above)
        return 'CASH'

    def _handle_regime_transition(self, bar, new_regime: str):
        """
        Handle regime change - liquidate current position then enter new regime.

        Liquidation order:
        1. Exit current position (if any)
        2. Clear state tracking
        3. Enter new regime

        Args:
            bar: Current QQQ bar
            new_regime: New regime to enter ('CASH', 'TQQQ', or 'QQQ')
        """
        # Step 1: Liquidate current position (if any)
        if self.current_position_symbol is not None:
            self._liquidate_position()

        # Step 2: Enter new regime
        if new_regime == 'TQQQ':
            self._enter_tqqq(bar)
        elif new_regime == 'QQQ':
            self._enter_qqq(bar)
        # CASH: already liquidated, do nothing

    def _liquidate_position(self):
        """
        Liquidate current position (TQQQ or QQQ).

        Logs strategy context BEFORE selling to ensure liquidation trades have context.
        """
        if self.current_position_symbol is None:
            return

        symbol = self.current_position_symbol

        # Log context BEFORE liquidation signal
        if self._trade_logger and hasattr(self, '_current_bar'):
            regime_desc = f"Liquidating {symbol} position (regime change)"

            self._trade_logger.log_strategy_context(
                timestamp=self._current_bar.timestamp,
                symbol=symbol,
                strategy_state=regime_desc,
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Close position (100% exit)
        if symbol == self.bull_symbol:
            self.sell(symbol, Decimal('1.0'))  # Close TQQQ long
        else:  # QQQ
            self.buy(symbol, Decimal('0.0'))  # Close QQQ (buy with 0% = exit)

        self.log(f"LIQUIDATE: Closed {symbol} position")

        # Clear state tracking
        self.current_position_symbol = None
        self.tqqq_entry_price = None
        self.tqqq_stop_loss = None

    def _enter_tqqq(self, bar):
        """
        Enter TQQQ position with ATR-based sizing (2.5% risk).

        Uses ATR-based position sizing:
        - Total_Dollar_Risk = Portfolio_Equity × 2.5%
        - Dollar_Risk_Per_Share = ATR × 3.0
        - Shares = Total_Dollar_Risk / Dollar_Risk_Per_Share
        - Stop_Loss = Fill_Price - Dollar_Risk_Per_Share

        Args:
            bar: Current QQQ bar (for timestamp)
        """
        trade_symbol = self.bull_symbol  # TQQQ
        regime_desc = "RISK-ON (STRONG): Price > EMA AND MACD_Line > Signal_Line"

        # Calculate ATR on TQQQ (trade vehicle)
        trade_bars = [b for b in self._bars if b.symbol == trade_symbol]
        if len(trade_bars) < self.atr_period:
            self.log(
                f"WARNING: Insufficient {trade_symbol} bars for ATR calculation "
                f"({len(trade_bars)} < {self.atr_period})"
            )
            return

        # Get ATR from trade vehicle
        highs = [b.high for b in trade_bars[-self.atr_period-1:]]
        lows = [b.low for b in trade_bars[-self.atr_period-1:]]
        closes = [b.close for b in trade_bars[-self.atr_period-1:]]

        atr_series = atr(highs, lows, closes, period=self.atr_period)
        current_atr = Decimal(str(atr_series.iloc[-1]))

        # Calculate position size based on ATR risk
        # Dollar_Risk_Per_Share = ATR × ATR_Stop_Multiplier
        dollar_risk_per_share = current_atr * self.atr_stop_multiplier

        # Get current price of TQQQ (last bar)
        current_price = trade_bars[-1].close

        # Calculate stop-loss price
        # For TQQQ (long): Stop = Entry - Dollar_Risk_Per_Share
        stop_price = current_price - dollar_risk_per_share

        # Store entry and stop-loss for tracking
        self.current_position_symbol = trade_symbol
        self.tqqq_entry_price = current_price
        self.tqqq_stop_loss = stop_price

        # Log context BEFORE generating signal
        if self._trade_logger:
            self._trade_logger.log_strategy_context(
                timestamp=bar.timestamp,
                symbol=trade_symbol,
                strategy_state=f"Regime TQQQ: {regime_desc}",
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with ATR-based risk allocation
        # Pass both tqqq_risk (2.5% dollar risk) and dollar_risk_per_share (ATR-based stop)
        # Portfolio will calculate: shares = (portfolio_value × tqqq_risk) / dollar_risk_per_share
        self.buy(trade_symbol, self.tqqq_risk, risk_per_share=dollar_risk_per_share)

        self.log(
            f"REGIME TQQQ: {regime_desc} → {trade_symbol} {self.tqqq_risk*100:.1f}% | "
            f"ATR={current_atr:.2f}, Entry={current_price:.2f}, Stop={stop_price:.2f}"
        )

    def _enter_qqq(self, bar):
        """
        Enter QQQ position with FLAT 60% allocation (NO risk_per_share parameter).

        Uses flat percentage allocation (NOT ATR-based):
        - Allocation = 60% of portfolio value
        - NO ATR calculation
        - NO risk_per_share parameter
        - NO stop-loss tracking
        - Exit is purely regime-managed (regime change only)

        Args:
            bar: Current QQQ bar (for timestamp)
        """
        trade_symbol = self.defensive_symbol  # QQQ
        regime_desc = "RISK-ON (PAUSE): Price > EMA AND MACD_Line <= Signal_Line"

        # Get current price of QQQ (last bar)
        trade_bars = [b for b in self._bars if b.symbol == trade_symbol]
        current_price = trade_bars[-1].close

        # Track current position symbol
        self.current_position_symbol = trade_symbol

        # Log context BEFORE generating signal
        if self._trade_logger:
            self._trade_logger.log_strategy_context(
                timestamp=bar.timestamp,
                symbol=trade_symbol,
                strategy_state=f"Regime QQQ: {regime_desc}",
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with FLAT allocation (NO risk_per_share parameter!)
        # Portfolio will calculate: shares = (portfolio_value × qqq_allocation) / current_price
        self.buy(trade_symbol, self.qqq_allocation)  # NO risk_per_share!

        self.log(
            f"REGIME QQQ: {regime_desc} → {trade_symbol} {self.qqq_allocation*100:.1f}% | "
            f"Entry={current_price:.2f}, NO ATR STOP (regime-managed exit)"
        )

    def _check_tqqq_stop_loss(self, bar):
        """
        Check if stop-loss has been hit on current TQQQ position.

        Simplified stop-loss checking (manual, not GTC orders).
        Liquidates position if price breaches stop level.

        Args:
            bar: TQQQ bar

        Note:
            QQQ positions are NOT checked here (NO ATR stop, regime-managed exit only).
        """
        # Only check if we have an active TQQQ position
        if self.current_position_symbol != self.bull_symbol:
            return

        if self.tqqq_stop_loss is None:
            return

        # TQQQ (long): Stop if price falls below stop level
        if bar.low <= self.tqqq_stop_loss:
            self.log(
                f"STOP-LOSS HIT: {self.bull_symbol} | "
                f"Entry={self.tqqq_entry_price:.2f}, Stop={self.tqqq_stop_loss:.2f}, "
                f"Current={bar.close:.2f}"
            )

            # Log context for stop-loss exit
            if self._trade_logger:
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=self.bull_symbol,
                    strategy_state="Stop-Loss Triggered",
                    decision_reason=f"Price breached stop at {self.tqqq_stop_loss:.2f}",
                    indicator_values=self._last_indicator_values if hasattr(self, '_last_indicator_values') else {},
                    threshold_values=self._last_threshold_values if hasattr(self, '_last_threshold_values') else {}
                )

            # Liquidate position
            self.sell(self.bull_symbol, Decimal('1.0'))

            # Clear tracking
            self.current_position_symbol = None
            self.tqqq_entry_price = None
            self.tqqq_stop_loss = None
            self.current_regime = None  # Force regime re-evaluation on next QQQ bar
