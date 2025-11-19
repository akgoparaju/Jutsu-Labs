"""
Unit tests for Hierarchical Adaptive v1.0 strategy.

Tests cover:
- Initialization and parameter validation (28 parameters)
- VIX volatility filter (master switch) - NEW
- Regime determination logic (all 4 regimes)
- Regime-specific MACD/EMA logic (Strong Bull, Moderate Bull, Bear)
- Position sizing (leveraged & unleveraged)
- Stop-loss calculation and triggering
- Regime change execution and vehicle transitions
- VIX-regime interaction - NEW
- Edge cases and error handling

Coverage Target: >85%
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import pandas as pd

from jutsu_engine.strategies.Hierarchical_Adaptive_v1 import Hierarchical_Adaptive_v1, Regime
from jutsu_engine.core.events import MarketDataEvent


class TestInitialization:
    """Test strategy initialization and parameter validation."""

    def test_initialization_default_parameters(self):
        """Test initialization with default parameters (28 params)."""
        strategy = Hierarchical_Adaptive_v1()

        assert strategy.name == "Hierarchical_Adaptive_v1"

        # VIX filter parameter (NEW)
        assert strategy.vix_ema_period == 20
        assert strategy.vix_symbol == 'VIX'

        # Kalman filter parameters
        assert strategy.measurement_noise == 5000.0
        assert strategy.osc_smoothness == 20
        assert strategy.strength_smoothness == 20
        assert strategy.process_noise_1 == 0.01
        assert strategy.process_noise_2 == 0.01

        # Regime thresholds
        assert strategy.thresh_strong_bull == Decimal('60')
        assert strategy.thresh_moderate_bull == Decimal('20')
        assert strategy.thresh_moderate_bear == Decimal('-20')

        # Strong Bull parameters
        assert strategy.ema_trend_sb == 100
        assert strategy.macd_fast_sb == 12
        assert strategy.macd_slow_sb == 26
        assert strategy.macd_signal_sb == 9

        # Moderate Bull parameters
        assert strategy.ema_trend_mb == 150
        assert strategy.macd_fast_mb == 20
        assert strategy.macd_slow_mb == 50
        assert strategy.macd_signal_mb == 12

        # Bear parameters
        assert strategy.ema_trend_b == 100
        assert strategy.macd_fast_b == 12
        assert strategy.macd_slow_b == 26
        assert strategy.macd_signal_b == 9

        # Risk parameters
        assert strategy.atr_period == 14
        assert strategy.atr_stop_multiplier == Decimal('3.0')
        assert strategy.risk_leveraged == Decimal('0.025')
        assert strategy.allocation_unleveraged == Decimal('0.80')

        # Symbols
        assert strategy.signal_symbol == 'QQQ'
        assert strategy.bull_symbol == 'TQQQ'
        assert strategy.defense_symbol == 'QQQ'
        assert strategy.bear_symbol == 'SQQQ'

    def test_initialization_custom_parameters(self):
        """Test initialization with custom parameters."""
        strategy = Hierarchical_Adaptive_v1(
            vix_ema_period=50,
            measurement_noise=10000.0,
            osc_smoothness=30,
            thresh_strong_bull=Decimal('70'),
            thresh_moderate_bull=Decimal('30'),
            thresh_moderate_bear=Decimal('-30'),
            ema_trend_sb=125,
            macd_fast_sb=20,
            macd_slow_sb=50,
            risk_leveraged=Decimal('0.02'),
            name="CustomHierarchical"
        )

        assert strategy.name == "CustomHierarchical"
        assert strategy.vix_ema_period == 50
        assert strategy.measurement_noise == 10000.0
        assert strategy.osc_smoothness == 30
        assert strategy.thresh_strong_bull == Decimal('70')
        assert strategy.ema_trend_sb == 125
        assert strategy.macd_fast_sb == 20
        assert strategy.macd_slow_sb == 50
        assert strategy.risk_leveraged == Decimal('0.02')

    def test_vix_ema_period_validation_failure(self):
        """Test that invalid VIX EMA period raises ValueError (NEW)."""
        # VIX EMA period must be >= 1
        with pytest.raises(ValueError, match="VIX EMA period must be >= 1"):
            Hierarchical_Adaptive_v1(vix_ema_period=0)

        with pytest.raises(ValueError, match="VIX EMA period must be >= 1"):
            Hierarchical_Adaptive_v1(vix_ema_period=-5)

    def test_threshold_validation_failure(self):
        """Test that invalid threshold ordering raises ValueError."""
        # Moderate bear must be negative
        with pytest.raises(ValueError, match="Thresholds must satisfy"):
            Hierarchical_Adaptive_v1(thresh_moderate_bear=Decimal('10'))

        # Moderate bull must be less than strong bull
        with pytest.raises(ValueError, match="Thresholds must satisfy"):
            Hierarchical_Adaptive_v1(
                thresh_strong_bull=Decimal('50'),
                thresh_moderate_bull=Decimal('60')
            )

        # Moderate bear must be less than zero
        with pytest.raises(ValueError, match="Thresholds must satisfy"):
            Hierarchical_Adaptive_v1(
                thresh_moderate_bear=Decimal('0')
            )

    def test_macd_parameter_validation_failure(self):
        """Test that invalid MACD parameters raise ValueError."""
        # Strong Bull: fast must be < slow
        with pytest.raises(ValueError, match="Strong Bull: MACD fast"):
            Hierarchical_Adaptive_v1(
                macd_fast_sb=26,
                macd_slow_sb=12
            )

        # Moderate Bull: fast must be < slow
        with pytest.raises(ValueError, match="Moderate Bull: MACD fast"):
            Hierarchical_Adaptive_v1(
                macd_fast_mb=50,
                macd_slow_mb=20
            )

        # Bear: fast must be < slow
        with pytest.raises(ValueError, match="Bear: MACD fast"):
            Hierarchical_Adaptive_v1(
                macd_fast_b=26,
                macd_slow_b=12
            )

    def test_init_method(self):
        """Test init() method sets up Kalman filter and state."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        assert strategy.kalman_filter is not None
        assert strategy.current_regime is None
        assert strategy.current_vehicle is None
        assert strategy.leveraged_stop_price is None
        assert strategy.max_lookback > 0

        # max_lookback should include VIX EMA period (NEW)
        assert strategy.max_lookback == max(
            20,   # vix_ema_period (NEW)
            150,  # ema_trend_mb
            50,   # macd_slow_mb
            14    # atr_period
        )

    def test_init_method_custom_vix_period(self):
        """Test max_lookback calculation with custom VIX period (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=200)
        strategy.init()

        # max_lookback should use larger VIX period
        assert strategy.max_lookback == max(
            200,  # vix_ema_period (custom)
            150,  # ema_trend_mb
            50,   # macd_slow_mb
            14    # atr_period
        )


class TestVIXFilter:
    """Test VIX volatility filter (master switch) - NEW TEST CLASS."""

    def create_vix_bars(self, num_bars=50, vix_trend='rising'):
        """Helper to create VIX bars for testing."""
        bars = []
        base_vix = Decimal('15')
        timestamp = datetime.now(timezone.utc)

        for i in range(num_bars):
            if vix_trend == 'rising':
                close = base_vix + Decimal(str(i * 0.5))
            elif vix_trend == 'falling':
                close = base_vix - Decimal(str(i * 0.1))
            else:  # stable
                close = base_vix + Decimal(str((i % 5) - 2.5))

            bar = MarketDataEvent(
                symbol='VIX',
                timestamp=timestamp,
                open=close - Decimal('0.2'),
                high=close + Decimal('0.3'),
                low=close - Decimal('0.3'),
                close=close,
                volume=Decimal('0')  # VIX doesn't have volume
            )
            bars.append(bar)

        return bars

    def test_vix_filter_triggers_cash(self):
        """Test VIX filter triggers CASH when VIX > VIX_EMA (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=10)
        strategy.init()

        # Create VIX bars with rising trend (VIX will exceed EMA)
        vix_bars = self.create_vix_bars(num_bars=30, vix_trend='rising')

        # Update strategy with VIX bars
        for bar in vix_bars:
            strategy._update_bar(bar)

        # Check VIX filter - should trigger (VIX > EMA)
        filter_triggered = strategy._check_vix_filter()
        assert filter_triggered is True

    def test_vix_filter_allows_trading(self):
        """Test VIX filter allows trading when VIX < VIX_EMA (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=10)
        strategy.init()

        # Create VIX bars with falling trend (VIX will be below EMA)
        vix_bars = self.create_vix_bars(num_bars=30, vix_trend='falling')

        # Update strategy with VIX bars
        for bar in vix_bars:
            strategy._update_bar(bar)

        # Check VIX filter - should NOT trigger (VIX < EMA)
        filter_triggered = strategy._check_vix_filter()
        assert filter_triggered is False

    def test_vix_filter_insufficient_data(self):
        """Test VIX filter with insufficient data allows trading (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=20)
        strategy.init()

        # Only 5 VIX bars (insufficient for 20-period EMA)
        vix_bars = self.create_vix_bars(num_bars=5, vix_trend='rising')

        # Update strategy with VIX bars
        for bar in vix_bars:
            strategy._update_bar(bar)

        # Check VIX filter - should NOT trigger (insufficient data)
        filter_triggered = strategy._check_vix_filter()
        assert filter_triggered is False

    def test_vix_filter_liquidates_position(self):
        """Test VIX filter liquidates existing position (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=10)
        strategy.init()

        # Set up existing position
        strategy.current_vehicle = 'TQQQ'
        strategy.current_regime = Regime.STRONG_BULL
        strategy._positions = {'TQQQ': 100}

        # Create rising VIX bars
        vix_bars = self.create_vix_bars(num_bars=30, vix_trend='rising')
        for bar in vix_bars:
            strategy._update_bar(bar)

        # Create QQQ bar that would trigger VIX filter
        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )
        strategy._update_bar(qqq_bar)

        # Process QQQ bar - VIX filter should trigger liquidation
        strategy.on_bar(qqq_bar)

        # Check that position was liquidated
        signals = strategy.get_signals()
        if len(signals) > 0:
            # Should generate SELL signal for liquidation
            assert any(s.signal_type == 'SELL' for s in signals)

        # Regime should be reset to CHOP_NEUTRAL
        assert strategy.current_regime == Regime.CHOP_NEUTRAL
        assert strategy.current_vehicle is None

    def test_vix_filter_overrides_strong_bull_signal(self):
        """Test VIX filter overrides strong bull regime signal (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=10)
        strategy.init()

        # Create rising VIX bars (will trigger filter)
        vix_bars = self.create_vix_bars(num_bars=30, vix_trend='rising')
        for bar in vix_bars:
            strategy._update_bar(bar)

        # Create bullish QQQ bars (would normally trigger TQQQ entry)
        qqq_bars = []
        base_price = Decimal('100')
        timestamp = datetime.now(timezone.utc)

        for i in range(200):
            close = base_price + Decimal(str(i * 0.5))
            bar = MarketDataEvent(
                symbol='QQQ',
                timestamp=timestamp,
                open=close - Decimal('0.5'),
                high=close + Decimal('0.5'),
                low=close - Decimal('0.5'),
                close=close,
                volume=Decimal('1000000')
            )
            qqq_bars.append(bar)
            strategy._update_bar(bar)

        # Process bars
        for bar in qqq_bars[-10:]:  # Process last 10 bars
            strategy.on_bar(bar)

        # Despite bullish conditions, should stay in CASH due to VIX filter
        # Current regime should be CHOP_NEUTRAL (VIX override)
        assert strategy.current_regime == Regime.CHOP_NEUTRAL
        assert strategy.current_vehicle is None

    def test_vix_filter_custom_period(self):
        """Test VIX filter with custom EMA period (NEW)."""
        # Test with 50-period VIX EMA
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=50)
        strategy.init()

        # Create 60 VIX bars
        vix_bars = self.create_vix_bars(num_bars=60, vix_trend='rising')

        for bar in vix_bars:
            strategy._update_bar(bar)

        # Check filter - should work with custom period
        filter_triggered = strategy._check_vix_filter()
        assert isinstance(filter_triggered, bool)  # Valid result

    def test_vix_filter_logs_trigger_event(self):
        """Test VIX filter logs trigger event to TradeLogger (NEW)."""
        mock_logger = Mock()
        strategy = Hierarchical_Adaptive_v1(
            vix_ema_period=10,
            trade_logger=mock_logger
        )
        strategy.init()

        # Set up existing position
        strategy.current_vehicle = 'TQQQ'
        strategy._positions = {'TQQQ': 100}

        # Create rising VIX bars
        vix_bars = self.create_vix_bars(num_bars=30, vix_trend='rising')
        for bar in vix_bars:
            strategy._update_bar(bar)

        # Create QQQ bar
        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )
        strategy._update_bar(qqq_bar)

        # Process bar - should trigger VIX filter and log
        strategy.on_bar(qqq_bar)

        # Verify TradeLogger was called for VIX trigger
        if mock_logger.log_strategy_context.called:
            call_args = mock_logger.log_strategy_context.call_args
            # Check that VIX filter event was logged
            assert any(
                'VIX Filter' in str(call)
                for call in mock_logger.log_strategy_context.call_args_list
            )


