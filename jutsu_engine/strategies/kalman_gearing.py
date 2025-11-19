"""
Kalman Gearing v1.0: Dynamic leverage matching strategy.

This strategy matches portfolio leverage (from -3x to +3x) to trend strength magnitude
and direction identified by an Adaptive Kalman Filter. It trades across 4 vehicles
(TQQQ, QQQ, SQQQ, CASH) based on 4 distinct market regimes.

Core Innovation: Replace traditional trend indicators (EMA/MACD) with a single
Adaptive Kalman Filter Trend Strength Oscillator, using the "dead zone" (neutral)
regime to hold CASH and avoid whipsaw/volatility drag.

Strategy Logic:
- STRONG BULL (trend_strength > 70): TQQQ (3x long leverage)
- MODERATE BULL (20 < trend_strength <= 70): QQQ (1x long)
- CHOP/NEUTRAL (-70 <= trend_strength <= 20): CASH (no position)
- STRONG BEAR (trend_strength < -70): SQQQ (3x short leverage)

Position Sizing:
- Leveraged (TQQQ/SQQQ): ATR-based risk sizing (2.5% portfolio risk)
- Unleveraged (QQQ): 80% portfolio allocation

Stop-Loss:
- TQQQ/SQQQ only: ATR-based hard stops
- QQQ: No stop-loss (regime change exit only)

Signal Source: QQQ with Kalman Filter
All Parameters: Configurable for WFO optimization
"""
from decimal import Decimal
from enum import Enum
from typing import Optional
import logging

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import (
    AdaptiveKalmanFilter,
    KalmanFilterModel
)
from jutsu_engine.indicators.technical import atr
from jutsu_engine.performance.trade_logger import TradeLogger

logger = logging.getLogger('STRATEGY.KALMAN_GEARING')


class Regime(Enum):
    """
    Market regime classification based on Kalman trend strength.

    Attributes:
        STRONG_BULL: Strong bullish trend (trend_strength > 70)
        MODERATE_BULL: Moderate bullish trend (20 < trend_strength <= 70)
        CHOP_NEUTRAL: Choppy/neutral market (-70 <= trend_strength <= 20)
        STRONG_BEAR: Strong bearish trend (trend_strength < -70)
    """
    STRONG_BULL = "STRONG_BULL"
    MODERATE_BULL = "MODERATE_BULL"
    CHOP_NEUTRAL = "CHOP_NEUTRAL"
    STRONG_BEAR = "STRONG_BEAR"


