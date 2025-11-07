"""
ADX-Trend Strategy: Regime-based allocation using QQQ trend signals.

This strategy trades QQQ-based leveraged ETFs (TQQQ, SQQQ) based on trend
direction and strength indicators calculated on QQQ data.

Strategy Logic:
- Calculates indicators on QQQ data only (signal asset)
- Trades TQQQ (3x bull), SQQQ (3x bear), QQQ (1x), or CASH based on regime
- 6 distinct regimes determined by EMA crossovers and ADX thresholds
- Rebalances only on regime changes (no intra-regime adjustments)
"""
from decimal import Decimal
from typing import Optional
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import ema, adx


class ADX_Trend(Strategy):
    """
    ADX-Trend Strategy: Regime-based allocation using QQQ trend signals.

    Trades TQQQ (3x bull), SQQQ (3x bear), or QQQ (1x) based on:
    - Trend direction: EMA(20) vs EMA(50)
    - Trend strength: ADX(14) thresholds

    6 regimes with specific allocations:
    1. Strong Bullish (ADX > 25, EMA_fast > EMA_slow): TQQQ 60%
    2. Building Bullish (20 < ADX <= 25, EMA_fast > EMA_slow): TQQQ 30%
    3. Strong Bearish (ADX > 25, EMA_fast < EMA_slow): SQQQ 60%
    4. Building Bearish (20 < ADX <= 25, EMA_fast < EMA_slow): SQQQ 30%
    5. Weak Bullish (ADX <= 20, EMA_fast > EMA_slow): QQQ 50%
    6. Weak Bearish (ADX <= 20, EMA_fast < EMA_slow): 100% CASH

    Rebalances only on regime changes.
    """

    def __init__(
        self,
        ema_fast_period: int = 20,
        ema_slow_period: int = 50,
        adx_period: int = 14,
        adx_threshold_low: Decimal = Decimal('20'),
        adx_threshold_high: Decimal = Decimal('25')
    ):
        """
        Initialize ADX-Trend strategy.

        Args:
            ema_fast_period: Period for fast EMA (default: 20)
            ema_slow_period: Period for slow EMA (default: 50)
            adx_period: Period for ADX calculation (default: 14)
            adx_threshold_low: ADX threshold for weak trend (default: 20)
            adx_threshold_high: ADX threshold for strong trend (default: 25)
        """
        super().__init__()
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.adx_period = adx_period
        self.adx_threshold_low = adx_threshold_low
        self.adx_threshold_high = adx_threshold_high

        # Trading symbols
        self.signal_symbol = 'QQQ'  # Calculate indicators on QQQ
        self.bull_symbol = 'TQQQ'   # 3x leveraged long
        self.bear_symbol = 'SQQQ'   # 3x leveraged inverse
        self.neutral_symbol = 'QQQ' # 1x tracking

        # Track previous regime
        self.previous_regime: Optional[int] = None

    def init(self):
        """Initialize strategy state."""
        self.previous_regime = None

    def on_bar(self, bar):
        """
        Process each bar and generate signals based on regime.

        Only processes QQQ bars for regime detection. Ignores TQQQ/SQQQ bars.
        Regime changes trigger complete portfolio rebalancing.

        Args:
            bar: Market data bar (MarketDataEvent)
        """
        # Only process QQQ bars for regime calculation
        if bar.symbol != self.signal_symbol:
            return

        # Need enough bars for indicators
        lookback = max(self.ema_slow_period, self.adx_period) + 10
        if len(self._bars) < lookback:
            return

        # Get historical data for QQQ ONLY (filter out TQQQ/SQQQ bars)
        closes = self.get_closes(lookback=lookback, symbol=self.signal_symbol)
        highs = self.get_highs(lookback=lookback, symbol=self.signal_symbol)
        lows = self.get_lows(lookback=lookback, symbol=self.signal_symbol)

        # Calculate indicators on QQQ data
        ema_fast_series = ema(closes, period=self.ema_fast_period)
        ema_slow_series = ema(closes, period=self.ema_slow_period)
        adx_series = adx(highs, lows, closes, period=self.adx_period)

        # Get current indicator values
        ema_fast_val = Decimal(str(ema_fast_series.iloc[-1]))
        ema_slow_val = Decimal(str(ema_slow_series.iloc[-1]))
        adx_val = Decimal(str(adx_series.iloc[-1]))

        # Store current bar and indicator values for context logging later
        self._current_bar = bar
        self._last_indicator_values = {
            'EMA_fast': ema_fast_val,
            'EMA_slow': ema_slow_val,
            'ADX': adx_val
        }
        self._last_threshold_values = {
            'adx_threshold_low': self.adx_threshold_low,
            'adx_threshold_high': self.adx_threshold_high
        }

        # Build decision reason
        ema_position = "EMA_fast > EMA_slow" if ema_fast_val > ema_slow_val else "EMA_fast < EMA_slow"
        if adx_val > self.adx_threshold_high:
            adx_level = "Strong"
        elif adx_val > self.adx_threshold_low:
            adx_level = "Building"
        else:
            adx_level = "Weak"
        self._last_decision_reason = f"{ema_position}, ADX={adx_val:.2f} ({adx_level} trend)"

        # Determine current regime (1-6)
        current_regime = self._determine_regime(ema_fast_val, ema_slow_val, adx_val)

        # Log indicator calculation (for debugging)
        self.log(
            f"Indicators: EMA_fast={ema_fast_val:.2f}, EMA_slow={ema_slow_val:.2f}, "
            f"ADX={adx_val:.2f} | Regime={current_regime} | Bars used={len(closes)}"
        )

        # Check if regime changed
        if current_regime != self.previous_regime:
            # Log regime transition
            if self.previous_regime is not None:
                self.log(
                    f"REGIME CHANGE: {self.previous_regime} → {current_regime} | "
                    f"EMA_fast={ema_fast_val:.2f}, EMA_slow={ema_slow_val:.2f}, ADX={adx_val:.2f}"
                )

            # Liquidate all positions
            self._liquidate_all_positions()

            # Execute new regime allocation (now logs context internally with correct trade symbol)
            self._execute_regime_allocation(current_regime)

            # Update regime tracker
            self.previous_regime = current_regime

    def _determine_regime(
        self,
        ema_fast_val: Decimal,
        ema_slow_val: Decimal,
        adx_val: Decimal
    ) -> int:
        """
        Determine current regime (1-6) based on indicators.

        Regime Logic:
        - Trend direction: EMA_fast > EMA_slow (bullish) vs EMA_fast < EMA_slow (bearish)
        - Trend strength: ADX > 25 (strong), 20 < ADX <= 25 (building), ADX <= 20 (weak)

        Args:
            ema_fast_val: Current fast EMA value
            ema_slow_val: Current slow EMA value
            adx_val: Current ADX value

        Returns:
            Regime number (1-6)
        """
        is_bullish = ema_fast_val > ema_slow_val

        # Determine trend strength
        if adx_val > self.adx_threshold_high:
            trend_strength = 'strong'
        elif adx_val > self.adx_threshold_low:
            trend_strength = 'building'
        else:
            trend_strength = 'weak'

        # Map to regime number
        if is_bullish:
            if trend_strength == 'strong':
                return 1  # Strong Bullish: TQQQ 60%
            elif trend_strength == 'building':
                return 2  # Building Bullish: TQQQ 30%
            else:  # weak
                return 5  # Weak Bullish: QQQ 50%
        else:  # bearish
            if trend_strength == 'strong':
                return 3  # Strong Bearish: SQQQ 60%
            elif trend_strength == 'building':
                return 4  # Building Bearish: SQQQ 30%
            else:  # weak
                return 6  # Weak Bearish: CASH 100%

    def _liquidate_all_positions(self):
        """
        Close all positions in TQQQ, SQQQ, QQQ.

        Logs strategy context BEFORE selling to ensure liquidation trades have context.
        Sells 0% allocation (close position) for each symbol.
        """
        for symbol in [self.bull_symbol, self.bear_symbol, self.neutral_symbol]:
            if self.get_position(symbol) > 0:
                # Log context BEFORE liquidation signal (so SELL has context)
                if self._trade_logger and hasattr(self, '_current_bar'):
                    # Get regime description for liquidation
                    regime_desc = f"Liquidating {symbol} position (regime change)"

                    self._trade_logger.log_strategy_context(
                        timestamp=self._current_bar.timestamp,
                        symbol=symbol,  # Log for the specific symbol being liquidated
                        strategy_state=regime_desc,
                        decision_reason=self._last_decision_reason,  # From on_bar
                        indicator_values=self._last_indicator_values,  # From on_bar
                        threshold_values=self._last_threshold_values  # From on_bar
                    )

                self.sell(symbol, Decimal('0.0'))  # Close long position
                self.log(f"LIQUIDATE: Closed {symbol} position")

    def _execute_regime_allocation(self, regime: int):
        """
        Generate signals based on regime.

        Logs strategy context BEFORE generating signals with correct trade symbol.

        Regime Allocations:
        1. Strong Bullish: TQQQ 60%
        2. Building Bullish: TQQQ 30%
        3. Strong Bearish: SQQQ 60%
        4. Building Bearish: SQQQ 30%
        5. Weak Bullish: QQQ 50%
        6. Weak Bearish: CASH (no position)

        Args:
            regime: Regime number (1-6)
        """
        # Determine which symbol we'll trade and regime description
        if regime == 1:
            trade_symbol = self.bull_symbol  # 'TQQQ'
            allocation = Decimal('0.60')
            regime_desc = "Strong Bullish (ADX > 25, EMA_fast > EMA_slow)"
        elif regime == 2:
            trade_symbol = self.bull_symbol  # 'TQQQ'
            allocation = Decimal('0.30')
            regime_desc = "Building Bullish (20 < ADX <= 25, EMA_fast > EMA_slow)"
        elif regime == 3:
            trade_symbol = self.bear_symbol  # 'SQQQ'
            allocation = Decimal('0.60')
            regime_desc = "Strong Bearish (ADX > 25, EMA_fast < EMA_slow)"
        elif regime == 4:
            trade_symbol = self.bear_symbol  # 'SQQQ'
            allocation = Decimal('0.30')
            regime_desc = "Building Bearish (20 < ADX <= 25, EMA_fast < EMA_slow)"
        elif regime == 5:
            trade_symbol = self.neutral_symbol  # 'QQQ'
            allocation = Decimal('0.50')
            regime_desc = "Weak Bullish (ADX <= 20, EMA_fast > EMA_slow)"
        elif regime == 6:
            # Weak Bearish: No trade, just return (already in cash)
            self.log(f"REGIME 6: Weak Bearish → CASH 100%")
            return
        else:
            raise ValueError(f"Invalid regime: {regime}")

        # Log context BEFORE generating signal (with TRADE symbol, not signal symbol!)
        if self._trade_logger and hasattr(self, '_current_bar'):
            self._trade_logger.log_strategy_context(
                timestamp=self._current_bar.timestamp,
                symbol=trade_symbol,  # CRITICAL: Use trade symbol (TQQQ/SQQQ/QQQ), not signal symbol (QQQ)!
                strategy_state=f"Regime {regime}: {regime_desc}",
                decision_reason=self._last_decision_reason,  # From on_bar
                indicator_values=self._last_indicator_values,  # From on_bar
                threshold_values=self._last_threshold_values  # From on_bar
            )

        # Generate signal
        self.buy(trade_symbol, allocation)
        self.log(f"REGIME {regime}: {regime_desc} → {trade_symbol} {allocation*100:.0f}%")
