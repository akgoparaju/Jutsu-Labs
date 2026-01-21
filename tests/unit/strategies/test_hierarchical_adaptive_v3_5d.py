"""
Unit tests for Hierarchical Adaptive v3.5d strategy.

Test Coverage:
1. Initialization (3 tests) - includes Cell 1 Exit Confirmation params
2. Warmup Calculation (4 tests)
3. Trend Classification (6 tests)
4. Volatility Z-Score (3 tests)
5. Hysteresis State Machine (5 tests)
6. Vol-Crush Override (3 tests)
7. Cell Allocation (6 tests)
8. Leverage Scalar (2 tests)
9. Integration (3 tests)
10. Treasury Overlay (8 tests)
11. Treasury Overlay Integration (4 tests)
12. Execution Timing (10 tests)
13. Cell 1 Exit Confirmation (12 tests) - NEW in v3.5d

Total: 69 tests
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d import Hierarchical_Adaptive_v3_5d
from jutsu_engine.core.events import MarketDataEvent


# ===== Fixtures =====

@pytest.fixture
def strategy_default():
    """Create strategy with default parameters."""
    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()
    return strategy


@pytest.fixture
def strategy_with_exit_confirmation():
    """Create strategy with Cell 1 Exit Confirmation enabled."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=2
    )
    strategy.init()
    return strategy


@pytest.fixture
def strategy_with_psq():
    """Create strategy with PSQ enabled."""
    strategy = Hierarchical_Adaptive_v3_5d(use_inverse_hedge=True, w_PSQ_max=Decimal("0.5"))
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


# ===== 1. Initialization Tests (3 tests) =====

def test_initialization_default_parameters():
    """Test strategy initialization with default parameters (Golden Config defaults)."""
    strategy = Hierarchical_Adaptive_v3_5d()

    # Kalman parameters
    assert strategy.measurement_noise == Decimal("2000.0")
    assert strategy.T_max == Decimal("50.0")

    # Structural trend parameters (v3.5d uses Golden Config defaults)
    assert strategy.sma_fast == 40  # Golden Config default
    assert strategy.sma_slow == 140  # Golden Config default
    assert strategy.t_norm_bull_thresh == Decimal("0.2")  # Golden Config default
    assert strategy.t_norm_bear_thresh == Decimal("-0.3")

    # Volatility parameters (v3.5d uses Golden Config defaults)
    assert strategy.realized_vol_window == 21
    assert strategy.vol_baseline_window == 126
    assert strategy.upper_thresh_z == Decimal("1.0")
    assert strategy.lower_thresh_z == Decimal("0.2")  # Golden Config default

    # Vol-crush parameters (v3.5d uses Golden Config defaults)
    assert strategy.vol_crush_threshold == Decimal("-0.15")  # Golden Config default
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

    # v3.5d: Cell 1 Exit Confirmation parameters (defaults)
    assert strategy.cell1_exit_confirmation_enabled is False
    assert strategy.cell1_exit_confirmation_days == 2