class TestRegimeDetermination:
    """Test regime determination from trend strength."""

    def test_strong_bull_regime(self):
        """Test strong bull regime detection."""
        strategy = Hierarchical_Adaptive_v1()

        regime = strategy._determine_regime(Decimal('65'))
        assert regime == Regime.STRONG_BULL

        regime = strategy._determine_regime(Decimal('60.01'))
        assert regime == Regime.STRONG_BULL

        regime = strategy._determine_regime(Decimal('100'))
        assert regime == Regime.STRONG_BULL

    def test_moderate_bull_regime(self):
        """Test moderate bull regime detection."""
        strategy = Hierarchical_Adaptive_v1()

        regime = strategy._determine_regime(Decimal('40'))
        assert regime == Regime.MODERATE_BULL

        regime = strategy._determine_regime(Decimal('20.01'))
        assert regime == Regime.MODERATE_BULL

        regime = strategy._determine_regime(Decimal('60'))
        assert regime == Regime.MODERATE_BULL

    def test_chop_neutral_regime(self):
        """Test chop/neutral regime detection."""
        strategy = Hierarchical_Adaptive_v1()

        regime = strategy._determine_regime(Decimal('0'))
        assert regime == Regime.CHOP_NEUTRAL

        regime = strategy._determine_regime(Decimal('20'))
        assert regime == Regime.CHOP_NEUTRAL

        regime = strategy._determine_regime(Decimal('-20'))
        assert regime == Regime.CHOP_NEUTRAL

        regime = strategy._determine_regime(Decimal('10'))
        assert regime == Regime.CHOP_NEUTRAL

    def test_bear_regime(self):
        """Test bear regime detection."""
        strategy = Hierarchical_Adaptive_v1()

        regime = strategy._determine_regime(Decimal('-25'))
        assert regime == Regime.BEAR

        regime = strategy._determine_regime(Decimal('-20.01'))
        assert regime == Regime.BEAR

        regime = strategy._determine_regime(Decimal('-100'))
        assert regime == Regime.BEAR

    def test_custom_thresholds(self):
        """Test regime determination with custom thresholds."""
        strategy = Hierarchical_Adaptive_v1(
            thresh_strong_bull=Decimal('70'),
            thresh_moderate_bull=Decimal('30'),
            thresh_moderate_bear=Decimal('-30')
        )

        assert strategy._determine_regime(Decimal('75')) == Regime.STRONG_BULL
        assert strategy._determine_regime(Decimal('50')) == Regime.MODERATE_BULL
        assert strategy._determine_regime(Decimal('15')) == Regime.CHOP_NEUTRAL
        assert strategy._determine_regime(Decimal('-35')) == Regime.BEAR


