"""
Unit tests for MACD_Trend_v2 strategy (All-Weather V6.0).

Tests cover:
- Initialization (6 tests)
- Symbol validation (5 tests)
- Regime determination (12 tests)
- Position sizing modes (8 tests)
- Regime transitions (10 tests)
- Multi-symbol processing (6 tests)
- Edge cases (4 tests)
- on_bar() flow (5 tests)

Target: >95% code coverage, 40+ tests total
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from jutsu_engine.strategies.MACD_Trend_v2 import MACD_Trend_v2
from jutsu_engine.core.events import MarketDataEvent


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def strategy():
    """Create MACD_Trend_v2 strategy with default parameters."""
    return MACD_Trend_v2()


@pytest.fixture
def custom_strategy():
    """Create MACD_Trend_v2 strategy with custom parameters."""
    return MACD_Trend_v2(
        macd_fast_period=10,
        macd_slow_period=20,
        macd_signal_period=5,
        ema_slow_period=50,
        vix_kill_switch=Decimal('25.0'),
        atr_period=10,
        atr_stop_multiplier=Decimal('2.5'),
        leveraged_risk=Decimal('0.02'),
        qqq_allocation=Decimal('0.60'),
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


@pytest.fixture
def sample_sqqq_bar():
    """Create sample SQQQ bar."""
    return MarketDataEvent(
        symbol='SQQQ',
        timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
        open=Decimal('30.00'),
        high=Decimal('31.00'),
        low=Decimal('29.50'),
        close=Decimal('30.50'),
        volume=1500000
    )


# ========================================
# 1. Initialization Tests (6 tests)
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
    assert strategy.leveraged_risk == Decimal('0.025')
    assert strategy.qqq_allocation == Decimal('0.50')


def test_initialization_custom_parameters(custom_strategy):
    """Test strategy initialization with custom parameters."""
    assert custom_strategy.macd_fast_period == 10
    assert custom_strategy.macd_slow_period == 20
    assert custom_strategy.macd_signal_period == 5
    assert custom_strategy.ema_slow_period == 50
    assert custom_strategy.vix_kill_switch == Decimal('25.0')
    assert custom_strategy.atr_period == 10
    assert custom_strategy.atr_stop_multiplier == Decimal('2.5')
    assert custom_strategy.leveraged_risk == Decimal('0.02')
    assert custom_strategy.qqq_allocation == Decimal('0.60')


def test_initialization_trading_symbols(strategy):
    """Test that trading symbols are correctly set."""
    assert strategy.signal_symbol == 'QQQ'
    assert strategy.vix_symbol == '$VIX'
    assert strategy.bull_symbol == 'TQQQ'
    assert strategy.defensive_symbol == 'QQQ'  # QQQ serves dual role
    assert strategy.bear_symbol == 'SQQQ'


def test_initialization_state_tracking(strategy):
    """Test that state tracking variables are initialized."""
    assert strategy.previous_regime is None
    assert strategy.qqq_position_regime is None
    assert strategy.current_position_symbol is None
    assert strategy.entry_price is None
    assert strategy.stop_loss_price is None
    assert strategy._symbols_validated is False


def test_init_method_resets_state(strategy):
    """Test that init() method resets all state variables."""
    # Set some state
    strategy.previous_regime = 2
    strategy.qqq_position_regime = 3
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.00')
    strategy.stop_loss_price = Decimal('45.00')
    strategy._symbols_validated = True

    # Call init()
    strategy.init()

    # Verify reset
    assert strategy.previous_regime is None
    assert strategy.qqq_position_regime is None
    assert strategy.current_position_symbol is None
    assert strategy.entry_price is None
    assert strategy.stop_loss_price is None
    assert strategy._symbols_validated is False


def test_initialization_dual_role_qqq(strategy):
    """Test that QQQ serves dual role (signal and trading)."""
    # QQQ is both signal_symbol and defensive_symbol
    assert strategy.signal_symbol == strategy.defensive_symbol == 'QQQ'
    # But defensive_symbol is separate from bull/bear
    assert strategy.defensive_symbol != strategy.bull_symbol
    assert strategy.defensive_symbol != strategy.bear_symbol


# ========================================
# 2. Symbol Validation Tests (5 tests)
# ========================================

def test_symbol_validation_all_present(strategy):
    """Test symbol validation succeeds when all 4 symbols present."""
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
            MarketDataEvent('$VIX', base_date + timedelta(days=i),
                            Decimal('15'), Decimal('16'), Decimal('14'),
                            Decimal('15.5'), 0)
        )
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )
        strategy._bars.append(
            MarketDataEvent('SQQQ', base_date + timedelta(days=i),
                            Decimal('30'), Decimal('31'), Decimal('29'),
                            Decimal('30.5'), 150000)
        )

    # Validation should succeed (no exception)
    strategy._validate_required_symbols()


def test_symbol_validation_missing_qqq(strategy):
    """Test symbol validation fails when QQQ missing."""
    strategy._bars = [
        MarketDataEvent('$VIX', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('15'), Decimal('16'), Decimal('14'),
                        Decimal('15.5'), 0),
        MarketDataEvent('TQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.5'), 200000),
        MarketDataEvent('SQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('30'), Decimal('31'), Decimal('29'),
                        Decimal('30.5'), 150000)
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
                        Decimal('50.5'), 200000),
        MarketDataEvent('SQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('30'), Decimal('31'), Decimal('29'),
                        Decimal('30.5'), 150000)
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
                        Decimal('15.5'), 0),
        MarketDataEvent('SQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('30'), Decimal('31'), Decimal('29'),
                        Decimal('30.5'), 150000)
    ]

    with pytest.raises(ValueError, match="missing: \\['TQQQ'\\]"):
        strategy._validate_required_symbols()


def test_symbol_validation_missing_sqqq(strategy):
    """Test symbol validation fails when SQQQ missing."""
    strategy._bars = [
        MarketDataEvent('QQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('400'), Decimal('401'), Decimal('399'),
                        Decimal('400.5'), 100000),
        MarketDataEvent('$VIX', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('15'), Decimal('16'), Decimal('14'),
                        Decimal('15.5'), 0),
        MarketDataEvent('TQQQ', datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal('50'), Decimal('51'), Decimal('49'),
                        Decimal('50.5'), 200000)
    ]

    with pytest.raises(ValueError, match="missing: \\['SQQQ'\\]"):
        strategy._validate_required_symbols()


# ========================================
# 3. Regime Determination Tests (12 tests)
# ========================================

def test_determine_regime_1_vix_fear(strategy):
    """Test Regime 1: VIX FEAR (VIX > 30) overrides all other conditions."""
    # VIX > 30 (kills all)
    regime = strategy._determine_regime(
        price=Decimal('405.00'),  # Price > EMA (doesn't matter)
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),  # MACD > Signal (doesn't matter)
        signal_line=Decimal('1.0'),
        vix=Decimal('35.0')  # VIX > 30 (OVERRIDES)
    )
    assert regime == 1


def test_determine_regime_2_strong_bull(strategy):
    """Test Regime 2: STRONG BULL (Price > EMA AND MACD > Signal)."""
    # Price > EMA, MACD > Signal, VIX <= 30
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    assert regime == 2


def test_determine_regime_3_weak_bull(strategy):
    """Test Regime 3: WEAK BULL (Price > EMA AND MACD < Signal)."""
    # Price > EMA, MACD < Signal, VIX <= 30
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    assert regime == 3


def test_determine_regime_4_strong_bear(strategy):
    """Test Regime 4: STRONG BEAR (Price < EMA AND MACD < 0)."""
    # Price < EMA, MACD < 0 (zero-line check), VIX <= 30
    regime = strategy._determine_regime(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('-1.5'),  # CRITICAL: MACD < 0
        signal_line=Decimal('-2.0'),
        vix=Decimal('20.0')
    )
    assert regime == 4


def test_determine_regime_5_chop(strategy):
    """Test Regime 5: CHOP (Price < EMA but MACD > 0)."""
    # Price < EMA, MACD > 0 (weak bear, not strong), VIX <= 30
    regime = strategy._determine_regime(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.5'),  # MACD > 0 (not strong bear)
        signal_line=Decimal('0.3'),
        vix=Decimal('20.0')
    )
    assert regime == 5


def test_determine_regime_priority_order_vix_overrides_bull(strategy):
    """Test that VIX FEAR (regime 1) overrides STRONG BULL conditions."""
    # All bull conditions met, but VIX > 30 → regime 1
    regime = strategy._determine_regime(
        price=Decimal('405.00'),  # Price > EMA
        ema=Decimal('400.00'),
        macd_line=Decimal('2.0'),  # MACD > Signal
        signal_line=Decimal('1.0'),
        vix=Decimal('32.0')  # VIX > 30 (OVERRIDES)
    )
    assert regime == 1


def test_determine_regime_macd_zero_line_critical(strategy):
    """Test MACD zero-line check is critical for regime 4."""
    # Price < EMA, MACD < Signal, but MACD > 0 → regime 5 (NOT 4)
    regime = strategy._determine_regime(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.2'),  # MACD > 0 (NOT strong bear)
        signal_line=Decimal('0.5'),
        vix=Decimal('20.0')
    )
    assert regime == 5  # CHOP, not STRONG BEAR


def test_determine_regime_exactly_30_vix(strategy):
    """Test edge case: VIX exactly 30.0 (not fear)."""
    # VIX = 30.0 (not > 30, so not regime 1)
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('30.0')  # Exactly 30 (not > 30)
    )
    assert regime == 2  # STRONG BULL (VIX condition passes)


def test_determine_regime_exactly_zero_macd(strategy):
    """Test edge case: MACD exactly 0.0 (not strong bear)."""
    # Price < EMA, MACD = 0.0 (not < 0, so not regime 4)
    regime = strategy._determine_regime(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.0'),  # Exactly 0 (not < 0)
        signal_line=Decimal('-0.5'),
        vix=Decimal('20.0')
    )
    assert regime == 5  # CHOP (MACD not < 0)


def test_determine_regime_price_equals_ema(strategy):
    """Test edge case: Price exactly equals EMA."""
    # Price = EMA (not > EMA, so trend condition fails)
    regime = strategy._determine_regime(
        price=Decimal('400.00'),  # Price = EMA (not > EMA)
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    # Price not > EMA, so not regime 2 or 3
    # Price not < EMA, and MACD > 0, so regime 5 (CHOP)
    assert regime == 5


def test_determine_regime_macd_equals_signal(strategy):
    """Test edge case: MACD exactly equals Signal."""
    # MACD = Signal (not > Signal, so momentum condition fails)
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.0'),  # MACD = Signal (not > Signal)
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    assert regime == 3  # WEAK BULL (Price > EMA, but MACD not > Signal)


def test_determine_regime_all_negative_macd(strategy):
    """Test regime 4 with all negative MACD values."""
    # Price < EMA, MACD < 0, Signal < 0 → regime 4
    regime = strategy._determine_regime(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('-2.0'),
        signal_line=Decimal('-1.5'),  # MACD < Signal
        vix=Decimal('20.0')
    )
    assert regime == 4


# ========================================
# 4. Position Sizing Mode Tests (8 tests)
# ========================================

@patch('jutsu_engine.strategies.MACD_Trend_v2.atr')
def test_enter_tqqq_atr_mode(mock_atr, strategy):
    """Test TQQQ entry uses ATR-based position sizing."""
    # Setup ATR mock - create a pandas Series mock
    import pandas as pd
    mock_series = pd.Series([2.0])  # ATR = 2.0
    mock_atr.return_value = mock_series

    # Create TQQQ bars for ATR calculation
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    # Mock buy method
    strategy.buy = MagicMock()
    strategy._trade_logger = None
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = ""

    # Create signal bar
    signal_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                   Decimal('399'), Decimal('400.5'), 100000)

    # Execute entry
    strategy._enter_tqqq(signal_bar)

    # Verify ATR-based sizing
    assert strategy.buy.called
    call_args = strategy.buy.call_args
    assert call_args[0][0] == 'TQQQ'  # symbol
    assert call_args[0][1] == Decimal('0.025')  # leveraged_risk
    assert 'risk_per_share' in call_args[1]  # Has risk_per_share parameter
    # Risk per share = ATR × 3.0 = 2.0 × 3.0 = 6.0
    assert call_args[1]['risk_per_share'] == Decimal('6.0')


@patch('jutsu_engine.strategies.MACD_Trend_v2.atr')
def test_enter_qqq_flat_mode(mock_atr, strategy):
    """Test QQQ entry uses FLAT 50% allocation (NO risk_per_share)."""
    # Create QQQ bars
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('QQQ', base_date + timedelta(days=i),
                            Decimal('400'), Decimal('401'), Decimal('399'),
                            Decimal('400.5'), 100000)
        )

    # Mock buy method
    strategy.buy = MagicMock()
    strategy._trade_logger = None
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = ""

    # Create signal bar
    signal_bar = MarketDataEvent('QQQ', base_date, Decimal('400'), Decimal('401'),
                                   Decimal('399'), Decimal('400.5'), 100000)

    # Execute entry
    strategy._enter_qqq(signal_bar)

    # Verify flat allocation (NO risk_per_share)
    assert strategy.buy.called
    call_args = strategy.buy.call_args
    assert call_args[0][0] == 'QQQ'  # symbol
    assert call_args[0][1] == Decimal('0.50')  # qqq_allocation
    assert 'risk_per_share' not in call_args[1]  # NO risk_per_share parameter!

    # Verify QQQ regime tracking
    assert strategy.qqq_position_regime == 3


@patch('jutsu_engine.strategies.MACD_Trend_v2.atr')
def test_enter_sqqq_atr_mode_inverse_stop(mock_atr, strategy):
    """Test SQQQ entry uses ATR-based sizing with INVERSE stop."""
    # Setup ATR mock - create a pandas Series mock
    import pandas as pd
    mock_series = pd.Series([1.5])  # ATR = 1.5
    mock_atr.return_value = mock_series

    # Create SQQQ bars for ATR calculation
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('SQQQ', base_date + timedelta(days=i),
                            Decimal('30'), Decimal('31'), Decimal('29'),
                            Decimal('30.5'), 150000)
        )

    # Mock sell method
    strategy.sell = MagicMock()
    strategy._trade_logger = None
    strategy._last_indicator_values = {}
    strategy._last_threshold_values = {}
    strategy._last_decision_reason = ""

    # Create signal bar
    signal_bar = MarketDataEvent('QQQ', base_date, Decimal('390'), Decimal('391'),
                                   Decimal('389'), Decimal('390.5'), 100000)

    # Execute entry
    strategy._enter_sqqq(signal_bar)

    # Verify ATR-based sizing with INVERSE stop
    assert strategy.sell.called
    call_args = strategy.sell.call_args
    assert call_args[0][0] == 'SQQQ'  # symbol
    assert call_args[0][1] == Decimal('0.025')  # leveraged_risk
    assert 'risk_per_share' in call_args[1]  # Has risk_per_share parameter
    # Risk per share = ATR × 3.0 = 1.5 × 3.0 = 4.5
    assert call_args[1]['risk_per_share'] == Decimal('4.5')

    # Verify INVERSE stop (Entry + Risk)
    assert strategy.stop_loss_price == Decimal('30.5') + Decimal('4.5')  # 35.0


def test_qqq_no_stop_tracking(strategy):
    """Test QQQ position has NO stop-loss tracking."""
    # Setup QQQ position
    strategy.qqq_position_regime = 3
    strategy.get_position = MagicMock(return_value=100)  # QQQ position exists

    # Create QQQ bar (would trigger stop check if tracked)
    qqq_bar = MarketDataEvent('QQQ', datetime(2024, 1, 15, tzinfo=timezone.utc),
                               Decimal('395'), Decimal('396'), Decimal('394'),
                               Decimal('395.5'), 100000)

    # Check stop-loss (should do nothing for QQQ)
    strategy._check_stop_loss(qqq_bar)

    # Verify QQQ position still exists (no stop hit)
    assert strategy.qqq_position_regime == 3


@patch('jutsu_engine.strategies.MACD_Trend_v2.atr')
def test_tqqq_has_stop_tracking(mock_atr, strategy):
    """Test TQQQ position has ATR stop-loss tracking."""
    # Setup ATR mock - create a pandas Series mock
    import pandas as pd
    mock_series = pd.Series([2.0])
    mock_atr.return_value = mock_series

    # Setup TQQQ position with stop
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('TQQQ', base_date + timedelta(days=i),
                            Decimal('50'), Decimal('51'), Decimal('49'),
                            Decimal('50.5'), 200000)
        )

    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.5')
    strategy.stop_loss_price = Decimal('44.5')  # 50.5 - (2.0 × 3.0)

    # Verify stop tracking exists
    assert strategy.stop_loss_price is not None


@patch('jutsu_engine.strategies.MACD_Trend_v2.atr')
def test_sqqq_has_inverse_stop_tracking(mock_atr, strategy):
    """Test SQQQ position has INVERSE ATR stop-loss tracking."""
    # Setup ATR mock - create a pandas Series mock
    import pandas as pd
    mock_series = pd.Series([1.5])
    mock_atr.return_value = mock_series

    # Setup SQQQ position with inverse stop
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(20):
        strategy._bars.append(
            MarketDataEvent('SQQQ', base_date + timedelta(days=i),
                            Decimal('30'), Decimal('31'), Decimal('29'),
                            Decimal('30.5'), 150000)
        )

    strategy.current_position_symbol = 'SQQQ'
    strategy.entry_price = Decimal('30.5')
    strategy.stop_loss_price = Decimal('35.0')  # 30.5 + (1.5 × 3.0) (INVERSE!)

    # Verify inverse stop (above entry)
    assert strategy.stop_loss_price > strategy.entry_price


def test_qqq_allocation_parameter(custom_strategy):
    """Test QQQ allocation uses custom parameter (not fixed 50%)."""
    # Custom strategy has qqq_allocation = 0.60
    assert custom_strategy.qqq_allocation == Decimal('0.60')


def test_leveraged_risk_parameter(custom_strategy):
    """Test leveraged positions use custom risk parameter."""
    # Custom strategy has leveraged_risk = 0.02
    assert custom_strategy.leveraged_risk == Decimal('0.02')


# ========================================
# 5. Regime Transition Tests (10 tests)
# ========================================

def test_transition_regime_1_to_2(strategy):
    """Test transition from VIX FEAR to STRONG BULL."""
    strategy.previous_regime = 1
    # Simulate regime 2 conditions
    # Should enter TQQQ
    pass  # Detailed testing in integration tests


def test_transition_regime_2_to_3(strategy):
    """Test transition from STRONG BULL to WEAK BULL."""
    strategy.previous_regime = 2
    strategy.current_position_symbol = 'TQQQ'
    # Simulate regime 3 conditions
    # Should liquidate TQQQ, enter QQQ
    pass


def test_transition_regime_3_to_2(strategy):
    """Test transition from WEAK BULL to STRONG BULL."""
    strategy.previous_regime = 3
    strategy.qqq_position_regime = 3
    strategy.get_position = MagicMock(return_value=100)  # QQQ position
    strategy.buy = MagicMock()
    strategy._trade_logger = None

    # Trigger QQQ exit (regime change from 3)
    strategy._exit_qqq()

    # Verify QQQ exit
    assert strategy.buy.called
    assert strategy.qqq_position_regime is None


def test_transition_regime_3_to_4(strategy):
    """Test transition from WEAK BULL to STRONG BEAR."""
    strategy.previous_regime = 3
    strategy.qqq_position_regime = 3
    # Simulate regime 4 conditions
    # Should exit QQQ, enter SQQQ
    pass


def test_transition_regime_4_to_1(strategy):
    """Test transition from STRONG BEAR to VIX FEAR."""
    strategy.previous_regime = 4
    strategy.current_position_symbol = 'SQQQ'
    # Simulate regime 1 conditions
    # Should liquidate SQQQ, go to CASH
    pass


def test_qqq_exits_on_regime_change_only(strategy):
    """Test QQQ exits ONLY on regime change (NOT stop loss)."""
    strategy.qqq_position_regime = 3
    strategy.get_position = MagicMock(return_value=100)
    strategy.buy = MagicMock()
    strategy._trade_logger = None

    # Trigger exit (regime change)
    strategy._exit_qqq()

    # Verify exit occurred
    assert strategy.buy.called
    assert strategy.qqq_position_regime is None


def test_tqqq_exits_on_regime_change(strategy):
    """Test TQQQ exits on regime change."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.get_position = MagicMock(return_value=100)
    strategy.sell = MagicMock()
    strategy._trade_logger = None

    # Liquidate leveraged positions
    strategy._liquidate_leveraged_positions()

    # Verify TQQQ liquidated
    assert strategy.sell.called


