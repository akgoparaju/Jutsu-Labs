"""
Reusable test fixtures and sample data for Vibe Engine tests.

Provides common test data objects that can be imported and used across
different test modules. Follows the Arrange-Act-Assert pattern.

Usage:
    from tests.fixtures.sample_data import SAMPLE_BARS, create_sample_strategy

    def test_strategy_with_sample_data():
        strategy = create_sample_strategy()
        for bar in SAMPLE_BARS:
            strategy.on_bar(bar)
"""
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import List

from jutsu_engine.core.events import (
    MarketDataEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
)


# ============================================================================
# Sample Market Data
# ============================================================================

def create_sample_bar(
    symbol: str = 'AAPL',
    timestamp: datetime = None,
    open: Decimal = Decimal('150.00'),
    high: Decimal = Decimal('152.00'),
    low: Decimal = Decimal('149.00'),
    close: Decimal = Decimal('151.00'),
    volume: int = 1000000,
    timeframe: str = '1D',
) -> MarketDataEvent:
    """
    Create a sample market data bar with sensible defaults.

    Args:
        symbol: Stock ticker symbol
        timestamp: Bar timestamp (defaults to 2024-01-15 09:30 UTC)
        open: Opening price
        high: High price
        low: Low price
        close: Closing price
        volume: Trading volume
        timeframe: Bar timeframe

    Returns:
        MarketDataEvent instance
    """
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

    return MarketDataEvent(
        symbol=symbol,
        timestamp=timestamp,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        timeframe=timeframe,
    )


def create_sample_bars(
    symbol: str = 'AAPL',
    num_bars: int = 20,
    start_date: datetime = None,
    start_price: Decimal = Decimal('150.00'),
    price_increment: Decimal = Decimal('0.50'),
) -> List[MarketDataEvent]:
    """
    Create a sequence of sample market data bars.

    Useful for testing strategies that need historical data.

    Args:
        symbol: Stock ticker symbol
        num_bars: Number of bars to create
        start_date: Starting date (defaults to 2024-01-01)
        start_price: Starting close price
        price_increment: Amount to increment close price each bar

    Returns:
        List of MarketDataEvent instances
    """
    if start_date is None:
        start_date = datetime(2024, 1, 1, 9, 30, 0, tzinfo=timezone.utc)

    bars = []
    current_price = start_price

    for i in range(num_bars):
        timestamp = start_date + timedelta(days=i)

        # Create realistic OHLC from close price
        open_price = current_price
        high_price = current_price + Decimal('2.00')
        low_price = current_price - Decimal('1.00')
        close_price = current_price + price_increment

        bar = MarketDataEvent(
            symbol=symbol,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=1000000 + (i * 10000),  # Increasing volume
            timeframe='1D',
        )

        bars.append(bar)
        current_price = close_price

    return bars


# Pre-created sample bar sequences for common test scenarios
SAMPLE_BARS = create_sample_bars(num_bars=20)

UPTREND_BARS = create_sample_bars(
    num_bars=10, start_price=Decimal('100.00'), price_increment=Decimal('1.00')
)

DOWNTREND_BARS = create_sample_bars(
    num_bars=10, start_price=Decimal('150.00'), price_increment=Decimal('-1.00')
)


# ============================================================================
# Sample Signals
# ============================================================================

def create_sample_signal(
    symbol: str = 'AAPL',
    signal_type: str = 'BUY',
    quantity: int = 100,
    timestamp: datetime = None,
    strategy_name: str = 'TestStrategy',
    price: Decimal = None,
) -> SignalEvent:
    """
    Create a sample trading signal.

    Args:
        symbol: Stock ticker symbol
        signal_type: 'BUY', 'SELL', or 'HOLD'
        quantity: Number of shares
        timestamp: Signal timestamp
        strategy_name: Name of strategy generating signal
        price: Optional price for signal

    Returns:
        SignalEvent instance
    """
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

    return SignalEvent(
        symbol=symbol,
        signal_type=signal_type,
        timestamp=timestamp,
        quantity=quantity,
        strategy_name=strategy_name,
        price=price,
    )


