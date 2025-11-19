"""
Unit tests for Hierarchical_Adaptive_v2 strategy.

Tests all 5 tiers of the exposure engine:
- Tier 1: Normalized trend calculation
- Tier 2: Baseline exposure
- Tier 3: Volatility scaler
- Tier 4: VIX compression
- Tier 5: Drawdown governor
- Position mapping
- Rebalancing logic
- Full integration with on_bar()
"""
from decimal import Decimal
from datetime import datetime, timezone
import pytest

from jutsu_engine.strategies.Hierarchical_Adaptive_v2 import Hierarchical_Adaptive_v2
from jutsu_engine.core.events import MarketDataEvent


class TestInitialization:
    """Test strategy initialization and parameter validation."""

    def test_default_initialization(self):
        """Test strategy initializes with default parameters."""
        strategy = Hierarchical_Adaptive_v2()

        # Tier 1: Kalman
        assert strategy.measurement_noise == Decimal("2000.0")
        assert strategy.process_noise_1 == Decimal("0.01")
        assert strategy.process_noise_2 == Decimal("0.01")
        assert strategy.osc_smoothness == 15
        assert strategy.strength_smoothness == 15
        assert strategy.T_max == Decimal("60")

        # Tier 0: Core exposure
        assert strategy.k_trend == Decimal("0.3")
        assert strategy.E_min == Decimal("0.5")
        assert strategy.E_max == Decimal("1.3")

        # Tier 2: Volatility
        assert strategy.sigma_target_multiplier == Decimal("0.9")
        assert strategy.realized_vol_lookback == 20
        assert strategy.S_vol_min == Decimal("0.5")
        assert strategy.S_vol_max == Decimal("1.5")

        # Tier 3: VIX
        assert strategy.vix_ema_period == 50
        assert strategy.alpha_VIX == Decimal("1.0")

        # Tier 4: Drawdown
        assert strategy.DD_soft == Decimal("0.10")
        assert strategy.DD_hard == Decimal("0.20")
        assert strategy.p_min == Decimal("0.0")

        # Tier 5: Rebalancing
        assert strategy.rebalance_threshold == Decimal("0.025")

        # Symbols
        assert strategy.signal_symbol == "QQQ"
        assert strategy.core_long_symbol == "QQQ"
        assert strategy.leveraged_long_symbol == "TQQQ"
        assert strategy.vix_symbol == "VIX"

    def test_custom_parameters(self):
        """Test strategy accepts custom parameters."""
        strategy = Hierarchical_Adaptive_v2(
            measurement_noise=Decimal("5000.0"),
            k_trend=Decimal("0.4"),
            E_min=Decimal("0.6"),
            E_max=Decimal("1.4"),
            vix_ema_period=30,
            rebalance_threshold=Decimal("0.03")
        )

        assert strategy.measurement_noise == Decimal("5000.0")
        assert strategy.k_trend == Decimal("0.4")
        assert strategy.E_min == Decimal("0.6")
        assert strategy.E_max == Decimal("1.4")
        assert strategy.vix_ema_period == 30
        assert strategy.rebalance_threshold == Decimal("0.03")

    def test_invalid_exposure_bounds(self):
        """Test validation of exposure bounds."""
        with pytest.raises(ValueError, match="Exposure bounds"):
            Hierarchical_Adaptive_v2(E_min=Decimal("1.5"), E_max=Decimal("1.3"))

        with pytest.raises(ValueError, match="Exposure bounds"):
            Hierarchical_Adaptive_v2(E_min=Decimal("-0.1"), E_max=Decimal("1.3"))

    def test_invalid_vol_scaler_bounds(self):
        """Test validation of volatility scaler bounds."""
        with pytest.raises(ValueError, match="Vol scaler bounds"):
            Hierarchical_Adaptive_v2(S_vol_min=Decimal("1.5"), S_vol_max=Decimal("0.8"))

        with pytest.raises(ValueError, match="Vol scaler bounds"):
            Hierarchical_Adaptive_v2(S_vol_min=Decimal("-0.1"))

    def test_invalid_drawdown_thresholds(self):
        """Test validation of drawdown thresholds."""
        with pytest.raises(ValueError, match="Drawdown thresholds"):
            Hierarchical_Adaptive_v2(DD_soft=Decimal("0.25"), DD_hard=Decimal("0.20"))

        with pytest.raises(ValueError, match="Drawdown thresholds"):
            Hierarchical_Adaptive_v2(DD_soft=Decimal("-0.1"))

    def test_invalid_vix_ema_period(self):
        """Test validation of VIX EMA period."""
        with pytest.raises(ValueError, match="VIX EMA period"):
            Hierarchical_Adaptive_v2(vix_ema_period=0)

    def test_invalid_rebalance_threshold(self):
        """Test validation of rebalance threshold."""
        with pytest.raises(ValueError, match="Rebalance threshold"):
            Hierarchical_Adaptive_v2(rebalance_threshold=Decimal("-0.01"))


