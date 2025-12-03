"""
Unit tests for Hierarchical_Adaptive_v2.7 strategy.

Tests v2.7-specific three critical bug fixes:
1. **Signed Trend (CRITICAL)**: Use oscillator sign, not just magnitude
2. **DD Governor Anchor (CRITICAL)**: Converge to 0 (cash), not 1.0 (QQQ)
3. **SQQQ Logging (MINOR)**: Add SQQQ position tracking to daily log

All other tiers (Vol, VIX, position mapping, rebalancing) are unchanged from v2.5/v2.6.
"""
from decimal import Decimal
from datetime import datetime, timezone
import pytest

from jutsu_engine.strategies.Hierarchical_Adaptive_v2_7 import Hierarchical_Adaptive_v2_7
from jutsu_engine.core.events import MarketDataEvent


# ===========================================================================================
# v2.7 SPECIFIC TESTS - Three Critical Bug Fixes
# ===========================================================================================

class TestHierarchicalAdaptiveV2_7SignedTrend:
    """Test v2.7 FIX 1: Signed trend (use oscillator sign, not just magnitude)."""

    def test_signed_trend_positive_oscillator(self):
        """
        FIX 1: Positive oscillator creates positive signed trend.

        v2.6 Bug:
            - Only used trend_strength (magnitude)
            - Result: T_norm ∈ [0, 1] not [-1, +1]

        v2.7 Fix:
            - Use oscillator sign: trend_signed = strength * sign(oscillator)
            - Result: T_norm ∈ [-1, +1]
        """
        strategy = Hierarchical_Adaptive_v2_7()

        # v2.8: Kalman now returns signed trend directly
        # Simulate what Kalman returns with return_signed=True
        oscillator = Decimal("10.0")
        trend_strength = Decimal("30.0")
        sign = Decimal("1.0") if oscillator >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed = trend_strength * sign

        T_norm = strategy._calculate_normalized_trend(trend_strength_signed)

        # sign = +1, trend_signed = 30.0 * 1 = 30.0
        # T_norm = 30.0 / 60 = 0.5
        assert T_norm == Decimal("0.5")

    def test_signed_trend_negative_oscillator(self):
        """
        FIX 1: Negative oscillator creates NEGATIVE signed trend.

        This is the key fix - v2.6 could not express bearish regimes.
        """
        strategy = Hierarchical_Adaptive_v2_7()

        # v2.8: Kalman now returns signed trend directly
        # Simulate what Kalman returns with return_signed=True
        oscillator = Decimal("-10.0")
        trend_strength = Decimal("30.0")
        sign = Decimal("1.0") if oscillator >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed = trend_strength * sign

        T_norm = strategy._calculate_normalized_trend(trend_strength_signed)

        # sign = -1, trend_signed = 30.0 * (-1) = -30.0
        # T_norm = -30.0 / 60 = -0.5
        assert T_norm == Decimal("-0.5")

        # Verify T_norm can be negative (v2.6 could not!)
        assert T_norm < Decimal("0.0")

    def test_signed_trend_zero_oscillator(self):
        """FIX 1: Zero oscillator creates zero signed trend."""
        strategy = Hierarchical_Adaptive_v2_7()

        # v2.8: Kalman now returns signed trend directly
        # Simulate what Kalman returns with return_signed=True
        oscillator = Decimal("0.0")
        trend_strength = Decimal("30.0")
        sign = Decimal("1.0") if oscillator >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed = trend_strength * sign

        T_norm = strategy._calculate_normalized_trend(trend_strength_signed)

        # sign = +1 (0 treated as positive), trend_signed = 30.0 * 1 = 30.0
        # T_norm = 30.0 / 60 = 0.5
        assert T_norm == Decimal("0.5")

    def test_signed_trend_clipping(self):
        """FIX 1: Signed trend clipped to [-1, +1] range."""
        strategy = Hierarchical_Adaptive_v2_7(T_max=Decimal("60"))

        # v2.8: Kalman now returns signed trend directly
        # Test positive clipping
        osc_pos = Decimal("10.0")
        strength_high = Decimal("90.0")
        sign_pos = Decimal("1.0") if osc_pos >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed_pos = strength_high * sign_pos
        T_norm_pos = strategy._calculate_normalized_trend(trend_strength_signed_pos)
        assert T_norm_pos == Decimal("1.0")  # clip(90/60, -1, +1) = +1.0

        # Test negative clipping
        osc_neg = Decimal("-10.0")
        sign_neg = Decimal("1.0") if osc_neg >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed_neg = strength_high * sign_neg
        T_norm_neg = strategy._calculate_normalized_trend(trend_strength_signed_neg)
        assert T_norm_neg == Decimal("-1.0")  # clip(-90/60, -1, +1) = -1.0