class KalmanGearing(Strategy):
    """
    Dynamic gearing strategy using Kalman Filter for regime detection.

    Matches portfolio leverage to trend strength:
    - STRONG BULL (>70): TQQQ (3x long leverage)
    - MODERATE BULL (20-70): QQQ (1x long)
    - CHOP/NEUTRAL (-70 to 20): CASH (no position)
    - STRONG BEAR (<-70): SQQQ (3x short leverage)

    Performance Targets:
        - Processing Speed: <1ms per bar (excluding Kalman update)
        - Memory: O(lookback_period) for Kalman state
        - Backtest: 2010-2025 (15 years) in <10 seconds

    Example:
        strategy = KalmanGearing(
            process_noise_1=0.01,
            measurement_noise=500.0,
            thresh_strong_bull=Decimal('70'),
            thresh_moderate_bull=Decimal('20'),
            thresh_strong_bear=Decimal('-70'),
            atr_stop_multiplier=Decimal('3.0'),
            risk_leveraged=Decimal('0.025'),
            allocation_unleveraged=Decimal('0.80')
        )
    """

    def __init__(
        self,
        # Kalman filter parameters
        process_noise_1: float = 0.01,
        process_noise_2: float = 0.01,
        measurement_noise: float = 500.0,
        osc_smoothness: int = 10,
        strength_smoothness: int = 10,

        # Regime thresholds
        thresh_strong_bull: Decimal = Decimal('70'),
        thresh_moderate_bull: Decimal = Decimal('20'),
        thresh_strong_bear: Decimal = Decimal('-70'),

        # Risk management
        atr_period: int = 14,
        atr_stop_multiplier: Decimal = Decimal('3.0'),
        risk_leveraged: Decimal = Decimal('0.025'),  # 2.5%
        allocation_unleveraged: Decimal = Decimal('0.80'),  # 80%

        # Trading symbols
        signal_symbol: str = 'QQQ',
        bull_3x_symbol: str = 'TQQQ',
        bear_3x_symbol: str = 'SQQQ',
        unleveraged_symbol: str = 'QQQ',

        # TradeLogger integration
        trade_logger: Optional[TradeLogger] = None,

        # Metadata
        name: str = "KalmanGearing"
    ):
        """
        Initialize Kalman Gearing strategy.

        Args:
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            measurement_noise: Base measurement noise (default: 500.0)
            osc_smoothness: Smoothing period for oscillator (default: 10)
            strength_smoothness: Smoothing period for trend strength (default: 10)
            thresh_strong_bull: Strong bull threshold (default: 70)
            thresh_moderate_bull: Moderate bull threshold (default: 20)
            thresh_strong_bear: Strong bear threshold (default: -70)
            atr_period: ATR calculation period (default: 14)
            atr_stop_multiplier: ATR multiplier for stop-loss (default: 3.0)
            risk_leveraged: Risk % for leveraged positions (default: 0.025 = 2.5%)
            allocation_unleveraged: Allocation % for QQQ (default: 0.80 = 80%)
            signal_symbol: Symbol for Kalman signal generation (default: 'QQQ')
            bull_3x_symbol: 3x leveraged long symbol (default: 'TQQQ')
            bear_3x_symbol: 3x leveraged short symbol (default: 'SQQQ')
            unleveraged_symbol: 1x long symbol (default: 'QQQ')
            trade_logger: Optional TradeLogger for strategy context logging (default: None)
            name: Strategy name (default: 'KalmanGearing')

        Raises:
            ValueError: If thresholds are not properly ordered
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate threshold ordering
        if not (thresh_strong_bear < Decimal('0') < thresh_moderate_bull < thresh_strong_bull):
            raise ValueError(
                f"Thresholds must satisfy: strong_bear ({thresh_strong_bear}) < 0 < "
                f"moderate_bull ({thresh_moderate_bull}) < strong_bull ({thresh_strong_bull})"
            )

        # Store Kalman filter parameters
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.measurement_noise = measurement_noise
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness

        # Store regime thresholds
        self.thresh_strong_bull = thresh_strong_bull
        self.thresh_moderate_bull = thresh_moderate_bull
        self.thresh_strong_bear = thresh_strong_bear

        # Store risk management parameters
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_leveraged = risk_leveraged
        self.allocation_unleveraged = allocation_unleveraged

        # Store trading symbols
        self.signal_symbol = signal_symbol
        self.bull_3x_symbol = bull_3x_symbol
        self.bear_3x_symbol = bear_3x_symbol
        self.unleveraged_symbol = unleveraged_symbol

        # State variables (initialized in init())
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.current_regime: Optional[Regime] = None
        self.current_vehicle: Optional[str] = None
        self.leveraged_stop_price: Optional[Decimal] = None
        self.vehicles = {}

        logger.info(
            f"Initialized {name} with thresholds: "
            f"strong_bull={thresh_strong_bull}, moderate_bull={thresh_moderate_bull}, "
            f"strong_bear={thresh_strong_bear}"
        )

    def init(self):
        """
        Initialize Kalman filter and state variables.

        Called once before backtesting starts. Sets up:
        - AdaptiveKalmanFilter instance with VOLUME_ADJUSTED model
        - Regime → Vehicle mapping
        - Current regime and vehicle state
        - Stop-loss tracking
        """
        # Create Kalman filter instance
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            process_noise_1=self.process_noise_1,
            process_noise_2=self.process_noise_2,
            measurement_noise=self.measurement_noise,
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness
        )

        # Initialize state
        self.current_regime = None
        self.current_vehicle = None
        self.leveraged_stop_price = None

        # Define regime → vehicle mapping
        self.vehicles = {
            Regime.STRONG_BULL: self.bull_3x_symbol,
            Regime.MODERATE_BULL: self.unleveraged_symbol,
            Regime.CHOP_NEUTRAL: None,  # CASH
            Regime.STRONG_BEAR: self.bear_3x_symbol
        }

        logger.info(f"{self.name} initialized with Kalman filter")

    def on_bar(self, bar: MarketDataEvent):
        """
        Process each bar:
        1. Update Kalman filter with QQQ data
        2. Determine current regime from trend_strength
        3. Check if regime changed
        4. If changed: liquidate → calculate size → execute
        5. Monitor stop-loss for leveraged positions

        Args:
            bar: New market data bar with OHLCV data

        Processing Flow:
            QQQ bar → Kalman update → trend_strength → regime determination
            → check stop-loss → execute regime change if needed
        """
        # Step 1: Only process signal symbol (QQQ) for regime detection
        if bar.symbol != self.signal_symbol:
            return

        # Step 2: Update Kalman filter with volume-adjusted model
        _, trend_strength = self.kalman_filter.update(
            close=bar.close,
            volume=bar.volume
        )

        # Step 3: Determine regime from trend strength
        new_regime = self._determine_regime(trend_strength)

        # Step 4: Check for stop-loss hit BEFORE regime change
        # (Only applies to leveraged positions: TQQQ/SQQQ)
        if self.current_vehicle in [self.bull_3x_symbol, self.bear_3x_symbol]:
            if self._check_stop_loss(bar):
                # FIX BUG 2: Log context BEFORE liquidation so trade has proper state
                if self._trade_logger:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=self.current_vehicle,  # TQQQ or SQQQ
                        strategy_state=f"Stop-Loss Exit ({self.current_vehicle})",
                        decision_reason=f"ATR stop triggered at {self.leveraged_stop_price:.2f}",
                        indicator_values={'stop_price': float(self.leveraged_stop_price)},
                        threshold_values={'atr_stop_multiplier': float(self.atr_stop_multiplier)}
                    )
                
                self._liquidate_position()
                self.current_regime = Regime.CHOP_NEUTRAL
                self.current_vehicle = None
                logger.warning(
                    f"Stop-loss hit at {bar.timestamp}: {self.current_vehicle} "
                    f"liquidated at {bar.close}"
                )
                return

        # Step 5: Execute regime change if needed
        if new_regime != self.current_regime:
            logger.info(
                f"Regime change at {bar.timestamp}: {self.current_regime} → {new_regime} "
                f"(trend_strength={trend_strength:.2f})"
            )

            # FIX BUG 3: Log context for LIQUIDATION (SELL) of current position BEFORE regime change
            if self._trade_logger and self.current_vehicle:
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=self.current_vehicle,  # Log for vehicle being liquidated
                    strategy_state=f"Regime Change Exit ({self.current_regime} → {new_regime})",
                    decision_reason=f"Trend strength {trend_strength:.2f} triggered regime change",
                    indicator_values={'trend_strength': float(trend_strength)},
                    threshold_values={
                        'strong_bull_threshold': float(self.thresh_strong_bull),
                        'moderate_bull_threshold': float(self.thresh_moderate_bull),
                        'strong_bear_threshold': float(self.thresh_strong_bear)
                    }
                )

            # Calculate target vehicle for new regime
            target_vehicle = self.vehicles[new_regime]

            # FIX BUG 1: Log context for NEW ENTRY (BUY) with correct symbol
            # Skip logging for CASH regime (target_vehicle=None)
            if self._trade_logger and target_vehicle:
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=target_vehicle,  # FIX: Use actual trading vehicle, not signal symbol
                    strategy_state=self._get_regime_description(new_regime),
                    decision_reason=self._build_decision_reason(trend_strength, new_regime),
                    indicator_values={'trend_strength': trend_strength},
                    threshold_values={
                        'strong_bull_threshold': self.thresh_strong_bull,
                        'moderate_bull_threshold': self.thresh_moderate_bull,
                        'strong_bear_threshold': self.thresh_strong_bear
                    }
                )

            self._execute_regime_change(new_regime, bar)

    def _determine_regime(self, trend_strength: Decimal) -> Regime:
        """
        Map trend_strength to regime using thresholds.

        Threshold Logic:
            trend_strength > 70: STRONG_BULL
            20 < trend_strength <= 70: MODERATE_BULL
            -70 <= trend_strength <= 20: CHOP_NEUTRAL
            trend_strength < -70: STRONG_BEAR

        Args:
            trend_strength: Value from -100 to +100 from Kalman filter

        Returns:
            Regime enum value

        Example:
            trend_strength = Decimal('75') → Regime.STRONG_BULL
            trend_strength = Decimal('50') → Regime.MODERATE_BULL
            trend_strength = Decimal('0') → Regime.CHOP_NEUTRAL
            trend_strength = Decimal('-75') → Regime.STRONG_BEAR
        """
        if trend_strength > self.thresh_strong_bull:
            return Regime.STRONG_BULL
        elif trend_strength > self.thresh_moderate_bull:
            return Regime.MODERATE_BULL
        elif trend_strength < self.thresh_strong_bear:
            return Regime.STRONG_BEAR
        else:
            return Regime.CHOP_NEUTRAL

    def _execute_regime_change(self, new_regime: Regime, bar: MarketDataEvent):
        """
        Execute transition to new regime.

        Process:
        1. Liquidate current position (if any)
        2. Get target vehicle for new regime
        3. Execute new position based on vehicle type
        4. Update state variables

        Args:
            new_regime: Target regime to transition to
            bar: Current market data bar for reference

        Side Effects:
            - Liquidates existing position
            - Generates buy/sell signals
            - Updates current_regime and current_vehicle
            - Resets stop-loss tracking
        """
        # Liquidate current position
        if self.current_vehicle:
            self._liquidate_position()

        # Get target vehicle for new regime
        target_vehicle = self.vehicles[new_regime]

        # Execute new position based on vehicle type
        if target_vehicle == self.bull_3x_symbol:
            self._enter_leveraged_long(bar)
        elif target_vehicle == self.bear_3x_symbol:
            self._enter_leveraged_short(bar)
        elif target_vehicle == self.unleveraged_symbol:
            self._enter_unleveraged(bar)
        # else: target_vehicle is None (CASH) - no action needed

        # Update state
        self.current_regime = new_regime
        self.current_vehicle = target_vehicle

        logger.info(
            f"Regime executed: {new_regime.value} → "
            f"vehicle={target_vehicle if target_vehicle else 'CASH'}"
        )

    def _enter_leveraged_long(self, bar: MarketDataEvent):
        """
        Enter TQQQ position with ATR-based position sizing.

        Position Sizing:
        - Risk-based sizing: risk 2.5% of portfolio equity
        - Shares = (portfolio_value × risk_percent) / (ATR × stop_multiplier)
        - ATR calculated from TQQQ bars (not QQQ)

        Args:
            bar: Current QQQ bar (for timestamp context)

        Side Effects:
            - Generates BUY signal for TQQQ
            - Sets leveraged_stop_price (after fill)

        Note:
            Stop-loss price is calculated after fill occurs (next bar's open).
            We'll update stop_price in _check_stop_loss() when position exists.
        """
        # Get TQQQ data for ATR calculation
        closes = self.get_closes(lookback=self.atr_period, symbol=self.bull_3x_symbol)
        highs = self.get_highs(lookback=self.atr_period, symbol=self.bull_3x_symbol)
        lows = self.get_lows(lookback=self.atr_period, symbol=self.bull_3x_symbol)

        if len(closes) < self.atr_period:
            logger.debug(
                f"Insufficient TQQQ data for ATR: {len(closes)} < {self.atr_period}"
            )
            return  # Not enough data

        # Calculate ATR
        atr_value = atr(closes, highs, lows, self.atr_period).iloc[-1]
        dollar_risk_per_share = Decimal(str(atr_value)) * self.atr_stop_multiplier

        # Execute buy order using portfolio percentage and risk_per_share
        # Portfolio module will calculate actual shares
        self.buy(
            self.bull_3x_symbol,
            portfolio_percent=self.risk_leveraged,
            risk_per_share=dollar_risk_per_share
        )

        # Stop-loss will be calculated after fill (in _check_stop_loss)
        self.leveraged_stop_price = None

        logger.info(
            f"Entering TQQQ: risk={self.risk_leveraged}, "
            f"risk_per_share=${dollar_risk_per_share:.2f}"
        )

    def _enter_leveraged_short(self, bar: MarketDataEvent):
        """
        Enter SQQQ position with ATR-based position sizing.

        Position Sizing:
        - Risk-based sizing: risk 2.5% of portfolio equity
        - Shares = (portfolio_value × risk_percent) / (ATR × stop_multiplier)
        - ATR calculated from SQQQ bars

        Args:
            bar: Current QQQ bar (for timestamp context)

        Side Effects:
            - Generates BUY signal for SQQQ (SQQQ is inverse ETF)
            - Sets leveraged_stop_price (after fill)

        Note:
            SQQQ is an inverse ETF, so we BUY it to express bearish view.
            Stop-loss price calculated after fill (next bar's open).
        """
        # Get SQQQ data for ATR calculation
        closes = self.get_closes(lookback=self.atr_period, symbol=self.bear_3x_symbol)
        highs = self.get_highs(lookback=self.atr_period, symbol=self.bear_3x_symbol)
        lows = self.get_lows(lookback=self.atr_period, symbol=self.bear_3x_symbol)

        if len(closes) < self.atr_period:
            logger.debug(
                f"Insufficient SQQQ data for ATR: {len(closes)} < {self.atr_period}"
            )
            return  # Not enough data

        # Calculate ATR
        atr_value = atr(closes, highs, lows, self.atr_period).iloc[-1]
        dollar_risk_per_share = Decimal(str(atr_value)) * self.atr_stop_multiplier

        # Execute buy order (SQQQ is inverse, so BUY for bearish exposure)
        self.buy(
            self.bear_3x_symbol,
            portfolio_percent=self.risk_leveraged,
            risk_per_share=dollar_risk_per_share
        )

        # Stop-loss will be calculated after fill (in _check_stop_loss)
        self.leveraged_stop_price = None

        logger.info(
            f"Entering SQQQ: risk={self.risk_leveraged}, "
            f"risk_per_share=${dollar_risk_per_share:.2f}"
        )

    def _enter_unleveraged(self, bar: MarketDataEvent):
        """
        Enter QQQ position with percentage allocation.

        Position Sizing:
        - Allocate 80% of portfolio equity (default)
        - No ATR-based sizing (unleveraged)
        - No stop-loss (exit via regime change only)

        Args:
            bar: Current QQQ bar (for price context)

        Side Effects:
            - Generates BUY signal for QQQ
            - Clears leveraged_stop_price (no stop for QQQ)
        """
        # Execute buy order using percentage allocation
        # Portfolio module calculates shares from allocation percentage
        self.buy(
            self.unleveraged_symbol,
            portfolio_percent=self.allocation_unleveraged
        )

        # No stop-loss for unleveraged position
        self.leveraged_stop_price = None

        logger.info(
            f"Entering QQQ: allocation={self.allocation_unleveraged}"
        )

    def _check_stop_loss(self, bar: MarketDataEvent) -> bool:
        """
        Check if stop-loss hit for leveraged position.

        Stop-Loss Logic:
        - Only applies to TQQQ/SQQQ positions
        - Uses bar.low for conservative check (worst intraday price)
        - Stop calculated as: entry_price - (ATR × stop_multiplier)
        - Calculated lazily on first check after entry

        Args:
            bar: Current QQQ bar (signal symbol)

        Returns:
            True if stop-loss hit, False otherwise

        Side Effects:
            - Sets leveraged_stop_price on first call after entry
        """
        # If we don't have a stop-loss price yet, calculate from current position
        if not self.leveraged_stop_price:
            # Get current position for leveraged vehicle
            position_qty = self.get_position(self.current_vehicle)

            if position_qty > 0:
                # Calculate stop from entry price using ATR
                closes = self.get_closes(
                    lookback=self.atr_period,
                    symbol=self.current_vehicle
                )
                highs = self.get_highs(
                    lookback=self.atr_period,
                    symbol=self.current_vehicle
                )
                lows = self.get_lows(
                    lookback=self.atr_period,
                    symbol=self.current_vehicle
                )

                if len(closes) >= self.atr_period:
                    atr_value = atr(closes, highs, lows, self.atr_period).iloc[-1]
                    dollar_risk = Decimal(str(atr_value)) * self.atr_stop_multiplier

                    # Get current bar for vehicle to approximate entry
                    # (In production, we'd track actual fill price)
                    vehicle_bars = [b for b in self._bars if b.symbol == self.current_vehicle]
                    if vehicle_bars:
                        latest_bar = vehicle_bars[-1]
                        self.leveraged_stop_price = latest_bar.close - dollar_risk

                        logger.debug(
                            f"Stop-loss calculated for {self.current_vehicle}: "
                            f"entry~{latest_bar.close}, stop={self.leveraged_stop_price:.2f}"
                        )

        # Check if stop-loss hit using vehicle's low price
        if self.leveraged_stop_price:
            # Get latest bar for current vehicle
            vehicle_bars = [b for b in self._bars if b.symbol == self.current_vehicle]
            if vehicle_bars:
                latest_vehicle_bar = vehicle_bars[-1]

                # Conservative check: use bar.low (worst intraday price)
                if latest_vehicle_bar.low <= self.leveraged_stop_price:
                    logger.info(
                        f"Stop-loss triggered: {self.current_vehicle} "
                        f"low={latest_vehicle_bar.low:.2f} <= stop={self.leveraged_stop_price:.2f}"
                    )
                    return True

        return False

    def _liquidate_position(self):
        """
        Liquidate current position if any.

        Side Effects:
            - Generates SELL signal for current vehicle
            - Clears leveraged_stop_price
            - Does NOT update current_vehicle (caller responsible)
        """
        if self.current_vehicle:
            position_qty = self.get_position(self.current_vehicle)

            if position_qty > 0:
                # Close position completely (0% triggers Portfolio's close-position logic)
                self.sell(self.current_vehicle, portfolio_percent=Decimal('0.0'))

                logger.info(
                    f"Liquidated {self.current_vehicle}: {position_qty} shares"
                )

            # Clear stop-loss tracking
            self.leveraged_stop_price = None

    def _get_regime_description(self, regime: Regime) -> str:
        """
        Convert Regime enum to human-readable string for logging.

        Args:
            regime: Regime enum value

        Returns:
            Human-readable regime description with trading vehicle

        Example:
            Regime.STRONG_BULL → "Regime 1: Strong Bullish (TQQQ)"
        """
        descriptions = {
            Regime.STRONG_BULL: "Regime 1: Strong Bullish (TQQQ)",
            Regime.MODERATE_BULL: "Regime 2: Moderate Bullish (QQQ)",
            Regime.CHOP_NEUTRAL: "Regime 3: Choppy/Neutral (CASH)",
            Regime.STRONG_BEAR: "Regime 4: Strong Bearish (SQQQ)"
        }
        return descriptions[regime]

    def _build_decision_reason(self, trend_strength: Decimal, regime: Regime) -> str:
        """
        Build decision rationale from trend strength and thresholds.

        Args:
            trend_strength: Current trend strength value (-100 to +100)
            regime: Determined regime based on trend strength

        Returns:
            Human-readable explanation of why this regime was chosen

        Example:
            trend_strength=75.3, regime=STRONG_BULL →
            "Trend strength 75.30 > strong_bull threshold 70.00"
        """
        if regime == Regime.STRONG_BULL:
            return f"Trend strength {trend_strength:.2f} > strong_bull threshold {self.thresh_strong_bull}"
        elif regime == Regime.MODERATE_BULL:
            return (
                f"Trend strength {trend_strength:.2f} > moderate_bull threshold "
                f"{self.thresh_moderate_bull} and <= strong_bull threshold {self.thresh_strong_bull}"
            )
        elif regime == Regime.STRONG_BEAR:
            return f"Trend strength {trend_strength:.2f} < strong_bear threshold {self.thresh_strong_bear}"
        else:  # CHOP_NEUTRAL
            return (
                f"Trend strength {trend_strength:.2f} between strong_bear threshold "
                f"{self.thresh_strong_bear} and moderate_bull threshold {self.thresh_moderate_bull} (choppy)"
            )