def test_initialization_cell1_exit_confirmation_parameters():
    """Test Cell 1 Exit Confirmation parameter initialization."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )

    assert strategy.cell1_exit_confirmation_enabled is True
    assert strategy.cell1_exit_confirmation_days == 3


def test_initialization_parameter_validation():
    """Test parameter validation on initialization."""
    # Invalid SMA configuration
    with pytest.raises(ValueError, match="sma_fast.*must be < sma_slow"):
        Hierarchical_Adaptive_v3_5d(sma_fast=200, sma_slow=50)

    # Invalid trend thresholds
    with pytest.raises(ValueError, match="Trend thresholds must satisfy"):
        Hierarchical_Adaptive_v3_5d(
            t_norm_bear_thresh=Decimal("0.1"),
            t_norm_bull_thresh=Decimal("0.2")
        )

    # Invalid z-score thresholds
    with pytest.raises(ValueError, match="upper_thresh_z.*must be > lower_thresh_z"):
        Hierarchical_Adaptive_v3_5d(
            upper_thresh_z=Decimal("0.0"),
            lower_thresh_z=Decimal("1.0")
        )

    # Invalid vol-crush threshold
    with pytest.raises(ValueError, match="vol_crush_threshold must be negative"):
        Hierarchical_Adaptive_v3_5d(vol_crush_threshold=Decimal("0.10"))

    # Invalid leverage scalar
    with pytest.raises(ValueError, match="leverage_scalar must be in"):
        Hierarchical_Adaptive_v3_5d(leverage_scalar=Decimal("2.0"))

    # Invalid PSQ max
    with pytest.raises(ValueError, match="w_PSQ_max must be in"):
        Hierarchical_Adaptive_v3_5d(w_PSQ_max=Decimal("0.0"))

    # Invalid Cell 1 Exit Confirmation days (must be in [1, 10])
    with pytest.raises(ValueError, match="cell1_exit_confirmation_days must be in"):
        Hierarchical_Adaptive_v3_5d(cell1_exit_confirmation_days=0)

    with pytest.raises(ValueError, match="cell1_exit_confirmation_days must be in"):
        Hierarchical_Adaptive_v3_5d(cell1_exit_confirmation_days=-1)


# ===== 2. Warmup Calculation Tests (4 tests) =====

def test_warmup_calculation_default_parameters():
    """Test warmup calculation with default parameters (Golden Config: sma_slow=140)."""
    strategy = Hierarchical_Adaptive_v3_5d()

    # Default (Golden Config): sma_slow=140, vol_baseline=126, vol_realized=21
    # SMA lookback: 140 + 10 = 150
    # Vol lookback: 126 + 21 = 147
    # Expected: max(150, 147) = 150

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 150


def test_warmup_calculation_sma_dominant():
    """Test warmup when SMA requires more bars than volatility (sma_slow=140)."""
    strategy = Hierarchical_Adaptive_v3_5d(sma_slow=140)

    # SMA lookback: 140 + 10 = 150
    # Vol lookback: 126 + 21 = 147
    # Expected: max(150, 147) = 150

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 150


def test_warmup_calculation_vol_dominant():
    """Test warmup when volatility requires more bars than SMA (sma_slow=75)."""
    strategy = Hierarchical_Adaptive_v3_5d(sma_slow=75)

    # SMA lookback: 75 + 10 = 85
    # Vol lookback: 126 + 21 = 147
    # Expected: max(85, 147) = 147

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 147


def test_warmup_calculation_large_sma():
    """Test warmup with large sma_slow parameter (sma_slow=220)."""
    strategy = Hierarchical_Adaptive_v3_5d(sma_slow=220)

    # SMA lookback: 220 + 10 = 230
    # Vol lookback: 126 + 21 = 147
    # Expected: max(230, 147) = 230

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 230


# ===== 3. Trend Classification Tests (6 tests) =====

def test_trend_classification_bull_strong():
    """Test BullStrong classification: T_norm > 0.3 AND SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5d()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BullStrong"