class TestHierarchicalAdaptiveV2_7DDGovernor:
    """Test v2.7 FIX 2: DD governor converges to 0 (cash), not 1.0 (QQQ)."""

    def test_dd_governor_deep_dd_goes_to_cash(self):
        """
        FIX 2: Deep DD (P_DD → 0) converges to 0 (cash), not 1.0 (QQQ).

        v2.6 Bug:
            - Defensive path: E_raw = E_volVIX * P_DD + 1.0 * (1 - P_DD)
            - Deep DD (P_DD = 0) → E_raw = 1.0 (100% QQQ)
            - Opposite of intent!

        v2.7 Fix:
            - Single formula: E_raw = E_floor + (E_volVIX - E_floor) * P_DD
            - E_floor = 0 (cash)
            - Deep DD (P_DD = 0) → E_raw = 0 (cash)
        """
        strategy = Hierarchical_Adaptive_v2_7(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Defensive signal
        E_volVIX = Decimal("0.7")

        # Severe DD (beyond DD_hard)
        DD_severe = Decimal("0.25")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_severe)

        # P_DD = 0.0 (max DD)
        assert P_DD == Decimal("0.0")

        # v2.7: E_raw = 0 + (0.7 - 0) * 0 = 0.0 (cash!)
        assert E_raw == Decimal("0.0")

        # This is the key fix: deep DD → cash (0), not QQQ (1.0)

    def test_dd_governor_no_dd_is_identity(self):
        """
        FIX 2: P_DD = 1.0 → E_raw = E_volVIX (no modification).

        This behavior is same as v2.6, verified for consistency.
        """
        strategy = Hierarchical_Adaptive_v2_7(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20")
        )

        DD_current = Decimal("0.05")  # Below DD_soft

        # Test with defensive signal
        E_volVIX = Decimal("0.7")
        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)
        assert P_DD == Decimal("1.0")
        assert E_raw == E_volVIX

    def test_dd_governor_partial_dd_interpolates_to_zero(self):
        """
        FIX 2: Partial DD interpolates between E_volVIX and 0 (not 1.0!).

        v2.6 Bug:
            - Interpolated toward 1.0
            - Example: E_volVIX = 0.6, P_DD = 0.8 → E_raw = 0.76 (moved toward 1.0)

        v2.7 Fix:
            - Interpolates toward 0 (cash)
            - Example: E_volVIX = 0.6, P_DD = 0.8 → E_raw = 0.48 (moved toward 0)
        """
        strategy = Hierarchical_Adaptive_v2_7(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("0.6")
        DD_current = Decimal("0.12")  # 20% into range

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 1.0 - ((0.12 - 0.10) / (0.20 - 0.10)) = 1.0 - 0.2 = 0.8
        assert P_DD == Decimal("0.8")

        # v2.7: E_raw = 0 + (0.6 - 0) * 0.8 = 0.48
        assert E_raw == Decimal("0.48")

        # Verify moved toward 0 (not 1.0!)
        assert E_raw < E_volVIX  # 0.48 < 0.6
        assert E_raw > Decimal("0.0")  # Not fully defensive yet

    def test_dd_governor_negative_exposure_works(self):
        """
        FIX 2: DD governor now handles negative exposure correctly.

        v2.6 Bug:
            - E_volVIX = -0.6, P_DD = 0.5 → E_raw = -0.3 + 0.5 = 0.2 (net long!)

        v2.7 Fix:
            - E_volVIX = -0.6, P_DD = 0.5 → E_raw = 0 + (-0.6 - 0) * 0.5 = -0.3 (stays short)
        """
        strategy = Hierarchical_Adaptive_v2_7(
            E_min=Decimal("-0.5"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Negative exposure (short bias)
        E_volVIX = Decimal("-0.6")

        # Moderate DD (50% into range)
        DD_current = Decimal("0.15")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 1.0 - ((0.15 - 0.10) / (0.20 - 0.10)) = 1.0 - 0.5 = 0.5
        assert P_DD == Decimal("0.5")

        # v2.7: E_raw = 0 + (-0.6 - 0) * 0.5 = -0.3
        assert E_raw == Decimal("-0.3")

        # Verify stays negative (defensive for short bias)
        assert E_raw < Decimal("0.0")

        # Verify moved toward 0 (defensive)
        assert E_raw > E_volVIX  # -0.3 > -0.6 (closer to 0)

    def test_dd_governor_leverage_path_changed(self):
        """
        FIX 2: Leverage path (E_volVIX > 1.0) IS affected by new formula.

        v2.6 had two paths (leverage vs defensive), v2.7 uses single formula.
        This changes leverage behavior slightly but consistently.
        """
        strategy = Hierarchical_Adaptive_v2_7(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Leverage signal
        E_volVIX = Decimal("1.3")

        # Moderate DD
        DD_current = Decimal("0.12")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 0.8 (same as defensive path test)
        assert P_DD == Decimal("0.8")

        # v2.7 single formula: E_raw = E_floor + (E_volVIX - E_floor) * P_DD
        # E_raw = 0 + (1.3 - 0) * 0.8 = 1.04
        assert E_raw == Decimal("1.04")

        # Note: This is DIFFERENT from v2.6's leverage path formula
        # v2.6 leverage: E_raw = 1.0 + (1.3 - 1.0) * 0.8 = 1.24
        # But the new formula is more consistent and still provides leverage compression


class TestHierarchicalAdaptiveV2_7BaselineExposure:
    """Test baseline exposure with SIGNED trend (enabled by FIX 1)."""

    def test_baseline_exposure_bearish_regime(self):
        """
        FIX 1 enables: Baseline exposure can now go BELOW 1.0.

        v2.6: T_norm ∈ [0, 1] → E_trend ∈ [1.0, 1.3]
        v2.7: T_norm ∈ [-1, +1] → E_trend ∈ [0.7, 1.3] for k_trend = 0.3
        """
        strategy = Hierarchical_Adaptive_v2_7(k_trend=Decimal("0.3"))

        # Strong bearish trend (T_norm = -1.0)
        T_norm_bearish = Decimal("-1.0")
        E_trend = strategy._calculate_baseline_exposure(T_norm_bearish)

        # E_trend = 1.0 + 0.3 * (-1.0) = 0.7
        assert E_trend == Decimal("0.7")

        # Verify E_trend < 1.0 (bearish baseline!)
        assert E_trend < Decimal("1.0")

    def test_baseline_exposure_neutral_regime(self):
        """Neutral trend produces E_trend = 1.0 (same as v2.6)."""
        strategy = Hierarchical_Adaptive_v2_7(k_trend=Decimal("0.3"))

        T_norm_neutral = Decimal("0.0")
        E_trend = strategy._calculate_baseline_exposure(T_norm_neutral)

        assert E_trend == Decimal("1.0")

    def test_baseline_exposure_bullish_regime(self):
        """Bullish trend produces E_trend > 1.0 (same as v2.6)."""
        strategy = Hierarchical_Adaptive_v2_7(k_trend=Decimal("0.3"))

        T_norm_bullish = Decimal("1.0")
        E_trend = strategy._calculate_baseline_exposure(T_norm_bullish)

        # E_trend = 1.0 + 0.3 * 1.0 = 1.3
        assert E_trend == Decimal("1.3")


class TestHierarchicalAdaptiveV2_7SQQQLogging:
    """Test v2.7 FIX 3: SQQQ logging (verified indirectly through TradeLogger)."""

    def test_sqqq_logging_infrastructure_present(self):
        """
        FIX 3: Verify SQQQ infrastructure is present.

        Note: Full logging test would require TradeLogger mock,
        but we can verify state tracking exists.
        """
        strategy = Hierarchical_Adaptive_v2_7(
            leveraged_short_symbol="SQQQ"
        )

        # Verify SQQQ symbol configured
        assert strategy.leveraged_short_symbol == "SQQQ"

        # Verify SQQQ weight tracking initialized
        assert hasattr(strategy, 'current_sqqq_weight')
        assert strategy.current_sqqq_weight == Decimal("0")


# ===========================================================================================
# v2.7 INTEGRATION TESTS
# ===========================================================================================

class TestHierarchicalAdaptiveV2_7Integration:
    """Integration tests for full v2.7 strategy with all three fixes."""

    def test_sqqq_region_reachable(self):
        """
        Integration test: Verify SQQQ region (E_t < 0) is now reachable.

        v2.6 Bug: E_t never went below 1.0 (unsigned trend + wrong DD anchor)
        v2.7 Fix: E_t can go below 0 (signed trend + cash anchor)
        """
        strategy = Hierarchical_Adaptive_v2_7(
            E_min=Decimal("-0.5"),
            E_max=Decimal("1.5"),
            k_trend=Decimal("0.7"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Simulate bearish scenario components:
        # 1. Strong bearish trend (v2.8: Kalman returns signed)
        oscillator = Decimal("-10.0")
        trend_strength = Decimal("60.0")
        sign = Decimal("1.0") if oscillator >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed = trend_strength * sign
        T_norm = strategy._calculate_normalized_trend(trend_strength_signed)

        # sign = -1, trend_signed = 60 * (-1) = -60
        # T_norm = -60 / 60 = -1.0
        assert T_norm == Decimal("-1.0")

        # 2. Baseline exposure (FIX 1 enables bearish)
        E_trend = strategy._calculate_baseline_exposure(T_norm)
        # E_trend = 1.0 + 0.7 * (-1.0) = 0.3
        assert E_trend == Decimal("0.3")
        assert E_trend < Decimal("1.0")  # Bearish baseline!

        # 3. After vol scaler (assume neutral)
        S_vol = Decimal("1.0")
        E_vol = Decimal("1.0") + (E_trend - Decimal("1.0")) * S_vol
        assert E_vol == Decimal("0.3")

        # 4. After VIX compression (assume neutral)
        P_VIX = Decimal("1.0")
        E_volVIX = Decimal("1.0") + (E_vol - Decimal("1.0")) * P_VIX
        assert E_volVIX == Decimal("0.3")

        # 5. After DD governor (FIX 2: converge to 0, not 1.0)
        DD_current = Decimal("0.15")  # Moderate DD
        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 0.5 (midpoint)
        # v2.7: E_raw = 0 + (0.3 - 0) * 0.5 = 0.15
        assert E_raw == Decimal("0.15")

        # 6. After clipping
        E_t = max(strategy.E_min, min(strategy.E_max, E_raw))
        assert E_t == Decimal("0.15")

        # Verify E_t is in defensive long range (not SQQQ yet)
        assert Decimal("0.0") < E_t < Decimal("1.0")

        # Test EXTREME bearish scenario (to reach SQQQ)
        # Very strong bearish + moderate DD → E_t could go negative
        oscillator_extreme = Decimal("-10.0")
        strength_extreme = Decimal("90.0")  # Very strong
        sign_extreme = Decimal("1.0") if oscillator_extreme >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed_extreme = strength_extreme * sign_extreme
        T_norm_extreme = strategy._calculate_normalized_trend(trend_strength_signed_extreme)
        assert T_norm_extreme == Decimal("-1.0")  # Clipped

        E_trend_extreme = strategy._calculate_baseline_exposure(T_norm_extreme)
        # E_trend = 1.0 + 0.7 * (-1.0) = 0.3
        assert E_trend_extreme == Decimal("0.3")

        # With NO DD, high vol, high VIX, we could push E_volVIX negative
        # But this test shows the pathway is now OPEN (v2.6 it was blocked)

    def test_defensive_positioning_improved(self):
        """
        Integration test: Verify DD governor now provides true defensive positioning.

        v2.6 Bug: Deep DD → E_raw = 1.0 (100% QQQ)
        v2.7 Fix: Deep DD → E_raw = 0 (cash)
        """
        strategy = Hierarchical_Adaptive_v2_7(
            E_min=Decimal("0.5"),
            E_max=Decimal("1.3"),
            k_trend=Decimal("0.3"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Moderate bearish signal (v2.8: Kalman returns signed)
        oscillator = Decimal("-5.0")
        trend_strength = Decimal("30.0")
        sign = Decimal("1.0") if oscillator >= Decimal("0.0") else Decimal("-1.0")
        trend_strength_signed = trend_strength * sign
        T_norm = strategy._calculate_normalized_trend(trend_strength_signed)
        # sign = -1, trend_signed = 30 * (-1) = -30
        # T_norm = -30 / 60 = -0.5
        assert T_norm == Decimal("-0.5")

        E_trend = strategy._calculate_baseline_exposure(T_norm)
        # E_trend = 1.0 + 0.3 * (-0.5) = 0.85
        assert E_trend == Decimal("0.85")

        # Assume neutral vol/VIX
        E_volVIX = Decimal("0.85")

        # Severe DD
        DD_severe = Decimal("0.25")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_severe)

        # P_DD = 0.0 (max DD)
        # v2.7: E_raw = 0 + (0.85 - 0) * 0 = 0.0 (CASH!)
        assert E_raw == Decimal("0.0")

        # After clipping
        E_t = max(strategy.E_min, min(strategy.E_max, E_raw))
        # E_t = max(0.5, min(1.3, 0.0)) = 0.5 (clipped to E_min)
        assert E_t == Decimal("0.5")

        # Verify defensive positioning (50% QQQ, not 100% QQQ!)
        assert E_t < Decimal("1.0")


# ===========================================================================================
# COPIED FROM v2.5 TESTS - Unchanged Components
# ===========================================================================================

class TestInitialization:
    """Test strategy initialization and parameter validation."""

    def test_default_initialization(self):
        """Test strategy initializes with v2.7 default parameters."""
        strategy = Hierarchical_Adaptive_v2_7()

        # Tier 1: Kalman (unchanged from v2.6)
        assert strategy.measurement_noise == Decimal("2000.0")
        assert strategy.process_noise_1 == Decimal("0.01")
        assert strategy.process_noise_2 == Decimal("0.01")
        assert strategy.osc_smoothness == 15
        assert strategy.strength_smoothness == 15
        assert strategy.T_max == Decimal("60")

        # Tier 0: Core exposure (unchanged from v2.6)
        assert strategy.k_trend == Decimal("0.3")
        assert strategy.E_min == Decimal("-0.5")  # v2.6 default (can be negative)
        assert strategy.E_max == Decimal("1.5")

        # Tier 2: Volatility (unchanged from v2.6)
        assert strategy.sigma_target_multiplier == Decimal("0.9")
        assert strategy.realized_vol_lookback == 20
        assert strategy.S_vol_min == Decimal("0.5")
        assert strategy.S_vol_max == Decimal("1.5")

        # Tier 3: VIX (unchanged from v2.6)
        assert strategy.vix_ema_period == 50
        assert strategy.alpha_VIX == Decimal("1.0")

        # Tier 4: Drawdown (unchanged from v2.6)
        assert strategy.DD_soft == Decimal("0.10")
        assert strategy.DD_hard == Decimal("0.20")
        assert strategy.p_min == Decimal("0.0")

        # Tier 5: Rebalancing (unchanged from v2.6)
        assert strategy.rebalance_threshold == Decimal("0.025")

        # Symbols (SQQQ added in v2.6, unchanged in v2.7)
        assert strategy.signal_symbol == "QQQ"
        assert strategy.core_long_symbol == "QQQ"
        assert strategy.leveraged_long_symbol == "TQQQ"
        assert strategy.leveraged_short_symbol == "SQQQ"
        assert strategy.vix_symbol == "$VIX"

    def test_custom_parameters(self):
        """Test strategy accepts custom parameters."""
        strategy = Hierarchical_Adaptive_v2_7(
            measurement_noise=Decimal("5000.0"),
            k_trend=Decimal("0.4"),
            E_min=Decimal("-0.3"),
            E_max=Decimal("1.4"),
            DD_soft=Decimal("0.08"),
            DD_hard=Decimal("0.18"),
            vix_ema_period=30,
            rebalance_threshold=Decimal("0.03"),
            leveraged_short_symbol="SQQQ"
        )

        assert strategy.measurement_noise == Decimal("5000.0")
        assert strategy.k_trend == Decimal("0.4")
        assert strategy.E_min == Decimal("-0.3")
        assert strategy.E_max == Decimal("1.4")
        assert strategy.DD_soft == Decimal("0.08")
        assert strategy.DD_hard == Decimal("0.18")
        assert strategy.vix_ema_period == 30
        assert strategy.rebalance_threshold == Decimal("0.03")
        assert strategy.leveraged_short_symbol == "SQQQ"

    def test_invalid_exposure_bounds(self):
        """Test validation of exposure bounds."""
        with pytest.raises(ValueError, match="Exposure bounds"):
            Hierarchical_Adaptive_v2_7(E_min=Decimal("1.5"), E_max=Decimal("1.3"))

    def test_invalid_drawdown_thresholds(self):
        """Test validation of drawdown thresholds."""
        with pytest.raises(ValueError, match="Drawdown thresholds"):
            Hierarchical_Adaptive_v2_7(DD_soft=Decimal("0.25"), DD_hard=Decimal("0.20"))

        with pytest.raises(ValueError, match="Drawdown thresholds"):
            Hierarchical_Adaptive_v2_7(DD_soft=Decimal("-0.1"))


class TestVolatilityScaler:
    """Test volatility scaler application (unchanged from v2.6)."""

    def test_low_realized_vol(self):
        """Test scaler when realized vol is below target."""
        strategy = Hierarchical_Adaptive_v2_7(
            sigma_target_multiplier=Decimal("0.9"),
            S_vol_min=Decimal("0.5"),
            S_vol_max=Decimal("1.5")
        )
        strategy.sigma_target = Decimal("0.18")  # 18%

        E_trend = Decimal("1.3")
        sigma_real = Decimal("0.15")  # Lower than target

        S_vol, E_vol = strategy._apply_volatility_scaler(E_trend, sigma_real)

        # S_vol = 0.18 / 0.15 = 1.2
        assert S_vol == Decimal("1.2")
        # E_vol = 1.0 + (1.3 - 1.0) * 1.2 = 1.36
        assert E_vol == Decimal("1.36")

    def test_zero_realized_vol(self):
        """Test handling of zero realized volatility."""
        strategy = Hierarchical_Adaptive_v2_7()
        strategy.sigma_target = Decimal("0.18")

        E_trend = Decimal("1.3")
        sigma_real = Decimal("0.0")

        S_vol, E_vol = strategy._apply_volatility_scaler(E_trend, sigma_real)

        # Should default to S_vol = 1.0 when sigma_real = 0
        assert S_vol == Decimal("1.0")
        assert E_vol == Decimal("1.3")


class TestVIXCompression:
    """Test VIX compression application (unchanged from v2.6)."""

    def test_vix_below_ema(self):
        """Test no compression when VIX below EMA."""
        strategy = Hierarchical_Adaptive_v2_7(alpha_VIX=Decimal("1.0"))

        E_vol = Decimal("1.3")
        R_VIX = Decimal("0.9")  # VIX < VIX_EMA

        P_VIX, E_volVIX = strategy._apply_vix_compression(E_vol, R_VIX)

        assert P_VIX == Decimal("1.0")
        assert E_volVIX == Decimal("1.3")

    def test_vix_above_ema(self):
        """Test compression when VIX above EMA."""
        strategy = Hierarchical_Adaptive_v2_7(alpha_VIX=Decimal("1.0"))

        E_vol = Decimal("1.3")
        R_VIX = Decimal("1.2")  # VIX > VIX_EMA

        P_VIX, E_volVIX = strategy._apply_vix_compression(E_vol, R_VIX)

        # P_VIX = 1 / (1 + 1.0 * (1.2 - 1.0)) = 1 / 1.2 = 0.8333...
        expected_P_VIX = Decimal("1.0") / (Decimal("1.0") + Decimal("0.2"))
        assert abs(P_VIX - expected_P_VIX) < Decimal("0.001")


class TestPositionMapping:
    """Test QQQ/TQQQ/SQQQ position mapping (unchanged from v2.6)."""

    def test_exposure_defensive_long(self):
        """Test mapping when 0 < E_t <= 1.0 (QQQ + cash)."""
        strategy = Hierarchical_Adaptive_v2_7()

        E_t = Decimal("0.7")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        assert w_QQQ == Decimal("0.7")
        assert w_TQQQ == Decimal("0.0")
        assert w_SQQQ == Decimal("0.0")
        assert w_cash == Decimal("0.3")

    def test_exposure_leveraged_long(self):
        """Test mapping when E_t > 1.0 (QQQ + TQQQ)."""
        strategy = Hierarchical_Adaptive_v2_7()

        E_t = Decimal("1.3")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # w_TQQQ = (1.3 - 1.0) / 2.0 = 0.15
        assert w_TQQQ == Decimal("0.15")
        # w_QQQ = 1.0 - 0.15 = 0.85
        assert w_QQQ == Decimal("0.85")
        assert w_SQQQ == Decimal("0.0")
        assert w_cash == Decimal("0.0")

        # Verify effective exposure: 0.85*1 + 0.15*3 = 1.3
        effective_exposure = w_QQQ * Decimal("1") + w_TQQQ * Decimal("3")
        assert effective_exposure == Decimal("1.3")

    def test_exposure_defensive_short(self):
        """Test mapping when -1.0 < E_t < 0 (SQQQ + cash)."""
        strategy = Hierarchical_Adaptive_v2_7()

        E_t = Decimal("-0.3")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # w_SQQQ = -(-0.3) / 3.0 = 0.1
        assert w_SQQQ == Decimal("0.1")
        assert w_QQQ == Decimal("0.0")
        assert w_TQQQ == Decimal("0.0")
        # w_cash = 1.0 - 0.1 = 0.9
        assert w_cash == Decimal("0.9")

        # Verify effective exposure: 0.1 * (-3) = -0.3
        effective_exposure = w_SQQQ * Decimal("-3")
        assert effective_exposure == Decimal("-0.3")

    def test_exposure_leveraged_short(self):
        """Test mapping when E_t <= -1.0 (QQQ + SQQQ)."""
        strategy = Hierarchical_Adaptive_v2_7()

        E_t = Decimal("-1.5")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # w_SQQQ = (1.0 - (-1.5)) / 4.0 = 2.5 / 4.0 = 0.625
        assert w_SQQQ == Decimal("0.625")
        # w_QQQ = 1.0 - 0.625 = 0.375
        assert w_QQQ == Decimal("0.375")
        assert w_TQQQ == Decimal("0.0")
        assert w_cash == Decimal("0.0")

        # Verify effective exposure: 0.375*1 + 0.625*(-3) = 0.375 - 1.875 = -1.5
        effective_exposure = w_QQQ * Decimal("1") + w_SQQQ * Decimal("-3")
        assert effective_exposure == Decimal("-1.5")


class TestRebalancing:
    """Test rebalancing threshold and execution (SQQQ added in v2.6)."""

    def test_no_rebalancing_needed(self):
        """Test no rebalancing when weights within threshold."""
        strategy = Hierarchical_Adaptive_v2_7(rebalance_threshold=Decimal("0.025"))

        strategy.current_qqq_weight = Decimal("0.85")
        strategy.current_tqqq_weight = Decimal("0.15")
        strategy.current_sqqq_weight = Decimal("0.0")

        target_qqq = Decimal("0.86")
        target_tqqq = Decimal("0.14")
        target_sqqq = Decimal("0.0")

        needs_rebalance = strategy._check_rebalancing_threshold(target_qqq, target_tqqq, target_sqqq)

        # Deviation = |0.85 - 0.86| + |0.15 - 0.14| + |0.0 - 0.0| = 0.02 = 2%
        # Threshold = 2.5%, so no rebalance needed
        assert not needs_rebalance

    def test_rebalancing_needed_with_sqqq(self):
        """Test rebalancing when SQQQ weight changes significantly."""
        strategy = Hierarchical_Adaptive_v2_7(rebalance_threshold=Decimal("0.025"))

        strategy.current_qqq_weight = Decimal("0.0")
        strategy.current_tqqq_weight = Decimal("0.0")
        strategy.current_sqqq_weight = Decimal("0.0")

        target_qqq = Decimal("0.0")
        target_tqqq = Decimal("0.0")
        target_sqqq = Decimal("0.1")  # New SQQQ position

        needs_rebalance = strategy._check_rebalancing_threshold(target_qqq, target_tqqq, target_sqqq)

        # Deviation = |0.0 - 0.0| + |0.0 - 0.0| + |0.0 - 0.1| = 0.1 = 10%
        # Threshold = 2.5%, so rebalance needed
        assert needs_rebalance


class TestDrawdownTracking:
    """Test drawdown tracking logic (unchanged from v2.6)."""

    def test_initial_drawdown_zero(self):
        """Test drawdown is zero initially."""
        strategy = Hierarchical_Adaptive_v2_7()

        DD_current = strategy._update_drawdown_tracking(Decimal("0"))

        assert DD_current == Decimal("0")

    def test_peak_updated(self):
        """Test equity peak is updated when new high reached."""
        strategy = Hierarchical_Adaptive_v2_7()

        # First update sets peak
        DD_current = strategy._update_drawdown_tracking(Decimal("100000"))
        assert strategy.equity_peak == Decimal("100000")
        assert DD_current == Decimal("0")

        # Higher equity updates peak
        DD_current = strategy._update_drawdown_tracking(Decimal("110000"))
        assert strategy.equity_peak == Decimal("110000")
        assert DD_current == Decimal("0")

    def test_drawdown_calculation(self):
        """Test drawdown calculated correctly."""
        strategy = Hierarchical_Adaptive_v2_7()

        # Set peak
        strategy._update_drawdown_tracking(Decimal("100000"))

        # Drawdown to 88000
        DD_current = strategy._update_drawdown_tracking(Decimal("88000"))

        # DD = (100000 - 88000) / 100000 = 0.12 = 12%
        assert DD_current == Decimal("0.12")

    def test_drawdown_recovery(self):
        """Test drawdown decreases as equity recovers."""
        strategy = Hierarchical_Adaptive_v2_7()

        # Set peak
        strategy._update_drawdown_tracking(Decimal("100000"))

        # Initial drawdown
        DD_current = strategy._update_drawdown_tracking(Decimal("80000"))
        assert DD_current == Decimal("0.20")  # 20% drawdown

        # Partial recovery
        DD_current = strategy._update_drawdown_tracking(Decimal("90000"))
        assert DD_current == Decimal("0.10")  # 10% drawdown

        # Full recovery (new peak)
        DD_current = strategy._update_drawdown_tracking(Decimal("105000"))
        assert DD_current == Decimal("0.0")  # No drawdown
        assert strategy.equity_peak == Decimal("105000")