class TestNormalizedTrend:
    """Test normalized trend calculation."""

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

    def test_zero_trend(self):
        """Test zero trend strength."""
        strategy = Hierarchical_Adaptive_v2(T_max=Decimal("60"))

        T_norm = strategy._calculate_normalized_trend(Decimal("0"))
        assert T_norm == Decimal("0.0")


class TestBaselineExposure:
    """Test baseline exposure calculation."""

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

    def test_moderate_bull_trend(self):
        """Test baseline exposure with moderate bullish trend."""
        strategy = Hierarchical_Adaptive_v2(k_trend=Decimal("0.3"))

        E_trend = strategy._calculate_baseline_exposure(Decimal("0.5"))
        assert E_trend == Decimal("1.15")  # 1.0 + 0.3 * 0.5 = 1.15


class TestVolatilityScaler:
    """Test volatility scaler application."""

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

    def test_high_realized_vol(self):
        """Test scaler when realized vol is above target."""
        strategy = Hierarchical_Adaptive_v2(
            sigma_target_multiplier=Decimal("0.9"),
            S_vol_min=Decimal("0.5"),
            S_vol_max=Decimal("1.5")
        )
        strategy.sigma_target = Decimal("0.18")  # 18%

        E_trend = Decimal("1.3")
        sigma_real = Decimal("0.25")  # Higher than target

        S_vol, E_vol = strategy._apply_volatility_scaler(E_trend, sigma_real)

        # S_vol = 0.18 / 0.25 = 0.72
        assert S_vol == Decimal("0.72")
        # E_vol = 1.0 + (1.3 - 1.0) * 0.72 = 1.216
        assert E_vol == Decimal("1.216")

    def test_scaler_clipped_to_max(self):
        """Test scaler clipped to S_vol_max."""
        strategy = Hierarchical_Adaptive_v2(
            sigma_target_multiplier=Decimal("0.9"),
            S_vol_min=Decimal("0.5"),
            S_vol_max=Decimal("1.5")
        )
        strategy.sigma_target = Decimal("0.18")

        E_trend = Decimal("1.3")
        sigma_real = Decimal("0.05")  # Very low vol

        S_vol, E_vol = strategy._apply_volatility_scaler(E_trend, sigma_real)

        # S_vol = clip(0.18 / 0.05 = 3.6, 0.5, 1.5) = 1.5
        assert S_vol == Decimal("1.5")
        # E_vol = 1.0 + (1.3 - 1.0) * 1.5 = 1.45
        assert E_vol == Decimal("1.45")

    def test_scaler_clipped_to_min(self):
        """Test scaler clipped to S_vol_min."""
        strategy = Hierarchical_Adaptive_v2(
            sigma_target_multiplier=Decimal("0.9"),
            S_vol_min=Decimal("0.5"),
            S_vol_max=Decimal("1.5")
        )
        strategy.sigma_target = Decimal("0.18")

        E_trend = Decimal("1.3")
        sigma_real = Decimal("0.50")  # Very high vol

        S_vol, E_vol = strategy._apply_volatility_scaler(E_trend, sigma_real)

        # S_vol = clip(0.18 / 0.50 = 0.36, 0.5, 1.5) = 0.5
        assert S_vol == Decimal("0.5")
        # E_vol = 1.0 + (1.3 - 1.0) * 0.5 = 1.15
        assert E_vol == Decimal("1.15")

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
    """Test VIX compression application."""

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

        # E_volVIX = 1.0 + (1.3 - 1.0) * 0.8333 = 1.25
        expected_E = Decimal("1.0") + (E_vol - Decimal("1.0")) * P_VIX
        assert abs(E_volVIX - expected_E) < Decimal("0.001")

    def test_high_vix_spike(self):
        """Test strong compression during VIX spike."""
        strategy = Hierarchical_Adaptive_v2(alpha_VIX=Decimal("1.0"))

        E_vol = Decimal("1.3")
        R_VIX = Decimal("2.0")  # VIX doubled

        P_VIX, E_volVIX = strategy._apply_vix_compression(E_vol, R_VIX)

        # P_VIX = 1 / (1 + 1.0 * (2.0 - 1.0)) = 1 / 2.0 = 0.5
        assert P_VIX == Decimal("0.5")

        # E_volVIX = 1.0 + (1.3 - 1.0) * 0.5 = 1.15
        assert E_volVIX == Decimal("1.15")

    def test_vix_equal_to_ema(self):
        """Test edge case when VIX equals EMA."""
        strategy = Hierarchical_Adaptive_v2(alpha_VIX=Decimal("1.0"))

        E_vol = Decimal("1.3")
        R_VIX = Decimal("1.0")  # VIX == VIX_EMA

        P_VIX, E_volVIX = strategy._apply_vix_compression(E_vol, R_VIX)

        assert P_VIX == Decimal("1.0")
        assert E_volVIX == Decimal("1.3")


