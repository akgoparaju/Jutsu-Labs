"""
Hierarchical Adaptive v3.5: Binarized Regime Allocator with Hysteresis

v3.5 introduces four major structural improvements:

1. **Binarized Volatility (3x3 → 3x2 Grid)**:
   - Eliminated "Medium Vol" - leverage decay is binary (safe or not)
   - 6-cell regime grid (Bull/Side/Bear × Low/High Vol)

2. **Rolling Z-Score Volatility**:
   - Replaced static percentile thresholds (look-ahead bias)
   - Adapts to market baseline: Z = (σ_t - μ) / σ
   - Robust across decades without magic numbers

3. **Hysteresis State Machine**:
   - Prevents flicker when volatility near threshold
   - Latch mechanism: High requires crossing upper bound, Low requires crossing lower bound
   - Deadband behavior between thresholds

4. **Removed SQQQ (Toxic Asset)**:
   - SQQQ decay extreme in high vol (only time v3.0 allowed it)
   - Replaced with Cash or PSQ (-1x) in bearish regimes
   - Negative expectancy in high-vol chopping eliminated

Key Architecture:
- Hierarchical Trend: Fast (Kalman) gated by Slow (SMA 50/200)
- Volatility Z-Score: Rolling 21-day realized vol vs 126-day baseline
- 6-Cell Allocation Matrix: (Trend × Vol) → {TQQQ, QQQ, PSQ, Cash}
- Vol-Crush Override: 20% vol drop in 5 days forces Low state
- Hybrid Leverage: Base weights × leverage_scalar (0.8-1.2)

Performance Targets:
    - Processing Speed: <1ms per bar
    - Memory: O(max_lookback_period)
    - Backtest: 2010-2025 (15 years) in <20 seconds
"""
from decimal import Decimal
from typing import Optional
import logging
import pandas as pd
import numpy as np

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel
from jutsu_engine.indicators.technical import sma, annualized_volatility
from jutsu_engine.performance.trade_logger import TradeLogger

logger = logging.getLogger('STRATEGY.HIERARCHICAL_ADAPTIVE_V3_5')


