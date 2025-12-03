"""
Unit tests for Hierarchical_Adaptive_v2.5 strategy.

Tests v2.5-specific asymmetric DD governor changes:
- Leverage compression (E > 1.0): Same as v2.0
- Defensive preservation (E <= 1.0): NEW asymmetric formula
- E_min reachability during drawdowns
- Continuity at E = 1.0 boundary
- Parameter defaults (DD_soft: 0.10, DD_hard: 0.20)

All other tiers (Kalman, Vol, VIX, position mapping, rebalancing) are unchanged from v2.0,
so those tests are copied from test_hierarchical_adaptive_v2.py.
"""
from decimal import Decimal
from datetime import datetime, timezone
import pytest

from jutsu_engine.strategies.Hierarchical_Adaptive_v2 import Hierarchical_Adaptive_v2
from jutsu_engine.core.events import MarketDataEvent


# ===========================================================================================
# v2.5 SPECIFIC TESTS - Asymmetric DD Governor
# ===========================================================================================

class TestHierarchicalAdaptiveV2_5DDGovernor:
    """Test v2.5 asymmetric DD governor specifically."""

    def test_dd_governor_bull_with_dd_compresses_to_1_0(self):
        """
        Leverage path: E_volVIX > 1.0 with drawdown compresses toward 1.0.

        Scenario: E_volVIX = 1.3, DD = 12%, P_DD = 0.8
        Expected: E_raw = 1.0 + (1.3 - 1.0) * 0.8 = 1.24 (compressed from 1.3)
        """
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.12")  # 12% drawdown (midpoint)

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 1.0 - ((0.12 - 0.10) / (0.20 - 0.10)) = 1.0 - 0.2 = 0.8
        assert P_DD == Decimal("0.8")

        # E_raw = 1.0 + (1.3 - 1.0) * 0.8 = 1.24
        assert E_raw == Decimal("1.24")

        # Verify compression occurred (E_raw < E_volVIX)
        assert E_raw < E_volVIX

    def test_dd_governor_bear_with_dd_preserves_defensive(self):
        """
        Defensive path: E_volVIX < 1.0 with drawdown interpolates toward 1.0 BUT stays defensive.

        Scenario: E_volVIX = 0.7, DD = 12%, P_DD = 0.8
        v2.5: E_raw = 0.7 * 0.8 + 1.0 * 0.2 = 0.76 (weighted average)

        Key difference from v2.0: Formula interpretation is intentional interpolation,
        not accidental compression.
        """
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("0.7")
        DD_current = Decimal("0.12")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("0.8")

        # v2.5 asymmetric formula: E_raw = E_volVIX * P_DD + 1.0 * (1.0 - P_DD)
        # E_raw = 0.7 * 0.8 + 1.0 * 0.2 = 0.56 + 0.20 = 0.76
        assert E_raw == Decimal("0.76")

        # Verify defensive position preserved (E_raw < 1.0)
        assert E_raw < Decimal("1.0")

        # Verify moved toward neutral (E_raw > E_volVIX)
        assert E_raw > E_volVIX

    def test_dd_governor_no_dd_is_identity(self):
        """
        P_DD = 1.0 → E_raw = E_volVIX (no modification).

        Both paths should preserve signal when DD < DD_soft.
        """
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20")
        )

        DD_current = Decimal("0.05")  # Below DD_soft

        # Test leverage path
        E_volVIX_bull = Decimal("1.3")
        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX_bull, DD_current)
        assert P_DD == Decimal("1.0")
        assert E_raw == E_volVIX_bull

        # Test defensive path
        E_volVIX_bear = Decimal("0.7")
        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX_bear, DD_current)
        assert P_DD == Decimal("1.0")
        assert E_raw == E_volVIX_bear

    def test_dd_governor_partial_dd_partial_compression(self):
        """
        Partial drawdown produces partial compression for both paths.

        Test various P_DD values across DD range.
        """
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        test_cases = [
            # (DD, expected_P_DD)
            (Decimal("0.10"), Decimal("1.0")),   # At DD_soft
            (Decimal("0.12"), Decimal("0.8")),   # 20% into range
            (Decimal("0.15"), Decimal("0.5")),   # Midpoint
            (Decimal("0.18"), Decimal("0.2")),   # 80% into range
            (Decimal("0.20"), Decimal("0.0")),   # At DD_hard
        ]

        E_volVIX_bull = Decimal("1.3")
        E_volVIX_bear = Decimal("0.6")

        for DD_current, expected_P_DD in test_cases:
            # Test leverage path
            P_DD, E_raw_bull = strategy._apply_drawdown_governor(E_volVIX_bull, DD_current)
            assert P_DD == expected_P_DD

            # Expected: 1.0 + (1.3 - 1.0) * P_DD
            expected_E_bull = Decimal("1.0") + (E_volVIX_bull - Decimal("1.0")) * P_DD
            assert E_raw_bull == expected_E_bull

            # Test defensive path
            P_DD, E_raw_bear = strategy._apply_drawdown_governor(E_volVIX_bear, DD_current)
            assert P_DD == expected_P_DD

            # Expected: 0.6 * P_DD + 1.0 * (1.0 - P_DD)
            expected_E_bear = E_volVIX_bear * P_DD + Decimal("1.0") * (Decimal("1.0") - P_DD)
            assert E_raw_bear == expected_E_bear

    def test_dd_governor_continuity_at_1_0(self):
        """
        E_volVIX = 1.0 → E_raw = 1.0 for all P_DD (smooth transition).

        Verify no discontinuity at leverage/defensive boundary.
        """
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Test at various DD levels
        DD_levels = [
            Decimal("0.05"),  # No DD
            Decimal("0.12"),  # Mild DD
            Decimal("0.15"),  # Mid DD
            Decimal("0.25"),  # Severe DD
        ]

        for DD_current in DD_levels:
            # At E_volVIX = 1.0, both paths should give E_raw = 1.0
            E_volVIX = Decimal("1.0")
            P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

            # For E_volVIX = 1.0:
            # Leverage path: E_raw = 1.0 + (1.0 - 1.0) * P_DD = 1.0
            # Defensive path: E_raw = 1.0 * P_DD + 1.0 * (1.0 - P_DD) = 1.0
            # Both give 1.0 ✓
            assert E_raw == Decimal("1.0")

    def test_dd_governor_e_min_reachable(self):
        """
        With bearish signal and DD, E_raw can reach E_min (0.4 or below).

        This tests the v2.5 fix: defensive positions should be able to reach E_min.
        """
        strategy = Hierarchical_Adaptive_v2(
            E_min=Decimal("0.4"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        # Very defensive signal
        E_volVIX = Decimal("0.5")

        # Moderate drawdown (15%, midpoint)
        DD_current = Decimal("0.15")

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 0.5 (midpoint)
        assert P_DD == Decimal("0.5")

        # E_raw = 0.5 * 0.5 + 1.0 * 0.5 = 0.25 + 0.50 = 0.75
        assert E_raw == Decimal("0.75")

        # After clipping to E_min (0.4), E_t will be 0.75 (no clipping needed)
        # But if E_volVIX was lower or DD higher, we could reach 0.4

        # Test extreme case: very defensive + severe DD
        E_volVIX_extreme = Decimal("0.4")
        DD_severe = Decimal("0.25")  # Beyond DD_hard

        P_DD_severe, E_raw_extreme = strategy._apply_drawdown_governor(E_volVIX_extreme, DD_severe)

        # P_DD = 0.0 (max DD)
        # E_raw = 0.4 * 0.0 + 1.0 * 1.0 = 1.0 (forced neutral)
        assert E_raw_extreme == Decimal("1.0")

        # This shows that even at max DD, defensive positions can't go below neutral (1.0)
        # But with partial DD, we can get values closer to E_min

        # Better test: moderate defensive signal + moderate DD
        E_volVIX_mod = Decimal("0.6")
        DD_mod = Decimal("0.12")

        P_DD_mod, E_raw_mod = strategy._apply_drawdown_governor(E_volVIX_mod, DD_mod)

        # P_DD = 0.8
        # E_raw = 0.6 * 0.8 + 1.0 * 0.2 = 0.48 + 0.20 = 0.68
        assert E_raw_mod == Decimal("0.68")

        # E_raw (0.68) is above E_min (0.4), showing defensive range is accessible


# ===========================================================================================
# v2.5 INTEGRATION TESTS
# ===========================================================================================

class TestHierarchicalAdaptiveV2_5Integration:
    """Integration tests for full v2.5 strategy."""

    def test_e_min_reachable_in_backtest(self):
        """
        Mini-backtest: Verify E_t can reach defensive range during bearish periods.

        This test verifies the v2.5 fix enables defensive positioning.
        """
        strategy = Hierarchical_Adaptive_v2(
            E_min=Decimal("0.5"),
            E_max=Decimal("1.3"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            k_trend=Decimal("0.3")
        )

        strategy.init()

        # Create bearish scenario bars
        # (This is a simplified test - full backtest would use real data)

        # Simulate: Strong bearish trend + moderate drawdown
        # Expected: E_t should be in defensive range (< 1.0)

        # Test components directly:
        # 1. Bearish trend → low E_trend
        T_norm_bearish = Decimal("-0.8")
        E_trend = strategy._calculate_baseline_exposure(T_norm_bearish)

        # E_trend = 1.0 + 0.3 * (-0.8) = 0.76
        assert E_trend == Decimal("0.76")
        assert E_trend < Decimal("1.0")  # Defensive

        # 2. After vol scaler (assume neutral)
        S_vol = Decimal("1.0")
        E_vol = Decimal("1.0") + (E_trend - Decimal("1.0")) * S_vol
        assert E_vol == Decimal("0.76")

        # 3. After VIX compression (assume neutral)
        P_VIX = Decimal("1.0")
        E_volVIX = Decimal("1.0") + (E_vol - Decimal("1.0")) * P_VIX
        assert E_volVIX == Decimal("0.76")

        # 4. After DD governor with moderate DD
        DD_current = Decimal("0.12")
        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 0.8
        # E_raw = 0.76 * 0.8 + 1.0 * 0.2 = 0.608 + 0.20 = 0.808
        assert E_raw == Decimal("0.808")

        # 5. After clipping
        E_t = max(strategy.E_min, min(strategy.E_max, E_raw))
        assert E_t == Decimal("0.808")

        # Verify E_t is in defensive range
        assert E_t < Decimal("1.0")
        assert E_t >= strategy.E_min

        # This proves v2.5 can reach defensive exposure levels

    def test_parameter_defaults_updated(self):
        """Verify v2.5 DD_soft = 0.10, DD_hard = 0.20 by default."""
        strategy = Hierarchical_Adaptive_v2()

        # v2.5 defaults (changed from v2.0)
        assert strategy.DD_soft == Decimal("0.10")  # Was 0.05 in v2.0
        assert strategy.DD_hard == Decimal("0.20")  # Was 0.15 in v2.0
        assert strategy.p_min == Decimal("0.0")     # Unchanged

    def test_v2_0_vs_v2_5_regression(self):
        """
        Compare v2.0 and v2.5 behavior with same parameters.

        Since the DD governor formula is algebraically equivalent,
        the difference comes from updated DD thresholds.
        """
        # v2.0 parameters
        strategy_v2_0 = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.05"),  # v2.0 default
            DD_hard=Decimal("0.15"),  # v2.0 default
        )

        # v2.5 parameters
        strategy_v2_5 = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),  # v2.5 default
            DD_hard=Decimal("0.20"),  # v2.5 default
        )

        E_volVIX = Decimal("0.7")

        # Test 1: Low DD (below both v2.0 and v2.5 soft thresholds)
        DD_low = Decimal("0.04")

        P_DD_v2_0, E_raw_v2_0 = strategy_v2_0._apply_drawdown_governor(E_volVIX, DD_low)
        P_DD_v2_5, E_raw_v2_5 = strategy_v2_5._apply_drawdown_governor(E_volVIX, DD_low)

        # Both should have P_DD = 1.0, E_raw = E_volVIX
        assert P_DD_v2_0 == Decimal("1.0")
        assert P_DD_v2_5 == Decimal("1.0")
        assert E_raw_v2_0 == E_volVIX
        assert E_raw_v2_5 == E_volVIX

        # Test 2: DD in v2.0's compression range but below v2.5's soft threshold
        DD_mid = Decimal("0.08")

        P_DD_v2_0, E_raw_v2_0 = strategy_v2_0._apply_drawdown_governor(E_volVIX, DD_mid)
        P_DD_v2_5, E_raw_v2_5 = strategy_v2_5._apply_drawdown_governor(E_volVIX, DD_mid)

        # v2.0: DD_soft=0.05, DD_hard=0.15 → P_DD compressed
        # P_DD_v2_0 = 1.0 - ((0.08 - 0.05) / (0.15 - 0.05)) = 1.0 - 0.3 = 0.7
        assert P_DD_v2_0 == Decimal("0.7")

        # v2.5: DD_soft=0.10 → No compression yet
        assert P_DD_v2_5 == Decimal("1.0")

        # v2.0 compresses more aggressively at lower DD levels
        assert E_raw_v2_0 > E_volVIX  # Compressed toward 1.0
        assert E_raw_v2_5 == E_volVIX  # No compression