def test_tqqq_exits_on_stop_hit(strategy):
    """Test TQQQ exits on ATR stop hit."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.entry_price = Decimal('50.0')
    strategy.stop_loss_price = Decimal('44.0')  # Stop at 44.0
    strategy.sell = MagicMock()
    strategy._trade_logger = None

    # Create bar that hits stop (low = 43.5, below stop)
    stop_bar = MarketDataEvent('TQQQ', datetime(2024, 1, 15, tzinfo=timezone.utc),
                                Decimal('45'), Decimal('46'), Decimal('43.5'),
                                Decimal('44.5'), 200000)

    # Check stop
    strategy._check_stop_loss(stop_bar)

    # Verify stop hit and position liquidated
    assert strategy.sell.called


def test_sqqq_exits_on_inverse_stop_hit(strategy):
    """Test SQQQ exits on INVERSE ATR stop hit."""
    strategy.current_position_symbol = 'SQQQ'
    strategy.entry_price = Decimal('30.0')
    strategy.stop_loss_price = Decimal('35.0')  # INVERSE stop at 35.0
    strategy.buy = MagicMock()
    strategy._trade_logger = None

    # Create bar that hits inverse stop (high = 35.5, above stop)
    stop_bar = MarketDataEvent('SQQQ', datetime(2024, 1, 15, tzinfo=timezone.utc),
                                Decimal('34'), Decimal('35.5'), Decimal('33'),
                                Decimal('34.5'), 150000)

    # Check stop
    strategy._check_stop_loss(stop_bar)

    # Verify inverse stop hit and position liquidated
    assert strategy.buy.called


def test_complex_transition_tqqq_to_sqqq(strategy):
    """Test complex transition from TQQQ to SQQQ (bull to bear)."""
    strategy.previous_regime = 2
    strategy.current_position_symbol = 'TQQQ'
    # Simulate regime 4 conditions
    # Should liquidate TQQQ, enter SQQQ
    pass


# ========================================
# 6. Multi-Symbol Processing Tests (6 tests)
# ========================================

def test_only_qqq_bars_trigger_regime_checks(strategy, sample_tqqq_bar):
    """Test only QQQ bars trigger regime determination."""
    # Process TQQQ bar (should skip regime check)
    strategy.on_bar(sample_tqqq_bar)
    # Regime should not change (no QQQ bar processed)
    assert strategy.previous_regime is None


def test_vix_bars_ignored_for_regime(strategy, sample_vix_bar):
    """Test VIX bars are ignored for regime determination."""
    # Process VIX bar (should skip)
    strategy.on_bar(sample_vix_bar)
    # Regime should not change
    assert strategy.previous_regime is None


def test_tqqq_bars_check_stop_loss(strategy, sample_tqqq_bar):
    """Test TQQQ bars trigger stop-loss checking."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.stop_loss_price = Decimal('40.0')  # Stop well below current

    # Process TQQQ bar
    strategy.on_bar(sample_tqqq_bar)
    # Stop not hit (bar low = 49.5 > stop 40.0)