class Hierarchical_Adaptive_v3_5(Strategy):
    """
    Hierarchical Adaptive v3.5: Binarized Regime Allocator

    Six-cell allocation system combining hierarchical trend (Kalman + SMA)
    with binarized volatility (rolling Z-score with hysteresis).

    Regime Grid (3x2):
        | Trend      | Low Vol               | High Vol                  |
        |------------|------------------------|---------------------------|
        | BullStrong | Kill Zone (60/40 T/Q) | Fragile (100% QQQ)       |
        | Sideways   | Drift (20/80 T/Q)     | Chop (100% Cash)         |
        | BearStrong | Grind (50/50 Q/Cash)  | Crash (100% Cash or PSQ) |

    Key Features:
    - Hierarchical Trend: T_norm (Kalman) gated by SMA_fast/SMA_slow
    - Volatility Z-Score: Adaptive regime detection
    - Hysteresis: Prevents regime flicker
    - Vol-Crush Override: Rapid volatility collapse detection
    - Hybrid Allocation: Base weights scaled by leverage_scalar
    - Automatic Warmup: Calculates required warmup bars based on indicator requirements
      (max of sma_slow+10 and vol_baseline+vol_realized, typically 147-210 bars)

    Example:
        strategy = Hierarchical_Adaptive_v3_5(
            sma_fast=50,
            sma_slow=200,
            upper_thresh_z=Decimal("1.0"),
            lower_thresh_z=Decimal("0.0"),
            vol_crush_threshold=Decimal("-0.20"),
            leverage_scalar=Decimal("1.0"),
            use_inverse_hedge=False,  # PSQ toggle
            ...
        )
    """

    def __init__(
        self,
        # ==================================================================
        # KALMAN TREND PARAMETERS (6 parameters from v2.8)
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("50.0"),

        # ==================================================================
        # STRUCTURAL TREND PARAMETERS (4 parameters - NEW)
        # ==================================================================
        sma_fast: int = 40,
        sma_slow: int = 140,
        t_norm_bull_thresh: Decimal = Decimal("0.2"),
        t_norm_bear_thresh: Decimal = Decimal("-0.3"),

        # ==================================================================
        # VOLATILITY Z-SCORE PARAMETERS (4 parameters - NEW)
        # ==================================================================
        realized_vol_window: int = 21,
        vol_baseline_window: int = 126,
        upper_thresh_z: Decimal = Decimal("1.0"),
        lower_thresh_z: Decimal = Decimal("0.2"),

        # ==================================================================
        # VOL-CRUSH OVERRIDE (2 parameters - NEW)
        # ==================================================================
        vol_crush_threshold: Decimal = Decimal("-0.15"),
        vol_crush_lookback: int = 5,

        # ==================================================================
        # ALLOCATION PARAMETERS (2 parameters - NEW)
        # ==================================================================
        leverage_scalar: Decimal = Decimal("1.0"),

        # ==================================================================
        # INSTRUMENT TOGGLES (2 parameters - NEW)
        # ==================================================================
        use_inverse_hedge: bool = False,
        w_PSQ_max: Decimal = Decimal("0.5"),

        # ==================================================================
        # REBALANCING CONTROL (1 parameter)
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # SYMBOL CONFIGURATION (5 parameters)
        # ==================================================================
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        inverse_hedge_symbol: str = "PSQ",

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Hierarchical_Adaptive_v3_5"
    ):
        """
        Initialize Hierarchical Adaptive v3.5 strategy.

        v3.5 introduces binarized volatility regime detection with hysteresis,
        hierarchical trend classification, and hybrid allocation system.

        Args:
            measurement_noise: Kalman filter measurement noise (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 15)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 50.0)
            sma_fast: Fast structural trend SMA period (default: 50, range: [40, 60])
            sma_slow: Slow structural trend SMA period (default: 200, range: [180, 220])
            t_norm_bull_thresh: T_norm threshold for BullStrong (default: 0.3)
            t_norm_bear_thresh: T_norm threshold for BearStrong (default: -0.3)
            realized_vol_window: Rolling realized vol window (default: 21)
            vol_baseline_window: Volatility baseline statistics window (default: 126)
            upper_thresh_z: Z-score threshold for High vol (default: 1.0, range: [0.8, 1.2])
            lower_thresh_z: Z-score threshold for Low vol (default: 0.0, range: [-0.2, 0.2])
            vol_crush_threshold: Vol-crush percentage threshold (default: -0.20, range: [-0.15, -0.25])
            vol_crush_lookback: Vol-crush detection lookback period (default: 5)
            leverage_scalar: Allocation scaling factor (default: 1.0, range: [0.8, 1.2])
            use_inverse_hedge: Enable PSQ in bearish regimes (default: False)
            w_PSQ_max: Maximum PSQ weight (default: 0.5 = 50%)
            rebalance_threshold: Weight drift threshold for rebalancing (default: 0.025 = 2.5%)
            signal_symbol: Signal generation symbol (default: 'QQQ')
            core_long_symbol: 1x long symbol (default: 'QQQ')
            leveraged_long_symbol: 3x long symbol (default: 'TQQQ')
            inverse_hedge_symbol: -1x short symbol (default: 'PSQ')
            trade_logger: Optional TradeLogger (default: None)
            name: Strategy name (default: 'Hierarchical_Adaptive_v3_5')
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate parameters
        if sma_fast >= sma_slow:
            raise ValueError(
                f"sma_fast ({sma_fast}) must be < sma_slow ({sma_slow})"
            )

        if not (t_norm_bear_thresh < Decimal("0") < t_norm_bull_thresh):
            raise ValueError(
                f"Trend thresholds must satisfy: "
                f"t_norm_bear_thresh ({t_norm_bear_thresh}) < 0 < t_norm_bull_thresh ({t_norm_bull_thresh})"
            )

        if upper_thresh_z <= lower_thresh_z:
            raise ValueError(
                f"upper_thresh_z ({upper_thresh_z}) must be > lower_thresh_z ({lower_thresh_z})"
            )

        if vol_crush_threshold >= Decimal("0"):
            raise ValueError(
                f"vol_crush_threshold must be negative, got {vol_crush_threshold}"
            )

        if not (Decimal("0.5") <= leverage_scalar <= Decimal("1.5")):
            raise ValueError(
                f"leverage_scalar must be in [0.5, 1.5], got {leverage_scalar}"
            )

        if not (Decimal("0.0") < w_PSQ_max <= Decimal("1.0")):
            raise ValueError(
                f"w_PSQ_max must be in (0, 1], got {w_PSQ_max}"
            )

        if rebalance_threshold <= Decimal("0"):
            raise ValueError(
                f"rebalance_threshold must be positive, got {rebalance_threshold}"
            )

        # Store all parameters
        self.measurement_noise = measurement_noise
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.T_max = T_max

        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.t_norm_bull_thresh = t_norm_bull_thresh
        self.t_norm_bear_thresh = t_norm_bear_thresh

        self.realized_vol_window = realized_vol_window
        self.vol_baseline_window = vol_baseline_window
        self.upper_thresh_z = upper_thresh_z
        self.lower_thresh_z = lower_thresh_z

        self.vol_crush_threshold = vol_crush_threshold
        self.vol_crush_lookback = vol_crush_lookback

        self.leverage_scalar = leverage_scalar

        self.use_inverse_hedge = use_inverse_hedge
        self.w_PSQ_max = w_PSQ_max

        self.rebalance_threshold = rebalance_threshold

        self.signal_symbol = signal_symbol
        self.core_long_symbol = core_long_symbol
        self.leveraged_long_symbol = leveraged_long_symbol
        self.inverse_hedge_symbol = inverse_hedge_symbol

        # State variables
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.vol_state: str = "Low"  # Hysteresis state (persists across bars)
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_psq_weight: Decimal = Decimal("0")

        logger.info(
            f"Initialized {name} (v3.5 - BINARIZED REGIME): "
            f"SMA_fast={sma_fast}, SMA_slow={sma_slow}, "
            f"upper_thresh_z={upper_thresh_z}, lower_thresh_z={lower_thresh_z}, "
            f"leverage_scalar={leverage_scalar}, use_inverse_hedge={use_inverse_hedge}"
        )

    def init(self) -> None:
        """Initialize strategy state."""
        # Initialize Kalman filter
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=float(self.measurement_noise),
            process_noise_1=float(self.process_noise_1),
            process_noise_2=float(self.process_noise_2),
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness,
            return_signed=True
        )

        # Initialize hysteresis state
        self.vol_state = "Low"  # Default to Low on startup
        self.current_tqqq_weight = Decimal("0")
        self.current_qqq_weight = Decimal("0")
        self.current_psq_weight = Decimal("0")

        logger.info(
            f"Initialized {self.name} (v3.5) with hysteresis state: {self.vol_state}"
        )

    def get_required_warmup_bars(self) -> int:
        """
        Calculate warmup bars needed for Hierarchical Adaptive v3.5 indicators.

        This strategy uses two indicator systems that require warmup:
        1. SMA indicators: sma_slow + buffer (10 bars)
        2. Volatility z-score: vol_baseline_window (126) + realized_vol_window (21)

        Returns:
            int: Maximum lookback required by all indicator systems

        Notes:
            - Ensures sufficient warmup for both SMA and volatility systems
            - Prevents "Volatility z-score calculation failed" errors
            - Warmup bars are fetched BEFORE start_date (don't consume trading days)

        Example:
            With sma_slow=140, vol_baseline=126, vol_realized=21:
            Returns max(140+10, 126+21) = max(150, 147) = 150

            With sma_slow=75, vol_baseline=126, vol_realized=21:
            Returns max(75+10, 126+21) = max(85, 147) = 147
        """
        # Calculate lookback for SMA indicators
        sma_lookback = self.sma_slow + 10

        # Calculate lookback for volatility z-score
        vol_lookback = self.vol_baseline_window + self.realized_vol_window

        # Return maximum of all indicator requirements
        required_warmup = max(sma_lookback, vol_lookback)

        return required_warmup

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through v3.5 binarized regime allocator.

        Pipeline:
        1. Calculate Kalman trend (T_norm) - Fast signal
        2. Calculate SMA_fast, SMA_slow - Slow structural filter
        3. Calculate realized volatility and z-score
        4. Apply hysteresis to determine VolState (Low/High)
        5. Check vol-crush override
        6. Classify TrendState (BullStrong/Sideways/BearStrong)
        7. Map to 6-cell allocation matrix
        8. Apply leverage_scalar
        9. Rebalance if needed
        """
        # Only process signal symbol
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check
        min_warmup = self.sma_slow + 20
        if len(self._bars) < min_warmup:
            logger.debug(f"Warmup: {len(self._bars)}/{min_warmup} bars")
            return

        # 1. Calculate Kalman trend
        filtered_price, trend_strength_signed = self.kalman_filter.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
        T_norm = self._calculate_kalman_trend(Decimal(str(trend_strength_signed)))

        # 2. Calculate structural trend
        # Calculate required lookback accounting for ALL indicator needs:
        # - SMA indicators need: sma_slow + buffer (10 bars)
        # - Volatility z-score needs: vol_baseline_window (126) + realized_vol_window (21) = 147 bars
        # Use max() to ensure sufficient warmup for both indicator systems
        sma_lookback = self.sma_slow + 10
        vol_lookback = self.vol_baseline_window + self.realized_vol_window
        required_lookback = max(sma_lookback, vol_lookback)

        closes = self.get_closes(
            lookback=required_lookback,
            symbol=self.signal_symbol
        )
        sma_fast_series = sma(closes, self.sma_fast)
        sma_slow_series = sma(closes, self.sma_slow)

        if pd.isna(sma_fast_series.iloc[-1]) or pd.isna(sma_slow_series.iloc[-1]):
            logger.warning("SMA calculation returned NaN")
            return

        sma_fast_val = Decimal(str(sma_fast_series.iloc[-1]))
        sma_slow_val = Decimal(str(sma_slow_series.iloc[-1]))

        # 3. Calculate volatility z-score
        z_score = self._calculate_volatility_zscore(closes)

        if z_score is None:
            logger.error("Volatility z-score calculation failed - insufficient warmup data")
            return

        # 4. Apply hysteresis to determine VolState
        self._apply_hysteresis(z_score)

        # 5. Check vol-crush override
        vol_crush_triggered = self._check_vol_crush_override(closes)

        # 6. Classify trend regime
        trend_state = self._classify_trend_regime(T_norm, sma_fast_val, sma_slow_val)

        # Apply vol-crush override to trend
        if vol_crush_triggered:
            if trend_state == "BearStrong":
                logger.info("Vol-crush override: BearStrong → Sideways")
                trend_state = "Sideways"

        # 7-8. Get cell allocation and apply leverage_scalar
        cell_id = self._get_cell_id(trend_state, self.vol_state)
        w_TQQQ, w_QQQ, w_PSQ, w_cash = self._get_cell_allocation(cell_id)

        # Apply leverage_scalar to base weights
        w_TQQQ = w_TQQQ * self.leverage_scalar
        w_QQQ = w_QQQ * self.leverage_scalar
        w_PSQ = w_PSQ * self.leverage_scalar

        # Normalize to ensure sum = 1.0
        total_weight = w_TQQQ + w_QQQ + w_PSQ + w_cash
        if total_weight > Decimal("0"):
            w_TQQQ = w_TQQQ / total_weight
            w_QQQ = w_QQQ / total_weight
            w_PSQ = w_PSQ / total_weight
            w_cash = w_cash / total_weight

        # 9. Check rebalancing threshold
        needs_rebalance = self._check_rebalancing_threshold(w_TQQQ, w_QQQ, w_PSQ)

        # Log context
        logger.info(
            f"[{bar.timestamp}] v3.5 Regime | "
            f"T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f}, SMA_slow={sma_slow_val:.2f} → "
            f"TrendState={trend_state} | "
            f"z_score={z_score:.3f} → VolState={self.vol_state} (hysteresis) | "
            f"vol_crush={vol_crush_triggered} | "
            f"Cell={cell_id} → w_TQQQ={w_TQQQ:.3f}, w_QQQ={w_QQQ:.3f}, w_PSQ={w_PSQ:.3f}, "
            f"w_cash={w_cash:.3f} (leverage_scalar={self.leverage_scalar})"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                for symbol in [self.core_long_symbol, self.leveraged_long_symbol, self.inverse_hedge_symbol]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v3.5 Cell {cell_id}: {trend_state}/{self.vol_state}",
                        decision_reason=(
                            f"Kalman T_norm={T_norm:.3f}, SMA_fast={sma_fast_val:.2f} vs SMA_slow={sma_slow_val:.2f}, "
                            f"z_score={z_score:.3f}, vol_crush={vol_crush_triggered}"
                        ),
                        indicator_values={
                            'T_norm': float(T_norm),
                            'SMA_fast': float(sma_fast_val),
                            'SMA_slow': float(sma_slow_val),
                            'z_score': float(z_score)
                        },
                        threshold_values={
                            'upper_thresh_z': float(self.upper_thresh_z),
                            'lower_thresh_z': float(self.lower_thresh_z),
                            'leverage_scalar': float(self.leverage_scalar)
                        }
                    )

            self._execute_rebalance(w_TQQQ, w_QQQ, w_PSQ)

    # ===== Calculation methods =====

    def _calculate_kalman_trend(self, trend_strength_signed: Decimal) -> Decimal:
        """
        Calculate normalized SIGNED Kalman trend.

        Args:
            trend_strength_signed: Raw signed trend strength from Kalman filter

        Returns:
            T_norm ∈ [-1.0, +1.0]
        """
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_structural_trend(
        self,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """
        Calculate structural trend from SMA crossover.

        Args:
            sma_fast_val: Fast SMA value
            sma_slow_val: Slow SMA value

        Returns:
            "Bull" if SMA_fast > SMA_slow, else "Bear"
        """
        return "Bull" if sma_fast_val > sma_slow_val else "Bear"

    def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
        """
        Calculate rolling z-score of realized volatility.

        Formula:
            σ_t = Realized Volatility (21-day annualized)
            μ_vol = Mean(σ, 126-day rolling window)
            σ_vol = Std(σ, 126-day rolling window)
            z_score = (σ_t - μ_vol) / σ_vol

        Args:
            closes: Price series for volatility calculation

        Returns:
            z_score or None if insufficient data
        """
        if len(closes) < self.vol_baseline_window + self.realized_vol_window:
            return None

        # Calculate realized volatility (annualized)
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)

        if len(vol_series) < self.vol_baseline_window:
            return None

        # Calculate rolling baseline statistics
        vol_values = vol_series.tail(self.vol_baseline_window)

        if len(vol_values) < self.vol_baseline_window:
            return None

        # Convert to Decimal for precision
        vol_mean = Decimal(str(vol_values.mean()))
        vol_std = Decimal(str(vol_values.std()))

        if vol_std == Decimal("0"):
            return Decimal("0")

        # Current realized vol
        sigma_t = Decimal(str(vol_series.iloc[-1]))

        # Z-score
        z_score = (sigma_t - vol_mean) / vol_std

        return z_score

    def _apply_hysteresis(self, z_score: Decimal) -> None:
        """
        Apply hysteresis state machine to volatility state.

        Hysteresis Logic:
            if z_score > upper_thresh_z:
                VolState = "High"
            elif z_score < lower_thresh_z:
                VolState = "Low"
            else:
                VolState = Previous_VolState (deadband)

        Initialization (Day 1):
            if z_score > 0: VolState = "High"
            else: VolState = "Low"

        Args:
            z_score: Current volatility z-score
        """
        # Day 1 initialization
        if len(self._bars) == max(self.sma_slow, self.vol_baseline_window) + 20:
            self.vol_state = "High" if z_score > Decimal("0") else "Low"
            logger.info(f"Initialized VolState: {self.vol_state} (z_score={z_score:.3f})")
            return

        # Hysteresis logic
        if z_score > self.upper_thresh_z:
            if self.vol_state != "High":
                logger.info(
                    f"VolState transition: {self.vol_state} → High (z_score={z_score:.3f} > {self.upper_thresh_z})"
                )
                self.vol_state = "High"
        elif z_score < self.lower_thresh_z:
            if self.vol_state != "Low":
                logger.info(
                    f"VolState transition: {self.vol_state} → Low (z_score={z_score:.3f} < {self.lower_thresh_z})"
                )
                self.vol_state = "Low"
        # else: Deadband - maintain current state

    def _check_vol_crush_override(self, closes: pd.Series) -> bool:
        """
        Check for vol-crush override (V-shaped recovery detection).

        Trigger: If realized volatility drops by >20% in 5 days.
        Action: Force VolState = "Low", override BearStrong → Sideways.

        Args:
            closes: Price series for volatility calculation

        Returns:
            True if vol-crush triggered, False otherwise
        """
        if len(closes) < self.realized_vol_window + self.vol_crush_lookback:
            return False

        # Calculate realized volatility series
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_window)

        if len(vol_series) < self.vol_crush_lookback + 1:
            return False

        # Current and historical volatility
        sigma_t = Decimal(str(vol_series.iloc[-1]))
        sigma_t_minus_N = Decimal(str(vol_series.iloc[-(self.vol_crush_lookback + 1)]))

        if sigma_t_minus_N == Decimal("0"):
            return False

        # Calculate percentage change
        vol_change = (sigma_t - sigma_t_minus_N) / sigma_t_minus_N

        # Check if vol-crush threshold breached
        if vol_change < self.vol_crush_threshold:
            logger.info(
                f"Vol-crush override triggered: "
                f"vol drop {vol_change:.1%} in {self.vol_crush_lookback} days"
            )
            # Force VolState to Low
            self.vol_state = "Low"
            return True

        return False

    def _classify_trend_regime(
        self,
        T_norm: Decimal,
        sma_fast_val: Decimal,
        sma_slow_val: Decimal
    ) -> str:
        """
        Classify trend regime using hierarchical logic.

        Classification Rules:
        1. BullStrong: (T_norm > 0.3) AND (SMA_fast > SMA_slow)
        2. BearStrong: (T_norm < -0.3) AND (SMA_fast < SMA_slow)
        3. Sideways: All other conditions

        Args:
            T_norm: Normalized Kalman trend
            sma_fast_val: Fast SMA value
            sma_slow_val: Slow SMA value

        Returns:
            "BullStrong", "BearStrong", or "Sideways"
        """
        is_struct_bull = sma_fast_val > sma_slow_val

        if T_norm > self.t_norm_bull_thresh and is_struct_bull:
            return "BullStrong"
        elif T_norm < self.t_norm_bear_thresh and not is_struct_bull:
            return "BearStrong"
        else:
            return "Sideways"

    def _get_cell_id(self, trend_state: str, vol_state: str) -> int:
        """
        Map (TrendState, VolState) to cell ID (1-6).

        Cell Mapping:
            1: BullStrong + Low
            2: BullStrong + High
            3: Sideways + Low
            4: Sideways + High
            5: BearStrong + Low
            6: BearStrong + High

        Args:
            trend_state: "BullStrong", "Sideways", or "BearStrong"
            vol_state: "Low" or "High"

        Returns:
            cell_id ∈ [1, 6]
        """
        if trend_state == "BullStrong":
            return 1 if vol_state == "Low" else 2
        elif trend_state == "Sideways":
            return 3 if vol_state == "Low" else 4
        else:  # BearStrong
            return 5 if vol_state == "Low" else 6

    def _get_cell_allocation(self, cell_id: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Get base allocation weights for cell ID.

        6-Cell Allocation Matrix (Base Weights):
            Cell 1 (Bull/Low):   60% TQQQ, 40% QQQ (Net Beta ~2.2)
            Cell 2 (Bull/High):  0% TQQQ, 100% QQQ (Net Beta 1.0)
            Cell 3 (Side/Low):   20% TQQQ, 80% QQQ (Net Beta ~1.4)
            Cell 4 (Side/High):  0% TQQQ, 0% QQQ, 100% Cash (Net Beta 0.0)
            Cell 5 (Bear/Low):   0% TQQQ, 50% QQQ, 50% Cash (Net Beta 0.5)
            Cell 6a (Bear/High, no PSQ): 0% TQQQ, 0% QQQ, 100% Cash (Net Beta 0.0)
            Cell 6b (Bear/High, PSQ): 0% TQQQ, 0% QQQ, 50% PSQ, 50% Cash (Net Beta -0.5)

        Args:
            cell_id: Cell identifier [1-6]

        Returns:
            (w_TQQQ, w_QQQ, w_PSQ, w_cash) base weights (sum = 1.0)
        """
        if cell_id == 1:
            # Kill Zone: Aggressive upside
            return (Decimal("0.6"), Decimal("0.4"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 2:
            # Fragile Trend: De-risk
            return (Decimal("0.0"), Decimal("1.0"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 3:
            # Drift Capture: Slow grind
            return (Decimal("0.2"), Decimal("0.8"), Decimal("0.0"), Decimal("0.0"))
        elif cell_id == 4:
            # Chopping Block: Avoid whipsaw
            return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))
        elif cell_id == 5:
            # Grind: Defensive hold
            return (Decimal("0.0"), Decimal("0.5"), Decimal("0.0"), Decimal("0.5"))
        elif cell_id == 6:
            # Crash: Capital preservation
            if self.use_inverse_hedge:
                # Cell 6b: Use PSQ (capped)
                w_PSQ = min(Decimal("0.5"), self.w_PSQ_max)
                w_cash = Decimal("1.0") - w_PSQ
                return (Decimal("0.0"), Decimal("0.0"), w_PSQ, w_cash)
            else:
                # Cell 6a: 100% Cash
                return (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("1.0"))
        else:
            raise ValueError(f"Invalid cell_id: {cell_id}")

    def _check_rebalancing_threshold(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal
    ) -> bool:
        """
        Check if portfolio weights drifted beyond threshold.

        Args:
            target_tqqq_weight: Target TQQQ weight
            target_qqq_weight: Target QQQ weight
            target_psq_weight: Target PSQ weight

        Returns:
            True if rebalancing needed, False otherwise
        """
        weight_deviation = (
            abs(self.current_tqqq_weight - target_tqqq_weight) +
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_psq_weight - target_psq_weight)
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance(
        self,
        target_tqqq_weight: Decimal,
        target_qqq_weight: Decimal,
        target_psq_weight: Decimal
    ) -> None:
        """
        Rebalance portfolio to target weights using two-phase execution.

        Phase 1: Reduce positions (execute SELLs first to free cash)
        Phase 2: Increase positions (execute BUYs with freed cash)

        Args:
            target_tqqq_weight: Target TQQQ weight
            target_qqq_weight: Target QQQ weight
            target_psq_weight: Target PSQ weight
        """
        # Helper: Check if allocation is sufficient for at least 1 share
        def _validate_weight(symbol: str, weight: Decimal) -> Decimal:
            if weight <= Decimal("0"):
                return Decimal("0")

            # Get latest price
            closes = self.get_closes(lookback=1, symbol=symbol)
            if closes.empty:
                return Decimal("0")

            price = Decimal(str(closes.iloc[-1]))
            if price <= Decimal("0"):
                return Decimal("0")

            # Calculate portfolio equity
            portfolio_equity = self._cash
            for sym, qty in self._positions.items():
                if qty > 0:
                    symbol_bars = [b for b in self._bars if b.symbol == sym]
                    if symbol_bars:
                        latest_price = symbol_bars[-1].close
                        portfolio_equity += Decimal(str(qty)) * latest_price

            allocation_value = portfolio_equity * weight
            if allocation_value < price:
                logger.debug(
                    f"Skipping {symbol} buy: Allocation ${allocation_value:.2f} < Price ${price:.2f}"
                )
                return Decimal("0")

            return weight

        # Validate weights before execution
        target_tqqq_weight = _validate_weight(self.leveraged_long_symbol, target_tqqq_weight)
        target_qqq_weight = _validate_weight(self.core_long_symbol, target_qqq_weight)
        target_psq_weight = _validate_weight(self.inverse_hedge_symbol, target_psq_weight)

        # Phase 1: REDUCE positions (execute SELLs first)

        # TQQQ: Reduce if needed
        if target_tqqq_weight == Decimal("0"):
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))
        elif target_tqqq_weight > Decimal("0") and target_tqqq_weight < self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # QQQ: Reduce if needed
        if target_qqq_weight == Decimal("0"):
            self.sell(self.core_long_symbol, Decimal("0.0"))
        elif target_qqq_weight > Decimal("0") and target_qqq_weight < self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # PSQ: Reduce if needed
        if target_psq_weight == Decimal("0"):
            self.sell(self.inverse_hedge_symbol, Decimal("0.0"))
        elif target_psq_weight > Decimal("0") and target_psq_weight < self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        # Phase 2: INCREASE positions (execute BUYs second)

        # TQQQ: Increase if needed
        if target_tqqq_weight > Decimal("0") and target_tqqq_weight > self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # QQQ: Increase if needed
        if target_qqq_weight > Decimal("0") and target_qqq_weight > self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # PSQ: Increase if needed
        if target_psq_weight > Decimal("0") and target_psq_weight > self.current_psq_weight:
            self.buy(self.inverse_hedge_symbol, target_psq_weight)

        # Update current weights
        self.current_tqqq_weight = target_tqqq_weight
        self.current_qqq_weight = target_qqq_weight
        self.current_psq_weight = target_psq_weight

        logger.info(
            f"Executed v3.5 rebalance: TQQQ={target_tqqq_weight:.3f}, "
            f"QQQ={target_qqq_weight:.3f}, PSQ={target_psq_weight:.3f}"
        )
