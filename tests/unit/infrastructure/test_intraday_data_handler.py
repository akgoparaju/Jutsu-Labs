"""
Unit tests for intraday data fetching functionality in DatabaseDataHandler.

Tests the get_intraday_bars_for_time_window method for:
- Timezone conversion (ET to UTC)
- Time window filtering
- Multi-symbol support
- Edge cases (no data, market closed, invalid inputs)
- Performance validation
"""
from datetime import datetime, date, time
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.models import Base, MarketData
from jutsu_engine.data.handlers.database import MultiSymbolDataHandler
from jutsu_engine.core.events import MarketDataEvent


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    return session


@pytest.fixture
def sample_intraday_data(in_memory_db):
    """Insert sample 5min and 15min intraday data for QQQ, TQQQ, PSQ."""
    session = in_memory_db

    # Sample date: 2025-03-10 (Monday)
    test_date = date(2025, 3, 10)

    # QQQ 5min bars for 9:30 AM - 10:00 AM ET (13:30 - 14:00 UTC)
    # Market time 9:30 AM ET = 13:30 UTC
    qqq_5min_bars = [
        {'timestamp': datetime(2025, 3, 10, 13, 30), 'close': Decimal('481.96')},
        {'timestamp': datetime(2025, 3, 10, 13, 35), 'close': Decimal('482.45')},
        {'timestamp': datetime(2025, 3, 10, 13, 40), 'close': Decimal('483.53')},
        {'timestamp': datetime(2025, 3, 10, 13, 45), 'close': Decimal('482.43')},
        {'timestamp': datetime(2025, 3, 10, 13, 50), 'close': Decimal('480.68')},
        {'timestamp': datetime(2025, 3, 10, 13, 55), 'close': Decimal('481.25')},
        {'timestamp': datetime(2025, 3, 10, 14, 0), 'close': Decimal('479.24')},
    ]

    for bar_data in qqq_5min_bars:
        bar = MarketData(
            symbol='QQQ',
            timeframe='5m',
            timestamp=bar_data['timestamp'],
            open=bar_data['close'] - Decimal('0.50'),
            high=bar_data['close'] + Decimal('0.25'),
            low=bar_data['close'] - Decimal('0.75'),
            close=bar_data['close'],
            volume=1000000,
            data_source='test',
            is_valid=True
        )
        session.add(bar)

    # TQQQ 5min bars for same period
    tqqq_5min_bars = [
        {'timestamp': datetime(2025, 3, 10, 13, 30), 'close': Decimal('55.20')},
        {'timestamp': datetime(2025, 3, 10, 13, 35), 'close': Decimal('55.50')},
        {'timestamp': datetime(2025, 3, 10, 13, 40), 'close': Decimal('56.00')},
    ]

    for bar_data in tqqq_5min_bars:
        bar = MarketData(
            symbol='TQQQ',
            timeframe='5m',
            timestamp=bar_data['timestamp'],
            open=bar_data['close'] - Decimal('0.10'),
            high=bar_data['close'] + Decimal('0.05'),
            low=bar_data['close'] - Decimal('0.15'),
            close=bar_data['close'],
            volume=500000,
            data_source='test',
            is_valid=True
        )
        session.add(bar)

    # PSQ 15min bars
    psq_15min_bars = [
        {'timestamp': datetime(2025, 3, 10, 13, 30), 'close': Decimal('12.45')},
        {'timestamp': datetime(2025, 3, 10, 13, 45), 'close': Decimal('12.50')},
        {'timestamp': datetime(2025, 3, 10, 14, 0), 'close': Decimal('12.55')},
    ]

    for bar_data in psq_15min_bars:
        bar = MarketData(
            symbol='PSQ',
            timeframe='15m',
            timestamp=bar_data['timestamp'],
            open=bar_data['close'] - Decimal('0.02'),
            high=bar_data['close'] + Decimal('0.01'),
            low=bar_data['close'] - Decimal('0.03'),
            close=bar_data['close'],
            volume=100000,
            data_source='test',
            is_valid=True
        )
        session.add(bar)

    session.commit()
    return session


def test_basic_time_window_fetch(sample_intraday_data):
    """Test fetching bars for a specific time window."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ', 'TQQQ', 'PSQ'],
        timeframe='1D',  # Not used for this method
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # Fetch 9:30 AM to 9:45 AM ET (13:30 to 13:45 UTC)
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 45),
        interval='5m'
    )

    # Should get 3 bars: 9:30, 9:35, 9:40 (not 9:45 since end_time is exclusive)
    # Actually, end_time should be inclusive based on the implementation
    assert len(bars) == 4  # 9:30, 9:35, 9:40, 9:45
    assert all(isinstance(bar, MarketDataEvent) for bar in bars)
    assert bars[0].timestamp == datetime(2025, 3, 10, 13, 30)
    assert bars[-1].timestamp == datetime(2025, 3, 10, 13, 45)
    assert bars[0].symbol == 'QQQ'


def test_first_15_minutes_of_trading(sample_intraday_data):
    """Test fetching first 15 minutes (9:30-9:45 AM ET)."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 45),
        interval='5m'
    )

    assert len(bars) == 4  # 9:30, 9:35, 9:40, 9:45
    assert bars[0].close == Decimal('481.96')
    assert bars[1].close == Decimal('482.45')
    assert bars[2].close == Decimal('483.53')
    assert bars[3].close == Decimal('482.43')