class TestDrawdownGovernor:
    """Test drawdown governor application."""

    def test_no_drawdown(self):
        """Test no penalty when drawdown below DD_soft."""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.05")  # Below DD_soft

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("1.0")
        assert E_raw == Decimal("1.3")

    def test_moderate_drawdown(self):
        """Test linear compression between DD_soft and DD_hard."""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.15")  # Midpoint between soft and hard

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        # P_DD = 1.0 - ((0.15 - 0.10) / (0.20 - 0.10)) * (1.0 - 0.0)
        # P_DD = 1.0 - (0.05 / 0.10) * 1.0 = 1.0 - 0.5 = 0.5
        assert P_DD == Decimal("0.5")

        # E_raw = 1.0 + (1.3 - 1.0) * 0.5 = 1.15
        assert E_raw == Decimal("1.15")

    def test_severe_drawdown(self):
        """Test maximum penalty when drawdown exceeds DD_hard."""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.25")  # Beyond DD_hard

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("0.0")  # p_min
        # E_raw = 1.0 + (1.3 - 1.0) * 0.0 = 1.0
        assert E_raw == Decimal("1.0")

    def test_at_dd_soft_threshold(self):
        """Test edge case at DD_soft threshold."""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.10")  # Exactly at DD_soft

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("1.0")
        assert E_raw == Decimal("1.3")

    def test_at_dd_hard_threshold(self):
        """Test edge case at DD_hard threshold."""
        strategy = Hierarchical_Adaptive_v2(
            DD_soft=Decimal("0.10"),
            DD_hard=Decimal("0.20"),
            p_min=Decimal("0.0")
        )

        E_volVIX = Decimal("1.3")
        DD_current = Decimal("0.20")  # Exactly at DD_hard

        P_DD, E_raw = strategy._apply_drawdown_governor(E_volVIX, DD_current)

        assert P_DD == Decimal("0.0")
        assert E_raw == Decimal("1.0")


