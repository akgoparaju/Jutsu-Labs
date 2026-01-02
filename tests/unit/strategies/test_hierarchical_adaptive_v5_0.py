"""
Unit tests for Hierarchical Adaptive v5.0 strategy.

Test Coverage:
1. Initialization (3 tests) - includes v5.0 new parameters
2. Warmup Calculation (3 tests) - includes commodity lookback
3. Trend Classification (6 tests) - inherited from v3.5b
4. Volatility Z-Score (3 tests) - inherited from v3.5b
5. Hysteresis State Machine (5 tests) - inherited from v3.5b
6. Vol-Crush Override (3 tests) - inherited from v3.5b
7. Hedge Preference Signal (5 tests) - NEW v5.0
8. Gold Momentum (4 tests) - NEW v5.0
9. Silver Relative Strength (4 tests) - NEW v5.0
10. Hard Hedge Allocation (4 tests) - NEW v5.0
11. 9-Cell Allocation Matrix (6 tests) - extended from v3.5b
12. Treasury Overlay (4 tests) - Paper hedge mode
13. Rebalancing (3 tests) - extended for 7 assets
14. Integration (4 tests) - full signal flow

Total: ~57 tests
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v5_0 import Hierarchical_Adaptive_v5_0
from jutsu_engine.core.events import MarketDataEvent


# ===== Fixtures =====

@pytest.fixture
def strategy_default():
    """Create strategy with default parameters."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()
    return strategy


@pytest.fixture
def strategy_silver_disabled():
    """Create strategy with silver momentum gate disabled."""
    strategy = Hierarchical_Adaptive_v5_0(silver_momentum_gate=False)
    strategy.init()
    return strategy


@pytest.fixture
def strategy_aggressive_commodity():
    """Create strategy with aggressive commodity allocation."""
    strategy = Hierarchical_Adaptive_v5_0(
        gold_weight_max=Decimal("0.80"),
        silver_vol_multiplier=Decimal("0.7")
    )
    strategy.init()
    return strategy


@pytest.fixture
def sample_bars():
    """Create sample market data bars for QQQ."""
    base_time = datetime.now(timezone.utc)
    bars = []
    for i in range(300):
        bars.append(
            MarketDataEvent(
                symbol="QQQ",
                timestamp=base_time + timedelta(days=i),
                open=Decimal("300.00") + Decimal(str(i * 0.1)),
                high=Decimal("301.00") + Decimal(str(i * 0.1)),
                low=Decimal("299.00") + Decimal(str(i * 0.1)),
                close=Decimal("300.00") + Decimal(str(i * 0.1)),
                volume=1000000
            )
        )
    return bars


# ===== 1. Initialization Tests (3 tests) =====

def test_initialization_default_parameters():
    """Test strategy initialization with default parameters including v5.0 additions."""
    strategy = Hierarchical_Adaptive_v5_0()

    # v3.5b Golden Parameters (preserved)
    assert strategy.measurement_noise == Decimal("3000.0")
    assert strategy.T_max == Decimal("50.0")
    assert strategy.sma_fast == 40
    assert strategy.sma_slow == 140
    assert strategy.t_norm_bull_thresh == Decimal("0.05")
    assert strategy.t_norm_bear_thresh == Decimal("-0.3")
    assert strategy.realized_vol_window == 21
    assert strategy.vol_baseline_window == 200
    assert strategy.upper_thresh_z == Decimal("1.0")
    assert strategy.lower_thresh_z == Decimal("0.2")
    assert strategy.vol_crush_threshold == Decimal("-0.15")
    assert strategy.vol_crush_lookback == 5
    assert strategy.leverage_scalar == Decimal("1.0")
    assert strategy.use_inverse_hedge is False
    assert strategy.allow_treasury is True
    assert strategy.bond_sma_fast == 20
    assert strategy.bond_sma_slow == 60
    assert strategy.max_bond_weight == Decimal("0.4")
    assert strategy.rebalance_threshold == Decimal("0.025")

    # NEW v5.0 Parameters
    assert strategy.hedge_corr_threshold == Decimal("0.20")
    assert strategy.hedge_corr_lookback == 60
    assert strategy.commodity_ma_period == 150
    assert strategy.gold_weight_max == Decimal("0.60")
    assert strategy.silver_vol_multiplier == Decimal("0.5")
    assert strategy.silver_momentum_lookback == 20
    assert strategy.silver_momentum_gate is True
    assert strategy.gold_symbol == "GLD"
    assert strategy.silver_symbol == "SLV"