def test_full_hour_fetch(sample_intraday_data):
    """Test fetching a full hour (9:30-10:00 AM ET)."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(10, 0),
        interval='5m'
    )

    # 9:30, 9:35, 9:40, 9:45, 9:50, 9:55, 10:00
    assert len(bars) == 7
    assert bars[0].timestamp == datetime(2025, 3, 10, 13, 30)  # 9:30 AM ET
    assert bars[-1].timestamp == datetime(2025, 3, 10, 14, 0)  # 10:00 AM ET


def test_timezone_conversion_accuracy(sample_intraday_data):
    """Test that timezone conversion from ET to UTC is accurate."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # 9:30 AM ET on 2025-03-10 should be 13:30 UTC (EDT, UTC-4)
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 35),
        interval='5m'
    )

    assert len(bars) == 2  # 9:30 and 9:35
    # Database stores naive UTC timestamps
    assert bars[0].timestamp == datetime(2025, 3, 10, 13, 30)


def test_multi_symbol_support(sample_intraday_data):
    """Test fetching intraday data for multiple symbols."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ', 'TQQQ', 'PSQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # Test QQQ
    qqq_bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 40),
        interval='5m'
    )
    assert len(qqq_bars) == 3
    assert qqq_bars[0].symbol == 'QQQ'

    # Test TQQQ
    tqqq_bars = handler.get_intraday_bars_for_time_window(
        symbol='TQQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 40),
        interval='5m'
    )
    assert len(tqqq_bars) == 3
    assert tqqq_bars[0].symbol == 'TQQQ'


def test_15min_interval_support(sample_intraday_data):
    """Test fetching 15min bars."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['PSQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    bars = handler.get_intraday_bars_for_time_window(
        symbol='PSQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(10, 0),
        interval='15m'
    )

    # 9:30, 9:45, 10:00
    assert len(bars) == 3
    assert bars[0].timestamp == datetime(2025, 3, 10, 13, 30)
    assert bars[1].timestamp == datetime(2025, 3, 10, 13, 45)
    assert bars[2].timestamp == datetime(2025, 3, 10, 14, 0)


def test_no_data_for_time_window(sample_intraday_data):
    """Test handling when no data exists for the time window."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # Try to fetch data for 3:00 PM - 4:00 PM (after market close)
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(15, 0),
        end_time=time(16, 0),
        interval='5m'
    )

    assert len(bars) == 0


def test_no_data_for_weekend(sample_intraday_data):
    """Test handling weekend date (market closed)."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # Saturday 2025-03-08
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 8),
        start_time=time(9, 30),
        end_time=time(10, 0),
        interval='5m'
    )

    assert len(bars) == 0


def test_invalid_symbol(sample_intraday_data):
    """Test error handling for symbol not in handler."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    with pytest.raises(ValueError, match="not in handler symbols"):
        handler.get_intraday_bars_for_time_window(
            symbol='AAPL',  # Not in symbols list
            date=date(2025, 3, 10),
            start_time=time(9, 30),
            end_time=time(9, 45),
            interval='5m'
        )


def test_invalid_interval(sample_intraday_data):
    """Test error handling for invalid interval."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    with pytest.raises(ValueError, match="Interval must be"):
        handler.get_intraday_bars_for_time_window(
            symbol='QQQ',
            date=date(2025, 3, 10),
            start_time=time(9, 30),
            end_time=time(9, 45),
            interval='1H'  # Invalid interval
        )


def test_single_bar_fetch(sample_intraday_data):
    """Test fetching a single bar (narrow time window)."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # Fetch exactly 9:30 AM bar
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 30),
        interval='5m'
    )

    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2025, 3, 10, 13, 30)
    assert bars[0].close == Decimal('481.96')


def test_chronological_ordering(sample_intraday_data):
    """Test that bars are returned in chronological order."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(10, 0),
        interval='5m'
    )

    # Verify timestamps are in ascending order
    timestamps = [bar.timestamp for bar in bars]
    assert timestamps == sorted(timestamps)

    # Verify no gaps in 5min intervals
    for i in range(len(bars) - 1):
        time_diff = (bars[i + 1].timestamp - bars[i].timestamp).total_seconds()
        assert time_diff == 300  # 5 minutes = 300 seconds


def test_performance_benchmark(sample_intraday_data):
    """Test that query completes in <10ms."""
    import time as time_module

    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    # Measure query time
    start_time = time_module.perf_counter()
    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(10, 0),
        interval='5m'
    )
    end_time = time_module.perf_counter()

    query_time_ms = (end_time - start_time) * 1000

    assert len(bars) > 0  # Ensure query returned data
    assert query_time_ms < 10  # Target: <10ms


def test_data_quality_validation(sample_intraday_data):
    """Test that returned bars have valid OHLCV data."""
    handler = MultiSymbolDataHandler(
        session=sample_intraday_data,
        symbols=['QQQ'],
        timeframe='1D',
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 31)
    )

    bars = handler.get_intraday_bars_for_time_window(
        symbol='QQQ',
        date=date(2025, 3, 10),
        start_time=time(9, 30),
        end_time=time(9, 45),
        interval='5m'
    )

    for bar in bars:
        # Validate OHLC relationships
        assert bar.high >= bar.low
        assert bar.high >= bar.open
        assert bar.high >= bar.close
        assert bar.low <= bar.open
        assert bar.low <= bar.close

        # Validate positive values
        assert bar.open > 0
        assert bar.high > 0
        assert bar.low > 0
        assert bar.close > 0
        assert bar.volume >= 0

        # Validate types
        assert isinstance(bar.open, Decimal)
        assert isinstance(bar.high, Decimal)
        assert isinstance(bar.low, Decimal)
        assert isinstance(bar.close, Decimal)
        assert isinstance(bar.volume, int)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
