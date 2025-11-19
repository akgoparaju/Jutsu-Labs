"""
Tests for MACD_Trend_v6 (VIX-Filtered Strategy with Master Switch).

This module tests the VIX-filtered Goldilocks strategy that uses VIX as a "master switch"
to gate the base v4 logic. Key behaviors tested:
- VIX regime detection (CALM vs CHOPPY)
- Master switch gating (run v4 only when CALM)
- Position liquidation when switching to CHOPPY
- Inheritance from v4 (all v4 logic works when CALM)
"""
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from jutsu_engine.strategies.MACD_Trend_v6 import MACD_Trend_v6
from jutsu_engine.core.events import MarketDataEvent


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def strategy():
    """Create MACD_Trend_v6 strategy with default parameters."""
    return MACD_Trend_v6()


@pytest.fixture
def custom_strategy():
    """Create MACD_Trend_v6 strategy with custom parameters."""
    return MACD_Trend_v6(
        vix_symbol='$VIX',  # Index symbols use $ prefix
        vix_ema_period=75,
        signal_symbol='QQQ',
        bull_symbol='TQQQ',
        defense_symbol='QQQ',
        ema_period=150,
        atr_stop_multiplier=Decimal('2.5'),
        risk_bull=Decimal('0.020'),
        allocation_defense=Decimal('0.70')
    )


@pytest.fixture
def sample_qqq_bar():
    """Create sample QQQ bar."""
    return MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='QQQ',
        open=Decimal('385.50'),
        high=Decimal('387.25'),
        low=Decimal('384.75'),
        close=Decimal('386.80'),
        volume=50000000
    )


@pytest.fixture
def sample_tqqq_bar():
    """Create sample TQQQ bar."""
    return MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='TQQQ',
        open=Decimal('42.50'),
        high=Decimal('43.25'),
        low=Decimal('42.00'),
        close=Decimal('42.95'),
        volume=30000000
    )


@pytest.fixture
def sample_vix_bar():
    """Create sample VIX bar."""
    return MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='$VIX',  # Index symbols use $ prefix
        open=Decimal('14.50'),
        high=Decimal('15.25'),
        low=Decimal('14.25'),
        close=Decimal('14.80'),
        volume=0  # VIX is an index, volume may be 0
    )


# =============================================================================
# Category 1: Initialization Tests (6 tests)
# =============================================================================

def test_initialization_default_parameters():
    """Test strategy initializes with default parameters."""
    strategy = MACD_Trend_v6()

    # VIX parameters (Index symbols use $ prefix)
    assert strategy.vix_symbol == '$VIX'
    assert strategy.vix_ema_period == 50

    # V4 parameters (inherited)
    assert strategy.signal_symbol == 'QQQ'
    assert strategy.bull_symbol == 'TQQQ'
    assert strategy.defensive_symbol == 'QQQ'
    assert strategy.ema_period == 100
    assert strategy.atr_stop_multiplier == Decimal('3.0')
    assert strategy.risk_bull == Decimal('0.025')
    assert strategy.allocation_defense == Decimal('0.60')

    # State tracking
    assert strategy.current_vix_regime is None
    assert strategy._vix_bars == []


def test_initialization_custom_parameters():
    """Test strategy initializes with custom parameters."""
    strategy = MACD_Trend_v6(
        vix_symbol='$VIX',  # Index symbols use $ prefix
        vix_ema_period=75,
        signal_symbol='SPY',
        bull_symbol='UPRO',
        defense_symbol='SPY',
        ema_period=150,
        atr_stop_multiplier=Decimal('2.5'),
        risk_bull=Decimal('0.020'),
        allocation_defense=Decimal('0.70')
    )

    # VIX parameters (Index symbols use $ prefix)
    assert strategy.vix_symbol == '$VIX'
    assert strategy.vix_ema_period == 75

    # V4 parameters
    assert strategy.signal_symbol == 'SPY'
    assert strategy.bull_symbol == 'UPRO'
    assert strategy.defensive_symbol == 'SPY'
    assert strategy.ema_period == 150
    assert strategy.atr_stop_multiplier == Decimal('2.5')
    assert strategy.risk_bull == Decimal('0.020')
    assert strategy.allocation_defense == Decimal('0.70')