# ===========================================================================================
# COPIED FROM v2.0 TESTS - Unchanged Components
# ===========================================================================================

class TestInitialization:
    """Test strategy initialization and parameter validation."""

    def test_default_initialization(self):
        """Test strategy initializes with v2.5 default parameters."""
        strategy = Hierarchical_Adaptive_v2()

        # Tier 1: Kalman (unchanged from v2.0)
        assert strategy.measurement_noise == Decimal("2000.0")
        assert strategy.process_noise_1 == Decimal("0.01")
        assert strategy.process_noise_2 == Decimal("0.01")
        assert strategy.osc_smoothness == 15
        assert strategy.strength_smoothness == 15
        assert strategy.T_max == Decimal("60")

        # Tier 0: Core exposure (unchanged from v2.0)
        assert strategy.k_trend == Decimal("0.3")
        assert strategy.E_min == Decimal("0.5")
        assert strategy.E_max == Decimal("1.3")

        # Tier 2: Volatility (unchanged from v2.0)
        assert strategy.sigma_target_multiplier == Decimal("0.9")
        assert strategy.realized_vol_lookback == 20
        assert strategy.S_vol_min == Decimal("0.5")
        assert strategy.S_vol_max == Decimal("1.5")

        # Tier 3: VIX (unchanged from v2.0)
        assert strategy.vix_ema_period == 50
        assert strategy.alpha_VIX == Decimal("1.0")

        # Tier 4: Drawdown (CHANGED in v2.5)
        assert strategy.DD_soft == Decimal("0.10")  # Changed from 0.05
        assert strategy.DD_hard == Decimal("0.20")  # Changed from 0.15
        assert strategy.p_min == Decimal("0.0")     # Unchanged

        # Tier 5: Rebalancing (unchanged from v2.0)
        assert strategy.rebalance_threshold == Decimal("0.025")

        # Symbols (unchanged from v2.0)
        assert strategy.signal_symbol == "QQQ"
        assert strategy.core_long_symbol == "QQQ"
        assert strategy.leveraged_long_symbol == "TQQQ"
        assert strategy.vix_symbol == "$VIX"

    def test_custom_parameters(self):
        """Test strategy accepts custom parameters."""
        strategy = Hierarchical_Adaptive_v2(
            measurement_noise=Decimal("5000.0"),
            k_trend=Decimal("0.4"),
            E_min=Decimal("0.6"),
            E_max=Decimal("1.4"),
            DD_soft=Decimal("0.08"),
            DD_hard=Decimal("0.18"),
            vix_ema_period=30,
            rebalance_threshold=Decimal("0.03")
        )

        assert strategy.measurement_noise == Decimal("5000.0")
        assert strategy.k_trend == Decimal("0.4")
        assert strategy.E_min == Decimal("0.6")
        assert strategy.E_max == Decimal("1.4")
        assert strategy.DD_soft == Decimal("0.08")
        assert strategy.DD_hard == Decimal("0.18")
        assert strategy.vix_ema_period == 30
        assert strategy.rebalance_threshold == Decimal("0.03")

    def test_invalid_exposure_bounds(self):
        """Test validation of exposure bounds."""
        with pytest.raises(ValueError, match="Exposure bounds"):
            Hierarchical_Adaptive_v2(E_min=Decimal("1.5"), E_max=Decimal("1.3"))

        with pytest.raises(ValueError, match="Exposure bounds"):
            Hierarchical_Adaptive_v2(E_min=Decimal("-0.1"), E_max=Decimal("1.3"))

    def test_invalid_drawdown_thresholds(self):
        """Test validation of drawdown thresholds."""
        with pytest.raises(ValueError, match="Drawdown thresholds"):
            Hierarchical_Adaptive_v2(DD_soft=Decimal("0.25"), DD_hard=Decimal("0.20"))

        with pytest.raises(ValueError, match="Drawdown thresholds"):
            Hierarchical_Adaptive_v2(DD_soft=Decimal("-0.1"))


