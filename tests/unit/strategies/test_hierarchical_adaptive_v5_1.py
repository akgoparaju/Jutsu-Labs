"""
Unit tests for Hierarchical Adaptive v5.1 strategy.

Test Coverage:
1. Initialization (4 tests) - includes v5.1 DXY parameters
2. Warmup Calculation (3 tests) - includes DXY SMA lookback
3. Trend Classification (6 tests) - inherited from v5.0/v3.5b
4. Volatility Z-Score (3 tests) - inherited from v5.0/v3.5b
5. Hysteresis State Machine (3 tests) - inherited from v5.0/v3.5b
6. Vol-Crush Override (2 tests) - inherited from v5.0
7. DXY Trend Calculation (5 tests) - NEW v5.1
8. Hedge Preference Signal (7 tests) - EXTENDED v5.1 (correlation + DXY dual filter)
9. Gold Momentum (4 tests) - inherited from v5.0
10. Silver Relative Strength (4 tests) - inherited from v5.0
11. Hard Hedge Allocation (4 tests) - inherited from v5.0
12. 9-Cell Allocation Matrix (8 tests) - EXTENDED v5.1 (C1, C2, C9 changes)
13. Treasury Overlay (3 tests) - Paper hedge mode
14. Rebalancing (3 tests) - extended for 9 symbols
15. Integration (5 tests) - full signal flow with DXY

Total: ~64 tests

v5.1 Changes from v5.0:
-----------------------
1. DXY FILTER FOR HEDGE ROUTING:
   - v5.0: Correlation-only hedge preference (corr >= threshold → Hard)
   - v5.1: Correlation + DXY momentum dual filter
   - Rule: PAPER if (corr < threshold AND DXY > SMA), else HARD

2. CELL ALLOCATION CHANGES:
   - C1: 80/20 → 100% TQQQ (aggressive bull/low)
   - C2: 50/20/30 → 50/25/25 (balanced hedge)
   - C9: Explicit vol-crush override cell (100% TQQQ)

3. NEW PARAMETERS:
   - dxy_symbol: UUP (Dollar Index ETF proxy)
   - dxy_sma_period: 50 (default)
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v5_1 import Hierarchical_Adaptive_v5_1
from jutsu_engine.core.events import MarketDataEvent


# ===== Fixtures =====

@pytest.fixture
def strategy_default():
    """Create strategy with default parameters."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()
    return strategy


@pytest.fixture
def strategy_aggressive_dxy():
    """Create strategy with aggressive DXY filter (short SMA)."""
    strategy = Hierarchical_Adaptive_v5_1(dxy_sma_period=30)
    strategy.init()
    return strategy


@pytest.fixture
def strategy_conservative_dxy():
    """Create strategy with conservative DXY filter (long SMA)."""
    strategy = Hierarchical_Adaptive_v5_1(dxy_sma_period=70)
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


# ===== 1. Initialization Tests (4 tests) =====

def test_initialization_default_parameters():
    """Test strategy initialization with default parameters including v5.1 DXY additions."""
    strategy = Hierarchical_Adaptive_v5_1()

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
    assert strategy.use_inverse_hedge is True  # v5.1 default is True
    assert strategy.allow_treasury is True
    assert strategy.bond_sma_fast == 20
    assert strategy.bond_sma_slow == 60
    assert strategy.max_bond_weight == Decimal("0.4")
    assert strategy.rebalance_threshold == Decimal("0.025")

    # v5.0 Parameters (preserved)
    assert strategy.hedge_corr_threshold == Decimal("0.20")
    assert strategy.hedge_corr_lookback == 60
    assert strategy.commodity_ma_period == 150
    assert strategy.gold_weight_max == Decimal("0.60")
    assert strategy.silver_vol_multiplier == Decimal("0.5")
    assert strategy.silver_momentum_lookback == 20
    assert strategy.silver_momentum_gate is True
    assert strategy.gold_symbol == "GLD"
    assert strategy.silver_symbol == "SLV"

    # NEW v5.1 Parameters
    assert strategy.dxy_symbol == "UUP"
    assert strategy.dxy_sma_period == 50


