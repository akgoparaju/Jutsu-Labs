"""
Momentum-ATR Strategy (V4.0): Risk-managed regime trading using MACD and VIX.

This strategy trades TQQQ/SQQQ based on QQQ momentum (MACD) and VIX volatility filter,
with ATR-based position sizing and simplified stop-loss management.

Strategy Logic:
- Calculates MACD on QQQ data only (signal asset)
- Monitors VIX for kill switch (>30 = Risk-Off → CASH)
- Trades TQQQ (3x bull), SQQQ (3x bear), or CASH based on 6 regimes
- ATR-based position sizing (3.0% or 1.5% portfolio risk)
- Simplified stop-loss checking (manual tracking, no GTC orders)
Sample command: jutsu backtest --strategy Momentum_ATR --symbols QQQ,VIX,TQQQ,SQQQ --timeframe 1D --start 2011-01-01 --end 2025-11-01
More Info: Strategy Specification_ Momentum-ATR (V4.0).md
"""
from decimal import Decimal
from typing import Optional, Dict
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import macd, atr


class Momentum_ATR(Strategy):
    """
    Momentum-ATR Strategy: Regime-based allocation using QQQ MACD signals and VIX filter.

    Trades TQQQ (3x bull), SQQQ (3x bear), or CASH based on:
    - Momentum: MACD Histogram and Histogram Delta
    - Volatility Filter: VIX Kill Switch (>30 → CASH)
    - Position Sizing: ATR-based risk management

    6 regimes with specific allocations:
    1. Risk-Off / Kill-Switch (VIX > 30): CASH 100%
    2. Strong Bull (VIX ≤ 30, Histogram > 0, Delta > 0): TQQQ 3.0% risk
    3. Waning Bull (VIX ≤ 30, Histogram > 0, Delta ≤ 0): TQQQ 1.5% risk
    4. Strong Bear (VIX ≤ 30, Histogram < 0, Delta < 0): SQQQ 3.0% risk
    5. Waning Bear (VIX ≤ 30, Histogram < 0, Delta ≥ 0): SQQQ 1.5% risk
    6. Neutral / Flat (Other conditions): CASH 100%

    Rebalances only on regime changes.
    Stop-Loss: Simplified manual checking (not GTC orders) at 2-ATR from entry.
    """

    def __init__(
        self,
        macd_fast_period: int = 12,
        macd_slow_period: int = 26,
        macd_signal_period: int = 9,
        vix_kill_switch: Decimal = Decimal('30.0'),
        atr_period: int = 14,
        atr_stop_multiplier: Decimal = Decimal('2.0'),
        risk_strong_trend: Decimal = Decimal('0.03'),
        risk_waning_trend: Decimal = Decimal('0.015'),
    ):
        """
        Initialize Momentum-ATR strategy.

        Args:
            macd_fast_period: Period for fast MACD EMA (default: 12)
            macd_slow_period: Period for slow MACD EMA (default: 26)
            macd_signal_period: Period for MACD signal line (default: 9)
            vix_kill_switch: VIX level that triggers risk-off (default: 30.0)
            atr_period: Period for ATR calculation (default: 14)
            atr_stop_multiplier: Stop-loss distance in ATR units (default: 2.0)
            risk_strong_trend: Portfolio risk for strong trends (default: 3.0%)
            risk_waning_trend: Portfolio risk for waning trends (default: 1.5%)
        """
        super().__init__()
        self.macd_fast_period = macd_fast_period
        self.macd_slow_period = macd_slow_period
        self.macd_signal_period = macd_signal_period
        self.vix_kill_switch = vix_kill_switch
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_strong_trend = risk_strong_trend
        self.risk_waning_trend = risk_waning_trend

        # Trading symbols
        self.signal_symbol = 'QQQ'    # Calculate MACD on QQQ
        self.vix_symbol = '$VIX'      # Volatility filter (index symbols use $ prefix)
        self.bull_symbol = 'TQQQ'     # 3x leveraged long
        self.bear_symbol = 'SQQQ'     # 3x leveraged inverse

        # State tracking
        self.previous_regime: Optional[int] = None
        self.previous_histogram: Optional[Decimal] = None
        self.current_position_symbol: Optional[str] = None
        self.entry_price: Optional[Decimal] = None
        self.stop_loss_price: Optional[Decimal] = None
        self._symbols_validated: bool = False  # Track if symbol validation completed

    def init(self):
        """Initialize strategy state."""
        self.previous_regime = None
        self.previous_histogram = None
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
            self.signal_symbol,  # QQQ - momentum signal
            self.vix_symbol,     # $VIX - volatility filter
            self.bull_symbol,    # TQQQ - leveraged long
            self.bear_symbol     # SQQQ - leveraged short
        ]

        # Get unique symbols from loaded bars
        available_symbols = list(set(bar.symbol for bar in self._bars))

        # Check for missing symbols
        missing_symbols = [s for s in required_symbols if s not in available_symbols]

        if missing_symbols:
            raise ValueError(
                f"Momentum_ATR requires symbols {required_symbols} but "
                f"missing: {missing_symbols}. Available symbols: {available_symbols}. "
                f"Please include all required symbols in your backtest command."
            )

    def on_bar(self, bar):
        """
        Process each bar and generate signals based on regime.

        Processes:
        - QQQ bars: Regime detection (MACD calculation)
        - VIX bars: Volatility filter
        - TQQQ/SQQQ bars: Stop-loss checking

        Args:
            bar: Market data bar (MarketDataEvent)

        Raises:
            ValueError: If required symbols are missing from loaded data
        """
        # Perform symbol validation once we have enough bars
        # Wait until we have enough bars for MACD calculation to ensure all symbols loaded
        lookback = max(self.macd_slow_period, self.atr_period) + 10
        if not self._symbols_validated and len(self._bars) >= lookback:
            self._validate_required_symbols()
            self._symbols_validated = True
            self.log(f"Symbol validation passed: All required symbols present")

        # Check stop-loss on trading vehicle bars
        if bar.symbol in [self.bull_symbol, self.bear_symbol]:
            self._check_stop_loss(bar)
            return

        # Only process QQQ bars for regime calculation
        if bar.symbol != self.signal_symbol:
            return

        # Need enough bars for indicators
        lookback = max(self.macd_slow_period, self.atr_period) + 10
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

        # Get current MACD values
        current_histogram = Decimal(str(histogram.iloc[-1]))

        # Calculate Histogram Delta (current - previous)
        if self.previous_histogram is not None:
            histogram_delta = current_histogram - self.previous_histogram
        else:
            # First calculation - assume delta is 0
            histogram_delta = Decimal('0.0')

        # Store current bar and indicator values for context logging
        self._current_bar = bar
        self._last_indicator_values = {
            'MACD_Line': Decimal(str(macd_line.iloc[-1])),
            'Signal_Line': Decimal(str(signal_line.iloc[-1])),
            'Histogram': current_histogram,
            'Histogram_Delta': histogram_delta,
            'VIX': current_vix
        }
        self._last_threshold_values = {
            'VIX_Kill_Switch': self.vix_kill_switch,
            'ATR_Stop_Multiplier': self.atr_stop_multiplier,
            'Risk_Strong_Trend': self.risk_strong_trend,
            'Risk_Waning_Trend': self.risk_waning_trend
        }

        # Build decision reason
        macd_position = f"Histogram={current_histogram:.4f}, Delta={histogram_delta:.4f}"
        vix_position = f"VIX={current_vix:.2f}"
        self._last_decision_reason = f"{macd_position}, {vix_position}"

        # Determine current regime (1-6)
        current_regime = self._determine_regime(
            current_vix, current_histogram, histogram_delta
        )

        # Log indicator calculation
        self.log(
            f"Indicators: {macd_position}, {vix_position} | "
            f"Regime={current_regime} | Bars used={len(closes)}"
        )

        # Check if regime changed
        if current_regime != self.previous_regime:
            # Log regime transition
            if self.previous_regime is not None:
                self.log(
                    f"REGIME CHANGE: {self.previous_regime} → {current_regime} | "
                    f"{self._last_decision_reason}"
                )

            # Liquidate all positions
            self._liquidate_all_positions()

            # Execute new regime allocation
            self._execute_regime_allocation(current_regime, bar)

            # Update regime tracker
            self.previous_regime = current_regime

        # Update histogram for next bar's delta calculation
        self.previous_histogram = current_histogram

    def _determine_regime(
        self,
        vix: Decimal,
        histogram: Decimal,
        histogram_delta: Decimal
    ) -> int:
        """
        Determine current regime (1-6) based on VIX and MACD signals.

        Regime Priority (checked in order):
        1. VIX > 30 → Risk-Off (CASH)
        2. VIX ≤ 30, Histogram > 0, Delta > 0 → Strong Bull (TQQQ 3.0%)
        3. VIX ≤ 30, Histogram > 0, Delta ≤ 0 → Waning Bull (TQQQ 1.5%)
        4. VIX ≤ 30, Histogram < 0, Delta < 0 → Strong Bear (SQQQ 3.0%)
        5. VIX ≤ 30, Histogram < 0, Delta ≥ 0 → Waning Bear (SQQQ 1.5%)
        6. Other → Neutral (CASH)

        Args:
            vix: Current VIX value
            histogram: Current MACD histogram
            histogram_delta: Change in histogram (current - previous)

        Returns:
            Regime number (1-6)
        """
        # Priority 1: VIX Kill Switch
        if vix > self.vix_kill_switch:
            return 1  # Risk-Off / Kill-Switch → CASH

        # Priority 2-3: Bullish regimes (Histogram > 0)
        if histogram > 0:
            if histogram_delta > 0:
                return 2  # Strong Bull → TQQQ 3.0%
            else:
                return 3  # Waning Bull → TQQQ 1.5%

        # Priority 4-5: Bearish regimes (Histogram < 0)
        if histogram < 0:
            if histogram_delta < 0:
                return 4  # Strong Bear → SQQQ 3.0%
            else:
                return 5  # Waning Bear → SQQQ 1.5%

        # Priority 6: Neutral (Histogram = 0 or other edge case)
        return 6  # Neutral / Flat → CASH

    def _liquidate_all_positions(self):
        """
        Close all positions in TQQQ and SQQQ.

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

        # Clear stop-loss tracking
        self.current_position_symbol = None
        self.entry_price = None
        self.stop_loss_price = None

    def _execute_regime_allocation(self, regime: int, signal_bar):
        """
        Generate signals based on regime with ATR-based position sizing.

        Regime Allocations:
        1. Risk-Off: CASH (no position)
        2. Strong Bull: TQQQ (3.0% risk)
        3. Waning Bull: TQQQ (1.5% risk)
        4. Strong Bear: SQQQ (3.0% risk)
        5. Waning Bear: SQQQ (1.5% risk)
        6. Neutral: CASH (no position)

        Args:
            regime: Regime number (1-6)
            signal_bar: Current QQQ bar (for timestamp)
        """
        # Determine trade symbol, risk level, and regime description
        if regime == 1:
            # Risk-Off / Kill-Switch
            self.log(f"REGIME 1: Risk-Off (VIX > {self.vix_kill_switch}) → CASH 100%")
            return
        elif regime == 2:
            trade_symbol = self.bull_symbol  # TQQQ
            risk_percent = self.risk_strong_trend  # 3.0%
            regime_desc = f"Strong Bull (Histogram > 0, Delta > 0)"
        elif regime == 3:
            trade_symbol = self.bull_symbol  # TQQQ
            risk_percent = self.risk_waning_trend  # 1.5%
            regime_desc = f"Waning Bull (Histogram > 0, Delta ≤ 0)"
        elif regime == 4:
            trade_symbol = self.bear_symbol  # SQQQ
            risk_percent = self.risk_strong_trend  # 3.0%
            regime_desc = f"Strong Bear (Histogram < 0, Delta < 0)"
        elif regime == 5:
            trade_symbol = self.bear_symbol  # SQQQ
            risk_percent = self.risk_waning_trend  # 1.5%
            regime_desc = f"Waning Bear (Histogram < 0, Delta ≥ 0)"
        elif regime == 6:
            # Neutral / Flat
            self.log(f"REGIME 6: Neutral / Flat → CASH 100%")
            return
        else:
            raise ValueError(f"Invalid regime: {regime}")

        # Calculate ATR on the trade vehicle (TQQQ or SQQQ)
        # Need to get TQQQ/SQQQ bars for ATR calculation
        trade_bars = [b for b in self._bars if b.symbol == trade_symbol]
        if len(trade_bars) < self.atr_period:
            self.log(f"WARNING: Insufficient {trade_symbol} bars for ATR calculation ({len(trade_bars)} < {self.atr_period})")
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

        # Total_Dollar_Risk = Portfolio_Equity × Risk_To_Apply
        # Note: Portfolio equity will be calculated by portfolio module
        # We just pass the risk percentage to buy() method

        # Get current price of trade vehicle (last bar)
        current_price = trade_bars[-1].close

        # Calculate stop-loss price
        # For TQQQ (long): Stop = Entry - Dollar_Risk_Per_Share
        # For SQQQ (long): Stop = Entry + Dollar_Risk_Per_Share
        # Note: Both TQQQ and SQQQ are held as long positions, but they move inversely to market
        if trade_symbol == self.bull_symbol:
            stop_price = current_price - dollar_risk_per_share
        else:  # bear_symbol (SQQQ)
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
                strategy_state=f"Regime {regime}: {regime_desc}",
                decision_reason=self._last_decision_reason,
                indicator_values=self._last_indicator_values,
                threshold_values=self._last_threshold_values
            )

        # Generate signal with ATR-based risk allocation
        # Pass both risk_percent (dollar risk as % of portfolio) and dollar_risk_per_share (ATR-based stop distance)
        # Portfolio will calculate: shares = (portfolio_value × risk_percent) / dollar_risk_per_share
        self.buy(trade_symbol, risk_percent, risk_per_share=dollar_risk_per_share)

        self.log(
            f"REGIME {regime}: {regime_desc} → {trade_symbol} {risk_percent*100:.1f}% | "
            f"ATR={current_atr:.2f}, Entry={current_price:.2f}, Stop={stop_price:.2f}"
        )

    def _check_stop_loss(self, bar):
        """
        Check if stop-loss has been hit on current position.

        Simplified stop-loss checking (manual, not GTC orders).
        Liquidates position if price breaches stop level.

        Args:
            bar: TQQQ or SQQQ bar
        """
        # Only check if we have an active position
        if not self.current_position_symbol or bar.symbol != self.current_position_symbol:
            return

        if self.stop_loss_price is None:
            return

        # Check if stop-loss triggered
        stop_hit = False

        if self.current_position_symbol == self.bull_symbol:
            # TQQQ (long): Stop if price falls below stop level
            if bar.low <= self.stop_loss_price:
                stop_hit = True
        else:  # bear_symbol (SQQQ)
            # SQQQ (long): Stop if price rises above stop level
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

            # Liquidate position
            self.sell(self.current_position_symbol, Decimal('0.0'))

            # Clear tracking
            self.current_position_symbol = None
            self.entry_price = None
            self.stop_loss_price = None
            self.previous_regime = None  # Force regime re-evaluation on next QQQ bar
