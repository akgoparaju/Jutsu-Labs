"""
Unit tests for MACD_Trend strategy.

Tests cover:
- Initialization (5 tests)
- Symbol validation (4 tests)
- State determination (6 tests)
- Entry execution (4 tests)
- Exit execution (3 tests)
- on_bar() flow (5 tests)
- Integration (2 tests)

Target: >95% code coverage
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from jutsu_engine.strategies.MACD_Trend import MACD_Trend
from jutsu_engine.core.events import MarketDataEvent


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def strategy():
    """Create MACD_Trend strategy with default parameters."""
    return MACD_Trend()


@pytest.fixture
def custom_strategy():
    """Create MACD_Trend strategy with custom parameters."""
    return MACD_Trend(
        macd_fast_period=10,
        macd_slow_period=20,
        macd_signal_period=5,
        ema_slow_period=50,
        vix_kill_switch=Decimal('25.0'),
        atr_period=10,
        atr_stop_multiplier=Decimal('2.5'),
        risk_per_trade=Decimal('0.02'),
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
def sample_vix_bar():
    """Create sample VIX bar."""
    return MarketDataEvent(
        symbol='$VIX',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('15.00'),
        high=Decimal('16.00'),
        low=Decimal('14.50'),
        close=Decimal('15.50'),
        volume=0
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


# ========================================
# 1. Initialization Tests (5 tests)
# ========================================

def test_initialization_default_parameters(strategy):
    """Test strategy initialization with default parameters."""
    assert strategy.macd_fast_period == 12
    assert strategy.macd_slow_period == 26
    assert strategy.macd_signal_period == 9
    assert strategy.ema_slow_period == 100
    assert strategy.vix_kill_switch == Decimal('30.0')
    assert strategy.atr_period == 14
    assert strategy.atr_stop_multiplier == Decimal('3.0')
    assert strategy.risk_per_trade == Decimal('0.025')


def test_initialization_custom_parameters(custom_strategy):
    """Test strategy initialization with custom parameters."""
    assert custom_strategy.macd_fast_period == 10
    assert custom_strategy.macd_slow_period == 20
    assert custom_strategy.macd_signal_period == 5
    assert custom_strategy.ema_slow_period == 50
    assert custom_strategy.vix_kill_switch == Decimal('25.0')
    assert custom_strategy.atr_period == 10
    assert custom_strategy.atr_stop_multiplier == Decimal('2.5')
    assert custom_strategy.risk_per_trade == Decimal('0.02')


def test_initialization_trading_symbols(strategy):
    """Test that trading symbols are correctly set."""
    assert strategy.signal_symbol == 'QQQ'
    assert strategy.vix_symbol == '$VIX'
    assert strategy.bull_symbol == 'TQQQ'
    # Verify no bear symbol (long-only)
    assert not hasattr(strategy, 'bear_symbol')


def test_initialization_state_tracking(strategy):
    """Test that state tracking variables are initialized."""
    assert strategy.previous_state is None
    assert strategy.current_position_symbol is None
    assert strategy.entry_price is None
    assert strategy.stop_loss_price is None
    assert strategy._symbols_validated is False


def test_init_method_resets_state(strategy):
    """Test that init() method resets all state variables."""
    # Set some state
    strategy.previous_state = 'IN'
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.00')
    strategy.stop_loss_price = Decimal('45.00')
    strategy._symbols_validated = True

    # Call init()
    strategy.init()

    # Verify reset
    assert strategy.previous_state is None
    assert strategy.current_position_symbol is None
    assert strategy.entry_price is None
    assert strategy.stop_loss_price is None
    assert strategy._symbols_validated is False


# ========================================
# 2. Symbol Validation Tests (4 tests)
# ========================================

def test_symbol_validation_all_present(strategy):
    """Test symbol validation succeeds when all symbols present."""
    from datetime import timedelta
    # Create bars with all required symbols (spread across dates)
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = [
        MarketDataEvent('QQQ', base_date + timedelta(days=i),
                        Decimal('400'), Decimal('401'), Decimal('399'),
                        Decimal('400.5'), 100000)
        for i in range(111)
    ]
    strategy._bars += [
        MarketDataEvent('$VIX', base_date + timedelta(days=i),
                        Decimal('15'), Decimal('16'), Decimal('14'),
                        Decimal('15.5'), 0)
        for i in range(111)
    ]
    strategy._bars += [
        MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.5'), 200000)
        for i in range(111)
    ]

    # Validation should succeed (no exception)
    strategy._validate_required_symbols()
    # If we reach here, validation passed


def test_symbol_validation_missing_qqq(strategy):
    """Test symbol validation fails when QQQ missing."""
    strategy._bars = [
        MarketDataEvent('$VIX', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('15'), Decimal('16'), Decimal('14'),
                        Decimal('15.5'), 0),
        MarketDataEvent('TQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.5'), 200000)
    ]

    with pytest.raises(ValueError, match="missing: \\['QQQ'\\]"):
        strategy._validate_required_symbols()


def test_symbol_validation_missing_vix(strategy):
    """Test symbol validation fails when VIX missing."""
    strategy._bars = [
        MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('400'), Decimal('401'), Decimal('399'),
                        Decimal('400.5'), 100000),
        MarketDataEvent('TQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.5'), 200000)
    ]

    with pytest.raises(ValueError, match="missing: \\['\\$VIX'\\]"):
        strategy._validate_required_symbols()


def test_symbol_validation_missing_tqqq(strategy):
    """Test symbol validation fails when TQQQ missing."""
    strategy._bars = [
        MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('400'), Decimal('401'), Decimal('399'),
                        Decimal('400.5'), 100000),
        MarketDataEvent('$VIX', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('15'), Decimal('16'), Decimal('14'),
                        Decimal('15.5'), 0)
    ]

    with pytest.raises(ValueError, match="missing: \\['TQQQ'\\]"):
        strategy._validate_required_symbols()


# ========================================
# 3. State Determination Tests (6 tests)
# ========================================

def test_determine_state_in_all_conditions_met(strategy):
    """Test IN state when all 3 conditions are met."""
    # Price > EMA, MACD > Signal, VIX <= 30
    state = strategy._determine_state(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    assert state == 'IN'


def test_determine_state_out_trend_fails(strategy):
    """Test OUT state when trend condition fails (Price < EMA)."""
    # Price < EMA (trend fails), MACD > Signal, VIX <= 30
    state = strategy._determine_state(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    assert state == 'OUT'


def test_determine_state_out_momentum_fails(strategy):
    """Test OUT state when momentum condition fails (MACD < Signal)."""
    # Price > EMA, MACD < Signal (momentum fails), VIX <= 30
    state = strategy._determine_state(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    assert state == 'OUT'


def test_determine_state_out_vix_fails(strategy):
    """Test OUT state when VIX condition fails (VIX > 30)."""
    # Price > EMA, MACD > Signal, VIX > 30 (volatility fails)
    state = strategy._determine_state(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('35.0')
    )
    assert state == 'OUT'


def test_determine_state_out_multiple_failures(strategy):
    """Test OUT state when multiple conditions fail."""
    # Price < EMA, MACD < Signal, VIX > 30 (all fail)
    state = strategy._determine_state(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('35.0')
    )
    assert state == 'OUT'


def test_determine_state_boundary_vix_equals_threshold(strategy):
    """Test IN state when VIX equals threshold (30.0)."""
    # Price > EMA, MACD > Signal, VIX = 30.0 (boundary case)
    state = strategy._determine_state(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('30.0')
    )
    assert state == 'IN'


# ========================================
# 4. Entry Execution Tests (4 tests)
# ========================================

@patch('jutsu_engine.strategies.MACD_Trend.atr')
def test_execute_entry_generates_signal(mock_atr, strategy, sample_qqq_bar):
    """Test that entry execution generates buy signal with ATR sizing."""
    # Setup mock ATR
    import pandas as pd
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Setup TQQQ bars for ATR calculation
    strategy._bars = [
        MarketDataEvent('TQQQ', datetime(2024, 1, i, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.50'), 200000)
        for i in range(1, 16)
    ]

    # Setup strategy state for logging
    strategy._current_bar = sample_qqq_bar
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = "Test"

    # Execute entry
    strategy._execute_entry(sample_qqq_bar)

    # Verify signal generated
    signals = strategy.get_signals()
    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == 'TQQQ'
    assert signal.signal_type == 'BUY'
    assert signal.portfolio_percent == Decimal('0.025')


@patch('jutsu_engine.strategies.MACD_Trend.atr')
def test_execute_entry_calculates_risk_per_share(mock_atr, strategy, sample_qqq_bar):
    """Test that entry calculates risk_per_share correctly (ATR × multiplier)."""
    # Setup mock ATR
    import pandas as pd
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Setup TQQQ bars
    strategy._bars = [
        MarketDataEvent('TQQQ', datetime(2024, 1, i, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.50'), 200000)
        for i in range(1, 16)
    ]

    # Setup strategy state
    strategy._current_bar = sample_qqq_bar
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = "Test"

    # Execute entry
    strategy._execute_entry(sample_qqq_bar)

    # Verify signal has risk_per_share
    signals = strategy.get_signals()
    signal = signals[0]
    expected_risk_per_share = Decimal('2.50') * Decimal('3.0')  # ATR × multiplier
    assert signal.risk_per_share == expected_risk_per_share


@patch('jutsu_engine.strategies.MACD_Trend.atr')
def test_execute_entry_sets_stop_loss(mock_atr, strategy, sample_qqq_bar):
    """Test that entry sets stop-loss price correctly."""
    # Setup mock ATR
    import pandas as pd
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Setup TQQQ bars
    strategy._bars = [
        MarketDataEvent('TQQQ', datetime(2024, 1, i, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.50'), 200000)
        for i in range(1, 16)
    ]

    # Setup strategy state
    strategy._current_bar = sample_qqq_bar
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = "Test"

    # Execute entry
    strategy._execute_entry(sample_qqq_bar)

    # Verify stop-loss tracking
    assert strategy.current_position_symbol == 'TQQQ'
    assert strategy.entry_price == Decimal('50.50')
    expected_stop = Decimal('50.50') - (Decimal('2.50') * Decimal('3.0'))
    assert strategy.stop_loss_price == expected_stop


def test_execute_entry_insufficient_bars(strategy, sample_qqq_bar):
    """Test that entry skips if insufficient TQQQ bars for ATR."""
    # Setup insufficient TQQQ bars
    strategy._bars = [
        MarketDataEvent('TQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.50'), 200000)
    ]

    # Setup strategy state
    strategy._current_bar = sample_qqq_bar
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = "Test"

    # Execute entry
    strategy._execute_entry(sample_qqq_bar)

    # Verify no signal generated
    signals = strategy.get_signals()
    assert len(signals) == 0


# ========================================
# 5. Exit Execution Tests (3 tests)
# ========================================

def test_liquidate_all_positions_closes_tqqq(strategy):
    """Test that liquidation closes TQQQ position."""
    # Setup position
    strategy._positions = {'TQQQ': 100}
    strategy._current_bar = MarketDataEvent(
        'QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
        Decimal('400'), Decimal('401'), Decimal('399'),
        Decimal('400.5'), 100000
    )
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = "Test"

    # Liquidate
    strategy._liquidate_all_positions()

    # Verify sell signal generated
    signals = strategy.get_signals()
    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == 'TQQQ'
    assert signal.signal_type == 'SELL'
    assert signal.portfolio_percent == Decimal('0.0')


def test_liquidate_clears_stop_loss_tracking(strategy):
    """Test that liquidation clears stop-loss tracking."""
    # Setup tracking
    strategy._positions = {'TQQQ': 100}
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.00')
    strategy.stop_loss_price = Decimal('45.00')
    strategy._current_bar = MarketDataEvent(
        'QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
        Decimal('400'), Decimal('401'), Decimal('399'),
        Decimal('400.5'), 100000
    )
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = "Test"

    # Liquidate
    strategy._liquidate_all_positions()

    # Verify tracking cleared
    assert strategy.current_position_symbol is None
    assert strategy.entry_price is None
    assert strategy.stop_loss_price is None


def test_liquidate_no_position_no_signal(strategy):
    """Test that liquidation with no position generates no signal."""
    # Setup no position
    strategy._positions = {}
    strategy._current_bar = MarketDataEvent(
        'QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
        Decimal('400'), Decimal('401'), Decimal('399'),
        Decimal('400.5'), 100000
    )

    # Liquidate
    strategy._liquidate_all_positions()

    # Verify no signal generated
    signals = strategy.get_signals()
    assert len(signals) == 0


# ========================================
# 6. on_bar() Flow Tests (5 tests)
# ========================================

def test_on_bar_ignores_vix_bars(strategy, sample_vix_bar):
    """Test that on_bar() ignores VIX bars."""
    from datetime import timedelta
    # Create bars with all symbols for validation, then process VIX
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(111):
        strategy._bars.append(MarketDataEvent('QQQ', base_date + timedelta(days=i),
                                              Decimal('400'), Decimal('401'),
                                              Decimal('399'), Decimal('400.5'), 100000))
        strategy._bars.append(MarketDataEvent('$VIX', base_date + timedelta(days=i),
                                              Decimal('15'), Decimal('16'),
                                              Decimal('14'), Decimal('15.5'), 0))
        strategy._bars.append(MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                                              Decimal('50'), Decimal('51'),
                                              Decimal('49'), Decimal('50.5'), 200000))
    
    strategy.on_bar(sample_vix_bar)
    # Should not process (no exception, no signals)
    assert len(strategy.get_signals()) == 0


def test_on_bar_processes_tqqq_for_stop_loss(strategy, sample_tqqq_bar):
    """Test that on_bar() processes TQQQ bars for stop-loss checking."""
    # Setup active position with stop-loss
    strategy._bars = [sample_tqqq_bar] * 111
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.50')
    strategy.stop_loss_price = Decimal('40.00')  # High stop, won't trigger
    strategy._symbols_validated = True

    # Process TQQQ bar
    strategy.on_bar(sample_tqqq_bar)

    # Verify stop-loss was checked (no exit since stop not hit)
    assert strategy.current_position_symbol == 'TQQQ'


def test_on_bar_skips_if_insufficient_bars(strategy, sample_qqq_bar):
    """Test that on_bar() skips processing if insufficient bars."""
    # Setup only a few bars
    strategy._bars = [sample_qqq_bar] * 10
    strategy._symbols_validated = True

    # Process bar
    strategy.on_bar(sample_qqq_bar)

    # Should not process (no signals)
    assert len(strategy.get_signals()) == 0


def test_on_bar_skips_if_no_vix_data(strategy, sample_qqq_bar):
    """Test that on_bar() skips if VIX data not available."""
    # Setup bars without VIX
    strategy._bars = [sample_qqq_bar] * 111
    strategy._symbols_validated = True

    # Process bar
    strategy.on_bar(sample_qqq_bar)

    # Should skip (no VIX data)
    assert len(strategy.get_signals()) == 0


@patch('jutsu_engine.strategies.MACD_Trend.macd')
@patch('jutsu_engine.strategies.MACD_Trend.ema')
def test_on_bar_state_change_triggers_rebalance(mock_ema, mock_macd, strategy, sample_qqq_bar):
    """Test that on_bar() rebalances on state change."""
    import pandas as pd

    # Setup mocks - OUT state (MACD < Signal)
    mock_macd.return_value = (
        pd.Series([Decimal('0.5')]),  # MACD line
        pd.Series([Decimal('1.0')]),  # Signal line
        pd.Series([Decimal('-0.5')])  # Histogram
    )
    mock_ema.return_value = pd.Series([Decimal('395.00')])  # EMA < Price

    # Setup bars
    from datetime import timedelta
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(112):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('$VIX', base_date + timedelta(days=i),
                            Decimal('15'), Decimal('16'), Decimal('14'),
                            Decimal('15.5'), 0)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Set previous state to IN (will change to OUT)
    strategy.previous_state = 'IN'
    strategy._positions = {'TQQQ': 100}
    strategy._symbols_validated = True

    # Process bar
    strategy.on_bar(sample_qqq_bar)

    # Verify state changed to OUT
    assert strategy.previous_state == 'OUT'

    # Verify liquidation signal generated
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'SELL'


# ========================================
# 7. Stop-Loss Tests (3 tests)
# ========================================

def test_check_stop_loss_triggers_on_breach(strategy):
    """Test that stop-loss triggers when price breaches stop level."""
    # Setup active position
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.00')
    strategy.stop_loss_price = Decimal('45.00')
    strategy._positions = {'TQQQ': 100}

    # Create bar with price below stop
    bar = MarketDataEvent(
        'TQQQ', datetime(2024, 1, 15, tzinfo=timezone.utc),
        Decimal('44.00'), Decimal('46.00'), Decimal('43.00'),
        Decimal('44.50'), 200000
    )

    # Check stop-loss
    strategy._check_stop_loss(bar)

    # Verify exit signal generated
    signals = strategy.get_signals()
    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == 'TQQQ'
    assert signal.signal_type == 'SELL'
    assert signal.portfolio_percent == Decimal('0.0')

    # Verify tracking cleared
    assert strategy.current_position_symbol is None
    assert strategy.previous_state is None


def test_check_stop_loss_no_trigger_above_stop(strategy):
    """Test that stop-loss does not trigger when price above stop."""
    # Setup active position
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.00')
    strategy.stop_loss_price = Decimal('45.00')

    # Create bar with price above stop
    bar = MarketDataEvent(
        'TQQQ', datetime(2024, 1, 15, tzinfo=timezone.utc),
        Decimal('48.00'), Decimal('51.00'), Decimal('47.00'),
        Decimal('50.50'), 200000
    )

    # Check stop-loss
    strategy._check_stop_loss(bar)

    # Verify no exit signal
    signals = strategy.get_signals()
    assert len(signals) == 0

    # Verify tracking maintained
    assert strategy.current_position_symbol == 'TQQQ'


def test_check_stop_loss_ignores_wrong_symbol(strategy, sample_qqq_bar):
    """Test that stop-loss checking ignores bars from other symbols."""
    # Setup active TQQQ position
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.00')
    strategy.stop_loss_price = Decimal('45.00')

    # Process QQQ bar (not TQQQ)
    strategy._check_stop_loss(sample_qqq_bar)

    # Verify no processing (no signals, tracking maintained)
    signals = strategy.get_signals()
    assert len(signals) == 0
    assert strategy.current_position_symbol == 'TQQQ'


# ========================================
# 8. Integration Tests (2 tests)
# ========================================

@patch('jutsu_engine.strategies.MACD_Trend.macd')
@patch('jutsu_engine.strategies.MACD_Trend.ema')
@patch('jutsu_engine.strategies.MACD_Trend.atr')
def test_integration_full_in_to_out_cycle(mock_atr, mock_ema, mock_macd, strategy):
    """Test full cycle: None → IN → OUT."""
    import pandas as pd

    # Setup mocks for IN state (all conditions met)
    mock_macd.return_value = (
        pd.Series([Decimal('1.5')]),  # MACD line > Signal
        pd.Series([Decimal('1.0')]),  # Signal line
        pd.Series([Decimal('0.5')])   # Histogram
    )
    mock_ema.return_value = pd.Series([Decimal('395.00')])  # EMA < Price (trend up)
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Setup comprehensive bar data
    from datetime import timedelta
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(112):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('$VIX', base_date + timedelta(days=i),
                            Decimal('15'), Decimal('16'), Decimal('14'),
                            Decimal('15.5'), 0)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    strategy._symbols_validated = True

    # Process bar 1: None → IN (should generate BUY)
    bar1 = MarketDataEvent('QQQ', base_date + timedelta(days=112),
                           Decimal('400'), Decimal('401'), Decimal('399'),
                           Decimal('400.5'), 100000)
    strategy.on_bar(bar1)

    # Verify IN state and buy signal
    assert strategy.previous_state == 'IN'
    signals1 = strategy.get_signals()
    assert len(signals1) == 1
    assert signals1[0].signal_type == 'BUY'
    assert signals1[0].symbol == 'TQQQ'

    # Setup position from buy
    strategy._positions = {'TQQQ': 100}

    # Change mocks to OUT state (MACD < Signal)
    mock_macd.return_value = (
        pd.Series([Decimal('0.5')]),  # MACD line < Signal
        pd.Series([Decimal('1.0')]),  # Signal line
        pd.Series([Decimal('-0.5')])  # Histogram
    )

    # Process bar 2: IN → OUT (should generate SELL)
    bar2 = MarketDataEvent('QQQ', base_date + timedelta(days=113),
                           Decimal('400'), Decimal('401'), Decimal('399'),
                           Decimal('400.5'), 100000)
    strategy.on_bar(bar2)

    # Verify OUT state and sell signal
    assert strategy.previous_state == 'OUT'
    signals2 = strategy.get_signals()
    assert len(signals2) == 1
    assert signals2[0].signal_type == 'SELL'
    assert signals2[0].symbol == 'TQQQ'


def test_integration_never_generates_sqqq_signals(strategy):
    """Test that strategy NEVER generates SQQQ signals (long-only verification)."""
    import pandas as pd
    from unittest.mock import patch

    with patch('jutsu_engine.strategies.MACD_Trend.macd') as mock_macd, \
         patch('jutsu_engine.strategies.MACD_Trend.ema') as mock_ema:

        # Setup mocks for OUT state (MACD bearish)
        mock_macd.return_value = (
            pd.Series([Decimal('-1.5')]),  # MACD line < 0
            pd.Series([Decimal('-1.0')]),  # Signal line
            pd.Series([Decimal('-0.5')])   # Histogram
        )
        mock_ema.return_value = pd.Series([Decimal('405.00')])  # EMA > Price (trend down)

        # Setup bars
        from datetime import timedelta
        base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        strategy._bars = []
        for i in range(112):
            strategy._bars.append(
                MarketDataEvent('QQQ', base_date + timedelta(days=i),
                                Decimal('400'), Decimal('401'), Decimal('399'),
                                Decimal('400.5'), 100000)
            )
            strategy._bars.append(
                MarketDataEvent('$VIX', base_date + timedelta(days=i),
                                Decimal('15'), Decimal('16'), Decimal('14'),
                                Decimal('15.5'), 0)
            )
            strategy._bars.append(
                MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                                Decimal('50'), Decimal('51'), Decimal('49'),
                                Decimal('50.5'), 200000)
            )

        strategy._symbols_validated = True

        # Process bar (OUT state - bearish conditions)
        bar = MarketDataEvent('QQQ', base_date + timedelta(days=112),
                              Decimal('400'), Decimal('401'), Decimal('399'),
                              Decimal('400.5'), 100000)
        strategy.on_bar(bar)

        # Verify OUT state (should be CASH, not SQQQ)
        assert strategy.previous_state == 'OUT'
        signals = strategy.get_signals()
        # No signals generated (OUT state = stay in CASH)
        assert len(signals) == 0
        # Verify never generates SQQQ signals
        for signal in signals:
            assert signal.symbol != 'SQQQ', "Long-only strategy generated SQQQ signal!"
