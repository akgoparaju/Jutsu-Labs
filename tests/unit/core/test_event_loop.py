"""
Unit tests for EventLoop module.

Tests sequential bar processing, portfolio coordination, and snapshot recording.
"""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterator

from jutsu_engine.core.event_loop import EventLoop
from jutsu_engine.core.events import MarketDataEvent, SignalEvent
from jutsu_engine.data.handlers.base import DataHandler
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.portfolio.simulator import PortfolioSimulator


# === Test Fixtures ===

class MockDataHandler(DataHandler):
    """Mock data handler for testing."""

    def __init__(self, bars):
        self.bars = bars
        self._index = 0

    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        """Yield bars sequentially."""
        for bar in self.bars:
            yield bar

    def get_latest_bar(self, symbol: str):
        """Get the most recent bar for a symbol."""
        for bar in reversed(self.bars):
            if bar.symbol == symbol:
                return bar
        return None

    def get_bars(self, symbol: str, start_date: datetime, end_date: datetime, limit=None):
        """Get bars for a date range."""
        filtered = [
            bar for bar in self.bars
            if bar.symbol == symbol and start_date <= bar.timestamp <= end_date
        ]
        if limit:
            filtered = filtered[:limit]
        return filtered

    def get_bars_lookback(self, symbol: str, lookback: int):
        """Get last N bars for a symbol."""
        symbol_bars = [bar for bar in self.bars if bar.symbol == symbol]
        return symbol_bars[-lookback:] if len(symbol_bars) >= lookback else symbol_bars


class MockStrategy(Strategy):
    """Mock strategy for testing."""

    def __init__(self):
        super().__init__()
        self.bars_processed = []

    def init(self):
        """Initialize strategy."""
        pass

    def on_bar(self, bar: MarketDataEvent):
        """Process bar and track it."""
        self.bars_processed.append(bar)


@pytest.fixture
def sample_bars_single_date():
    """
    Sample bars for testing: 3 symbols on same date.

    Simulates multi-symbol backtest (QQQ, TQQQ, VIX) on same date.
    Used to test that only ONE snapshot is recorded per unique date.
    """
    base_date = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    return [
        MarketDataEvent(
            symbol='QQQ',
            timestamp=base_date,
            open=Decimal('400.00'),
            high=Decimal('402.00'),
            low=Decimal('399.00'),
            close=Decimal('401.00'),
            volume=1000000
        ),
        MarketDataEvent(
            symbol='TQQQ',
            timestamp=base_date,
            open=Decimal('50.00'),
            high=Decimal('51.00'),
            low=Decimal('49.50'),
            close=Decimal('50.50'),
            volume=2000000
        ),
        MarketDataEvent(
            symbol='VIX',
            timestamp=base_date,
            open=Decimal('15.00'),
            high=Decimal('15.50'),
            low=Decimal('14.80'),
            close=Decimal('15.20'),
            volume=500000
        ),
    ]


@pytest.fixture
def sample_bars_multi_date():
    """
    Sample bars for testing: 2 dates with 2 symbols each.

    Date 1: QQQ, TQQQ
    Date 2: QQQ, TQQQ
    """
    date1 = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    date2 = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)

    return [
        # Date 1 - Symbol 1
        MarketDataEvent(
            symbol='QQQ',
            timestamp=date1,
            open=Decimal('400.00'),
            high=Decimal('402.00'),
            low=Decimal('399.00'),
            close=Decimal('401.00'),
            volume=1000000
        ),
        # Date 1 - Symbol 2
        MarketDataEvent(
            symbol='TQQQ',
            timestamp=date1,
            open=Decimal('50.00'),
            high=Decimal('51.00'),
            low=Decimal('49.50'),
            close=Decimal('50.50'),
            volume=2000000
        ),
        # Date 2 - Symbol 1
        MarketDataEvent(
            symbol='QQQ',
            timestamp=date2,
            open=Decimal('402.00'),
            high=Decimal('404.00'),
            low=Decimal('401.00'),
            close=Decimal('403.00'),
            volume=1100000
        ),
        # Date 2 - Symbol 2
        MarketDataEvent(
            symbol='TQQQ',
            timestamp=date2,
            open=Decimal('51.00'),
            high=Decimal('52.00'),
            low=Decimal('50.50'),
            close=Decimal('51.50'),
            volume=2100000
        ),
    ]