class TestExposureBounds:
    """Test final exposure clipping to bounds."""

    def test_exposure_within_bounds(self):
        """Test exposure already within bounds."""
        strategy = Hierarchical_Adaptive_v2(
            E_min=Decimal("0.5"),
            E_max=Decimal("1.3")
        )

        # Simulate on_bar processing (would normally clip E_raw)
        E_raw = Decimal("1.1")
        E_t = max(strategy.E_min, min(strategy.E_max, E_raw))

        assert E_t == Decimal("1.1")

    def test_exposure_clipped_to_max(self):
        """Test exposure clipped to E_max."""
        strategy = Hierarchical_Adaptive_v2(
            E_min=Decimal("0.5"),
            E_max=Decimal("1.3")
        )

        E_raw = Decimal("1.5")
        E_t = max(strategy.E_min, min(strategy.E_max, E_raw))

        assert E_t == Decimal("1.3")

    def test_exposure_clipped_to_min(self):
        """Test exposure clipped to E_min."""
        strategy = Hierarchical_Adaptive_v2(
            E_min=Decimal("0.5"),
            E_max=Decimal("1.3")
        )

        E_raw = Decimal("0.3")
        E_t = max(strategy.E_min, min(strategy.E_max, E_raw))

        assert E_t == Decimal("0.5")


class TestPositionMapping:
    """Test QQQ/TQQQ position mapping."""

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

    def test_minimum_exposure(self):
        """Test mapping at E_min (0.5)."""
        strategy = Hierarchical_Adaptive_v2()

        E_t = Decimal("0.5")
        w_QQQ, w_TQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        assert w_QQQ == Decimal("0.5")
        assert w_TQQQ == Decimal("0.0")
        assert w_cash == Decimal("0.5")

    def test_maximum_exposure(self):
        """Test mapping at E_max (1.3)."""
        strategy = Hierarchical_Adaptive_v2()

        E_t = Decimal("1.3")
        w_QQQ, w_TQQQ, w_cash = strategy._map_exposure_to_weights(E_t)

        assert w_TQQQ == Decimal("0.15")
        assert w_QQQ == Decimal("0.85")
        assert w_cash == Decimal("0.0")


class TestRebalancing:
    """Test rebalancing threshold and execution."""

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

    def test_rebalancing_at_threshold(self):
        """Test edge case at exact threshold."""
        strategy = Hierarchical_Adaptive_v2(rebalance_threshold=Decimal("0.025"))

        strategy.current_qqq_weight = Decimal("0.8375")
        strategy.current_tqqq_weight = Decimal("0.1625")

        target_qqq = Decimal("0.85")
        target_tqqq = Decimal("0.15")

        needs_rebalance = strategy._check_rebalancing_threshold(target_qqq, target_tqqq)

        # Deviation = |0.8375 - 0.85| + |0.1625 - 0.15| = 0.0125 + 0.0125 = 0.025 = 2.5%
        # Exactly at threshold, should NOT trigger (> not >=)
        assert not needs_rebalance


class TestDrawdownTracking:
    """Test drawdown tracking logic."""

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


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_insufficient_warmup_data(self):
        """Test strategy skips processing during warmup period."""
        strategy = Hierarchical_Adaptive_v2()
        strategy.init()

        # Create bar but not enough for warmup
        bar = MarketDataEvent(
            symbol="QQQ",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=Decimal("450.00"),
            high=Decimal("452.00"),
            low=Decimal("449.00"),
            close=Decimal("451.00"),
            volume=Decimal("1000000")
        )

        # Should not generate signals during warmup
        strategy._update_bar(bar)
        strategy.on_bar(bar)

        signals = strategy.get_signals()
        assert len(signals) == 0

    def test_non_signal_symbol_ignored(self):
        """Test bars for non-signal symbols are ignored."""
        strategy = Hierarchical_Adaptive_v2(signal_symbol="QQQ")
        strategy.init()

        # TQQQ bar should be ignored
        bar = MarketDataEvent(
            symbol="TQQQ",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=Decimal("50.00"),
            high=Decimal("51.00"),
            low=Decimal("49.00"),
            close=Decimal("50.50"),
            volume=Decimal("500000")
        )

        strategy._update_bar(bar)
        strategy.on_bar(bar)

        # Should not process TQQQ bars
        signals = strategy.get_signals()
        assert len(signals) == 0
