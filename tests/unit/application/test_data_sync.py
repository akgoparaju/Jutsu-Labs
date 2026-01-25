"""
Unit tests for DataSync module.

Tests incremental sync, backfill scenarios, metadata management, and data validation.
Uses PostgreSQL session from conftest.py (timezone() function requires PostgreSQL).
"""
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch

from jutsu_engine.application.data_sync import DataSync
from jutsu_engine.data.models import Base, MarketData, DataMetadata, DataAuditLog
from jutsu_engine.data.fetchers.base import DataFetcher


# Use clean_db_session fixture from conftest.py (PostgreSQL)
# The fixture handles transaction rollback for test isolation


@pytest.fixture
def mock_fetcher():
    """Create mock data fetcher."""
    fetcher = Mock(spec=DataFetcher)
    return fetcher


@pytest.fixture
def sample_bars():
    """Create sample bar data for testing - weekdays only to avoid weekend filtering."""
    # Use weekdays only: Jan 2-3, 8-12, 15-17, 2024 (skipping weekends and Jan 1 holiday)
    weekday_dates = [
        datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),   # Tuesday
        datetime(2024, 1, 3, 21, 0, tzinfo=timezone.utc),   # Wednesday
        datetime(2024, 1, 4, 21, 0, tzinfo=timezone.utc),   # Thursday
        datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc),   # Friday
        datetime(2024, 1, 8, 21, 0, tzinfo=timezone.utc),   # Monday
        datetime(2024, 1, 9, 21, 0, tzinfo=timezone.utc),   # Tuesday
        datetime(2024, 1, 10, 21, 0, tzinfo=timezone.utc),  # Wednesday
        datetime(2024, 1, 11, 21, 0, tzinfo=timezone.utc),  # Thursday
        datetime(2024, 1, 12, 21, 0, tzinfo=timezone.utc),  # Friday
        datetime(2024, 1, 16, 21, 0, tzinfo=timezone.utc),  # Tuesday (skip MLK day)
    ]
    bars = []
    for i, dt in enumerate(weekday_dates):
        bars.append({
            'timestamp': dt,
            'open': Decimal('100.00') + i,
            'high': Decimal('102.00') + i,
            'low': Decimal('99.00') + i,
            'close': Decimal('101.00') + i,
            'volume': 1000000 + i * 1000,
            'data_source': 'test',
        })
    return bars


# Use unique test symbol to avoid conflicts with production data
TEST_SYMBOL = 'XTEST_SYNC'


class TestDataSyncBasic:
    """Test basic DataSync operations."""

    def test_initialization(self, clean_db_session):
        """Test DataSync initialization."""
        sync = DataSync(session=clean_db_session)
        assert sync.session == clean_db_session

    def test_sync_symbol_no_existing_data(self, clean_db_session, mock_fetcher, sample_bars):
        """Test sync when no existing data (initial fetch)."""
        mock_fetcher.fetch_bars.return_value = sample_bars

        sync = DataSync(session=clean_db_session)
        result = sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 16, tzinfo=timezone.utc),
        )

        # All 10 bars should be stored (weekdays only, no filtering)
        assert result['bars_fetched'] == 10
        assert result['bars_stored'] == 10
        assert result['bars_updated'] == 0

        # Verify API called with correct parameters
        mock_fetcher.fetch_bars.assert_called_once_with(
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 16, tzinfo=timezone.utc),
        )

    def test_sync_symbol_incremental_update(self, clean_db_session, mock_fetcher, sample_bars):
        """Test incremental update (fetching newer data)."""
        # First sync: store initial data (first 5 weekday bars)
        sync = DataSync(session=clean_db_session)
        mock_fetcher.fetch_bars.return_value = sample_bars[:5]

        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 8, tzinfo=timezone.utc),
        )

        # Second sync: fetch newer data (incremental)
        new_bars = sample_bars[5:]
        mock_fetcher.fetch_bars.return_value = new_bars

        result = sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 16, tzinfo=timezone.utc),
        )

        # Verify incremental fetch: should start from day after last bar (Jan 9)
        last_call_args = mock_fetcher.fetch_bars.call_args[1]
        assert last_call_args['start_date'] == datetime(2024, 1, 9, tzinfo=timezone.utc)
        assert last_call_args['end_date'] == datetime(2024, 1, 16, tzinfo=timezone.utc)

        assert result['bars_fetched'] == 5
        assert result['bars_stored'] == 5


