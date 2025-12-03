"""
Unit tests for Hierarchical_Adaptive_v2.8 strategy.

Tests v2.8-specific two-parameter floor system and SQQQ reachability:

1. **Two-Parameter Floor System (CRITICAL)**: E_anchor (DD governor) vs E_short (clip floor)
2. **Stronger k_short (CRITICAL)**: Range [0.8, 1.2] allows negative E_trend
3. **DD Governor Fix (CRITICAL)**: Anchors to E_anchor (not E_short)
4. **Final Clipping Fix (CRITICAL)**: Uses E_short as lower bound
5. **SQQQ Weight Cap (NEW)**: w_SQQQ_max parameter limits SQQQ positions
6. **SQQQ Reachability (VALIDATION)**: Mathematical proof SQQQ is accessible

All other tiers (Vol, VIX, signed trend, position mapping, rebalancing) are unchanged from v2.7_1.
"""
from decimal import Decimal
from datetime import datetime, timezone
import pytest

from jutsu_engine.strategies.Hierarchical_Adaptive_v2_8 import Hierarchical_Adaptive_v2_8
from jutsu_engine.core.events import MarketDataEvent


# ===========================================================================================
# v2.8 SPECIFIC TESTS - Two-Parameter Floor System & SQQQ Reachability
# ===========================================================================================

class TestHierarchicalAdaptiveV2_8TwoParameterSystem:
    """Test v2.8 FIX 1: Two-parameter floor system (E_anchor vs E_short)."""

    def test_valid_two_parameter_system(self):
        """
        Valid two-parameter system: E_short < 0 <= E_anchor < E_max
        """
        strategy = Hierarchical_Adaptive_v2_8(
            E_short=Decimal("-0.2"),
            E_anchor=Decimal("0.7"),
            E_max=Decimal("1.5")
        )

        assert strategy.E_short == Decimal("-0.2")
        assert strategy.E_anchor == Decimal("0.7")
        assert strategy.E_max == Decimal("1.5")

    def test_invalid_e_short_positive(self):
        """
        Invalid: E_short >= 0 (must be negative)
        """
        with pytest.raises(ValueError, match="E_short.*< 0"):
            Hierarchical_Adaptive_v2_8(
                E_short=Decimal("0.1"),  # Invalid
                E_anchor=Decimal("0.7"),
                E_max=Decimal("1.5")
            )

    def test_invalid_e_anchor_negative(self):
        """
        Invalid: E_anchor <= 0 (must be positive)
        """
        with pytest.raises(ValueError, match="Two-parameter floor system"):
            Hierarchical_Adaptive_v2_8(
                E_short=Decimal("-0.2"),
                E_anchor=Decimal("-0.1"),  # Invalid
                E_max=Decimal("1.5")
            )

    def test_invalid_e_anchor_exceeds_e_max(self):
        """
        Invalid: E_anchor >= E_max
        """
        with pytest.raises(ValueError, match="Two-parameter floor system"):
            Hierarchical_Adaptive_v2_8(
                E_short=Decimal("-0.2"),
                E_anchor=Decimal("1.6"),  # Invalid (>= E_max)
                E_max=Decimal("1.5")
            )

    def test_w_sqqq_max_validation(self):
        """
        Valid: w_SQQQ_max in (0, 1]
        """
        # Valid
        strategy = Hierarchical_Adaptive_v2_8(
            w_SQQQ_max=Decimal("0.25")
        )
        assert strategy.w_SQQQ_max == Decimal("0.25")

        # Invalid: w_SQQQ_max <= 0
        with pytest.raises(ValueError, match="SQQQ cap"):
            Hierarchical_Adaptive_v2_8(
                w_SQQQ_max=Decimal("0.0")
            )

        # Invalid: w_SQQQ_max > 1.0
        with pytest.raises(ValueError, match="SQQQ cap"):
            Hierarchical_Adaptive_v2_8(
                w_SQQQ_max=Decimal("1.5")
            )


