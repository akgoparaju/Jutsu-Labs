"""
All-Weather Strategy (V6.0): 5-regime adaptive trend-following using QQQ signals.

This strategy trades TQQQ/QQQ/SQQQ based on QQQ MACD, 100-day EMA trend filter, and VIX volatility,
with dual position sizing (ATR-based for leveraged, flat allocation for QQQ).

Strategy Logic:
- Calculates MACD and 100-EMA on QQQ data only (signal asset)
- Monitors VIX for kill switch (>30 = VIX FEAR → CASH)
- Trades TQQQ (3x bull), QQQ (1x defensive), SQQQ (3x bear), or CASH based on 5 regimes
- ATR-based position sizing for TQQQ/SQQQ (2.5% portfolio risk)
- Flat 50% allocation for QQQ (regime-managed exits only, NO ATR stop)
- Wide 3.0 ATR stop-loss for leveraged positions (allows trend to "breathe")
More Info: MACD_Trend-v2.md
"""
from decimal import Decimal
from typing import Optional
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import macd, ema, atr


class MACD_Trend_v2(Strategy):
    """
    All-Weather Strategy: 5-regime adaptive trend-following using QQQ signals.

    Trades TQQQ (3x bull), QQQ (1x defensive), SQQQ (3x bear), or CASH based on:
    - Main Trend: 100-day EMA (Price > EMA = Up, Price < EMA = Down)
    - Momentum: MACD Line vs Signal Line (bullish/bearish) and Zero-Line (strong bear check)
    - Volatility Filter: VIX Kill Switch (>30 → CASH)
    - Position Sizing: DUAL MODE
      * ATR-based for TQQQ/SQQQ (2.5% risk, 3.0 ATR stop)
      * Flat 50% allocation for QQQ (NO ATR stop, regime-managed exit)

    5 regimes with priority order (checked top to bottom):
    1. VIX FEAR (Priority 1): VIX > 30 → CASH 100%
    2. STRONG BULL (Priority 2): Price > EMA AND MACD_Line > Signal_Line → TQQQ 2.5% risk
    3. WEAK BULL/PAUSE (Priority 3): Price > EMA AND MACD_Line < Signal_Line → QQQ 50% flat
    4. STRONG BEAR (Priority 4): Price < EMA AND MACD_Line < 0 → SQQQ 2.5% risk
    5. CHOP/WEAK BEAR (Priority 5): All other conditions → CASH 100%

    Entry Conditions by Regime:
    - Regime 1 (VIX FEAR): VIX > 30 (overrides all other conditions)
    - Regime 2 (STRONG BULL): Price > 100-EMA AND MACD_Line > Signal_Line
    - Regime 3 (WEAK BULL): Price > 100-EMA AND MACD_Line < Signal_Line
    - Regime 4 (STRONG BEAR): Price < 100-EMA AND MACD_Line < Zero-Line (0)
    - Regime 5 (CHOP): All other (e.g., Price < EMA but MACD > 0)

    Exit Conditions:
    - TQQQ/SQQQ: Regime change OR ATR stop hit
    - QQQ: Regime change ONLY (NO ATR stop)

    Rebalances only on regime changes.
    Stop-Loss: Wide 3.0 ATR from entry for TQQQ/SQQQ (allows trend to breathe).
    """

    def __init__(
        self,
        macd_fast_period: int = 12,
        macd_slow_period: int = 26,
        macd_signal_period: int = 9,
        ema_slow_period: int = 100,
        vix_kill_switch: Decimal = Decimal('30.0'),
        atr_period: int = 14,
        atr_stop_multiplier: Decimal = Decimal('3.0'),
        leveraged_risk: Decimal = Decimal('0.025'),
        qqq_allocation: Decimal = Decimal('0.50'),
    ):
        """
        Initialize All-Weather strategy.

        Args:
            macd_fast_period: Period for fast MACD EMA (default: 12)
            macd_slow_period: Period for slow MACD EMA (default: 26)
            macd_signal_period: Period for MACD signal line (default: 9)
            ema_slow_period: Period for slow trend EMA (default: 100)
            vix_kill_switch: VIX level that triggers risk-off (default: 30.0)
            atr_period: Period for ATR calculation (default: 14)
            atr_stop_multiplier: Stop-loss distance in ATR units (default: 3.0)
            leveraged_risk: Portfolio risk for TQQQ/SQQQ trades (default: 2.5%)
            qqq_allocation: Flat allocation for QQQ trades (default: 50%)
        """
        super().__init__()
        self.macd_fast_period = macd_fast_period
        self.macd_slow_period = macd_slow_period
        self.macd_signal_period = macd_signal_period
        self.ema_slow_period = ema_slow_period
        self.vix_kill_switch = vix_kill_switch
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.leveraged_risk = leveraged_risk
        self.qqq_allocation = qqq_allocation

        # Trading symbols (4 symbols: signal + filter + 3 vehicles)
        self.signal_symbol = 'QQQ'    # Calculate indicators on QQQ (also trades QQQ)
        self.vix_symbol = '$VIX'      # Volatility filter (index symbols use $ prefix)
        self.bull_symbol = 'TQQQ'     # 3x leveraged long
        self.defensive_symbol = 'QQQ'  # 1x defensive (same as signal)
        self.bear_symbol = 'SQQQ'     # 3x leveraged inverse

        # State tracking
        self.previous_regime: Optional[int] = None  # Track regime (1-5)
        self.qqq_position_regime: Optional[int] = None  # Track which regime opened QQQ
        self.current_position_symbol: Optional[str] = None  # TQQQ or SQQQ (NOT QQQ)
        self.entry_price: Optional[Decimal] = None
        self.stop_loss_price: Optional[Decimal] = None
        self._symbols_validated: bool = False  # Track if symbol validation completed

    def init(self):
        """Initialize strategy state."""
        self.previous_regime = None
        self.qqq_position_regime = None
        self.current_position_symbol = None
        self.entry_price = None
        self.stop_loss_price = None
        self._symbols_validated = False

    def _validate_required_symbols(self) -> None:
        """
        Validate that all required symbols are present in data handler.

        This method checks that all 4 required symbols (QQQ, $VIX, TQQQ, SQQQ)
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
            self.vix_symbol,     # $VIX - volatility filter
            self.bull_symbol,    # TQQQ - leveraged long
            self.bear_symbol,    # SQQQ - leveraged inverse
        ]

        # Get unique symbols from loaded bars
        available_symbols = list(set(bar.symbol for bar in self._bars))

        # Check for missing symbols
        missing_symbols = [s for s in required_symbols if s not in available_symbols]

        if missing_symbols:
            raise ValueError(
                f"MACD_Trend_v2 requires symbols {required_symbols} but "
                f"missing: {missing_symbols}. Available symbols: {available_symbols}. "
                f"Please include all required symbols in your backtest command."
            )

    def on_bar(self, bar):
        """
        Process each bar and generate signals based on regime.

        Processes:
        - QQQ bars: Regime detection (MACD, EMA, VIX evaluation)
        - TQQQ/SQQQ bars: Stop-loss checking (ATR stops only)
        - VIX bars: Ignored (read from last bar when evaluating regime)

        Args:
            bar: Market data bar (MarketDataEvent)

        Raises:
            ValueError: If required symbols are missing from loaded data

        Note:
            QQQ position has NO stop-loss checking (regime-managed exit only).
        """
        # Perform symbol validation once we have enough bars
        # Wait until we have enough bars for EMA calculation to ensure all symbols loaded
        lookback = max(self.ema_slow_period, self.atr_period) + 10
        if not self._symbols_validated and len(self._bars) >= lookback:
            self._validate_required_symbols()
            self._symbols_validated = True
            self.log(f"Symbol validation passed: All required symbols present")

        # Check stop-loss on leveraged trading vehicles (TQQQ/SQQQ only, NOT QQQ)
        if bar.symbol in [self.bull_symbol, self.bear_symbol]:
            self._check_stop_loss(bar)
            return

        # Only process QQQ bars for regime calculation
        if bar.symbol != self.signal_symbol:
            return

        # Need enough bars for indicators
        lookback = max(self.ema_slow_period, self.atr_period) + 10
        if len(self._bars) < lookback:
            return

        # Get latest VIX value (from last VIX bar)
        vix_bars = [b for b in self._bars if b.symbol == self.vix_symbol]
        if not vix_bars:
            self.log("WARNING: No VIX data available, cannot evaluate kill switch")
            return

        current_vix = vix_bars[-1].close

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
        ema_slow = ema(closes, period=self.ema_slow_period)

        # Get current values
        current_price = closes.iloc[-1]
        current_ema = Decimal(str(ema_slow.iloc[-1]))
        current_macd_line = Decimal(str(macd_line.iloc[-1]))
        current_signal_line = Decimal(str(signal_line.iloc[-1]))

        # Store current bar and indicator values for context logging
        self._current_bar = bar
        self._last_indicator_values = {
            'Price': current_price,
            'EMA_100': current_ema,
            'MACD_Line': current_macd_line,
            'Signal_Line': current_signal_line,
            'VIX': current_vix
        }
        self._last_threshold_values = {
            'EMA_Period': self.ema_slow_period,
            'VIX_Kill_Switch': self.vix_kill_switch,
            'ATR_Stop_Multiplier': self.atr_stop_multiplier,
            'Leveraged_Risk': self.leveraged_risk,
            'QQQ_Allocation': self.qqq_allocation
        }

        # Build decision reason
        trend_status = f"Price({current_price:.2f}) {'>' if current_price > current_ema else '<='} EMA({current_ema:.2f})"
        momentum_status = f"MACD({current_macd_line:.4f}) {'>' if current_macd_line > current_signal_line else '<='} Signal({current_signal_line:.4f})"
        macd_zero_status = f"MACD {'>' if current_macd_line > Decimal('0.0') else '<='} 0"
        vix_status = f"VIX({current_vix:.2f}) {'>' if current_vix > self.vix_kill_switch else '<='} {self.vix_kill_switch}"
        self._last_decision_reason = f"{trend_status}, {momentum_status}, {macd_zero_status}, {vix_status}"

        # Determine current regime (1-5)
        current_regime = self._determine_regime(
            current_price, current_ema, current_macd_line,
            current_signal_line, current_vix
        )

        # Log indicator calculation
        self.log(
            f"Indicators: {trend_status}, {momentum_status}, {macd_zero_status}, {vix_status} | "
            f"Regime={current_regime} | Bars used={len(closes)}"
        )

        # Handle QQQ regime-managed exit (CRITICAL)
        # QQQ exits on regime change ONLY (NO ATR stop)
        if self.qqq_position_regime is not None and current_regime != self.qqq_position_regime:
            self._exit_qqq()

        # Check if regime changed
        if current_regime != self.previous_regime:
            # Log regime transition
            if self.previous_regime is not None:
                self.log(
                    f"REGIME CHANGE: {self.previous_regime} → {current_regime} | "
                    f"{self._last_decision_reason}"
                )

            # Liquidate all leveraged positions (TQQQ/SQQQ only, NOT QQQ)
            self._liquidate_leveraged_positions()

            # Execute new regime allocation
            self._execute_regime_allocation(current_regime, bar)

            # Update regime tracker
            self.previous_regime = current_regime

    def _determine_regime(
        self,
        price: Decimal,
        ema: Decimal,
        macd_line: Decimal,
        signal_line: Decimal,
        vix: Decimal
    ) -> int:
        """
        Determine current regime (1-5) based on priority order.

        Priority Order (CRITICAL - checked top to bottom):
        1. VIX > 30 → VIX FEAR (CASH)
        2. Price > EMA AND MACD_Line > Signal_Line → STRONG BULL (TQQQ)
        3. Price > EMA AND MACD_Line < Signal_Line → WEAK BULL (QQQ)
        4. Price < EMA AND MACD_Line < 0 → STRONG BEAR (SQQQ)
        5. All other → CHOP (CASH)

        Args:
            price: Current QQQ price
            ema: Current 100-day EMA value
            macd_line: Current MACD line value
            signal_line: Current MACD signal line value
            vix: Current VIX value

        Returns:
            Regime number (1-5)
        """
        # Priority 1: VIX FEAR (overrides everything)
        if vix > self.vix_kill_switch:
            return 1  # VIX FEAR → CASH

        # Priority 2: STRONG BULL
        if price > ema and macd_line > signal_line:
            return 2  # STRONG BULL → TQQQ

        # Priority 3: WEAK BULL/PAUSE (includes MACD == Signal case)
        if price > ema and macd_line <= signal_line:
            return 3  # WEAK BULL → QQQ

        # Priority 4: STRONG BEAR (CRITICAL: MACD zero-line check)
        if price < ema and macd_line < Decimal('0.0'):
            return 4  # STRONG BEAR → SQQQ

        # Priority 5: CHOP/WEAK BEAR (e.g., Price < EMA but MACD > 0)
        return 5  # CHOP → CASH

    def _liquidate_leveraged_positions(self):
        """
        Close leveraged positions (TQQQ and SQQQ ONLY, NOT QQQ).

        QQQ position is managed separately through regime-specific exit logic.

        Logs strategy context BEFORE selling to ensure liquidation trades have context.
        """
        for symbol in [self.bull_symbol, self.bear_symbol]:
            if self.get_position(symbol) > 0:
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

                self.sell(symbol, Decimal('0.0'))  # Close long position
                self.log(f"LIQUIDATE: Closed {symbol} position")

        # Clear stop-loss tracking (leveraged positions only)
        self.current_position_symbol = None
        self.entry_price = None
        self.stop_loss_price = None

    def _exit_qqq(self):
        """
        Exit QQQ position (regime-managed exit, NO ATR stop).

        This method is called when regime changes from 3 (WEAK BULL) to any other regime.
        QQQ has NO stop-loss tracking - exits are purely regime-based.
        """
        if self.get_position(self.defensive_symbol) > 0:
            # Log context BEFORE exit signal
            if self._trade_logger and hasattr(self, '_current_bar'):
                exit_desc = f"Exiting QQQ position (regime change from 3 to {self.previous_regime})"

                self._trade_logger.log_strategy_context(
                    timestamp=self._current_bar.timestamp,
                    symbol=self.defensive_symbol,
                    strategy_state=exit_desc,
                    decision_reason=self._last_decision_reason,
                    indicator_values=self._last_indicator_values,
                    threshold_values=self._last_threshold_values
                )

            self.buy(self.defensive_symbol, Decimal('0.0'))  # Close position (buy with 0% = exit)
            self.log(f"EXIT QQQ: Regime changed from {self.qqq_position_regime} → regime-managed exit")

        # Clear QQQ tracking
        self.qqq_position_regime = None

    def _execute_regime_allocation(self, regime: int, signal_bar):
        """
        Generate signals based on regime with appropriate position sizing.

        Regime Allocations:
        1. VIX FEAR: CASH (no position)
        2. STRONG BULL: TQQQ (2.5% risk, ATR-based)
        3. WEAK BULL: QQQ (50% flat allocation, NO ATR stop)
        4. STRONG BEAR: SQQQ (2.5% risk, ATR-based, INVERSE stop)
        5. CHOP: CASH (no position)

        Args:
            regime: Regime number (1-5)
            signal_bar: Current QQQ bar (for timestamp)
        """
        if regime == 1:
            # VIX FEAR
            self.log(f"REGIME 1: VIX FEAR (VIX > {self.vix_kill_switch}) → CASH 100%")
            return
        elif regime == 2:
            # STRONG BULL → TQQQ (ATR mode)
            self._enter_tqqq(signal_bar)
        elif regime == 3:
            # WEAK BULL → QQQ (Flat mode)
            self._enter_qqq(signal_bar)
        elif regime == 4:
            # STRONG BEAR → SQQQ (ATR mode, INVERSE stop)
            self._enter_sqqq(signal_bar)
        elif regime == 5:
            # CHOP
            self.log(f"REGIME 5: CHOP/WEAK BEAR → CASH 100%")
            return
        else:
            raise ValueError(f"Invalid regime: {regime}")

    def _enter_tqqq(self, signal_bar):
        """
        Enter TQQQ position with ATR-based sizing (2.5% risk).

        Uses ATR-based position sizing:
        - Total_Dollar_Risk = Portfolio_Equity × 2.5%
        - Dollar_Risk_Per_Share = ATR × 3.0
        - Shares = Total_Dollar_Risk / Dollar_Risk_Per_Share
        - Stop_Loss = Fill_Price - Dollar_Risk_Per_Share

        Args:
            signal_bar: Current QQQ bar (for timestamp)
        """
        trade_symbol = self.bull_symbol  # TQQQ
        regime_desc = "STRONG BULL: Price > EMA AND MACD_Line > Signal_Line"

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
        self.entry_price = current_price
        self.stop_loss_price = stop_price

        # Log context BEFORE generating signal
        if self._trade_logger:
            self._trade_logger.log_strategy_context(
                timestamp=signal_bar.timestamp,
                symbol=trade_symbol,
                strategy_state=f"Regime 2: {regime_desc}",
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with ATR-based risk allocation
        # Pass both leveraged_risk (2.5% dollar risk) and dollar_risk_per_share (ATR-based stop)
        # Portfolio will calculate: shares = (portfolio_value × leveraged_risk) / dollar_risk_per_share
        self.buy(trade_symbol, self.leveraged_risk, risk_per_share=dollar_risk_per_share)

        self.log(
            f"REGIME 2: {regime_desc} → {trade_symbol} {self.leveraged_risk*100:.1f}% | "
            f"ATR={current_atr:.2f}, Entry={current_price:.2f}, Stop={stop_price:.2f}"
        )

    def _enter_qqq(self, signal_bar):
        """
        Enter QQQ position with FLAT 50% allocation (NO risk_per_share parameter).

        Uses flat percentage allocation (NOT ATR-based):
        - Allocation = 50% of portfolio value
        - NO ATR calculation
        - NO risk_per_share parameter
        - NO stop-loss tracking
        - Exit is purely regime-managed (regime 3 → any other)

        Args:
            signal_bar: Current QQQ bar (for timestamp)
        """
        trade_symbol = self.defensive_symbol  # QQQ
        regime_desc = "WEAK BULL/PAUSE: Price > EMA AND MACD_Line < Signal_Line"

        # Get current price of QQQ (last bar)
        trade_bars = [b for b in self._bars if b.symbol == trade_symbol]
        current_price = trade_bars[-1].close

        # Track which regime opened this QQQ position
        self.qqq_position_regime = 3  # Regime 3 = WEAK BULL

        # Log context BEFORE generating signal
        if self._trade_logger:
            self._trade_logger.log_strategy_context(
                timestamp=signal_bar.timestamp,
                symbol=trade_symbol,
                strategy_state=f"Regime 3: {regime_desc}",
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with FLAT allocation (NO risk_per_share parameter!)
        # Portfolio will calculate: shares = (portfolio_value × qqq_allocation) / current_price
        self.buy(trade_symbol, self.qqq_allocation)  # NO risk_per_share!

        self.log(
            f"REGIME 3: {regime_desc} → {trade_symbol} {self.qqq_allocation*100:.1f}% | "
            f"Entry={current_price:.2f}, NO ATR STOP (regime-managed exit)"
        )

    def _enter_sqqq(self, signal_bar):
        """
        Enter SQQQ position with ATR-based sizing (2.5% risk, INVERSE stop).

        Uses ATR-based position sizing with INVERSE stop:
        - Total_Dollar_Risk = Portfolio_Equity × 2.5%
        - Dollar_Risk_Per_Share = ATR × 3.0
        - Shares = Total_Dollar_Risk / Dollar_Risk_Per_Share
        - Stop_Loss = Fill_Price + Dollar_Risk_Per_Share (INVERSE!)

        CRITICAL: SQQQ is held LONG but moves INVERSE to market, so stop is ABOVE entry.

        Args:
            signal_bar: Current QQQ bar (for timestamp)
        """
        trade_symbol = self.bear_symbol  # SQQQ
        regime_desc = "STRONG BEAR: Price < EMA AND MACD_Line < 0"

        # Calculate ATR on SQQQ (trade vehicle)
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

        # Get current price of SQQQ (last bar)
        current_price = trade_bars[-1].close

        # Calculate stop-loss price (INVERSE!)
        # For SQQQ (long position, inverse movement): Stop = Entry + Dollar_Risk_Per_Share
        stop_price = current_price + dollar_risk_per_share

        # Store entry and stop-loss for tracking
        self.current_position_symbol = trade_symbol
        self.entry_price = current_price
        self.stop_loss_price = stop_price

        # Log context BEFORE generating signal
        if self._trade_logger:
            self._trade_logger.log_strategy_context(
                timestamp=signal_bar.timestamp,
                symbol=trade_symbol,
                strategy_state=f"Regime 4: {regime_desc}",
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with ATR-based risk allocation
        # Pass both leveraged_risk (2.5% dollar risk) and dollar_risk_per_share (ATR-based stop)
        # Portfolio will calculate: shares = (portfolio_value × leveraged_risk) / dollar_risk_per_share
        self.sell(trade_symbol, self.leveraged_risk, risk_per_share=dollar_risk_per_share)

        self.log(
            f"REGIME 4: {regime_desc} → {trade_symbol} {self.leveraged_risk*100:.1f}% | "
            f"ATR={current_atr:.2f}, Entry={current_price:.2f}, Stop={stop_price:.2f} (INVERSE)"
        )

    def _check_stop_loss(self, bar):
        """
        Check if stop-loss has been hit on current TQQQ or SQQQ position.

        Simplified stop-loss checking (manual, not GTC orders).
        Liquidates position if price breaches stop level.

        CRITICAL: SQQQ has INVERSE stop (stop is ABOVE entry, not below).

        Args:
            bar: TQQQ or SQQQ bar

        Note:
            QQQ positions are NOT checked here (NO ATR stop, regime-managed exit only).
        """
        # Only check if we have an active leveraged position
        if not self.current_position_symbol or bar.symbol != self.current_position_symbol:
            return

        if self.stop_loss_price is None:
            return

        # Check if stop-loss triggered (direction depends on symbol)
        stop_hit = False

        if self.current_position_symbol == self.bull_symbol:
            # TQQQ (long): Stop if price falls below stop level
            if bar.low <= self.stop_loss_price:
                stop_hit = True
        elif self.current_position_symbol == self.bear_symbol:
            # SQQQ (long, inverse): Stop if price rises above stop level
            if bar.high >= self.stop_loss_price:
                stop_hit = True

        if stop_hit:
            self.log(
                f"STOP-LOSS HIT: {self.current_position_symbol} | "
                f"Entry={self.entry_price:.2f}, Stop={self.stop_loss_price:.2f}, "
                f"Current={bar.close:.2f}"
            )

            # Log context for stop-loss exit
            if self._trade_logger:
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=self.current_position_symbol,
                    strategy_state="Stop-Loss Triggered",
                    decision_reason=f"Price breached stop at {self.stop_loss_price:.2f}",
                    indicator_values=self._last_indicator_values if hasattr(self, '_last_indicator_values') else {},
                    threshold_values=self._last_threshold_values if hasattr(self, '_last_threshold_values') else {}
                )

            # Liquidate position (use sell for both TQQQ and SQQQ since both are long positions)
            if self.current_position_symbol == self.bull_symbol:
                self.sell(self.current_position_symbol, Decimal('0.0'))
            else:  # bear_symbol
                self.buy(self.current_position_symbol, Decimal('0.0'))  # Close short by buying back

            # Clear tracking
            self.current_position_symbol = None
            self.entry_price = None
            self.stop_loss_price = None
            self.previous_regime = None  # Force regime re-evaluation on next QQQ bar