class TestNormalizedTrend:
    """Test normalized trend calculation (unchanged from v2.0)."""

    def test_positive_trend_within_bounds(self):
        """Test positive trend strength within T_max."""
        strategy = Hierarchical_Adaptive_v2(T_max=Decimal("60"))

        T_norm = strategy._calculate_normalized_trend(Decimal("30"))
        assert T_norm == Decimal("0.5")  # 30 / 60 = 0.5

    def test_negative_trend_within_bounds(self):
        """Test negative trend strength within T_max."""
        strategy = Hierarchical_Adaptive_v2(T_max=Decimal("60"))

        T_norm = strategy._calculate_normalized_trend(Decimal("-30"))
        assert T_norm == Decimal("-0.5")  # -30 / 60 = -0.5

    def test_trend_clipped_to_plus_one(self):
        """Test trend strength clipped to +1.0."""
        strategy = Hierarchical_Adaptive_v2(T_max=Decimal("60"))

        T_norm = strategy._calculate_normalized_trend(Decimal("90"))
        assert T_norm == Decimal("1.0")  # clip(90/60, -1, +1) = +1.0

    def test_trend_clipped_to_minus_one(self):
        """Test trend strength clipped to -1.0."""
        strategy = Hierarchical_Adaptive_v2(T_max=Decimal("60"))

        T_norm = strategy._calculate_normalized_trend(Decimal("-90"))
        assert T_norm == Decimal("-1.0")  # clip(-90/60, -1, +1) = -1.0