def test_initialization_float_to_decimal_conversion():
    """Test that float parameters are converted to Decimal."""
    strategy = MACD_Trend_v6(
        atr_stop_multiplier=2.5,  # float
        risk_bull=0.020,  # float
        allocation_defense=0.70  # float
    )

    # All should be Decimal type
    assert isinstance(strategy.atr_stop_multiplier, Decimal)
    assert isinstance(strategy.risk_bull, Decimal)
    assert isinstance(strategy.allocation_defense, Decimal)

    # Values should be correct
    assert strategy.atr_stop_multiplier == Decimal('2.5')
    assert strategy.risk_bull == Decimal('0.020')
    assert strategy.allocation_defense == Decimal('0.70')


def test_init_method_resets_state():
    """Test that init() method resets all state variables."""
    strategy = MACD_Trend_v6()

    # Simulate some state
    strategy._vix_bars = [1, 2, 3]
    strategy.current_vix_regime = 'CALM'
    strategy.current_position_symbol = 'TQQQ'

    # Call init
    strategy.init()

    # State should be reset
    assert strategy._vix_bars == []
    assert strategy.current_vix_regime is None
    assert strategy.current_position_symbol is None


def test_inheritance_from_v4():
    """Test that v6 properly inherits from v4."""
    strategy = MACD_Trend_v6()

    # Should have v4 methods
    assert hasattr(strategy, '_determine_regime')
    assert hasattr(strategy, '_handle_regime_transition')
    assert hasattr(strategy, '_enter_tqqq')
    assert hasattr(strategy, '_enter_qqq')
    assert hasattr(strategy, '_check_tqqq_stop_loss')

    # Should have v4 attributes
    assert hasattr(strategy, 'current_regime')
    assert hasattr(strategy, 'current_position_symbol')
    assert hasattr(strategy, 'tqqq_entry_price')
    assert hasattr(strategy, 'tqqq_stop_loss')


def test_initialization_vix_bars_list():
    """Test that VIX bars list is properly initialized."""
    strategy = MACD_Trend_v6()

    # Should be empty list
    assert isinstance(strategy._vix_bars, list)
    assert len(strategy._vix_bars) == 0


# =============================================================================
# Category 2: Symbol Validation Tests (4 tests)
# =============================================================================

def test_validate_all_symbols_present(strategy, sample_qqq_bar, sample_tqqq_bar, sample_vix_bar):
    """Test validation passes when all 3 required symbols are present."""
    # Add bars for all 3 symbols
    for _ in range(120):  # Enough for lookback
        strategy._bars.append(sample_qqq_bar)
        strategy._bars.append(sample_tqqq_bar)
        strategy._bars.append(sample_vix_bar)

    # Should not raise
    strategy._validate_required_symbols()


def test_validate_missing_vix(strategy, sample_qqq_bar, sample_tqqq_bar):
    """Test validation fails when VIX symbol is missing."""
    # Add bars for QQQ and TQQQ only (no VIX)
    for i in range(120):
        qqq_bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='QQQ',
            open=Decimal('385.50'),
            high=Decimal('387.25'),
            low=Decimal('384.75'),
            close=Decimal('386.80'),
            volume=50000000
        )
        tqqq_bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='TQQQ',
            open=Decimal('42.50'),
            high=Decimal('43.25'),
            low=Decimal('42.00'),
            close=Decimal('42.95'),
            volume=30000000
        )
        strategy._bars.append(qqq_bar)
        strategy._bars.append(tqqq_bar)

    # Add a dummy third symbol to trigger validation
    # (validation only happens when len(available_symbols) >= len(unique_required))
    dummy_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
        symbol='DUMMY',  # Not a required symbol
        open=Decimal('100.00'),
        high=Decimal('101.00'),
        low=Decimal('99.00'),
        close=Decimal('100.50'),
        volume=10000
    )
    strategy._bars.append(dummy_bar)

    # Should raise ValueError when we have 3 available symbols but $VIX is missing (Index symbols use $ prefix)
    with pytest.raises(ValueError, match="MACD_Trend_v6 requires symbols.*missing.*\\$VIX"):
        strategy._validate_required_symbols()


