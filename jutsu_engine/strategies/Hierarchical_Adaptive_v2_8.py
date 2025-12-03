"""
Hierarchical Adaptive v2.8: Two-Parameter Floor System with Stronger Short Slope

v2.8 introduces a critical architectural fix to enable controlled SQQQ usage through
a two-parameter floor system, replacing the conflated E_min with:

1. **E_anchor** (0.6-0.8): Positive defensive anchor for drawdown governor
2. **E_short** (-0.3 to 0.0): Global clip floor enabling negative exposure

Key Changes from v2.7_1:

1. **Two-Parameter Floor System**:
   - E_anchor: DD governor anchor (positive, defensive)
   - E_short: Global lower bound (possibly negative, enables SQQQ)
   - Removes conflation of "defensive anchor" and "clip floor"

2. **Stronger k_short** (0.8-1.2):
   - Default 1.0 allows E_trend to go negative when T_norm = -1
   - Range allows optimization for bear market sensitivity
   - Enables SQQQ reach when trend warrants

3. **Drawdown Governor Fix**:
   - Anchors to E_anchor (not E_min)
   - E_raw = E_anchor + (E_volVIX - E_anchor) × P_DD
   - Prevents deep DD from forcing further short

4. **Final Clipping Fix**:
   - Uses E_short as lower bound (not E_anchor)
   - E_t = clip(E_raw, E_short, E_max)
   - Allows negative E_t when trend strong and DD mild

5. **SQQQ Weight Cap**:
   - New parameter w_SQQQ_max (0.2-0.25)
   - Caps SQQQ positions to limit decay and volatility

Mathematical Validation (SQQQ Reachable):
- With k_short=1.0, T_norm=-1.0 → E_trend = 1.0 - 1.0 = 0.0
- Vol/VIX can compress → E_volVIX ≈ 0.0 to -0.2
- With mild DD (P_DD ≈ 1) → E_raw ≈ E_volVIX < 0
- With E_short=-0.2 → E_t can reach -0.2 (SQQQ region)

Performance Targets:
    - Processing Speed: <3ms per bar
    - Memory: O(max_lookback_period)
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

logger = logging.getLogger('STRATEGY.HIERARCHICAL_ADAPTIVE_V2_8')


class Hierarchical_Adaptive_v2_8(Strategy):
    """
    Hierarchical Adaptive v2.8: Two-Parameter Floor System for Controlled SQQQ

    Architectural breakthrough enabling controlled short exposure through:
    1. E_anchor: Positive defensive anchor (DD governor target)
    2. E_short: Global clip floor (enables negative exposure)

    5-Tier Exposure Engine:
    - Tier 1: Kalman trend engine (Signed)
    - Tier 2: Trend Normalization & Asymmetric Scaling (k_short STRONGER)
    - Tier 3: Volatility modulator
    - Tier 4: VIX compression
    - Tier 5: Drawdown governor (FIXED: Anchors to E_anchor)
    - Tier 6: Final clipping (FIXED: Uses E_short floor)
    - Tier 7: Position mapping (NEW: SQQQ cap)

    Example:
        strategy = Hierarchical_Adaptive_v2_8(
            k_long=Decimal("0.7"),
            k_short=Decimal("1.0"),     # STRONGER! Allows negative E_trend
            E_anchor=Decimal("0.7"),    # NEW! DD anchor
            E_short=Decimal("-0.2"),    # NEW! Clip floor (enables SQQQ)
            w_SQQQ_max=Decimal("0.25"), # NEW! SQQQ cap
            ...
        )
    """

    def __init__(
        self,
        # ==================================================================
        # TIER 1: KALMAN FILTER PARAMETERS (6 parameters)
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("60"),

        # ==================================================================
        # TIER 2: TREND EXPOSURE (7 parameters - CHANGED from v2.7_1)
        # ==================================================================
        k_long: Decimal = Decimal("0.7"),      # [0.5, 0.8] - Unchanged
        k_short: Decimal = Decimal("1.0"),     # [0.8, 1.2] - STRONGER! (was [0.2, 0.4])
        E_anchor: Decimal = Decimal("0.7"),    # [0.6, 0.8] - NEW! DD anchor (was E_min)
        E_short: Decimal = Decimal("-0.2"),    # [-0.3, 0.0] - NEW! Clip floor
        E_max: Decimal = Decimal("1.5"),       # [1.5, 1.8] - Unchanged
        w_SQQQ_max: Decimal = Decimal("0.25"), # [0.2, 0.25] - NEW! SQQQ cap

        # ==================================================================
        # TIER 3: VOLATILITY MODULATOR (4 parameters)
        # ==================================================================
        sigma_target_multiplier: Decimal = Decimal("0.9"),
        realized_vol_lookback: int = 20,
        S_vol_min: Decimal = Decimal("0.5"),
        S_vol_max: Decimal = Decimal("1.5"),

        # ==================================================================
        # TIER 4: VIX MODULATOR (2 parameters)
        # ==================================================================
        vix_ema_period: int = 50,
        alpha_VIX: Decimal = Decimal("1.0"),

        # ==================================================================
        # TIER 5: DRAWDOWN GOVERNOR (3 parameters)
        # ==================================================================
        DD_soft: Decimal = Decimal("0.10"),
        DD_hard: Decimal = Decimal("0.20"),
        p_min: Decimal = Decimal("0.0"),

        # ==================================================================
        # TIER 6: REBALANCING CONTROL (1 parameter)
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # SYMBOL CONFIGURATION (5 parameters)
        # ==================================================================
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        leveraged_short_symbol: str = "SQQQ",
        vix_symbol: str = "$VIX",

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Hierarchical_Adaptive_v2_8"
    ):
        """
        Initialize Hierarchical Adaptive v2.8 strategy.

        v2.8 Changes (Two-Parameter Floor System):
        - Replaced E_min with E_anchor (DD governor anchor) and E_short (clip floor)
        - Increased k_short range to [0.8, 1.2] (was [0.2, 0.4])
        - DD governor anchors to E_anchor (positive defensive floor)
        - Final clipping uses E_short (possibly negative)
        - Added w_SQQQ_max to cap SQQQ positions

        Args:
            measurement_noise: Kalman filter measurement noise (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 15)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 60)
            k_long: Trend sensitivity for LONG regimes (default: 0.7)
            k_short: Trend sensitivity for SHORT regimes (default: 1.0, range: [0.8, 1.2])
            E_anchor: DD governor anchor - positive defensive floor (default: 0.7)
            E_short: Global clip floor - enables negative exposure (default: -0.2)
            E_max: Maximum exposure (default: 1.5 = 150% long)
            w_SQQQ_max: Maximum SQQQ weight (default: 0.25 = 25%)
            sigma_target_multiplier: Target volatility multiplier (default: 0.9)
            realized_vol_lookback: Realized vol calculation period (default: 20)
            S_vol_min: Minimum volatility scaler (default: 0.5)
            S_vol_max: Maximum volatility scaler (default: 1.5)
            vix_ema_period: VIX EMA period (default: 50)
            alpha_VIX: VIX compression factor (default: 1.0)
            DD_soft: Soft drawdown threshold (default: 0.10 = 10%)
            DD_hard: Hard drawdown threshold (default: 0.20 = 20%)
            p_min: Minimum drawdown penalty (default: 0.0)
            rebalance_threshold: Weight drift threshold (default: 0.025 = 2.5%)
            signal_symbol: Signal generation symbol (default: 'QQQ')
            core_long_symbol: 1x long symbol (default: 'QQQ')
            leveraged_long_symbol: 3x long symbol (default: 'TQQQ')
            leveraged_short_symbol: 3x inverse symbol (default: 'SQQQ')
            vix_symbol: Volatility index symbol (default: '$VIX')
            trade_logger: Optional TradeLogger (default: None)
            name: Strategy name (default: 'Hierarchical_Adaptive_v2_8')
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate two-parameter floor system
        if not (E_short < Decimal("0.0") <= E_anchor < E_max):
            raise ValueError(
                f"Two-parameter floor system requires: "
                f"E_short ({E_short}) < 0 <= E_anchor ({E_anchor}) < E_max ({E_max})"
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

        if not (Decimal("0.0") < w_SQQQ_max <= Decimal("1.0")):
            raise ValueError(
                f"SQQQ cap must be in (0, 1], got {w_SQQQ_max}"
            )

        # Store all parameters
        self.measurement_noise = measurement_noise
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.T_max = T_max

        self.k_long = k_long
        self.k_short = k_short
        self.E_anchor = E_anchor
        self.E_short = E_short
        self.E_max = E_max
        self.w_SQQQ_max = w_SQQQ_max

        self.sigma_target_multiplier = sigma_target_multiplier
        self.realized_vol_lookback = realized_vol_lookback
        self.S_vol_min = S_vol_min
        self.S_vol_max = S_vol_max

        self.vix_ema_period = vix_ema_period
        self.alpha_VIX = alpha_VIX

        self.DD_soft = DD_soft
        self.DD_hard = DD_hard
        self.p_min = p_min

        self.rebalance_threshold = rebalance_threshold

        self.signal_symbol = signal_symbol
        self.core_long_symbol = core_long_symbol
        self.leveraged_long_symbol = leveraged_long_symbol
        self.leveraged_short_symbol = leveraged_short_symbol
        self.vix_symbol = vix_symbol

        # State variables
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.sigma_target: Optional[Decimal] = None
        self.equity_peak: Decimal = Decimal("0")
        self.current_exposure: Decimal = Decimal("1.0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_sqqq_weight: Decimal = Decimal("0")

        logger.info(
            f"Initialized {name} (v2.8 - TWO-PARAMETER FLOOR SYSTEM): "
            f"k_long={k_long}, k_short={k_short} (STRONGER!), "
            f"E_anchor={E_anchor} (DD Anchor), E_short={E_short} (Clip Floor), "
            f"E_max={E_max}, w_SQQQ_max={w_SQQQ_max}"
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
            return_signed=True  # Preserved v2.7 fix
        )

        # Calculate sigma_target from historical data
        qqq_closes = self.get_closes(lookback=999999, symbol=self.signal_symbol)

        if len(qqq_closes) > 50:
            historical_vol_series = annualized_volatility(
                qqq_closes,
                lookback=len(qqq_closes)
            )
            historical_vol = Decimal(str(historical_vol_series.iloc[-1]))
            self.sigma_target = historical_vol * self.sigma_target_multiplier
        else:
            self.sigma_target = Decimal("0.20") * self.sigma_target_multiplier

        # Initialize state tracking
        self.equity_peak = Decimal("0")
        self.current_exposure = Decimal("1.0")
        self.current_qqq_weight = Decimal("0")
        self.current_tqqq_weight = Decimal("0")
        self.current_sqqq_weight = Decimal("0")

        logger.info(
            f"Initialized {self.name} (v2.8) with sigma_target: {self.sigma_target:.4f}"
        )

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through 5-tier exposure engine with v2.8 two-parameter floor system.
        """
        # Only process signal symbol
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check
        min_warmup = max(self.vix_ema_period, self.realized_vol_lookback * 2) + 10
        if len(self._bars) < min_warmup:
            logger.debug(f"Warmup: {len(self._bars)}/{min_warmup} bars")
            return

        # Tier 1: Update Kalman filter
        filtered_price, trend_strength_signed = self.kalman_filter.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
        trend_strength_decimal = Decimal(str(trend_strength_signed))

        # Tier 2: Calculate normalized trend
        T_norm = self._calculate_normalized_trend(trend_strength_decimal)

        # Tier 3: Calculate baseline exposure (v2.8: STRONGER k_short)
        E_trend = self._calculate_baseline_exposure(T_norm)

        # Tier 4: Apply volatility scaler
        closes = self.get_closes(
            lookback=self.realized_vol_lookback + 10,
            symbol=self.signal_symbol
        )
        vol_series = annualized_volatility(closes, lookback=self.realized_vol_lookback)

        if pd.isna(vol_series.iloc[-1]):
            sigma_real = self.sigma_target
            logger.warning(f"Vol calc returned NaN, using sigma_target: {self.sigma_target:.4f}")
        else:
            sigma_real = Decimal(str(vol_series.iloc[-1]))

        S_vol, E_vol = self._apply_volatility_scaler(E_trend, sigma_real)

        # Tier 5: Apply VIX compression
        vix_closes = self.get_closes(
            lookback=self.vix_ema_period + 10,
            symbol=self.vix_symbol
        )
        vix_ema_series = ema(vix_closes, self.vix_ema_period)

        if len(vix_closes) < self.vix_ema_period:
            logger.warning(f"Insufficient VIX data: need {self.vix_ema_period}, have {len(vix_closes)}")
            return

        vix_current = Decimal(str(vix_closes.iloc[-1]))

        if pd.isna(vix_ema_series.iloc[-1]):
            logger.warning("VIX EMA returned NaN")
            return

        vix_ema_value = Decimal(str(vix_ema_series.iloc[-1]))
        R_VIX = vix_current / vix_ema_value if vix_ema_value > Decimal("0") else Decimal("1.0")
        P_VIX, E_volVIX = self._apply_vix_compression(E_vol, R_VIX)

        # Tier 6: Apply drawdown governor (v2.8 FIX: Anchors to E_anchor)
        portfolio_equity = self._cash
        for symbol, qty in self._positions.items():
            if qty > 0:
                symbol_bars = [b for b in self._bars if b.symbol == symbol]
                if symbol_bars:
                    latest_price = symbol_bars[-1].close
                    portfolio_equity += Decimal(str(qty)) * latest_price

        DD_current = self._update_drawdown_tracking(portfolio_equity)
        P_DD, E_raw = self._apply_drawdown_governor(E_volVIX, DD_current)

        # Tier 7: Clip to bounds (v2.8 FIX: Uses E_short floor)
        E_t = max(self.E_short, min(self.E_max, E_raw))
        self.current_exposure = E_t

        # Tier 8: Map to weights (v2.8: SQQQ cap)
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = self._map_exposure_to_weights(E_t)

        # Tier 9: Check rebalancing threshold
        needs_rebalance = self._check_rebalancing_threshold(w_QQQ, w_TQQQ, w_SQQQ)

        # Tier 10: Log context
        logger.info(
            f"[{bar.timestamp}] v2.8 Exposure | "
            f"fp={filtered_price:.3f}, str={trend_strength_decimal:.3f} → T_norm={T_norm:.3f} → "
            f"E_trend={E_trend:.3f} (k_short={self.k_short}) → S_vol={S_vol:.3f} → E_vol={E_vol:.3f} → "
            f"P_VIX={P_VIX:.3f} → E_volVIX={E_volVIX:.3f} → "
            f"P_DD={P_DD:.3f}/DD={DD_current:.3f} (→E_anchor!) → E_raw={E_raw:.3f} → "
            f"E_t={E_t:.3f} [E_short={self.E_short}, E_max={self.E_max}] → "
            f"w_QQQ={w_QQQ:.3f}, w_TQQQ={w_TQQQ:.3f}, w_SQQQ={w_SQQQ:.3f} (cap={self.w_SQQQ_max}), w_cash={w_cash:.3f}"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                for symbol in [self.core_long_symbol, self.leveraged_long_symbol, self.leveraged_short_symbol]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v2.8 Two-Parameter Floor (E_t={E_t:.3f})",
                        decision_reason=(
                            f"Kalman fp={filtered_price:.2f}, str={trend_strength_decimal:.2f} → "
                            f"T_norm {T_norm:.3f}, E_trend {E_trend:.3f}, Vol {S_vol:.3f}, VIX {P_VIX:.3f}, "
                            f"DD {P_DD:.3f} (→E_anchor={self.E_anchor}) → E_t {E_t:.3f} [floor={self.E_short}]"
                        ),
                        indicator_values={
                            'filtered_price': float(filtered_price),
                            'trend_strength_signed': float(trend_strength_decimal),
                            'T_norm': float(T_norm),
                            'E_trend': float(E_trend),
                            'E_t': float(E_t),
                            'sigma_real': float(sigma_real),
                            'R_VIX': float(R_VIX),
                            'DD_current': float(DD_current)
                        },
                        threshold_values={
                            'T_max': float(self.T_max),
                            'E_anchor': float(self.E_anchor),
                            'E_short': float(self.E_short),
                            'E_max': float(self.E_max),
                            'w_SQQQ_max': float(self.w_SQQQ_max),
                            'DD_soft': float(self.DD_soft),
                            'DD_hard': float(self.DD_hard)
                        }
                    )

            self._execute_rebalance(w_QQQ, w_TQQQ, w_SQQQ, portfolio_equity)

    # ===== Tier calculation methods =====

    def _calculate_normalized_trend(
        self,
        trend_strength_signed: Decimal
    ) -> Decimal:
        """
        Calculate normalized SIGNED trend.
        """
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_baseline_exposure(self, T_norm: Decimal) -> Decimal:
        """
        Calculate baseline exposure from normalized trend using ASYMMETRIC scaling.

        v2.8 CRITICAL CHANGE:
        - k_short now in range [0.8, 1.2] (was [0.2, 0.4])
        - With k_short ≥ 1.0, E_trend can go NEGATIVE when T_norm = -1
        - This enables SQQQ reach when trend warrants

        Mathematical Example (k_short=1.0):
        - T_norm = -1.0 (strong bear)
        - E_trend = 1.0 + 1.0 × (-1.0) = 0.0
        - Vol/VIX can compress further → E_volVIX < 0
        - With mild DD (P_DD ≈ 1) → E_raw < 0
        - Clipped to [E_short, E_max] → E_t can be negative

        Returns:
            E_trend ∈ [1.0 - k_short, 1.0 + k_long]
        """
        if T_norm >= Decimal("0"):
            return Decimal("1.0") + self.k_long * T_norm
        else:
            return Decimal("1.0") + self.k_short * T_norm

    def _apply_volatility_scaler(
        self,
        E_trend: Decimal,
        sigma_real: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Apply volatility scaler to deviations from 1.0.

        Returns:
            (S_vol, E_vol) where E_vol = 1.0 + (E_trend - 1.0) × S_vol
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
        Apply VIX compression to deviations from 1.0.

        Returns:
            (P_VIX, E_volVIX) where E_volVIX = 1.0 + (E_vol - 1.0) × P_VIX
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
        Apply drawdown governor with E_anchor as positive defensive floor.

        v2.8 CRITICAL FIX:
        - Anchors to self.E_anchor (positive defensive floor, e.g. 0.7)
        - NOT to self.E_short (which is the global clip floor)
        - Prevents deep drawdowns from forcing system further short

        Mathematical Behavior:
        - Mild DD (P_DD ≈ 1): E_raw ≈ E_volVIX (trend-driven, can be negative)
        - Deep DD (P_DD → 0): E_raw → E_anchor (safe positive floor)

        Returns:
            (P_DD, E_raw) where E_raw = E_anchor + (E_volVIX - E_anchor) × P_DD
        """
        if DD_current <= self.DD_soft:
            P_DD = Decimal("1.0")
        elif DD_current >= self.DD_hard:
            P_DD = self.p_min
        else:
            dd_range = self.DD_hard - self.DD_soft
            dd_excess = DD_current - self.DD_soft
            P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

        # v2.8 FIX: Interpolate toward E_anchor (positive defensive floor)
        E_raw = self.E_anchor + (E_volVIX - self.E_anchor) * P_DD

        return P_DD, E_raw

    def _map_exposure_to_weights(
        self,
        E_t: Decimal
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Map final exposure to 4-weight allocation: (w_QQQ, w_TQQQ, w_SQQQ, w_cash)

        v2.8 CHANGE: SQQQ weight capped at w_SQQQ_max (e.g. 0.25)

        Effective exposure: E_t ≈ w_QQQ × 1 + w_TQQQ × 3 - w_SQQQ × 3

        Returns:
            (w_QQQ, w_TQQQ, w_SQQQ, w_cash) with sum = 1.0
        """
        if E_t <= Decimal("-1.0"):
            # Region 1: Leveraged short (fully invested)
            w_SQQQ = (Decimal("1.0") - E_t) / Decimal("4.0")
            w_SQQQ = min(w_SQQQ, self.w_SQQQ_max)  # v2.8: Apply cap
            w_QQQ = Decimal("1.0") - w_SQQQ
            w_TQQQ = Decimal("0")
            w_cash = Decimal("0")

        elif E_t < Decimal("0"):
            # Region 2: Defensive short (v2.8: CAP SQQQ weight)
            w_SQQQ = -E_t / Decimal("3.0")
            w_SQQQ = min(w_SQQQ, self.w_SQQQ_max)  # v2.8: Apply cap
            w_QQQ = Decimal("0")
            w_TQQQ = Decimal("0")
            w_cash = Decimal("1.0") - w_SQQQ

        elif E_t <= Decimal("1.0"):
            # Region 3: Defensive long
            w_QQQ = E_t
            w_TQQQ = Decimal("0")
            w_SQQQ = Decimal("0")
            w_cash = Decimal("1.0") - E_t

        else:  # E_t > 1.0
            # Region 4: Leveraged long
            w_TQQQ = (E_t - Decimal("1.0")) / Decimal("2.0")
            w_QQQ = Decimal("1.0") - w_TQQQ
            w_SQQQ = Decimal("0")
            w_cash = Decimal("0")

        return w_QQQ, w_TQQQ, w_SQQQ, w_cash

    def _check_rebalancing_threshold(
        self,
        target_qqq_weight: Decimal,
        target_tqqq_weight: Decimal,
        target_sqqq_weight: Decimal
    ) -> bool:
        """Check if portfolio weights drifted > threshold."""
        weight_deviation = (
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_tqqq_weight - target_tqqq_weight) +
            abs(self.current_sqqq_weight - target_sqqq_weight)
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance(
        self,
        target_qqq_weight: Decimal,
        target_tqqq_weight: Decimal,
        target_sqqq_weight: Decimal,
        portfolio_equity: Decimal
    ) -> None:
        """
        Rebalance portfolio to target weights using two-phase execution.
        
        v2.7.1 Fix: Checks if allocation > share price to avoid 0-share orders.
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
                
            allocation_value = portfolio_equity * weight
            if allocation_value < price:
                # Log debug, but silently coerce to 0 to avoid engine warning
                logger.debug(
                    f"Skipping {symbol} buy: Allocation ${allocation_value:.2f} < Price ${price:.2f}"
                )
                return Decimal("0")
            
            return weight

        # Validate weights before execution
        target_qqq_weight = _validate_weight(self.core_long_symbol, target_qqq_weight)
        target_tqqq_weight = _validate_weight(self.leveraged_long_symbol, target_tqqq_weight)
        target_sqqq_weight = _validate_weight(self.leveraged_short_symbol, target_sqqq_weight)

        # Phase 1: REDUCE positions (execute SELLs first to free cash)

        # QQQ: Reduce if needed
        if target_qqq_weight == Decimal("0"):
            self.sell(self.core_long_symbol, Decimal("0.0"))
        elif target_qqq_weight > Decimal("0") and target_qqq_weight < self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # TQQQ: Reduce if needed
        if target_tqqq_weight == Decimal("0"):
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))
        elif target_tqqq_weight > Decimal("0") and target_tqqq_weight < self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # SQQQ: Reduce if needed
        if target_sqqq_weight == Decimal("0"):
            self.sell(self.leveraged_short_symbol, Decimal("0.0"))
        elif target_sqqq_weight > Decimal("0") and target_sqqq_weight < self.current_sqqq_weight:
            self.buy(self.leveraged_short_symbol, target_sqqq_weight)

        # Phase 2: INCREASE positions (execute BUYs second with freed cash)

        # QQQ: Increase if needed
        if target_qqq_weight > Decimal("0") and target_qqq_weight > self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)

        # TQQQ: Increase if needed
        if target_tqqq_weight > Decimal("0") and target_tqqq_weight > self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)

        # SQQQ: Increase if needed
        if target_sqqq_weight > Decimal("0") and target_sqqq_weight > self.current_sqqq_weight:
            self.buy(self.leveraged_short_symbol, target_sqqq_weight)

        # Update current weights
        self.current_qqq_weight = target_qqq_weight
        self.current_tqqq_weight = target_tqqq_weight
        self.current_sqqq_weight = target_sqqq_weight

        logger.info(
            f"Executed v2.8 two-phase rebalance: QQQ={target_qqq_weight:.3f}, "
            f"TQQQ={target_tqqq_weight:.3f}, SQQQ={target_sqqq_weight:.3f} (cap={self.w_SQQQ_max})"
        )

    def _update_drawdown_tracking(self, portfolio_equity: Decimal) -> Decimal:
        """Track peak-to-trough drawdown."""
        if portfolio_equity > self.equity_peak:
            self.equity_peak = portfolio_equity

        if self.equity_peak > Decimal("0"):
            DD_current = (self.equity_peak - portfolio_equity) / self.equity_peak
        else:
            DD_current = Decimal("0")

        return DD_current