# === Tests ===

def test_eventloop_initialization():
    """Test EventLoop initializes correctly."""
    data_handler = MockDataHandler([])
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio
    )

    assert event_loop.data_handler is data_handler
    assert event_loop.strategy is strategy
    assert event_loop.portfolio is portfolio
    assert event_loop._last_snapshot_date is None  # Initial state
    assert len(event_loop.all_bars) == 0
    assert len(event_loop.all_signals) == 0


def test_eventloop_processes_bars_sequentially(sample_bars_multi_date):
    """Test EventLoop processes bars in correct order."""
    data_handler = MockDataHandler(sample_bars_multi_date)
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio
    )

    event_loop.run()

    # Verify all bars processed
    assert len(event_loop.all_bars) == 4
    assert len(strategy.bars_processed) == 4

    # Verify sequential order
    for i, bar in enumerate(event_loop.all_bars):
        assert bar == sample_bars_multi_date[i]


def test_eventloop_one_snapshot_per_date_single_date(sample_bars_single_date):
    """
    Test EventLoop records exactly ONE snapshot per unique date.

    Bug Fix Verification:
    - Before fix: 3 snapshots (one per symbol)
    - After fix: 1 snapshot (one per date)

    Scenario: 3 symbols (QQQ, TQQQ, VIX) on SAME date
    Expected: Only 1 snapshot recorded (not 3)
    """
    data_handler = MockDataHandler(sample_bars_single_date)
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio
    )

    event_loop.run()

    # Verify only ONE snapshot recorded for the single date
    snapshots = portfolio.get_daily_snapshots()
    assert len(snapshots) == 1, (
        f"Expected 1 snapshot per date, got {len(snapshots)}. "
        f"Bug fix failed: duplicate snapshots still being recorded."
    )

    # Verify snapshot has correct date
    snapshot = snapshots[0]
    expected_date = sample_bars_single_date[0].timestamp.date()
    assert snapshot['timestamp'].date() == expected_date


def test_eventloop_one_snapshot_per_date_multi_date(sample_bars_multi_date):
    """
    Test EventLoop records exactly ONE snapshot per unique date across multiple dates.

    Scenario: 2 dates with 2 symbols each (4 bars total)
    Expected: 2 snapshots (one per date, not 4)
    """
    data_handler = MockDataHandler(sample_bars_multi_date)
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio
    )

    event_loop.run()

    # Verify exactly TWO snapshots (one per unique date)
    snapshots = portfolio.get_daily_snapshots()
    assert len(snapshots) == 2, (
        f"Expected 2 snapshots (one per date), got {len(snapshots)}. "
        f"Snapshots: {[(s['timestamp'].date(), s) for s in snapshots]}"
    )

    # Verify snapshot dates are unique and correct
    snapshot_dates = [s['timestamp'].date() for s in snapshots]
    expected_dates = [
        sample_bars_multi_date[0].timestamp.date(),  # 2024-01-01
        sample_bars_multi_date[2].timestamp.date(),  # 2024-01-02
    ]

    assert snapshot_dates == expected_dates, (
        f"Snapshot dates mismatch. Expected: {expected_dates}, Got: {snapshot_dates}"
    )