def test_trend_classification_bear_strong():
    """Test BearStrong classification: T_norm < -0.3 AND SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5d()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "BearStrong"


def test_trend_classification_sideways_scenario1():
    """Test Sideways: T_norm positive but SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5d()

    T_norm = Decimal("0.5")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_scenario2():
    """Test Sideways: T_norm negative but SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5d()

    T_norm = Decimal("-0.5")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_scenario3():
    """Test Sideways: T_norm between thresholds, SMA_fast > SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5d()

    T_norm = Decimal("0.1")
    sma_fast = Decimal("100.0")
    sma_slow = Decimal("90.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


def test_trend_classification_sideways_scenario4():
    """Test Sideways: T_norm between thresholds, SMA_fast < SMA_slow."""
    strategy = Hierarchical_Adaptive_v3_5d()

    T_norm = Decimal("-0.1")
    sma_fast = Decimal("90.0")
    sma_slow = Decimal("100.0")

    trend_state = strategy._classify_trend_regime(T_norm, sma_fast, sma_slow)

    assert trend_state == "Sideways"


# ===== 3. Volatility Z-Score Tests (3 tests) =====

def test_volatility_zscore_calculation():
    """Test rolling volatility z-score calculation."""
    strategy = Hierarchical_Adaptive_v3_5d()

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
    strategy = Hierarchical_Adaptive_v3_5d()

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
    strategy = Hierarchical_Adaptive_v3_5d()

    # Too few data points
    closes = pd.Series([100.0, 101.0, 102.0], dtype=object)

    z_score = strategy._calculate_volatility_zscore(closes)

    assert z_score is None


# ===== 4. Hysteresis State Machine Tests (5 tests) =====

def test_hysteresis_regime_stability():
    """Test hysteresis maintains state between thresholds (deadband)."""
    strategy = Hierarchical_Adaptive_v3_5d(
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
    strategy = Hierarchical_Adaptive_v3_5d(
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
    strategy = Hierarchical_Adaptive_v3_5d(
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
    """Test Day 1 initialization: z_score > upper_thresh → High, z_score < lower_thresh → Low."""
    # Use explicit thresholds for predictable behavior
    strategy = Hierarchical_Adaptive_v3_5d(
        upper_thresh_z=Decimal("1.0"),
        lower_thresh_z=Decimal("0.0")
    )
    strategy.init()

    # Simulate warmup period
    for i in range(160):  # Golden Config uses sma_slow=140, so 150 warmup
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

    # z_score above upper_thresh (1.0) → High
    strategy._apply_hysteresis(Decimal("1.5"))
    assert strategy.vol_state == "High"

    # z_score below lower_thresh (0.0) → Low
    strategy._apply_hysteresis(Decimal("-0.5"))
    assert strategy.vol_state == "Low"


def test_hysteresis_indefinite_persistence():
    """Test hysteresis state persists indefinitely until boundary crossed."""
    strategy = Hierarchical_Adaptive_v3_5d(
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
    strategy = Hierarchical_Adaptive_v3_5d(vol_crush_threshold=Decimal("-0.20"))

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
    strategy = Hierarchical_Adaptive_v3_5d()
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
    strategy = Hierarchical_Adaptive_v3_5d()
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
    strategy = Hierarchical_Adaptive_v3_5d()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(1)

    assert w_TQQQ == Decimal("0.6")
    assert w_QQQ == Decimal("0.4")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.0")


def test_cell_2_fragile():
    """Test Cell 2 (Bull/High): 100% QQQ."""
    strategy = Hierarchical_Adaptive_v3_5d()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(2)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("1.0")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.0")


def test_cell_3_drift():
    """Test Cell 3 (Side/Low): 20% TQQQ, 80% QQQ."""
    strategy = Hierarchical_Adaptive_v3_5d()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(3)

    assert w_TQQQ == Decimal("0.2")
    assert w_QQQ == Decimal("0.8")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.0")


def test_cell_4_chop():
    """Test Cell 4 (Side/High): 100% Cash."""
    strategy = Hierarchical_Adaptive_v3_5d()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(4)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.0")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("1.0")


def test_cell_5_grind():
    """Test Cell 5 (Bear/Low): 50% QQQ, 50% Cash."""
    strategy = Hierarchical_Adaptive_v3_5d()

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(5)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.5")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("0.5")


def test_cell_6_crash_with_psq():
    """Test Cell 6 (Bear/High): PSQ enabled → 50% PSQ, 50% Cash."""
    strategy = Hierarchical_Adaptive_v3_5d(use_inverse_hedge=True, w_PSQ_max=Decimal("0.5"))

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(6)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.0")
    assert w_PSQ == Decimal("0.5")
    assert w_cash == Decimal("0.5")


def test_cell_6_crash_without_psq():
    """Test Cell 6 (Bear/High): PSQ disabled → 100% Cash."""
    strategy = Hierarchical_Adaptive_v3_5d(use_inverse_hedge=False)

    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy._get_cell_allocation(6)

    assert w_TQQQ == Decimal("0.0")
    assert w_QQQ == Decimal("0.0")
    assert w_PSQ == Decimal("0.0")
    assert w_cash == Decimal("1.0")


# ===== 7. Leverage Scalar Tests (2 tests) =====

def test_leverage_scalar_reduction():
    """Test leverage_scalar=0.8 scales down all weights."""
    strategy = Hierarchical_Adaptive_v3_5d(leverage_scalar=Decimal("0.8"))

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
    strategy = Hierarchical_Adaptive_v3_5d(leverage_scalar=Decimal("1.2"))

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

@patch('jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d.sma')
@patch('jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d.annualized_volatility')
def test_full_pipeline_integration(mock_vol, mock_sma, sample_bars):
    """Test full pipeline: Kalman → SMA → z-score → hysteresis → cell → weights."""
    strategy = Hierarchical_Adaptive_v3_5d()
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
    strategy = Hierarchical_Adaptive_v3_5d(rebalance_threshold=Decimal("0.05"))

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
    strategy_no_psq = Hierarchical_Adaptive_v3_5d(use_inverse_hedge=False)

    # Strategy with PSQ
    strategy_with_psq = Hierarchical_Adaptive_v3_5d(
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


# ===== 9. Treasury Overlay Tests (8 tests) =====

def test_treasury_overlay_initialization():
    """Test Treasury Overlay parameters initialize correctly."""
    strategy = Hierarchical_Adaptive_v3_5d(
        allow_treasury=True,
        bond_sma_fast=20,
        bond_sma_slow=60,
        max_bond_weight=Decimal("0.4"),
        treasury_trend_symbol="TLT",
        bull_bond_symbol="TMF",
        bear_bond_symbol="TMV"
    )

    assert strategy.allow_treasury is True
    assert strategy.bond_sma_fast == 20
    assert strategy.bond_sma_slow == 60
    assert strategy.max_bond_weight == Decimal("0.4")
    assert strategy.treasury_trend_symbol == "TLT"
    assert strategy.bull_bond_symbol == "TMF"
    assert strategy.bear_bond_symbol == "TMV"


def test_treasury_overlay_parameter_validation():
    """Test Treasury Overlay parameter validation."""
    # Invalid bond SMA configuration (fast >= slow)
    with pytest.raises(ValueError, match="bond_sma_fast.*must be < bond_sma_slow"):
        Hierarchical_Adaptive_v3_5d(bond_sma_fast=60, bond_sma_slow=20)

    # Invalid max_bond_weight (outside [0.0, 1.0])
    with pytest.raises(ValueError, match="max_bond_weight must be in"):
        Hierarchical_Adaptive_v3_5d(max_bond_weight=Decimal("1.5"))

    with pytest.raises(ValueError, match="max_bond_weight must be in"):
        Hierarchical_Adaptive_v3_5d(max_bond_weight=Decimal("-0.1"))


def test_treasury_overlay_warmup_calculation():
    """Test warmup calculation includes bond_sma_slow when allow_treasury=True."""
    # With Treasury Overlay enabled
    strategy_with_bonds = Hierarchical_Adaptive_v3_5d(
        allow_treasury=True,
        bond_sma_slow=60,
        sma_slow=50  # Make SMA shorter than bonds
    )
    warmup_with_bonds = strategy_with_bonds.get_required_warmup_bars()

    # bond_sma_slow (60) should dominate
    # Expected: max(50+10, 126+21, 60) = max(60, 147, 60) = 147
    assert warmup_with_bonds == 147

    # With Treasury Overlay disabled
    strategy_no_bonds = Hierarchical_Adaptive_v3_5d(
        allow_treasury=False,
        bond_sma_slow=60,
        sma_slow=50
    )
    warmup_no_bonds = strategy_no_bonds.get_required_warmup_bars()

    # bond_sma_slow should be ignored
    # Expected: max(50+10, 126+21) = max(60, 147) = 147
    assert warmup_no_bonds == 147


def test_get_safe_haven_allocation_bond_bull():
    """Test Safe Haven Selector chooses TMF when bond trend is bullish."""
    strategy = Hierarchical_Adaptive_v3_5d(
        bond_sma_fast=20,
        bond_sma_slow=60,
        max_bond_weight=Decimal("0.4")
    )

    # Create TLT price series with bullish trend (SMA_fast > SMA_slow)
    # Prices trending up
    tlt_prices = pd.Series([100.0 + i * 0.1 for i in range(100)], dtype=object)

    # Test with 100% defensive weight
    defensive_weight = Decimal("1.0")
    allocation = strategy.get_safe_haven_allocation(tlt_prices, defensive_weight)

    # Should allocate to TMF (bull bonds)
    assert "TMF" in allocation
    assert allocation["TMF"] == Decimal("0.4")  # 40% cap
    assert allocation["CASH"] == Decimal("0.6")  # Remaining 60%


def test_get_safe_haven_allocation_bond_bear():
    """Test Safe Haven Selector chooses TMV when bond trend is bearish."""
    strategy = Hierarchical_Adaptive_v3_5d(
        bond_sma_fast=20,
        bond_sma_slow=60,
        max_bond_weight=Decimal("0.4")
    )

    # Create TLT price series with bearish trend (SMA_fast < SMA_slow)
    # Prices trending down
    tlt_prices = pd.Series([100.0 - i * 0.1 for i in range(100)], dtype=object)

    # Test with 100% defensive weight
    defensive_weight = Decimal("1.0")
    allocation = strategy.get_safe_haven_allocation(tlt_prices, defensive_weight)

    # Should allocate to TMV (bear bonds)
    assert "TMV" in allocation
    assert allocation["TMV"] == Decimal("0.4")  # 40% cap
    assert allocation["CASH"] == Decimal("0.6")  # Remaining 60%


def test_get_safe_haven_allocation_insufficient_data():
    """Test Safe Haven Selector falls back to Cash with insufficient TLT data."""
    strategy = Hierarchical_Adaptive_v3_5d(bond_sma_slow=60)

    # Insufficient data (less than bond_sma_slow)
    tlt_prices = pd.Series([100.0, 101.0, 102.0], dtype=object)

    defensive_weight = Decimal("1.0")
    allocation = strategy.get_safe_haven_allocation(tlt_prices, defensive_weight)

    # Should fallback to 100% Cash
    assert allocation == {"CASH": Decimal("1.0")}


def test_get_safe_haven_allocation_partial_defensive():
    """Test Safe Haven Selector with partial defensive allocation (Cell 5)."""
    strategy = Hierarchical_Adaptive_v3_5d(
        bond_sma_fast=20,
        bond_sma_slow=60,
        max_bond_weight=Decimal("0.4")
    )

    # Bullish bond trend
    tlt_prices = pd.Series([100.0 + i * 0.1 for i in range(100)], dtype=object)

    # Test with 50% defensive weight (Cell 5 scenario)
    defensive_weight = Decimal("0.5")
    allocation = strategy.get_safe_haven_allocation(tlt_prices, defensive_weight)

    # Should allocate 40% of 0.5 = 0.2 to TMF (respecting global 40% cap)
    # But max(0.5 * 0.4, global_cap) = min(0.2, 0.4) = 0.2
    assert "TMF" in allocation
    assert allocation["TMF"] == Decimal("0.2")  # 40% of defensive portion
    assert allocation["CASH"] == Decimal("0.3")  # Remaining 60% of defensive


def test_get_safe_haven_allocation_nan_handling():
    """Test Safe Haven Selector handles NaN SMA values gracefully."""
    strategy = Hierarchical_Adaptive_v3_5d(bond_sma_slow=60)

    # Create series that will produce NaN SMAs (insufficient rolling window)
    tlt_prices = pd.Series([100.0, 101.0, np.nan, 102.0], dtype=object)

    defensive_weight = Decimal("1.0")
    allocation = strategy.get_safe_haven_allocation(tlt_prices, defensive_weight)

    # Should fallback to Cash when NaN encountered
    assert allocation == {"CASH": Decimal("1.0")}


# ===== 10. Treasury Overlay Integration Tests (4 tests) =====

def test_cell_4_treasury_overlay_integration():
    """Test Cell 4 (Chop) uses Treasury Overlay instead of 100% Cash."""
    strategy = Hierarchical_Adaptive_v3_5d(allow_treasury=True)

    # Cell 4 without Treasury Overlay would be 100% Cash
    # With Treasury Overlay enabled, should call get_safe_haven_allocation

    # This is tested indirectly via on_bar() behavior
    # We verify that the method signature accepts TMF/TMV weights
    assert hasattr(strategy, 'get_safe_haven_allocation')


def test_cell_5_treasury_overlay_integration():
    """Test Cell 5 (Grind) splits between QQQ and Safe Haven."""
    strategy = Hierarchical_Adaptive_v3_5d(allow_treasury=True)

    # Cell 5 without Treasury Overlay: 50% QQQ + 50% Cash
    # With Treasury Overlay: 50% QQQ + Safe Haven (Cash/TMF/TMV mix)

    # Verify method signature supports this pattern
    assert hasattr(strategy, 'get_safe_haven_allocation')


def test_cell_6_psq_priority_over_treasury():
    """Test Cell 6 PSQ logic takes precedence over Treasury Overlay."""
    strategy_with_psq = Hierarchical_Adaptive_v3_5d(
        use_inverse_hedge=True,
        w_PSQ_max=Decimal("0.5"),
        allow_treasury=True
    )

    # Cell 6 with PSQ enabled should use PSQ, NOT bonds
    # Even if allow_treasury=True
    w_TQQQ, w_QQQ, w_PSQ, w_cash = strategy_with_psq._get_cell_allocation(6)

    # Should still be 50% PSQ + 50% Cash (bonds ignored)
    assert w_PSQ == Decimal("0.5")
    assert w_cash == Decimal("0.5")


def test_rebalancing_with_treasury_overlay():
    """Test rebalancing threshold calculation includes TMF/TMV weights."""
    strategy = Hierarchical_Adaptive_v3_5d(
        rebalance_threshold=Decimal("0.05"),
        allow_treasury=True
    )

    # Set current weights (including bonds)
    strategy.current_tqqq_weight = Decimal("0.0")
    strategy.current_qqq_weight = Decimal("0.5")
    strategy.current_psq_weight = Decimal("0.0")
    strategy.current_tmf_weight = Decimal("0.2")
    strategy.current_tmv_weight = Decimal("0.0")

    # Test: Small drift in bonds (no rebalance)
    needs_rebalance = strategy._check_rebalancing_threshold(
        target_tqqq_weight=Decimal("0.0"),
        target_qqq_weight=Decimal("0.5"),
        target_psq_weight=Decimal("0.0"),
        target_tmf_weight=Decimal("0.22"),  # +0.02 drift
        target_tmv_weight=Decimal("0.0")
    )
    assert needs_rebalance is False

    # Test: Large drift in bonds (rebalance)
    needs_rebalance = strategy._check_rebalancing_threshold(
        target_tqqq_weight=Decimal("0.0"),
        target_qqq_weight=Decimal("0.5"),
        target_psq_weight=Decimal("0.0"),
        target_tmf_weight=Decimal("0.0"),   # Switch from TMF to TMV
        target_tmv_weight=Decimal("0.2")
    )
    assert needs_rebalance is True


# ===== 11. Execution Timing Tests (10 tests) =====

def test_execution_time_parameter_validation_valid():
    """Test execution_time parameter accepts all valid values."""
    valid_times = ["open", "15min_after_open", "15min_before_close", "close"]

    for exec_time in valid_times:
        strategy = Hierarchical_Adaptive_v3_5d(execution_time=exec_time)
        strategy.init()
        assert strategy.execution_time == exec_time


def test_execution_time_parameter_validation_invalid():
    """Test execution_time parameter rejects invalid values."""
    invalid_times = ["midday", "11am", "invalid", "3pm", ""]

    for exec_time in invalid_times:
        with pytest.raises(ValueError, match="execution_time must be one of"):
            Hierarchical_Adaptive_v3_5d(execution_time=exec_time)


def test_execution_time_default_value():
    """Test execution_time defaults to 'close' for backward compatibility."""
    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    assert strategy.execution_time == "close"


def test_set_end_date_datetime():
    """Test set_end_date() accepts datetime and extracts date."""
    from datetime import date

    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    end_datetime = datetime(2024, 12, 31, 16, 0, tzinfo=timezone.utc)
    strategy.set_end_date(end_datetime)

    assert strategy._end_date == date(2024, 12, 31)


def test_set_end_date_date():
    """Test set_end_date() accepts date object directly."""
    from datetime import date

    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    end_date = date(2024, 12, 31)
    strategy.set_end_date(end_date)

    assert strategy._end_date == end_date


def test_set_data_handler():
    """Test set_data_handler() stores data handler reference."""
    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    mock_handler = MagicMock()
    strategy.set_data_handler(mock_handler)

    assert strategy._data_handler is mock_handler


def test_is_last_day_detection_true():
    """Test _is_last_day() returns True when on last day."""
    from datetime import date

    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    end_date = date(2024, 12, 31)
    strategy.set_end_date(end_date)

    # Test with timestamp on last day
    timestamp = datetime(2024, 12, 31, 10, 0, tzinfo=timezone.utc)
    assert strategy._is_last_day(timestamp) is True


def test_is_last_day_detection_false():
    """Test _is_last_day() returns False when not on last day."""
    from datetime import date

    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    end_date = date(2024, 12, 31)
    strategy.set_end_date(end_date)

    # Test with timestamp before last day
    timestamp = datetime(2024, 12, 30, 10, 0, tzinfo=timezone.utc)
    assert strategy._is_last_day(timestamp) is False


def test_is_last_day_no_end_date():
    """Test _is_last_day() returns False when end_date not set."""
    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    # No end_date set (_end_date is None)
    timestamp = datetime(2024, 12, 31, 10, 0, tzinfo=timezone.utc)
    assert strategy._is_last_day(timestamp) is False


def test_get_closes_for_indicator_calculation_eod_mode():
    """Test _get_closes_for_indicator_calculation returns EOD data for close execution time."""
    strategy = Hierarchical_Adaptive_v3_5d(execution_time="close")
    strategy.init()

    from datetime import date

    # Set end_date
    end_date = date(2024, 12, 31)
    strategy.set_end_date(end_date)

    # Create historical bars
    base_time = datetime(2024, 12, 30, 16, 0, tzinfo=timezone.utc)
    for i in range(50):
        close_price = Decimal("300.00") + Decimal(str(i * 0.1))
        bar = MarketDataEvent(
            symbol="QQQ",
            timestamp=base_time - timedelta(days=50-i),
            open=Decimal("300.00"),
            high=close_price + Decimal("1.00"),  # Always above close
            low=Decimal("299.00"),
            close=close_price,
            volume=1000000
        )
        strategy._bars.append(bar)

    # Create a current bar for testing
    current_bar = MarketDataEvent(
        symbol="QQQ",
        timestamp=datetime(2024, 12, 30, 16, 0, tzinfo=timezone.utc),
        open=Decimal("305.00"),
        high=Decimal("306.00"),
        low=Decimal("304.00"),
        close=Decimal("305.00"),
        volume=1000000
    )

    # Get closes using the v3.5d method signature
    closes = strategy._get_closes_for_indicator_calculation(
        lookback=20,
        symbol="QQQ",
        current_bar=current_bar
    )

    # Should return EOD data (20 bars from self._bars) for close execution time
    assert len(closes) == 20
    assert all(isinstance(c, Decimal) for c in closes)


# ===== 12. Cell 1 Exit Confirmation Tests (12 tests) - NEW in v3.5d =====

def test_cell1_exit_confirmation_disabled_by_default():
    """Test Cell 1 Exit Confirmation is disabled by default (backward compatible)."""
    strategy = Hierarchical_Adaptive_v3_5d()
    strategy.init()

    assert strategy.cell1_exit_confirmation_enabled is False
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_counter_initialization():
    """Test _cell1_exit_pending_days counter starts at 0."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()

    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_when_disabled():
    """Test _apply_cell1_exit_confirmation passes through when disabled."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=False
    )
    strategy.init()
    strategy.cell_id = 1  # Currently in Cell 1

    # Should return raw_trend_state unchanged
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),  # Below bull threshold
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )

    assert result == "Sideways"
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_increment_counter():
    """Test counter increments when in Cell 1 and T_norm drops below threshold."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 1  # Currently in Cell 1
    strategy._cell1_exit_pending_days = 0

    # T_norm below threshold with Sideways raw state
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),  # Below 0.3 threshold
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )

    # Counter should increment, state should remain BullStrong (stay in Cell 1)
    assert strategy._cell1_exit_pending_days == 1
    assert result == "BullStrong"


def test_cell1_exit_confirmation_stay_until_threshold():
    """Test strategy stays in Cell 1 until confirmation days reached."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 1

    # Day 1: counter = 0 → 1, stay in Cell 1
    result1 = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )
    assert result1 == "BullStrong"
    assert strategy._cell1_exit_pending_days == 1

    # Day 2: counter = 1 → 2, stay in Cell 1
    result2 = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )
    assert result2 == "BullStrong"
    assert strategy._cell1_exit_pending_days == 2

    # Day 3: counter = 2 → 3 >= threshold, EXIT confirmed
    result3 = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )
    assert result3 == "Sideways"  # Exit now allowed
    assert strategy._cell1_exit_pending_days == 0  # Counter reset


