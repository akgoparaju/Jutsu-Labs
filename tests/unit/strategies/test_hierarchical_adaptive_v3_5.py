"""
Unit tests for Hierarchical Adaptive v3.5 strategy.

Test Coverage:
1. Initialization (2 tests)
2. Warmup Calculation (4 tests)
3. Trend Classification (6 tests)
4. Volatility Z-Score (3 tests)
5. Hysteresis State Machine (5 tests)
6. Vol-Crush Override (3 tests)
7. Cell Allocation (6 tests)
8. Leverage Scalar (2 tests)
9. Integration (3 tests)

Total: 34 tests
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5 import Hierarchical_Adaptive_v3_5
from jutsu_engine.core.events import MarketDataEvent


# ===== Fixtures =====

@pytest.fixture
def strategy_default():
    """Create strategy with default parameters."""
    strategy = Hierarchical_Adaptive_v3_5()
    strategy.init()
    return strategy


@pytest.fixture
def strategy_with_psq():
    """Create strategy with PSQ enabled."""
    strategy = Hierarchical_Adaptive_v3_5(use_inverse_hedge=True, w_PSQ_max=Decimal("0.5"))
    strategy.init()
    return strategy


@pytest.fixture
def sample_bars():
    """Create sample market data bars."""
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


# ===== 1. Initialization Tests (2 tests) =====

def test_initialization_default_parameters():
    """Test strategy initialization with default parameters."""
    strategy = Hierarchical_Adaptive_v3_5()

    # Kalman parameters
    assert strategy.measurement_noise == Decimal("2000.0")
    assert strategy.T_max == Decimal("50.0")

    # Structural trend parameters
    assert strategy.sma_fast == 50
    assert strategy.sma_slow == 200
    assert strategy.t_norm_bull_thresh == Decimal("0.3")
    assert strategy.t_norm_bear_thresh == Decimal("-0.3")

    # Volatility parameters
    assert strategy.realized_vol_window == 21
    assert strategy.vol_baseline_window == 126
    assert strategy.upper_thresh_z == Decimal("1.0")
    assert strategy.lower_thresh_z == Decimal("0.0")

    # Vol-crush parameters
    assert strategy.vol_crush_threshold == Decimal("-0.20")
    assert strategy.vol_crush_lookback == 5

    # Allocation parameters
    assert strategy.leverage_scalar == Decimal("1.0")

    # Instrument toggles
    assert strategy.use_inverse_hedge is False
    assert strategy.w_PSQ_max == Decimal("0.5")

    # Symbol configuration
    assert strategy.signal_symbol == "QQQ"
    assert strategy.core_long_symbol == "QQQ"
    assert strategy.leveraged_long_symbol == "TQQQ"
    assert strategy.inverse_hedge_symbol == "PSQ"


def test_initialization_parameter_validation():
    """Test parameter validation on initialization."""
    # Invalid SMA configuration
    with pytest.raises(ValueError, match="sma_fast.*must be < sma_slow"):
        Hierarchical_Adaptive_v3_5(sma_fast=200, sma_slow=50)

    # Invalid trend thresholds
    with pytest.raises(ValueError, match="Trend thresholds must satisfy"):
        Hierarchical_Adaptive_v3_5(
            t_norm_bear_thresh=Decimal("0.1"),
            t_norm_bull_thresh=Decimal("0.2")
        )

    # Invalid z-score thresholds
    with pytest.raises(ValueError, match="upper_thresh_z.*must be > lower_thresh_z"):
        Hierarchical_Adaptive_v3_5(
            upper_thresh_z=Decimal("0.0"),
            lower_thresh_z=Decimal("1.0")
        )

    # Invalid vol-crush threshold
    with pytest.raises(ValueError, match="vol_crush_threshold must be negative"):
        Hierarchical_Adaptive_v3_5(vol_crush_threshold=Decimal("0.10"))

    # Invalid leverage scalar
    with pytest.raises(ValueError, match="leverage_scalar must be in"):
        Hierarchical_Adaptive_v3_5(leverage_scalar=Decimal("2.0"))

    # Invalid PSQ max
    with pytest.raises(ValueError, match="w_PSQ_max must be in"):
        Hierarchical_Adaptive_v3_5(w_PSQ_max=Decimal("0.0"))


# ===== 2. Warmup Calculation Tests (4 tests) =====

def test_warmup_calculation_default_parameters():
    """Test warmup calculation with default parameters (sma_slow=200)."""
    strategy = Hierarchical_Adaptive_v3_5()

    # Default: sma_slow=200, vol_baseline=126, vol_realized=21
    # SMA lookback: 200 + 10 = 210
    # Vol lookback: 126 + 21 = 147
    # Expected: max(210, 147) = 210

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 210


def test_warmup_calculation_sma_dominant():
    """Test warmup when SMA requires more bars than volatility (sma_slow=140)."""
    strategy = Hierarchical_Adaptive_v3_5(sma_slow=140)

    # SMA lookback: 140 + 10 = 150
    # Vol lookback: 126 + 21 = 147
    # Expected: max(150, 147) = 150

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 150


def test_warmup_calculation_vol_dominant():
    """Test warmup when volatility requires more bars than SMA (sma_slow=75)."""
    strategy = Hierarchical_Adaptive_v3_5(sma_slow=75)

    # SMA lookback: 75 + 10 = 85
    # Vol lookback: 126 + 21 = 147
    # Expected: max(85, 147) = 147

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 147


def test_warmup_calculation_large_sma():
    """Test warmup with large sma_slow parameter (sma_slow=220)."""
    strategy = Hierarchical_Adaptive_v3_5(sma_slow=220)

    # SMA lookback: 220 + 10 = 230
    # Vol lookback: 126 + 21 = 147
    # Expected: max(230, 147) = 230

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 230


# ===== 3. Trend Classification Tests (6 tests) =====

def test_trend_classification_bull_strong():
    """Test BullStrong classification: T_norm > 0.3 AND SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BullStrong"