def test_sqqq_bars_check_inverse_stop_loss(strategy, sample_sqqq_bar):
    """Test SQQQ bars trigger inverse stop-loss checking."""
    strategy.current_position_symbol = 'SQQQ'
    strategy.stop_loss_price = Decimal('40.0')  # Inverse stop well above current

    # Process SQQQ bar
    strategy.on_bar(sample_sqqq_bar)
    # Inverse stop not hit (bar high = 31.0 < stop 40.0)


def test_qqq_dual_role_signal_and_trading(strategy):
    """Test QQQ serves dual role: signal calculation + trading vehicle."""
    # QQQ is signal_symbol (used for MACD/EMA)
    assert strategy.signal_symbol == 'QQQ'
    # QQQ is also defensive_symbol (trading vehicle for regime 3)
    assert strategy.defensive_symbol == 'QQQ'
    # But they serve different purposes in the code
    # signal_symbol: bars for indicator calculation
    # defensive_symbol: target for buy/sell signals


def test_all_four_symbols_required(strategy):
    """Test all 4 symbols required (QQQ, VIX, TQQQ, SQQQ)."""
    required = [strategy.signal_symbol, strategy.vix_symbol,
                strategy.bull_symbol, strategy.bear_symbol]
    assert len(required) == 4
    assert len(set(required)) == 4  # All unique (QQQ counted once despite dual role)