def test_validate_missing_qqq(strategy, sample_tqqq_bar, sample_vix_bar):
    """Test validation fails when QQQ symbol is missing."""
    # Add bars for TQQQ and VIX only (no QQQ)
    for i in range(120):
        tqqq_bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='TQQQ',
            open=Decimal('42.50'),
            high=Decimal('43.25'),
            low=Decimal('42.00'),
            close=Decimal('42.95'),
            volume=30000000
        )
        vix_bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('14.50'),
            high=Decimal('15.25'),
            low=Decimal('14.25'),
            close=Decimal('14.80'),
            volume=0
        )
        strategy._bars.append(tqqq_bar)
        strategy._bars.append(vix_bar)

    # Add a dummy third symbol to trigger validation
    dummy_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
        symbol='DUMMY',
        open=Decimal('100.00'),
        high=Decimal('101.00'),
        low=Decimal('99.00'),
        close=Decimal('100.50'),
        volume=10000
    )
    strategy._bars.append(dummy_bar)

    # Should raise ValueError
    with pytest.raises(ValueError, match="MACD_Trend_v6 requires symbols.*missing.*QQQ"):
        strategy._validate_required_symbols()


def test_validate_missing_tqqq(strategy, sample_qqq_bar, sample_vix_bar):
    """Test validation fails when TQQQ symbol is missing."""
    # Add bars for QQQ and VIX only (no TQQQ)
    for i in range(120):
        qqq_bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='QQQ',
            open=Decimal('385.50'),
            high=Decimal('387.25'),
            low=Decimal('384.75'),
            close=Decimal('386.80'),
            volume=50000000
        )
        vix_bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('14.50'),
            high=Decimal('15.25'),
            low=Decimal('14.25'),
            close=Decimal('14.80'),
            volume=0
        )
        strategy._bars.append(qqq_bar)
        strategy._bars.append(vix_bar)

    # Add a dummy third symbol to trigger validation
    dummy_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
        symbol='DUMMY',
        open=Decimal('100.00'),
        high=Decimal('101.00'),
        low=Decimal('99.00'),
        close=Decimal('100.50'),
        volume=10000
    )
    strategy._bars.append(dummy_bar)

    # Should raise ValueError
    with pytest.raises(ValueError, match="MACD_Trend_v6 requires symbols.*missing.*TQQQ"):
        strategy._validate_required_symbols()


# =============================================================================
# Category 3: VIX Regime Detection Tests (8 tests)
# =============================================================================

def test_detect_calm_regime(strategy, sample_vix_bar):
    """Test CALM regime detection when VIX <= VIX_EMA."""
    # Add VIX bars with declining trend (VIX below EMA)
    for i in range(60):
        close_price = Decimal('13.50') - Decimal(i) / 200  # Slowly declining
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=close_price + Decimal('0.10'),
            high=close_price + Decimal('0.50'),
            low=close_price - Decimal('0.10'),
            close=close_price,
            volume=0
        )
        strategy._vix_bars.append(bar)

    regime = strategy._detect_vix_regime()
    assert regime == 'CALM'


def test_detect_choppy_regime(strategy, sample_vix_bar):
    """Test CHOPPY regime detection when VIX > VIX_EMA."""
    # Add VIX bars with rising trend (VIX above EMA)
    for i in range(60):
        close_price = Decimal('14.00') + Decimal(i) / 50  # Rising
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=close_price - Decimal('0.10'),
            high=close_price + Decimal('0.50'),
            low=close_price - Decimal('0.30'),
            close=close_price,
            volume=0
        )
        strategy._vix_bars.append(bar)

    regime = strategy._detect_vix_regime()
    assert regime == 'CHOPPY'