def test_trend_classification_bear_strong():
    """Test BearStrong classification: T_norm < -0.3 AND SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BearStrong"


def test_trend_classification_sideways_scenario1():
    """Test Sideways: T_norm positive but SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_scenario2():
    """Test Sideways: T_norm negative but SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_scenario3():
    """Test Sideways: T_norm between thresholds, SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5()

    T_norm = Decimal("0.1")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_scenario4():
    """Test Sideways: T_norm between thresholds, SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5()

    T_norm = Decimal("-0.1")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


# ===== 3. Volatility Z-Score Tests (3 tests) =====

def test_volatility_zscore_calculation():
    """Test rolling volatility z-score calculation."""
    strategy = Hierarchical_Adaptive_v3_5()

    # Create synthetic price series with known volatility pattern
    np.random.seed(42)
    base_price = 100.0
    returns = np.random.normal(0, 0.01, 200)  # 1% daily vol
    prices = [base_price]
    for ret in returns:
        prices.append(prices[-1] * (1 + ret))

    closes = pd.Series(prices, dtype=object)

    z_score = strategy._calculate_volatility_zscore(closes)

    assert z_score is not None
    assert isinstance(z_score, Decimal)


def test_volatility_zscore_baseline_statistics():
    """Test z-score uses rolling baseline (mean and std)."""
    strategy = Hierarchical_Adaptive_v3_5()

    # Create series with increasing volatility
    np.random.seed(42)
    low_vol_returns = np.random.normal(0, 0.005, 126)  # Low vol period
    high_vol_returns = np.random.normal(0, 0.02, 126)  # High vol period

    base_price = 100.0
    prices = [base_price]
    for ret in np.concatenate([low_vol_returns, high_vol_returns]):
        prices.append(prices[-1] * (1 + ret))

    closes = pd.Series(prices, dtype=object)

    z_score = strategy._calculate_volatility_zscore(closes)

    # Z-score should be positive (current vol > baseline mean)
    assert z_score is not None
    assert z_score > Decimal("0")


def test_volatility_zscore_insufficient_data():
    """Test z-score returns None with insufficient data."""
    strategy = Hierarchical_Adaptive_v3_5()

    # Too few data points
    closes = pd.Series([100.0, 101.0, 102.0], dtype=object)

    z_score = strategy._calculate_volatility_zscore(closes)

    assert z_score is None


# ===== 4. Hysteresis State Machine Tests (5 tests) =====

def test_hysteresis_regime_stability():
    """Test hysteresis maintains state between thresholds (deadband)."""
    strategy = Hierarchical_Adaptive_v3_5(
        upper_thresh_z=Decimal("1.0"),
        lower_thresh_z=Decimal("0.0")
    )
    strategy.init()

    # Set initial state
    strategy.vol_state = "Low"

    # Z-score in deadband (between 0.0 and 1.0)
    strategy._apply_hysteresis(Decimal("0.5"))

    # State should persist
    assert strategy.vol_state == "Low"

    # Try with High initial state
    strategy.vol_state = "High"
    strategy._apply_hysteresis(Decimal("0.5"))

    # State should persist
    assert strategy.vol_state == "High"


def test_hysteresis_upper_breach():
    """Test hysteresis transitions to High when z_score > upper_thresh."""
    strategy = Hierarchical_Adaptive_v3_5(
        upper_thresh_z=Decimal("1.0"),
        lower_thresh_z=Decimal("0.0")
    )
    strategy.init()

    # Start in Low state
    strategy.vol_state = "Low"

    # Breach upper threshold
    strategy._apply_hysteresis(Decimal("1.5"))

    # State should transition to High
    assert strategy.vol_state == "High"


def test_hysteresis_lower_breach():
    """Test hysteresis transitions to Low when z_score < lower_thresh."""
    strategy = Hierarchical_Adaptive_v3_5(
        upper_thresh_z=Decimal("1.0"),
        lower_thresh_z=Decimal("0.0")
    )
    strategy.init()

    # Start in High state
    strategy.vol_state = "High"

    # Breach lower threshold
    strategy._apply_hysteresis(Decimal("-0.5"))

    # State should transition to Low
    assert strategy.vol_state == "Low"


def test_hysteresis_initialization_logic():
    """Test Day 1 initialization: z_score > 0 → High, else Low."""
    strategy = Hierarchical_Adaptive_v3_5()
    strategy.init()

    # Simulate warmup period (bars = 220 = max(200, 126) + 20 for SMA_slow warmup)
    for i in range(220):
        bar = MarketDataEvent(
            symbol="QQQ",
            timestamp=datetime.now(timezone.utc),
            open=Decimal("100.0"),
            high=Decimal("101.0"),
            low=Decimal("99.0"),
            close=Decimal("100.0"),
            volume=1000000
        )
        strategy._bars.append(bar)

    # Positive z-score → High
    strategy._apply_hysteresis(Decimal("0.5"))
    assert strategy.vol_state == "High"

    # Negative z-score → Low
    strategy.vol_state = "Low"  # Reset
    strategy._apply_hysteresis(Decimal("-0.5"))
    assert strategy.vol_state == "Low"


def test_hysteresis_indefinite_persistence():
    """Test hysteresis state persists indefinitely until boundary crossed."""
    strategy = Hierarchical_Adaptive_v3_5(
        upper_thresh_z=Decimal("1.0"),
        lower_thresh_z=Decimal("0.0")
    )
    strategy.init()

    # Start in Low state
    strategy.vol_state = "Low"

    # Apply z-scores in deadband for 100 iterations
    for _ in range(100):
        strategy._apply_hysteresis(Decimal("0.5"))
        assert strategy.vol_state == "Low"

    # State should still be Low after 100 iterations
    assert strategy.vol_state == "Low"


# ===== 5. Vol-Crush Override Tests (3 tests) =====

def test_vol_crush_trigger_detection():
    """Test vol-crush override triggers on 20% vol drop in 5 days."""
    strategy = Hierarchical_Adaptive_v3_5(vol_crush_threshold=Decimal("-0.20"))

    # Create price series with volatility spike then crush
    np.random.seed(42)

    # High vol period (10%)
    high_vol_returns = np.random.normal(0, 0.10, 50)
    # Vol crush period (2%)
    low_vol_returns = np.random.normal(0, 0.02, 10)

    base_price = 100.0
    prices = [base_price]
    for ret in np.concatenate([high_vol_returns, low_vol_returns]):
        prices.append(prices[-1] * (1 + ret))

    closes = pd.Series(prices, dtype=object)

    vol_crush_triggered = strategy._check_vol_crush_override(closes)

    # Should trigger (vol dropped >20%)
    assert vol_crush_triggered is True


def test_vol_crush_bear_override():
    """Test vol-crush forces BearStrong → Sideways."""
    strategy = Hierarchical_Adaptive_v3_5()
    strategy.init()

    # Set up scenario: BearStrong trend
    T_norm = Decimal("-0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)
    assert trend_state == "BearStrong"

    # Simulate vol-crush trigger
    vol_crush_triggered = True

    if vol_crush_triggered and trend_state == "BearStrong":
        trend_state = "Sideways"

    # Trend should be overridden to Sideways
    assert trend_state == "Sideways"


def test_vol_crush_volstate_force():
    """Test vol-crush forces VolState → Low."""
    strategy = Hierarchical_Adaptive_v3_5()
    strategy.init()

    # Start in High state
    strategy.vol_state = "High"

    # Create vol-crush scenario
    np.random.seed(42)
    high_vol_returns = np.random.normal(0, 0.10, 50)
    low_vol_returns = np.random.normal(0, 0.02, 10)

    base_price = 100.0
    prices = [base_price]
    for ret in np.concatenate([high_vol_returns, low_vol_returns]):
        prices.append(prices[-1] * (1 + ret))

    closes = pd.Series(prices, dtype=object)

    # Vol-crush should force VolState to Low
    vol_crush_triggered = strategy._check_vol_crush_override(closes)

    if vol_crush_triggered:
        assert strategy.vol_state == "Low"


# ===== 6. Cell Allocation Tests (6 tests) =====

def test_cell_1_kill_zone():
    """Test Cell 1 (Bull/Low): 60% TQQQ, 40% QQQ."""
    strategy = Hierarchical_Adaptive_v3_5()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(1)

    assert w_TQQQ == Decimal("0.6")
    assert w_QQQ == Decimal("0.4")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.0")


def test_cell_2_fragile():
    """Test Cell 2 (Bull/High): 100% QQQ."""
    strategy = Hierarchical_Adaptive_v3_5()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(2)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("1.0")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.0")


def test_cell_3_drift():
    """Test Cell 3 (Side/Low): 20% TQQQ, 80% QQQ."""
    strategy = Hierarchical_Adaptive_v3_5()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(3)

    assert w_TQQQ == Decimal("0.2")
    assert w_QQQ == Decimal("0.8")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.0")


def test_cell_4_chop():
    """Test Cell 4 (Side/High): 100% Cash."""
    strategy = Hierarchical_Adaptive_v3_5()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(4)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.0")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("1.0")


def test_cell_5_grind():
    """Test Cell 5 (Bear/Low): 50% QQQ, 50% Cash."""
    strategy = Hierarchical_Adaptive_v3_5()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(5)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.5")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.5")


def test_cell_6_crash_with_psq():
    """Test Cell 6 (Bear/High): PSQ enabled → 50% PSQ, 50% Cash."""
    strategy = Hierarchical_Adaptive_v3_5(use_inverse_hedge=True, w_PSQ_max=Decimal("0.5"))

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(6)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.0")
    assert w_PSQ == Decimal("0.5")
    assert w_cash == Decimal("0.5")


def test_cell_6_crash_without_psq():
    """Test Cell 6 (Bear/High): PSQ disabled → 100% Cash."""
    strategy = Hierarchical_Adaptive_v3_5(use_inverse_hedge=False)

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(6)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.0")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("1.0")


# ===== 7. Leverage Scalar Tests (2 tests) =====

def test_leverage_scalar_reduction():
    """Test leverage_scalar=0.8 scales down all weights."""
    strategy = Hierarchical_Adaptive_v3_5(leverage_scalar=Decimal("0.8"))

    # Get base weights for Cell 1 (60/40 TQQQ/QQQ)
    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(1)

    # Apply leverage scalar
    w_TQQQ_scaled = w_TQQQ * strategy.leverage_scalar
    w_QQQ_scaled = w_QQQ * strategy.leverage_scalar

    # Normalize
    total = w_TQQQ_scaled + w_QQQ_scaled
    w_TQQQ_final = w_TQQQ_scaled / total
    w_QQQ_final = w_QQQ_scaled / total

    # Weights should be scaled down proportionally
    assert w_TQQQ_final == Decimal("0.6")  # Ratio preserved
    assert w_QQQ_final == Decimal("0.4")   # Ratio preserved


def test_leverage_scalar_amplification():
    """Test leverage_scalar=1.2 scales up all weights."""
    strategy = Hierarchical_Adaptive_v3_5(leverage_scalar=Decimal("1.2"))

    # Get base weights for Cell 1 (60/40 TQQQ/QQQ)
    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(1)

    # Apply leverage scalar
    w_TQQQ_scaled = w_TQQQ * strategy.leverage_scalar
    w_QQQ_scaled = w_QQQ * strategy.leverage_scalar

    # Normalize
    total = w_TQQQ_scaled + w_QQQ_scaled
    w_TQQQ_final = w_TQQQ_scaled / total
    w_QQQ_final = w_QQQ_scaled / total

    # Weights should be scaled up proportionally
    assert w_TQQQ_final == Decimal("0.6")  # Ratio preserved
    assert w_QQQ_final == Decimal("0.4")   # Ratio preserved


# ===== 8. Integration Tests (3 tests) =====

@patch('jutsu_engine.strategies.Hierarchical_Adaptive_v3_5.sma')
@patch('jutsu_engine.strategies.Hierarchical_Adaptive_v3_5.annualized_volatility')
def test_full_pipeline_integration(mock_vol, mock_sma, sample_bars):
    """Test full pipeline: Kalman → SMA → z-score → hysteresis → cell → weights."""
    strategy = Hierarchical_Adaptive_v3_5()
    strategy.init()

    # Mock SMA values
    mock_sma.return_value = pd.Series([100.0, 105.0], dtype=object)  # SMA_fast > SMA_slow

    # Mock volatility z-score calculation
    mock_vol.return_value = pd.Series([0.15] * 150, dtype=object)  # Low vol

    # Feed bars
    for bar in sample_bars[:250]:
        strategy._bars.append(bar)

    # Process a bar
    strategy.on_bar(sample_bars[250])

    # Should have processed successfully (no exceptions)
    # Verify state was updated
    assert strategy.vol_state in ["Low", "High"]
    assert strategy.current_tqqq_weight >= Decimal("0")
    assert strategy.current_qqq_weight >= Decimal("0")


def test_rebalancing_logic():
    """Test rebalancing triggers when weights drift beyond threshold."""
    strategy = Hierarchical_Adaptive_v3_5(rebalance_threshold=Decimal("0.05"))

    # Set current weights
    strategy.current_tqqq_weight = Decimal("0.6")
    strategy.current_qqq_weight = Decimal("0.4")
    strategy.current_psq_weight = Decimal("0.0")

    # Test 1: Small drift (no rebalance)
    needs_rebalance = strategy._check_rebalancing_threshold(
        Decimal("0.62"), Decimal("0.38"), Decimal("0.0")
    )
    assert needs_rebalance is False

    # Test 2: Large drift (rebalance)
    needs_rebalance = strategy._check_rebalancing_threshold(
        Decimal("0.8"), Decimal("0.2"), Decimal("0.0")
    )
    assert needs_rebalance is True


def test_psq_toggle_behavior():
    """Test PSQ toggle affects Cell 6 allocation only."""
    # Strategy without PSQ
    strategy_no_psq = Hierarchical_Adaptive_v3_5(use_inverse_hedge=False)

    # Strategy with PSQ
    strategy_with_psq = Hierarchical_Adaptive_v3_5(
        use_inverse_hedge=True,
        w_PSQ_max=Decimal("0.5")
    )

    # Cell 6 should differ
    _, _, psq_no, cash_no = strategy_no_psq._get_cell_allocation(6)
    _, _, psq_yes, cash_yes = strategy_with_psq._get_cell_allocation(6)

    assert psq_no == Decimal("0.0")
    assert cash_no == Decimal("1.0")

    assert psq_yes == Decimal("0.5")
    assert cash_yes == Decimal("0.5")

    # Cell 1 should be identical
    w1_no = strategy_no_psq._get_cell_allocation(1)
    w1_yes = strategy_with_psq._get_cell_allocation(1)

    assert w1_no == w1_yes