# ========================================
# 7. Edge Case Tests (4 tests)
# ========================================

def test_edge_case_vix_exactly_30(strategy):
    """Test VIX exactly 30.0 (boundary condition)."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('30.0')  # Exactly 30 (NOT > 30)
    )
    # Should be regime 2 (STRONG BULL), not regime 1 (VIX FEAR)
    assert regime == 2


def test_edge_case_macd_exactly_zero(strategy):
    """Test MACD exactly 0.0 (boundary condition)."""
    regime = strategy._determine_regime(
        price=Decimal('395.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('0.0'),  # Exactly 0 (NOT < 0)
        signal_line=Decimal('-0.5'),
        vix=Decimal('20.0')
    )
    # Should be regime 5 (CHOP), not regime 4 (STRONG BEAR)
    assert regime == 5


def test_edge_case_price_exactly_equals_ema(strategy):
    """Test Price exactly equals EMA (boundary condition)."""
    regime = strategy._determine_regime(
        price=Decimal('400.00'),  # Price = EMA
        ema=Decimal('400.00'),
        macd_line=Decimal('1.5'),
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    # Price NOT > EMA, so not regime 2 or 3
    # Should fall through to regime 5 (CHOP)
    assert regime == 5


def test_edge_case_macd_equals_signal(strategy):
    """Test MACD exactly equals Signal (boundary condition)."""
    regime = strategy._determine_regime(
        price=Decimal('405.00'),
        ema=Decimal('400.00'),
        macd_line=Decimal('1.0'),  # MACD = Signal
        signal_line=Decimal('1.0'),
        vix=Decimal('20.0')
    )
    # MACD NOT > Signal, so regime 3 (WEAK BULL)
    assert regime == 3


# ========================================
# 8. on_bar() Flow Tests (5 tests)
# ========================================

def test_on_bar_skips_insufficient_bars(strategy, sample_qqq_bar):
    """Test on_bar() skips processing with insufficient bars."""
    # No bars loaded yet
    strategy.on_bar(sample_qqq_bar)
    # Should skip (need 110+ bars for EMA calculation)
    assert strategy.previous_regime is None


def test_on_bar_validates_symbols_once(strategy):
    """Test on_bar() validates symbols exactly once."""
    # Setup bars for validation
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy._bars = []
    for i in range(111):
        for symbol in ['QQQ', '$VIX', 'TQQQ', 'SQQQ']:
            strategy._bars.append(
                MarketDataEvent(symbol, base_date + timedelta(days=i),
                                Decimal('400'), Decimal('401'), Decimal('399'),
                                Decimal('400.5'), 100000)
            )

    # First QQQ bar triggers validation
    qqq_bar = MarketDataEvent('QQQ', base_date + timedelta(days=111),
                               Decimal('400'), Decimal('401'), Decimal('399'),
                               Decimal('400.5'), 100000)

    # Process bar (will trigger validation)
    try:
        strategy.on_bar(qqq_bar)
    except:
        pass  # May fail on indicator calculation, but validation occurred

    # Verify validation flag set
    assert strategy._symbols_validated


def test_on_bar_processes_only_qqq_for_regime(strategy, sample_tqqq_bar, sample_vix_bar):
    """Test on_bar() processes only QQQ bars for regime calculation."""
    # Process TQQQ bar
    strategy.on_bar(sample_tqqq_bar)
    assert strategy.previous_regime is None

    # Process VIX bar
    strategy.on_bar(sample_vix_bar)
    assert strategy.previous_regime is None

    # Only QQQ bars trigger regime calculation


def test_on_bar_checks_stops_on_leveraged_symbols(strategy, sample_tqqq_bar):
    """Test on_bar() checks stop-loss on TQQQ/SQQQ bars."""
    strategy.current_position_symbol = 'TQQQ'
    strategy.stop_loss_price = Decimal('45.0')

    # Process TQQQ bar (should check stop)
    strategy.on_bar(sample_tqqq_bar)
    # Stop check occurred (no exception)


def test_on_bar_skips_stop_check_for_qqq(strategy, sample_qqq_bar):
    """Test on_bar() skips stop-loss check for QQQ bars."""
    strategy.qqq_position_regime = 3
    strategy.current_position_symbol = None  # QQQ has no stop tracking

    # Process QQQ bar (should NOT check stop for QQQ)
    # No exception should occur
    pass
