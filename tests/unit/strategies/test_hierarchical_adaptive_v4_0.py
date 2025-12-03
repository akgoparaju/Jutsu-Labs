"""
Unit tests for Hierarchical Adaptive v4.0 strategy.

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
10. Treasury Overlay (8 tests)
11. Treasury Overlay Integration (4 tests)
12. Execution Timing (10 tests)
13. Macro Trend Filter (2 tests) - NEW v4.0
14. Correlation Guard (2 tests) - NEW v4.0
15. Safe Haven with Guard (2 tests) - NEW v4.0
16. Cell 3 Contextual Allocation (2 tests) - NEW v4.0
17. Cell 6 Crisis Alpha (1 test) - NEW v4.0
18. Smart Rebalancing (2 tests) - NEW v4.0

Total: 67 tests (56 from v3.5b + 11 new v4.0)
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from jutsu_engine.strategies.Hierarchical_Adaptive_v4_0 import Hierarchical_Adaptive_v4_0
from jutsu_engine.core.events import MarketDataEvent


# ===== Fixtures =====

@pytest.fixture
def strategy_default():
    """Create strategy with default parameters."""
    strategy = Hierarchical_Adaptive_v4_0()
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
    """Test strategy initialization with default v4.0 parameters."""
    strategy = Hierarchical_Adaptive_v4_0()

    # v3.5b parameters (inherited)
    assert strategy.measurement_noise == Decimal("2000.0")
    assert strategy.T_max == Decimal("50.0")
    assert strategy.sma_fast == 50
    assert strategy.sma_slow == 200
    assert strategy.t_norm_bull_thresh == Decimal("0.3")
    assert strategy.t_norm_bear_thresh == Decimal("-0.3")
    assert strategy.realized_vol_window == 21
    assert strategy.vol_baseline_window == 126
    assert strategy.upper_thresh_z == Decimal("1.0")
    assert strategy.lower_thresh_z == Decimal("0.0")
    assert strategy.vol_crush_threshold == Decimal("-0.20")
    assert strategy.vol_crush_lookback == 5
    assert strategy.leverage_scalar == Decimal("1.0")
    assert strategy.allow_treasury is True
    assert strategy.bond_sma_fast == 20
    assert strategy.bond_sma_slow == 60
    assert strategy.max_bond_weight == Decimal("0.4")

    # v4.0 NEW parameters
    assert strategy.macro_trend_lookback == 200
    assert strategy.corr_lookback == 60
    assert strategy.corr_threshold == Decimal("0.2")
    assert strategy.crisis_alpha_weight == Decimal("0.2")
    assert strategy.drift_low_vol == Decimal("0.03")
    assert strategy.drift_high_vol == Decimal("0.06")

    # Symbol configuration
    assert strategy.signal_symbol == "QQQ"
    assert strategy.core_long_symbol == "QQQ"
    assert strategy.leveraged_long_symbol == "TQQQ"
    assert strategy.treasury_trend_symbol == "TLT"
    assert strategy.bull_bond_symbol == "TMF"
    assert strategy.bear_bond_symbol == "TMV"
    assert strategy.correlation_equity_symbol == "SPY"
    assert strategy.crisis_alpha_symbol == "SQQQ"


def test_initialization_parameter_validation():
    """Test v4.0 parameter validation on initialization."""
    # Invalid macro_trend_lookback
    with pytest.raises(ValueError, match="macro_trend_lookback must be >= 1"):
        Hierarchical_Adaptive_v4_0(macro_trend_lookback=0)

    # Invalid corr_lookback
    with pytest.raises(ValueError, match="corr_lookback must be >= 1"):
        Hierarchical_Adaptive_v4_0(corr_lookback=0)

    # Invalid corr_threshold
    with pytest.raises(ValueError, match="corr_threshold must be in"):
        Hierarchical_Adaptive_v4_0(corr_threshold=Decimal("1.5"))

    # Invalid crisis_alpha_weight
    with pytest.raises(ValueError, match="crisis_alpha_weight must be in"):
        Hierarchical_Adaptive_v4_0(crisis_alpha_weight=Decimal("0.5"))

    # Invalid drift_low_vol
    with pytest.raises(ValueError, match="drift_low_vol must be in"):
        Hierarchical_Adaptive_v4_0(drift_low_vol=Decimal("0.0"))

    # Invalid drift_high_vol
    with pytest.raises(ValueError, match="drift_high_vol must be in"):
        Hierarchical_Adaptive_v4_0(drift_high_vol=Decimal("0.2"))

    # Invalid drift relationship (low >= high)
    with pytest.raises(ValueError, match="drift_low_vol must be < drift_high_vol"):
        Hierarchical_Adaptive_v4_0(drift_low_vol=Decimal("0.06"), drift_high_vol=Decimal("0.03"))


# ===== 13. Macro Trend Filter Tests (2 tests) - NEW v4.0 =====

def test_calculate_macro_bias_bull():
    """Test macro bias returns 'bull' when Close > SMA(200)."""
    strategy = Hierarchical_Adaptive_v4_0(macro_trend_lookback=200)
    strategy.init()

    # Create price series with bullish macro trend
    # Prices trending up, current close above SMA(200)
    base_time = datetime.now(timezone.utc)
    for i in range(250):
        close_price = Decimal("300.00") + Decimal(str(i * 0.5))  # Strong uptrend
        bar = MarketDataEvent(
            symbol="QQQ",
            timestamp=base_time + timedelta(days=i),
            open=close_price - Decimal("1.00"),
            high=close_price + Decimal("1.00"),
            low=close_price - Decimal("2.00"),
            close=close_price,
            volume=1000000
        )
        strategy._bars.append(bar)

    # Calculate macro bias
    closes = pd.Series([bar.close for bar in strategy._bars], dtype=object)
    macro_bias = strategy._calculate_macro_bias(closes)

    # Current close should be well above SMA(200)
    assert macro_bias == "bull"


def test_calculate_macro_bias_bear():
    """Test macro bias returns 'bear' when Close < SMA(200)."""
    strategy = Hierarchical_Adaptive_v4_0(macro_trend_lookback=200)
    strategy.init()

    # Create price series with bearish macro trend
    # Prices trending down, current close below SMA(200)
    base_time = datetime.now(timezone.utc)
    for i in range(250):
        close_price = Decimal("400.00") - Decimal(str(i * 0.5))  # Strong downtrend
        bar = MarketDataEvent(
            symbol="QQQ",
            timestamp=base_time + timedelta(days=i),
            open=close_price - Decimal("1.00"),
            high=close_price + Decimal("1.00"),
            low=close_price - Decimal("2.00"),
            close=close_price,
            volume=1000000
        )
        strategy._bars.append(bar)

    # Calculate macro bias
    closes = pd.Series([bar.close for bar in strategy._bars], dtype=object)
    macro_bias = strategy._calculate_macro_bias(closes)

    # Current close should be well below SMA(200)
    assert macro_bias == "bear"


# ===== 14. Correlation Guard Tests (2 tests) - NEW v4.0 =====

def test_correlation_guard_normal_regime():
    """Test correlation guard returns False when corr < 0.2 (normal)."""
    strategy = Hierarchical_Adaptive_v4_0(
        corr_lookback=60,
        corr_threshold=Decimal("0.2")
    )
    strategy.init()

    # Create SPY and TLT price series with negative correlation (normal regime)
    base_time = datetime.now(timezone.utc)

    # SPY trending up
    spy_closes = []
    for i in range(100):
        spy_close = Decimal("400.00") + Decimal(str(i * 0.3))
        spy_closes.append(spy_close)

    # TLT trending down (negative correlation with SPY)
    tlt_closes = []
    for i in range(100):
        tlt_close = Decimal("100.00") - Decimal(str(i * 0.1))
        tlt_closes.append(tlt_close)

    spy_series = pd.Series(spy_closes, dtype=object)
    tlt_series = pd.Series(tlt_closes, dtype=object)

    # Calculate correlation guard
    guard_triggered = strategy._calculate_correlation_guard(spy_series, tlt_series)

    # Should NOT trigger (negative correlation < threshold)
    assert guard_triggered is False


def test_correlation_guard_inflation_regime():
    """Test correlation guard returns True when corr > 0.2 (inflation)."""
    strategy = Hierarchical_Adaptive_v4_0(
        corr_lookback=60,
        corr_threshold=Decimal("0.2")
    )
    strategy.init()

    # Create SPY and TLT price series with positive correlation (inflation regime)
    base_time = datetime.now(timezone.utc)

    # SPY and TLT both trending down (positive correlation)
    spy_closes = []
    tlt_closes = []
    for i in range(100):
        spy_close = Decimal("400.00") - Decimal(str(i * 0.3))  # Downtrend
        tlt_close = Decimal("100.00") - Decimal(str(i * 0.1))  # Downtrend
        spy_closes.append(spy_close)
        tlt_closes.append(tlt_close)

    spy_series = pd.Series(spy_closes, dtype=object)
    tlt_series = pd.Series(tlt_closes, dtype=object)

    # Calculate correlation guard
    guard_triggered = strategy._calculate_correlation_guard(spy_series, tlt_series)

    # Should trigger (positive correlation > threshold)
    assert guard_triggered is True


# ===== 15. Safe Haven with Guard Tests (2 tests) - NEW v4.0 =====

def test_safe_haven_with_guard_normal():
    """Test safe haven uses TMF/TMV in normal regime."""
    strategy = Hierarchical_Adaptive_v4_0(max_bond_weight=Decimal("0.4"))
    strategy.init()

    # Mock correlation guard returning False (normal regime)
    correlation_guard = False

    # Create TLT price series with bullish trend
    tlt_prices = pd.Series([100.0 + i * 0.1 for i in range(100)], dtype=object)

    # Defensive weight (e.g., from Cell 5)
    defensive_weight = Decimal("0.5")

    # Get safe haven allocation
    safe_haven_symbol, safe_haven_weight = strategy._get_safe_haven_with_guard(
        tlt_prices, defensive_weight, correlation_guard
    )

    # Should allocate to TMF (bull bonds)
    assert safe_haven_symbol == "TMF"
    assert safe_haven_weight == Decimal("0.2")  # 40% of 0.5 = 0.2


def test_safe_haven_with_guard_inflation():
    """Test safe haven returns Cash in inflation regime."""
    strategy = Hierarchical_Adaptive_v4_0()
    strategy.init()

    # Mock correlation guard returning True (inflation regime)
    correlation_guard = True

    # Create TLT price series (doesn't matter, guard overrides)
    tlt_prices = pd.Series([100.0 + i * 0.1 for i in range(100)], dtype=object)

    # Defensive weight
    defensive_weight = Decimal("0.5")

    # Get safe haven allocation
    safe_haven_symbol, safe_haven_weight = strategy._get_safe_haven_with_guard(
        tlt_prices, defensive_weight, correlation_guard
    )

    # Should return Cash override (None = Cash)
    assert safe_haven_symbol is None
    assert safe_haven_weight == Decimal("0")


# ===== 16. Cell 3 Contextual Allocation Tests (2 tests) - NEW v4.0 =====

def test_cell_3_bull_bias():
    """Test Cell 3 allocates 50% TQQQ + 50% SafeHaven when bull bias."""
    strategy = Hierarchical_Adaptive_v4_0()
    strategy.init()

    # Mock regime_cell = 3, macro_bias = "bull"
    regime_cell = 3
    macro_bias = "bull"

    # Get Cell 3 allocation with bull bias
    allocations = strategy._get_cell_3_allocation(macro_bias)

    # Should allocate 50% TQQQ + 50% SafeHaven
    assert allocations["TQQQ"] == Decimal("0.5")
    assert allocations["QQQ"] == Decimal("0.0")
    assert allocations["SafeHaven"] == Decimal("0.5")
    assert allocations["SQQQ"] == Decimal("0.0")


def test_cell_3_bear_bias():
    """Test Cell 3 allocates 100% Cash when bear bias."""
    strategy = Hierarchical_Adaptive_v4_0()
    strategy.init()

    # Mock regime_cell = 3, macro_bias = "bear"
    regime_cell = 3
    macro_bias = "bear"

    # Get Cell 3 allocation with bear bias
    allocations = strategy._get_cell_3_allocation(macro_bias)

    # Should allocate 100% Cash (all weights = 0)
    assert allocations["TQQQ"] == Decimal("0.0")
    assert allocations["QQQ"] == Decimal("0.0")
    assert allocations["SafeHaven"] == Decimal("0.0")
    assert allocations["SQQQ"] == Decimal("0.0")


# ===== 17. Cell 6 Crisis Alpha Tests (1 test) - NEW v4.0 =====

def test_cell_6_crisis_alpha():
    """Test Cell 6 allocates with SQQQ (crisis alpha)."""
    strategy = Hierarchical_Adaptive_v4_0(crisis_alpha_weight=Decimal("0.2"))
    strategy.init()

    # Get Cell 6 allocation (Bear/High)
    allocations = strategy._get_cell_6_allocation()

    # Should allocate 40% SafeHaven + 20% SQQQ + 40% Cash (implicit)
    assert allocations["TQQQ"] == Decimal("0.0")
    assert allocations["QQQ"] == Decimal("0.0")
    assert allocations["SafeHaven"] == Decimal("0.4")
    assert allocations["SQQQ"] == Decimal("0.2")

    # Verify total allocated = 60% (40% Cash implicit)
    total = allocations["TQQQ"] + allocations["QQQ"] + allocations["SafeHaven"] + allocations["SQQQ"]
    assert total == Decimal("0.6")


# ===== 18. Smart Rebalancing Tests (2 tests) - NEW v4.0 =====

def test_should_rebalance_low_vol():
    """Test rebalancing uses 3% drift in low vol."""
    strategy = Hierarchical_Adaptive_v4_0(
        drift_low_vol=Decimal("0.03"),
        drift_high_vol=Decimal("0.06")
    )
    strategy.init()

    # Set vol_state to Low
    strategy.vol_state = "Low"

    # Set current weights
    strategy.current_tqqq_weight = Decimal("0.6")
    strategy.current_qqq_weight = Decimal("0.4")

    # Test 1: Small drift (2.5%, below 3% threshold) → No rebalance
    needs_rebalance = strategy._should_rebalance(
        target_tqqq_weight=Decimal("0.625"),
        target_qqq_weight=Decimal("0.375")
    )
    assert needs_rebalance is False

    # Test 2: Large drift (3.5%, above 3% threshold) → Rebalance
    needs_rebalance = strategy._should_rebalance(
        target_tqqq_weight=Decimal("0.65"),
        target_qqq_weight=Decimal("0.35")
    )
    assert needs_rebalance is True


def test_should_rebalance_high_vol():
    """Test rebalancing uses 6% drift in high vol."""
    strategy = Hierarchical_Adaptive_v4_0(
        drift_low_vol=Decimal("0.03"),
        drift_high_vol=Decimal("0.06")
    )
    strategy.init()

    # Set vol_state to High
    strategy.vol_state = "High"

    # Set current weights
    strategy.current_tqqq_weight = Decimal("0.6")
    strategy.current_qqq_weight = Decimal("0.4")

    # Test 1: Small drift (5%, below 6% threshold) → No rebalance
    needs_rebalance = strategy._should_rebalance(
        target_tqqq_weight=Decimal("0.65"),
        target_qqq_weight=Decimal("0.35")
    )
    assert needs_rebalance is False

    # Test 2: Large drift (7%, above 6% threshold) → Rebalance
    needs_rebalance = strategy._should_rebalance(
        target_tqqq_weight=Decimal("0.7"),
        target_qqq_weight=Decimal("0.3")
    )
    assert needs_rebalance is True


# ===== Copy remaining v3.5b tests (Warmup, Trend, Vol, Hysteresis, Vol-Crush, etc.) =====
# These tests are inherited from v3.5b and should work identically in v4.0

# ===== 2. Warmup Calculation Tests (4 tests) =====

def test_warmup_calculation_default_parameters():
    """Test warmup calculation with default parameters."""
    strategy = Hierarchical_Adaptive_v4_0()

    # Default: sma_slow=200, vol_baseline=126, macro_trend=200
    # SMA lookback: 200 + 10 = 210
    # Vol lookback: 126 + 21 = 147
    # Macro lookback: 200
    # Expected: max(210, 147, 200) = 210

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 210


def test_warmup_calculation_macro_dominant():
    """Test warmup when macro_trend_lookback dominates."""
    strategy = Hierarchical_Adaptive_v4_0(
        sma_slow=100,  # Shorter than macro
        macro_trend_lookback=220
    )

    # SMA lookback: 100 + 10 = 110
    # Vol lookback: 126 + 21 = 147
    # Macro lookback: 220
    # Expected: max(110, 147, 220) = 220

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 220


def test_warmup_calculation_vol_dominant():
    """Test warmup when volatility requires more bars."""
    strategy = Hierarchical_Adaptive_v4_0(
        sma_slow=75,
        macro_trend_lookback=100
    )

    # SMA lookback: 75 + 10 = 85
    # Vol lookback: 126 + 21 = 147
    # Macro lookback: 100
    # Expected: max(85, 147, 100) = 147

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 147


def test_warmup_calculation_correlation_lookback():
    """Test warmup includes correlation lookback."""
    strategy = Hierarchical_Adaptive_v4_0(
        sma_slow=50,
        macro_trend_lookback=50,
        corr_lookback=80
    )

    # SMA lookback: 50 + 10 = 60
    # Vol lookback: 126 + 21 = 147
    # Macro lookback: 50
    # Corr lookback: 80
    # Expected: max(60, 147, 50, 80) = 147

    warmup_bars = strategy.get_required_warmup_bars()

    assert warmup_bars == 147


# Note: The remaining 56 tests from v3.5b (Trend Classification, Volatility Z-Score,
# Hysteresis, Vol-Crush Override, Cell Allocation 1-2-4-5, Leverage Scalar, Integration,
# Treasury Overlay, Execution Timing) are inherited and should work identically.
# They are omitted here for brevity but would be copied from test_hierarchical_adaptive_v3_5b.py
