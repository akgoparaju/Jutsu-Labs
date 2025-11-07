"""
Integration tests for CSV export feature.

Tests full end-to-end CSV export workflow:
- Full backtest → CSV generation
- Timestamp consistency between files
- Both portfolio and trades CSV created
- Output directory structure
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil
import csv

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent


class SimpleTestStrategy(Strategy):
    """Simple test strategy that generates one buy signal."""
    
    def init(self):
        self.traded = False
    
    def on_bar(self, bar: MarketDataEvent):
        # Buy on first bar
        if not self.traded and len(self.get_closes(10)) >= 10:
            self.buy(bar.symbol, Decimal('0.5'))  # 50% of portfolio
            self.traded = True


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_database_with_data(tmp_path, monkeypatch):
    """Create mock database with test data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from jutsu_engine.data.models import Base, MarketData, DataMetadata
    
    # Create in-memory database
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Add test data (20 days of AAPL data)
    start_date = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
    for i in range(20):
        timestamp = datetime(2024, 1, i+1, 16, 0, tzinfo=timezone.utc)
        bar = MarketData(
            symbol='AAPL',
            timestamp=timestamp,
            timeframe='1D',
            open=Decimal('150.00') + Decimal(i),
            high=Decimal('152.00') + Decimal(i),
            low=Decimal('149.00') + Decimal(i),
            close=Decimal('151.00') + Decimal(i),
            volume=1000000,
            source='test',
            is_valid=True
        )
        session.add(bar)
    
    # Add metadata
    metadata = DataMetadata(
        symbol='AAPL',
        timeframe='1D',
        first_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        last_date=datetime(2024, 1, 20, tzinfo=timezone.utc),
        total_bars=20,
        last_updated=datetime.now(timezone.utc),
        source='test'
    )
    session.add(metadata)
    session.commit()
    session.close()
    
    return db_url


class TestCSVExportIntegration:
    """Integration tests for CSV export feature."""
    
    def test_full_backtest_generates_both_csvs(
        self,
        mock_database_with_data,
        temp_output_dir
    ):
        """Test that running backtest generates both portfolio and trades CSVs."""
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_data
        }
        
        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()
        
        results = runner.run(strategy, output_dir=temp_output_dir)
        
        # Verify results include CSV paths
        assert 'portfolio_csv_path' in results
        assert 'trades_csv_path' in results
        
        # Verify both files exist
        assert Path(results['portfolio_csv_path']).exists()
        assert Path(results['trades_csv_path']).exists()
        
        # Verify files in correct directory
        assert results['portfolio_csv_path'].startswith(temp_output_dir)
        assert results['trades_csv_path'].startswith(temp_output_dir)
    
    def test_csv_filenames_have_consistent_timestamps(
        self,
        mock_database_with_data,
        temp_output_dir
    ):
        """Test that portfolio and trades CSVs have matching timestamps."""
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_data
        }
        
        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()
        
        results = runner.run(strategy, output_dir=temp_output_dir)
        
        portfolio_filename = Path(results['portfolio_csv_path']).name
        trades_filename = Path(results['trades_csv_path']).name
        
        # Extract timestamps (format: Strategy_YYYYMMDD_HHMMSS.csv)
        # Portfolio: SimpleTestStrategy_20250107_143022.csv
        # Trades:    SimpleTestStrategy_20250107_143022_trades.csv
        
        portfolio_parts = portfolio_filename.replace('.csv', '').split('_')
        trades_parts = trades_filename.replace('_trades.csv', '').split('_')
        
        # Should have same strategy name and timestamp
        assert portfolio_parts[:-2] == trades_parts[:-2]  # Strategy name
        assert portfolio_parts[-2:] == trades_parts[-2:]  # Date and time
    
    def test_portfolio_csv_structure(
        self,
        mock_database_with_data,
        temp_output_dir
    ):
        """Test portfolio CSV has correct structure and data."""
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_data
        }
        
        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()
        
        results = runner.run(strategy, output_dir=temp_output_dir)
        portfolio_csv = results['portfolio_csv_path']
        
        # Read CSV
        with open(portfolio_csv, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
        
        # Verify required columns
        required_columns = [
            'Date',
            'Portfolio_Total_Value',
            'Portfolio_Day_Change',
            'Portfolio_Overall_Return',
            'Portfolio_PL_Percent',
            'Cash'
        ]
        for col in required_columns:
            assert col in headers
        
        # Should have 20 rows (20 days)
        assert len(rows) == 20
        
        # Verify first row has initial capital
        assert Decimal(rows[0]['Portfolio_Total_Value']) == Decimal('100000.00')
        assert Decimal(rows[0]['Cash']) == Decimal('100000.00')
        
        # After trade (around day 10), should have position
        # Check for AAPL ticker columns
        if 'AAPL_Qty' in headers:
            # Should have non-zero position after trade
            for row in rows[10:]:  # After trade executed
                if Decimal(row.get('AAPL_Qty', 0)) > 0:
                    assert Decimal(row['AAPL_Value']) > 0
                    break
    
    def test_trades_csv_structure(
        self,
        mock_database_with_data,
        temp_output_dir
    ):
        """Test trades CSV has correct structure."""
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_data
        }
        
        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()
        
        results = runner.run(strategy, output_dir=temp_output_dir)
        trades_csv = results['trades_csv_path']
        
        # Read CSV
        with open(trades_csv, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
        
        # Verify key trade columns exist
        required_columns = [
            'Trade_ID',
            'Date',
            'Ticker',
            'Decision',
            'Shares',
            'Fill_Price',
            'Portfolio_Value_Before',
            'Portfolio_Value_After'
        ]
        for col in required_columns:
            assert col in headers
        
        # Should have at least 1 trade (buy signal)
        assert len(rows) >= 1
        
        # Verify first trade is BUY
        assert rows[0]['Decision'] == 'BUY'
        assert rows[0]['Ticker'] == 'AAPL'
    
    def test_custom_output_directory(
        self,
        mock_database_with_data,
        temp_output_dir
    ):
        """Test custom output directory parameter works."""
        custom_dir = str(Path(temp_output_dir) / "custom_output")
        
        config = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'end_date': datetime(2024, 1, 20, tzinfo=timezone.utc),
            'initial_capital': Decimal('100000'),
            'database_url': mock_database_with_data
        }
        
        runner = BacktestRunner(config)
        strategy = SimpleTestStrategy()
        
        results = runner.run(strategy, output_dir=custom_dir)
        
        # Verify files in custom directory
        assert results['portfolio_csv_path'].startswith(custom_dir)
        assert results['trades_csv_path'].startswith(custom_dir)
        assert Path(custom_dir).exists()
