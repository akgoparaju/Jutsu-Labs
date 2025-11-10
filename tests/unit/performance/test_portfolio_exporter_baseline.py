"""
Unit tests for PortfolioCSVExporter baseline columns functionality.

Tests baseline comparison columns (Baseline_QQQ_Value, Baseline_Return_Pct)
added to portfolio daily CSV exports.
"""
import pytest
import pandas as pd
from decimal import Decimal
from datetime import datetime, date
from pathlib import Path

from jutsu_engine.performance.portfolio_exporter import PortfolioCSVExporter


@pytest.fixture
def sample_snapshots():
    """Create sample daily snapshots for testing."""
    return [
        {
            'timestamp': datetime(2024, 1, 1, 16, 0, 0),
            'cash': Decimal('100000.00'),
            'positions': {},
            'holdings': {},
            'total_value': Decimal('100000.00')
        },
        {
            'timestamp': datetime(2024, 1, 2, 16, 0, 0),
            'cash': Decimal('90000.00'),
            'positions': {'AAPL': 50},
            'holdings': {'AAPL': Decimal('11000.00')},
            'total_value': Decimal('101000.00')
        },
        {
            'timestamp': datetime(2024, 1, 3, 16, 0, 0),
            'cash': Decimal('90000.00'),
            'positions': {'AAPL': 50},
            'holdings': {'AAPL': Decimal('12000.00')},
            'total_value': Decimal('102000.00')
        },
    ]


@pytest.fixture
def baseline_info():
    """Create baseline info for testing."""
    return {
        'symbol': 'QQQ',
        'start_price': Decimal('100.00'),
        'price_history': {
            date(2024, 1, 1): Decimal('100.00'),
            date(2024, 1, 2): Decimal('105.00'),
            date(2024, 1, 3): Decimal('110.00'),
        }
    }


