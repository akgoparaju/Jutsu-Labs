"""
Unit tests for MACD_Trend_v4 strategy (Goldilocks V8.0).

Tests cover:
- Initialization (6 tests)
- Symbol validation (4 tests)
- Regime determination (9 tests)
- Position sizing modes (6 tests)
- Regime transitions (12 tests)
- Stop-loss (6 tests)
- Multi-symbol processing (5 tests)
- Edge cases (4 tests)
- Integration (4 tests)

Target: >90% code coverage, 56 tests total
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from jutsu_engine.strategies.MACD_Trend_v4 import MACD_Trend_v4
from jutsu_engine.core.events import MarketDataEvent


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def strategy():
    """Create MACD_Trend_v4 strategy with default parameters."""
    return MACD_Trend_v4()


@pytest.fixture
def custom_strategy():
    """Create MACD_Trend_v4 strategy with custom parameters."""
    return MACD_Trend_v4(
        macd_fast_period=10,
        macd_slow_period=20,
        macd_signal_period=5,
        ema_period=50,
        atr_period=10,
        atr_stop_multiplier=Decimal('2.5'),
        tqqq_risk=Decimal('0.02'),
        qqq_allocation=Decimal('0.70'),
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


# ========================================
# 1. Initialization Tests (6 tests)
# ========================================

def test_initialization_default_parameters(strategy):
    """Test strategy initialization with default parameters."""
    assert strategy.macd_fast_period == 12
    assert strategy.macd_slow_period == 26
    assert strategy.macd_signal_period == 9
    assert strategy.ema_period == 100
    assert strategy.atr_period == 14
    assert strategy.atr_stop_multiplier == Decimal('3.0')
    assert strategy.tqqq_risk == Decimal('0.025')
    assert strategy.qqq_allocation == Decimal('0.60')


def test_initialization_custom_parameters(custom_strategy):
    """Test strategy initialization with custom parameters."""
    assert custom_strategy.macd_fast_period == 10
    assert custom_strategy.macd_slow_period == 20
    assert custom_strategy.macd_signal_period == 5
    assert custom_strategy.ema_period == 50
    assert custom_strategy.atr_period == 10
    assert custom_strategy.atr_stop_multiplier == Decimal('2.5')
    assert custom_strategy.tqqq_risk == Decimal('0.02')
    assert custom_strategy.qqq_allocation == Decimal('0.70')


def test_initialization_trading_symbols(strategy):
    """Test that trading symbols are correctly set."""
    assert strategy.signal_symbol == 'QQQ'
    assert strategy.bull_symbol == 'TQQQ'
    assert strategy.defensive_symbol == 'QQQ'  # QQQ serves dual role


def test_initialization_state_tracking(strategy):
    """Test that state tracking variables are initialized."""
    assert strategy.current_regime is None
    assert strategy.current_position_symbol is None
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None
    assert strategy._symbols_validated is False


def test_init_method_resets_state(strategy):
    """Test that init() method resets all state variables."""
    # Set some state
    strategy.current_regime = 'TQQQ'
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')
    strategy._symbols_validated = True

    # Call init()
    strategy.init()

    # Verify reset
    assert strategy.current_regime is None
    assert strategy.current_position_symbol is None
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None
    assert strategy._symbols_validated is False


def test_initialization_dual_role_qqq(strategy):
    """Test that QQQ serves dual role (signal and trading)."""
    # QQQ is both signal_symbol and defensive_symbol
    assert strategy.signal_symbol == strategy.defensive_symbol == 'QQQ'
    # But defensive_symbol is separate from bull
    assert strategy.defensive_symbol != strategy.bull_symbol


# ========================================
# 2. Symbol Validation Tests (4 tests)
# ========================================

def test_symbol_validation_all_present(strategy):
    """Test symbol validation succeeds when both symbols present."""
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # Create bars with all required symbols (111 bars to ensure validation triggers)
    strategy._bars = []
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Validation should succeed (no exception)
    strategy._validate_required_symbols()


def test_symbol_validation_missing_qqq(strategy):
    """Test symbol validation fails when QQQ missing."""
    strategy._bars = [
        MarketDataEvent('TQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.5'), 200000)
    ]

    with pytest.raises(ValueError, match="missing: \\['QQQ'\\]"):
        strategy._validate_required_symbols()


def test_symbol_validation_missing_tqqq(strategy):
    """Test symbol validation fails when TQQQ missing."""
    strategy._bars = [
        MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('400'), Decimal('401'), Decimal('399'),
                        Decimal('400.5'), 100000)
    ]

    with pytest.raises(ValueError, match="missing: \\['TQQQ'\\]"):
        strategy._validate_required_symbols()


def test_symbol_validation_triggered_at_right_time(strategy):
    """Test symbol validation is triggered after enough bars loaded."""
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Add bars (need 110+ to trigger validation in on_bar)
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Validation hasn't run yet
    assert strategy._symbols_validated is False

    # Process a bar (should trigger validation)
    strategy.on_bar(strategy._bars[-1])

    # Validation should have run
    assert strategy._symbols_validated is True


# ========================================
# 3. Regime Determination Tests (9 tests)
# ========================================

def test_determine_regime_cash_price_below_ema(strategy):
    """Test Regime CASH: Price < EMA."""
    regime = strategy._determine_regime(
        price=Decimal('390.00'),  # Below EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('2.0'),  # Bullish MACD (doesn't matter)
        signal_line=Decimal('1.0')
    )
    assert regime == 'CASH'


def test_determine_regime_tqqq_strong_bullish(strategy):
    """Test Regime TQQQ: Price > EMA AND MACD > Signal."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),  # Above EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('2.0'),  # MACD > Signal
        signal_line=Decimal('1.0')
    )
    assert regime == 'TQQQ'


