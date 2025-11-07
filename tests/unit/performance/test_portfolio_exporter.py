"""
Unit tests for PortfolioCSVExporter.

Tests CSV export functionality for daily portfolio snapshots including:
- Basic export with cash only
- Export with positions
- All-ticker column logic (0 values)
- Day change calculations
- Overall return calculations
- Precision formatting (2 and 4 decimals)
- Output path handling (directory vs file)
"""
import pytest
import csv
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from jutsu_engine.performance.portfolio_exporter import PortfolioCSVExporter


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def initial_capital():
    """Standard initial capital for tests."""
    return Decimal('100000.00')


@pytest.fixture
def exporter(initial_capital):
    """Create PortfolioCSVExporter instance."""
    return PortfolioCSVExporter(initial_capital=initial_capital)


@pytest.fixture
def sample_snapshots_cash_only():
    """Sample snapshots with cash only (no positions)."""
    return [
        {
            'timestamp': datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            'cash': Decimal('100000.00'),
            'positions': {},
            'holdings': {},
            'total_value': Decimal('100000.00')
        },
        {
            'timestamp': datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
            'cash': Decimal('100000.00'),
            'positions': {},
            'holdings': {},
            'total_value': Decimal('100000.00')
        },
    ]


@pytest.fixture
def sample_snapshots_with_positions():
    """Sample snapshots with positions."""
    return [
        {
            'timestamp': datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            'cash': Decimal('50000.00'),
            'positions': {'AAPL': 100},
            'holdings': {'AAPL': Decimal('50000.00')},
            'total_value': Decimal('100000.00')
        },
        {
            'timestamp': datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
            'cash': Decimal('48000.00'),
            'positions': {'AAPL': 100},
            'holdings': {'AAPL': Decimal('52000.00')},
            'total_value': Decimal('100000.00')
        },
        {
            'timestamp': datetime(2024, 1, 3, 16, 0, tzinfo=timezone.utc),
            'cash': Decimal('45000.00'),
            'positions': {'AAPL': 100, 'MSFT': 50},
            'holdings': {'AAPL': Decimal('53000.00'), 'MSFT': Decimal('7000.00')},
            'total_value': Decimal('105000.00')
        },
    ]