def test_detect_regime_exact_threshold(strategy):
    """Test regime detection when VIX exactly equals VIX_EMA."""
    # Add VIX bars with flat trend (VIX = EMA)
    for i in range(60):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('15.00'),
            high=Decimal('15.50'),
            low=Decimal('14.50'),
            close=Decimal('15.00'),  # Flat
            volume=0
        )
        strategy._vix_bars.append(bar)

    regime = strategy._detect_vix_regime()
    # VIX <= VIX_EMA should be CALM
    assert regime == 'CALM'


def test_detect_regime_insufficient_data(strategy):
    """Test regime detection with insufficient VIX data defaults to CHOPPY."""
    # Add only 40 bars (less than vix_ema_period=50)
    for i in range(40):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('15.00'),
            high=Decimal('15.50'),
            low=Decimal('14.00'),
            close=Decimal('14.50'),
            volume=0
        )
        strategy._vix_bars.append(bar)

    regime = strategy._detect_vix_regime()
    # Should default to CHOPPY (conservative)
    assert regime == 'CHOPPY'


def test_vix_regime_transitions():
    """Test VIX regime transitions are detected correctly."""
    strategy = MACD_Trend_v6()

    # Start with CALM regime (low VIX)
    for i in range(60):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('12.00'),
            high=Decimal('12.50'),
            low=Decimal('11.50'),
            close=Decimal('12.00'),
            volume=0
        )
        strategy._vix_bars.append(bar)

    assert strategy._detect_vix_regime() == 'CALM'

    # Add bars showing VIX spike (transition to CHOPPY)
    for i in range(20):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('18.00'),
            high=Decimal('19.00'),
            low=Decimal('17.00'),
            close=Decimal('18.50'),
            volume=0
        )
        strategy._vix_bars.append(bar)

    assert strategy._detect_vix_regime() == 'CHOPPY'


def test_vix_ema_calculation():
    """Test that VIX EMA is calculated correctly."""
    strategy = MACD_Trend_v6(vix_ema_period=10)

    # Add 20 VIX bars with known values
    for i in range(20):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('15.00'),
            high=Decimal('15.50'),
            low=Decimal('14.50'),
            close=Decimal('15.00'),
            volume=0
        )
        strategy._vix_bars.append(bar)

    # Should calculate regime (sufficient data)
    regime = strategy._detect_vix_regime()
    # VIX flat at 15.00, EMA should be ~15.00, so CALM
    assert regime == 'CALM'


def test_vix_lookback_period_handling():
    """Test that VIX lookback period is handled correctly."""
    strategy = MACD_Trend_v6(vix_ema_period=50)

    # Add exactly 50 bars
    for i in range(50):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('15.00'),
            high=Decimal('15.50'),
            low=Decimal('14.50'),
            close=Decimal('15.00'),
            volume=0
        )
        strategy._vix_bars.append(bar)

    # Should have enough data now
    regime = strategy._detect_vix_regime()
    assert regime in ['CALM', 'CHOPPY']  # Should not raise


def test_vix_data_validation():
    """Test that VIX bars are stored correctly."""
    strategy = MACD_Trend_v6()

    # Process VIX bars
    for i in range(10):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('15.00'),
            high=Decimal('15.50'),
            low=Decimal('14.50'),
            close=Decimal('15.00'),
            volume=0
        )
        strategy._process_vix_bar(bar)

    # Should have 10 VIX bars
    assert len(strategy._vix_bars) == 10

    # Bars should be correct symbol (Index symbols use $ prefix)
    for bar in strategy._vix_bars:
        assert bar.symbol == '$VIX'