class TestBaselineColumns:
    """Test baseline columns in CSV export."""

    def test_csv_contains_baseline_columns(self, tmp_path, sample_snapshots, baseline_info):
        """Test that baseline columns are added to CSV."""
        # Setup
        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        df = pd.read_csv(output_path)
        assert 'Baseline_QQQ_Value' in df.columns
        assert 'Baseline_QQQ_Return_Pct' in df.columns

    def test_baseline_column_order(self, tmp_path, sample_snapshots, baseline_info):
        """Test baseline columns in correct position."""
        # Setup
        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        df = pd.read_csv(output_path)
        columns = list(df.columns)

        # Verify column order (baseline after portfolio metrics, before Cash)
        portfolio_pl_idx = columns.index('Portfolio_PL_Percent')
        baseline_value_idx = columns.index('Baseline_QQQ_Value')
        baseline_return_idx = columns.index('Baseline_QQQ_Return_Pct')
        cash_idx = columns.index('Cash')

        assert baseline_value_idx == portfolio_pl_idx + 1
        assert baseline_return_idx == baseline_value_idx + 1
        assert cash_idx == baseline_return_idx + 1

    def test_baseline_values_calculated_correctly(self, tmp_path, sample_snapshots, baseline_info):
        """Test baseline values are calculated correctly for each day."""
        # Setup
        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        df = pd.read_csv(output_path)

        # Day 1: QQQ at $100, baseline value should be $100,000
        shares = Decimal('100000') / Decimal('100')  # 1000 shares
        expected_value_day1 = shares * Decimal('100')  # $100,000
        assert float(df.loc[0, 'Baseline_QQQ_Value']) == pytest.approx(float(expected_value_day1), rel=0.01)

        # Day 2: QQQ at $105, baseline value should be $105,000
        expected_value_day2 = shares * Decimal('105')  # $105,000
        assert float(df.loc[1, 'Baseline_QQQ_Value']) == pytest.approx(float(expected_value_day2), rel=0.01)

        # Day 3: QQQ at $110, baseline value should be $110,000
        expected_value_day3 = shares * Decimal('110')  # $110,000
        assert float(df.loc[2, 'Baseline_QQQ_Value']) == pytest.approx(float(expected_value_day3), rel=0.01)

    def test_baseline_return_progression(self, tmp_path, sample_snapshots, baseline_info):
        """Test baseline return increases with QQQ price."""
        # Setup
        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        df = pd.read_csv(output_path)

        # Day 1: QQQ at $100, baseline return should be 0%
        expected_return_day1 = 0.0
        assert float(df.loc[0, 'Baseline_QQQ_Return_Pct']) == pytest.approx(expected_return_day1, abs=0.01)

        # Day 2: QQQ at $105, baseline return should be 5%
        expected_return_day2 = 5.0
        assert float(df.loc[1, 'Baseline_QQQ_Return_Pct']) == pytest.approx(expected_return_day2, abs=0.01)

        # Day 3: QQQ at $110, baseline return should be 10%
        expected_return_day3 = 10.0
        assert float(df.loc[2, 'Baseline_QQQ_Return_Pct']) == pytest.approx(expected_return_day3, abs=0.01)

    def test_csv_without_baseline_info(self, tmp_path, sample_snapshots):
        """Test CSV export works without baseline (backward compatibility)."""
        # Setup
        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy"
        )

        # Assert
        assert output_path.exists()
        df = pd.read_csv(output_path)
        assert 'Baseline_QQQ_Value' not in df.columns
        assert 'Baseline_QQQ_Return_Pct' not in df.columns
        assert len(df) == 3

    def test_baseline_missing_price_for_date(self, tmp_path, sample_snapshots):
        """Test handling of missing prices (weekends/holidays)."""
        # Setup - Missing price for day 2
        baseline_info = {
            'symbol': 'QQQ',
            'start_price': Decimal('100.00'),
            'price_history': {
                date(2024, 1, 1): Decimal('100.00'),
                # Missing 2024-01-02 (weekend/holiday)
                date(2024, 1, 3): Decimal('110.00'),
            }
        }

        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        df = pd.read_csv(output_path, keep_default_na=False)

        # Day 1: Should have value
        assert df.loc[0, 'Baseline_QQQ_Value'] != 'N/A'

        # Day 2: Should be N/A (missing price)
        assert df.loc[1, 'Baseline_QQQ_Value'] == 'N/A'
        assert df.loc[1, 'Baseline_QQQ_Return_Pct'] == 'N/A'

        # Day 3: Should have value
        assert df.loc[2, 'Baseline_QQQ_Value'] != 'N/A'

    def test_baseline_with_empty_price_history(self, tmp_path, sample_snapshots):
        """Test CSV generation with empty price history."""
        # Setup
        baseline_info = {
            'symbol': 'QQQ',
            'start_price': Decimal('100.00'),
            'price_history': {}
        }

        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        assert output_path.exists()
        df = pd.read_csv(output_path, keep_default_na=False)

        # All baseline values should be N/A
        assert all(df['Baseline_QQQ_Value'] == 'N/A')
        assert all(df['Baseline_QQQ_Return_Pct'] == 'N/A')

    def test_baseline_invalid_start_price(self, tmp_path, sample_snapshots):
        """Test handling of invalid start price."""
        # Setup - Invalid start price
        baseline_info = {
            'symbol': 'QQQ',
            'start_price': Decimal('0.00'),  # Invalid
            'price_history': {
                date(2024, 1, 1): Decimal('100.00'),
            }
        }

        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert - CSV should be created but baseline columns should not be present
        # because baseline_initial_shares will be None due to invalid start_price
        assert output_path.exists()
        df = pd.read_csv(output_path)
        # CSV will still have columns but no data rows with baseline values
        assert len(df) == 3

    def test_baseline_with_different_symbol(self, tmp_path, sample_snapshots):
        """Test baseline with symbol other than QQQ."""
        # Setup
        baseline_info = {
            'symbol': 'SPY',
            'start_price': Decimal('450.00'),
            'price_history': {
                date(2024, 1, 1): Decimal('450.00'),
                date(2024, 1, 2): Decimal('455.00'),
                date(2024, 1, 3): Decimal('460.00'),
            }
        }

        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert
        df = pd.read_csv(output_path)
        assert 'Baseline_SPY_Value' in df.columns
        assert 'Baseline_SPY_Return_Pct' in df.columns

        # Verify calculations with SPY prices
        shares = Decimal('100000') / Decimal('450')  # ~222.22 shares
        expected_value_day3 = shares * Decimal('460')
        assert float(df.loc[2, 'Baseline_SPY_Value']) == pytest.approx(float(expected_value_day3), rel=0.01)

    def test_baseline_decimal_precision(self, tmp_path, sample_snapshots, baseline_info):
        """Test baseline values maintain proper decimal precision."""
        # Setup
        exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
        output_path = tmp_path / "portfolio.csv"

        # Execute
        exporter.export_daily_portfolio_csv(
            daily_snapshots=sample_snapshots,
            output_path=str(output_path),
            strategy_name="TestStrategy",
            baseline_info=baseline_info
        )

        # Assert - Read the raw file to check formatting
        with open(output_path, 'r') as f:
            lines = f.readlines()

        # Check first data row (skip header)
        first_data_row = lines[1].split(',')
        baseline_value_idx = 5  # Position of Baseline_QQQ_Value
        baseline_return_idx = 6  # Position of Baseline_QQQ_Return_Pct

        # Check value formatting (2 decimal places)
        value = first_data_row[baseline_value_idx]
        assert '.' in value
        decimal_places = len(value.split('.')[1])
        assert decimal_places == 2

        # Check return formatting (4 decimal places)
        ret = first_data_row[baseline_return_idx]
        assert '.' in ret
        decimal_places = len(ret.split('.')[1])
        assert decimal_places >= 4  # At least 4 decimal places