class TestDataSyncBackfill:
    """Test backfill scenarios (fetching earlier historical data)."""

    def test_backfill_earlier_data(self, clean_db_session, mock_fetcher):
        """Test backfill: fetching data BEFORE existing data."""
        sync = DataSync(session=clean_db_session)

        # First sync: store data from 2000-2025
        initial_bars = []
        base_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
        for i in range(10):
            initial_bars.append({
                'timestamp': base_date + timedelta(days=i),
                'open': Decimal('100.00'),
                'high': Decimal('102.00'),
                'low': Decimal('99.00'),
                'close': Decimal('101.00'),
                'volume': 1000000,
                'data_source': 'test',
            })

        mock_fetcher.fetch_bars.return_value = initial_bars
        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2000, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2000, 1, 10, tzinfo=timezone.utc),
        )

        # Second sync: backfill earlier data (1980-1999)
        backfill_bars = []
        backfill_date = datetime(1980, 1, 1, tzinfo=timezone.utc)
        for i in range(5):
            backfill_bars.append({
                'timestamp': backfill_date + timedelta(days=i),
                'open': Decimal('50.00'),
                'high': Decimal('52.00'),
                'low': Decimal('49.00'),
                'close': Decimal('51.00'),
                'volume': 500000,
                'data_source': 'test',
            })

        mock_fetcher.fetch_bars.return_value = backfill_bars

        result = sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(1980, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2025, 1, 1, tzinfo=timezone.utc),  # User requests all data
        )

        # CRITICAL TEST: Verify API called with ADJUSTED end_date (not today!)
        # Should fetch from 1980-01-01 to 1999-12-31 (day before existing data)
        last_call_args = mock_fetcher.fetch_bars.call_args[1]
        assert last_call_args['start_date'] == datetime(1980, 1, 1, tzinfo=timezone.utc)
        assert last_call_args['end_date'] == datetime(1999, 12, 31, tzinfo=timezone.utc)

        assert result['bars_fetched'] == 5
        assert result['bars_stored'] == 5

    def test_metadata_preserves_most_recent_timestamp(self, clean_db_session, mock_fetcher):
        """Test that metadata keeps most recent timestamp after backfill."""
        sync = DataSync(session=clean_db_session)

        # First sync: store recent data (2024)
        recent_bars = [{
            'timestamp': datetime(2024, 12, 31, tzinfo=timezone.utc),
            'open': Decimal('100.00'),
            'high': Decimal('102.00'),
            'low': Decimal('99.00'),
            'close': Decimal('101.00'),
            'volume': 1000000,
            'data_source': 'test',
        }]

        mock_fetcher.fetch_bars.return_value = recent_bars
        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
            end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
        )

        # Check metadata before backfill
        metadata_before = sync._get_metadata(TEST_SYMBOL, '1D')
        assert metadata_before.last_bar_timestamp == datetime(2024, 12, 31, tzinfo=timezone.utc)

        # Second sync: backfill older data (2020)
        old_bars = [{
            'timestamp': datetime(2020, 1, 1, tzinfo=timezone.utc),
            'open': Decimal('50.00'),
            'high': Decimal('52.00'),
            'low': Decimal('49.00'),
            'close': Decimal('51.00'),
            'volume': 500000,
            'data_source': 'test',
        }]

        mock_fetcher.fetch_bars.return_value = old_bars
        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        # CRITICAL TEST: Verify metadata still has MOST RECENT timestamp (2024, not 2020!)
        metadata_after = sync._get_metadata(TEST_SYMBOL, '1D')
        assert metadata_after.last_bar_timestamp == datetime(2024, 12, 31, tzinfo=timezone.utc)
        assert metadata_after.total_bars == 2