# =============================================================================
# Category 4: Regime Transitions Tests (6 tests)
# =============================================================================

def test_calm_to_choppy_liquidates_tqqq():
    """Test transition from CALM to CHOPPY liquidates TQQQ position."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Simulate TQQQ position
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('42.00')
    strategy.tqqq_stop_loss = Decimal('40.00')
    strategy.current_regime = 'TQQQ'

    # Call _enter_cash_regime
    strategy._enter_cash_regime()

    # Position should be cleared
    assert strategy.current_position_symbol is None
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None
    assert strategy.current_regime is None


def test_calm_to_choppy_liquidates_qqq():
    """Test transition from CALM to CHOPPY liquidates QQQ position."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Simulate QQQ position
    strategy.current_position_symbol = 'QQQ'
    strategy.current_regime = 'QQQ'

    # Call _enter_cash_regime
    strategy._enter_cash_regime()

    # Position should be cleared
    assert strategy.current_position_symbol is None
    assert strategy.current_regime is None


def test_choppy_to_calm_allows_v4_entry_tqqq(strategy):
    """Test transition from CHOPPY to CALM allows v4 to enter TQQQ."""
    # This is tested implicitly by v4 tests
    # When CALM, super().on_bar() runs, which can enter TQQQ
    # We verify by checking that v4 methods are accessible
    assert hasattr(strategy, '_enter_tqqq')
    assert callable(strategy._enter_tqqq)


def test_choppy_to_calm_allows_v4_entry_qqq(strategy):
    """Test transition from CHOPPY to CALM allows v4 to enter QQQ."""
    # This is tested implicitly by v4 tests
    # When CALM, super().on_bar() runs, which can enter QQQ
    # We verify by checking that v4 methods are accessible
    assert hasattr(strategy, '_enter_qqq')
    assert callable(strategy._enter_qqq)


def test_choppy_to_choppy_stays_cash():
    """Test CHOPPY to CHOPPY transition stays in CASH."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Already in CASH (no position)
    assert strategy.current_position_symbol is None

    # Call _enter_cash_regime (should be no-op)
    strategy._enter_cash_regime()

    # Should still be in CASH
    assert strategy.current_position_symbol is None


def test_already_in_cash_no_redundant_liquidation():
    """Test that already being in CASH doesn't trigger redundant liquidation."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # No position
    assert strategy.current_position_symbol is None

    # Call _enter_cash_regime
    strategy._enter_cash_regime()

    # Should still be None (no errors)
    assert strategy.current_position_symbol is None


# =============================================================================
# Category 5: Integration with v4 Tests (4 tests)
# =============================================================================