class TestPortfolioCSVExporter:
    """Test suite for PortfolioCSVExporter."""

    def test_init(self, initial_capital):
        """Test exporter initialization."""
        exporter = PortfolioCSVExporter(initial_capital=initial_capital)
        assert exporter.initial_capital == initial_capital

    def test_export_empty_snapshots_raises_error(self, exporter, temp_output_dir):
        """Test that exporting empty snapshots raises ValueError."""
        with pytest.raises(ValueError, match="Cannot export empty daily snapshots"):
            exporter.export_daily_portfolio_csv(
                daily_snapshots=[],
                output_path=temp_output_dir,
                strategy_name="TestStrategy"
            )

    def test_export_cash_only_snapshots(
        self,
        exporter,
        sample_snapshots_cash_only,
        temp_output_dir
    ):
        """Test export with cash-only snapshots (no positions)."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_cash_only,
            output_path=temp_output_dir,
            strategy_name="CashOnly"
        )

        # Verify file exists
        assert Path(csv_path).exists()
        assert "CashOnly" in csv_path

        # Read and verify CSV content
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            # Should have 2 rows
            assert len(rows) == 2

            # Verify first row
            row1 = rows[0]
            assert row1['Date'] == '2024-01-01'
            assert row1['Portfolio_Total_Value'] == '100000.00'
            assert row1['Portfolio_Day_Change_Pct'] == '0.0000'  # First day: no change
            assert row1['Portfolio_Overall_Return'] == '0.0000'
            assert row1['Portfolio_PL_Percent'] == '0.0000'
            assert row1['Cash'] == '100000.00'

            # Verify second row
            row2 = rows[1]
            assert row2['Date'] == '2024-01-02'
            assert row2['Portfolio_Total_Value'] == '100000.00'
            assert row2['Portfolio_Day_Change_Pct'] == '0.0000'
            assert row2['Cash'] == '100000.00'

    def test_export_with_positions(
        self,
        exporter,
        sample_snapshots_with_positions,
        temp_output_dir
    ):
        """Test export with positions and all-ticker columns."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_with_positions,
            output_path=temp_output_dir,
            strategy_name="WithPositions"
        )

        # Verify file exists
        assert Path(csv_path).exists()

        # Read and verify CSV content
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)

            # Verify headers include fixed + dynamic ticker columns
            assert 'Date' in headers
            assert 'Portfolio_Total_Value' in headers
            assert 'Portfolio_Day_Change_Pct' in headers
            assert 'Portfolio_Overall_Return' in headers
            assert 'Portfolio_PL_Percent' in headers
            assert 'Cash' in headers

            # All tickers (AAPL, MSFT) should have qty and value columns
            assert 'AAPL_Qty' in headers
            assert 'AAPL_Value' in headers
            assert 'MSFT_Qty' in headers
            assert 'MSFT_Value' in headers

            # Should have 3 rows
            assert len(rows) == 3

            # Verify first row - has AAPL, no MSFT (should show 0)
            row1 = rows[0]
            assert row1['Date'] == '2024-01-01'
            assert row1['Portfolio_Total_Value'] == '100000.00'
            assert row1['Cash'] == '50000.00'
            assert row1['AAPL_Qty'] == '100'
            assert row1['AAPL_Value'] == '50000.00'
            assert row1['MSFT_Qty'] == '0'  # Not held - show 0
            assert row1['MSFT_Value'] == '0.00'

            # Verify second row - still only AAPL
            row2 = rows[1]
            assert row2['Date'] == '2024-01-02'
            assert row2['AAPL_Qty'] == '100'
            assert row2['AAPL_Value'] == '52000.00'
            assert row2['MSFT_Qty'] == '0'
            assert row2['MSFT_Value'] == '0.00'

            # Verify third row - has both AAPL and MSFT
            row3 = rows[2]
            assert row3['Date'] == '2024-01-03'
            assert row3['AAPL_Qty'] == '100'
            assert row3['AAPL_Value'] == '53000.00'
            assert row3['MSFT_Qty'] == '50'
            assert row3['MSFT_Value'] == '7000.00'

    def test_day_change_calculation(
        self,
        exporter,
        sample_snapshots_with_positions,
        temp_output_dir
    ):
        """Test portfolio day change calculation."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_with_positions,
            output_path=temp_output_dir,
            strategy_name="DayChange"
        )

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            # Day 1: 0% (first day, no previous value)
            assert rows[0]['Portfolio_Day_Change_Pct'] == '0.0000'

            # Day 2: 0% (100000 - 100000) / 100000 * 100 = 0%
            assert rows[1]['Portfolio_Day_Change_Pct'] == '0.0000'

            # Day 3: 5% (105000 - 100000) / 100000 * 100 = 5%
            assert rows[2]['Portfolio_Day_Change_Pct'] == '5.0000'

    def test_overall_return_calculation(
        self,
        exporter,
        sample_snapshots_with_positions,
        temp_output_dir
    ):
        """Test overall return percentage calculation."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_with_positions,
            output_path=temp_output_dir,
            strategy_name="OverallReturn"
        )

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            # Day 1: (100000 - 100000) / 100000 * 100 = 0%
            assert rows[0]['Portfolio_Overall_Return'] == '0.0000'
            assert rows[0]['Portfolio_PL_Percent'] == '0.0000'

            # Day 3: (105000 - 100000) / 100000 * 100 = 5%
            assert rows[2]['Portfolio_Overall_Return'] == '5.0000'
            assert rows[2]['Portfolio_PL_Percent'] == '5.0000'

    def test_precision_formatting(
        self,
        exporter,
        sample_snapshots_with_positions,
        temp_output_dir
    ):
        """Test decimal precision: 2 for dollars, 4 for percentages."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_with_positions,
            output_path=temp_output_dir,
            strategy_name="Precision"
        )

        with open(csv_path, 'r') as f:
            content = f.read()

            # All monetary values should have exactly 2 decimal places
            # Portfolio_Total_Value, Cash, ticker values
            assert '100000.00' in content
            assert '50000.00' in content

            # Percentages should have exactly 4 decimal places
            assert '0.0000' in content
            assert '5.0000' in content

    def test_output_path_directory(self, exporter, sample_snapshots_cash_only, temp_output_dir):
        """Test output path when directory is provided."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_cash_only,
            output_path=temp_output_dir,
            strategy_name="DirTest"
        )

        # Should create file in directory with timestamp
        assert csv_path.startswith(temp_output_dir)
        assert "DirTest" in csv_path
        assert csv_path.endswith(".csv")
        assert Path(csv_path).exists()

    def test_output_path_file(self, exporter, sample_snapshots_cash_only, temp_output_dir):
        """Test output path when full file path is provided."""
        file_path = str(Path(temp_output_dir) / "custom_name.csv")

        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_cash_only,
            output_path=file_path,
            strategy_name="FileTest"
        )

        # Should use exact file path
        assert csv_path == file_path
        assert Path(csv_path).exists()

    def test_get_all_tickers(self, exporter, sample_snapshots_with_positions):
        """Test extraction of all unique tickers."""
        tickers = exporter._get_all_tickers(sample_snapshots_with_positions)

        # Should have AAPL and MSFT, sorted alphabetically
        assert tickers == ['AAPL', 'MSFT']

    def test_ticker_columns_alphabetical_order(
        self,
        exporter,
        sample_snapshots_with_positions,
        temp_output_dir
    ):
        """Test that ticker columns are in alphabetical order."""
        csv_path = exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots_with_positions,
            output_path=temp_output_dir,
            strategy_name="AlphaOrder"
        )

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

            # Find ticker columns (exclude Portfolio_Total_Value)
            ticker_cols = [h for h in headers if (h.endswith('_Qty') or h.endswith('_Value')) and h not in ['Portfolio_Total_Value']]

            # Should be: AAPL_Qty, AAPL_Value, MSFT_Qty, MSFT_Value
            expected_order = ['AAPL_Qty', 'AAPL_Value', 'MSFT_Qty', 'MSFT_Value']
            assert ticker_cols == expected_order