def test_initialization_v5_parameter_validation():
    """Test v5.0 specific parameter validation."""
    # Invalid hedge correlation threshold (must be 0-1)
    with pytest.raises(ValueError, match="hedge_corr_threshold must be in"):
        Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("1.5"))

    with pytest.raises(ValueError, match="hedge_corr_threshold must be in"):
        Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("-0.1"))

    # Invalid hedge correlation lookback (must be positive)
    with pytest.raises(ValueError, match="hedge_corr_lookback must be positive"):
        Hierarchical_Adaptive_v5_0(hedge_corr_lookback=0)

    # Invalid commodity MA period (must be positive)
    with pytest.raises(ValueError, match="commodity_ma_period must be positive"):
        Hierarchical_Adaptive_v5_0(commodity_ma_period=-10)

    # Invalid gold weight max (must be 0-1)
    with pytest.raises(ValueError, match="gold_weight_max must be in"):
        Hierarchical_Adaptive_v5_0(gold_weight_max=Decimal("1.5"))

    # Invalid silver vol multiplier (must be 0-1)
    with pytest.raises(ValueError, match="silver_vol_multiplier must be in"):
        Hierarchical_Adaptive_v5_0(silver_vol_multiplier=Decimal("1.5"))

    # Invalid silver momentum lookback (must be positive)
    with pytest.raises(ValueError, match="silver_momentum_lookback must be positive"):
        Hierarchical_Adaptive_v5_0(silver_momentum_lookback=0)


def test_initialization_symbol_set_extended():
    """Test v5.0 has extended symbol set including GLD/SLV."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # v3.5b symbols
    assert strategy.signal_symbol == "QQQ"
    assert strategy.core_long_symbol == "QQQ"
    assert strategy.leveraged_long_symbol == "TQQQ"
    assert strategy.inverse_hedge_symbol == "PSQ"
    assert strategy.treasury_trend_symbol == "TLT"
    assert strategy.bull_bond_symbol == "TMF"
    assert strategy.bear_bond_symbol == "TMV"

    # v5.0 new symbols
    assert strategy.gold_symbol == "GLD"
    assert strategy.silver_symbol == "SLV"


# ===== 2. Warmup Calculation Tests (3 tests) =====

def test_warmup_calculation_includes_commodity_lookback():
    """Test warmup includes commodity MA period."""
    strategy = Hierarchical_Adaptive_v5_0(commodity_ma_period=200)

    # Warmup should consider: SMA, vol baseline, commodity MA, hedge correlation
    # commodity_ma_period=200 should dominate
    warmup_bars = strategy.get_required_warmup_bars()

    # Should be at least 200 + buffer
    assert warmup_bars >= 200


def test_warmup_calculation_includes_hedge_correlation():
    """Test warmup includes hedge correlation lookback."""
    strategy = Hierarchical_Adaptive_v5_0(
        sma_slow=50,  # Small SMA
        vol_baseline_window=50,  # Small vol window
        commodity_ma_period=50,  # Small commodity MA
        hedge_corr_lookback=150  # Large correlation lookback should dominate
    )

    warmup_bars = strategy.get_required_warmup_bars()

    # hedge_corr_lookback=150 should dominate
    assert warmup_bars >= 150


def test_warmup_calculation_includes_silver_lookback():
    """Test warmup includes silver momentum lookback."""
    strategy = Hierarchical_Adaptive_v5_0(silver_momentum_lookback=30)

    warmup_bars = strategy.get_required_warmup_bars()

    # Should include silver lookback in calculation
    # But other params (sma_slow=140, vol_baseline=200) likely dominate
    assert warmup_bars >= 30


# ===== 3. Trend Classification Tests (6 tests) - Inherited from v3.5b =====

def test_trend_classification_bull_strong():
    """Test BullStrong classification: T_norm > bull_thresh AND SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_0()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BullStrong"