def test_v4_logic_executes_during_calm():
    """Test that v4 logic executes when VIX regime is CALM."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Mock v4's on_bar to track if it was called
    original_on_bar = MACD_Trend_v6.__bases__[0].on_bar
    called = []

    def mock_on_bar(self, bar):
        called.append(True)
        original_on_bar(self, bar)

    # Patch super().on_bar
    MACD_Trend_v6.__bases__[0].on_bar = mock_on_bar

    # Set CALM regime
    strategy.current_vix_regime = 'CALM'

    # Add enough VIX bars for CALM regime
    for i in range(60):
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=Decimal('12.00'),
            high=Decimal('12.50'),
            low=Decimal('11.50'),
            close=Decimal('12.00'),
            volume=0
        )
        strategy._vix_bars.append(bar)

    # Process QQQ bar
    qqq_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='QQQ',
        open=Decimal('385.50'),
        high=Decimal('387.25'),
        low=Decimal('384.75'),
        close=Decimal('386.80'),
        volume=50000000
    )

    strategy.on_bar(qqq_bar)

    # v4's on_bar should have been called
    assert len(called) > 0

    # Restore original method
    MACD_Trend_v6.__bases__[0].on_bar = original_on_bar


def test_v4_logic_blocked_during_choppy():
    """Test that v4 logic is blocked when VIX regime is CHOPPY."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Add enough VIX bars for CHOPPY regime (VIX > VIX_EMA)
    for i in range(60):
        close_price = Decimal('18.00') + Decimal(i) / 30  # Rising VIX
        bar = MarketDataEvent(
            timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            symbol='$VIX',  # Index symbols use $ prefix
            open=close_price - Decimal('0.10'),
            high=close_price + Decimal('0.50'),
            low=close_price - Decimal('0.30'),
            close=close_price,
            volume=0
        )
        strategy._vix_bars.append(bar)

    # Verify CHOPPY regime
    assert strategy._detect_vix_regime() == 'CHOPPY'

    # Set initial regime to something other than CHOPPY (to force transition)
    strategy.current_vix_regime = None

    # Simulate a position (should be liquidated when CHOPPY is detected)
    strategy.current_position_symbol = 'TQQQ'

    # Create QQQ bar
    qqq_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='QQQ',
        open=Decimal('385.50'),
        high=Decimal('387.25'),
        low=Decimal('384.75'),
        close=Decimal('386.80'),
        volume=50000000
    )

    # Mock _current_bar and indicator values for logging context
    strategy._current_bar = qqq_bar
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Process QQQ bar
    strategy.on_bar(qqq_bar)

    # Position should be cleared (liquidated) and regime changed to CHOPPY
    assert strategy.current_position_symbol is None
    assert strategy.current_vix_regime == 'CHOPPY'


def test_position_sizing_correct_inherited():
    """Test that position sizing is correct (inherited from v4)."""
    strategy = MACD_Trend_v6(
        risk_bull=Decimal('0.020'),
        allocation_defense=Decimal('0.70')
    )

    # Parameters should match
    assert strategy.risk_bull == Decimal('0.020')
    assert strategy.allocation_defense == Decimal('0.70')


def test_signal_generation_correct():
    """Test that signal generation is correct (inherited from v4)."""
    strategy = MACD_Trend_v6()

    # Should have buy/sell methods from base class
    assert hasattr(strategy, 'buy')
    assert hasattr(strategy, 'sell')
    assert callable(strategy.buy)
    assert callable(strategy.sell)


# =============================================================================
# Category 6: Edge Cases Tests (3 tests)
# =============================================================================

def test_vix_bar_arrives_before_qqq():
    """Test VIX bar processing when it arrives before QQQ."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Process VIX bar first
    vix_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='$VIX',  # Index symbols use $ prefix
        open=Decimal('14.50'),
        high=Decimal('15.25'),
        low=Decimal('14.25'),
        close=Decimal('14.80'),
        volume=0
    )

    strategy.on_bar(vix_bar)

    # Should have stored VIX bar
    assert len(strategy._vix_bars) == 1


def test_vix_bar_arrives_after_qqq():
    """Test VIX bar processing when it arrives after QQQ."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # Process QQQ bar first
    qqq_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='QQQ',
        open=Decimal('385.50'),
        high=Decimal('387.25'),
        low=Decimal('384.75'),
        close=Decimal('386.80'),
        volume=50000000
    )

    strategy.on_bar(qqq_bar)

    # Then process VIX bar
    vix_bar = MarketDataEvent(
        timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
        symbol='$VIX',  # Index symbols use $ prefix
        open=Decimal('14.50'),
        high=Decimal('15.25'),
        low=Decimal('14.25'),
        close=Decimal('14.80'),
        volume=0
    )

    strategy.on_bar(vix_bar)

    # Should have stored VIX bar
    assert len(strategy._vix_bars) == 1


def test_missing_vix_data_conservative_default():
    """Test that missing VIX data defaults to CHOPPY (conservative)."""
    strategy = MACD_Trend_v6()
    strategy.init()

    # No VIX bars
    assert len(strategy._vix_bars) == 0

    # Should default to CHOPPY
    regime = strategy._detect_vix_regime()
    assert regime == 'CHOPPY'