def test_determine_regime_qqq_pause(strategy):
    """Test Regime QQQ: Price > EMA AND MACD < Signal."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),  # Above EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('1.0'),  # MACD < Signal
        signal_line=Decimal('2.0')
    )
    assert regime == 'QQQ'


def test_determine_regime_qqq_macd_equal_signal(strategy):
    """Test Regime QQQ: Price > EMA AND MACD == Signal (edge case)."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),  # Above EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('1.5'),  # MACD == Signal
        signal_line=Decimal('1.5')
    )
    assert regime == 'QQQ'


def test_determine_regime_price_equal_ema_below(strategy):
    """Test Regime CASH: Price == EMA (edge case, treated as < EMA)."""
    regime = strategy._determine_regime(
        price=Decimal('400.00'),  # Equal to EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('2.0'),  # Bullish MACD
        signal_line=Decimal('1.0')
    )
    # Price == EMA does NOT satisfy > condition, so CASH
    assert regime == 'CASH'


def test_determine_regime_priority_price_filter(strategy):
    """Test priority: Price < EMA overrides MACD conditions."""
    # Price < EMA but MACD is bullish (should still be CASH)
    regime = strategy._determine_regime(
        price=Decimal('390.00'),  # Below EMA (CASH priority 1)
        ema_value=Decimal('400.00'),
        macd_line=Decimal('2.0'),  # MACD > Signal (would be TQQQ if Price > EMA)
        signal_line=Decimal('1.0')
    )
    assert regime == 'CASH'


def test_determine_regime_tqqq_strong_momentum(strategy):
    """Test Regime TQQQ: Strong momentum with large MACD spread."""
    regime = strategy._determine_regime(
        price=Decimal('410.00'),  # Above EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('5.0'),  # Strong bullish MACD
        signal_line=Decimal('1.0')
    )
    assert regime == 'TQQQ'