class TestDataSyncMetadata:
    """Test metadata management."""

    def test_metadata_created_on_first_sync(self, clean_db_session, mock_fetcher, sample_bars):
        """Test metadata is created after first sync."""
        sync = DataSync(session=clean_db_session)
        mock_fetcher.fetch_bars.return_value = sample_bars

        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        )

        metadata = sync._get_metadata(TEST_SYMBOL, '1D')
        assert metadata is not None
        assert metadata.symbol == TEST_SYMBOL
        assert metadata.timeframe == '1D'
        assert metadata.total_bars == 10
        assert metadata.last_bar_timestamp == sample_bars[-1]['timestamp']

    def test_get_sync_status(self, clean_db_session, mock_fetcher, sample_bars):
        """Test get_sync_status method."""
        sync = DataSync(session=clean_db_session)

        # Before sync
        status = sync.get_sync_status(TEST_SYMBOL, '1D')
        assert status['has_data'] is False
        assert status['total_bars'] == 0

        # After sync
        mock_fetcher.fetch_bars.return_value = sample_bars
        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        )

        status = sync.get_sync_status(TEST_SYMBOL, '1D')
        assert status['has_data'] is True
        assert status['total_bars'] == 10
        assert status['first_bar_timestamp'] == sample_bars[0]['timestamp']
        assert status['last_bar_timestamp'] == sample_bars[-1]['timestamp']


class TestDataSyncValidation:
    """Test data validation."""

    def test_validate_data_all_valid(self, clean_db_session, mock_fetcher, sample_bars):
        """Test validation passes for valid data."""
        sync = DataSync(session=clean_db_session)
        mock_fetcher.fetch_bars.return_value = sample_bars

        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        )

        validation = sync.validate_data(TEST_SYMBOL, '1D')
        assert validation['total_bars'] == 10
        assert validation['valid_bars'] == 10
        assert validation['invalid_bars'] == 0
        assert len(validation['issues']) == 0

    def test_validate_data_detects_invalid_ohlc(self, clean_db_session):
        """Test validation detects invalid OHLC relationships."""
        sync = DataSync(session=clean_db_session)

        # Manually insert invalid bar (high < low)
        invalid_bar = MarketData(
            symbol='TEST',
            timeframe='1D',
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=Decimal('100.00'),
            high=Decimal('98.00'),  # HIGH < LOW!
            low=Decimal('99.00'),
            close=Decimal('101.00'),
            volume=1000000,
            data_source='test',
            is_valid=True,
        )
        clean_db_session.add(invalid_bar)
        clean_db_session.commit()

        validation = sync.validate_data('TEST', '1D')
        assert validation['total_bars'] == 1
        assert validation['valid_bars'] == 0
        assert validation['invalid_bars'] == 1
        assert len(validation['issues']) > 0


class TestDataSyncAudit:
    """Test audit logging."""

    def test_audit_log_created_on_sync(self, clean_db_session, mock_fetcher, sample_bars):
        """Test audit log is created after sync."""
        sync = DataSync(session=clean_db_session)
        mock_fetcher.fetch_bars.return_value = sample_bars

        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        )

        logs = sync.get_audit_logs(symbol=TEST_SYMBOL)
        assert len(logs) == 1
        assert logs[0].operation == 'sync'
        assert logs[0].status == 'success'
        assert logs[0].bars_affected == 10

    def test_audit_log_on_error(self, clean_db_session, mock_fetcher):
        """Test audit log is created on fetch error."""
        sync = DataSync(session=clean_db_session)
        mock_fetcher.fetch_bars.side_effect = Exception("API failure")

        with pytest.raises(Exception):
            sync.sync_symbol(
                fetcher=mock_fetcher,
                symbol=TEST_SYMBOL,
                timeframe='1D',
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
            )

        logs = sync.get_audit_logs(symbol=TEST_SYMBOL)
        assert len(logs) == 1
        assert logs[0].operation == 'fetch'
        assert logs[0].status == 'error'


class TestDataSyncForceRefresh:
    """Test force refresh functionality."""

    def test_force_refresh_ignores_metadata(self, clean_db_session, mock_fetcher, sample_bars):
        """Test force_refresh=True ignores existing metadata."""
        sync = DataSync(session=clean_db_session)

        # First sync
        mock_fetcher.fetch_bars.return_value = sample_bars[:5]
        sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 5, tzinfo=timezone.utc),
        )

        # Second sync with force_refresh=True
        mock_fetcher.fetch_bars.return_value = sample_bars
        result = sync.sync_symbol(
            fetcher=mock_fetcher,
            symbol=TEST_SYMBOL,
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
            force_refresh=True,
        )

        # Verify API called with user's start_date (not incremental)
        last_call_args = mock_fetcher.fetch_bars.call_args[1]
        assert last_call_args['start_date'] == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert result['bars_fetched'] == 10
        assert result['bars_updated'] == 5  # First 5 bars updated
        assert result['bars_stored'] == 5  # Last 5 bars stored