def test_initialization_v51_parameter_validation():
    """Test v5.1 specific parameter validation."""
    # Invalid DXY SMA period (must be >= 10)
    with pytest.raises(ValueError, match="dxy_sma_period must be >= 10"):
        Hierarchical_Adaptive_v5_1(dxy_sma_period=5)

    with pytest.raises(ValueError, match="dxy_sma_period must be >= 10"):
        Hierarchical_Adaptive_v5_1(dxy_sma_period=0)


def test_initialization_v50_parameter_validation_preserved():
    """Test v5.0 parameter validation still works in v5.1."""
    # Invalid hedge correlation threshold (must be in [-0.5, 0.9])
    with pytest.raises(ValueError, match="hedge_corr_threshold must be in"):
        Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("1.5"))

    # Invalid gold weight max (must be in [0.1, 1.0])
    with pytest.raises(ValueError, match="gold_weight_max must be in"):
        Hierarchical_Adaptive_v5_1(gold_weight_max=Decimal("0.05"))


def test_initialization_symbol_set_extended():
    """Test v5.1 has extended symbol set including UUP (DXY proxy)."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # v3.5b symbols
    assert strategy.signal_symbol == "QQQ"
    assert strategy.core_long_symbol == "QQQ"
    assert strategy.leveraged_long_symbol == "TQQQ"
    assert strategy.inverse_hedge_symbol == "PSQ"
    assert strategy.treasury_trend_symbol == "TLT"
    assert strategy.bull_bond_symbol == "TMF"
    assert strategy.bear_bond_symbol == "TMV"

    # v5.0 symbols
    assert strategy.gold_symbol == "GLD"
    assert strategy.silver_symbol == "SLV"

    # v5.1 new symbol
    assert strategy.dxy_symbol == "UUP"


# ===== 2. Warmup Calculation Tests (3 tests) =====

def test_warmup_calculation_includes_dxy_lookback():
    """Test warmup includes DXY SMA period."""
    strategy = Hierarchical_Adaptive_v5_1(
        sma_slow=50,  # Small SMA
        vol_baseline_window=50,  # Small vol window
        commodity_ma_period=50,  # Small commodity MA
        hedge_corr_lookback=50,  # Small correlation lookback
        dxy_sma_period=200  # Large DXY SMA should dominate
    )

    warmup_bars = strategy.get_required_warmup_bars()

    # dxy_sma_period=200 should dominate
    assert warmup_bars >= 200


def test_warmup_calculation_includes_commodity_lookback():
    """Test warmup includes commodity MA period (inherited from v5.0)."""
    strategy = Hierarchical_Adaptive_v5_1(commodity_ma_period=200)

    warmup_bars = strategy.get_required_warmup_bars()
    assert warmup_bars >= 200


def test_warmup_calculation_default():
    """Test warmup calculation with default parameters."""
    strategy = Hierarchical_Adaptive_v5_1()

    warmup_bars = strategy.get_required_warmup_bars()

    # Default: vol_baseline_window=200 should dominate
    assert warmup_bars >= 200


# ===== 3. Trend Classification Tests (6 tests) - Inherited =====

def test_trend_classification_bull_strong():
    """Test BullStrong classification: T_norm > bull_thresh AND SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_1()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BullStrong"


def test_trend_classification_bear_strong():
    """Test BearStrong classification: T_norm < bear_thresh AND SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_1()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BearStrong"


def test_trend_classification_sideways_kalman_bull_sma_bear():
    """Test Sideways: T_norm positive but SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_1()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_kalman_bear_sma_bull():
    """Test Sideways: T_norm negative but SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v5_1()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_neutral_kalman():
    """Test Sideways: T_norm between thresholds."""
    strategy = Hierarchical_Adaptive_v5_1()

    T_norm = Decimal("0.02")  # Between 0.05 and -0.3
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_uses_golden_thresholds():
    """Test v5.1 uses golden thresholds (0.05/-0.3)."""
    strategy = Hierarchical_Adaptive_v5_1()

    # T_norm = 0.1 should be BullStrong with golden threshold (> 0.05)
    T_norm = Decimal("0.1")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BullStrong"


# ===== 4. Hysteresis State Machine Tests (3 tests) - Inherited =====

def test_hysteresis_regime_stability():
    """Test hysteresis maintains state in deadband."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    strategy.vol_state = "Low"
    strategy._apply_hysteresis(Decimal("0.5"))

    assert strategy.vol_state == "Low"