def test_determine_regime_qqq_weak_momentum(strategy):
    """Test Regime QQQ: Weak momentum with negative MACD."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),  # Above EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('-1.0'),  # MACD < Signal (pause)
        signal_line=Decimal('0.0')
    )
    assert regime == 'QQQ'


def test_determine_regime_cash_at_boundary(strategy):
    """Test Regime CASH: Price just below EMA."""
    regime = strategy._determine_regime(
        price=Decimal('399.99'),  # Just below EMA
        ema_value=Decimal('400.00'),
        macd_line=Decimal('2.0'),  # Bullish MACD (irrelevant)
        signal_line=Decimal('1.0')
    )
    assert regime == 'CASH'


# ========================================
# 4. Position Sizing Tests (6 tests)
# ========================================

@patch('jutsu_engine.strategies.MACD_Trend_v4.atr')
def test_tqqq_position_sizing_uses_atr(mock_atr, strategy, sample_qqq_bar):
    """Test TQQQ position sizing uses ATR-based calculation."""
    # Setup mock ATR
    import pandas as pd
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Call enter_tqqq
    strategy._enter_tqqq(sample_qqq_bar)

    # Verify ATR-based parameters
    assert strategy.current_position_symbol == 'TQQQ'
    assert strategy.tqqq_entry_price == Decimal('50.5')
    # Stop = Entry - (ATR × 3.0) = 50.5 - (2.5 × 3.0) = 50.5 - 7.5 = 43.0
    assert strategy.tqqq_stop_loss == Decimal('43.00')

    # Verify signal was generated with risk_per_share
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].portfolio_percent == Decimal('0.025')  # 2.5%
    assert signals[0].risk_per_share == Decimal('7.50')  # 2.5 × 3.0


@patch('jutsu_engine.strategies.MACD_Trend_v4.atr')
def test_tqqq_stop_loss_calculation(mock_atr, strategy, sample_qqq_bar):
    """Test TQQQ stop-loss is calculated as Entry - (ATR × 3.0)."""
    # Setup mock ATR
    import pandas as pd
    mock_atr.return_value = pd.Series([Decimal('3.00')])

    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('58'), Decimal('62'), Decimal('57'),
                            Decimal('60.0'), 200000)  # Entry at 60.0, valid OHLC
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Call enter_tqqq
    strategy._enter_tqqq(sample_qqq_bar)

    # Stop = 60.0 - (3.0 × 3.0) = 60.0 - 9.0 = 51.0
    assert strategy.tqqq_entry_price == Decimal('60.0')
    assert strategy.tqqq_stop_loss == Decimal('51.0')


def test_qqq_position_sizing_flat_allocation(strategy, sample_qqq_bar):
    """Test QQQ position sizing uses flat 60% allocation."""
    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Call enter_qqq
    strategy._enter_qqq(sample_qqq_bar)

    # Verify flat allocation (NO risk_per_share)
    assert strategy.current_position_symbol == 'QQQ'

    # Verify signal was generated WITHOUT risk_per_share
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].portfolio_percent == Decimal('0.60')  # 60%
    assert signals[0].risk_per_share is None  # NO ATR-based sizing


def test_qqq_no_stop_loss_tracking(strategy, sample_qqq_bar):
    """Test QQQ position has NO stop-loss tracking."""
    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Call enter_qqq
    strategy._enter_qqq(sample_qqq_bar)

    # Verify NO stop-loss for QQQ
    assert strategy.current_position_symbol == 'QQQ'
    assert strategy.tqqq_entry_price is None  # No TQQQ entry
    assert strategy.tqqq_stop_loss is None    # No stop-loss


@patch('jutsu_engine.strategies.MACD_Trend_v4.atr')
def test_custom_tqqq_risk_parameter(mock_atr, custom_strategy, sample_qqq_bar):
    """Test custom TQQQ risk parameter (2% instead of 2.5%)."""
    # Setup mock ATR
    import pandas as pd
    mock_atr.return_value = pd.Series([Decimal('2.00')])

    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        custom_strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.0'), 200000)
        )

    # Setup required attributes
    custom_strategy._last_decision_reason = "Test"
    custom_strategy._last_indicator_values = {}
    custom_strategy._last_threshold_values = {}

    # Call enter_tqqq
    custom_strategy._enter_tqqq(sample_qqq_bar)

    # Verify custom risk (2%)
    signals = custom_strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].portfolio_percent == Decimal('0.02')  # 2.0%
    # risk_per_share = ATR × atr_stop_multiplier = 2.0 × 2.5 = 5.0
    assert signals[0].risk_per_share == Decimal('5.00')


def test_custom_qqq_allocation_parameter(custom_strategy, sample_qqq_bar):
    """Test custom QQQ allocation parameter (70% instead of 60%)."""
    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        custom_strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    custom_strategy._last_decision_reason = "Test"
    custom_strategy._last_indicator_values = {}
    custom_strategy._last_threshold_values = {}

    # Call enter_qqq
    custom_strategy._enter_qqq(sample_qqq_bar)

    # Verify custom allocation (70%)
    signals = custom_strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].portfolio_percent == Decimal('0.70')  # 70%


# ========================================
# 5. Regime Transition Tests (12 tests)
# ========================================

def test_transition_cash_to_tqqq(strategy):
    """Test regime transition from CASH → TQQQ."""
    strategy.current_regime = 'CASH'
    strategy.current_position_symbol = None

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Mock ATR
    with patch('jutsu_engine.strategies.MACD_Trend_v4.atr') as mock_atr:
        import pandas as pd
        mock_atr.return_value = pd.Series([Decimal('2.50')])

        # Setup required attributes
        strategy._last_decision_reason = "Test"
        strategy._last_indicator_values = {}
        strategy._last_threshold_values = {}

        # Transition to TQQQ
        bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                             Decimal('399'), Decimal('400.5'), 100000)
        strategy._handle_regime_transition(bar, 'TQQQ')

    # Verify TQQQ entered
    assert strategy.current_position_symbol == 'TQQQ'
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'BUY'
    assert signals[0].symbol == 'TQQQ'


def test_transition_cash_to_qqq(strategy):
    """Test regime transition from CASH → QQQ."""
    strategy.current_regime = 'CASH'
    strategy.current_position_symbol = None

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Transition to QQQ
    bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                         Decimal('399'), Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'QQQ')

    # Verify QQQ entered
    assert strategy.current_position_symbol == 'QQQ'
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'BUY'
    assert signals[0].symbol == 'QQQ'


def test_transition_tqqq_to_cash(strategy):
    """Test regime transition from TQQQ → CASH (liquidate)."""
    strategy.current_regime = 'TQQQ'
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                                            Decimal('400'), Decimal('401'), Decimal('399'),
                                            Decimal('400.5'), 100000)

    # Transition to CASH
    bar = MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                         Decimal('400'), Decimal('401'), Decimal('399'),
                         Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'CASH')

    # Verify liquidation
    assert strategy.current_position_symbol is None
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'SELL'
    assert signals[0].symbol == 'TQQQ'
    assert signals[0].portfolio_percent == Decimal('1.0')  # 100% exit


def test_transition_qqq_to_cash(strategy):
    """Test regime transition from QQQ → CASH (liquidate)."""
    strategy.current_regime = 'QQQ'
    strategy.current_position_symbol = 'QQQ'

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                                            Decimal('400'), Decimal('401'), Decimal('399'),
                                            Decimal('400.5'), 100000)

    # Transition to CASH
    bar = MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                         Decimal('400'), Decimal('401'), Decimal('399'),
                         Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'CASH')

    # Verify liquidation
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'BUY'
    assert signals[0].symbol == 'QQQ'
    assert signals[0].portfolio_percent == Decimal('0.0')  # Exit via buy(0.0)


def test_transition_tqqq_to_qqq(strategy):
    """Test regime transition from TQQQ → QQQ (liquidate then enter)."""
    strategy.current_regime = 'TQQQ'
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                            Decimal('399'), Decimal('400.5'), 100000)

    # Transition to QQQ
    bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                         Decimal('399'), Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'QQQ')

    # Verify TQQQ liquidated and QQQ entered
    assert strategy.current_position_symbol == 'QQQ'
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None
    signals = strategy.get_signals()
    assert len(signals) == 2  # SELL TQQQ + BUY QQQ
    assert signals[0].signal_type == 'SELL'
    assert signals[0].symbol == 'TQQQ'
    assert signals[1].signal_type == 'BUY'
    assert signals[1].symbol == 'QQQ'


def test_transition_qqq_to_tqqq(strategy):
    """Test regime transition from QQQ → TQQQ (liquidate then enter)."""
    strategy.current_regime = 'QQQ'
    strategy.current_position_symbol = 'QQQ'

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                            Decimal('399'), Decimal('400.5'), 100000)

    # Mock ATR
    with patch('jutsu_engine.strategies.MACD_Trend_v4.atr') as mock_atr:
        import pandas as pd
        mock_atr.return_value = pd.Series([Decimal('2.50')])

        # Transition to TQQQ
        bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                             Decimal('399'), Decimal('400.5'), 100000)
        strategy._handle_regime_transition(bar, 'TQQQ')

    # Verify QQQ liquidated and TQQQ entered
    assert strategy.current_position_symbol == 'TQQQ'
    signals = strategy.get_signals()
    assert len(signals) == 2  # BUY QQQ (0.0 exit) + BUY TQQQ
    assert signals[0].signal_type == 'BUY'
    assert signals[0].symbol == 'QQQ'
    assert signals[0].portfolio_percent == Decimal('0.0')  # Exit
    assert signals[1].signal_type == 'BUY'
    assert signals[1].symbol == 'TQQQ'


def test_transition_no_change_cash(strategy):
    """Test no transition when already in CASH."""
    strategy.current_regime = 'CASH'
    strategy.current_position_symbol = None

    # Transition to CASH (no-op)
    bar = MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                         Decimal('400'), Decimal('401'), Decimal('399'),
                         Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'CASH')

    # Verify no changes
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 0  # No signals


def test_transition_no_change_tqqq(strategy):
    """Test no transition when already in TQQQ."""
    strategy.current_regime = 'TQQQ'
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                            Decimal('399'), Decimal('400.5'), 100000)

    # Mock ATR
    with patch('jutsu_engine.strategies.MACD_Trend_v4.atr') as mock_atr:
        import pandas as pd
        mock_atr.return_value = pd.Series([Decimal('2.50')])

        # Transition to TQQQ (should liquidate then re-enter)
        bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                             Decimal('399'), Decimal('400.5'), 100000)
        strategy._handle_regime_transition(bar, 'TQQQ')

    # Verify re-entry (liquidate + enter)
    assert strategy.current_position_symbol == 'TQQQ'
    signals = strategy.get_signals()
    assert len(signals) == 2  # SELL + BUY


def test_transition_no_change_qqq(strategy):
    """Test no transition when already in QQQ."""
    strategy.current_regime = 'QQQ'
    strategy.current_position_symbol = 'QQQ'

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                            Decimal('399'), Decimal('400.5'), 100000)

    # Transition to QQQ (should liquidate then re-enter)
    bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                         Decimal('399'), Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'QQQ')

    # Verify re-entry (liquidate + enter)
    assert strategy.current_position_symbol == 'QQQ'
    signals = strategy.get_signals()
    assert len(signals) == 2  # BUY(0.0 exit) + BUY(enter)


def test_transition_clears_tqqq_state(strategy):
    """Test that regime transition clears TQQQ stop-loss state."""
    strategy.current_regime = 'TQQQ'
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                            Decimal('399'), Decimal('400.5'), 100000)

    # Transition to QQQ
    bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                         Decimal('399'), Decimal('400.5'), 100000)
    strategy._handle_regime_transition(bar, 'QQQ')

    # Verify TQQQ state cleared
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None


def test_transition_preserves_qqq_position(strategy):
    """Test that QQQ position doesn't have stop-loss state."""
    strategy.current_regime = 'QQQ'
    strategy.current_position_symbol = 'QQQ'

    # Add bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._current_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                            Decimal('399'), Decimal('400.5'), 100000)

    # Mock ATR
    with patch('jutsu_engine.strategies.MACD_Trend_v4.atr') as mock_atr:
        import pandas as pd
        mock_atr.return_value = pd.Series([Decimal('2.50')])

        # Transition to TQQQ
        bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                             Decimal('399'), Decimal('400.5'), 100000)
        strategy._handle_regime_transition(bar, 'TQQQ')

    # Verify QQQ was liquidated and TQQQ entered with stop
    assert strategy.current_position_symbol == 'TQQQ'
    assert strategy.tqqq_entry_price is not None
    assert strategy.tqqq_stop_loss is not None