def test_eventloop_snapshot_timing():
    """
    Test snapshot is recorded on FIRST bar of each date.

    Verifies that when date changes, snapshot is recorded immediately
    on the first bar of the new date (not the last bar of previous date).
    """
    date1 = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    date2 = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)

    bars = [
        MarketDataEvent(
            symbol='QQQ', timestamp=date1,
            open=Decimal('400'), high=Decimal('402'),
            low=Decimal('399'), close=Decimal('401'), volume=1000000
        ),
        MarketDataEvent(
            symbol='QQQ', timestamp=date2,
            open=Decimal('402'), high=Decimal('404'),
            low=Decimal('401'), close=Decimal('403'), volume=1100000
        ),
    ]

    data_handler = MockDataHandler(bars)
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio
    )

    event_loop.run()

    # Verify 2 snapshots (one per date)
    snapshots = portfolio.get_daily_snapshots()
    assert len(snapshots) == 2

    # Verify snapshot timestamps match bar timestamps
    assert snapshots[0]['timestamp'] == bars[0].timestamp
    assert snapshots[1]['timestamp'] == bars[1].timestamp


def test_eventloop_get_results():
    """Test get_results returns correct summary."""
    bars = [
        MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc),
            open=Decimal('400'), high=Decimal('402'),
            low=Decimal('399'), close=Decimal('401'), volume=1000000
        ),
    ]

    data_handler = MockDataHandler(bars)
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio
    )

    event_loop.run()

    results = event_loop.get_results()

    assert results['total_bars'] == 1
    assert results['final_value'] == Decimal('100000')
    assert results['total_return'] == Decimal('0')
    assert results['cash'] == Decimal('100000')


# === Warmup Phase Tests ===

def test_in_warmup_phase_no_warmup():
    """Test _in_warmup_phase returns False when warmup_end_date is None."""
    data_handler = MockDataHandler([])
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=None
    )

    # Any date should return False when warmup_end_date is None
    test_date = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    assert event_loop._in_warmup_phase(test_date) is False


def test_in_warmup_phase_before_end():
    """Test _in_warmup_phase returns True for dates before warmup_end_date."""
    data_handler = MockDataHandler([])
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    warmup_end = datetime(2024, 1, 10, 9, 30, tzinfo=timezone.utc)
    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=warmup_end
    )

    # Date before warmup_end should return True
    before_date = datetime(2024, 1, 5, 9, 30, tzinfo=timezone.utc)
    assert event_loop._in_warmup_phase(before_date) is True


def test_in_warmup_phase_after_end():
    """Test _in_warmup_phase returns False for dates on or after warmup_end_date."""
    data_handler = MockDataHandler([])
    strategy = MockStrategy()
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    warmup_end = datetime(2024, 1, 10, 9, 30, tzinfo=timezone.utc)
    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=warmup_end
    )

    # Date equal to warmup_end should return False (trading starts)
    assert event_loop._in_warmup_phase(warmup_end) is False

    # Date after warmup_end should return False
    after_date = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
    assert event_loop._in_warmup_phase(after_date) is False


class SignalGeneratingStrategy(Strategy):
    """Mock strategy that generates signals for testing."""

    def __init__(self, buy_dates=None):
        super().__init__()
        self.buy_dates = buy_dates or []
        self.bars_processed = []

    def init(self):
        pass

    def on_bar(self, bar: MarketDataEvent):
        """Generate BUY signal on specific dates."""
        self.bars_processed.append(bar)

        # Check if this bar's date matches a buy_date
        if bar.timestamp.date() in [d.date() for d in self.buy_dates]:
            self.buy(bar.symbol, portfolio_percent=Decimal('0.1'))


def test_warmup_signals_ignored():
    """Test that signals generated during warmup phase are NOT executed."""
    # Create bars spanning warmup and trading periods
    warmup_date = datetime(2024, 1, 5, 9, 30, tzinfo=timezone.utc)
    trading_date = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)

    bars = [
        MarketDataEvent(
            symbol='QQQ', timestamp=warmup_date,
            open=Decimal('400'), high=Decimal('402'),
            low=Decimal('399'), close=Decimal('401'), volume=1000000
        ),
        MarketDataEvent(
            symbol='QQQ', timestamp=trading_date,
            open=Decimal('405'), high=Decimal('407'),
            low=Decimal('404'), close=Decimal('406'), volume=1100000
        ),
    ]

    # Strategy generates BUY signal on warmup_date
    strategy = SignalGeneratingStrategy(buy_dates=[warmup_date])

    data_handler = MockDataHandler(bars)
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    warmup_end = datetime(2024, 1, 10, 9, 30, tzinfo=timezone.utc)
    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=warmup_end
    )

    event_loop.run()

    # Verify signal was generated but NOT executed
    assert len(event_loop.all_signals) == 1  # Signal collected
    assert len(event_loop.all_fills) == 0   # No fills (warmup)
    assert portfolio.cash == Decimal('100000')  # Cash unchanged
    assert len(portfolio.positions) == 0  # No positions