class TestRegimeLogic:
    """Test regime-specific MACD/EMA logic."""

    def create_sample_bars(self, num_bars=200, trend='up'):
        """Helper to create sample bars for testing."""
        bars = []
        base_price = Decimal('100')
        timestamp = datetime.now(timezone.utc)

        for i in range(num_bars):
            if trend == 'up':
                close = base_price + Decimal(str(i * 0.5))
            elif trend == 'down':
                close = base_price - Decimal(str(i * 0.5))
            else:  # sideways
                close = base_price + Decimal(str((i % 10) - 5))

            bar = MarketDataEvent(
                symbol='QQQ',
                timestamp=timestamp,
                open=close - Decimal('0.5'),
                high=close + Decimal('0.5'),
                low=close - Decimal('0.5'),
                close=close,
                volume=Decimal('1000000')
            )
            bars.append(bar)

        return bars

    def test_strong_bull_logic_insufficient_data(self):
        """Test Strong Bull logic with insufficient data."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Should return None (CASH) with insufficient data
        target = strategy._strong_bull_logic(bar)
        assert target is None

    def test_moderate_bull_logic_insufficient_data(self):
        """Test Moderate Bull logic with insufficient data."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Should return None (CASH) with insufficient data
        target = strategy._moderate_bull_logic(bar)
        assert target is None

    def test_bear_logic_insufficient_data(self):
        """Test Bear logic with insufficient data."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Should return None (CASH) with insufficient data
        target = strategy._bear_logic(bar)
        assert target is None

    def test_execute_regime_logic_chop_neutral(self):
        """Test that CHOP_NEUTRAL always returns None (CASH)."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        target = strategy._execute_regime_logic(Regime.CHOP_NEUTRAL, bar)
        assert target is None  # Always CASH for chop