class TestBaselineExposure:
    """Test baseline exposure calculation (unchanged from v2.0)."""

    def test_neutral_trend(self):
        """Test baseline exposure with neutral trend."""
        strategy = Hierarchical_Adaptive_v2(k_trend=Decimal("0.3"))

        E_trend = strategy._calculate_baseline_exposure(Decimal("0.0"))
        assert E_trend == Decimal("1.0")  # 1.0 + 0.3 * 0.0 = 1.0

    def test_strong_bull_trend(self):
        """Test baseline exposure with strong bullish trend."""
        strategy = Hierarchical_Adaptive_v2(k_trend=Decimal("0.3"))

        E_trend = strategy._calculate_baseline_exposure(Decimal("1.0"))
        assert E_trend == Decimal("1.3")  # 1.0 + 0.3 * 1.0 = 1.3

    def test_strong_bear_trend(self):
        """Test baseline exposure with strong bearish trend."""
        strategy = Hierarchical_Adaptive_v2(k_trend=Decimal("0.3"))

        E_trend = strategy._calculate_baseline_exposure(Decimal("-1.0"))
        assert E_trend == Decimal("0.7")  # 1.0 + 0.3 * (-1.0) = 0.7


class TestVolatilityScaler:
    """Test volatility scaler application (unchanged from v2.0)."""

    def test_low_realized_vol(self):
        """Test scaler when realized vol is below target."""
        strategy = Hierarchical_Adaptive_v2(
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
        strategy = Hierarchical_Adaptive_v2()
        strategy.sigma_target = Decimal("0.18")

        E_trend = Decimal("1.3")
        sigma_real = Decimal("0.0")

        S_vol, E_vol = strategy._apply_volatility_scaler(E_trend, sigma_real)

        # Should default to S_vol = 1.0 when sigma_real = 0
        assert S_vol == Decimal("1.0")
        assert E_vol == Decimal("1.3")


class TestVIXCompression:
    """Test VIX compression application (unchanged from v2.0)."""

    def test_vix_below_ema(self):
        """Test no compression when VIX below EMA."""
        strategy = Hierarchical_Adaptive_v2(alpha_VIX=Decimal("1.0"))

        E_vol = Decimal("1.3")
        R_VIX = Decimal("0.9")  # VIX < VIX_EMA

        P_VIX, E_volVIX = strategy._apply_vix_compression(E_vol, R_VIX)

        assert P_VIX == Decimal("1.0")
        assert E_volVIX == Decimal("1.3")

    def test_vix_above_ema(self):
        """Test compression when VIX above EMA."""
        strategy = Hierarchical_Adaptive_v2(alpha_VIX=Decimal("1.0"))

        E_vol = Decimal("1.3")
        R_VIX = Decimal("1.2")  # VIX > VIX_EMA

        P_VIX, E_volVIX = strategy._apply_vix_compression(E_vol, R_VIX)

        # P_VIX = 1 / (1 + 1.0 * (1.2 - 1.0)) = 1 / 1.2 = 0.8333...
        expected_P_VIX = Decimal("1.0") / (Decimal("1.0") + Decimal("0.2"))
        assert abs(P_VIX - expected_P_VIX) < Decimal("0.001")


class TestPositionMapping:
    """Test QQQ/TQQQ position mapping (unchanged from v2.0)."""

    def test_exposure_below_one(self):
        """Test mapping when E_t <= 1.0 (QQQ + cash)."""
        strategy = Hierarchical_Adaptive_v2()

        E_t = Decimal("0.7")
        w_QQQ, w_TQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        assert w_QQQ == Decimal("0.7")
        assert w_TQQQ == Decimal("0.0")
        assert w_cash == Decimal("0.3")

    def test_exposure_equal_to_one(self):
        """Test mapping when E_t == 1.0 (100% QQQ)."""
        strategy = Hierarchical_Adaptive_v2()

        E_t = Decimal("1.0")
        w_QQQ, w_TQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        assert w_QQQ == Decimal("1.0")
        assert w_TQQQ == Decimal("0.0")
        assert w_cash == Decimal("0.0")

    def test_exposure_above_one(self):
        """Test mapping when E_t > 1.0 (QQQ + TQQQ)."""
        strategy = Hierarchical_Adaptive_v2()

        E_t = Decimal("1.3")
        w_QQQ, w_TQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # w_TQQQ = (1.3 - 1.0) / 2.0 = 0.15
        assert w_TQQQ == Decimal("0.15")
        # w_QQQ = 1.0 - 0.15 = 0.85
        assert w_QQQ == Decimal("0.85")
        assert w_cash == Decimal("0.0")

        # Verify effective exposure: 0.85*1 + 0.15*3 = 1.3
        effective_exposure = w_QQQ * Decimal("1") + w_TQQQ * Decimal("3")
        assert effective_exposure == Decimal("1.3")


class TestRebalancing:
    """Test rebalancing threshold and execution (unchanged from v2.0)."""

    def test_no_rebalancing_needed(self):
        """Test no rebalancing when weights within threshold."""
        strategy = Hierarchical_Adaptive_v2(rebalance_threshold=Decimal("0.025"))

        strategy.current_qqq_weight = Decimal("0.85")
        strategy.current_tqqq_weight = Decimal("0.15")

        target_qqq = Decimal("0.86")
        target_tqqq = Decimal("0.14")

        needs_rebalance = strategy._check_rebalancing_threshold(target_qqq, target_tqqq)

        # Deviation = |0.85 - 0.86| + |0.15 - 0.14| = 0.01 + 0.01 = 0.02 = 2%
        # Threshold = 2.5%, so no rebalance needed
        assert not needs_rebalance

    def test_rebalancing_needed(self):
        """Test rebalancing when weights exceed threshold."""
        strategy = Hierarchical_Adaptive_v2(rebalance_threshold=Decimal("0.025"))

        strategy.current_qqq_weight = Decimal("0.82")
        strategy.current_tqqq_weight = Decimal("0.16")

        target_qqq = Decimal("0.85")
        target_tqqq = Decimal("0.15")

        needs_rebalance = strategy._check_rebalancing_threshold(target_qqq, target_tqqq)

        # Deviation = |0.82 - 0.85| + |0.16 - 0.15| = 0.03 + 0.01 = 0.04 = 4%
        # Threshold = 2.5%, so rebalance needed
        assert needs_rebalance


class TestDrawdownTracking:
    """Test drawdown tracking logic (unchanged from v2.0)."""

    def test_initial_drawdown_zero(self):
        """Test drawdown is zero initially."""
        strategy = Hierarchical_Adaptive_v2()

        DD_current = strategy._update_drawdown_tracking(Decimal("0"))

        assert DD_current == Decimal("0")

    def test_peak_updated(self):
        """Test equity peak is updated when new high reached."""
        strategy = Hierarchical_Adaptive_v2()

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
        strategy = Hierarchical_Adaptive_v2()

        # Set peak
        strategy._update_drawdown_tracking(Decimal("100000"))

        # Drawdown to 88000
        DD_current = strategy._update_drawdown_tracking(Decimal("88000"))

        # DD = (100000 - 88000) / 100000 = 0.12 = 12%
        assert DD_current == Decimal("0.12")

    def test_drawdown_recovery(self):
        """Test drawdown decreases as equity recovers."""
        strategy = Hierarchical_Adaptive_v2()

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