# ============================================================================
# Sample Orders
# ============================================================================

def create_sample_order(
    symbol: str = 'AAPL',
    order_type: str = 'MARKET',
    direction: str = 'BUY',
    quantity: int = 100,
    timestamp: datetime = None,
    price: Decimal = None,
) -> OrderEvent:
    """
    Create a sample order event.

    Args:
        symbol: Stock ticker symbol
        order_type: 'MARKET' or 'LIMIT'
        direction: 'BUY' or 'SELL'
        quantity: Number of shares
        timestamp: Order timestamp
        price: Optional limit price

    Returns:
        OrderEvent instance
    """
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

    return OrderEvent(
        symbol=symbol,
        order_type=order_type,
        direction=direction,
        quantity=quantity,
        timestamp=timestamp,
        price=price,
    )


# ============================================================================
# Sample Fills
# ============================================================================

def create_sample_fill(
    symbol: str = 'AAPL',
    direction: str = 'BUY',
    quantity: int = 100,
    fill_price: Decimal = Decimal('150.00'),
    timestamp: datetime = None,
    commission: Decimal = Decimal('1.00'),
    slippage: Decimal = Decimal('0.00'),
) -> FillEvent:
    """
    Create a sample fill event.

    Args:
        symbol: Stock ticker symbol
        direction: 'BUY' or 'SELL'
        quantity: Number of shares filled
        fill_price: Execution price
        timestamp: Fill timestamp
        commission: Commission cost
        slippage: Slippage cost

    Returns:
        FillEvent instance
    """
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

    return FillEvent(
        symbol=symbol,
        direction=direction,
        quantity=quantity,
        fill_price=fill_price,
        timestamp=timestamp,
        commission=commission,
        slippage=slippage,
    )


# ============================================================================
# Sample Backtest Configurations
# ============================================================================

SAMPLE_BACKTEST_CONFIG = {
    'symbol': 'AAPL',
    'timeframe': '1D',
    'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
    'end_date': datetime(2024, 12, 31, tzinfo=timezone.utc),
    'initial_capital': Decimal('100000'),
    'commission_per_share': Decimal('0.01'),
}

MINIMAL_BACKTEST_CONFIG = {
    'symbol': 'SPY',
    'timeframe': '1D',
    'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
    'end_date': datetime(2024, 1, 31, tzinfo=timezone.utc),
    'initial_capital': Decimal('10000'),
    'commission_per_share': Decimal('0.00'),
}


# ============================================================================
# Helper Functions
# ============================================================================

def assert_valid_ohlc(bar: MarketDataEvent) -> None:
    """
    Assert that a bar has valid OHLC relationships.

    Raises:
        AssertionError: If OHLC relationships are invalid
    """
    assert bar.low <= bar.open <= bar.high, "Open must be between low and high"
    assert bar.low <= bar.close <= bar.high, "Close must be between low and high"
    assert bar.high >= bar.low, "High must be >= low"
    assert bar.volume >= 0, "Volume must be non-negative"


def assert_events_chronological(events: List) -> None:
    """
    Assert that events are in chronological order.

    Args:
        events: List of event objects with timestamp attribute

    Raises:
        AssertionError: If events are not chronological
    """
    for i in range(1, len(events)):
        assert events[i].timestamp >= events[i - 1].timestamp, (
            f"Events not chronological: {events[i-1].timestamp} > {events[i].timestamp}"
        )


def calculate_sma(prices: List[Decimal], period: int) -> Decimal:
    """
    Calculate Simple Moving Average for testing.

    Args:
        prices: List of prices
        period: SMA period

    Returns:
        SMA value as Decimal
    """
    if len(prices) < period:
        raise ValueError(f"Need at least {period} prices for SMA calculation")

    recent_prices = prices[-period:]
    return sum(recent_prices) / Decimal(period)
