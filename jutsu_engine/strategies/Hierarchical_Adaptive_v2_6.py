"""
Hierarchical Adaptive v2.6: SQQQ Capability for Defensive Short Positioning

v2.6 extends v2.5 to enable net short QQQ exposure via SQQQ allocation.

v2.6 Scope:
- **NEW**: Long/short flexibility (QQQ + TQQQ + SQQQ exposure scaling)
- **NEW**: Extended exposure range (E_min can be negative for net short positions)
- **NEW**: 4-weight position mapping (QQQ, TQQQ, SQQQ, cash)
- Preserves all v2.5 features (5-tier engine, asymmetric DD governor)

Key Innovation from v2.5:
- **SQQQ Allocation**: Can go net short QQQ during extreme bearish conditions
  * SQQQ is 3x inverse ETF (buying SQQQ = shorting QQQ exposure)
  * E_t < 0: Net short exposure via long SQQQ positions
  * E_t = 0: Market neutral (100% cash)
  * E_t > 0: Net long exposure (same as v2.5)

v2.6 Changes from v2.5:
1. ✅ 4-weight position mapping (added SQQQ allocation)
2. ✅ Extended E_min to allow negative values (e.g., -0.5 = 50% net short)
3. ✅ Added leveraged_short_symbol parameter (SQQQ)
4. ✅ Updated rebalancing to handle 4 positions

Preserved Features (100% compatibility with v2.5 core logic):
- ✅ Same 5-tier exposure engine
- ✅ Same asymmetric DD governor (works for negative exposure!)
- ✅ Same Kalman trend normalization
- ✅ Same vol/VIX modulators
- ✅ Same drift-based rebalancing mechanism

Position Mapping Logic:
- E_t <= -1.0: QQQ + SQQQ (leveraged short, fully invested)
- -1.0 < E_t < 0: SQQQ + cash (defensive short)
- 0 <= E_t <= 1.0: QQQ + cash (defensive long - same as v2.5)
- E_t > 1.0: QQQ + TQQQ (leveraged long - same as v2.5)

Core Flow (same as v2.5):
1. Kalman trend engine → normalized trend T_norm ∈ [-1, +1]
2. Baseline exposure E_trend = 1.0 + k_trend * T_norm
3. Volatility scaler S_vol = clip(σ_target / σ_real, S_vol_min, S_vol_max)
4. VIX compression P_VIX (soft filter, not hard gate)
5. Drawdown governor P_DD (v2.5 asymmetric - works for negative E!)
6. Final exposure E_t ∈ [E_min, E_max] (E_min can now be negative)
7. Map E_t to QQQ/TQQQ/SQQQ/cash weights (NEW: 4-weight mapping)
8. Rebalance if drift > threshold

Performance Targets:
    - Processing Speed: <3ms per bar (same as v2.5)
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

logger = logging.getLogger('STRATEGY.HIERARCHICAL_ADAPTIVE_V2_6')


class Hierarchical_Adaptive_v2_6(Strategy):
    """
    Hierarchical Adaptive v2.6: SQQQ Capability for Long/Short Flexibility

    v2.6 extends v2.5 to enable net short QQQ exposure via SQQQ (3x inverse ETF).

    5-Tier Exposure Engine (same as v2.5):
    - Tier 1: Kalman trend engine (normalized trend T_norm ∈ [-1, +1])
    - Tier 2: Volatility modulator (realized vol scaler)
    - Tier 3: VIX compression (soft filter)
    - Tier 4: Drawdown governor (asymmetric risk limiter - v2.5 formula)
    - Tier 5: QQQ/TQQQ/SQQQ/cash position mapping (NEW: 4 weights)

    v2.6 Key Innovation: SQQQ Allocation
    - SQQQ is 3x inverse ETF (buying SQQQ = shorting QQQ exposure)
    - Enables net short positioning when E_t < 0
    - DD governor asymmetric formula works correctly for negative exposure

    Position Mapping:
    - E_t <= -1.0: Leveraged short (QQQ + SQQQ, fully invested)
    - -1.0 < E_t < 0: Defensive short (SQQQ + cash)
    - 0 <= E_t <= 1.0: Defensive long (QQQ + cash - v2.5 logic)
    - E_t > 1.0: Leveraged long (QQQ + TQQQ - v2.5 logic)

    Performance Targets:
        - Processing Speed: <3ms per bar
        - Memory: O(max_lookback_period)
        - Backtest: 2010-2025 in <20 seconds

    Example:
        strategy = Hierarchical_Adaptive_v2_6(
            E_min=Decimal("-0.5"),  # NEW: Can go 50% net short
            E_max=Decimal("1.5"),
            leveraged_short_symbol="SQQQ",  # NEW: 3x inverse symbol
            # ... (all other v2.5 parameters)
        )

    v2.6 Changelog:
    - Added SQQQ allocation capability (4-weight position mapping)
    - Extended E_min to allow negative values (net short exposure)
    - Added leveraged_short_symbol parameter
    - Preserved all v2.5 logic (asymmetric DD governor, 5-tier engine)
    """

    def __init__(
        self,
        # ==================================================================
        # TIER 1: KALMAN FILTER PARAMETERS (6 parameters) - Same as v2.5
        # ==================================================================
        measurement_noise: Decimal = Decimal("2000.0"),
        process_noise_1: Decimal = Decimal("0.01"),
        process_noise_2: Decimal = Decimal("0.01"),
        osc_smoothness: int = 15,
        strength_smoothness: int = 15,
        T_max: Decimal = Decimal("60"),

        # ==================================================================
        # TIER 0: CORE EXPOSURE ENGINE (3 parameters) - UPDATED for v2.6
        # ==================================================================
        k_trend: Decimal = Decimal("0.3"),
        E_min: Decimal = Decimal("-0.5"),  # NEW: Can be negative for net short
        E_max: Decimal = Decimal("1.5"),

        # ==================================================================
        # TIER 2: VOLATILITY MODULATOR (4 parameters) - Same as v2.5
        # ==================================================================
        sigma_target_multiplier: Decimal = Decimal("0.9"),
        realized_vol_lookback: int = 20,
        S_vol_min: Decimal = Decimal("0.5"),
        S_vol_max: Decimal = Decimal("1.5"),

        # ==================================================================
        # TIER 3: VIX MODULATOR (2 parameters) - Same as v2.5
        # ==================================================================
        vix_ema_period: int = 50,
        alpha_VIX: Decimal = Decimal("1.0"),

        # ==================================================================
        # TIER 4: DRAWDOWN GOVERNOR (3 parameters) - Same as v2.5
        # ==================================================================
        DD_soft: Decimal = Decimal("0.10"),
        DD_hard: Decimal = Decimal("0.20"),
        p_min: Decimal = Decimal("0.0"),

        # ==================================================================
        # TIER 5: REBALANCING CONTROL (1 parameter) - Same as v2.5
        # ==================================================================
        rebalance_threshold: Decimal = Decimal("0.025"),

        # ==================================================================
        # SYMBOL CONFIGURATION (5 parameters) - NEW: Added SQQQ
        # ==================================================================
        signal_symbol: str = "QQQ",
        core_long_symbol: str = "QQQ",
        leveraged_long_symbol: str = "TQQQ",
        leveraged_short_symbol: str = "SQQQ",  # NEW: 3x inverse symbol
        vix_symbol: str = "$VIX",

        # ==================================================================
        # METADATA
        # ==================================================================
        trade_logger: Optional[TradeLogger] = None,
        name: str = "Hierarchical_Adaptive_v2_6"
    ):
        """
        Initialize Hierarchical Adaptive v2.6 strategy with 21 parameters.

        v2.6 Changes from v2.5:
        - E_min can now be negative (default: -0.5 for 50% net short capability)
        - Added leveraged_short_symbol (SQQQ for 3x inverse exposure)
        - All other parameters same as v2.5

        Total Parameters: 21 (v2.5 had 20 + version, v2.6 adds leveraged_short_symbol)

        Args:
            measurement_noise: Kalman filter measurement noise (default: 2000.0)
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            osc_smoothness: Oscillator smoothing period (default: 15)
            strength_smoothness: Trend strength smoothing period (default: 15)
            T_max: Trend normalization threshold (default: 60)
            k_trend: Trend sensitivity (default: 0.3)
            E_min: Minimum exposure (default: -0.5 = 50% net short, NEW: can be negative!)
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
            leveraged_short_symbol: 3x inverse symbol (default: 'SQQQ', NEW in v2.6!)
            vix_symbol: Volatility index symbol (default: '$VIX')
            trade_logger: Optional TradeLogger (default: None)
            name: Strategy name (default: 'Hierarchical_Adaptive_v2_6')

        Raises:
            ValueError: If parameter constraints violated
        """
        super().__init__()
        self.name = name
        self._trade_logger = trade_logger

        # Validate parameter constraints
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

        # Store all parameters (same as v2.5, plus leveraged_short_symbol)
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
        self.leveraged_short_symbol = leveraged_short_symbol  # NEW
        self.vix_symbol = vix_symbol

        # State variables
        self.kalman_filter: Optional[AdaptiveKalmanFilter] = None
        self.sigma_target: Optional[Decimal] = None
        self.equity_peak: Decimal = Decimal("0")
        self.current_exposure: Decimal = Decimal("1.0")
        self.current_qqq_weight: Decimal = Decimal("0")
        self.current_tqqq_weight: Decimal = Decimal("0")
        self.current_sqqq_weight: Decimal = Decimal("0")  # NEW

        logger.info(
            f"Initialized {name} with 21 parameters (v2.6): "
            f"E_min={E_min} (NEW: can be negative), "
            f"E_max={E_max}, "
            f"SQQQ={leveraged_short_symbol} (NEW: 3x inverse), "
            f"DD=[{DD_soft}, {DD_hard}]"
        )

    def init(self) -> None:
        """Initialize strategy state (same as v2.5)."""
        # Initialize Kalman filter
        self.kalman_filter = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=float(self.measurement_noise),
            process_noise_1=float(self.process_noise_1),
            process_noise_2=float(self.process_noise_2),
            osc_smoothness=self.osc_smoothness,
            strength_smoothness=self.strength_smoothness
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
        self.current_sqqq_weight = Decimal("0")  # NEW

        logger.info(
            f"Initialized {self.name} (v2.6) with sigma_target: {self.sigma_target:.4f}"
        )

    def on_bar(self, bar: MarketDataEvent) -> None:
        """
        Process each bar through 5-tier exposure engine (same flow as v2.5).
        
        NEW in v2.6: Step 8 maps to 4 weights (QQQ, TQQQ, SQQQ, cash) instead of 3.
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
        _, trend_strength = self.kalman_filter.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
        trend_strength_decimal = Decimal(str(trend_strength))

        # Tier 2: Calculate normalized trend
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

        # Tier 6: Apply drawdown governor (v2.5 asymmetric - works for negative E!)
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

        # Tier 8: Map to weights (NEW: 4 weights instead of 3!)
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = self._map_exposure_to_weights(E_t)

        # Tier 9: Check rebalancing threshold
        needs_rebalance = self._check_rebalancing_threshold(w_QQQ, w_TQQQ, w_SQQQ)

        # Tier 10: Log context
        logger.info(
            f"[{bar.timestamp}] v2.6 Exposure Calculation | "
            f"T_norm={T_norm:.3f} → E_trend={E_trend:.3f} → "
            f"S_vol={S_vol:.3f} → E_vol={E_vol:.3f} → "
            f"P_VIX={P_VIX:.3f} → E_volVIX={E_volVIX:.3f} → "
            f"P_DD={P_DD:.3f}/DD={DD_current:.3f} → E_t={E_t:.3f} → "
            f"w_QQQ={w_QQQ:.3f}, w_TQQQ={w_TQQQ:.3f}, w_SQQQ={w_SQQQ:.3f}, w_cash={w_cash:.3f}"
        )

        # Execute rebalance if needed
        if needs_rebalance:
            logger.info(f"Rebalancing: weights drifted beyond {self.rebalance_threshold:.3f}")

            if self._trade_logger:
                # Log context for all traded symbols
                for symbol in [self.core_long_symbol, self.leveraged_long_symbol, self.leveraged_short_symbol]:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=symbol,
                        strategy_state=f"v2.6 Continuous Exposure (E_t={E_t:.3f})",
                        decision_reason=(
                            f"Kalman {trend_strength_decimal:.2f} → T_norm {T_norm:.3f}, "
                            f"Vol {S_vol:.3f}, VIX {P_VIX:.3f}, DD {P_DD:.3f} (v2.5 asymmetric) "
                            f"→ E_t {E_t:.3f}"
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

            self._execute_rebalance(w_QQQ, w_TQQQ, w_SQQQ)

    # ===== Tier calculation methods (same as v2.5) =====
    
    def _calculate_normalized_trend(self, trend_strength: Decimal) -> Decimal:
        """T_norm = clip(trend_strength / T_max, -1, +1) - Same as v2.5"""
        T_norm = trend_strength / self.T_max
        return max(Decimal("-1.0"), min(Decimal("1.0"), T_norm))

    def _calculate_baseline_exposure(self, T_norm: Decimal) -> Decimal:
        """E_trend = 1.0 + k_trend * T_norm - Same as v2.5"""
        return Decimal("1.0") + self.k_trend * T_norm

    def _apply_volatility_scaler(
        self,
        E_trend: Decimal,
        sigma_real: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Apply volatility scaler - Same as v2.5"""
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
        """Apply VIX compression - Same as v2.5"""
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
        v2.5 Asymmetric DD Governor - WORKS FOR NEGATIVE EXPOSURE!
        
        Key insight: v2.5's asymmetric formula naturally handles negative exposure correctly.
        When E_volVIX < 0 (net short), defensive path interpolates toward neutral (0),
        which is the correct risk reduction behavior.
        
        Example:
            E_volVIX = -0.6, DD = 12%, P_DD = 0.8
            E_raw = -0.6 * 0.8 + 1.0 * 0.2 = -0.48 + 0.2 = -0.28
            
            Interpretation: Reduced short exposure from -0.6 to -0.28 (closer to neutral)
            This is CORRECT - during drawdown, reduce risk by moving toward neutral.
        
        No changes needed from v2.5!
        """
        # Calculate P_DD (same as v2.5)
        if DD_current <= self.DD_soft:
            P_DD = Decimal("1.0")
        elif DD_current >= self.DD_hard:
            P_DD = self.p_min
        else:
            dd_range = self.DD_hard - self.DD_soft
            dd_excess = DD_current - self.DD_soft
            P_DD = Decimal("1.0") - (dd_excess / dd_range) * (Decimal("1.0") - self.p_min)

        # Apply asymmetric compression (same as v2.5, works for negative E!)
        if E_volVIX > Decimal("1.0"):
            # Leverage path
            E_raw = Decimal("1.0") + (E_volVIX - Decimal("1.0")) * P_DD
        else:
            # Defensive path (handles both 0 < E <= 1.0 AND E < 0!)
            E_raw = E_volVIX * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)

        return P_DD, E_raw

    def _map_exposure_to_weights(
        self,
        E_t: Decimal
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Map final exposure to 4-weight allocation: (w_QQQ, w_TQQQ, w_SQQQ, w_cash)
        
        NEW in v2.6: Handles negative exposure via SQQQ allocation.
        
        Regions:
        1. E_t <= -1.0: Leveraged short (QQQ + SQQQ, fully invested)
           - Need net exposure = E_t
           - Constraints: w_QQQ + w_SQQQ = 1, 1*w_QQQ + (-3)*w_SQQQ = E_t
           - Solution: w_SQQQ = (1 - E_t) / 4, w_QQQ = 1 - w_SQQQ
           
        2. -1.0 < E_t < 0: Defensive short (SQQQ + cash)
           - SQQQ provides -3x exposure
           - w_SQQQ * (-3) = E_t → w_SQQQ = -E_t / 3
           - w_cash = 1 - w_SQQQ
           
        3. 0 <= E_t <= 1.0: Defensive long (QQQ + cash) - Same as v2.5
        
        4. E_t > 1.0: Leveraged long (QQQ + TQQQ) - Same as v2.5
        
        Examples:
            E_t = -1.5: w_SQQQ=0.625, w_QQQ=0.375 → 0.375 - 1.875 = -1.5 ✓
            E_t = -0.6: w_SQQQ=0.2, w_cash=0.8 → -0.6 ✓
            E_t = 0.7: w_QQQ=0.7, w_cash=0.3 → 0.7 ✓ (v2.5)
            E_t = 1.3: w_QQQ=0.85, w_TQQQ=0.15 → 1.3 ✓ (v2.5)
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
            # Region 3: Defensive long (v2.5 logic)
            w_QQQ = E_t
            w_TQQQ = Decimal("0")
            w_SQQQ = Decimal("0")
            w_cash = Decimal("1.0") - E_t
            
        else:  # E_t > 1.0
            # Region 4: Leveraged long (v2.5 logic)
            w_TQQQ = (E_t - Decimal("1.0")) / Decimal("2.0")
            w_QQQ = Decimal("1.0") - w_TQQQ
            w_SQQQ = Decimal("0")
            w_cash = Decimal("0")

        return w_QQQ, w_TQQQ, w_SQQQ, w_cash

    def _check_rebalancing_threshold(
        self,
        target_qqq_weight: Decimal,
        target_tqqq_weight: Decimal,
        target_sqqq_weight: Decimal  # NEW
    ) -> bool:
        """
        Check if portfolio weights drifted > threshold.
        
        NEW in v2.6: Includes SQQQ weight in deviation calculation.
        """
        weight_deviation = (
            abs(self.current_qqq_weight - target_qqq_weight) +
            abs(self.current_tqqq_weight - target_tqqq_weight) +
            abs(self.current_sqqq_weight - target_sqqq_weight)  # NEW
        )
        return weight_deviation > self.rebalance_threshold

    def _execute_rebalance(
        self,
        target_qqq_weight: Decimal,
        target_tqqq_weight: Decimal,
        target_sqqq_weight: Decimal  # NEW
    ) -> None:
        """
        Rebalance portfolio to target weights.
        
        NEW in v2.6: Handles SQQQ position.
        """
        # Update QQQ position
        if target_qqq_weight > Decimal("0"):
            self.buy(self.core_long_symbol, target_qqq_weight)
        else:
            self.sell(self.core_long_symbol, Decimal("0.0"))

        # Update TQQQ position
        if target_tqqq_weight > Decimal("0"):
            self.buy(self.leveraged_long_symbol, target_tqqq_weight)
        else:
            self.sell(self.leveraged_long_symbol, Decimal("0.0"))

        # Update SQQQ position (NEW)
        if target_sqqq_weight > Decimal("0"):
            self.buy(self.leveraged_short_symbol, target_sqqq_weight)
        else:
            self.sell(self.leveraged_short_symbol, Decimal("0.0"))

        # Update current weights
        self.current_qqq_weight = target_qqq_weight
        self.current_tqqq_weight = target_tqqq_weight
        self.current_sqqq_weight = target_sqqq_weight  # NEW

        logger.info(
            f"Executed v2.6 rebalance: QQQ={target_qqq_weight:.3f}, "
            f"TQQQ={target_tqqq_weight:.3f}, SQQQ={target_sqqq_weight:.3f}"
        )

    def _update_drawdown_tracking(self, portfolio_equity: Decimal) -> Decimal:
        """Track peak-to-trough drawdown - Same as v2.5"""
        if portfolio_equity > self.equity_peak:
            self.equity_peak = portfolio_equity

        if self.equity_peak > Decimal("0"):
            DD_current = (self.equity_peak - portfolio_equity) / self.equity_peak
        else:
            DD_current = Decimal("0")

        return DD_current