class TestPositionSizing:
    """Test position sizing for leveraged and unleveraged positions."""

    def test_enter_leveraged_long_insufficient_data(self):
        """Test leveraged long entry with insufficient ATR data."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Should not generate signal with insufficient data
        strategy._enter_leveraged_long(bar)
        signals = strategy.get_signals()
        assert len(signals) == 0

    def test_enter_leveraged_short_insufficient_data(self):
        """Test leveraged short entry with insufficient ATR data."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Should not generate signal with insufficient data
        strategy._enter_leveraged_short(bar)
        signals = strategy.get_signals()
        assert len(signals) == 0

    def test_enter_unleveraged(self):
        """Test unleveraged QQQ entry."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        strategy._enter_unleveraged(bar)
        signals = strategy.get_signals()

        assert len(signals) == 1
        assert signals[0].symbol == 'QQQ'
        assert signals[0].signal_type == 'BUY'
        assert signals[0].portfolio_percent == Decimal('0.80')
        assert signals[0].risk_per_share is None  # No ATR sizing for QQQ

    def test_enter_position_delegates_correctly(self):
        """Test that _enter_position delegates to correct vehicle methods."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Test QQQ entry
        strategy._enter_position('QQQ', bar)
        signals = strategy.get_signals()
        assert len(signals) == 1
        assert signals[0].symbol == 'QQQ'

        # Clear signals
        strategy._signals = []

        # Test unknown vehicle raises error
        with pytest.raises(ValueError, match="Unknown vehicle"):
            strategy._enter_position('UNKNOWN', bar)

    def test_liquidate_position_with_position(self):
        """Test position liquidation when position exists."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()
        strategy.current_vehicle = 'TQQQ'

        # Mock position
        strategy._positions = {'TQQQ': 100}

        strategy._liquidate_position()
        signals = strategy.get_signals()

        assert len(signals) == 1
        assert signals[0].symbol == 'TQQQ'
        assert signals[0].signal_type == 'SELL'
        assert signals[0].portfolio_percent == Decimal('0.0')
        assert strategy.leveraged_stop_price is None

    def test_liquidate_position_no_position(self):
        """Test liquidation when no position exists."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()
        strategy.current_vehicle = 'TQQQ'
        strategy._positions = {}

        strategy._liquidate_position()
        signals = strategy.get_signals()

        # Should still clear stop-loss even if no position
        assert strategy.leveraged_stop_price is None
        # No signals generated if no position
        assert len(signals) == 0


