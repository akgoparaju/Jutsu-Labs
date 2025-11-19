"""
Kalman-MACD Adaptive v1.0: Hierarchical regime-based strategy.

This is an adaptive "strategy-of-strategies" model that identifies market regimes
using a Kalman Filter Trend Strength Oscillator (-100 to +100) and deploys
regime-specific MACD/EMA parameters optimized for each environment.

Core Innovation: Replace static parameters with adaptive parameter sets that
change based on market regime, reducing parameter drift and improving adaptability.

Strategy Logic:
- STRONG BULL (trend_strength > 60): Aggressive TQQQ/QQQ with EMA(100), MACD(12/26/9)
- MODERATE BULL (20 < trend_strength <= 60): Cautious QQQ with EMA(150), MACD(20/50/12)
- CHOP/NEUTRAL (-20 <= trend_strength <= 20): CASH (avoid whipsaw)
- BEAR (trend_strength < -20): Defensive SQQQ with EMA(100), MACD(12/26/9)

Position Sizing:
- Leveraged (TQQQ/SQQQ): ATR-based risk sizing (2.5% portfolio risk)
- Unleveraged (QQQ): 80% portfolio allocation

Stop-Loss:
- TQQQ/SQQQ only: ATR-based hard stops (3.0x ATR)
- QQQ: No stop-loss (regime change exit only)

Signal Source: QQQ with Kalman Filter + regime-specific MACD/EMA
All 27 Parameters: Fully configurable for grid-search and WFO optimization
"""
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple
import logging

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import (
    AdaptiveKalmanFilter,
    KalmanFilterModel
)
from jutsu_engine.indicators.technical import ema, macd, atr
from jutsu_engine.performance.trade_logger import TradeLogger

logger = logging.getLogger('STRATEGY.KALMAN_MACD_ADAPTIVE_V1')


class Regime(Enum):
    """
    Market regime classification based on Kalman trend strength.

    Attributes:
        STRONG_BULL: Strong bullish trend requiring aggressive parameters
        MODERATE_BULL: Moderate bullish trend requiring cautious parameters
        CHOP_NEUTRAL: Choppy/neutral market - hold CASH
        BEAR: Bearish trend requiring defensive/short parameters
    """
    STRONG_BULL = "STRONG_BULL"
    MODERATE_BULL = "MODERATE_BULL"
    CHOP_NEUTRAL = "CHOP_NEUTRAL"
    BEAR = "BEAR"