def test_liquidate_position_when_none(strategy):
    """Test _liquidate_position() is safe when no position exists."""
    strategy.current_position_symbol = None

    # Should not raise
    strategy._liquidate_position()

    # Verify no signals generated
    signals = strategy.get_signals()
    assert len(signals) == 0


# ========================================
# 6. Stop-Loss Tests (6 tests)
# ========================================

def test_tqqq_stop_loss_hit_low(strategy):
    """Test TQQQ stop-loss triggers when bar low breaches stop."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Setup required attributes
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Bar with low breaching stop
    bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('46.00'),
        high=Decimal('47.00'),
        low=Decimal('44.50'),  # Below stop
        close=Decimal('45.50'),
        volume=2000000
    )

    # Check stop-loss
    strategy._check_tqqq_stop_loss(bar)

    # Verify stop hit and position liquidated
    assert strategy.current_position_symbol is None
    assert strategy.tqqq_entry_price is None
    assert strategy.tqqq_stop_loss is None
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'SELL'
    assert signals[0].symbol == 'TQQQ'


def test_tqqq_stop_loss_exact_hit(strategy):
    """Test TQQQ stop-loss triggers when bar low equals stop."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Setup required attributes
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Bar with low exactly at stop
    bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('46.00'),
        high=Decimal('47.00'),
        low=Decimal('45.00'),  # Exactly at stop
        close=Decimal('45.50'),
        volume=2000000
    )

    # Check stop-loss
    strategy._check_tqqq_stop_loss(bar)

    # Verify stop hit
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 1


