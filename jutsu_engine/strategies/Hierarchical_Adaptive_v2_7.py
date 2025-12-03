"""
Hierarchical Adaptive v2.7: Three Critical Bug Fixes from v2.6

v2.7 fixes three critical bugs discovered in v2.6 that prevented proper operation:

Critical Fixes:
1. **Signed Trend (ROOT CAUSE)**: Use oscillator sign, not just magnitude
   - v2.6 bug: Used unsigned trend_strength → T_norm ∈ [0, 1] → E_trend ≥ 1.0 always
   - v2.7 fix: Use signed trend (strength * sign(oscillator)) → T_norm ∈ [-1, +1]
   - Impact: Enables bearish baseline exposure (E_t < 1.0), SQQQ region reachable

2. **DD Governor Anchor (ROOT CAUSE)**: Converge to 0 (cash), not 1.0 (QQQ)
   - v2.6 bug: Defensive path interpolated between E_volVIX and 1.0
   - v2.7 fix: Single formula E_raw = E_floor + (E_volVIX - E_floor) * P_DD with E_floor = 0
   - Impact: Deep DD now goes to cash (defensive), not 100% QQQ (opposite of intent)

3. **SQQQ Logging (MINOR)**: Add SQQQ position tracking to daily log
   - v2.6 bug: Daily log missing SQQQ_Qty and SQQQ_Value fields
   - v2.7 fix: Added SQQQ fields to portfolio snapshot logging
   - Impact: SQQQ positions now visible in diagnostics

v2.7 Version Evolution:
- v2.0 → v2.5: DD governor "fix" (incomplete, still anchored to 1.0)
- v2.5 → v2.6: SQQQ capability (inherited v2.5 bugs + new unsigned trend bug)
- v2.6 → v2.7: True fix for all three bugs (this version)

Why v2.7 Not v2.6 Patch:
- v2.6 has fundamental logic bugs that change behavior significantly
- Grid search results for v2.6 are invalid (strategy wasn't working as designed)
- v2.7 represents correct implementation of intended v2.6 design

Expected Behavior Changes After Fixes:
- Strategy can now enter bearish regimes (E_t < 1.0)
- SQQQ positions will appear during bear markets
- E_min parameter becomes meaningful (not flat like v2.6 Phase 2)
- Max DD should improve (defensive positioning active)
- DD governor converges to cash in deep drawdown (not QQQ)

All v2.5/v2.6 features preserved:
- ✅ Same 5-tier exposure engine
- ✅ Same Kalman filter configuration
- ✅ Same vol/VIX modulators
- ✅ Same drift-based rebalancing mechanism
- ✅ Same 4-weight position mapping (QQQ, TQQQ, SQQQ, cash)

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

logger = logging.getLogger('STRATEGY.HIERARCHICAL_ADAPTIVE_V2_7')


class Hierarchical_Adaptive_v2_7(Strategy):
    """
    Hierarchical Adaptive v2.7: Three Critical Bug Fixes from v2.6

    v2.7 fixes three critical bugs that prevented v2.6 from working as designed:

    Fix 1: Signed Trend (CRITICAL - ROOT CAUSE)
    ------------------------------------------
    v2.6 Bug:
        - Used only magnitude (trend_strength) from Kalman filter
        - Discarded signed oscillator
        - Result: T_norm ∈ [0, 1] not [-1, +1], E_trend ≥ 1.0 always
        - Evidence: Run 268 showed Indicator_trend_strength strictly positive

    v2.7 Fix:
        - Use both oscillator and trend_strength from Kalman filter
        - Derive signed trend: trend_signed = strength * sign(oscillator)
        - Normalize to [-1, +1]: T_norm = trend_signed / T_max
        - Result: E_trend ∈ [1-k_trend, 1+k_trend], e.g., [0.3, 1.7] for k_trend=0.7

    Impact:
        - Strategy can now express bearish regimes (E_t < 1.0)
        - SQQQ region becomes reachable
        - E_min parameter becomes meaningful

    Fix 2: DD Governor Anchor (CRITICAL - ROOT CAUSE)
    -------------------------------------------------
    v2.6 Bug:
        - Defensive path: E_raw = E_volVIX * P_DD + 1.0 * (1 - P_DD)
        - Converged to 1.0 (100% QQQ) when P_DD → 0 (deep DD)
        - Mathematical proof: E_volVIX = -0.6, P_DD = 0 → E_raw = 1.0
        - Opposite of intent: removed short exposure as DD worsened

    v2.7 Fix:
        - Single formula: E_raw = E_floor + (E_volVIX - E_floor) * P_DD
        - E_floor = 0 (cash in deep DD, conservative for v2.7)
        - Deep DD now converges to 0 (cash), not 1.0 (QQQ)

    Impact:
        - DD governor now acts as true defensive brake
        - Deep DD → cash (0), not QQQ (1.0)
        - Max DD should improve

    Fix 3: SQQQ Logging (MINOR)
    ---------------------------
    v2.6 Bug:
        - Daily log missing SQQQ_Qty and SQQQ_Value fields
        - Diagnostics difficult once SQQQ positions appear

    v2.7 Fix:
        - Added SQQQ fields to daily portfolio log
        - SQQQ positions now visible in daily logs

    5-Tier Exposure Engine (same as v2.5/v2.6):
    - Tier 1: Kalman trend engine (FIXED: now uses signed trend!)
    - Tier 2: Volatility modulator (realized vol scaler)
    - Tier 3: VIX compression (soft filter)
    - Tier 4: Drawdown governor (FIXED: now converges to 0, not 1!)
    - Tier 5: QQQ/TQQQ/SQQQ/cash position mapping

    Position Mapping (same as v2.6):
    - E_t <= -1.0: Leveraged short (QQQ + SQQQ, fully invested)
    - -1.0 < E_t < 0: Defensive short (SQQQ + cash)
    - 0 <= E_t <= 1.0: Defensive long (QQQ + cash)
    - E_t > 1.0: Leveraged long (QQQ + TQQQ)

    Performance Targets:
        - Processing Speed: <3ms per bar
        - Memory: O(max_lookback_period)
        - Backtest: 2010-2025 in <20 seconds

    Example:
        strategy = Hierarchical_Adaptive_v2_7(
            E_min=Decimal("-0.5"),  # Can go 50% net short
            E_max=Decimal("1.5"),
            leveraged_short_symbol="SQQQ",
            # ... (all v2.6 parameters)
        )

    v2.7 Changelog:
    - Fixed signed trend (use oscillator sign, not just magnitude)
    - Fixed DD governor (converge to 0, not 1.0)
    - Added SQQQ logging fields
    """

    def __init__(
        self,
        # ==================================================================
        # TIER 1: KALMAN FILTER PARAMETERS (6 parameters) - Same as v2.6
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("60"),

        # ==================================================================
        # TIER 0: CORE EXPOSURE ENGINE (3 parameters) - Same as v2.6
        # ==================================================================
        k_trend: Decimal = Decimal("0.3"),
        E_min: Decimal = Decimal("-0.5"),
        E_max: Decimal = Decimal("1.5"),

        # ==================================================================
        # TIER 2: VOLATILITY MODULATOR (4 parameters) - Same as v2.6
        # ==================================================================
        sigma_target_multiplier: Decimal = Decimal("0.9"),
        realized_vol_lookback: int = 20,
        S_vol_min: Decimal = Decimal("0.5"),
        S_vol_max: Decimal = Decimal("1.5"),

        # ==================================================================
        # TIER 3: VIX MODULATOR (2 parameters) - Same as v2.6
        # ==================================================================
        vix_ema_period: int = 50,
        alpha_VIX: Decimal = Decimal("1.0"),

        # ==================================================================
        # TIER 4: DRAWDOWN GOVERNOR (3 parameters) - Same as v2.6
        # ==================================================================
        DD_soft: Decimal = Decimal("0.10"),
        DD_hard: Decimal = Decimal("0.20"),
        p_min: Decimal = Decimal("0.0"),

        # ==================================================================
        # TIER 5: REBALANCING CONTROL (1 parameter) - Same as v2.6
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # SYMBOL CONFIGURATION (5 parameters) - Same as v2.6
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
        name: str = "Hierarchical_Adaptive_v2_7"
    ):
        """
        Initialize Hierarchical Adaptive v2.7 strategy with 21 parameters.

        v2.7 Changes from v2.6:
        - CRITICAL FIX 1: Signed trend (use oscillator sign, not just magnitude)
        - CRITICAL FIX 2: DD governor (converge to 0, not 1.0)
        - MINOR FIX 3: SQQQ logging (added fields to daily log)
        - All parameters same as v2.6

        Total Parameters: 21 (same as v2.6)

        Args:
            measurement_noise: Kalman filter measurement noise (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 15)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 60)
            k_trend: Trend sensitivity (default: 0.3)
            E_min: Minimum exposure (default: -0.5 = 50% net short)
            E_max: Maximum exposure (default: 1.5 = 150% long)
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
            name: Strategy name (default: 'Hierarchical_Adaptive_v2_7')

        Raises:
            ValueError: If parameter constraints violated
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate parameter constraints (same as v2.6)
        if not (E_min < E_max):
            raise ValueError(
                f"Exposure bounds must satisfy E_min ({E_min}) < E_max ({E_max})"
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

        # Store all parameters (same as v2.6)
        self.measurement_noise = measurement_noise
        self.process_noise_1 = process_noise_1
        self.process_noise_2 = process_noise_2
        self.osc_smoothness = osc_smoothness
        self.strength_smoothness = strength_smoothness
        self.T_max = T_max

        self.k_trend = k_trend
        self.E_min = E_min
        self.E_max = E_max

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

        # State variables (same as v2.6)
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.sigma_target: Optional[Decimal] = None
        self.equity_peak: Decimal = Decimal("0")
        self.current_exposure: Decimal = Decimal("1.0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_sqqq_weight: Decimal = Decimal("0")

        logger.info(
            f"Initialized {name} with 21 parameters (v2.7 - THREE CRITICAL FIXES): "
            f"E_min={E_min}, E_max={E_max}, "
            f"SQQQ={leveraged_short_symbol}, DD=[{DD_soft}, {DD_hard}]"
        )

    def init(self) -> None:
        """Initialize strategy state (same as v2.6)."""
        # Initialize Kalman filter
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=float(self.measurement_noise),
            process_noise_1=float(self.process_noise_1),
            process_noise_2=float(self.process_noise_2),
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness,
            return_signed=True  # v2.8 FIX: Enable signed output for bearish regimes
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
            f"Initialized {self.name} (v2.7 - FIXED) with sigma_target: {self.sigma_target:.4f}"
        )

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through 5-tier exposure engine.

        v2.7 FIXES:
        - Step 3: Now uses SIGNED trend (fix 1)
        - Step 7: DD governor now converges to 0, not 1.0 (fix 2)
        - Step 11: SQQQ logging added (fix 3)
        """
        # Only process signal symbol
        if bar.symbol != self.signal_symbol:
            return

        # Warmup period check
        min_warmup = max(self.vix_ema_period, self.realized_vol_lookback * 2) + 10
        if len(self._bars) < min_warmup:
            logger.debug(f"Warmup: {len(self._bars)}/{min_warmup} bars")
            return

        # Tier 1: Update Kalman filter (v2.8 FIX: Get signed trend_strength!)
        filtered_price, trend_strength_signed = self.kalman_filter.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
        # Note: filtered_price is Kalman-filtered price (not used for signal)
        # Note: trend_strength_signed is now SIGNED (can be negative for bearish regimes)
        trend_strength_decimal = Decimal(str(trend_strength_signed))

        # Tier 2: Calculate normalized trend (v2.8 FIX: Use signed trend directly!)
        T_norm = self._calculate_normalized_trend(trend_strength_decimal)

        # Tier 3: Calculate baseline exposure
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

        # Tier 6: Apply drawdown governor (FIX 2: Converge to 0, not 1.0!)
        portfolio_equity = self._cash
        for symbol, qty in self._positions.items():
            if qty > 0:
                symbol_bars = [b for b in self._bars if b.symbol == symbol]
                if symbol_bars:
                    latest_price = symbol_bars[-1].close
                    portfolio_equity += Decimal(str(qty)) * latest_price

        DD_current = self._update_drawdown_tracking(portfolio_equity)
        P_DD, E_raw = self._apply_drawdown_governor(E_volVIX, DD_current)

        # Tier 7: Clip to bounds
        E_t = max(self.E_min, min(self.E_max, E_raw))
        self.current_exposure = E_t

        # Tier 8: Map to weights (same as v2.6)
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = self._map_exposure_to_weights(E_t)

        # Tier 9: Check rebalancing threshold
        needs_rebalance = self._check_rebalancing_threshold(w_QQQ, w_TQQQ, w_SQQQ)

        # Tier 10: Log context (v2.8 markers)
        logger.info(
            f"[{bar.timestamp}] v2.8 FIXED Exposure Calculation | "
            f"fp={filtered_price:.3f}, str_signed={trend_strength_decimal:.3f} → T_norm={T_norm:.3f} (SIGNED!) → "
            f"E_trend={E_trend:.3f} → S_vol={S_vol:.3f} → E_vol={E_vol:.3f} → "
            f"P_VIX={P_VIX:.3f} → E_volVIX={E_volVIX:.3f} → "
            f"P_DD={P_DD:.3f}/DD={DD_current:.3f} (→0 not 1!) → E_t={E_t:.3f} → "
            f"w_QQQ={w_QQQ:.3f}, w_TQQQ={w_TQQQ:.3f}, w_SQQQ={w_SQQQ:.3f}, w_cash={w_cash:.3f}"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                # Log context for all traded symbols (FIX 3: Include SQQQ!)
                for symbol in [self.core_long_symbol, self.leveraged_long_symbol, self.leveraged_short_symbol]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v2.8 FIXED Continuous Exposure (E_t={E_t:.3f})",
                        decision_reason=(
                            f"Kalman fp={filtered_price:.2f}, str_signed={trend_strength_decimal:.2f} → "
                            f"T_norm {T_norm:.3f} (SIGNED!), Vol {S_vol:.3f}, VIX {P_VIX:.3f}, "
                            f"DD {P_DD:.3f} (→0 not 1!) → E_t {E_t:.3f}"
                        ),
                        indicator_values={
                            'filtered_price': float(filtered_price),
                            'trend_strength_signed': float(trend_strength_decimal),
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

            self._execute_rebalance(w_QQQ, w_TQQQ, w_SQQQ)

    # ===== Tier calculation methods =====

    def _calculate_normalized_trend(
        self,
        trend_strength_signed: Decimal
    ) -> Decimal:
        """
        Calculate normalized SIGNED trend.

        v2.8 FIX: Kalman now returns SIGNED trend_strength directly!

        v2.6 Bug:
            - Only used trend_strength (magnitude)
            - Result: T_norm ∈ [0, 1] not [-1, +1]

        v2.7 Attempted Fix (FAILED):
            - Tried to derive sign from oscillator: sign = sign(oscillator)
            - But "oscillator" was actually filtered_price (stock price, always positive)
            - Result: sign always +1.0, T_norm still always positive

        v2.8 Fix (CORRECT):
            - Kalman filter now has return_signed=True parameter
            - Returns trend_strength_signed directly (can be negative)
            - Just normalize to [-1, +1] range

        Impact:
            - T_norm can now be negative during bearish regimes
            - E_trend can go below 1.0
            - SQQQ region becomes reachable

        Args:
            trend_strength_signed: SIGNED trend strength from Kalman (can be ±)

        Returns:
            T_norm ∈ [-1, +1] (SIGNED, not [0, 1]!)
        """
        # Normalize to [-1, +1] (trend_strength_signed already has sign!)
        T_norm = trend_strength_signed / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_baseline_exposure(self, T_norm: Decimal) -> Decimal:
        """
        Calculate baseline exposure from normalized trend.

        E_trend = 1.0 + k_trend * T_norm

        With SIGNED T_norm ∈ [-1, +1]:
        - E_trend ∈ [1 - k_trend, 1 + k_trend]
        - Example: k_trend = 0.7 → E_trend ∈ [0.3, 1.7]

        This enables bearish baseline exposure (E_trend < 1.0)
        """
        return Decimal("1.0") + self.k_trend * T_norm

    def _apply_volatility_scaler(
        self,
        E_trend: Decimal,
        sigma_real: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Apply volatility scaler (same as v2.6)."""
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
        """Apply VIX compression (same as v2.6)."""
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
        Apply drawdown governor with FIXED defensive anchor.

        v2.7 FIX 2: Converge to 0 (cash), not 1.0 (QQQ)!

        v2.6 Bug:
            - Defensive path: E_raw = E_volVIX * P_DD + 1.0 * (1 - P_DD)
            - Deep DD (P_DD → 0) converged to 1.0 (100% QQQ)
            - Opposite of intent: removed short exposure as DD worsened

        v2.7 Fix:
            - Single formula: E_raw = E_floor + (E_volVIX - E_floor) * P_DD
            - E_floor = 0 (cash in deep DD, conservative)
            - Deep DD (P_DD → 0) now converges to 0 (cash)

        Impact:
            - DD governor now acts as true defensive brake
            - Deep DD → cash (0), not QQQ (1.0)
            - Max DD should improve

        Behavior:
            - P_DD = 1 (no DD) → E_raw = E_volVIX (full exposure)
            - P_DD = 0 (deep DD) → E_raw = 0 (cash, not 1.0!)
            - P_DD ∈ (0,1) → Smooth interpolation toward 0

        Args:
            E_volVIX: Exposure after vol/VIX modulation
            DD_current: Current drawdown (0.0 to 1.0)

        Returns:
            (P_DD, E_raw) tuple
        """
        # Calculate P_DD (same as v2.6)
        if DD_current <= self.DD_soft:
            P_DD = Decimal("1.0")
        elif DD_current >= self.DD_hard:
            P_DD = self.p_min
        else:
            dd_range = self.DD_hard - self.DD_soft
            dd_excess = DD_current - self.DD_soft
            P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

        # FIX 2: Single interpolation toward E_floor = 0 (not 1.0!)
        E_floor = Decimal("0.0")  # Cash in deep DD (conservative for v2.7)
        E_raw = E_floor + (E_volVIX - E_floor) * P_DD

        return P_DD, E_raw

    def _map_exposure_to_weights(
        self,
        E_t: Decimal
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Map final exposure to 4-weight allocation: (w_QQQ, w_TQQQ, w_SQQQ, w_cash)

        Same as v2.6 (this part was correct).

        Regions:
        1. E_t <= -1.0: Leveraged short (QQQ + SQQQ, fully invested)
        2. -1.0 < E_t < 0: Defensive short (SQQQ + cash)
        3. 0 <= E_t <= 1.0: Defensive long (QQQ + cash)
        4. E_t > 1.0: Leveraged long (QQQ + TQQQ)
        """
        if E_t <= Decimal("-1.0"):
            # Region 1: Leveraged short (fully invested)
            w_SQQQ = (Decimal("1.0") - E_t) / Decimal("4.0")
            w_QQQ = Decimal("1.0") - w_SQQQ
            w_TQQQ = Decimal("0")
            w_cash = Decimal("0")

        elif E_t < Decimal("0"):
            # Region 2: Defensive short
            w_SQQQ = -E_t / Decimal("3.0")
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
        """
        Check if portfolio weights drifted > threshold.

        Same as v2.6 (includes SQQQ in deviation calculation).
        """
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
        target_sqqq_weight: Decimal
    ) -> None:
        """
        Rebalance portfolio to target weights using two-phase execution.

        Two-Phase Approach:
        1. Phase 1: Execute all position REDUCTIONS (SELLs) first to free cash
        2. Phase 2: Execute all position INCREASES (BUYs) second with freed cash

        This prevents "Insufficient cash" errors when rebalancing between multiple
        positions where one needs to shrink (freeing cash) and another needs to grow.

        Note: Portfolio.execute_signal() handles delta-based logic automatically:
        - If target < current weight: Portfolio SELLS to reduce position
        - If target > current weight: Portfolio BUYS to increase position
        - If target = 0: Close position entirely
        """
        # Phase 1: REDUCE positions (execute SELLs first to free cash)

        # QQQ: Reduce if needed
        if target_qqq_weight == Decimal("0"):
            self.sell(self.core_long_symbol, Decimal("0.0"))
        elif target_qqq_weight > Decimal("0") and target_qqq_weight < self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)  # Portfolio delta logic will SELL

        # TQQQ: Reduce if needed
        if target_tqqq_weight == Decimal("0"):
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))
        elif target_tqqq_weight > Decimal("0") and target_tqqq_weight < self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)  # Portfolio delta logic will SELL

        # SQQQ: Reduce if needed
        if target_sqqq_weight == Decimal("0"):
            self.sell(self.leveraged_short_symbol, Decimal("0.0"))
        elif target_sqqq_weight > Decimal("0") and target_sqqq_weight < self.current_sqqq_weight:
            self.buy(self.leveraged_short_symbol, target_sqqq_weight)  # Portfolio delta logic will SELL

        # Phase 2: INCREASE positions (execute BUYs second with freed cash)

        # QQQ: Increase if needed
        if target_qqq_weight > Decimal("0") and target_qqq_weight > self.current_qqq_weight:
            self.buy(self.core_long_symbol, target_qqq_weight)  # Portfolio delta logic will BUY

        # TQQQ: Increase if needed
        if target_tqqq_weight > Decimal("0") and target_tqqq_weight > self.current_tqqq_weight:
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)  # Portfolio delta logic will BUY

        # SQQQ: Increase if needed
        if target_sqqq_weight > Decimal("0") and target_sqqq_weight > self.current_sqqq_weight:
            self.buy(self.leveraged_short_symbol, target_sqqq_weight)  # Portfolio delta logic will BUY

        # Update current weights
        self.current_qqq_weight = target_qqq_weight
        self.current_tqqq_weight = target_tqqq_weight
        self.current_sqqq_weight = target_sqqq_weight

        logger.info(
            f"Executed v2.7 two-phase rebalance: QQQ={target_qqq_weight:.3f}, "
            f"TQQQ={target_tqqq_weight:.3f}, SQQQ={target_sqqq_weight:.3f}"
        )

    def _update_drawdown_tracking(self, portfolio_equity: Decimal) -> Decimal:
        """Track peak-to-trough drawdown (same as v2.6)."""
        if portfolio_equity > self.equity_peak:
            self.equity_peak = portfolio_equity

        if self.equity_peak > Decimal("0"):
            DD_current = (self.equity_peak - portfolio_equity) / self.equity_peak
        else:
            DD_current = Decimal("0")

        return DD_current
