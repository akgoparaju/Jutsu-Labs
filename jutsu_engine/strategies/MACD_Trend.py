"""
MACD-Trend Strategy (V5.0): Conservative trend-following using QQQ signals.

This strategy trades TQQQ based on QQQ MACD, 100-day EMA trend filter, and VIX volatility,
with ATR-based position sizing and wide stop-loss management.

Strategy Logic:
- Calculates MACD on QQQ data only (signal asset)
- Monitors 100-day EMA for primary trend direction
- Monitors VIX for kill switch (>30 = Risk-Off → CASH)
- Trades TQQQ (3x bull) or CASH based on 2 states (IN or OUT)
- ATR-based position sizing (2.5% fixed portfolio risk)
- Wide 3.0 ATR stop-loss (allows trend to "breathe")
More Info: Strategy Specification_ MACD-Trend (V5.0).md
"""
from decimal import Decimal
from typing import Optional
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import macd, ema, atr


class MACD_Trend(Strategy):
    """
    MACD-Trend Strategy: Conservative trend-following using QQQ signals.

    Trades TQQQ (3x bull) or CASH based on:
    - Main Trend: 100-day EMA (Price > EMA = Up)
    - Momentum: MACD Line vs Signal Line
    - Volatility Filter: VIX Kill Switch (>30 → CASH)
    - Position Sizing: ATR-based risk management (2.5% fixed)

    2 states with specific allocations:
    1. IN (All 3 conditions met): TQQQ 2.5% risk
    2. OUT (Any 1 condition fails): CASH 100%

    Entry Conditions (ALL 3 required):
    - Price > 100-day EMA (main trend is up)
    - MACD_Line > Signal_Line (momentum is bullish)
    - VIX <= 30 (market is calm)

    Exit Conditions (ANY 1 triggers):
    - Price < 100-day EMA (main trend fails)
    - MACD_Line < Signal_Line (momentum fails)
    - VIX > 30 (market fear spikes)

    Rebalances only on state changes.
    Stop-Loss: Wide 3.0 ATR from entry (allows trend to breathe).
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
        risk_per_trade: Decimal = Decimal('0.025'),
    ):
        """
        Initialize MACD-Trend strategy.

        Args:
            macd_fast_period: Period for fast MACD EMA (default: 12)
            macd_slow_period: Period for slow MACD EMA (default: 26)
            macd_signal_period: Period for MACD signal line (default: 9)
            ema_slow_period: Period for slow trend EMA (default: 100)
            vix_kill_switch: VIX level that triggers risk-off (default: 30.0)
            atr_period: Period for ATR calculation (default: 14)
            atr_stop_multiplier: Stop-loss distance in ATR units (default: 3.0)
            risk_per_trade: Fixed portfolio risk per trade (default: 2.5%)
        """
        super().__init__()
        self.macd_fast_period = macd_fast_period
        self.macd_slow_period = macd_slow_period
        self.macd_signal_period = macd_signal_period
        self.ema_slow_period = ema_slow_period
        self.vix_kill_switch = vix_kill_switch
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_per_trade = risk_per_trade

        # Trading symbols (3 symbols, not 4 like Momentum_ATR)
        self.signal_symbol = 'QQQ'    # Calculate indicators on QQQ
        self.vix_symbol = '$VIX'      # Volatility filter (index symbols use $ prefix)
        self.bull_symbol = 'TQQQ'     # 3x leveraged long
        # NO bear_symbol - long-only strategy

        # State tracking (simpler than Momentum_ATR)
        self.previous_state: Optional[str] = None  # 'IN' or 'OUT'
        self.current_position_symbol: Optional[str] = None
        self.entry_price: Optional[Decimal] = None
        self.stop_loss_price: Optional[Decimal] = None
        self._symbols_validated: bool = False  # Track if symbol validation completed

    def init(self):
        """Initialize strategy state."""
        self.previous_state = None
        self.current_position_symbol = None
        self.entry_price = None
        self.stop_loss_price = None
        self._symbols_validated = False

    def _validate_required_symbols(self) -> None:
        """
        Validate that all required symbols are present in data handler.

        This method checks that all 3 required symbols (QQQ, $VIX, TQQQ)
        are available in the loaded market data. If any symbols are missing,
        it raises a ValueError with a clear, actionable error message.

        Raises:
            ValueError: If any required symbol is missing from available symbols

        Note:
            This validation runs lazily on the first on_bar() call once enough
            bars are available, since symbols aren't known at __init__ time.
        """
        required_symbols = [
            self.signal_symbol,  # QQQ - signal calculations
            self.vix_symbol,     # $VIX - volatility filter
            self.bull_symbol,    # TQQQ - leveraged long
        ]

        # Get unique symbols from loaded bars
        available_symbols = list(set(bar.symbol for bar in self._bars))

        # Check for missing symbols
        missing_symbols = [s for s in required_symbols if s not in available_symbols]

        if missing_symbols:
            raise ValueError(
                f"MACD_Trend requires symbols {required_symbols} but "
                f"missing: {missing_symbols}. Available symbols: {available_symbols}. "
                f"Please include all required symbols in your backtest command."
            )

    def on_bar(self, bar):
        """
        Process each bar and generate signals based on state.

        Processes:
        - QQQ bars: State detection (MACD, EMA, VIX evaluation)
        - TQQQ bars: Stop-loss checking
        - VIX bars: Ignored (read from last bar when evaluating state)

        Args:
            bar: Market data bar (MarketDataEvent)

        Raises:
            ValueError: If required symbols are missing from loaded data
        """
        # Perform symbol validation once we have enough bars
        # Wait until we have enough bars for EMA calculation to ensure all symbols loaded
        lookback = max(self.ema_slow_period, self.atr_period) + 10
        if not self._symbols_validated and len(self._bars) >= lookback:
            self._validate_required_symbols()
            self._symbols_validated = True
            self.log(f"Symbol validation passed: All required symbols present")

        # Check stop-loss on TQQQ bars
        if bar.symbol == self.bull_symbol:
            self._check_stop_loss(bar)
            return

        # Only process QQQ bars for state calculation
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
            'Risk_Per_Trade': self.risk_per_trade
        }

        # Build decision reason
        trend_status = f"Price({current_price:.2f}) {'>' if current_price > current_ema else '<='} EMA({current_ema:.2f})"
        momentum_status = f"MACD({current_macd_line:.4f}) {'>' if current_macd_line > current_signal_line else '<='} Signal({current_signal_line:.4f})"
        vix_status = f"VIX({current_vix:.2f}) {'<=' if current_vix <= self.vix_kill_switch else '>'} {self.vix_kill_switch}"
        self._last_decision_reason = f"{trend_status}, {momentum_status}, {vix_status}"

        # Determine current state (IN or OUT)
        current_state = self._determine_state(
            current_price, current_ema, current_macd_line,
            current_signal_line, current_vix
        )

        # Log indicator calculation
        self.log(
            f"Indicators: {trend_status}, {momentum_status}, {vix_status} | "
            f"State={current_state} | Bars used={len(closes)}"
        )

        # Check if state changed
        if current_state != self.previous_state:
            # Log state transition
            if self.previous_state is not None:
                self.log(
                    f"STATE CHANGE: {self.previous_state} → {current_state} | "
                    f"{self._last_decision_reason}"
                )

            # Liquidate all positions
            self._liquidate_all_positions()

            # Execute new state allocation
            if current_state == 'IN':
                self._execute_entry(bar)
            # else: state is 'OUT', stay in CASH

            # Update state tracker
            self.previous_state = current_state

    def _determine_state(
        self,
        price: Decimal,
        ema: Decimal,
        macd_line: Decimal,
        signal_line: Decimal,
        vix: Decimal
    ) -> str:
        """
        Determine current state (IN or OUT).

        IN: ALL 3 conditions met
        - Price > 100-day EMA (main trend is up)
        - MACD_Line > Signal_Line (momentum is bullish)
        - VIX <= 30 (market is calm)

        OUT: ANY 1 condition fails

        Args:
            price: Current QQQ price
            ema: Current 100-day EMA value
            macd_line: Current MACD line value
            signal_line: Current MACD signal line value
            vix: Current VIX value

        Returns:
            'IN' or 'OUT'
        """
        # Check all entry conditions
        trend_is_up = price > ema
        momentum_is_bullish = macd_line > signal_line
        market_is_calm = vix <= self.vix_kill_switch

        # ALL 3 conditions must be met for IN state
        if trend_is_up and momentum_is_bullish and market_is_calm:
            return 'IN'
        else:
            return 'OUT'

    def _liquidate_all_positions(self):
        """
        Close all positions in TQQQ.

        Logs strategy context BEFORE selling to ensure liquidation trades have context.
        """
        if self.get_position(self.bull_symbol) > 0:
            # Log context BEFORE liquidation signal
            if self._trade_logger and hasattr(self, '_current_bar'):
                state_desc = f"Liquidating {self.bull_symbol} position (state change)"

                self._trade_logger.log_strategy_context(
                    timestamp=self._current_bar.timestamp,
                    symbol=self.bull_symbol,
                    strategy_state=state_desc,
                    decision_reason=self._last_decision_reason,
                    indicator_values=self._last_indicator_values,
                    threshold_values=self._last_threshold_values
                )

            self.sell(self.bull_symbol, Decimal('0.0'))  # Close long position
            self.log(f"LIQUIDATE: Closed {self.bull_symbol} position")

        # Clear stop-loss tracking
        self.current_position_symbol = None
        self.entry_price = None
        self.stop_loss_price = None

    def _execute_entry(self, signal_bar):
        """
        Generate entry signal for TQQQ with ATR-based position sizing.

        Entry Allocation:
        - TQQQ with 2.5% fixed risk
        - Uses 3.0 ATR stop-loss

        Args:
            signal_bar: Current QQQ bar (for timestamp)
        """
        trade_symbol = self.bull_symbol  # TQQQ
        state_desc = "IN: Price > EMA AND MACD bullish AND VIX calm"

        # Calculate ATR on TQQQ (trade vehicle, not signal asset)
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

        # Calculate position size based on ATR risk (2025-11-06 fix)
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
                strategy_state=state_desc,
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with ATR-based risk allocation (2025-11-06 fix)
        # Pass both risk_per_trade (2.5% dollar risk) and dollar_risk_per_share (ATR-based stop)
        # Portfolio will calculate: shares = (portfolio_value × risk_per_trade) / dollar_risk_per_share
        self.buy(trade_symbol, self.risk_per_trade, risk_per_share=dollar_risk_per_share)

        self.log(
            f"IN: {state_desc} → {trade_symbol} {self.risk_per_trade*100:.1f}% | "
            f"ATR={current_atr:.2f}, Entry={current_price:.2f}, Stop={stop_price:.2f}"
        )

    def _check_stop_loss(self, bar):
        """
        Check if stop-loss has been hit on current TQQQ position.

        Simplified stop-loss checking (manual, not GTC orders).
        Liquidates position if price breaches stop level.

        Args:
            bar: TQQQ bar
        """
        # Only check if we have an active position
        if not self.current_position_symbol or bar.symbol != self.current_position_symbol:
            return

        if self.stop_loss_price is None:
            return

        # Check if stop-loss triggered (TQQQ long: stop if price falls below)
        if bar.low <= self.stop_loss_price:
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

            # Liquidate position
            self.sell(self.current_position_symbol, Decimal('0.0'))

            # Clear tracking
            self.current_position_symbol = None
            self.entry_price = None
            self.stop_loss_price = None
            self.previous_state = None  # Force state re-evaluation on next QQQ bar