def test_tqqq_stop_loss_not_hit(strategy):
    """Test TQQQ stop-loss does not trigger when price above stop."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Bar with low above stop
    bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('50.00'),
        high=Decimal('51.00'),
        low=Decimal('49.00'),  # Above stop
        close=Decimal('50.50'),
        volume=2000000
    )

    # Check stop-loss
    strategy._check_tqqq_stop_loss(bar)

    # Verify stop NOT hit
    assert strategy.current_position_symbol == 'TQQQ'
    assert strategy.tqqq_entry_price == Decimal('50.00')
    assert strategy.tqqq_stop_loss == Decimal('45.00')
    signals = strategy.get_signals()
    assert len(signals) == 0


def test_qqq_no_stop_loss_check(strategy):
    """Test QQQ position is NOT checked for stop-loss."""
    strategy.current_position_symbol = 'QQQ'

    # QQQ bar (should be ignored by stop-loss check)
    bar = MarketDataEvent(
        symbol='QQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('400.00'),
        high=Decimal('402.00'),
        low=Decimal('390.00'),  # Big drop (but QQQ has no stop)
        close=Decimal('395.00'),
        volume=1000000
    )

    # Check stop-loss (should do nothing for QQQ)
    strategy._check_tqqq_stop_loss(bar)

    # Verify QQQ position unchanged
    assert strategy.current_position_symbol == 'QQQ'
    signals = strategy.get_signals()
    assert len(signals) == 0


def test_stop_loss_when_no_position(strategy):
    """Test stop-loss check is safe when no position exists."""
    strategy.current_position_symbol = None

    # TQQQ bar (should be ignored)
    bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('50.00'),
        high=Decimal('51.00'),
        low=Decimal('40.00'),  # Big drop (but no position)
        close=Decimal('45.00'),
        volume=2000000
    )

    # Check stop-loss (should do nothing)
    strategy._check_tqqq_stop_loss(bar)

    # Verify no changes
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 0


def test_stop_loss_forces_regime_reevaluation(strategy):
    """Test stop-loss hit clears current_regime to force re-evaluation."""
    strategy.current_regime = 'TQQQ'
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Setup required attributes
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Bar triggering stop
    bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('46.00'),
        high=Decimal('47.00'),
        low=Decimal('44.50'),  # Below stop
        close=Decimal('45.50'),
        volume=2000000
    )

    # Check stop-loss
    strategy._check_tqqq_stop_loss(bar)

    # Verify regime cleared for re-evaluation
    assert strategy.current_regime is None


# ========================================
# 7. Multi-Symbol Processing Tests (5 tests)
# ========================================

def test_on_bar_processes_qqq_only(strategy):
    """Test on_bar() only processes QQQ bars for regime calculation."""
    # Add bars but not enough for indicators
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(10):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Process QQQ bar (should return early due to insufficient data)
    bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                         Decimal('399'), Decimal('400.5'), 100000)
    strategy.on_bar(bar)

    # No signals generated (not enough data)
    signals = strategy.get_signals()
    assert len(signals) == 0


def test_on_bar_checks_tqqq_stop_only(strategy):
    """Test on_bar() only checks stop-loss for TQQQ bars."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.tqqq_entry_price = Decimal('50.00')
    strategy.tqqq_stop_loss = Decimal('45.00')

    # Setup required attributes
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Process TQQQ bar (should check stop-loss)
    bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('46.00'),
        high=Decimal('47.00'),
        low=Decimal('44.50'),  # Below stop
        close=Decimal('45.50'),
        volume=2000000
    )
    strategy.on_bar(bar)

    # Verify stop-loss was checked
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].symbol == 'TQQQ'