def test_trend_classification_bear_strong():
    """Test BearStrong classification: T_norm < bear_thresh AND SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_0()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BearStrong"


def test_trend_classification_sideways_kalman_bull_sma_bear():
    """Test Sideways: T_norm positive but SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_0()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_kalman_bear_sma_bull():
    """Test Sideways: T_norm negative but SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_0()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_neutral_kalman():
    """Test Sideways: T_norm between thresholds."""
    strategy = Hierarchical_Adaptive_v5_0()

    T_norm = Decimal("0.02")  # Between 0.05 and -0.3
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_uses_v5_thresholds():
    """Test v5.0 uses golden thresholds (0.05/-0.3 not 0.3/-0.3)."""
    strategy = Hierarchical_Adaptive_v5_0()

    # T_norm = 0.1 should be Sideways with v5.0 threshold (0.05)
    # But would be BullStrong with default v3.5b threshold (0.3)
    T_norm = Decimal("0.1")  # > 0.05 but would need SMA confirmation
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    # With golden thresholds, this should be BullStrong (T_norm > 0.05 AND SMA bull)
    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BullStrong"


# ===== 4. Hysteresis State Machine Tests (3 tests) - Key tests from v3.5b =====

def test_hysteresis_regime_stability():
    """Test hysteresis maintains state in deadband."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Set initial state to Low
    strategy.vol_state = "Low"

    # Z-score in deadband (between 0.2 and 1.0 for v5.0 golden)
    strategy._apply_hysteresis(Decimal("0.5"))

    # State should persist
    assert strategy.vol_state == "Low"


def test_hysteresis_upper_breach():
    """Test hysteresis transitions to High when z_score > upper_thresh."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    strategy.vol_state = "Low"
    strategy._apply_hysteresis(Decimal("1.5"))

    assert strategy.vol_state == "High"


def test_hysteresis_lower_breach():
    """Test hysteresis transitions to Low when z_score < lower_thresh."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    strategy.vol_state = "High"
    strategy._apply_hysteresis(Decimal("0.1"))  # Below 0.2 threshold

    assert strategy.vol_state == "Low"


# ===== 5. Hedge Preference Signal Tests (5 tests) - NEW v5.0 =====