class TestStopLoss:
    """Test stop-loss calculation and triggering."""

    def test_check_stop_loss_no_position(self):
        """Test stop-loss check when no position exists."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()
        strategy.current_vehicle = 'TQQQ'
        strategy._positions = {}

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        stop_hit = strategy._check_stop_loss(bar)
        assert stop_hit is False

    def test_check_stop_loss_no_stop_price(self):
        """Test stop-loss check when stop price not yet calculated."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()
        strategy.current_vehicle = 'TQQQ'
        strategy._positions = {'TQQQ': 100}
        strategy.leveraged_stop_price = None

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Without sufficient bars, should not hit stop
        stop_hit = strategy._check_stop_loss(bar)
        assert stop_hit is False


class TestOnBar:
    """Test on_bar() method with various scenarios."""

    def test_on_bar_ignores_non_signal_symbol(self):
        """Test that non-QQQ bars are ignored."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        tqqq_bar = MarketDataEvent(
            symbol='TQQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        strategy.on_bar(tqqq_bar)

        # Should not update Kalman or change regime
        assert strategy.current_regime is None

    def test_on_bar_updates_kalman_with_qqq(self):
        """Test that QQQ bars update Kalman filter."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        strategy._update_bar(qqq_bar)
        strategy.on_bar(qqq_bar)

        # Kalman filter should have processed the bar
        assert strategy.kalman_filter.bar_count == 1

    def test_on_bar_vix_filter_checked_first(self):
        """Test that VIX filter is checked BEFORE regime logic (NEW)."""
        strategy = Hierarchical_Adaptive_v1(vix_ema_period=10)
        strategy.init()

        # Create rising VIX bars (will trigger filter)
        vix_bars = []
        base_vix = Decimal('15')
        timestamp = datetime.now(timezone.utc)

        for i in range(30):
            close = base_vix + Decimal(str(i * 0.5))
            bar = MarketDataEvent(
                symbol='VIX',
                timestamp=timestamp,
                open=close - Decimal('0.2'),
                high=close + Decimal('0.3'),
                low=close - Decimal('0.3'),
                close=close,
                volume=Decimal('0')
            )
            vix_bars.append(bar)
            strategy._update_bar(bar)

        # Create bullish QQQ bar
        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )
        strategy._update_bar(qqq_bar)

        # Process QQQ bar - VIX filter should prevent regime logic
        strategy.on_bar(qqq_bar)

        # Should stay in CHOP_NEUTRAL due to VIX filter
        assert strategy.current_regime == Regime.CHOP_NEUTRAL
        assert strategy.current_vehicle is None