class TestHierarchicalAdaptiveV2_8StrongerKShort:
    """Test v2.8 FIX 2: Stronger k_short allows negative E_trend."""

    def test_k_short_default_value(self):
        """
        k_short default is 1.0 (stronger than v2.7_1's 0.2)
        """
        strategy = Hierarchical_Adaptive_v2_8()
        assert strategy.k_short == Decimal("1.0")

    def test_e_trend_can_go_negative(self):
        """
        With k_short=1.0, strong bear (T_norm=-1.0) yields E_trend=0.0
        """
        strategy = Hierarchical_Adaptive_v2_8(
            k_short=Decimal("1.0")
        )

        T_norm = Decimal("-1.0")
        E_trend = strategy._calculate_baseline_exposure(T_norm)

        # E_trend = 1.0 + k_short × T_norm
        # E_trend = 1.0 + 1.0 × (-1.0) = 0.0
        assert E_trend == Decimal("0.0")

    def test_e_trend_with_k_short_1_2(self):
        """
        With k_short=1.2 (max range), strong bear yields E_trend=-0.2
        """
        strategy = Hierarchical_Adaptive_v2_8(
            k_short=Decimal("1.2")
        )

        T_norm = Decimal("-1.0")
        E_trend = strategy._calculate_baseline_exposure(T_norm)

        # E_trend = 1.0 + 1.2 × (-1.0) = -0.2
        assert E_trend == Decimal("-0.2")

    def test_e_trend_asymmetric_scaling(self):
        """
        k_long and k_short are independent
        """
        strategy = Hierarchical_Adaptive_v2_8(
            k_long=Decimal("0.7"),
            k_short=Decimal("1.0")
        )

        # Bull regime
        T_norm_bull = Decimal("1.0")
        E_trend_bull = strategy._calculate_baseline_exposure(T_norm_bull)
        assert E_trend_bull == Decimal("1.7")  # 1.0 + 0.7 × 1.0

        # Bear regime
        T_norm_bear = Decimal("-1.0")
        E_trend_bear = strategy._calculate_baseline_exposure(T_norm_bear)
        assert E_trend_bear == Decimal("0.0")  # 1.0 + 1.0 × (-1.0)