def test_on_bar_ignores_other_symbols(strategy):
    """Test on_bar() ignores bars from other symbols."""
    # Add some bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(10):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Process bar from unknown symbol
    bar = MarketDataEvent(
        symbol='SPY',
        timestamp=base_date,
        open=Decimal('500.00'),
        high=Decimal('502.00'),
        low=Decimal('499.00'),
        close=Decimal('501.00'),
        volume=5000000
    )
    strategy.on_bar(bar)

    # No signals generated (symbol ignored)
    signals = strategy.get_signals()
    assert len(signals) == 0


def test_multi_symbol_data_sync(strategy):
    """Test strategy handles synchronized QQQ and TQQQ data."""
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Add synchronized bars (QQQ + TQQQ for same dates)
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Validation should pass (both symbols present)
    strategy._validate_required_symbols()


def test_insufficient_data_no_signals(strategy):
    """Test no signals generated when insufficient data for indicators."""
    # Add only 50 bars (need 100+ for EMA-100)
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(50):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Process bar
    bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                         Decimal('399'), Decimal('400.5'), 100000)
    strategy.on_bar(bar)

    # No signals (insufficient data)
    signals = strategy.get_signals()
    assert len(signals) == 0


# ========================================
# 8. Edge Cases Tests (4 tests)
# ========================================

def test_edge_case_price_exactly_equal_ema(strategy):
    """Test regime determination when price exactly equals EMA."""
    regime = strategy._determine_regime(
        price=Decimal('400.00'),
        ema_value=Decimal('400.00'),  # Exact equality
        macd_line=Decimal('2.0'),
        signal_line=Decimal('1.0')
    )
    # Price == EMA does NOT satisfy > condition, so CASH
    assert regime == 'CASH'


