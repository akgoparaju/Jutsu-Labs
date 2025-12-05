"""
Unit tests for DataFreshnessChecker module.

Tests data freshness validation and auto-sync functionality
for the pre-execution data check workflow.
"""

import pytest
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.models import Base, DataMetadata, MarketData
from jutsu_engine.live.data_freshness import (
    DataFreshnessChecker,
    DataFreshnessError,
    SyncError
)


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    engine = create_engine(f'sqlite:///{db_path}')
    Base.metadata.create_all(engine)

    yield db_path

    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def populated_db(temp_db):
    """Create a database with sample data."""
    engine = create_engine(f'sqlite:///{temp_db}')
    Session = sessionmaker(bind=engine)
    session = Session()

    # Get yesterday's date for "fresh" data
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    yesterday_midnight = datetime.combine(yesterday.date(), datetime.min.time()).replace(tzinfo=timezone.utc)

    # Add metadata for QQQ (fresh)
    metadata_qqq = DataMetadata(
        symbol='QQQ',
        timeframe='1D',
        last_bar_timestamp=yesterday_midnight,
        total_bars=250,
        last_updated=datetime.now(timezone.utc)
    )
    session.add(metadata_qqq)

    # Add metadata for TLT (stale - 5 days old)
    stale_date = datetime.now(timezone.utc) - timedelta(days=5)
    stale_midnight = datetime.combine(stale_date.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
    metadata_tlt = DataMetadata(
        symbol='TLT',
        timeframe='1D',
        last_bar_timestamp=stale_midnight,
        total_bars=200,
        last_updated=stale_date
    )
    session.add(metadata_tlt)

    session.commit()
    session.close()

    return temp_db


class TestDataFreshnessChecker:
    """Test suite for DataFreshnessChecker class."""

    def test_init_with_valid_db(self, temp_db):
        """Test initialization with valid database path."""
        checker = DataFreshnessChecker(db_path=temp_db)
        assert checker.db_path == Path(temp_db)
        assert checker.timeframe == '1D'
        assert 'QQQ' in checker.required_symbols
        checker.close()

    def test_init_with_invalid_db(self):
        """Test initialization with non-existent database."""
        with pytest.raises(DataFreshnessError, match="Database not found"):
            DataFreshnessChecker(db_path='/nonexistent/path.db')

    def test_init_with_custom_symbols(self, temp_db):
        """Test initialization with custom symbols list."""
        custom_symbols = ['AAPL', 'MSFT']
        checker = DataFreshnessChecker(
            db_path=temp_db,
            required_symbols=custom_symbols
        )
        assert checker.required_symbols == custom_symbols
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    def test_get_expected_last_bar_date(self, mock_prev_day, temp_db):
        """Test expected last bar date calculation."""
        # Mock previous trading day
        mock_prev_day.return_value = date(2025, 12, 2)

        checker = DataFreshnessChecker(db_path=temp_db)
        expected = checker.get_expected_last_bar_date()

        assert expected.date() == date(2025, 12, 2)
        assert expected.tzinfo is not None
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    def test_get_symbol_freshness_fresh_data(self, mock_prev_day, populated_db):
        """Test freshness check for symbol with fresh data."""
        # Set expected date to yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        mock_prev_day.return_value = yesterday

        checker = DataFreshnessChecker(db_path=populated_db)
        status = checker.get_symbol_freshness('QQQ')

        assert status['symbol'] == 'QQQ'
        assert status['is_fresh'] is True
        assert status['days_stale'] == 0
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    def test_get_symbol_freshness_stale_data(self, mock_prev_day, populated_db):
        """Test freshness check for symbol with stale data."""
        # Set expected date to yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        mock_prev_day.return_value = yesterday

        checker = DataFreshnessChecker(db_path=populated_db)
        status = checker.get_symbol_freshness('TLT')

        assert status['symbol'] == 'TLT'
        assert status['is_fresh'] is False
        assert status['days_stale'] > 0
        checker.close()

    def test_get_symbol_freshness_no_data(self, temp_db):
        """Test freshness check for symbol with no data."""
        checker = DataFreshnessChecker(db_path=temp_db)
        status = checker.get_symbol_freshness('UNKNOWN')

        assert status['symbol'] == 'UNKNOWN'
        assert status['is_fresh'] is False
        assert status['reason'] == 'no_data'
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    def test_check_freshness_all_fresh(self, mock_prev_day, populated_db):
        """Test freshness check when all symbols are fresh."""
        # Mock to return a date older than our "fresh" data
        old_date = (datetime.now(timezone.utc) - timedelta(days=2)).date()
        mock_prev_day.return_value = old_date

        checker = DataFreshnessChecker(
            db_path=populated_db,
            required_symbols=['QQQ']  # Only check QQQ which is fresh
        )

        all_fresh, stale_symbols, details = checker.check_freshness()

        assert all_fresh is True
        assert len(stale_symbols) == 0
        assert len(details) == 1
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    def test_check_freshness_some_stale(self, mock_prev_day, populated_db):
        """Test freshness check when some symbols are stale."""
        # Set expected date to yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        mock_prev_day.return_value = yesterday

        checker = DataFreshnessChecker(
            db_path=populated_db,
            required_symbols=['QQQ', 'TLT']
        )

        all_fresh, stale_symbols, details = checker.check_freshness()

        assert all_fresh is False
        assert 'TLT' in stale_symbols
        assert len(details) == 2
        checker.close()

    @patch('subprocess.run')
    def test_trigger_sync_success(self, mock_run, temp_db):
        """Test successful sync trigger."""
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')

        checker = DataFreshnessChecker(db_path=temp_db)
        result = checker.trigger_sync(symbols=['QQQ'])

        assert result is True
        mock_run.assert_called()
        checker.close()

    @patch('subprocess.run')
    def test_trigger_sync_failure(self, mock_run, temp_db):
        """Test sync trigger failure."""
        mock_run.return_value = Mock(returncode=1, stdout='', stderr='Sync failed')

        checker = DataFreshnessChecker(db_path=temp_db)

        with pytest.raises(SyncError, match="Sync failed"):
            checker.trigger_sync(symbols=['QQQ'])

        checker.close()

    @patch('subprocess.run')
    def test_trigger_sync_timeout(self, mock_run, temp_db):
        """Test sync trigger timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='jutsu sync', timeout=60)

        checker = DataFreshnessChecker(db_path=temp_db)

        with pytest.raises(SyncError, match="timed out"):
            checker.trigger_sync(symbols=['QQQ'])

        checker.close()

    def test_generate_report(self, temp_db):
        """Test report generation."""
        checker = DataFreshnessChecker(db_path=temp_db)

        details = [
            {
                'symbol': 'QQQ',
                'is_fresh': True,
                'last_bar_date': date(2025, 12, 2),
                'expected_date': date(2025, 12, 2),
                'days_stale': 0
            },
            {
                'symbol': 'TLT',
                'is_fresh': False,
                'last_bar_date': date(2025, 11, 28),
                'expected_date': date(2025, 12, 2),
                'days_stale': 4
            }
        ]

        report = checker.generate_report(details)

        assert 'DATA FRESHNESS REPORT' in report
        assert 'QQQ' in report
        assert 'TLT' in report
        assert 'FRESH' in report
        assert 'STALE' in report
        checker.close()

    def test_context_manager(self, temp_db):
        """Test context manager usage."""
        with DataFreshnessChecker(db_path=temp_db) as checker:
            assert checker is not None
            assert checker.session is not None

        # Session should be closed after context exits


class TestDataFreshnessIntegration:
    """Integration tests for data freshness workflow."""

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    @patch('subprocess.run')
    def test_ensure_fresh_data_already_fresh(self, mock_run, mock_prev_day, populated_db):
        """Test ensure_fresh_data when data is already fresh."""
        # Mock to return a date older than our data
        old_date = (datetime.now(timezone.utc) - timedelta(days=2)).date()
        mock_prev_day.return_value = old_date

        checker = DataFreshnessChecker(
            db_path=populated_db,
            required_symbols=['QQQ']
        )

        success, details = checker.ensure_fresh_data(auto_sync=True)

        assert success is True
        mock_run.assert_not_called()  # No sync needed
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    @patch('subprocess.run')
    def test_ensure_fresh_data_with_sync(self, mock_run, mock_prev_day, populated_db):
        """Test ensure_fresh_data with auto-sync for stale data."""
        # Set expected date to yesterday (TLT will be stale)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        mock_prev_day.return_value = yesterday

        # First call returns success
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')

        checker = DataFreshnessChecker(
            db_path=populated_db,
            required_symbols=['TLT']
        )

        # Note: Data will still be stale after mock sync, but sync was triggered
        success, details = checker.ensure_fresh_data(auto_sync=True)

        mock_run.assert_called()  # Sync was triggered
        checker.close()

    @patch('jutsu_engine.live.data_freshness.get_previous_trading_day')
    def test_ensure_fresh_data_no_sync(self, mock_prev_day, populated_db):
        """Test ensure_fresh_data with auto_sync disabled."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        mock_prev_day.return_value = yesterday

        checker = DataFreshnessChecker(
            db_path=populated_db,
            required_symbols=['TLT']
        )

        success, details = checker.ensure_fresh_data(auto_sync=False)

        assert success is False  # TLT is stale, no sync attempted
        checker.close()
