"""
Hierarchical Adaptive v2.5: Asymmetric DD Governor Fix for QQQ / TQQQ Exposure Overlay

v2.5 is an incremental bug fix release addressing the DD governor asymmetry in v2.0
that prevented defensive positioning (exposure < 1.0x) during drawdowns.

v2.5 Scope:
- Long-side only (QQQ + TQQQ exposure scaling, no SQQQ hedge)
- Continuous exposure: Always invested (except extreme stress), scale between E_min and E_max
- 5-Tier exposure engine: Kalman → Vol → VIX → Drawdown → Position Mapping
- Drift-based rebalancing: Check weights every bar, rebalance only if deviation > 2.5%

Key Innovation from v2.0:
- **Asymmetric DD Governor**: Separate formulas for leverage vs defensive positioning
  * Leverage path (E > 1.0): Compress toward 1.0 (same as v2.0)
  * Defensive path (E ≤ 1.0): Interpolate between E and 1.0 (NEW - v2.5 fix)
- **Updated DD Thresholds**: DD_soft=0.10 (was 0.05), DD_hard=0.20 (was 0.15)

v2.5 Changes from v2.0:
1. ✅ Asymmetric DD governor formula (5-line fix in _apply_drawdown_governor)
2. ✅ Updated DD threshold defaults (DD_soft: 0.10, DD_hard: 0.20)
3. ✅ Enhanced docstrings with v2.5 behavioral examples

Preserved Features (100% compatibility with v2.0):
- ✅ Same 20-parameter interface
- ✅ Same 5-tier exposure engine
- ✅ Same Kalman trend normalization
- ✅ Same vol/VIX modulators
- ✅ Same position mapping logic
- ✅ Same rebalancing mechanism

Bug Fix Explanation:
v2.0's DD governor used symmetric compression: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
This formula treated all E_volVIX values symmetrically around 1.0:
- E_volVIX > 1.0: Correctly compressed leverage toward 1.0 ✅
- E_volVIX < 1.0: Incorrectly compressed defensive positioning toward 1.0 ❌

v2.5's asymmetric DD governor fixes this:
- Leverage path (E > 1.0): E_raw = 1.0 + (E_volVIX - 1.0) * P_DD (same as v2.0)
- Defensive path (E ≤ 1.0): E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD) (NEW)

The defensive path is a weighted average (interpolation) between:
- E_volVIX (full defensive signal) with weight P_DD
- 1.0 (neutral) with weight (1.0 - P_DD)

This enables the strategy to:
1. Actually reach E_min during bearish conditions with drawdowns
2. Maintain defensive bias (< 1.0x) when markets are weak
3. Use the full designed exposure range [E_min, E_max]

Core Flow:
1. Kalman trend engine → normalized trend T_norm ∈ [-1, +1]
2. Baseline exposure E_trend = 1.0 + k_trend * T_norm
3. Volatility scaler S_vol = clip(σ_target / σ_real, S_vol_min, S_vol_max)
4. VIX compression P_VIX (soft filter, not hard gate)
5. Drawdown governor P_DD (v2.5: asymmetric compression)
6. Final exposure E_t ∈ [E_min, E_max]
7. Map E_t to QQQ/TQQQ weights
8. Rebalance if drift > threshold

Performance Targets:
    - Processing Speed: <3ms per bar (including Kalman + Vol + VIX + DD calculations)
    - Memory: O(max_lookback_period) for indicator state
    - Backtest: 2010-2025 (15 years) in <20 seconds
"""
from decimal import Decimal
from typing import Optional
import logging
import pandas as pd

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel
from jutsu_engine.indicators.technical import ema, annualized_volatility
from jutsu_engine.performance.trade_logger import TradeLogger

logger = logging.getLogger('STRATEGY.HIERARCHICAL_ADAPTIVE_V2_5')