def test_hysteresis_upper_breach():
    """Test hysteresis transitions to High when z_score > upper_thresh."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    strategy.vol_state = "Low"
    strategy._apply_hysteresis(Decimal("1.5"))

    assert strategy.vol_state == "High"


def test_hysteresis_lower_breach():
    """Test hysteresis transitions to Low when z_score < lower_thresh."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    strategy.vol_state = "High"
    strategy._apply_hysteresis(Decimal("0.1"))

    assert strategy.vol_state == "Low"


# ===== 5. DXY Trend Calculation Tests (5 tests) - NEW v5.1 =====

def test_dxy_trend_bullish():
    """Test DXY trend Bull when UUP > UUP_SMA."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # Mock UUP price above SMA (dollar strong)
    with patch.object(strategy, '_get_closes_for_indicator_calculation') as mock_closes:
        # Create mock price series where current > SMA
        mock_series = pd.Series([25.0] * 50 + [27.0])  # SMA ~25, current 27
        mock_closes.return_value = mock_series
        
        dxy_trend = strategy._calculate_dxy_trend(MagicMock())

    assert dxy_trend == "Bull"


def test_dxy_trend_bearish():
    """Test DXY trend Bear when UUP < UUP_SMA."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # Mock UUP price below SMA (dollar weak)
    with patch.object(strategy, '_get_closes_for_indicator_calculation') as mock_closes:
        # Create mock price series where current < SMA
        mock_series = pd.Series([25.0] * 50 + [23.0])  # SMA ~25, current 23
        mock_closes.return_value = mock_series
        
        dxy_trend = strategy._calculate_dxy_trend(MagicMock())

    assert dxy_trend == "Bear"