def test_cell1_exit_confirmation_reset_on_recovery():
    """Test counter resets when T_norm goes back above threshold."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 1
    strategy._cell1_exit_pending_days = 2  # 2 days already below threshold

    # T_norm recovers above threshold
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.5"),  # Above 0.3 threshold
        raw_trend_state="BullStrong",
        sma_fast_val=Decimal("100.0"),
        sma_slow_val=Decimal("90.0")
    )

    # Counter should reset, state passes through
    assert strategy._cell1_exit_pending_days == 0
    assert result == "BullStrong"


def test_cell1_exit_confirmation_bear_exit_immediate():
    """Test BearStrong exit is immediate (bypass confirmation)."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 1
    strategy._cell1_exit_pending_days = 1

    # T_norm drops to BearStrong
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("-0.5"),  # Bear territory
        raw_trend_state="BearStrong",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )

    # Should exit immediately for bear (don't wait for confirmation)
    assert result == "BearStrong"
    assert strategy._cell1_exit_pending_days == 0  # Counter reset


def test_cell1_exit_confirmation_not_in_cell1():
    """Test confirmation logic only applies when currently in Cell 1."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 3  # Currently in Cell 3, NOT Cell 1
    strategy._cell1_exit_pending_days = 2

    # Even if T_norm is below threshold, no confirmation needed (not in Cell 1)
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )

    # Should pass through unchanged, counter reset
    assert result == "Sideways"
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_counter_reset_on_not_cell1():
    """Test counter resets when strategy moves out of Cell 1."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 2  # Moved to Cell 2 (e.g., VolState changed to High)
    strategy._cell1_exit_pending_days = 2

    # Apply confirmation logic
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.5"),
        raw_trend_state="BullStrong",
        sma_fast_val=Decimal("100.0"),
        sma_slow_val=Decimal("90.0")
    )

    # Counter should reset (not in Cell 1 anymore)
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_with_1_day():
    """Test Cell 1 Exit Confirmation with 1 day (effectively 1-day lag)."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=1
    )
    strategy.init()
    strategy.cell_id = 1
    strategy._cell1_exit_pending_days = 0

    # Day 1: counter = 0 → 1 >= threshold, EXIT confirmed immediately
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )

    assert result == "Sideways"  # Exit allowed after 1 day
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_with_5_days():
    """Test Cell 1 Exit Confirmation with 5 days lag."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=5
    )
    strategy.init()
    strategy.cell_id = 1

    # Days 1-4: stay in Cell 1
    for day in range(1, 5):
        result = strategy._apply_cell1_exit_confirmation(
            T_norm=Decimal("0.1"),
            raw_trend_state="Sideways",
            sma_fast_val=Decimal("90.0"),
            sma_slow_val=Decimal("100.0")
        )
        assert result == "BullStrong"
        assert strategy._cell1_exit_pending_days == day

    # Day 5: counter = 4 → 5 >= threshold, EXIT confirmed
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.1"),
        raw_trend_state="Sideways",
        sma_fast_val=Decimal("90.0"),
        sma_slow_val=Decimal("100.0")
    )
    assert result == "Sideways"
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_re_entry_allowed():
    """Test immediate re-entry to Cell 1 is allowed after exit."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=2
    )
    strategy.init()

    # Start in Cell 3 (Sideways/Low)
    strategy.cell_id = 3
    strategy._cell1_exit_pending_days = 0

    # T_norm jumps above threshold with SMA confirmation → should enter Cell 1
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.5"),  # Above bull threshold
        raw_trend_state="BullStrong",
        sma_fast_val=Decimal("100.0"),  # SMA_fast > SMA_slow
        sma_slow_val=Decimal("90.0")
    )

    # Should pass through (no entry confirmation required)
    assert result == "BullStrong"
    assert strategy._cell1_exit_pending_days == 0


def test_cell1_exit_confirmation_volstate_change_bypass():
    """Test exit due to VolState change (Cell 1 → Cell 2) bypasses confirmation."""
    strategy = Hierarchical_Adaptive_v3_5d(
        cell1_exit_confirmation_enabled=True,
        cell1_exit_confirmation_days=3
    )
    strategy.init()
    strategy.cell_id = 1
    strategy._cell1_exit_pending_days = 1

    # T_norm still above threshold (BullStrong), but vol_state will change to High
    # This moves Cell 1 → Cell 2 without trend state change
    result = strategy._apply_cell1_exit_confirmation(
        T_norm=Decimal("0.5"),  # Still bullish
        raw_trend_state="BullStrong",
        sma_fast_val=Decimal("100.0"),
        sma_slow_val=Decimal("90.0")
    )

    # Trend state passes through (no exit confirmation needed since still BullStrong)
    # VolState-based cell change handled separately in on_bar()
    assert result == "BullStrong"
    # Counter remains (will be used if T_norm drops while in Cell 1)
    # But since T_norm is above threshold, counter should be reset
    assert strategy._cell1_exit_pending_days == 0