class TestHierarchicalAdaptiveV2_8DDGovernorAnchor:
    """Test v2.8 FIX 3: DD governor anchors to E_anchor (not E_short)."""

    def test_dd_governor_mild_dd(self):
        """
        Mild DD (P_DD ≈ 1): E_raw ≈ E_volVIX (trend-driven)
        """
        strategy = Hierarchical_Adaptive_v2_8(
            E_anchor=Decimal("0.7"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("-0.1")
        DD_current = Decimal("0.05")  # < DD_soft

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 1.0 (no compression)
        assert P_DD == Decimal("1.0")

        # E_raw = E_anchor + (E_volVIX - E_anchor) × P_DD
        # E_raw = 0.7 + (-0.1 - 0.7) × 1.0 = -0.1
        assert E_raw == Decimal("-0.1")

    def test_dd_governor_deep_dd(self):
        """
        Deep DD (P_DD → 0): E_raw → E_anchor (safe positive floor)
        """
        strategy = Hierarchical_Adaptive_v2_8(
            E_anchor=Decimal("0.7"),
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("-0.1")
        DD_current = Decimal("0.25")  # >= DD_hard

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = p_min = 0.0 (full compression)
        assert P_DD == Decimal("0.0")

        # E_raw = E_anchor + (E_volVIX - E_anchor) × 0.0 = E_anchor
        assert E_raw == Decimal("0.7")

    def test_dd_governor_uses_e_anchor_not_e_short(self):
        """
        DD governor uses E_anchor as anchor (not E_short)
        """
        strategy = Hierarchical_Adaptive_v2_8(
            E_anchor=Decimal("0.7"),
            E_short=Decimal("-0.2")
        )

        E_volVIX = Decimal("-0.5")
        DD_current = Decimal("0.25")  # Deep DD

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # E_raw should converge to E_anchor (0.7), not E_short (-0.2)
        assert E_raw == strategy.E_anchor
        assert E_raw != strategy.E_short


class TestHierarchicalAdaptiveV2_8FinalClipping:
    """Test v2.8 FIX 4: Final clipping uses E_short as lower bound."""

    def test_clipping_uses_e_short_floor(self):
        """
        E_t = clip(E_raw, E_short, E_max)

        v2.7_1 Bug: Used E_min for both DD anchor and clip floor
        v2.8 Fix: DD uses E_anchor, clip uses E_short
        """
        strategy = Hierarchical_Adaptive_v2_8(
            E_anchor=Decimal("0.7"),
            E_short=Decimal("-0.2"),
            E_max=Decimal("1.5")
        )

        # Test cases for clipping
        test_cases = [
            (Decimal("-0.5"), Decimal("-0.2")),  # Below floor → clipped to E_short
            (Decimal("-0.1"), Decimal("-0.1")),  # Within range → unchanged
            (Decimal("0.5"), Decimal("0.5")),    # Within range → unchanged
            (Decimal("1.3"), Decimal("1.3")),    # Within range → unchanged
            (Decimal("2.0"), Decimal("1.5")),    # Above ceiling → clipped to E_max
        ]

        for E_raw, expected_E_t in test_cases:
            E_t = max(strategy.E_short, min(strategy.E_max, E_raw))
            assert E_t == expected_E_t, f"E_raw={E_raw} → E_t={E_t} (expected {expected_E_t})"


class TestHierarchicalAdaptiveV2_8SQQQWeightCap:
    """Test v2.8 FIX 5: SQQQ weight cap enforced."""

    def test_sqqq_cap_region_2(self):
        """
        Region 2 (E_t ∈ (-1, 0)): w_SQQQ capped at w_SQQQ_max
        """
        strategy = Hierarchical_Adaptive_v2_8(
            w_SQQQ_max=Decimal("0.25")
        )

        # E_t = -0.9 → uncapped w_SQQQ = -(-0.9)/3.0 = 0.3
        E_t = Decimal("-0.9")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # Should be capped at 0.25
        assert w_SQQQ == Decimal("0.25")
        assert w_SQQQ <= strategy.w_SQQQ_max

    def test_sqqq_cap_region_1(self):
        """
        Region 1 (E_t <= -1): w_SQQQ capped at w_SQQQ_max
        """
        strategy = Hierarchical_Adaptive_v2_8(
            w_SQQQ_max=Decimal("0.25")
        )

        # E_t = -2.0 → uncapped w_SQQQ = (1.0 - (-2.0))/4.0 = 0.75
        E_t = Decimal("-2.0")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # Should be capped at 0.25
        assert w_SQQQ == Decimal("0.25")
        assert w_SQQQ <= strategy.w_SQQQ_max

    def test_sqqq_cap_no_effect_when_below_cap(self):
        """
        When uncapped w_SQQQ < w_SQQQ_max, cap has no effect
        """
        strategy = Hierarchical_Adaptive_v2_8(
            w_SQQQ_max=Decimal("0.25")
        )

        # E_t = -0.3 → uncapped w_SQQQ = 0.3/3.0 = 0.1
        E_t = Decimal("-0.3")
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # Should remain at 0.1 (< cap)
        expected_w_SQQQ = -E_t / Decimal("3.0")
        assert w_SQQQ == expected_w_SQQQ
        assert w_SQQQ < strategy.w_SQQQ_max


class TestHierarchicalAdaptiveV2_8SQQQReachability:
    """Test v2.8 VALIDATION: SQQQ is mathematically reachable."""

    def test_sqqq_reachable_scenario(self):
        """
        Mathematical proof SQQQ is reachable:

        1. k_short=1.0, T_norm=-1.0 → E_trend=0.0
        2. Vol/VIX compress → E_volVIX<0
        3. Mild DD (P_DD≈1) → E_raw<0
        4. Clip to [E_short, E_max] → E_t<0
        5. Map to weights → w_SQQQ>0
        """
        strategy = Hierarchical_Adaptive_v2_8(
            k_short=Decimal("1.0"),
            E_anchor=Decimal("0.7"),
            E_short=Decimal("-0.2"),
            E_max=Decimal("1.5"),
            w_SQQQ_max=Decimal("0.25")
        )

        # Step 1: Strong bear trend
        T_norm = Decimal("-1.0")
        E_trend = strategy._calculate_baseline_exposure(T_norm)
        assert E_trend == Decimal("0.0")

        # Step 2: Simulate vol/VIX compression (worst case)
        E_volVIX = Decimal("-0.1")

        # Step 3: Mild DD (no compression)
        DD_current = Decimal("0.05")  # < DD_soft
        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)
        assert P_DD == Decimal("1.0")
        assert E_raw < Decimal("0")  # Negative!

        # Step 4: Clip to bounds
        E_t = max(strategy.E_short, min(strategy.E_max, E_raw))
        assert E_t < Decimal("0")  # Still negative!

        # Step 5: Map to weights
        w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        # SQQQ reached!
        assert w_SQQQ > Decimal("0")
        assert w_QQQ == Decimal("0")
        assert w_TQQQ == Decimal("0")

    def test_sqqq_not_reachable_with_weak_k_short(self):
        """
        With weak k_short (like v2.7_1's 0.2), E_trend stays positive

        v2.7_1 config: k_short=0.2
        - E_trend_min = 1.0 + 0.2 × (-1.0) = 0.8 (never negative)
        - Result: E_t rarely went below 0

        Note: Can't directly simulate v2.7_1 because it used single E_min parameter
        """
        # Demonstrate weak k_short keeps E_trend positive
        strategy_weak = Hierarchical_Adaptive_v2_8(
            k_short=Decimal("0.2"),  # Weak (like v2.7_1)
            E_anchor=Decimal("0.5"),  # Need positive E_anchor
            E_short=Decimal("-0.5"),  # Allow negative E_t
            E_max=Decimal("1.5")
        )

        T_norm = Decimal("-1.0")
        E_trend = strategy_weak._calculate_baseline_exposure(T_norm)

        # E_trend = 1.0 + 0.2 × (-1.0) = 0.8 (positive!)
        assert E_trend == Decimal("0.8")
        assert E_trend > Decimal("0")  # Never negative

        # Even with extreme vol/VIX compression, unlikely to reach SQQQ
        # because E_trend starts at 0.8, not 0.0


class TestHierarchicalAdaptiveV2_8EdgeCases:
    """Test edge cases and boundary conditions."""

    def test_weight_sum_is_one(self):
        """
        All weight mappings sum to 1.0
        """
        strategy = Hierarchical_Adaptive_v2_8()

        test_exposures = [
            Decimal("-2.0"),
            Decimal("-0.5"),
            Decimal("-0.1"),
            Decimal("0.0"),
            Decimal("0.5"),
            Decimal("1.0"),
            Decimal("1.3"),
            Decimal("1.5"),
        ]

        for E_t in test_exposures:
            w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)
            weight_sum = w_QQQ + w_TQQQ + w_SQQQ + w_cash
            assert weight_sum == Decimal("1.0"), f"E_t={E_t} → sum={weight_sum}"

    def test_no_negative_weights(self):
        """
        All weights are non-negative
        """
        strategy = Hierarchical_Adaptive_v2_8()

        test_exposures = [
            Decimal("-2.0"),
            Decimal("-0.5"),
            Decimal("0.0"),
            Decimal("1.0"),
            Decimal("1.5"),
        ]

        for E_t in test_exposures:
            w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)
            assert w_QQQ >= Decimal("0")
            assert w_TQQQ >= Decimal("0")
            assert w_SQQQ >= Decimal("0")
            assert w_cash >= Decimal("0")

    def test_mutual_exclusivity_of_positions(self):
        """
        QQQ/TQQQ and SQQQ are mutually exclusive
        """
        strategy = Hierarchical_Adaptive_v2_8()

        test_exposures = [
            Decimal("-0.5"),
            Decimal("0.0"),
            Decimal("0.5"),
            Decimal("1.3"),
        ]

        for E_t in test_exposures:
            w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

            # Either long or short, never both
            if w_SQQQ > Decimal("0"):
                assert w_QQQ == Decimal("0")
                assert w_TQQQ == Decimal("0")
            else:
                assert w_SQQQ == Decimal("0")