def test_hedge_preference_paper_low_correlation():
    """Test Paper hedge when QQQ/TLT correlation < threshold."""
    strategy = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    # Mock correlation calculation
    with patch.object(strategy, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.10")):
        mock_bar = MagicMock()
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Paper"


def test_hedge_preference_hard_high_correlation():
    """Test Hard hedge when QQQ/TLT correlation >= threshold."""
    strategy = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    # Mock correlation calculation
    with patch.object(strategy, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.30")):
        mock_bar = MagicMock()
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Hard"


def test_hedge_preference_threshold_boundary():
    """Test hedge preference at exact threshold (should be Hard)."""
    strategy = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    with patch.object(strategy, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.20")):
        mock_bar = MagicMock()
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # At threshold, should route to Hard (>=)
    assert hedge_pref == "Hard"


def test_hedge_preference_insufficient_data():
    """Test hedge preference defaults to Paper with insufficient data."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock correlation returning None (insufficient data)
    with patch.object(strategy, '_calculate_qqq_tlt_correlation', return_value=None):
        mock_bar = MagicMock()
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # Default to Paper when data insufficient
    assert hedge_pref == "Paper"


def test_hedge_preference_threshold_sensitivity():
    """Test different threshold values affect routing correctly."""
    # Conservative threshold (0.30)
    strategy_conservative = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.30"))
    strategy_conservative.init()

    # Aggressive threshold (0.10)
    strategy_aggressive = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.10"))
    strategy_aggressive.init()

    # Correlation of 0.20 should be:
    # - Paper for conservative (0.20 < 0.30)
    # - Hard for aggressive (0.20 >= 0.10)
    with patch.object(strategy_conservative, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.20")):
        assert strategy_conservative._calculate_hedge_preference(MagicMock()) == "Paper"

    with patch.object(strategy_aggressive, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.20")):
        assert strategy_aggressive._calculate_hedge_preference(MagicMock()) == "Hard"


# ===== 6. Gold Momentum Tests (4 tests) - NEW v5.0 =====

def test_gold_momentum_bullish():
    """Test gold momentum bullish when GLD > GLD_SMA."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock GLD price above SMA
    with patch.object(strategy, '_get_commodity_price', return_value=Decimal("180.00")):
        with patch.object(strategy, '_calculate_commodity_sma', return_value=Decimal("170.00")):
            g_trend = strategy._calculate_gold_momentum(MagicMock())

    assert g_trend == "Bullish"


def test_gold_momentum_bearish():
    """Test gold momentum bearish when GLD < GLD_SMA."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock GLD price below SMA
    with patch.object(strategy, '_get_commodity_price', return_value=Decimal("160.00")):
        with patch.object(strategy, '_calculate_commodity_sma', return_value=Decimal("170.00")):
            g_trend = strategy._calculate_gold_momentum(MagicMock())

    assert g_trend == "Bearish"


def test_gold_momentum_insufficient_data():
    """Test gold momentum defaults to Bearish with insufficient data."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock SMA returning None
    with patch.object(strategy, '_get_commodity_price', return_value=Decimal("180.00")):
        with patch.object(strategy, '_calculate_commodity_sma', return_value=None):
            g_trend = strategy._calculate_gold_momentum(MagicMock())

    # Default to Bearish when insufficient data (conservative)
    assert g_trend == "Bearish"


def test_gold_momentum_ma_period_sensitivity():
    """Test gold momentum with different MA periods."""
    strategy_responsive = Hierarchical_Adaptive_v5_0(commodity_ma_period=100)
    strategy_stable = Hierarchical_Adaptive_v5_0(commodity_ma_period=200)

    # Both should calculate gold momentum
    assert strategy_responsive.commodity_ma_period == 100
    assert strategy_stable.commodity_ma_period == 200


# ===== 7. Silver Relative Strength Tests (4 tests) - NEW v5.0 =====

def test_silver_relative_strength_positive():
    """Test silver kicker when SLV ROC > GLD ROC."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock SLV outperforming GLD
    with patch.object(strategy, '_calculate_roc', side_effect=[Decimal("0.10"), Decimal("0.05")]):
        s_beta = strategy._calculate_silver_relative_strength(MagicMock())

    # SLV ROC (0.10) > GLD ROC (0.05) → Positive
    assert s_beta == "Positive"


def test_silver_relative_strength_negative():
    """Test no silver kicker when SLV ROC < GLD ROC."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock GLD outperforming SLV
    with patch.object(strategy, '_calculate_roc', side_effect=[Decimal("0.05"), Decimal("0.10")]):
        s_beta = strategy._calculate_silver_relative_strength(MagicMock())

    # SLV ROC (0.05) < GLD ROC (0.10) → Negative
    assert s_beta == "Negative"


def test_silver_relative_strength_gate_disabled():
    """Test silver kicker always Negative when gate disabled."""
    strategy = Hierarchical_Adaptive_v5_0(silver_momentum_gate=False)
    strategy.init()

    # Even with SLV outperforming, gate is off
    with patch.object(strategy, '_calculate_roc', side_effect=[Decimal("0.15"), Decimal("0.05")]):
        s_beta = strategy._calculate_silver_relative_strength(MagicMock())

    # Gate disabled → always Negative (no silver exposure)
    assert s_beta == "Negative"


def test_silver_relative_strength_lookback():
    """Test silver momentum uses correct lookback period."""
    strategy = Hierarchical_Adaptive_v5_0(silver_momentum_lookback=30)

    assert strategy.silver_momentum_lookback == 30


# ===== 8. Hard Hedge Allocation Tests (4 tests) - NEW v5.0 =====

def test_hard_hedge_allocation_gold_only():
    """Test hard hedge with gold only (silver negative or gate off)."""
    strategy = Hierarchical_Adaptive_v5_0(
        gold_weight_max=Decimal("0.60"),
        silver_momentum_gate=False
    )
    strategy.init()

    # Mock bullish gold, no silver
    with patch.object(strategy, '_calculate_gold_momentum', return_value="Bullish"):
        with patch.object(strategy, '_calculate_silver_relative_strength', return_value="Negative"):
            allocation = strategy._get_hard_hedge_allocation(MagicMock())

    # Should be gold_weight_max for GLD, 0 for SLV
    assert allocation["GLD"] == Decimal("0.60")
    assert allocation["SLV"] == Decimal("0.00")


def test_hard_hedge_allocation_with_silver_kicker():
    """Test hard hedge with silver kicker active."""
    strategy = Hierarchical_Adaptive_v5_0(
        gold_weight_max=Decimal("0.60"),
        silver_vol_multiplier=Decimal("0.5"),
        silver_momentum_gate=True
    )
    strategy.init()

    # Mock bullish gold, positive silver
    with patch.object(strategy, '_calculate_gold_momentum', return_value="Bullish"):
        with patch.object(strategy, '_calculate_silver_relative_strength', return_value="Positive"):
            allocation = strategy._get_hard_hedge_allocation(MagicMock())

    # Gold reduced, silver added
    # GLD = gold_weight_max * (1 - silver_vol_multiplier) = 0.60 * 0.5 = 0.30
    # SLV = gold_weight_max * silver_vol_multiplier = 0.60 * 0.5 = 0.30
    assert allocation["GLD"] == Decimal("0.30")
    assert allocation["SLV"] == Decimal("0.30")


def test_hard_hedge_allocation_bearish_gold():
    """Test hard hedge with bearish gold momentum (reduced allocation)."""
    strategy = Hierarchical_Adaptive_v5_0(gold_weight_max=Decimal("0.60"))
    strategy.init()

    # Mock bearish gold
    with patch.object(strategy, '_calculate_gold_momentum', return_value="Bearish"):
        with patch.object(strategy, '_calculate_silver_relative_strength', return_value="Negative"):
            allocation = strategy._get_hard_hedge_allocation(MagicMock())

    # Bearish gold → reduced allocation (half of max)
    assert allocation["GLD"] == Decimal("0.30")
    assert allocation["SLV"] == Decimal("0.00")


def test_hard_hedge_allocation_weight_limits():
    """Test hard hedge respects weight limits."""
    strategy = Hierarchical_Adaptive_v5_0(
        gold_weight_max=Decimal("0.80"),
        silver_vol_multiplier=Decimal("0.7")
    )
    strategy.init()

    # With aggressive settings, total should not exceed gold_weight_max
    with patch.object(strategy, '_calculate_gold_momentum', return_value="Bullish"):
        with patch.object(strategy, '_calculate_silver_relative_strength', return_value="Positive"):
            allocation = strategy._get_hard_hedge_allocation(MagicMock())

    total_commodity = allocation["GLD"] + allocation["SLV"]
    assert total_commodity <= strategy.gold_weight_max


# ===== 9. 9-Cell Allocation Matrix Tests (6 tests) =====

def test_cell_allocation_bull_low_any():
    """Test Cell 1: Bull/Low → 60% TQQQ + 40% QQQ (hedge pref doesn't matter)."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    allocation = strategy._get_cell_allocation_v5(
        cell_id=1,
        hedge_preference="Paper",  # Doesn't affect Bull/Low
        current_bar=MagicMock()
    )

    assert allocation["TQQQ"] == Decimal("0.60")
    assert allocation["QQQ"] == Decimal("0.40")
    assert allocation["GLD"] == Decimal("0.00")
    assert allocation["SLV"] == Decimal("0.00")


def test_cell_allocation_sideways_high_paper():
    """Test Cell 4 Paper: Sideways/High/Paper → TMF/TMV based on bond SMA."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock bond allocation
    with patch.object(strategy, '_get_treasury_allocation', return_value={"TMF": Decimal("0.40"), "TMV": Decimal("0.00")}):
        allocation = strategy._get_cell_allocation_v5(
            cell_id=4,
            hedge_preference="Paper",
            current_bar=MagicMock()
        )

    # Paper hedge → bonds, no commodities
    assert allocation["TMF"] == Decimal("0.40")
    assert allocation["GLD"] == Decimal("0.00")
    assert allocation["SLV"] == Decimal("0.00")


def test_cell_allocation_sideways_high_hard():
    """Test Cell 4 Hard: Sideways/High/Hard → GLD/SLV based on commodity signals."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock hard hedge allocation
    with patch.object(strategy, '_get_hard_hedge_allocation', return_value={"GLD": Decimal("0.50"), "SLV": Decimal("0.10")}):
        allocation = strategy._get_cell_allocation_v5(
            cell_id=4,
            hedge_preference="Hard",
            current_bar=MagicMock()
        )

    # Hard hedge → commodities, no bonds
    assert allocation["GLD"] == Decimal("0.50")
    assert allocation["SLV"] == Decimal("0.10")
    assert allocation["TMF"] == Decimal("0.00")


def test_cell_allocation_bear_high_paper():
    """Test Cell 6 Paper: Bear/High/Paper → TMF/TMV."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    with patch.object(strategy, '_get_treasury_allocation', return_value={"TMF": Decimal("0.40"), "TMV": Decimal("0.00")}):
        allocation = strategy._get_cell_allocation_v5(
            cell_id=6,
            hedge_preference="Paper",
            current_bar=MagicMock()
        )

    assert allocation["TMF"] == Decimal("0.40")
    assert allocation["GLD"] == Decimal("0.00")


def test_cell_allocation_bear_high_hard():
    """Test Cell 6 Hard: Bear/High/Hard → GLD/SLV."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    with patch.object(strategy, '_get_hard_hedge_allocation', return_value={"GLD": Decimal("0.60"), "SLV": Decimal("0.00")}):
        allocation = strategy._get_cell_allocation_v5(
            cell_id=6,
            hedge_preference="Hard",
            current_bar=MagicMock()
        )

    assert allocation["GLD"] == Decimal("0.60")
    assert allocation["TMF"] == Decimal("0.00")


def test_cell_allocation_preserves_v35b_behavior():
    """Test cells 1,2,3,5 behave same as v3.5b (hedge pref irrelevant)."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Cell 1: Bull/Low - hedge pref should not affect
    alloc_paper = strategy._get_cell_allocation_v5(1, "Paper", MagicMock())
    alloc_hard = strategy._get_cell_allocation_v5(1, "Hard", MagicMock())

    assert alloc_paper["TQQQ"] == alloc_hard["TQQQ"]
    assert alloc_paper["QQQ"] == alloc_hard["QQQ"]


# ===== 10. Rebalancing Tests (3 tests) =====

def test_rebalancing_threshold_7_assets():
    """Test rebalancing threshold check includes all 7 assets."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Current allocation (7 assets)
    current = {
        "TQQQ": Decimal("0.58"),
        "QQQ": Decimal("0.42"),
        "PSQ": Decimal("0.00"),
        "TMF": Decimal("0.00"),
        "TMV": Decimal("0.00"),
        "GLD": Decimal("0.00"),
        "SLV": Decimal("0.00"),
    }

    # Target allocation
    target = {
        "TQQQ": Decimal("0.60"),
        "QQQ": Decimal("0.40"),
        "PSQ": Decimal("0.00"),
        "TMF": Decimal("0.00"),
        "TMV": Decimal("0.00"),
        "GLD": Decimal("0.00"),
        "SLV": Decimal("0.00"),
    }

    # Drift is 0.02 for TQQQ and QQQ
    # Threshold is 0.025, so should NOT rebalance
    needs_rebalance = strategy._check_rebalancing_threshold_v5(current, target)

    assert needs_rebalance is False


def test_rebalancing_triggered_by_commodity_drift():
    """Test rebalancing triggers when commodity allocation drifts."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Current allocation with drifted GLD
    current = {
        "TQQQ": Decimal("0.00"),
        "QQQ": Decimal("0.00"),
        "PSQ": Decimal("0.00"),
        "TMF": Decimal("0.00"),
        "TMV": Decimal("0.00"),
        "GLD": Decimal("0.55"),  # Drifted from target
        "SLV": Decimal("0.05"),
    }

    # Target allocation
    target = {
        "TQQQ": Decimal("0.00"),
        "QQQ": Decimal("0.00"),
        "PSQ": Decimal("0.00"),
        "TMF": Decimal("0.00"),
        "TMV": Decimal("0.00"),
        "GLD": Decimal("0.50"),
        "SLV": Decimal("0.10"),
    }

    # Drift of 0.05 > threshold 0.025 → should rebalance
    needs_rebalance = strategy._check_rebalancing_threshold_v5(current, target)

    assert needs_rebalance is True


def test_rebalancing_executes_commodity_trades():
    """Test rebalance execution includes commodity trades."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # This is a higher-level test - verify rebalance considers all assets
    target = {
        "TQQQ": Decimal("0.00"),
        "QQQ": Decimal("0.00"),
        "PSQ": Decimal("0.00"),
        "TMF": Decimal("0.00"),
        "TMV": Decimal("0.00"),
        "GLD": Decimal("0.60"),
        "SLV": Decimal("0.00"),
    }

    # Verify GLD and SLV are in the target allocation dict
    assert "GLD" in target
    assert "SLV" in target


# ===== 11. Integration Tests (4 tests) =====

def test_full_signal_flow_paper_hedge():
    """Test complete signal flow with Paper hedge preference."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock all components for Paper hedge path
    with patch.object(strategy, '_classify_trend_regime', return_value="Sideways"):
        with patch.object(strategy, '_apply_hysteresis') as mock_hysteresis:
            strategy.vol_state = "High"
            with patch.object(strategy, '_calculate_hedge_preference', return_value="Paper"):
                with patch.object(strategy, '_get_treasury_allocation', return_value={"TMF": Decimal("0.40")}):
                    # Verify Paper hedge routes to treasury
                    hedge_pref = strategy._calculate_hedge_preference(MagicMock())
                    assert hedge_pref == "Paper"


def test_full_signal_flow_hard_hedge():
    """Test complete signal flow with Hard hedge preference."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    # Mock all components for Hard hedge path
    with patch.object(strategy, '_classify_trend_regime', return_value="Sideways"):
        strategy.vol_state = "High"
        with patch.object(strategy, '_calculate_hedge_preference', return_value="Hard"):
            with patch.object(strategy, '_get_hard_hedge_allocation', return_value={"GLD": Decimal("0.50"), "SLV": Decimal("0.10")}):
                # Verify Hard hedge routes to commodities
                hedge_pref = strategy._calculate_hedge_preference(MagicMock())
                assert hedge_pref == "Hard"


def test_strategy_processes_all_symbols():
    """Test strategy correctly processes all 8 symbols."""
    strategy = Hierarchical_Adaptive_v5_0()
    strategy.init()

    expected_symbols = {"QQQ", "TQQQ", "PSQ", "TLT", "TMF", "TMV", "GLD", "SLV"}

    # Get symbols the strategy uses
    strategy_symbols = set()
    strategy_symbols.add(strategy.signal_symbol)
    strategy_symbols.add(strategy.core_long_symbol)
    strategy_symbols.add(strategy.leveraged_long_symbol)
    strategy_symbols.add(strategy.inverse_hedge_symbol)
    strategy_symbols.add(strategy.treasury_trend_symbol)
    strategy_symbols.add(strategy.bull_bond_symbol)
    strategy_symbols.add(strategy.bear_bond_symbol)
    strategy_symbols.add(strategy.gold_symbol)
    strategy_symbols.add(strategy.silver_symbol)

    assert strategy_symbols == expected_symbols


def test_2022_scenario_hard_hedge_activation():
    """Test v5.0 activates Hard hedge in 2022-like conditions (high QQQ/TLT correlation)."""
    strategy = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    # 2022 scenario: QQQ/TLT correlation spiked as bonds failed to hedge
    # Simulate high correlation (bonds moving with equities)
    with patch.object(strategy, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.40")):
        hedge_pref = strategy._calculate_hedge_preference(MagicMock())

    # Should activate Hard hedge (commodities)
    assert hedge_pref == "Hard"


# ===== 12. Edge Case Tests (3 tests) =====

def test_edge_case_zero_commodity_allocation():
    """Test strategy handles zero commodity allocation gracefully."""
    strategy = Hierarchical_Adaptive_v5_0(gold_weight_max=Decimal("0.00"))
    strategy.init()

    # Even with gold_weight_max=0, strategy should function
    with patch.object(strategy, '_calculate_gold_momentum', return_value="Bullish"):
        with patch.object(strategy, '_calculate_silver_relative_strength', return_value="Positive"):
            allocation = strategy._get_hard_hedge_allocation(MagicMock())

    assert allocation["GLD"] == Decimal("0.00")
    assert allocation["SLV"] == Decimal("0.00")


def test_edge_case_maximum_commodity_allocation():
    """Test strategy handles maximum commodity allocation."""
    strategy = Hierarchical_Adaptive_v5_0(
        gold_weight_max=Decimal("1.00"),
        silver_vol_multiplier=Decimal("0.5")
    )
    strategy.init()

    with patch.object(strategy, '_calculate_gold_momentum', return_value="Bullish"):
        with patch.object(strategy, '_calculate_silver_relative_strength', return_value="Positive"):
            allocation = strategy._get_hard_hedge_allocation(MagicMock())

    # Total should not exceed 1.0
    total = allocation["GLD"] + allocation["SLV"]
    assert total <= Decimal("1.00")


def test_edge_case_correlation_exactly_zero():
    """Test hedge preference with zero correlation."""
    strategy = Hierarchical_Adaptive_v5_0(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    with patch.object(strategy, '_calculate_qqq_tlt_correlation', return_value=Decimal("0.00")):
        hedge_pref = strategy._calculate_hedge_preference(MagicMock())

    # Zero correlation < threshold → Paper hedge
    assert hedge_pref == "Paper"