def test_edge_case_macd_exactly_equal_signal(strategy):
    """Test regime determination when MACD exactly equals Signal."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema_value=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.5')  # Exact equality
    )
    # MACD == Signal satisfies <= condition, so QQQ
    assert regime == 'QQQ'


def test_edge_case_zero_atr(strategy):
    """Test TQQQ entry handles very small ATR gracefully."""
    # Add bars with minimal volatility
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('49.95'), Decimal('50.05'), Decimal('49.95'),
                            Decimal('50.0'), 200000)  # Minimal volatility
        )

    # Setup required attributes
    strategy._last_decision_reason = "Test"
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}

    # Mock ATR to return very small value
    with patch('jutsu_engine.strategies.MACD_Trend_v4.atr') as mock_atr:
        import pandas as pd
        mock_atr.return_value = pd.Series([Decimal('0.01')])  # Very small but positive

        # Call enter_tqqq (should handle gracefully)
        bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                             Decimal('399'), Decimal('400.5'), 100000)
        strategy._enter_tqqq(bar)

    # Verify position entered with small stop distance
    assert strategy.current_position_symbol == 'TQQQ'
    # Stop = 50.0 - (0.01 × 3.0) = 50.0 - 0.03 = 49.97
    assert strategy.tqqq_stop_loss == Decimal('49.97')


def test_edge_case_negative_prices(strategy):
    """Test strategy handles negative MACD values correctly."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema_value=Decimal('400.00'),
        macd_line=Decimal('-2.0'),  # Negative
        signal_line=Decimal('-1.0')
    )
    # MACD < Signal → QQQ
    assert regime == 'QQQ'


# ========================================
# 9. Integration Tests (4 tests)
# ========================================

@patch('jutsu_engine.strategies.MACD_Trend_v4.macd')
@patch('jutsu_engine.strategies.MACD_Trend_v4.ema')
@patch('jutsu_engine.strategies.MACD_Trend_v4.atr')
def test_integration_full_lifecycle_tqqq(mock_atr, mock_ema, mock_macd, strategy):
    """Test full lifecycle: CASH → TQQQ → CASH."""
    import pandas as pd

    # Setup mocks
    mock_macd.return_value = (
        pd.Series([Decimal('2.0')]),  # macd_line > signal
        pd.Series([Decimal('1.0')]),  # signal_line
        pd.Series([Decimal('1.0')])   # histogram
    )
    mock_ema.return_value = pd.Series([Decimal('400.00')])
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Initialize strategy
    strategy.init()

    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('405'), Decimal('406'), Decimal('404'),  # Price > EMA
                            Decimal('405.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Process bar (should enter TQQQ)
    bar = strategy._bars[-2]  # QQQ bar
    strategy.on_bar(bar)

    # Verify TQQQ entered
    assert strategy.current_regime == 'TQQQ'
    assert strategy.current_position_symbol == 'TQQQ'
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].symbol == 'TQQQ'

    # Change to bearish (Price < EMA)
    mock_ema.return_value = pd.Series([Decimal('410.00')])  # Price now below EMA

    # Add bearish bar
    strategy._bars.append(
        MarketDataEvent('QQQ', base_date + timedelta(days=112),
                        Decimal('405'), Decimal('406'), Decimal('404'),  # Price < EMA
                        Decimal('405.5'), 100000)
    )

    # Process bar (should exit to CASH)
    bar = strategy._bars[-1]
    strategy.on_bar(bar)

    # Verify CASH
    assert strategy.current_regime == 'CASH'
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 1  # Exit signal
    assert signals[0].signal_type == 'SELL'


@patch('jutsu_engine.strategies.MACD_Trend_v4.macd')
@patch('jutsu_engine.strategies.MACD_Trend_v4.ema')
def test_integration_full_lifecycle_qqq(mock_ema, mock_macd, strategy):
    """Test full lifecycle: CASH → QQQ → CASH."""
    import pandas as pd

    # Setup mocks
    mock_macd.return_value = (
        pd.Series([Decimal('1.0')]),  # macd_line < signal
        pd.Series([Decimal('2.0')]),  # signal_line
        pd.Series([Decimal('-1.0')])  # histogram
    )
    mock_ema.return_value = pd.Series([Decimal('400.00')])

    # Initialize strategy
    strategy.init()

    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('405'), Decimal('406'), Decimal('404'),  # Price > EMA
                            Decimal('405.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Process bar (should enter QQQ)
    bar = strategy._bars[-2]  # QQQ bar
    strategy.on_bar(bar)

    # Verify QQQ entered
    assert strategy.current_regime == 'QQQ'
    assert strategy.current_position_symbol == 'QQQ'
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].symbol == 'QQQ'

    # Change to bearish (Price < EMA)
    mock_ema.return_value = pd.Series([Decimal('410.00')])  # Price now below EMA

    # Add bearish bar
    strategy._bars.append(
        MarketDataEvent('QQQ', base_date + timedelta(days=112),
                        Decimal('405'), Decimal('406'), Decimal('404'),  # Price < EMA
                        Decimal('405.5'), 100000)
    )

    # Process bar (should exit to CASH)
    bar = strategy._bars[-1]
    strategy.on_bar(bar)

    # Verify CASH
    assert strategy.current_regime == 'CASH'
    assert strategy.current_position_symbol is None
    signals = strategy.get_signals()
    assert len(signals) == 1  # Exit signal


