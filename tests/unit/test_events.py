"""
Unit tests for core event classes.

Demonstrates testing patterns for the Jutsu Labs backtesting engine:
- Event validation and data integrity
- Decimal precision for financial data
- Property calculations
- Error handling
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from jutsu_engine.core.events import (
    MarketDataEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
)


class TestMarketDataEvent:
    """Test MarketDataEvent validation and behavior."""

    def test_valid_market_data_event(self):
        """Test creating a valid market data event."""
        event = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.50'),
            low=Decimal('149.50'),
            close=Decimal('151.00'),
            volume=1000000,
            timeframe='1D',
        )

        assert event.symbol == 'AAPL'
        assert event.open == Decimal('150.00')
        assert event.high == Decimal('152.50')
        assert event.low == Decimal('149.50')
        assert event.close == Decimal('151.00')
        assert event.volume == 1000000
        assert event.timeframe == '1D'

    def test_invalid_ohlc_relationships_high_too_low(self):
        """Test validation fails when high < open."""
        with pytest.raises(ValueError, match="Invalid OHLC:"):
            MarketDataEvent(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                open=Decimal('150.00'),
                high=Decimal('145.00'),  # High less than open - invalid
                low=Decimal('149.50'),
                close=Decimal('151.00'),
                volume=1000000,
            )

    def test_invalid_ohlc_relationships_low_too_high(self):
        """Test validation fails when low > close."""
        with pytest.raises(ValueError, match="Invalid OHLC:"):
            MarketDataEvent(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                open=Decimal('150.00'),
                high=Decimal('152.50'),
                low=Decimal('152.00'),  # Low greater than close - invalid
                close=Decimal('151.00'),
                volume=1000000,
            )

    def test_negative_volume(self):
        """Test that negative volume raises ValueError."""
        with pytest.raises(ValueError, match="Volume cannot be negative"):
            MarketDataEvent(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                open=Decimal('150.00'),
                high=Decimal('152.50'),
                low=Decimal('149.50'),
                close=Decimal('151.00'),
                volume=-1000,  # Negative volume - invalid
            )

    def test_default_timeframe(self):
        """Test that default timeframe is '1D'."""
        event = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.50'),
            low=Decimal('149.50'),
            close=Decimal('151.00'),
            volume=1000000,
        )

        assert event.timeframe == '1D'


class TestSignalEvent:
    """Test SignalEvent creation and properties."""

    def test_buy_signal(self):
        """Test creating a BUY signal."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            quantity=100,
            strategy_name='SMA_Crossover',
            price=Decimal('150.00'),
        )

        assert signal.symbol == 'AAPL'
        assert signal.signal_type == 'BUY'
        assert signal.quantity == 100
        assert signal.strategy_name == 'SMA_Crossover'
        assert signal.price == Decimal('150.00')

    def test_sell_signal(self):
        """Test creating a SELL signal."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='SELL',
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            quantity=100,
            strategy_name='RSI_Overbought',
        )

        assert signal.signal_type == 'SELL'
        assert signal.price is None  # Price optional for signals

    def test_default_strategy_name(self):
        """Test default strategy name is 'unknown'."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            quantity=100,
        )

        assert signal.strategy_name == 'unknown'


class TestOrderEvent:
    """Test OrderEvent creation and properties."""

    def test_market_order(self):
        """Test creating a market order."""
        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
        )

        assert order.order_type == 'MARKET'
        assert order.direction == 'BUY'
        assert order.quantity == 100
        assert order.price is None

    def test_limit_order(self):
        """Test creating a limit order with price."""
        order = OrderEvent(
            symbol='AAPL',
            order_type='LIMIT',
            direction='SELL',
            quantity=50,
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            price=Decimal('155.00'),
        )

        assert order.order_type == 'LIMIT'
        assert order.direction == 'SELL'
        assert order.price == Decimal('155.00')


class TestFillEvent:
    """Test FillEvent calculations and properties."""

    def test_fill_without_costs(self):
        """Test fill event with no commission or slippage."""
        fill = FillEvent(
            symbol='AAPL',
            direction='BUY',
            quantity=100,
            fill_price=Decimal('150.00'),
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
        )

        assert fill.total_cost == Decimal('15000.00')  # 100 * 150.00

    def test_fill_with_commission(self):
        """Test fill event with commission."""
        fill = FillEvent(
            symbol='AAPL',
            direction='BUY',
            quantity=100,
            fill_price=Decimal('150.00'),
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            commission=Decimal('1.00'),  # $1 commission
        )

        assert fill.total_cost == Decimal('15001.00')  # 15000 + 1

    def test_fill_with_commission_and_slippage(self):
        """Test fill event with both commission and slippage."""
        fill = FillEvent(
            symbol='AAPL',
            direction='BUY',
            quantity=100,
            fill_price=Decimal('150.00'),
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            commission=Decimal('1.00'),
            slippage=Decimal('5.00'),  # $5 slippage
        )

        assert fill.total_cost == Decimal('15006.00')  # 15000 + 1 + 5

    def test_decimal_precision_in_calculations(self):
        """Test that Decimal precision is maintained in cost calculations."""
        fill = FillEvent(
            symbol='AAPL',
            direction='BUY',
            quantity=33,
            fill_price=Decimal('150.33'),
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            commission=Decimal('0.01'),
            slippage=Decimal('0.02'),
        )

        # 33 * 150.33 = 4960.89
        # + 0.01 + 0.02 = 4960.92
        assert fill.total_cost == Decimal('4960.92')

    def test_sell_fill_event(self):
        """Test sell fill event (direction='SELL')."""
        fill = FillEvent(
            symbol='AAPL',
            direction='SELL',
            quantity=50,
            fill_price=Decimal('155.50'),
            timestamp=datetime(2024, 1, 15, 15, 30, 0, tzinfo=timezone.utc),
            commission=Decimal('0.50'),
        )

        assert fill.direction == 'SELL'
        assert fill.total_cost == Decimal('7775.50')  # (50 * 155.50) + 0.50


# Fixtures for reusable test data
@pytest.fixture
def sample_market_data():
    """Fixture providing sample market data event."""
    return MarketDataEvent(
        symbol='AAPL',
        timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
        open=Decimal('150.00'),
        high=Decimal('152.50'),
        low=Decimal('149.50'),
        close=Decimal('151.00'),
        volume=1000000,
        timeframe='1D',
    )


@pytest.fixture
def sample_buy_signal():
    """Fixture providing sample BUY signal."""
    return SignalEvent(
        symbol='AAPL',
        signal_type='BUY',
        timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
        quantity=100,
        strategy_name='SMA_Crossover',
        price=Decimal('150.00'),
    )


@pytest.fixture
def sample_fill():
    """Fixture providing sample fill event."""
    return FillEvent(
        symbol='AAPL',
        direction='BUY',
        quantity=100,
        fill_price=Decimal('150.00'),
        timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
        commission=Decimal('1.00'),
    )


class TestFixtureUsage:
    """Demonstrate using fixtures in tests."""

    def test_using_market_data_fixture(self, sample_market_data):
        """Example test using sample_market_data fixture."""
        assert sample_market_data.symbol == 'AAPL'
        assert sample_market_data.close == Decimal('151.00')

    def test_using_signal_fixture(self, sample_buy_signal):
        """Example test using sample_buy_signal fixture."""
        assert sample_buy_signal.signal_type == 'BUY'
        assert sample_buy_signal.quantity == 100

    def test_using_fill_fixture(self, sample_fill):
        """Example test using sample_fill fixture."""
        assert sample_fill.total_cost == Decimal('15001.00')