def test_warmup_trading_phase_signals_executed():
    """Test that signals generated after warmup_end_date ARE executed."""
    # Create bars spanning warmup and trading periods
    warmup_date = datetime(2024, 1, 5, 9, 30, tzinfo=timezone.utc)
    trading_date = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)

    bars = [
        MarketDataEvent(
            symbol='QQQ', timestamp=warmup_date,
            open=Decimal('400'), high=Decimal('402'),
            low=Decimal('399'), close=Decimal('401'), volume=1000000
        ),
        MarketDataEvent(
            symbol='QQQ', timestamp=trading_date,
            open=Decimal('405'), high=Decimal('407'),
            low=Decimal('404'), close=Decimal('406'), volume=1100000
        ),
    ]

    # Strategy generates BUY signal on trading_date
    strategy = SignalGeneratingStrategy(buy_dates=[trading_date])

    data_handler = MockDataHandler(bars)
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    warmup_end = datetime(2024, 1, 10, 9, 30, tzinfo=timezone.utc)
    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=warmup_end
    )

    event_loop.run()

    # Verify signal was generated AND executed
    assert len(event_loop.all_signals) == 1  # Signal collected
    assert len(event_loop.all_fills) == 1   # Fill executed
    assert portfolio.cash < Decimal('100000')  # Cash used
    assert 'QQQ' in portfolio.positions  # Position acquired


def test_warmup_no_warmup_backwards_compatible():
    """Test that warmup_end_date=None behaves like original (no warmup)."""
    date1 = datetime(2024, 1, 5, 9, 30, tzinfo=timezone.utc)

    bars = [
        MarketDataEvent(
            symbol='QQQ', timestamp=date1,
            open=Decimal('400'), high=Decimal('402'),
            low=Decimal('399'), close=Decimal('401'), volume=1000000
        ),
    ]

    # Strategy generates BUY signal
    strategy = SignalGeneratingStrategy(buy_dates=[date1])

    data_handler = MockDataHandler(bars)
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    # No warmup_end_date (original behavior)
    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=None
    )

    event_loop.run()

    # Verify signal executed (no warmup blocking)
    assert len(event_loop.all_signals) == 1
    assert len(event_loop.all_fills) == 1
    assert portfolio.cash < Decimal('100000')


def test_warmup_strategy_on_bar_still_called():
    """Test that Strategy.on_bar() is called during warmup (for indicator warmup)."""
    warmup_date = datetime(2024, 1, 5, 9, 30, tzinfo=timezone.utc)
    trading_date = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)

    bars = [
        MarketDataEvent(
            symbol='QQQ', timestamp=warmup_date,
            open=Decimal('400'), high=Decimal('402'),
            low=Decimal('399'), close=Decimal('401'), volume=1000000
        ),
        MarketDataEvent(
            symbol='QQQ', timestamp=trading_date,
            open=Decimal('405'), high=Decimal('407'),
            low=Decimal('404'), close=Decimal('406'), volume=1100000
        ),
    ]

    strategy = MockStrategy()
    data_handler = MockDataHandler(bars)
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    warmup_end = datetime(2024, 1, 10, 9, 30, tzinfo=timezone.utc)
    event_loop = EventLoop(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        warmup_end_date=warmup_end
    )

    event_loop.run()

    # Verify strategy.on_bar() was called for BOTH warmup and trading bars
    assert len(strategy.bars_processed) == 2
    assert strategy.bars_processed[0].timestamp == warmup_date
    assert strategy.bars_processed[1].timestamp == trading_date