@patch('jutsu_engine.strategies.MACD_Trend_v4.macd')
@patch('jutsu_engine.strategies.MACD_Trend_v4.ema')
@patch('jutsu_engine.strategies.MACD_Trend_v4.atr')
def test_integration_tqqq_stop_loss_lifecycle(mock_atr, mock_ema, mock_macd, strategy):
    """Test full lifecycle with TQQQ stop-loss hit."""
    import pandas as pd

    # Setup mocks for TQQQ entry
    mock_macd.return_value = (
        pd.Series([Decimal('2.0')]),  # macd_line > signal
        pd.Series([Decimal('1.0')]),  # signal_line
        pd.Series([Decimal('1.0')])   # histogram
    )
    mock_ema.return_value = pd.Series([Decimal('400.00')])
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Initialize strategy
    strategy.init()

    # Add sufficient bars for entry
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('405'), Decimal('406'), Decimal('404'),
                            Decimal('405.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Process bar (enter TQQQ)
    bar = strategy._bars[-2]  # QQQ bar
    strategy.on_bar(bar)

    # Verify TQQQ entered with stop
    assert strategy.current_position_symbol == 'TQQQ'
    assert strategy.tqqq_stop_loss is not None
    strategy.get_signals()  # Clear signals

    # Add TQQQ bar that hits stop
    stop_bar = MarketDataEvent(
        symbol='TQQQ',
        timestamp=base_date + timedelta(days=112),
        open=Decimal('46.00'),
        high=Decimal('47.00'),
        low=Decimal('40.00'),  # Below stop
        close=Decimal('45.00'),
        volume=2000000
    )
    strategy._bars.append(stop_bar)

    # Process stop bar
    strategy.on_bar(stop_bar)

    # Verify stop-loss liquidation
    assert strategy.current_position_symbol is None
    assert strategy.tqqq_stop_loss is None
    assert strategy.current_regime is None  # Cleared for re-evaluation
    signals = strategy.get_signals()
    assert len(signals) == 1
    assert signals[0].signal_type == 'SELL'
    assert signals[0].symbol == 'TQQQ'


@patch('jutsu_engine.strategies.MACD_Trend_v4.macd')
@patch('jutsu_engine.strategies.MACD_Trend_v4.ema')
@patch('jutsu_engine.strategies.MACD_Trend_v4.atr')
def test_integration_regime_transition_tqqq_to_qqq(mock_atr, mock_ema, mock_macd, strategy):
    """Test regime transition: TQQQ → QQQ."""
    import pandas as pd

    # Setup mocks for TQQQ entry
    mock_macd.return_value = (
        pd.Series([Decimal('2.0')]),  # macd_line > signal
        pd.Series([Decimal('1.0')]),  # signal_line
        pd.Series([Decimal('1.0')])   # histogram
    )
    mock_ema.return_value = pd.Series([Decimal('400.00')])
    mock_atr.return_value = pd.Series([Decimal('2.50')])

    # Initialize strategy
    strategy.init()

    # Add sufficient bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(111):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('405'), Decimal('406'), Decimal('404'),
                            Decimal('405.5'), 100000)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Process bar (enter TQQQ)
    bar = strategy._bars[-2]
    strategy.on_bar(bar)
    assert strategy.current_regime == 'TQQQ'
    strategy.get_signals()  # Clear signals

    # Change to QQQ regime (MACD < Signal)
    mock_macd.return_value = (
        pd.Series([Decimal('1.0')]),  # macd_line < signal
        pd.Series([Decimal('2.0')]),  # signal_line
        pd.Series([Decimal('-1.0')])  # histogram
    )

    # Add new bar
    strategy._bars.append(
        MarketDataEvent('QQQ', base_date + timedelta(days=112),
                        Decimal('405'), Decimal('406'), Decimal('404'),
                        Decimal('405.5'), 100000)
    )

    # Process bar (should transition to QQQ)
    bar = strategy._bars[-1]
    strategy.on_bar(bar)

    # Verify transition: TQQQ liquidated, QQQ entered
    assert strategy.current_regime == 'QQQ'
    assert strategy.current_position_symbol == 'QQQ'
    signals = strategy.get_signals()
    assert len(signals) == 2  # SELL TQQQ + BUY QQQ
    assert signals[0].symbol == 'TQQQ'
    assert signals[1].symbol == 'QQQ'
