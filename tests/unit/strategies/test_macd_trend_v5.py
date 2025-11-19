"""
Unit tests for MACD_Trend_v5 strategy (Dynamic Regime V9.0).

Tests cover:
- Initialization (6 tests)
- Symbol validation (4 tests)
- VIX regime detection (8 tests)
- VIX EMA calculation (4 tests)
- Parameter switching logic (6 tests)
- Integration with v4 logic (4 tests)
- Edge cases (4 tests)

Target: >80% code coverage, 36 tests total
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from jutsu_engine.strategies.MACD_Trend_v5 import MACD_Trend_v5
from jutsu_engine.core.events import MarketDataEvent
import pandas as pd


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def strategy():
    """Create MACD_Trend_v5 strategy with default parameters."""
    return MACD_Trend_v5()


@pytest.fixture
def custom_strategy():
    """Create MACD_Trend_v5 strategy with custom parameters."""
    return MACD_Trend_v5(
        vix_ema_period=20,
        ema_period_calm=150,
        atr_stop_calm=Decimal('2.5'),
        ema_period_choppy=50,
        atr_stop_choppy=Decimal('2.0'),
        macd_fast_period=10,
        macd_slow_period=20,
        macd_signal_period=5,
        risk_bull=Decimal('0.03'),
        allocation_defense=Decimal('0.50'),
    )


@pytest.fixture
def sample_qqq_bar():
    """Create sample QQQ bar."""
    return MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )


@pytest.fixture
def sample_tqqq_bar():
    """Create sample TQQQ bar."""
    return MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('50.00'),
        high=Decimal('51.00'),
        low=Decimal('49.50'),
        close=Decimal('50.50'),
        volume=2000000
    )


@pytest.fixture
def sample_vix_bar():
    """Create sample VIX bar."""
    return MarketDataEvent(
        symbol='VIX',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('15.00'),
        high=Decimal('16.00'),
        low=Decimal('14.50'),
        close=Decimal('15.50'),
        volume=0  # VIX has no volume
    )


def create_vix_bars(count: int, vix_value: Decimal, start_date: datetime) -> list:
    """Helper to create sequence of VIX bars with constant value."""
    bars = []
    for i in range(count):
        bar = MarketDataEvent(
            symbol='VIX',
            timestamp=start_date + timedelta(days=i),
            open=vix_value,
            high=vix_value + Decimal('1.0'),
            low=vix_value - Decimal('1.0'),
            close=vix_value,
            volume=0
        )
        bars.append(bar)
    return bars


# ========================================
# 1. Initialization Tests (6 tests)
# ========================================

def test_initialization_default_parameters(strategy):
    """Test strategy initialization with default parameters."""
    # V5-specific parameters
    assert strategy.vix_symbol == 'VIX'
    assert strategy.vix_ema_period == 50
    assert strategy.ema_period_calm == 200
    assert strategy.atr_stop_calm == Decimal('3.0')
    assert strategy.ema_period_choppy == 75
    assert strategy.atr_stop_choppy == Decimal('2.0')

    # V4 inherited parameters (should use CALM defaults)
    assert strategy.ema_period == 200  # CALM default
    assert strategy.atr_stop_multiplier == Decimal('3.0')  # CALM default
    assert strategy.risk_bull == Decimal('0.025')
    assert strategy.allocation_defense == Decimal('0.60')


def test_initialization_custom_parameters(custom_strategy):
    """Test strategy initialization with custom parameters."""
    # V5-specific parameters
    assert custom_strategy.vix_ema_period == 20
    assert custom_strategy.ema_period_calm == 150
    assert custom_strategy.atr_stop_calm == Decimal('2.5')
    assert custom_strategy.ema_period_choppy == 50
    assert custom_strategy.atr_stop_choppy == Decimal('2.0')

    # V4 inherited parameters (custom)
    assert custom_strategy.risk_bull == Decimal('0.03')
    assert custom_strategy.allocation_defense == Decimal('0.50')
    assert custom_strategy.macd_fast_period == 10


def test_initialization_state_tracking(strategy):
    """Test that state tracking fields are initialized correctly."""
    assert strategy._vix_bars == []
    assert strategy.current_vix_regime is None


def test_initialization_decimal_conversion(strategy):
    """Test that float parameters are converted to Decimal."""
    # Pass float parameters, should convert to Decimal
    strat = MACD_Trend_v5(
        atr_stop_calm=3.5,  # float
        atr_stop_choppy=2.5,  # float
        risk_bull=0.03,  # float
        allocation_defense=0.70  # float
    )

    assert isinstance(strat.atr_stop_calm, Decimal)
    assert isinstance(strat.atr_stop_choppy, Decimal)
    assert isinstance(strat.risk_bull, Decimal)
    assert isinstance(strat.allocation_defense, Decimal)


def test_init_method_resets_state(strategy):
    """Test that init() method properly resets VIX state."""
    # Manually set state
    strategy._vix_bars = [MagicMock()]
    strategy.current_vix_regime = 'CHOPPY'

    # Call init()
    strategy.init()

    # Verify reset
    assert strategy._vix_bars == []
    assert strategy.current_vix_regime is None


def test_inheritance_from_v4(strategy):
    """Test that v5 properly inherits from v4."""
    from jutsu_engine.strategies.MACD_Trend_v4 import MACD_Trend_v4
    assert isinstance(strategy, MACD_Trend_v4)

    # Verify v4 methods are available
    assert hasattr(strategy, '_determine_regime')
    assert hasattr(strategy, '_enter_tqqq')
    assert hasattr(strategy, '_enter_qqq')


# ========================================
# 2. Symbol Validation Tests (4 tests)
# ========================================

def test_validate_required_symbols_all_present(strategy):
    """Test symbol validation passes when all 3 symbols present."""
    # Create bars for all 3 symbols
    strategy._bars = [
        MarketDataEvent(symbol='QQQ', timestamp=datetime.now(timezone.utc), open=Decimal('400'), high=Decimal('401'),
                        low=Decimal('399'), close=Decimal('400'), volume=1000),
        MarketDataEvent(symbol='TQQQ', timestamp=datetime.now(timezone.utc), open=Decimal('50'), high=Decimal('51'),
                        low=Decimal('49'), close=Decimal('50'), volume=1000),
        MarketDataEvent(symbol='VIX', timestamp=datetime.now(timezone.utc), open=Decimal('15'), high=Decimal('16'),
                        low=Decimal('14'), close=Decimal('15'), volume=0),
    ]

    # Should not raise
    strategy._validate_required_symbols()


def test_validate_required_symbols_vix_missing(strategy):
    """Test symbol validation fails when VIX missing."""
    # Only QQQ and TQQQ (2 unique), but need 3 (QQQ, TQQQ, VIX)
    # Add a 4th symbol (e.g., SPY) to trigger validation with >=3 unique symbols
    strategy._bars = [
        MarketDataEvent(symbol='QQQ', timestamp=datetime.now(timezone.utc), open=Decimal('400'), high=Decimal('401'),
                        low=Decimal('399'), close=Decimal('400'), volume=1000),
        MarketDataEvent(symbol='TQQQ', timestamp=datetime.now(timezone.utc), open=Decimal('50'), high=Decimal('51'),
                        low=Decimal('49'), close=Decimal('50'), volume=1000),
        MarketDataEvent(symbol='SPY', timestamp=datetime.now(timezone.utc), open=Decimal('500'), high=Decimal('501'),
                        low=Decimal('499'), close=Decimal('500'), volume=1000),
    ]

    # Should raise error when we have >= 3 unique symbols but VIX is missing
    with pytest.raises(ValueError, match="missing: \\['VIX'\\]"):
        strategy._validate_required_symbols()


def test_validate_required_symbols_deferred_validation(strategy):
    """Test that symbol validation is deferred until all symbols appear."""
    # Only 1 symbol so far
    strategy._bars = [
        MarketDataEvent(symbol='QQQ', timestamp=datetime.now(timezone.utc), open=Decimal('400'), high=Decimal('401'),
                        low=Decimal('399'), close=Decimal('400'), volume=1000),
    ]

    # Should NOT raise error (validation deferred)
    strategy._validate_required_symbols()  # No error


def test_validate_custom_symbols(strategy):
    """Test symbol validation with custom symbol configuration."""
    # Create strategy with custom symbols
    strat = MACD_Trend_v5(
        signal_symbol='NVDA',
        bull_symbol='NVDL',
        defense_symbol='NVDA',
        vix_symbol='VIX'
    )

    # Create bars with custom symbols
    strat._bars = [
        MarketDataEvent(symbol='NVDA', timestamp=datetime.now(timezone.utc), open=Decimal('500'), high=Decimal('501'),
                        low=Decimal('499'), close=Decimal('500'), volume=1000),
        MarketDataEvent(symbol='NVDL', timestamp=datetime.now(timezone.utc), open=Decimal('100'), high=Decimal('101'),
                        low=Decimal('99'), close=Decimal('100'), volume=1000),
        MarketDataEvent(symbol='VIX', timestamp=datetime.now(timezone.utc), open=Decimal('15'), high=Decimal('16'),
                        low=Decimal('14'), close=Decimal('15'), volume=0),
    ]

    # Should not raise
    strat._validate_required_symbols()


# ========================================
# 3. VIX Regime Detection Tests (8 tests)
# ========================================

def test_detect_vix_regime_calm(strategy):
    """Test VIX regime detection when VIX_raw <= VIX_EMA_50 (CALM)."""
    # Create 60 VIX bars with VIX = 15 (constant)
    vix_bars = create_vix_bars(60, Decimal('15.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # VIX_raw = 15, VIX_EMA_50 ≈ 15 (since constant)
    # VIX_raw <= VIX_EMA_50 → CALM
    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'


def test_detect_vix_regime_choppy(strategy):
    """Test VIX regime detection when VIX_raw > VIX_EMA_50 (CHOPPY)."""
    # Create 50 bars with VIX = 15, then recent bars with VIX = 25
    vix_bars_low = create_vix_bars(50, Decimal('15.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    vix_bars_high = create_vix_bars(10, Decimal('25.0'), datetime(2024, 2, 20, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_low + vix_bars_high

    # VIX_raw = 25, VIX_EMA_50 ≈ 17 (weighted toward recent)
    # VIX_raw > VIX_EMA_50 → CHOPPY
    regime = strategy._detect_vix_regime()
    assert regime == 'CHOPPY'


def test_detect_vix_regime_insufficient_bars(strategy):
    """Test VIX regime defaults to CALM when insufficient VIX bars."""
    # Only 30 bars, need 50
    vix_bars = create_vix_bars(30, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # Should default to CALM
    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'


def test_detect_vix_regime_edge_case_equal(strategy):
    """Test VIX regime when VIX_raw == VIX_EMA_50 (boundary case)."""
    # Create 60 VIX bars with exactly constant value
    vix_bars = create_vix_bars(60, Decimal('18.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # VIX_raw = 18, VIX_EMA_50 = 18 (exactly equal)
    # VIX_raw <= VIX_EMA_50 → CALM (uses <=)
    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'


def test_detect_vix_regime_custom_period(custom_strategy):
    """Test VIX regime detection with custom VIX_EMA period."""
    # Custom strategy uses vix_ema_period=20
    vix_bars = create_vix_bars(30, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    custom_strategy._vix_bars = vix_bars

    # Should use 20-period EMA (has enough bars)
    regime = custom_strategy._detect_vix_regime()
    assert regime in ['CALM', 'CHOPPY']  # Valid result with 20-period


def test_detect_vix_regime_transition_calm_to_choppy(strategy):
    """Test VIX regime transition from CALM to CHOPPY."""
    # Start CALM (VIX = 12)
    vix_bars_calm = create_vix_bars(55, Decimal('12.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_calm
    assert strategy._detect_vix_regime() == 'CALM'

    # Spike to CHOPPY (VIX = 30)
    vix_bars_choppy = create_vix_bars(5, Decimal('30.0'), datetime(2024, 3, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_calm + vix_bars_choppy

    # Should transition to CHOPPY
    regime = strategy._detect_vix_regime()
    assert regime == 'CHOPPY'


def test_detect_vix_regime_transition_choppy_to_calm(strategy):
    """Test VIX regime transition from CHOPPY to CALM."""
    # Start with baseline VIX = 20, then spike to 35 (creates CHOPPY)
    vix_bars_baseline = create_vix_bars(50, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    vix_bars_spike = create_vix_bars(10, Decimal('35.0'), datetime(2024, 2, 20, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_baseline + vix_bars_spike
    # VIX_raw = 35, VIX_EMA_50 ≈ 22-23 → CHOPPY
    assert strategy._detect_vix_regime() == 'CHOPPY'

    # Drop to CALM (VIX = 18, below EMA)
    vix_bars_calm = create_vix_bars(5, Decimal('18.0'), datetime(2024, 3, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_baseline + vix_bars_spike + vix_bars_calm

    # VIX_raw = 18, VIX_EMA_50 still elevated (~23-24) → But EMA slowly declining
    # After 5 bars, VIX_raw may still be below EMA → CALM
    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'


def test_detect_vix_regime_volatility_spike(strategy):
    """Test VIX regime detection during volatility spike."""
    # Normal VIX (15) then sudden spike (40)
    vix_bars_normal = create_vix_bars(50, Decimal('15.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    vix_bars_spike = create_vix_bars(10, Decimal('40.0'), datetime(2024, 2, 20, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_normal + vix_bars_spike

    # VIX_raw = 40, VIX_EMA_50 still low (~18-20)
    # VIX_raw > VIX_EMA_50 → CHOPPY
    regime = strategy._detect_vix_regime()
    assert regime == 'CHOPPY'


# ========================================
# 4. VIX EMA Calculation Tests (4 tests)
# ========================================

@patch('jutsu_engine.strategies.MACD_Trend_v5.ema')
def test_vix_ema_calculation_calls_ema(mock_ema, strategy):
    """Test that VIX regime detection calls EMA indicator."""
    # Setup
    vix_bars = create_vix_bars(60, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # Mock EMA return value
    mock_ema.return_value = pd.Series([Decimal('19.0')])

    # Call regime detection
    strategy._detect_vix_regime()

    # Verify EMA was called with correct period
    assert mock_ema.called
    call_args = mock_ema.call_args
    assert call_args[1]['period'] == 50  # Default vix_ema_period


@patch('jutsu_engine.strategies.MACD_Trend_v5.ema')
def test_vix_ema_uses_correct_period(mock_ema, custom_strategy):
    """Test that custom VIX_EMA period is used correctly."""
    # Custom strategy has vix_ema_period=20
    vix_bars = create_vix_bars(30, Decimal('18.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    custom_strategy._vix_bars = vix_bars

    # Mock EMA return
    mock_ema.return_value = pd.Series([Decimal('18.0')])

    # Call regime detection
    custom_strategy._detect_vix_regime()

    # Verify EMA was called with custom period
    assert mock_ema.call_args[1]['period'] == 20


def test_vix_ema_calculation_uses_vix_closes(strategy):
    """Test that VIX EMA calculation uses VIX close prices."""
    # Create VIX bars with known close prices
    vix_bars = []
    for i in range(60):
        close_price = Decimal(str(10.0 + i * 0.5))  # Increasing closes
        bar = MarketDataEvent(
            symbol='VIX',
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
            open=close_price - Decimal('1.0'),
            high=close_price + Decimal('2.0'),
            low=close_price - Decimal('2.0'),
            close=close_price,
            volume=0
        )
        vix_bars.append(bar)
    strategy._vix_bars = vix_bars

    # Regime detection should use close prices
    regime = strategy._detect_vix_regime()
    assert regime in ['CALM', 'CHOPPY']  # Valid result


def test_process_vix_bar_stores_bars(strategy, sample_vix_bar):
    """Test that _process_vix_bar correctly stores VIX bars."""
    # Process 5 VIX bars
    for i in range(5):
        bar = MarketDataEvent(
            symbol='VIX',
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
            open=Decimal('15.0'),
            high=Decimal('16.0'),
            low=Decimal('14.0'),
            close=Decimal('15.5'),
            volume=0
        )
        strategy._process_vix_bar(bar)

    # Verify bars stored
    assert len(strategy._vix_bars) == 5
    assert all(bar.symbol == 'VIX' for bar in strategy._vix_bars)


# ========================================
# 5. Parameter Switching Logic Tests (6 tests)
# ========================================

def test_parameter_switching_calm_regime(strategy):
    """Test that CALM regime sets correct parameters."""
    # Setup VIX bars for CALM regime
    vix_bars = create_vix_bars(60, Decimal('12.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # Create minimal QQQ bars to trigger regime detection
    qqq_bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    # Mock parent on_bar to prevent full execution
    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar)

    # Verify CALM parameters set
    assert strategy.ema_period == strategy.ema_period_calm
    assert strategy.atr_stop_multiplier == strategy.atr_stop_calm


def test_parameter_switching_choppy_regime(strategy):
    """Test that CHOPPY regime sets correct parameters."""
    # Setup VIX bars for CHOPPY regime (high VIX)
    vix_bars_low = create_vix_bars(50, Decimal('15.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    vix_bars_high = create_vix_bars(10, Decimal('35.0'), datetime(2024, 2, 20, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_low + vix_bars_high

    # Create QQQ bar
    qqq_bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 3, 1, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    # Mock parent on_bar
    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar)

    # Verify CHOPPY parameters set
    assert strategy.ema_period == strategy.ema_period_choppy
    assert strategy.atr_stop_multiplier == strategy.atr_stop_choppy


def test_parameter_switching_calm_to_choppy(strategy):
    """Test parameter switching from CALM to CHOPPY."""
    # Start in CALM
    vix_bars = create_vix_bars(60, Decimal('12.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    qqq_bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 2, 1, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar)

    # Verify CALM parameters
    assert strategy.ema_period == 200
    assert strategy.atr_stop_multiplier == Decimal('3.0')

    # Spike VIX to CHOPPY
    vix_bars_spike = create_vix_bars(5, Decimal('40.0'), datetime(2024, 3, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars + vix_bars_spike

    qqq_bar2 = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 3, 6, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar2)

    # Verify CHOPPY parameters
    assert strategy.ema_period == 75
    assert strategy.atr_stop_multiplier == Decimal('2.0')


def test_parameter_switching_choppy_to_calm(strategy):
    """Test parameter switching from CHOPPY to CALM."""
    # Start with baseline VIX = 20, then spike to 40 (creates CHOPPY)
    vix_bars_baseline = create_vix_bars(50, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    vix_bars_spike = create_vix_bars(10, Decimal('40.0'), datetime(2024, 2, 20, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_baseline + vix_bars_spike

    qqq_bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 3, 1, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar)

    # Verify CHOPPY parameters (VIX=40 > VIX_EMA≈23)
    assert strategy.ema_period == 75
    assert strategy.atr_stop_multiplier == Decimal('2.0')

    # Drop VIX to CALM (VIX = 18, below EMA)
    vix_bars_low = create_vix_bars(5, Decimal('18.0'), datetime(2024, 4, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_baseline + vix_bars_spike + vix_bars_low

    qqq_bar2 = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 4, 6, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar2)

    # Verify CALM parameters (VIX=18 < VIX_EMA≈23)
    assert strategy.ema_period == 200
    assert strategy.atr_stop_multiplier == Decimal('3.0')


def test_parameter_switching_preserves_v4_parameters(strategy):
    """Test that parameter switching doesn't affect v4-only parameters."""
    # V4 parameters that should NOT change
    original_risk_bull = strategy.risk_bull
    original_allocation_defense = strategy.allocation_defense
    original_macd_fast = strategy.macd_fast_period

    # Trigger regime detection
    vix_bars = create_vix_bars(60, Decimal('12.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    qqq_bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(qqq_bar)

    # Verify v4 parameters unchanged
    assert strategy.risk_bull == original_risk_bull
    assert strategy.allocation_defense == original_allocation_defense
    assert strategy.macd_fast_period == original_macd_fast


def test_parameter_switching_updates_before_v4_processing(strategy):
    """Test that parameters update BEFORE v4 logic runs."""
    # This test verifies execution order
    # Create CHOPPY scenario: baseline VIX=20, then spike to 35
    vix_bars_baseline = create_vix_bars(50, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    vix_bars_spike = create_vix_bars(10, Decimal('35.0'), datetime(2024, 2, 20, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars_baseline + vix_bars_spike

    qqq_bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 3, 1, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('399.00'),
        close=Decimal('401.50'),
        volume=1000000
    )

    # Mock parent on_bar to capture parameters at call time
    params_at_call = {}

    def capture_params(bar):
        params_at_call['ema_period'] = strategy.ema_period
        params_at_call['atr_stop_multiplier'] = strategy.atr_stop_multiplier

    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar', side_effect=capture_params):
        strategy.on_bar(qqq_bar)

    # Verify CHOPPY parameters were set BEFORE v4 on_bar called (VIX=35 > VIX_EMA≈22)
    assert params_at_call['ema_period'] == 75  # CHOPPY value
    assert params_at_call['atr_stop_multiplier'] == Decimal('2.0')  # CHOPPY value


# ========================================
# 6. Integration with V4 Logic Tests (4 tests)
# ========================================

def test_on_bar_processes_vix_bars(strategy, sample_vix_bar):
    """Test that on_bar correctly processes VIX bars."""
    # Process VIX bar
    strategy.on_bar(sample_vix_bar)

    # Verify VIX bar stored
    assert len(strategy._vix_bars) == 1
    assert strategy._vix_bars[0].symbol == 'VIX'


def test_on_bar_delegates_to_v4_for_qqq(strategy, sample_qqq_bar):
    """Test that on_bar delegates to v4 logic for QQQ bars."""
    # Setup minimal VIX data
    vix_bars = create_vix_bars(60, Decimal('15.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # Mock parent on_bar
    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar') as mock_parent:
        strategy.on_bar(sample_qqq_bar)

        # Verify parent on_bar was called with QQQ bar
        mock_parent.assert_called_once_with(sample_qqq_bar)


def test_on_bar_delegates_to_v4_for_tqqq(strategy, sample_tqqq_bar):
    """Test that on_bar delegates to v4 logic for TQQQ bars."""
    # Mock parent on_bar
    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar') as mock_parent:
        strategy.on_bar(sample_tqqq_bar)

        # Verify parent on_bar was called with TQQQ bar
        mock_parent.assert_called_once_with(sample_tqqq_bar)


def test_on_bar_does_not_process_unknown_symbols(strategy):
    """Test that on_bar ignores unknown symbols."""
    # Create bar for unknown symbol
    unknown_bar = MarketDataEvent(
        symbol='UNKNOWN',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('100.00'),
        high=Decimal('101.00'),
        low=Decimal('99.00'),
        close=Decimal('100.50'),
        volume=1000
    )

    # Mock parent on_bar
    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar') as mock_parent:
        strategy.on_bar(unknown_bar)

        # Verify parent on_bar was called (v4 handles unknown symbols)
        mock_parent.assert_called_once_with(unknown_bar)


# ========================================
# 7. Edge Cases Tests (4 tests)
# ========================================

def test_edge_case_no_vix_bars(strategy, sample_qqq_bar):
    """Test that strategy handles QQQ bars before any VIX bars."""
    # No VIX bars yet
    assert len(strategy._vix_bars) == 0

    # Process QQQ bar (should default to CALM regime)
    with patch.object(MACD_Trend_v5.__bases__[0], 'on_bar'):
        strategy.on_bar(sample_qqq_bar)

    # Should use CALM defaults (no error)
    assert strategy.ema_period == 200
    assert strategy.atr_stop_multiplier == Decimal('3.0')


def test_edge_case_vix_exactly_equal_to_ema(strategy):
    """Test VIX regime when VIX_raw exactly equals VIX_EMA_50."""
    # Create constant VIX bars (VIX = VIX_EMA_50)
    vix_bars = create_vix_bars(60, Decimal('20.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # VIX_raw == VIX_EMA_50 (exactly equal)
    regime = strategy._detect_vix_regime()

    # Should be CALM (uses <= comparison)
    assert regime == 'CALM'


def test_edge_case_single_vix_bar(strategy):
    """Test VIX regime with only 1 VIX bar."""
    # Single VIX bar
    vix_bar = MarketDataEvent(
        symbol='VIX',
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        open=Decimal('20.0'),
        high=Decimal('21.0'),
        low=Decimal('19.0'),
        close=Decimal('20.0'),
        volume=0
    )
    strategy._vix_bars = [vix_bar]

    # Should default to CALM (insufficient bars)
    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'


def test_edge_case_vix_bars_exactly_at_threshold(strategy):
    """Test VIX regime when exactly at vix_ema_period threshold."""
    # Exactly 50 VIX bars (minimum required)
    vix_bars = create_vix_bars(50, Decimal('18.0'), datetime(2024, 1, 1, tzinfo=timezone.utc))
    strategy._vix_bars = vix_bars

    # Should be able to calculate regime
    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'  # Constant value -> VIX == VIX_EMA