class Kalman_MACD_Adaptive_v1(Strategy):
    """
    Hierarchical regime-based strategy with adaptive parameters.

    Uses Kalman Filter for regime classification, then applies regime-specific
    MACD and EMA parameters. Trades across 4 vehicles (TQQQ, QQQ, SQQQ, CASH)
    based on 4 distinct market regimes.

    Performance Targets:
        - Processing Speed: <2ms per bar (including Kalman + MACD calculations)
        - Memory: O(max_lookback_period) for indicator state
        - Backtest: 2010-2025 (15 years) in <15 seconds

    Example:
        strategy = Kalman_MACD_Adaptive_v1(
            measurement_noise=5000.0,
            osc_smoothness=20,
            strength_smoothness=20,
            thresh_strong_bull=Decimal('60'),
            thresh_moderate_bull=Decimal('20'),
            thresh_moderate_bear=Decimal('-20'),
            ema_trend_sb=100,
            macd_fast_sb=12,
            macd_slow_sb=26,
            macd_signal_sb=9,
            # ... (all 27 parameters configurable)
        )
    """

    def __init__(
        self,
        # ==================================================================
        # TIER 1: KALMAN FILTER PARAMETERS (Master Regime Filter)
        # ==================================================================
        measurement_noise: float = 5000.0,
        osc_smoothness: int = 20,
        strength_smoothness: int = 20,
        process_noise_1: float = 0.01,  # Fixed per spec
        process_noise_2: float = 0.01,  # Fixed per spec

        # ==================================================================
        # TIER 2: REGIME THRESHOLD PARAMETERS (Critical for Switching)
        # ==================================================================
        thresh_strong_bull: Decimal = Decimal('60'),
        thresh_moderate_bull: Decimal = Decimal('20'),
        thresh_moderate_bear: Decimal = Decimal('-20'),

        # ==================================================================
        # TIER 3: STRONG BULL REGIME PARAMETERS (Aggressive)
        # ==================================================================
        ema_trend_sb: int = 100,
        macd_fast_sb: int = 12,
        macd_slow_sb: int = 26,
        macd_signal_sb: int = 9,

        # ==================================================================
        # TIER 4: MODERATE BULL REGIME PARAMETERS (Cautious)
        # ==================================================================
        ema_trend_mb: int = 150,
        macd_fast_mb: int = 20,
        macd_slow_mb: int = 50,
        macd_signal_mb: int = 12,

        # ==================================================================
        # TIER 5: BEAR REGIME PARAMETERS (Defensive/Short)
        # ==================================================================
        ema_trend_b: int = 100,
        macd_fast_b: int = 12,
        macd_slow_b: int = 26,
        macd_signal_b: int = 9,

        # ==================================================================
        # TIER 6: RISK & SIZING PARAMETERS
        # ==================================================================
        atr_period: int = 14,
        atr_stop_multiplier: Decimal = Decimal('3.0'),
        risk_leveraged: Decimal = Decimal('0.025'),  # 2.5%
        allocation_unleveraged: Decimal = Decimal('0.80'),  # 80%

        # ==================================================================
        # TRADING SYMBOLS
        # ==================================================================
        signal_symbol: str = 'QQQ',
        bull_symbol: str = 'TQQQ',
        defense_symbol: str = 'QQQ',
        bear_symbol: str = 'SQQQ',

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Kalman_MACD_Adaptive_v1"
    ):
        """
        Initialize Kalman-MACD Adaptive strategy with 27 configurable parameters.

        Args:
            measurement_noise: Base measurement noise for Kalman filter (default: 5000.0)
            osc_smoothness: Smoothing period for oscillator (default: 20)
            strength_smoothness: Smoothing period for trend strength (default: 20)
            process_noise_1: Process noise for position (default: 0.01, per spec)
            process_noise_2: Process noise for velocity (default: 0.01, per spec)
            thresh_strong_bull: Strong bull threshold (default: 60)
            thresh_moderate_bull: Moderate bull threshold (default: 20)
            thresh_moderate_bear: Moderate bear threshold (default: -20)
            ema_trend_sb: Strong Bull EMA period (default: 100)
            macd_fast_sb: Strong Bull MACD fast period (default: 12)
            macd_slow_sb: Strong Bull MACD slow period (default: 26)
            macd_signal_sb: Strong Bull MACD signal period (default: 9)
            ema_trend_mb: Moderate Bull EMA period (default: 150)
            macd_fast_mb: Moderate Bull MACD fast period (default: 20)
            macd_slow_mb: Moderate Bull MACD slow period (default: 50)
            macd_signal_mb: Moderate Bull MACD signal period (default: 12)
            ema_trend_b: Bear EMA period (default: 100)
            macd_fast_b: Bear MACD fast period (default: 12)
            macd_slow_b: Bear MACD slow period (default: 26)
            macd_signal_b: Bear MACD signal period (default: 9)
            atr_period: ATR calculation period (default: 14)
            atr_stop_multiplier: ATR multiplier for stop-loss (default: 3.0)
            risk_leveraged: Risk % for leveraged positions (default: 0.025 = 2.5%)
            allocation_unleveraged: Allocation % for QQQ (default: 0.80 = 80%)
            signal_symbol: Symbol for signal generation (default: 'QQQ')
            bull_symbol: 3x leveraged long symbol (default: 'TQQQ')
            defense_symbol: 1x long symbol (default: 'QQQ')
            bear_symbol: 3x leveraged short symbol (default: 'SQQQ')
            trade_logger: Optional TradeLogger for strategy context (default: None)
            name: Strategy name (default: 'Kalman_MACD_Adaptive_v1')

        Raises:
            ValueError: If thresholds not properly ordered or MACD parameters invalid
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate threshold ordering
        if not (thresh_moderate_bear < Decimal('0') < thresh_moderate_bull < thresh_strong_bull):
            raise ValueError(
                f"Thresholds must satisfy: moderate_bear ({thresh_moderate_bear}) < 0 < "
                f"moderate_bull ({thresh_moderate_bull}) < strong_bull ({thresh_strong_bull})"
            )

        # Validate MACD parameters (fast < slow)
        if not (macd_fast_sb < macd_slow_sb):
            raise ValueError(f"Strong Bull: MACD fast ({macd_fast_sb}) must be < slow ({macd_slow_sb})")
        if not (macd_fast_mb < macd_slow_mb):
            raise ValueError(f"Moderate Bull: MACD fast ({macd_fast_mb}) must be < slow ({macd_slow_mb})")
        if not (macd_fast_b < macd_slow_b):
            raise ValueError(f"Bear: MACD fast ({macd_fast_b}) must be < slow ({macd_slow_b})")

        # Store Kalman filter parameters
        self.measurement_noise = measurement_noise
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2

        # Store regime thresholds
        self.thresh_strong_bull = thresh_strong_bull
        self.thresh_moderate_bull = thresh_moderate_bull
        self.thresh_moderate_bear = thresh_moderate_bear

        # Store Strong Bull regime parameters
        self.ema_trend_sb = ema_trend_sb
        self.macd_fast_sb = macd_fast_sb
        self.macd_slow_sb = macd_slow_sb
        self.macd_signal_sb = macd_signal_sb

        # Store Moderate Bull regime parameters
        self.ema_trend_mb = ema_trend_mb
        self.macd_fast_mb = macd_fast_mb
        self.macd_slow_mb = macd_slow_mb
        self.macd_signal_mb = macd_signal_mb

        # Store Bear regime parameters
        self.ema_trend_b = ema_trend_b
        self.macd_fast_b = macd_fast_b
        self.macd_slow_b = macd_slow_b
        self.macd_signal_b = macd_signal_b

        # Store risk management parameters
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_leveraged = risk_leveraged
        self.allocation_unleveraged = allocation_unleveraged

        # Store trading symbols
        self.signal_symbol = signal_symbol
        self.bull_symbol = bull_symbol
        self.defense_symbol = defense_symbol
        self.bear_symbol = bear_symbol

        # State variables (initialized in init())
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.current_regime: Optional[Regime] = None
        self.current_vehicle: Optional[str] = None
        self.leveraged_stop_price: Optional[Decimal] = None
        self.max_lookback: int = 0  # Will be calculated in init()

        logger.info(
            f"Initialized {name} with 27 parameters: "
            f"Kalman[noise={measurement_noise}, osc={osc_smoothness}, strength={strength_smoothness}], "
            f"Thresholds[bull={thresh_strong_bull}, mod={thresh_moderate_bull}, bear={thresh_moderate_bear}], "
            f"Risk[atr_mult={atr_stop_multiplier}, risk={risk_leveraged}, alloc={allocation_unleveraged}]"
        )

    def init(self):
        """
        Initialize Kalman filter and state variables.

        Called once before backtesting starts. Sets up:
        - AdaptiveKalmanFilter with VOLUME_ADJUSTED model
        - Regime state tracking
        - Stop-loss tracking
        - Maximum lookback period calculation

        Side Effects:
            - Creates Kalman filter instance
            - Initializes current_regime, current_vehicle, leveraged_stop_price
            - Calculates max_lookback from all parameter periods
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

        # Calculate maximum lookback period needed for any indicator
        self.max_lookback = max(
            self.ema_trend_sb,
            self.ema_trend_mb,
            self.ema_trend_b,
            self.macd_slow_sb,
            self.macd_slow_mb,
            self.macd_slow_b,
            self.atr_period
        )

        logger.info(
            f"{self.name} initialized with Kalman filter and "
            f"max_lookback={self.max_lookback}"
        )

    def on_bar(self, bar: MarketDataEvent):
        """
        Process each bar with hierarchical logic:
        1. Update Kalman filter with QQQ data → trend_strength
        2. Determine regime from trend_strength
        3. Check stop-loss for leveraged positions
        4. If regime changed: Execute hierarchical logic for new regime
        5. If target vehicle changed: Rebalance portfolio

        Args:
            bar: New market data bar with OHLCV data

        Processing Flow:
            QQQ bar → Kalman update → trend_strength → regime determination
            → regime logic (EMA + MACD checks) → target vehicle → rebalance

        Note:
            Only processes signal_symbol (QQQ) bars. Other symbols (TQQQ, SQQQ)
            are accessed via get_closes/highs/lows for calculations.
        """
        # Step 1: Only process signal symbol (QQQ) for regime detection
        if bar.symbol != self.signal_symbol:
            return

        # Step 2: Update Kalman filter with volume-adjusted model
        _, trend_strength = self.kalman_filter.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )

        # Step 3: Determine regime from trend strength
        new_regime = self._determine_regime(trend_strength)

        # Step 4: Check for stop-loss hit BEFORE regime logic
        # (Only applies to leveraged positions: TQQQ/SQQQ)
        if self.current_vehicle in [self.bull_symbol, self.bear_symbol]:
            if self._check_stop_loss(bar):
                # Log context BEFORE liquidation
                if self._trade_logger:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=self.current_vehicle,
                        strategy_state=f"Stop-Loss Exit ({self.current_vehicle})",
                        decision_reason=f"ATR stop triggered at {self.leveraged_stop_price:.2f}",
                        indicator_values={'stop_price': float(self.leveraged_stop_price)},
                        threshold_values={'atr_stop_multiplier': float(self.atr_stop_multiplier)}
                    )

                self._liquidate_position()
                self.current_regime = Regime.CHOP_NEUTRAL
                self.current_vehicle = None
                logger.warning(
                    f"Stop-loss hit at {bar.timestamp}: liquidated at {bar.close}"
                )
                return

        # Step 5: Execute regime logic (even if regime hasn't changed)
        # This allows MACD/EMA to re-evaluate target vehicle within same regime
        target_vehicle = self._execute_regime_logic(new_regime, bar)

        # Step 6: Rebalance if target vehicle changed
        if target_vehicle != self.current_vehicle:
            logger.info(
                f"Vehicle change at {bar.timestamp}: "
                f"{self.current_regime}[{self.current_vehicle}] → "
                f"{new_regime}[{target_vehicle}] "
                f"(trend_strength={trend_strength:.2f})"
            )

            # Log context for LIQUIDATION (if current position exists)
            if self._trade_logger and self.current_vehicle:
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=self.current_vehicle,
                    strategy_state=f"Vehicle Change Exit ({self.current_regime} → {new_regime})",
                    decision_reason=f"Trend strength {trend_strength:.2f}, target vehicle changed",
                    indicator_values={'trend_strength': float(trend_strength)},
                    threshold_values={
                        'strong_bull_threshold': float(self.thresh_strong_bull),
                        'moderate_bull_threshold': float(self.thresh_moderate_bull),
                        'moderate_bear_threshold': float(self.thresh_moderate_bear)
                    }
                )

            # Liquidate current position
            if self.current_vehicle:
                self._liquidate_position()

            # Enter new position (if not CASH)
            if target_vehicle:
                # Log context for NEW ENTRY
                if self._trade_logger:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=target_vehicle,
                        strategy_state=self._get_regime_description(new_regime),
                        decision_reason=self._build_decision_reason(trend_strength, new_regime, bar),
                        indicator_values={
                            'trend_strength': float(trend_strength),
                            'regime': new_regime.value
                        },
                        threshold_values={
                            'strong_bull_threshold': float(self.thresh_strong_bull),
                            'moderate_bull_threshold': float(self.thresh_moderate_bull),
                            'moderate_bear_threshold': float(self.thresh_moderate_bear)
                        }
                    )

                self._enter_position(target_vehicle, bar)

            # Update state
            self.current_regime = new_regime
            self.current_vehicle = target_vehicle

    def _determine_regime(self, trend_strength: Decimal) -> Regime:
        """
        Map trend_strength to regime using thresholds.

        Threshold Logic (from strategy spec):
            trend_strength > 60: STRONG_BULL
            20 < trend_strength <= 60: MODERATE_BULL
            -20 <= trend_strength <= 20: CHOP_NEUTRAL
            trend_strength < -20: BEAR

        Args:
            trend_strength: Value from -100 to +100 from Kalman filter

        Returns:
            Regime enum value

        Example:
            trend_strength = Decimal('75') → Regime.STRONG_BULL
            trend_strength = Decimal('45') → Regime.MODERATE_BULL
            trend_strength = Decimal('5') → Regime.CHOP_NEUTRAL
            trend_strength = Decimal('-45') → Regime.BEAR
        """
        if trend_strength > self.thresh_strong_bull:
            return Regime.STRONG_BULL
        elif trend_strength > self.thresh_moderate_bull:
            return Regime.MODERATE_BULL
        elif trend_strength < self.thresh_moderate_bear:
            return Regime.BEAR
        else:
            return Regime.CHOP_NEUTRAL

    def _execute_regime_logic(self, regime: Regime, bar: MarketDataEvent) -> Optional[str]:
        """
        Execute regime-specific logic to determine target vehicle.

        Each regime has unique EMA/MACD parameters and logic:
        - STRONG_BULL: Aggressive (TQQQ/QQQ/CASH)
        - MODERATE_BULL: Cautious (QQQ/CASH)
        - CHOP_NEUTRAL: CASH (avoid whipsaw)
        - BEAR: Defensive (SQQQ/CASH)

        Args:
            regime: Current market regime
            bar: Current QQQ bar for price reference

        Returns:
            Target vehicle symbol (TQQQ/QQQ/SQQQ) or None (CASH)

        Side Effects:
            - Reads historical bars via get_closes() for EMA/MACD calculations
        """
        if regime == Regime.STRONG_BULL:
            return self._strong_bull_logic(bar)
        elif regime == Regime.MODERATE_BULL:
            return self._moderate_bull_logic(bar)
        elif regime == Regime.BEAR:
            return self._bear_logic(bar)
        else:  # CHOP_NEUTRAL
            return None  # CASH

    def _strong_bull_logic(self, bar: MarketDataEvent) -> Optional[str]:
        """
        Strong Bull regime logic (Aggressive).

        Parameters: EMA(100), MACD(12/26/9)
        Logic:
            - IF QQQ_Price < EMA_Trend_SB → CASH
            - IF QQQ_Price > EMA_Trend_SB AND MACD_SB > Signal_SB → TQQQ
            - IF QQQ_Price > EMA_Trend_SB AND MACD_SB < Signal_SB → QQQ

        Args:
            bar: Current QQQ bar

        Returns:
            Target vehicle: 'TQQQ', 'QQQ', or None (CASH)
        """
        # Get QQQ close prices for EMA and MACD
        closes = self.get_closes(lookback=self.max_lookback, symbol=self.signal_symbol)

        if len(closes) < max(self.ema_trend_sb, self.macd_slow_sb):
            logger.debug(
                f"Insufficient data for Strong Bull logic: {len(closes)} bars"
            )
            return None  # CASH

        # Calculate EMA
        ema_values = ema(closes, self.ema_trend_sb)
        current_ema = Decimal(str(ema_values.iloc[-1]))

        # Check EMA filter first
        if bar.close < current_ema:
            logger.debug(
                f"Strong Bull: Price {bar.close:.2f} < EMA({self.ema_trend_sb})={current_ema:.2f} → CASH"
            )
            return None  # CASH

        # Calculate MACD
        macd_line, signal_line, _ = macd(
            closes,
            fast_period=self.macd_fast_sb,
            slow_period=self.macd_slow_sb,
            signal_period=self.macd_signal_sb
        )
        current_macd = Decimal(str(macd_line.iloc[-1]))
        current_signal = Decimal(str(signal_line.iloc[-1]))

        # MACD decision
        if current_macd > current_signal:
            logger.debug(
                f"Strong Bull: MACD {current_macd:.2f} > Signal {current_signal:.2f} → TQQQ"
            )
            return self.bull_symbol  # TQQQ
        else:
            logger.debug(
                f"Strong Bull: MACD {current_macd:.2f} < Signal {current_signal:.2f} → QQQ"
            )
            return self.defense_symbol  # QQQ

    def _moderate_bull_logic(self, bar: MarketDataEvent) -> Optional[str]:
        """
        Moderate Bull regime logic (Cautious - No 3x Leverage).

        Parameters: EMA(150), MACD(20/50/12)
        Logic:
            - IF QQQ_Price < EMA_Trend_MB → CASH
            - IF QQQ_Price > EMA_Trend_MB AND MACD_MB > Signal_MB → QQQ
            - IF QQQ_Price > EMA_Trend_MB AND MACD_MB < Signal_MB → CASH

        Args:
            bar: Current QQQ bar

        Returns:
            Target vehicle: 'QQQ' or None (CASH)
        """
        # Get QQQ close prices for EMA and MACD
        closes = self.get_closes(lookback=self.max_lookback, symbol=self.signal_symbol)

        if len(closes) < max(self.ema_trend_mb, self.macd_slow_mb):
            logger.debug(
                f"Insufficient data for Moderate Bull logic: {len(closes)} bars"
            )
            return None  # CASH

        # Calculate EMA
        ema_values = ema(closes, self.ema_trend_mb)
        current_ema = Decimal(str(ema_values.iloc[-1]))

        # Check EMA filter first
        if bar.close < current_ema:
            logger.debug(
                f"Moderate Bull: Price {bar.close:.2f} < EMA({self.ema_trend_mb})={current_ema:.2f} → CASH"
            )
            return None  # CASH

        # Calculate MACD
        macd_line, signal_line, _ = macd(
            closes,
            fast_period=self.macd_fast_mb,
            slow_period=self.macd_slow_mb,
            signal_period=self.macd_signal_mb
        )
        current_macd = Decimal(str(macd_line.iloc[-1]))
        current_signal = Decimal(str(signal_line.iloc[-1]))

        # MACD decision (more cautious - only QQQ or CASH)
        if current_macd > current_signal:
            logger.debug(
                f"Moderate Bull: MACD {current_macd:.2f} > Signal {current_signal:.2f} → QQQ"
            )
            return self.defense_symbol  # QQQ
        else:
            logger.debug(
                f"Moderate Bull: MACD {current_macd:.2f} < Signal {current_signal:.2f} → CASH"
            )
            return None  # CASH

    def _bear_logic(self, bar: MarketDataEvent) -> Optional[str]:
        """
        Bear regime logic (Defensive/Short - Inverted).

        Parameters: EMA(100), MACD(12/26/9)
        Logic (Inverted):
            - IF QQQ_Price > EMA_Trend_B → CASH
            - IF QQQ_Price < EMA_Trend_B AND MACD_B < Signal_B → SQQQ
            - IF QQQ_Price < EMA_Trend_B AND MACD_B > Signal_B → CASH

        Args:
            bar: Current QQQ bar

        Returns:
            Target vehicle: 'SQQQ' or None (CASH)
        """
        # Get QQQ close prices for EMA and MACD
        closes = self.get_closes(lookback=self.max_lookback, symbol=self.signal_symbol)

        if len(closes) < max(self.ema_trend_b, self.macd_slow_b):
            logger.debug(
                f"Insufficient data for Bear logic: {len(closes)} bars"
            )
            return None  # CASH

        # Calculate EMA
        ema_values = ema(closes, self.ema_trend_b)
        current_ema = Decimal(str(ema_values.iloc[-1]))

        # Check EMA filter first (INVERTED: price must be BELOW EMA)
        if bar.close > current_ema:
            logger.debug(
                f"Bear: Price {bar.close:.2f} > EMA({self.ema_trend_b})={current_ema:.2f} → CASH (inverted)"
            )
            return None  # CASH

        # Calculate MACD
        macd_line, signal_line, _ = macd(
            closes,
            fast_period=self.macd_fast_b,
            slow_period=self.macd_slow_b,
            signal_period=self.macd_signal_b
        )
        current_macd = Decimal(str(macd_line.iloc[-1]))
        current_signal = Decimal(str(signal_line.iloc[-1]))

        # MACD decision (INVERTED: < signal for SQQQ entry)
        if current_macd < current_signal:
            logger.debug(
                f"Bear: MACD {current_macd:.2f} < Signal {current_signal:.2f} → SQQQ (inverted)"
            )
            return self.bear_symbol  # SQQQ
        else:
            logger.debug(
                f"Bear: MACD {current_macd:.2f} > Signal {current_signal:.2f} → CASH (inverted)"
            )
            return None  # CASH

    def _enter_position(self, vehicle: str, bar: MarketDataEvent):
        """
        Enter position for target vehicle.

        Delegates to vehicle-specific entry methods:
        - TQQQ: ATR-based risk sizing with stop-loss
        - SQQQ: ATR-based risk sizing with stop-loss
        - QQQ: Percentage allocation, no stop-loss

        Args:
            vehicle: Target vehicle symbol (TQQQ/QQQ/SQQQ)
            bar: Current QQQ bar for reference

        Side Effects:
            - Calls _enter_leveraged_long, _enter_leveraged_short, or _enter_unleveraged
            - Generates buy signals via self.buy()
            - Sets leveraged_stop_price (for TQQQ/SQQQ only)
        """
        if vehicle == self.bull_symbol:
            self._enter_leveraged_long(bar)
        elif vehicle == self.bear_symbol:
            self._enter_leveraged_short(bar)
        elif vehicle == self.defense_symbol:
            self._enter_unleveraged(bar)
        else:
            raise ValueError(f"Unknown vehicle: {vehicle}")

    def _enter_leveraged_long(self, bar: MarketDataEvent):
        """
        Enter TQQQ position with ATR-based position sizing.

        Position Sizing (from spec):
        - Total_Dollar_Risk = Portfolio_Equity × Risk_Leveraged (2.5%)
        - Dollar_Risk_Per_Share = TQQQ_ATR × ATR_Stop_Multiplier (3.0x)
        - Shares_To_Buy = Total_Dollar_Risk / Dollar_Risk_Per_Share
        - Stop-Loss = Fill_Price - Dollar_Risk_Per_Share

        Args:
            bar: Current QQQ bar (for timestamp context)

        Side Effects:
            - Generates BUY signal for TQQQ
            - Sets leveraged_stop_price (will be calculated after fill)
        """
        # Get TQQQ data for ATR calculation
        closes = self.get_closes(lookback=self.atr_period, symbol=self.bull_symbol)
        highs = self.get_highs(lookback=self.atr_period, symbol=self.bull_symbol)
        lows = self.get_lows(lookback=self.atr_period, symbol=self.bull_symbol)

        if len(closes) < self.atr_period:
            logger.debug(
                f"Insufficient TQQQ data for ATR: {len(closes)} < {self.atr_period}"
            )
            return  # Not enough data

        # Calculate ATR
        atr_value = atr(highs, lows, closes, self.atr_period).iloc[-1]
        dollar_risk_per_share = Decimal(str(atr_value)) * self.atr_stop_multiplier

        # Execute buy order using portfolio percentage and risk_per_share
        # Portfolio module will calculate actual shares
        self.buy(
            self.bull_symbol,
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

        Position Sizing (from spec):
        - Total_Dollar_Risk = Portfolio_Equity × Risk_Leveraged (2.5%)
        - Dollar_Risk_Per_Share = SQQQ_ATR × ATR_Stop_Multiplier (3.0x)
        - Shares_To_Buy = Total_Dollar_Risk / Dollar_Risk_Per_Share
        - Stop-Loss = Fill_Price - Dollar_Risk_Per_Share

        Args:
            bar: Current QQQ bar (for timestamp context)

        Side Effects:
            - Generates BUY signal for SQQQ (SQQQ is inverse ETF)
            - Sets leveraged_stop_price (will be calculated after fill)

        Note:
            SQQQ is an inverse ETF, so we BUY it to express bearish view.
        """
        # Get SQQQ data for ATR calculation
        closes = self.get_closes(lookback=self.atr_period, symbol=self.bear_symbol)
        highs = self.get_highs(lookback=self.atr_period, symbol=self.bear_symbol)
        lows = self.get_lows(lookback=self.atr_period, symbol=self.bear_symbol)

        if len(closes) < self.atr_period:
            logger.debug(
                f"Insufficient SQQQ data for ATR: {len(closes)} < {self.atr_period}"
            )
            return  # Not enough data

        # Calculate ATR
        atr_value = atr(highs, lows, closes, self.atr_period).iloc[-1]
        dollar_risk_per_share = Decimal(str(atr_value)) * self.atr_stop_multiplier

        # Execute buy order (SQQQ is inverse, so BUY for bearish exposure)
        self.buy(
            self.bear_symbol,
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

        Position Sizing (from spec):
        - Dollars_To_Allocate = Portfolio_Equity × Allocation_Unleveraged (80%)
        - Shares_To_Buy = Dollars_To_Allocate / QQQ_Open_Price
        - Stop-Loss: None (managed by regime filters)

        Args:
            bar: Current QQQ bar (for price context)

        Side Effects:
            - Generates BUY signal for QQQ
            - Clears leveraged_stop_price (no stop for QQQ)
        """
        # Execute buy order using percentage allocation
        # Portfolio module calculates shares from allocation percentage
        self.buy(
            self.defense_symbol,
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

        Stop-Loss Logic (from spec):
        - Only applies to TQQQ/SQQQ positions
        - Uses bar.low for conservative check (worst intraday price)
        - Stop = entry_price - (ATR × stop_multiplier)
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
                    atr_value = atr(highs, lows, closes, self.atr_period).iloc[-1]
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
            Human-readable regime description with trading parameters

        Example:
            Regime.STRONG_BULL → "Regime 1: Strong Bullish (TQQQ/QQQ/CASH, EMA100, MACD12/26/9)"
        """
        descriptions = {
            Regime.STRONG_BULL: (
                f"Regime 1: Strong Bullish (TQQQ/QQQ/CASH, "
                f"EMA{self.ema_trend_sb}, MACD{self.macd_fast_sb}/{self.macd_slow_sb}/{self.macd_signal_sb})"
            ),
            Regime.MODERATE_BULL: (
                f"Regime 2: Moderate Bullish (QQQ/CASH, "
                f"EMA{self.ema_trend_mb}, MACD{self.macd_fast_mb}/{self.macd_slow_mb}/{self.macd_signal_mb})"
            ),
            Regime.CHOP_NEUTRAL: "Regime 3: Choppy/Neutral (CASH)",
            Regime.BEAR: (
                f"Regime 4: Bearish (SQQQ/CASH, "
                f"EMA{self.ema_trend_b}, MACD{self.macd_fast_b}/{self.macd_slow_b}/{self.macd_signal_b})"
            )
        }
        return descriptions[regime]

    def _build_decision_reason(
        self,
        trend_strength: Decimal,
        regime: Regime,
        bar: MarketDataEvent
    ) -> str:
        """
        Build decision rationale from trend strength, regime, and indicator values.

        Args:
            trend_strength: Current trend strength value (-100 to +100)
            regime: Determined regime based on trend strength
            bar: Current QQQ bar for price reference

        Returns:
            Human-readable explanation of why this regime and vehicle were chosen

        Example:
            "Trend strength 75.30 > strong_bull threshold 60.00, "
            "QQQ_Price 450.25 > EMA(100) 445.50, MACD 2.35 > Signal 1.80 → TQQQ"
        """
        # Base threshold explanation
        if regime == Regime.STRONG_BULL:
            reason = f"Trend strength {trend_strength:.2f} > strong_bull threshold {self.thresh_strong_bull}"
        elif regime == Regime.MODERATE_BULL:
            reason = (
                f"Trend strength {trend_strength:.2f} > moderate_bull threshold "
                f"{self.thresh_moderate_bull} and <= strong_bull threshold {self.thresh_strong_bull}"
            )
        elif regime == Regime.BEAR:
            reason = f"Trend strength {trend_strength:.2f} < moderate_bear threshold {self.thresh_moderate_bear}"
        else:  # CHOP_NEUTRAL
            reason = (
                f"Trend strength {trend_strength:.2f} between moderate_bear threshold "
                f"{self.thresh_moderate_bear} and moderate_bull threshold {self.thresh_moderate_bull} (choppy)"
            )

        return reason
