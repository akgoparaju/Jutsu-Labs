"""
Unit tests for Portfolio daily snapshot functionality.

Tests daily snapshot tracking for CSV export:
- Snapshot recording
- Snapshot retrieval
- Multiple snapshots accumulation
- Data structure validation
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from jutsu_engine.portfolio.simulator import PortfolioSimulator


@pytest.fixture
def initial_capital():
    """Standard initial capital for tests."""
    return Decimal('100000.00')


@pytest.fixture
def portfolio(initial_capital):
    """Create PortfolioSimulator instance."""
    return PortfolioSimulator(
        initial_capital=initial_capital,
        commission_per_share=Decimal('0.01'),
        slippage_percent=Decimal('0.001')
    )


class TestPortfolioDailySnapshots:
    """Test suite for portfolio daily snapshot functionality."""

    def test_initial_snapshots_empty(self, portfolio):
        """Test that snapshots list is empty on initialization."""
        snapshots = portfolio.get_daily_snapshots()
        assert snapshots == []

    def test_record_single_snapshot_cash_only(self, portfolio, initial_capital):
        """Test recording single snapshot with cash only."""
        timestamp = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        
        portfolio.record_daily_snapshot(timestamp)
        
        snapshots = portfolio.get_daily_snapshots()
        assert len(snapshots) == 1
        
        snapshot = snapshots[0]
        assert snapshot['timestamp'] == timestamp
        assert snapshot['cash'] == initial_capital
        assert snapshot['positions'] == {}
        assert snapshot['holdings'] == {}
        assert snapshot['total_value'] == initial_capital

    def test_record_multiple_snapshots(self, portfolio):
        """Test recording multiple snapshots over time."""
        timestamps = [
            datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 3, 16, 0, tzinfo=timezone.utc),
        ]
        
        for ts in timestamps:
            portfolio.record_daily_snapshot(ts)
        
        snapshots = portfolio.get_daily_snapshots()
        assert len(snapshots) == 3
        
        # Verify timestamps in order
        for i, ts in enumerate(timestamps):
            assert snapshots[i]['timestamp'] == ts

    def test_snapshot_with_positions(self, portfolio):
        """Test snapshot captures positions correctly."""
        # Simulate a position
        portfolio.positions = {'AAPL': 100}
        portfolio.current_holdings = {'AAPL': Decimal('15000.00')}
        portfolio.cash = Decimal('85000.00')
        
        timestamp = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp)
        
        snapshots = portfolio.get_daily_snapshots()
        snapshot = snapshots[0]
        
        # Verify position data
        assert snapshot['positions'] == {'AAPL': 100}
        assert snapshot['holdings'] == {'AAPL': Decimal('15000.00')}
        assert snapshot['cash'] == Decimal('85000.00')
        assert snapshot['total_value'] == portfolio.get_portfolio_value()

    def test_snapshot_immutability(self, portfolio):
        """Test that modifying original positions doesn't affect snapshot."""
        # Record snapshot with initial position
        portfolio.positions = {'AAPL': 100}
        portfolio.current_holdings = {'AAPL': Decimal('15000.00')}
        
        timestamp = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp)
        
        # Modify original positions
        portfolio.positions['AAPL'] = 200
        portfolio.positions['MSFT'] = 50
        
        # Verify snapshot unchanged
        snapshots = portfolio.get_daily_snapshots()
        snapshot = snapshots[0]
        assert snapshot['positions'] == {'AAPL': 100}
        assert 'MSFT' not in snapshot['positions']

    def test_snapshot_data_structure(self, portfolio):
        """Test snapshot contains all required keys."""
        timestamp = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp)
        
        snapshots = portfolio.get_daily_snapshots()
        snapshot = snapshots[0]
        
        # Verify all required keys present
        required_keys = ['timestamp', 'cash', 'positions', 'holdings', 'total_value']
        for key in required_keys:
            assert key in snapshot

    def test_snapshot_preserves_decimal_precision(self, portfolio):
        """Test that snapshot preserves Decimal precision."""
        portfolio.cash = Decimal('85123.456789')
        portfolio.current_holdings = {'AAPL': Decimal('14876.543211')}
        
        timestamp = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp)
        
        snapshots = portfolio.get_daily_snapshots()
        snapshot = snapshots[0]
        
        # Verify Decimal types preserved
        assert isinstance(snapshot['cash'], Decimal)
        assert isinstance(snapshot['holdings']['AAPL'], Decimal)
        assert isinstance(snapshot['total_value'], Decimal)
        
        # Verify precision preserved
        assert snapshot['cash'] == Decimal('85123.456789')
        assert snapshot['holdings']['AAPL'] == Decimal('14876.543211')

    def test_get_daily_snapshots_returns_copy(self, portfolio):
        """Test that get_daily_snapshots returns a copy, not reference."""
        timestamp = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp)
        
        snapshots1 = portfolio.get_daily_snapshots()
        snapshots2 = portfolio.get_daily_snapshots()
        
        # Should be equal but not same object
        assert snapshots1 == snapshots2
        assert snapshots1 is not snapshots2

    def test_snapshot_evolution_over_time(self, portfolio):
        """Test snapshot evolution as portfolio changes."""
        # Day 1: Cash only
        timestamp1 = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp1)
        
        # Day 2: Buy AAPL
        portfolio.positions = {'AAPL': 100}
        portfolio.current_holdings = {'AAPL': Decimal('15000.00')}
        portfolio.cash = Decimal('85000.00')
        timestamp2 = datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp2)
        
        # Day 3: Buy MSFT
        portfolio.positions = {'AAPL': 100, 'MSFT': 50}
        portfolio.current_holdings = {
            'AAPL': Decimal('15500.00'),
            'MSFT': Decimal('8500.00')
        }
        portfolio.cash = Decimal('76000.00')
        timestamp3 = datetime(2024, 1, 3, 16, 0, tzinfo=timezone.utc)
        portfolio.record_daily_snapshot(timestamp3)
        
        snapshots = portfolio.get_daily_snapshots()
        assert len(snapshots) == 3
        
        # Verify Day 1: Cash only
        assert len(snapshots[0]['positions']) == 0
        
        # Verify Day 2: AAPL only
        assert len(snapshots[1]['positions']) == 1
        assert 'AAPL' in snapshots[1]['positions']
        
        # Verify Day 3: AAPL and MSFT
        assert len(snapshots[2]['positions']) == 2
        assert 'AAPL' in snapshots[2]['positions']
        assert 'MSFT' in snapshots[2]['positions']