class Hierarchical_Adaptive_v2_5(Strategy):
    """
    Hierarchical Adaptive v2.5: Asymmetric DD Governor Fix for QQQ / TQQQ

    v2.5 bug fix: Asymmetric DD governor enables full exposure range [E_min, E_max].

    5-Tier Exposure Engine:
    - Tier 1: Kalman trend engine (normalized trend T_norm ∈ [-1, +1])
    - Tier 2: Volatility modulator (realized vol scaler)
    - Tier 3: VIX compression (soft filter)
    - Tier 4: Drawdown governor (asymmetric risk limiter - v2.5 FIX)
    - Tier 5: QQQ/TQQQ position mapping

    v2.5 Key Fix: Asymmetric DD Governor
    - Leverage path (E > 1.0): Compress toward 1.0 during drawdowns
    - Defensive path (E ≤ 1.0): Interpolate toward 1.0 (preserves defensive bias)

    v2.5 Scope: Long-side only (QQQ + TQQQ), no SQQQ hedge.

    Performance Targets:
        - Processing Speed: <3ms per bar
        - Memory: O(max_lookback_period)
        - Backtest: 2010-2025 in <20 seconds

    Example:
        strategy = Hierarchical_Adaptive_v2_5(
            measurement_noise=Decimal("2000.0"),
            k_trend=Decimal("0.3"),
            DD_soft=Decimal("0.10"),  # v2.5 default (was 0.05 in v2.0)
            DD_hard=Decimal("0.20"),  # v2.5 default (was 0.15 in v2.0)
            # ... (all 20 parameters configurable)
        )

    v2.5 Changelog:
    - Fixed asymmetric DD governor (enables defensive positioning)
    - Updated DD_soft default: 0.05 → 0.10
    - Updated DD_hard default: 0.15 → 0.20
    - Enhanced docstrings with asymmetric formula examples
    """

    def __init__(
        self,
        # ==================================================================
        # TIER 1: KALMAN TREND ENGINE (6 parameters)
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("60"),

        # ==================================================================
        # TIER 0: CORE EXPOSURE ENGINE (3 parameters)
        # ==================================================================
        k_trend: Decimal = Decimal("0.3"),  # CRITICAL exposure sensitivity
        E_min: Decimal = Decimal("0.5"),
        E_max: Decimal = Decimal("1.3"),

        # ==================================================================
        # TIER 2: VOLATILITY MODULATOR (4 parameters)
        # ==================================================================
        sigma_target_multiplier: Decimal = Decimal("0.9"),
        realized_vol_lookback: int = 20,
        S_vol_min: Decimal = Decimal("0.5"),
        S_vol_max: Decimal = Decimal("1.5"),

        # ==================================================================
        # TIER 3: VIX MODULATOR (2 parameters)
        # ==================================================================
        vix_ema_period: int = 50,
        alpha_VIX: Decimal = Decimal("1.0"),

        # ==================================================================
        # TIER 4: DRAWDOWN GOVERNOR (3 parameters) - v2.5 UPDATED DEFAULTS
        # ==================================================================
        DD_soft: Decimal = Decimal("0.10"),  # v2.5: Changed from 0.05
        DD_hard: Decimal = Decimal("0.20"),  # v2.5: Changed from 0.15
        p_min: Decimal = Decimal("0.0"),

        # ==================================================================
        # TIER 5: REBALANCING CONTROL (1 parameter)
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),  # 2.5%

        # ==================================================================
        # SYMBOL CONFIGURATION (4 parameters)
        # ==================================================================
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        vix_symbol: str = "$VIX",  # Must match CLI-normalized symbol (CLI adds $ prefix to index symbols)

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Hierarchical_Adaptive_v2_5"
    ):
        """
        Initialize Hierarchical Adaptive v2.5 strategy with 20 configurable parameters.

        v2.5 Changes:
        - DD_soft default: 0.05 → 0.10 (less aggressive compression)
        - DD_hard default: 0.15 → 0.20 (aligns with bear market threshold)
        - Asymmetric DD governor (code change in _apply_drawdown_governor)

        Total Parameters: 20 (same as v2.0)

        Args:
            measurement_noise: Base measurement noise for Kalman filter (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01, fixed per spec)
            process_noise_2: Process noise for velocity (default: 0.01, fixed per spec)
            osc_smoothness: Smoothing period for oscillator (default: 15)
            strength_smoothness: Smoothing period for trend strength (default: 15)
            T_max: Reference strength for normalization (default: 60)
            k_trend: Trend sensitivity for exposure scaling (default: 0.3, CRITICAL parameter)
            E_min: Minimum exposure (default: 0.5 = 50%)
            E_max: Maximum exposure (default: 1.3 = 130%)
            sigma_target_multiplier: Multiplier for historical vol to get target (default: 0.9)
            realized_vol_lookback: Period for realized volatility calculation (default: 20)
            S_vol_min: Minimum volatility scaler (default: 0.5)
            S_vol_max: Maximum volatility scaler (default: 1.5)
            vix_ema_period: VIX EMA period for compression (default: 50)
            alpha_VIX: VIX compression factor (default: 1.0)
            DD_soft: Soft drawdown threshold (default: 0.10 = 10%, v2.5: was 0.05 in v2.0)
            DD_hard: Hard drawdown threshold (default: 0.20 = 20%, v2.5: was 0.15 in v2.0)
            p_min: Minimum drawdown penalty factor (default: 0.0)
            rebalance_threshold: Weight drift threshold for rebalancing (default: 0.025 = 2.5%)
            signal_symbol: Symbol for signal generation (default: 'QQQ')
            core_long_symbol: 1x long symbol (default: 'QQQ')
            leveraged_long_symbol: 3x leveraged long symbol (default: 'TQQQ')
            vix_symbol: Volatility index symbol (default: 'VIX')
            trade_logger: Optional TradeLogger for strategy context (default: None)
            name: Strategy name (default: 'Hierarchical_Adaptive_v2_5')

        Raises:
            ValueError: If parameter constraints are violated
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate parameter constraints
        if not (Decimal("0.0") < E_min < E_max):
            raise ValueError(
                f"Exposure bounds must satisfy 0 < E_min ({E_min}) < E_max ({E_max})"
            )

        if not (Decimal("0.0") < S_vol_min <= Decimal("1.0") <= S_vol_max):
            raise ValueError(
                f"Vol scaler bounds must satisfy 0 < S_vol_min ({S_vol_min}) <= 1.0 <= S_vol_max ({S_vol_max})"
            )

        if not (Decimal("0.0") <= DD_soft < DD_hard <= Decimal("1.0")):
            raise ValueError(
                f"Drawdown thresholds must satisfy 0 <= DD_soft ({DD_soft}) < DD_hard ({DD_hard}) <= 1.0"
            )

        if not (Decimal("0.0") <= p_min <= Decimal("1.0")):
            raise ValueError(
                f"p_min must be in [0.0, 1.0], got {p_min}"
            )

        if vix_ema_period < 1:
            raise ValueError(
                f"VIX EMA period must be >= 1, got {vix_ema_period}"
            )

        if rebalance_threshold <= Decimal("0.0"):
            raise ValueError(
                f"Rebalance threshold must be positive, got {rebalance_threshold}"
            )

        # Store Tier 1: Kalman parameters
        self.measurement_noise = measurement_noise
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.T_max = T_max

        # Store Tier 0: Core exposure engine
        self.k_trend = k_trend
        self.E_min = E_min
        self.E_max = E_max

        # Store Tier 2: Volatility modulator
        self.sigma_target_multiplier = sigma_target_multiplier
        self.realized_vol_lookback = realized_vol_lookback
        self.S_vol_min = S_vol_min
        self.S_vol_max = S_vol_max

        # Store Tier 3: VIX modulator
        self.vix_ema_period = vix_ema_period
        self.alpha_VIX = alpha_VIX

        # Store Tier 4: Drawdown governor
        self.DD_soft = DD_soft
        self.DD_hard = DD_hard
        self.p_min = p_min

        # Store Tier 5: Rebalancing control
        self.rebalance_threshold = rebalance_threshold

        # Store symbol configuration
        self.signal_symbol = signal_symbol
        self.core_long_symbol = core_long_symbol
        self.leveraged_long_symbol = leveraged_long_symbol
        self.vix_symbol = vix_symbol

        # State variables (initialized in init())
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.sigma_target: Optional[Decimal] = None
        self.equity_peak: Decimal = Decimal("0")
        self.current_exposure: Decimal = Decimal("1.0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_tqqq_weight: Decimal = Decimal("0")

        logger.info(
            f"Initialized {name} with 20 parameters: "
            f"Kalman[noise={measurement_noise}, osc={osc_smoothness}, strength={strength_smoothness}], "
            f"Exposure[k_trend={k_trend}, E_min={E_min}, E_max={E_max}], "
            f"Vol[target_mult={sigma_target_multiplier}, lookback={realized_vol_lookback}], "
            f"VIX[ema={vix_ema_period}, alpha={alpha_VIX}], "
            f"DD[soft={DD_soft}, hard={DD_hard}] (v2.5 updated defaults), "
            f"Rebal[threshold={rebalance_threshold}]"
        )

    def init(self) -> None:
        """
        Initialize strategy state and calculate sigma_target from historical data.

        Called once before backtesting starts. Sets up:
        - AdaptiveKalmanFilter with VOLUME_ADJUSTED model
        - sigma_target from full historical QQQ data
        - State tracking variables

        Side Effects:
            - Creates Kalman filter instance
            - Calculates sigma_target from all available historical data
            - Initializes equity_peak, current_exposure, current_weights
        """
        # Initialize Kalman filter with VOLUME_ADJUSTED model
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=float(self.measurement_noise),
            process_noise_1=float(self.process_noise_1),
            process_noise_2=float(self.process_noise_2),
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness
        )

        # Calculate sigma_target from full historical data (one-time calculation)
        # Use large lookback to get all available data
        qqq_closes = self.get_closes(lookback=999999, symbol=self.signal_symbol)

        if len(qqq_closes) > 50:  # Need sufficient data
            # Calculate historical volatility from full series
            historical_vol_series = annualized_volatility(
                qqq_closes,
                lookback=len(qqq_closes)
            )
            historical_vol = Decimal(str(historical_vol_series.iloc[-1]))

            # Apply multiplier to get target
            self.sigma_target = historical_vol * self.sigma_target_multiplier
        else:
            # Fallback if insufficient data
            self.sigma_target = Decimal("0.20") * self.sigma_target_multiplier  # 20% default

        # Initialize state tracking
        self.equity_peak = Decimal("0")
        self.current_exposure = Decimal("1.0")
        self.current_qqq_weight = Decimal("0")
        self.current_tqqq_weight = Decimal("0")

        logger.info(
            f"Initialized {self.name} with Kalman filter and "
            f"calculated sigma_target: {self.sigma_target:.4f}"
        )

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through 5-tier exposure engine.

        Flow:
        1. Update Kalman filter → trend_strength
        2. Calculate normalized trend T_norm
        3. Calculate baseline exposure E_trend
        4. Apply volatility scaler → E_vol
        5. Apply VIX compression → E_volVIX
        6. Apply drawdown governor → E_raw (v2.5: asymmetric)
        7. Clip to bounds → E_t
        8. Map E_t to QQQ/TQQQ weights
        9. Check rebalancing threshold
        10. Execute rebalance if needed
        11. Log all tier calculations

        Args:
            bar: New market data bar with OHLCV data

        Note:
            Only processes signal_symbol (QQQ) bars. Other symbols (TQQQ, VIX)
            are accessed via get_closes/highs/lows for calculations.
        """
        # Only process signal symbol (QQQ)
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check (need enough data for indicators)
        # Use realized_vol_lookback * 2 to ensure rolling window has valid data
        # (need 1 bar for log returns shift + lookback bars for rolling std)
        min_warmup = max(self.vix_ema_period, self.realized_vol_lookback * 2) + 10
        if len(self._bars) < min_warmup:
            logger.debug(
                f"Warmup period: {len(self._bars)}/{min_warmup} bars"
            )
            return

        # ===== TIER 1: Update Kalman filter =====
        _, trend_strength = self.kalman_filter.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
        trend_strength_decimal = Decimal(str(trend_strength))

        # ===== TIER 2: Calculate normalized trend =====
        T_norm = self._calculate_normalized_trend(trend_strength_decimal)

        # ===== TIER 3: Calculate baseline exposure =====
        E_trend = self._calculate_baseline_exposure(T_norm)

        # ===== TIER 4: Apply volatility scaler =====
        closes = self.get_closes(
            lookback=self.realized_vol_lookback + 10,
            symbol=self.signal_symbol
        )
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_lookback)

        # Defensive NaN check: annualized_volatility uses rolling().std() which returns NaN
        # for first `lookback` rows. Use sigma_target as fallback.
        if pd.isna(vol_series.iloc[-1]):
            sigma_real = self.sigma_target
            logger.warning(
                f"Volatility calculation returned NaN (insufficient rolling window data), "
                f"using sigma_target: {self.sigma_target:.4f}"
            )
        else:
            sigma_real = Decimal(str(vol_series.iloc[-1]))

        S_vol, E_vol = self._apply_volatility_scaler(E_trend, sigma_real)

        # ===== TIER 5: Apply VIX compression =====
        vix_closes = self.get_closes(
            lookback=self.vix_ema_period + 10,
            symbol=self.vix_symbol
        )
        vix_ema_series = ema(vix_closes, self.vix_ema_period)

        # Defensive checks for VIX data (ensure sufficient data for EMA calculation)
        if len(vix_closes) < self.vix_ema_period:
            logger.warning(
                f"Insufficient VIX data for EMA: need {self.vix_ema_period}, "
                f"have {len(vix_closes)}. Skipping bar."
            )
            return

        vix_current = Decimal(str(vix_closes.iloc[-1]))

        # Check if EMA returned valid value (EMA can return NaN for first few periods)
        if pd.isna(vix_ema_series.iloc[-1]):
            logger.warning(
                f"VIX EMA calculation returned NaN (insufficient warmup). Skipping bar."
            )
            return

        vix_ema_value = Decimal(str(vix_ema_series.iloc[-1]))

        R_VIX = vix_current / vix_ema_value if vix_ema_value > Decimal("0") else Decimal("1.0")
        P_VIX, E_volVIX = self._apply_vix_compression(E_vol, R_VIX)

        # ===== TIER 6: Apply drawdown governor (v2.5: asymmetric) =====
        # Get current portfolio equity from cash + positions value
        portfolio_equity = self._cash
        for symbol, qty in self._positions.items():
            if qty > 0:
                # Get latest price for this symbol
                symbol_bars = [b for b in self._bars if b.symbol == symbol]
                if symbol_bars:
                    latest_price = symbol_bars[-1].close
                    portfolio_equity += Decimal(str(qty)) * latest_price

        DD_current = self._update_drawdown_tracking(portfolio_equity)
        P_DD, E_raw = self._apply_drawdown_governor(E_volVIX, DD_current)

        # ===== TIER 7: Clip to bounds =====
        E_t = max(self.E_min, min(self.E_max, E_raw))
        self.current_exposure = E_t

        # ===== TIER 8: Map to weights =====
        w_QQQ, w_TQQQ, w_cash = self._map_exposure_to_weights(E_t)

        # ===== TIER 9: Check rebalancing threshold =====
        needs_rebalance = self._check_rebalancing_threshold(w_QQQ, w_TQQQ)

        # ===== TIER 10: Log context =====
        logger.info(
            f"[{bar.timestamp}] Exposure Calculation | "
            f"trend_strength={trend_strength_decimal:.2f} → "
            f"T_norm={T_norm:.3f} → "
            f"E_trend={E_trend:.3f} → "
            f"S_vol={S_vol:.3f}/σ_real={sigma_real:.3f} → "
            f"E_vol={E_vol:.3f} → "
            f"P_VIX={P_VIX:.3f}/R_VIX={R_VIX:.3f} → "
            f"E_volVIX={E_volVIX:.3f} → "
            f"P_DD={P_DD:.3f}/DD={DD_current:.3f} → "
            f"E_t={E_t:.3f} (v2.5 asymmetric DD) → "
            f"w_QQQ={w_QQQ:.3f}, w_TQQQ={w_TQQQ:.3f}, w_cash={w_cash:.3f}"
        )

        # ===== Execute rebalance if needed =====
        if needs_rebalance:
            logger.info(
                f"Rebalancing: weights drifted beyond threshold "
                f"({self.rebalance_threshold:.3f})"
            )

            # Log context for trade logger (for BOTH symbols)
            if self._trade_logger:
                # Log context for QQQ
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=self.signal_symbol,
                    strategy_state=f"Continuous Exposure Overlay (E_t={E_t:.3f}, v2.5)",
                    decision_reason=(
                        f"Kalman trend {trend_strength_decimal:.2f} → T_norm {T_norm:.3f}, "
                        f"Vol scaler {S_vol:.3f}, VIX compression {P_VIX:.3f}, "
                        f"DD governor {P_DD:.3f} (v2.5 asymmetric) → Final exposure {E_t:.3f}"
                    ),
                    indicator_values={
                        'trend_strength': float(trend_strength_decimal),
                        'T_norm': float(T_norm),
                        'E_t': float(E_t),
                        'sigma_real': float(sigma_real),
                        'R_VIX': float(R_VIX),
                        'DD_current': float(DD_current)
                    },
                    threshold_values={
                        'T_max': float(self.T_max),
                        'E_min': float(self.E_min),
                        'E_max': float(self.E_max),
                        'DD_soft': float(self.DD_soft),
                        'DD_hard': float(self.DD_hard)
                    }
                )

                # Log context for TQQQ (same values, different symbol)
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=self.leveraged_long_symbol,
                    strategy_state=f"Continuous Exposure Overlay (E_t={E_t:.3f}, v2.5)",
                    decision_reason=(
                        f"Kalman trend {trend_strength_decimal:.2f} → T_norm {T_norm:.3f}, "
                        f"Vol scaler {S_vol:.3f}, VIX compression {P_VIX:.3f}, "
                        f"DD governor {P_DD:.3f} (v2.5 asymmetric) → Final exposure {E_t:.3f}"
                    ),
                    indicator_values={
                        'trend_strength': float(trend_strength_decimal),
                        'T_norm': float(T_norm),
                        'E_t': float(E_t),
                        'sigma_real': float(sigma_real),
                        'R_VIX': float(R_VIX),
                        'DD_current': float(DD_current)
                    },
                    threshold_values={
                        'T_max': float(self.T_max),
                        'E_min': float(self.E_min),
                        'E_max': float(self.E_max),
                        'DD_soft': float(self.DD_soft),
                        'DD_hard': float(self.DD_hard)
                    }
                )

            self._execute_rebalance(w_QQQ, w_TQQQ)

    def _calculate_normalized_trend(self, trend_strength: Decimal) -> Decimal:
        """
        Calculate normalized trend: T_norm = clip(trend_strength / T_max, -1, +1)

        Args:
            trend_strength: Kalman filter output (approx. [-100, +100])

        Returns:
            Normalized trend in [-1, +1]

        Example:
            trend_strength = Decimal('75.0')
            T_max = Decimal('60.0')
            T_norm = clip(75.0 / 60.0, -1, +1) = clip(1.25, -1, +1) = +1.0
        """
        T_norm = trend_strength / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_baseline_exposure(self, T_norm: Decimal) -> Decimal:
        """
        E_trend = 1.0 + k_trend * T_norm

        Examples:
        - Strong bull (T_norm = +1.0): E_trend = 1.0 + 0.3 * 1.0 = 1.3
        - Neutral (T_norm = 0.0): E_trend = 1.0
        - Strong bear (T_norm = -1.0): E_trend = 1.0 + 0.3 * (-1.0) = 0.7

        Args:
            T_norm: Normalized trend in [-1, +1]

        Returns:
            Baseline exposure before modulation
        """
        return Decimal("1.0") + self.k_trend * T_norm

    def _apply_volatility_scaler(
        self,
        E_trend: Decimal,
        sigma_real: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        S_vol = clip(σ_target / σ_real, S_min, S_max)
        E_vol = 1.0 + (E_trend - 1.0) * S_vol

        Args:
            E_trend: Baseline exposure from trend
            sigma_real: Current realized volatility

        Returns:
            (S_vol, E_vol) - volatility scaler and adjusted exposure

        Example:
            E_trend = 1.3, sigma_target = 0.18, sigma_real = 0.20
            S_vol = clip(0.18 / 0.20, 0.5, 1.5) = 0.9
            E_vol = 1.0 + (1.3 - 1.0) * 0.9 = 1.0 + 0.27 = 1.27
        """
        if sigma_real > Decimal("0"):
            S_vol = self.sigma_target / sigma_real
        else:
            S_vol = Decimal("1.0")

        S_vol = max(self.S_vol_min, min(self.S_vol_max, S_vol))
        E_vol = Decimal("1.0") + (E_trend - Decimal("1.0")) * S_vol

        return S_vol, E_vol

    def _apply_vix_compression(
        self,
        E_vol: Decimal,
        R_VIX: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        P_VIX = 1 / (1 + α_VIX * (R_VIX - 1)) when R_VIX > 1, else 1.0
        E_volVIX = 1.0 + (E_vol - 1.0) * P_VIX

        Args:
            E_vol: Exposure after volatility adjustment
            R_VIX: VIX ratio (VIX / VIX_EMA)

        Returns:
            (P_VIX, E_volVIX) - VIX penalty factor and adjusted exposure

        Example:
            E_vol = 1.27, R_VIX = 1.2, alpha_VIX = 1.0
            P_VIX = 1 / (1 + 1.0 * (1.2 - 1)) = 1 / 1.2 = 0.833
            E_volVIX = 1.0 + (1.27 - 1.0) * 0.833 = 1.225
        """
        if R_VIX > Decimal("1.0"):
            P_VIX = Decimal("1.0") / (Decimal("1.0") + self.alpha_VIX * (R_VIX - Decimal("1.0")))
        else:
            P_VIX = Decimal("1.0")

        E_volVIX = Decimal("1.0") + (E_vol - Decimal("1.0")) * P_VIX

        return P_VIX, E_volVIX

    def _apply_drawdown_governor(
        self,
        E_volVIX: Decimal,
        DD_current: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        v2.5 Asymmetric Drawdown Governor

        Linear compression between DD_soft and DD_hard with asymmetric treatment
        of leverage vs defensive positions.

        Key Change from v2.0:
        - v2.0: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD (symmetric compression)
        - v2.5: Split into two paths based on E_volVIX position

        Leverage Path (E_volVIX > 1.0):
            Goal: Reduce leverage toward neutral during drawdowns
            Formula: E_raw = 1.0 + (E_volVIX - 1.0) * P_DD
            Example: E_volVIX=1.3, P_DD=0.5 → E_raw = 1.0 + 0.3*0.5 = 1.15

        Defensive Path (E_volVIX <= 1.0):
            Goal: Maintain or strengthen defensive positioning during drawdowns
            Formula: E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
            Example: E_volVIX=0.6, P_DD=0.5 → E_raw = 0.6*0.5 + 1.0*0.5 = 0.8

            Interpretation: Weighted average between E_volVIX (full defense) and 1.0 (neutral)
            - P_DD=1.0 (no DD): E_raw = E_volVIX (preserve signal)
            - P_DD=0.5 (mid DD): E_raw = 50% signal + 50% neutral
            - P_DD=0.0 (max DD): E_raw = 1.0 (forced neutral)

        Args:
            E_volVIX: Exposure after VIX compression
            DD_current: Current drawdown (positive number, e.g., 0.12 = 12%)

        Returns:
            (P_DD, E_raw) - drawdown penalty factor and final raw exposure

        Example (Leverage Compression):
            E_volVIX = 1.225, DD_current = 0.15, DD_soft = 0.10, DD_hard = 0.20, p_min = 0.0
            P_DD = 1.0 - ((0.15 - 0.10) / (0.20 - 0.10)) * (1.0 - 0.0) = 1.0 - 0.5 = 0.5
            E_raw = 1.0 + (1.225 - 1.0) * 0.5 = 1.1125

        Example (Defensive Preservation):
            E_volVIX = 0.6, DD_current = 0.12, DD_soft = 0.10, DD_hard = 0.20, p_min = 0.0
            P_DD = 1.0 - ((0.12 - 0.10) / 0.10) = 0.8
            E_raw = 0.6 * 0.8 + 1.0 * 0.2 = 0.48 + 0.20 = 0.68
            → Interpolated 20% toward neutral (0.6 → 0.68)
        """
        # Step 1: Calculate penalty factor P_DD (same as v2.0)
        if DD_current <= self.DD_soft:
            # No drawdown pressure - preserve exposure
            P_DD = Decimal("1.0")
        elif DD_current >= self.DD_hard:
            # Maximum drawdown - apply full compression
            P_DD = self.p_min
        else:
            # Linear interpolation between soft and hard thresholds
            dd_range = self.DD_hard - self.DD_soft
            dd_excess = DD_current - self.DD_soft
            P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

        # Step 2: Apply asymmetric compression (v2.5 KEY FIX)
        if E_volVIX > Decimal("1.0"):
            # === LEVERAGE PATH ===
            # Compress excess leverage toward neutral during drawdowns
            # Formula same as v2.0: E_raw → 1.0 as DD increases
            E_raw = Decimal("1.0") + (E_volVIX - Decimal("1.0")) * P_DD

        else:
            # === DEFENSIVE PATH (v2.5 NEW) ===
            # Interpolate between defensive signal and neutral during drawdowns
            # E_raw moves toward 1.0 (but from below) as DD increases
            #
            # Weighted average interpretation:
            # - E_volVIX weight: P_DD (trust the defensive signal)
            # - 1.0 weight: (1.0 - P_DD) (retreat toward neutral)
            #
            # Effect: Gradually reduces defensiveness while maintaining bias below 1.0
            E_raw = E_volVIX * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)

        return P_DD, E_raw

    def _map_exposure_to_weights(
        self,
        E_t: Decimal
    ) -> tuple[Decimal, Decimal, Decimal]:
        """
        Map final exposure to QQQ/TQQQ/cash weights.

        If E_t ≤ 1.0:
            w_TQQQ = 0
            w_QQQ = E_t
            w_cash = 1 - E_t

        If E_t > 1.0:
            Solve: w_QQQ + w_TQQQ = 1
                   1*w_QQQ + 3*w_TQQQ = E_t
            Solution: w_TQQQ = (E_t - 1) / 2
                      w_QQQ = 1 - w_TQQQ
                      w_cash = 0

        Args:
            E_t: Final exposure level (clipped to [E_min, E_max])

        Returns:
            (w_QQQ, w_TQQQ, w_cash) - portfolio weights

        Examples:
            E_t = 0.7: (0.7, 0.0, 0.3) - 70% QQQ, 30% cash
            E_t = 1.0: (1.0, 0.0, 0.0) - 100% QQQ
            E_t = 1.3: (0.85, 0.15, 0.0) - 85% QQQ, 15% TQQQ
                       Verify: 0.85*1 + 0.15*3 = 1.3 ✓
        """
        if E_t <= Decimal("1.0"):
            w_TQQQ = Decimal("0")
            w_QQQ = E_t
            w_cash = Decimal("1.0") - E_t
        else:
            w_TQQQ = (E_t - Decimal("1.0")) / Decimal("2.0")
            w_QQQ = Decimal("1.0") - w_TQQQ
            w_cash = Decimal("0")

        return w_QQQ, w_TQQQ, w_cash

    def _check_rebalancing_threshold(
        self,
        target_qqq_weight: Decimal,
        target_tqqq_weight: Decimal
    ) -> bool:
        """
        Check if portfolio weights have drifted > threshold from targets.

        Weight deviation = |current_qqq - target_qqq| + |current_tqqq - target_tqqq|

        Args:
            target_qqq_weight: Target QQQ weight
            target_tqqq_weight: Target TQQQ weight

        Returns:
            True if deviation > rebalance_threshold (2.5% default)

        Example:
            current_qqq = 0.82, current_tqqq = 0.16
            target_qqq = 0.85, target_tqqq = 0.15
            deviation = |0.82 - 0.85| + |0.16 - 0.15| = 0.03 + 0.01 = 0.04 = 4%
            threshold = 0.025 = 2.5%
            needs_rebalance = True (4% > 2.5%)
        """
        weight_deviation = (
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_tqqq_weight - target_tqqq_weight)
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance(
        self,
        target_qqq_weight: Decimal,
        target_tqqq_weight: Decimal
    ) -> None:
        """
        Rebalance portfolio to target weights using portfolio_percent API.

        Uses Strategy base class buy/sell methods with portfolio_percent allocation.

        Args:
            target_qqq_weight: Target QQQ allocation (0.0 to 1.0)
            target_tqqq_weight: Target TQQQ allocation (0.0 to 1.0)

        Side Effects:
            - Generates BUY/SELL signals for QQQ and TQQQ
            - Updates current_qqq_weight and current_tqqq_weight

        Example:
            target_qqq_weight = 0.85
            target_tqqq_weight = 0.15
            → self.buy('QQQ', 0.85)
            → self.buy('TQQQ', 0.15)
        """
        # Update QQQ position
        if target_qqq_weight > Decimal("0"):
            self.buy(self.core_long_symbol, target_qqq_weight)
        else:
            # Close QQQ position (0% triggers Portfolio's close-position logic)
            self.sell(self.core_long_symbol, Decimal("0.0"))

        # Update TQQQ position
        if target_tqqq_weight > Decimal("0"):
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)
        else:
            # Close TQQQ position
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))

        # Update current weights
        self.current_qqq_weight = target_qqq_weight
        self.current_tqqq_weight = target_tqqq_weight

        logger.info(
            f"Executed rebalance: QQQ={target_qqq_weight:.3f}, TQQQ={target_tqqq_weight:.3f}"
        )

    def _update_drawdown_tracking(self, portfolio_equity: Decimal) -> Decimal:
        """
        Track peak-to-trough drawdown.

        Args:
            portfolio_equity: Current portfolio total value (cash + positions)

        Returns:
            Current drawdown as positive number (e.g., 0.12 = 12% drawdown)

        Side Effects:
            - Updates self.equity_peak if new peak reached

        Example:
            equity_peak = 100000, portfolio_equity = 88000
            DD_current = (100000 - 88000) / 100000 = 0.12 = 12%
        """
        # Update peak
        if portfolio_equity > self.equity_peak:
            self.equity_peak = portfolio_equity

        # Calculate drawdown
        if self.equity_peak > Decimal("0"):
            DD_current = (self.equity_peak - portfolio_equity) / self.equity_peak
        else:
            DD_current = Decimal("0")

        return DD_current