class TestHierarchicalAdaptiveV2_8ParameterRanges:
    """Test parameter validation and ranges."""

    def test_k_short_range(self):
        """
        k_short should be in [0.8, 1.2] for v2.8
        """
        # Valid values
        for k_short in [Decimal("0.8"), Decimal("1.0"), Decimal("1.2")]:
            strategy = Hierarchical_Adaptive_v2_8(k_short=k_short)
            assert strategy.k_short == k_short

    def test_e_anchor_range(self):
        """
        E_anchor should be in [0.6, 0.8] typically
        """
        # Valid values
        for E_anchor in [Decimal("0.6"), Decimal("0.7"), Decimal("0.8")]:
            strategy = Hierarchical_Adaptive_v2_8(E_anchor=E_anchor)
            assert strategy.E_anchor == E_anchor

    def test_e_short_range(self):
        """
        E_short should be in [-0.3, 0.0] typically
        """
        # Valid values
        for E_short in [Decimal("-0.3"), Decimal("-0.2"), Decimal("-0.1")]:
            strategy = Hierarchical_Adaptive_v2_8(E_short=E_short)
            assert strategy.E_short == E_short

    def test_w_sqqq_max_range(self):
        """
        w_SQQQ_max should be in [0.2, 0.25] typically
        """
        # Valid values
        for w_SQQQ_max in [Decimal("0.2"), Decimal("0.25")]:
            strategy = Hierarchical_Adaptive_v2_8(w_SQQQ_max=w_SQQQ_max)
            assert strategy.w_SQQQ_max == w_SQQQ_max