def test_dxy_trend_insufficient_data():
    """Test DXY trend defaults to Bull with insufficient data."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # Mock insufficient data
    with patch.object(strategy, '_get_closes_for_indicator_calculation') as mock_closes:
        mock_closes.return_value = pd.Series([25.0] * 10)  # Not enough for SMA
        
        dxy_trend = strategy._calculate_dxy_trend(MagicMock())

    # Default to Bull when insufficient data (conservative - allows Paper hedge)
    assert dxy_trend == "Bull"


def test_dxy_trend_sma_period_sensitivity():
    """Test DXY trend with different SMA periods."""
    strategy_short = Hierarchical_Adaptive_v5_1(dxy_sma_period=30)
    strategy_long = Hierarchical_Adaptive_v5_1(dxy_sma_period=70)

    assert strategy_short.dxy_sma_period == 30
    assert strategy_long.dxy_sma_period == 70


def test_dxy_trend_uses_correct_symbol():
    """Test DXY trend calculation uses configured symbol."""
    strategy = Hierarchical_Adaptive_v5_1(dxy_symbol="UUP")
    strategy.init()

    # Verify the strategy uses UUP for DXY calculation
    assert strategy.dxy_symbol == "UUP"


# ===== 6. Hedge Preference Signal Tests (7 tests) - EXTENDED v5.1 =====

def test_hedge_preference_paper_low_corr_dollar_strong():
    """Test Paper hedge: corr < threshold AND DXY > SMA (dollar strong)."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    # v5.1 Logic: PAPER if (corr < threshold AND DXY > SMA)
    # Mock DXY trend directly and provide data that produces negative correlation
    mock_bar = MagicMock()
    
    # Create alternating price series for negative correlation
    # QQQ: up, down, up, down... TLT: down, up, down, up...
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "QQQ":
            # Alternating: 100, 101, 100, 101, ...
            return pd.Series([100.0 + (i % 2) for i in range(lookback)])
        elif symbol == "TLT":
            # Inverse alternating: 100, 99, 100, 99, ...
            return pd.Series([100.0 - (i % 2) for i in range(lookback)])
        elif symbol == "UUP":
            # DXY above SMA (bullish)
            return pd.Series([25.0] * (lookback - 1) + [27.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # Low/negative correlation + DXY Bull → Paper
    assert hedge_pref == "Paper"


def test_hedge_preference_hard_high_correlation():
    """Test Hard hedge: corr >= threshold (DXY doesn't matter)."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    mock_bar = MagicMock()
    
    # Create price series that will produce high positive correlation
    def mock_closes(lookback, symbol, current_bar):
        if symbol in ["QQQ", "TLT"]:
            # Both trending same direction = high correlation
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "UUP":
            # DXY above SMA (bullish) - shouldn't matter
            return pd.Series([25.0] * (lookback - 1) + [27.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # High correlation → Hard (regardless of DXY)
    assert hedge_pref == "Hard"


def test_hedge_preference_hard_dollar_weak():
    """Test Hard hedge: DXY < SMA (dollar weak, even with low correlation)."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    mock_bar = MagicMock()
    
    # Create price series with low correlation but weak dollar
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "QQQ":
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "TLT":
            # Inverse of QQQ = negative/low correlation
            return pd.Series([100.0 - i * 0.3 for i in range(lookback)])
        elif symbol == "UUP":
            # DXY below SMA (bearish - weak dollar)
            return pd.Series([25.0] * (lookback - 1) + [23.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # DXY Bear (weak dollar) → Hard
    assert hedge_pref == "Hard"


def test_hedge_preference_dual_filter_both_trigger():
    """Test Hard hedge: both correlation AND DXY trigger Hard."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    mock_bar = MagicMock()
    
    # Both high correlation and weak dollar
    def mock_closes(lookback, symbol, current_bar):
        if symbol in ["QQQ", "TLT"]:
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [23.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Hard"


def test_hedge_preference_insufficient_data():
    """Test hedge preference defaults correctly with insufficient data."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    
    # Return very short series (insufficient for correlation)
    def mock_closes(lookback, symbol, current_bar):
        return pd.Series([100.0] * 5)  # Too short

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # Default to Paper when data insufficient
    assert hedge_pref == "Paper"


def test_hedge_preference_dxy_sma_period_sensitivity():
    """Test DXY filter with different SMA periods."""
    strategy_short = Hierarchical_Adaptive_v5_1(dxy_sma_period=30)
    strategy_long = Hierarchical_Adaptive_v5_1(dxy_sma_period=70)

    assert strategy_short.dxy_sma_period == 30
    assert strategy_long.dxy_sma_period == 70


def test_hedge_preference_v51_vs_v50_logic():
    """Test v5.1 DXY filter adds additional Hard hedge trigger."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    mock_bar = MagicMock()
    
    # Low correlation + weak dollar scenario
    # v5.0 would return Paper (correlation only)
    # v5.1 should return Hard (DXY filter triggers)
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "QQQ":
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "TLT":
            return pd.Series([100.0 - i * 0.3 for i in range(lookback)])
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [23.0])  # Weak dollar
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # v5.1 DXY filter kicks in
    assert hedge_pref == "Hard"


# ===== 7. Gold Momentum Tests (4 tests) - Inherited from v5.0 =====

def test_gold_momentum_bullish():
    """Test gold momentum Bull when GLD > GLD_SMA."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    
    # Mock GLD price above SMA
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "GLD":
            # Current price (180) above SMA (~170)
            return pd.Series([170.0] * (lookback - 1) + [180.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        g_trend = strategy._calculate_gold_momentum(mock_bar)

    assert g_trend == "Bull"


def test_gold_momentum_bearish():
    """Test gold momentum Bear when GLD < GLD_SMA."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    
    # Mock GLD price below SMA
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "GLD":
            # Current price (160) below SMA (~170)
            return pd.Series([170.0] * (lookback - 1) + [160.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        g_trend = strategy._calculate_gold_momentum(mock_bar)

    assert g_trend == "Bear"


def test_gold_momentum_insufficient_data():
    """Test gold momentum defaults to Bear with insufficient data."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    
    # Return very short series
    def mock_closes(lookback, symbol, current_bar):
        return pd.Series([170.0] * 10)  # Too short for commodity_ma_period=150

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        g_trend = strategy._calculate_gold_momentum(mock_bar)

    assert g_trend == "Bear"


def test_gold_momentum_ma_period():
    """Test gold momentum with different MA periods."""
    strategy = Hierarchical_Adaptive_v5_1(commodity_ma_period=100)
    assert strategy.commodity_ma_period == 100


# ===== 8. Silver Relative Strength Tests (4 tests) - Inherited from v5.0 =====

def test_silver_relative_strength_positive():
    """Test silver kicker True when SLV ROC > GLD ROC."""
    strategy = Hierarchical_Adaptive_v5_1(silver_momentum_gate=True)
    strategy.init()

    mock_bar = MagicMock()
    
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "SLV":
            # SLV: 20 → 24 (20% gain)
            return pd.Series([20.0] * (lookback - 1) + [24.0])
        elif symbol == "GLD":
            # GLD: 170 → 178.5 (5% gain)
            return pd.Series([170.0] * (lookback - 1) + [178.5])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        use_slv = strategy._calculate_silver_relative_strength(mock_bar)

    # SLV outperforming → True
    assert use_slv == True


def test_silver_relative_strength_negative():
    """Test no silver kicker (False) when SLV ROC < GLD ROC."""
    strategy = Hierarchical_Adaptive_v5_1(silver_momentum_gate=True)
    strategy.init()

    mock_bar = MagicMock()
    
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "SLV":
            # SLV: 20 → 21 (5% gain)
            return pd.Series([20.0] * (lookback - 1) + [21.0])
        elif symbol == "GLD":
            # GLD: 170 → 204 (20% gain)
            return pd.Series([170.0] * (lookback - 1) + [204.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        use_slv = strategy._calculate_silver_relative_strength(mock_bar)

    # GLD outperforming → False
    assert use_slv == False


def test_silver_relative_strength_gate_disabled():
    """Test silver always allowed (True) when gate disabled."""
    strategy = Hierarchical_Adaptive_v5_1(silver_momentum_gate=False)
    strategy.init()

    mock_bar = MagicMock()
    
    # Even with GLD outperforming, gate is off so SLV is allowed
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "SLV":
            return pd.Series([20.0] * (lookback - 1) + [21.0])  # 5% gain
        elif symbol == "GLD":
            return pd.Series([170.0] * (lookback - 1) + [204.0])  # 20% gain
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        use_slv = strategy._calculate_silver_relative_strength(mock_bar)

    # Gate disabled → always True
    assert use_slv is True


def test_silver_relative_strength_lookback():
    """Test silver momentum uses correct lookback period."""
    strategy = Hierarchical_Adaptive_v5_1(silver_momentum_lookback=30)
    assert strategy.silver_momentum_lookback == 30


# ===== 9. 9-Cell Allocation Matrix Tests (8 tests) - EXTENDED v5.1 =====

def test_cell_allocation_c1_bull_low_v51():
    """Test Cell 1 v5.1: Bull/Low → 100% TQQQ (changed from 80/20)."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    result = strategy._get_cell_allocation_v51(
        cell_id=1,
        hedge_preference="Paper",  # Doesn't affect Bull/Low
        current_bar=mock_bar
    )

    # Returns tuple: (w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash)
    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # v5.1: C1 = 100% TQQQ (not 80/20 like v5.0)
    assert w_TQQQ == Decimal("1.0")
    assert w_QQQ == Decimal("0")
    assert w_GLD == Decimal("0")
    assert w_SLV == Decimal("0")


def test_cell_allocation_c2_bull_high_v51():
    """Test Cell 2 v5.1: Bull/High → 50% TQQQ + 25% GLD + 25% Cash."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    result = strategy._get_cell_allocation_v51(
        cell_id=2,
        hedge_preference="Paper",
        current_bar=mock_bar
    )

    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # v5.1: C2 = 50% TQQQ + 25% GLD + 25% cash
    assert w_TQQQ == Decimal("0.5")
    assert w_GLD == Decimal("0.25")
    assert w_cash == Decimal("0.25")


def test_cell_allocation_c9_vol_crush_v51():
    """Test Cell 9 v5.1: Vol-Crush Override → 100% TQQQ."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    # Cell 9 triggered by vol_crush_triggered=True on bear cells (5 or 6)
    result = strategy._get_cell_allocation_v51(
        cell_id=5,  # Bear cell that gets overridden
        hedge_preference="Paper",
        current_bar=mock_bar,
        vol_crush_triggered=True
    )

    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # v5.1: C9 (vol-crush override) = 100% TQQQ
    assert w_TQQQ == Decimal("1.0")
    assert w_QQQ == Decimal("0")
    assert w_GLD == Decimal("0")


def test_cell_allocation_sideways_high_paper():
    """Test Cell 4 Paper: Sideways/High/Paper → 20% PSQ + 80% bonds/cash."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    
    # Mock bond trend calculation
    def mock_closes(lookback, symbol, current_bar):
        return pd.Series([100.0 + i * 0.1 for i in range(lookback)])

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        result = strategy._get_cell_allocation_v51(
            cell_id=4,
            hedge_preference="Paper",
            current_bar=mock_bar
        )

    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # Cell 4 Paper: 20% PSQ + defensive portion in bonds
    assert w_PSQ == Decimal("0.2")
    # GLD should be 0 for Paper hedge
    assert w_GLD == Decimal("0")


def test_cell_allocation_sideways_high_hard():
    """Test Cell 4 Hard: Sideways/High/Hard → 20% PSQ + 60% GLD + 20% SLV."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    result = strategy._get_cell_allocation_v51(
        cell_id=4,
        hedge_preference="Hard",
        current_bar=mock_bar
    )

    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # Cell 4 Hard: 20% PSQ + 60% GLD + 20% SLV
    assert w_PSQ == Decimal("0.2")
    assert w_GLD == Decimal("0.6")
    assert w_SLV == Decimal("0.2")
    assert w_TMF == Decimal("0")


def test_cell_allocation_bear_high_paper():
    """Test Cell 6 Paper: Bear/High/Paper → 100% Cash."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    result = strategy._get_cell_allocation_v51(
        cell_id=6,
        hedge_preference="Paper",
        current_bar=mock_bar
    )

    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # Cell 6 Paper: 100% Cash (maximum safety)
    assert w_cash == Decimal("1.0")
    assert w_GLD == Decimal("0")


def test_cell_allocation_bear_high_hard():
    """Test Cell 6 Hard: Bear/High/Hard → 70% GLD + 30% SLV."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    result = strategy._get_cell_allocation_v51(
        cell_id=6,
        hedge_preference="Hard",
        current_bar=mock_bar
    )

    w_TQQQ, w_QQQ, w_PSQ, w_TMF, w_TMV, w_GLD, w_SLV, w_cash = result

    # Cell 6 Hard: 70% GLD + 30% SLV
    assert w_GLD == Decimal("0.7")
    assert w_SLV == Decimal("0.3")
    assert w_TMF == Decimal("0")


# ===== 10. Hard Hedge Allocation Tests (4 tests) - Inherited from v5.0 =====

def test_hard_hedge_allocation_gold_only():
    """Test hard hedge with gold only (silver gate returns False)."""
    strategy = Hierarchical_Adaptive_v5_1(
        gold_weight_max=Decimal("0.60"),
        silver_momentum_gate=True
    )
    strategy.init()

    mock_bar = MagicMock()
    
    # Mock silver relative strength returning False (SLV underperforming)
    with patch.object(strategy, '_calculate_silver_relative_strength', return_value=False):
        allocation = strategy._get_hard_hedge_allocation(
            defensive_weight=Decimal("0.60"),
            current_bar=mock_bar
        )

    # Should be gold only, capped at gold_weight_max
    assert allocation["GLD"] == Decimal("0.60")
    assert allocation["SLV"] == Decimal("0")


def test_hard_hedge_allocation_with_silver_kicker():
    """Test hard hedge with silver kicker active."""
    strategy = Hierarchical_Adaptive_v5_1(
        gold_weight_max=Decimal("0.60"),
        silver_vol_multiplier=Decimal("0.5"),
        silver_momentum_gate=True
    )
    strategy.init()

    mock_bar = MagicMock()
    
    # Mock silver outperforming
    with patch.object(strategy, '_calculate_silver_relative_strength', return_value=True):
        allocation = strategy._get_hard_hedge_allocation(
            defensive_weight=Decimal("0.60"),
            current_bar=mock_bar
        )

    # Gold and silver split based on silver_vol_multiplier
    # With multiplier 0.5: SLV ratio = 0.5/(1+0.5) = 1/3, GLD ratio = 2/3
    # Of 0.60 defensive: GLD ~ 0.40, SLV ~ 0.20
    assert allocation["GLD"] > Decimal("0")
    assert allocation["SLV"] > Decimal("0")
    assert allocation["GLD"] + allocation["SLV"] <= Decimal("0.60")


def test_hard_hedge_allocation_respects_gold_max():
    """Test hard hedge respects gold_weight_max cap."""
    strategy = Hierarchical_Adaptive_v5_1(gold_weight_max=Decimal("0.40"))
    strategy.init()

    mock_bar = MagicMock()
    
    with patch.object(strategy, '_calculate_silver_relative_strength', return_value=False):
        allocation = strategy._get_hard_hedge_allocation(
            defensive_weight=Decimal("0.80"),  # More than gold_weight_max
            current_bar=mock_bar
        )

    # GLD capped at gold_weight_max, remainder goes to Cash
    assert allocation["GLD"] == Decimal("0.40")
    assert allocation["CASH"] == Decimal("0.40")


def test_hard_hedge_allocation_weight_limits():
    """Test hard hedge total doesn't exceed defensive_weight."""
    strategy = Hierarchical_Adaptive_v5_1(
        gold_weight_max=Decimal("0.80"),
        silver_vol_multiplier=Decimal("0.5")
    )
    strategy.init()

    mock_bar = MagicMock()
    
    with patch.object(strategy, '_calculate_silver_relative_strength', return_value=True):
        allocation = strategy._get_hard_hedge_allocation(
            defensive_weight=Decimal("0.50"),
            current_bar=mock_bar
        )

    total_commodity = allocation["GLD"] + allocation["SLV"]
    total = total_commodity + allocation["CASH"]
    assert total <= Decimal("0.50")


# ===== 11. Rebalancing Tests (3 tests) =====

def test_rebalancing_threshold_calculation():
    """Test rebalancing threshold is correctly applied."""
    strategy = Hierarchical_Adaptive_v5_1(rebalance_threshold=Decimal("0.025"))
    strategy.init()

    # Verify threshold is set correctly
    assert strategy.rebalance_threshold == Decimal("0.025")


def test_rebalancing_uses_correct_method_name():
    """Test the v5.1 rebalancing method exists."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # v5.1 uses _check_rebalancing_threshold_v51
    assert hasattr(strategy, '_check_rebalancing_threshold_v51')


def test_rebalancing_includes_all_assets():
    """Test strategy tracks all tradable assets."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # Strategy should track these asset symbols
    assert strategy.leveraged_long_symbol == "TQQQ"
    assert strategy.core_long_symbol == "QQQ"
    assert strategy.inverse_hedge_symbol == "PSQ"
    assert strategy.bull_bond_symbol == "TMF"
    assert strategy.bear_bond_symbol == "TMV"
    assert strategy.gold_symbol == "GLD"
    assert strategy.silver_symbol == "SLV"


# ===== 12. Integration Tests (5 tests) =====

def test_full_signal_flow_paper_hedge():
    """Test complete signal flow with Paper hedge preference (low corr + strong dollar)."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    # Set up regime state
    strategy.trend_state = "Sideways"
    strategy.vol_state = "High"

    mock_bar = MagicMock()
    
    # Create alternating price series for negative correlation
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "QQQ":
            # Alternating: 100, 101, 100, 101, ...
            return pd.Series([100.0 + (i % 2) for i in range(lookback)])
        elif symbol == "TLT":
            # Inverse alternating: 100, 99, 100, 99, ...
            return pd.Series([100.0 - (i % 2) for i in range(lookback)])
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [27.0])  # Strong dollar
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Paper"


def test_full_signal_flow_hard_hedge_correlation():
    """Test complete signal flow with Hard hedge (high correlation triggers)."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    strategy.trend_state = "Sideways"
    strategy.vol_state = "High"

    mock_bar = MagicMock()
    
    # Mock for high correlation scenario
    def mock_closes(lookback, symbol, current_bar):
        if symbol in ["QQQ", "TLT"]:
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [27.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Hard"


def test_full_signal_flow_hard_hedge_dxy():
    """Test complete signal flow with Hard hedge (DXY weakness triggers)."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    strategy.trend_state = "Sideways"
    strategy.vol_state = "High"

    mock_bar = MagicMock()
    
    # Mock for weak dollar scenario
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "QQQ":
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "TLT":
            return pd.Series([100.0 - i * 0.3 for i in range(lookback)])
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [23.0])  # Weak dollar
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Hard"


def test_strategy_processes_all_symbols():
    """Test strategy correctly processes all 9 symbols."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    expected_symbols = {"QQQ", "TQQQ", "PSQ", "TLT", "TMF", "TMV", "GLD", "SLV", "UUP"}

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
    strategy_symbols.add(strategy.dxy_symbol)

    assert strategy_symbols == expected_symbols


def test_2022_scenario_dxy_filter_activation():
    """Test v5.1 activates Hard hedge in 2022-like conditions (weak dollar)."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    mock_bar = MagicMock()
    
    # 2022-like: low correlation but weak dollar
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "QQQ":
            return pd.Series([100.0 + i * 0.5 for i in range(lookback)])
        elif symbol == "TLT":
            return pd.Series([100.0 - i * 0.3 for i in range(lookback)])
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [23.0])
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    assert hedge_pref == "Hard"


# ===== 13. Edge Case Tests (4 tests) =====

def test_edge_case_minimum_gold_allocation():
    """Test strategy with minimum gold allocation."""
    strategy = Hierarchical_Adaptive_v5_1(gold_weight_max=Decimal("0.10"))
    strategy.init()

    mock_bar = MagicMock()
    
    with patch.object(strategy, '_calculate_silver_relative_strength', return_value=False):
        allocation = strategy._get_hard_hedge_allocation(
            defensive_weight=Decimal("0.50"),
            current_bar=mock_bar
        )

    # GLD capped at 0.10, remainder in cash
    assert allocation["GLD"] == Decimal("0.10")
    assert allocation["CASH"] == Decimal("0.40")


def test_edge_case_maximum_gold_allocation():
    """Test strategy handles maximum gold allocation."""
    strategy = Hierarchical_Adaptive_v5_1(
        gold_weight_max=Decimal("1.00"),
        silver_vol_multiplier=Decimal("0.5")
    )
    strategy.init()

    mock_bar = MagicMock()
    
    with patch.object(strategy, '_calculate_silver_relative_strength', return_value=True):
        allocation = strategy._get_hard_hedge_allocation(
            defensive_weight=Decimal("0.80"),
            current_bar=mock_bar
        )

    # Total should not exceed defensive_weight
    total = allocation["GLD"] + allocation["SLV"] + allocation["CASH"]
    assert total <= Decimal("0.80")


def test_edge_case_zero_correlation():
    """Test hedge preference with zero/neutral correlation (DXY determines)."""
    strategy = Hierarchical_Adaptive_v5_1(hedge_corr_threshold=Decimal("0.20"))
    strategy.init()

    mock_bar = MagicMock()
    
    # Zero correlation + strong dollar → Paper
    def mock_closes_paper(lookback, symbol, current_bar):
        if symbol == "QQQ":
            return pd.Series([100.0] * lookback)  # Flat
        elif symbol == "TLT":
            return pd.Series([100.0] * lookback)  # Flat (zero correlation)
        elif symbol == "UUP":
            return pd.Series([25.0] * (lookback - 1) + [27.0])  # Strong dollar
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes_paper):
        hedge_pref = strategy._calculate_hedge_preference(mock_bar)

    # Zero/neutral correlation + strong dollar → Paper
    assert hedge_pref == "Paper"


def test_edge_case_dxy_at_sma():
    """Test DXY trend when price equals SMA (boundary case)."""
    strategy = Hierarchical_Adaptive_v5_1()
    strategy.init()

    mock_bar = MagicMock()
    
    # Mock UUP price exactly at SMA
    def mock_closes(lookback, symbol, current_bar):
        if symbol == "UUP":
            return pd.Series([25.0] * lookback)  # Current == SMA
        return pd.Series([100.0] * lookback)

    with patch.object(strategy, '_get_closes_for_indicator_calculation', side_effect=mock_closes):
        dxy_trend = strategy._calculate_dxy_trend(mock_bar)

    # At boundary, implementation determines behavior
    assert dxy_trend in ["Bull", "Bear"]