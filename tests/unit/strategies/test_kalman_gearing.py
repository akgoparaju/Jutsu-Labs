"""
Unit tests for Kalman Gearing v1.0 strategy.

Tests cover:
- Initialization and parameter validation
- Regime determination logic (all 4 regimes)
- Position sizing (leveraged & unleveraged)
- Stop-loss calculation and triggering
- Regime change execution
- Edge cases and error handling

Coverage Target: >85%
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from jutsu_engine.strategies.kalman_gearing import KalmanGearing, Regime
from jutsu_engine.core.events import MarketDataEvent


class TestInitialization:
    """Test strategy initialization and parameter validation."""

    def test_initialization_default_parameters(self):
        """Test initialization with default parameters."""
        strategy = KalmanGearing()

        assert strategy.name == "KalmanGearing"
        assert strategy.process_noise_1 == 0.01
        assert strategy.measurement_noise == 500.0
        assert strategy.thresh_strong_bull == Decimal('70')
        assert strategy.thresh_moderate_bull == Decimal('20')
        assert strategy.thresh_strong_bear == Decimal('-70')
        assert strategy.atr_stop_multiplier == Decimal('3.0')
        assert strategy.risk_leveraged == Decimal('0.025')
        assert strategy.allocation_unleveraged == Decimal('0.80')
        assert strategy.signal_symbol == 'QQQ'
        assert strategy.bull_3x_symbol == 'TQQQ'
        assert strategy.bear_3x_symbol == 'SQQQ'

    def test_initialization_custom_parameters(self):
        """Test initialization with custom parameters."""
        strategy = KalmanGearing(
            process_noise_1=0.001,
            measurement_noise=1000.0,
            thresh_strong_bull=Decimal('80'),
            thresh_moderate_bull=Decimal('30'),
            thresh_strong_bear=Decimal('-60'),
            risk_leveraged=Decimal('0.02'),
            name="CustomKalman"
        )

        assert strategy.name == "CustomKalman"
        assert strategy.process_noise_1 == 0.001
        assert strategy.measurement_noise == 1000.0
        assert strategy.thresh_strong_bull == Decimal('80')
        assert strategy.thresh_moderate_bull == Decimal('30')
        assert strategy.thresh_strong_bear == Decimal('-60')
        assert strategy.risk_leveraged == Decimal('0.02')

    def test_threshold_validation_failure(self):
        """Test that invalid threshold ordering raises ValueError."""
        # Strong bear must be negative
        with pytest.raises(ValueError, match="Thresholds must satisfy"):
            KalmanGearing(thresh_strong_bear=Decimal('10'))

        # Moderate bull must be less than strong bull
        with pytest.raises(ValueError, match="Thresholds must satisfy"):
            KalmanGearing(
                thresh_strong_bull=Decimal('50'),
                thresh_moderate_bull=Decimal('60')
            )

        # Strong bear must be less than zero
        with pytest.raises(ValueError, match="Thresholds must satisfy"):
            KalmanGearing(
                thresh_strong_bear=Decimal('0')
            )

    def test_init_method(self):
        """Test init() method sets up Kalman filter and state."""
        strategy = KalmanGearing()
        strategy.init()

        assert strategy.kalman_filter is not None
        assert strategy.current_regime is None
        assert strategy.current_vehicle is None
        assert strategy.leveraged_stop_price is None
        assert len(strategy.vehicles) == 4
        assert strategy.vehicles[Regime.STRONG_BULL] == 'TQQQ'
        assert strategy.vehicles[Regime.MODERATE_BULL] == 'QQQ'
        assert strategy.vehicles[Regime.CHOP_NEUTRAL] is None
        assert strategy.vehicles[Regime.STRONG_BEAR] == 'SQQQ'


class TestRegimeDetermination:
    """Test regime determination from trend strength."""

    def test_strong_bull_regime(self):
        """Test strong bull regime detection."""
        strategy = KalmanGearing()

        regime = strategy._determine_regime(Decimal('75'))
        assert regime == Regime.STRONG_BULL

        regime = strategy._determine_regime(Decimal('70.01'))
        assert regime == Regime.STRONG_BULL

        regime = strategy._determine_regime(Decimal('100'))
        assert regime == Regime.STRONG_BULL

    def test_moderate_bull_regime(self):
        """Test moderate bull regime detection."""
        strategy = KalmanGearing()

        regime = strategy._determine_regime(Decimal('50'))
        assert regime == Regime.MODERATE_BULL

        regime = strategy._determine_regime(Decimal('20.01'))
        assert regime == Regime.MODERATE_BULL

        regime = strategy._determine_regime(Decimal('70'))
        assert regime == Regime.MODERATE_BULL

    def test_chop_neutral_regime(self):
        """Test chop/neutral regime detection."""
        strategy = KalmanGearing()

        regime = strategy._determine_regime(Decimal('0'))
        assert regime == Regime.CHOP_NEUTRAL

        regime = strategy._determine_regime(Decimal('20'))
        assert regime == Regime.CHOP_NEUTRAL

        regime = strategy._determine_regime(Decimal('-70'))
        assert regime == Regime.CHOP_NEUTRAL

        regime = strategy._determine_regime(Decimal('10'))
        assert regime == Regime.CHOP_NEUTRAL

    def test_strong_bear_regime(self):
        """Test strong bear regime detection."""
        strategy = KalmanGearing()

        regime = strategy._determine_regime(Decimal('-75'))
        assert regime == Regime.STRONG_BEAR

        regime = strategy._determine_regime(Decimal('-70.01'))
        assert regime == Regime.STRONG_BEAR

        regime = strategy._determine_regime(Decimal('-100'))
        assert regime == Regime.STRONG_BEAR

    def test_custom_thresholds(self):
        """Test regime determination with custom thresholds."""
        strategy = KalmanGearing(
            thresh_strong_bull=Decimal('80'),
            thresh_moderate_bull=Decimal('30'),
            thresh_strong_bear=Decimal('-60')
        )

        assert strategy._determine_regime(Decimal('85')) == Regime.STRONG_BULL
        assert strategy._determine_regime(Decimal('50')) == Regime.MODERATE_BULL
        assert strategy._determine_regime(Decimal('20')) == Regime.CHOP_NEUTRAL
        assert strategy._determine_regime(Decimal('-65')) == Regime.STRONG_BEAR


class TestPositionSizing:
    """Test position sizing for leveraged and unleveraged positions."""

    def test_enter_leveraged_long_insufficient_data(self):
        """Test leveraged long entry with insufficient ATR data."""
        strategy = KalmanGearing()
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
        strategy = KalmanGearing()
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
        strategy = KalmanGearing()
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

    def test_liquidate_position_with_position(self):
        """Test position liquidation when position exists."""
        strategy = KalmanGearing()
        strategy.init()
        strategy.current_vehicle = 'TQQQ'

        # Mock position
        strategy._positions = {'TQQQ': 100}

        strategy._liquidate_position()
        signals = strategy.get_signals()

        assert len(signals) == 1
        assert signals[0].symbol == 'TQQQ'
        assert signals[0].signal_type == 'SELL'
        assert signals[0].portfolio_percent == Decimal('1.0')
        assert strategy.leveraged_stop_price is None

    def test_liquidate_position_no_position(self):
        """Test liquidation when no position exists."""
        strategy = KalmanGearing()
        strategy.init()
        strategy.current_vehicle = 'TQQQ'
        strategy._positions = {}

        strategy._liquidate_position()
        signals = strategy.get_signals()

        # Should still clear stop-loss even if no position
        assert strategy.leveraged_stop_price is None
        # No signals generated if no position
        assert len(signals) == 0


class TestRegimeChangeExecution:
    """Test regime change execution logic."""

    def test_execute_regime_change_to_cash(self):
        """Test transition to CASH regime."""
        strategy = KalmanGearing()
        strategy.init()
        strategy.current_regime = Regime.STRONG_BULL
        strategy.current_vehicle = 'TQQQ'
        strategy._positions = {'TQQQ': 100}

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        strategy._execute_regime_change(Regime.CHOP_NEUTRAL, bar)

        assert strategy.current_regime == Regime.CHOP_NEUTRAL
        assert strategy.current_vehicle is None

        # Should have liquidation signal
        signals = strategy.get_signals()
        assert len(signals) == 1
        assert signals[0].signal_type == 'SELL'

    def test_execute_regime_change_to_unleveraged(self):
        """Test transition to QQQ regime."""
        strategy = KalmanGearing()
        strategy.init()
        strategy.current_regime = None
        strategy.current_vehicle = None

        bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100.50'),
            volume=Decimal('1000000')
        )

        strategy._execute_regime_change(Regime.MODERATE_BULL, bar)

        assert strategy.current_regime == Regime.MODERATE_BULL
        assert strategy.current_vehicle == 'QQQ'

        signals = strategy.get_signals()
        assert len(signals) == 1
        assert signals[0].symbol == 'QQQ'
        assert signals[0].signal_type == 'BUY'


class TestStopLoss:
    """Test stop-loss calculation and triggering."""

    def test_check_stop_loss_no_position(self):
        """Test stop-loss check when no position exists."""
        strategy = KalmanGearing()
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
        strategy = KalmanGearing()
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
        strategy = KalmanGearing()
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
        strategy = KalmanGearing()
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


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_multiple_regime_changes(self):
        """Test handling multiple rapid regime changes."""
        strategy = KalmanGearing()
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

        # Simulate regime changes
        regimes = [
            Regime.STRONG_BULL,
            Regime.MODERATE_BULL,
            Regime.CHOP_NEUTRAL,
            Regime.STRONG_BEAR,
            Regime.CHOP_NEUTRAL
        ]

        for regime in regimes:
            strategy._execute_regime_change(regime, bar)
            assert strategy.current_regime == regime

    def test_stop_loss_with_leveraged_position(self):
        """Test stop-loss only applies to leveraged positions."""
        strategy = KalmanGearing()
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

        # Should not process stop-loss for QQQ
        # (In on_bar, the check only runs for leveraged positions)
        strategy.on_bar(bar)  # This won't enter the stop-loss check branch

        # Verify QQQ is not in leveraged symbols
        assert strategy.current_vehicle not in [strategy.bull_3x_symbol, strategy.bear_3x_symbol]

    def test_custom_symbols(self):
        """Test strategy with custom trading symbols."""
        strategy = KalmanGearing(
            signal_symbol='SPY',
            bull_3x_symbol='UPRO',
            bear_3x_symbol='SPXU',
            unleveraged_symbol='SPY'
        )
        strategy.init()

        assert strategy.signal_symbol == 'SPY'
        assert strategy.vehicles[Regime.STRONG_BULL] == 'UPRO'
        assert strategy.vehicles[Regime.STRONG_BEAR] == 'SPXU'
        assert strategy.vehicles[Regime.MODERATE_BULL] == 'SPY'