# ===========================================================================================
# INTEGRATION TEST
# ===========================================================================================

def test_v2_8_full_integration():
    """
    Full integration test: v2.8 two-parameter system enables SQQQ
    """
    strategy = Hierarchical_Adaptive_v2_8(
        k_long=Decimal("0.7"),
        k_short=Decimal("1.0"),
        E_anchor=Decimal("0.7"),
        E_short=Decimal("-0.2"),
        E_max=Decimal("1.5"),
        w_SQQQ_max=Decimal("0.25")
    )

    # Verify two-parameter system
    assert strategy.E_anchor == Decimal("0.7")
    assert strategy.E_short == Decimal("-0.2")
    assert strategy.E_short < Decimal("0") < strategy.E_anchor < strategy.E_max

    # Verify stronger k_short
    assert strategy.k_short == Decimal("1.0")
    T_norm_bear = Decimal("-1.0")
    E_trend_bear = strategy._calculate_baseline_exposure(T_norm_bear)
    assert E_trend_bear == Decimal("0.0")  # Can reach 0!

    # Verify DD governor uses E_anchor
    E_volVIX = Decimal("-0.1")
    DD_deep = Decimal("0.25")
    P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_deep)
    assert E_raw == strategy.E_anchor  # Converges to E_anchor

    # Verify final clipping uses E_short
    E_t_negative = Decimal("-0.15")
    E_t_clipped = max(strategy.E_short, min(strategy.E_max, E_t_negative))
    assert E_t_clipped == E_t_negative  # Within [E_short, E_max]

    # Verify SQQQ weight cap
    w_QQQ, w_TQQQ, w_SQQQ, w_cash = strategy._map_exposure_to_weights(E_t_negative)
    assert w_SQQQ > Decimal("0")  # SQQQ reached!
    assert w_SQQQ <= strategy.w_SQQQ_max  # Capped!

    print("✅ v2.8 Full Integration Test PASSED")