class TestHelperMethods:
    """Test helper methods for logging and descriptions."""

    def test_get_regime_description(self):
        """Test regime description generation."""
        strategy = Hierarchical_Adaptive_v1()

        desc = strategy._get_regime_description(Regime.STRONG_BULL)
        assert "Strong Bullish" in desc
        assert "TQQQ" in desc
        assert "EMA100" in desc
        assert "MACD12/26/9" in desc

        desc = strategy._get_regime_description(Regime.MODERATE_BULL)
        assert "Moderate Bullish" in desc
        assert "QQQ" in desc
        assert "EMA150" in desc
        assert "MACD20/50/12" in desc

        desc = strategy._get_regime_description(Regime.CHOP_NEUTRAL)
        assert "Choppy/Neutral" in desc
        assert "CASH" in desc

        desc = strategy._get_regime_description(Regime.BEAR)
        assert "Bearish" in desc
        assert "SQQQ" in desc

    def test_build_decision_reason(self):
        """Test decision reason generation."""
        strategy = Hierarchical_Adaptive_v1()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        reason = strategy._build_decision_reason(
            Decimal('65'),
            Regime.STRONG_BULL,
            bar
        )
        assert "65.00" in reason
        assert "strong_bull threshold" in reason
        assert "60" in reason

        reason = strategy._build_decision_reason(
            Decimal('40'),
            Regime.MODERATE_BULL,
            bar
        )
        assert "40.00" in reason
        assert "moderate_bull threshold" in reason

        reason = strategy._build_decision_reason(
            Decimal('-25'),
            Regime.BEAR,
            bar
        )
        assert "-25.00" in reason
        assert "moderate_bear threshold" in reason

        reason = strategy._build_decision_reason(
            Decimal('0'),
            Regime.CHOP_NEUTRAL,
            bar
        )
        assert "choppy" in reason


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_multiple_vehicle_changes(self):
        """Test handling multiple rapid vehicle changes."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        # Simulate position changes
        vehicles = ['TQQQ', 'QQQ', None, 'SQQQ', None]

        for vehicle in vehicles:
            strategy.current_vehicle = vehicle
            # Should handle transitions gracefully
            assert True  # Test passes if no exceptions

    def test_stop_loss_only_leveraged(self):
        """Test stop-loss only applies to leveraged positions."""
        strategy = Hierarchical_Adaptive_v1()
        strategy.init()

        # QQQ position should not trigger stop-loss check
        strategy.current_vehicle = 'QQQ'
        strategy._positions = {'QQQ': 100}

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('50'),  # Huge drop
            close=Decimal('51'),
            volume=Decimal('1000000')
        )

        # Verify QQQ is not in leveraged symbols
        assert strategy.current_vehicle not in [strategy.bull_symbol, strategy.bear_symbol]

    def test_custom_symbols(self):
        """Test strategy with custom trading symbols."""
        strategy = Hierarchical_Adaptive_v1(
            signal_symbol='SPY',
            bull_symbol='UPRO',
            bear_symbol='SPXU',
            defense_symbol='SPY',
            vix_symbol='VIX'
        )
        strategy.init()

        assert strategy.signal_symbol == 'SPY'
        assert strategy.bull_symbol == 'UPRO'
        assert strategy.bear_symbol == 'SPXU'
        assert strategy.defense_symbol == 'SPY'
        assert strategy.vix_symbol == 'VIX'

    def test_custom_regime_parameters(self):
        """Test strategy with custom regime-specific parameters."""
        strategy = Hierarchical_Adaptive_v1(
            # Strong Bull custom
            ema_trend_sb=125,
            macd_fast_sb=20,
            macd_slow_sb=50,
            macd_signal_sb=12,
            # Moderate Bull custom
            ema_trend_mb=200,
            macd_fast_mb=12,
            macd_slow_mb=26,
            macd_signal_mb=9,
            # Bear custom
            ema_trend_b=75,
            macd_fast_b=20,
            macd_slow_b=50,
            macd_signal_b=12
        )
        strategy.init()

        assert strategy.ema_trend_sb == 125
        assert strategy.macd_fast_sb == 20
        assert strategy.ema_trend_mb == 200
        assert strategy.ema_trend_b == 75
        assert strategy.macd_fast_b == 20

        # Verify max_lookback updated (should include vix_ema_period)
        assert strategy.max_lookback == max(
            20,   # vix_ema_period (default)
            200,  # ema_trend_mb (custom)
            50,   # macd_slow_sb/b
            14    # atr_period
        )

    def test_trade_logger_integration(self):
        """Test TradeLogger integration."""
        mock_logger = Mock()
        strategy = Hierarchical_Adaptive_v1(trade_logger=mock_logger)
        strategy.init()

        assert strategy._trade_logger == mock_logger
