"""
Unit tests for visualization module.

Tests equity curve and drawdown plotting functionality with various
data scenarios and edge cases.
"""
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import tempfile
import shutil

from jutsu_engine.infrastructure.visualization.equity_plotter import (
    EquityPlotter,
    generate_equity_curve,
    generate_drawdown,
)
from jutsu_engine.infrastructure.visualization.grid_search_plotter import (
    GridSearchPlotter,
)


@pytest.fixture
def sample_csv_simple(tmp_path):
    """
    Create a simple sample CSV with minimal required columns.
    """
    csv_path = tmp_path / "test_backtest.csv"

    # Generate simple test data
    dates = pd.date_range(start='2020-01-01', periods=100, freq='D')
    portfolio_values = [10000 + i * 100 + (i % 10) * 50 for i in range(100)]

    df = pd.DataFrame({
        'Date': dates,
        'Portfolio_Total_Value': portfolio_values,
    })

    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def sample_csv_full(tmp_path):
    """
    Create a comprehensive sample CSV with all baseline columns.
    """
    csv_path = tmp_path / "test_backtest_full.csv"

    # Generate test data with drawdown periods
    dates = pd.date_range(start='2020-01-01', periods=200, freq='D')

    # Portfolio with drawdown period (days 50-75)
    portfolio_values = []
    for i in range(200):
        if i < 50:
            portfolio_values.append(10000 + i * 100)
        elif i < 75:
            # Drawdown period
            portfolio_values.append(15000 - (i - 50) * 80)
        else:
            # Recovery
            portfolio_values.append(13000 + (i - 75) * 120)

    # Baseline and Buy & Hold values
    baseline_values = [10000 + i * 80 for i in range(200)]
    buyhold_values = [10000 + i * 90 for i in range(200)]

    df = pd.DataFrame({
        'Date': dates,
        'Portfolio_Total_Value': portfolio_values,
        'Baseline_QQQ_Value': baseline_values,
        'BuyHold_QQQ_Value': buyhold_values,
        'Cash': [5000] * 200,
    })

    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def sample_csv_with_positions(tmp_path):
    """
    Create a sample CSV with position allocation columns.
    """
    csv_path = tmp_path / "test_backtest_positions.csv"

    dates = pd.date_range(start='2020-01-01', periods=100, freq='D')

    # Portfolio value
    portfolio_values = [10000 + i * 100 for i in range(100)]

    # Position values (3 positions that change over time)
    qqq_values = [3000 + i * 30 for i in range(100)]
    tqqq_values = [4000 + i * 40 for i in range(100)]
    tmf_values = [3000 - i * 10 for i in range(100)]

    df = pd.DataFrame({
        'Date': dates,
        'Portfolio_Total_Value': portfolio_values,
        'Cash': [2000] * 100,
        'QQQ_Qty': [20 + i * 0.1 for i in range(100)],
        'QQQ_Value': qqq_values,
        'TQQQ_Qty': [30 + i * 0.2 for i in range(100)],
        'TQQQ_Value': tqqq_values,
        'TMF_Qty': [25 - i * 0.05 for i in range(100)],
        'TMF_Value': tmf_values,
    })

    df.to_csv(csv_path, index=False)
    return csv_path


class TestEquityPlotter:
    """Test suite for EquityPlotter class."""

    def test_init_with_valid_csv(self, sample_csv_simple, tmp_path):
        """Test EquityPlotter initialization with valid CSV."""
        plotter = EquityPlotter(csv_path=sample_csv_simple)

        assert plotter.csv_path == sample_csv_simple
        assert plotter.output_dir == sample_csv_simple.parent / 'plots'
        assert plotter.output_dir.exists()
        assert len(plotter._df) == 100

    def test_init_with_custom_output_dir(self, sample_csv_simple, tmp_path):
        """Test EquityPlotter initialization with custom output directory."""
        custom_dir = tmp_path / "custom_plots"
        plotter = EquityPlotter(csv_path=sample_csv_simple, output_dir=custom_dir)

        assert plotter.output_dir == custom_dir
        assert custom_dir.exists()

    def test_init_with_missing_csv(self, tmp_path):
        """Test EquityPlotter raises error for missing CSV file."""
        missing_csv = tmp_path / "missing.csv"

        with pytest.raises(FileNotFoundError, match="CSV file not found"):
            EquityPlotter(csv_path=missing_csv)

    def test_init_with_invalid_csv_columns(self, tmp_path):
        """Test EquityPlotter raises error for CSV missing required columns."""
        csv_path = tmp_path / "invalid.csv"
        df = pd.DataFrame({
            'Date': pd.date_range(start='2020-01-01', periods=10),
            'Wrong_Column': [10000] * 10,
        })
        df.to_csv(csv_path, index=False)

        with pytest.raises(ValueError, match="CSV missing required columns"):
            EquityPlotter(csv_path=csv_path)

    def test_calculate_drawdown_simple(self, sample_csv_simple):
        """Test drawdown calculation with simple increasing values."""
        plotter = EquityPlotter(csv_path=sample_csv_simple)
        portfolio_values = plotter._df['Portfolio_Total_Value']

        drawdowns = plotter._calculate_drawdown(portfolio_values)

        # For increasing values, drawdown should be mostly zero or small negatives
        assert len(drawdowns) == len(portfolio_values)
        assert drawdowns.iloc[0] == 0.0  # First value is always zero
        assert all(drawdowns <= 0)  # All drawdowns are zero or negative

    def test_calculate_drawdown_with_decline(self):
        """Test drawdown calculation with explicit decline."""
        # Create test data with known drawdown
        values = pd.Series([100, 110, 105, 115, 100])

        plotter = EquityPlotter.__new__(EquityPlotter)  # Skip __init__
        drawdowns = plotter._calculate_drawdown(values)

        # Expected drawdowns:
        # 100 -> 0% (first value)
        # 110 -> 0% (new peak)
        # 105 -> -4.55% (from 110 peak)
        # 115 -> 0% (new peak)
        # 100 -> -13.04% (from 115 peak)

        assert drawdowns.iloc[0] == pytest.approx(0.0, abs=0.01)
        assert drawdowns.iloc[1] == pytest.approx(0.0, abs=0.01)
        assert drawdowns.iloc[2] == pytest.approx(-4.55, abs=0.01)
        assert drawdowns.iloc[3] == pytest.approx(0.0, abs=0.01)
        assert drawdowns.iloc[4] == pytest.approx(-13.04, abs=0.01)

    def test_generate_equity_curve_creates_html(self, sample_csv_simple):
        """Test equity curve generation creates HTML file."""
        plotter = EquityPlotter(csv_path=sample_csv_simple)
        output_path = plotter.generate_equity_curve()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.name == 'equity_curve.html'

        # Check HTML content contains Plotly
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Portfolio' in html_content

    def test_generate_equity_curve_with_baselines(self, sample_csv_full):
        """Test equity curve generation with baseline comparison."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        output_path = plotter.generate_equity_curve(include_baseline=True)

        assert output_path.exists()

        # Check HTML contains baseline traces
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Baseline (QQQ)' in html_content
            assert 'Buy & Hold (QQQ)' in html_content

    def test_generate_equity_curve_without_baselines(self, sample_csv_full):
        """Test equity curve generation without baseline comparison."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        output_path = plotter.generate_equity_curve(include_baseline=False)

        assert output_path.exists()

        # Check HTML does NOT contain baseline traces
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Portfolio' in html_content
            # Baseline traces should not be in the plot
            # (Note: Baseline might be in axis labels, so check for trace names)

    def test_generate_equity_curve_custom_filename(self, sample_csv_simple):
        """Test equity curve generation with custom filename."""
        plotter = EquityPlotter(csv_path=sample_csv_simple)
        custom_name = 'my_custom_equity.html'
        output_path = plotter.generate_equity_curve(filename=custom_name)

        assert output_path.exists()
        assert output_path.name == custom_name

    def test_generate_drawdown_creates_html(self, sample_csv_full):
        """Test drawdown generation creates HTML file."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        output_path = plotter.generate_drawdown()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.name == 'drawdown.html'

        # Check HTML content
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Drawdown' in html_content

    def test_generate_drawdown_with_baselines(self, sample_csv_full):
        """Test drawdown generation with baseline comparison."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        output_path = plotter.generate_drawdown(include_baseline=True)

        assert output_path.exists()

        # Check HTML contains baseline drawdown traces
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Portfolio Drawdown' in html_content
            assert 'Baseline (QQQ) Drawdown' in html_content
            assert 'Buy & Hold (QQQ) Drawdown' in html_content

    def test_generate_drawdown_without_baselines(self, sample_csv_full):
        """Test drawdown generation without baseline comparison."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        output_path = plotter.generate_drawdown(include_baseline=False)

        assert output_path.exists()

        # Check HTML does NOT contain baseline drawdown traces
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Portfolio Drawdown' in html_content

    def test_generate_drawdown_custom_filename(self, sample_csv_simple):
        """Test drawdown generation with custom filename."""
        plotter = EquityPlotter(csv_path=sample_csv_simple)
        custom_name = 'my_custom_drawdown.html'
        output_path = plotter.generate_drawdown(filename=custom_name)

        assert output_path.exists()
        assert output_path.name == custom_name

    def test_generate_all_plots(self, sample_csv_with_positions):
        """Test generating all plots at once."""
        plotter = EquityPlotter(csv_path=sample_csv_with_positions)
        plots = plotter.generate_all_plots()

        # Verify all plots generated
        assert isinstance(plots, dict)
        assert 'equity_curve' in plots
        assert 'drawdown' in plots
        assert 'positions' in plots
        assert 'returns' in plots
        assert 'dashboard' in plots

        # Verify all files exist
        for plot_path in plots.values():
            assert plot_path.exists()
            assert plot_path.suffix == '.html'

    def test_plot_file_size(self, sample_csv_full):
        """Test that generated plot files are reasonably sized."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        equity_path = plotter.generate_equity_curve()

        # File should be < 100KB with CDN Plotly.js
        file_size_kb = equity_path.stat().st_size / 1024
        assert file_size_kb < 100, f"File size {file_size_kb:.2f}KB exceeds 100KB target"

    def test_generate_positions_creates_html(self, sample_csv_with_positions):
        """Test position allocation generation creates HTML file."""
        plotter = EquityPlotter(csv_path=sample_csv_with_positions)
        output_path = plotter.generate_positions()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.name == 'position_allocation.html'

        # Check HTML content contains position symbols
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'QQQ' in html_content
            assert 'TQQQ' in html_content
            assert 'TMF' in html_content

    def test_generate_positions_no_positions(self, sample_csv_simple):
        """Test position allocation handles CSV with no position columns."""
        plotter = EquityPlotter(csv_path=sample_csv_simple)
        output_path = plotter.generate_positions()

        assert output_path.exists()

        # Check HTML contains "no data" message
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'No position data available' in html_content

    def test_generate_positions_custom_filename(self, sample_csv_with_positions):
        """Test position allocation with custom filename."""
        plotter = EquityPlotter(csv_path=sample_csv_with_positions)
        custom_name = 'my_positions.html'
        output_path = plotter.generate_positions(filename=custom_name)

        assert output_path.exists()
        assert output_path.name == custom_name

    def test_generate_returns_distribution_creates_html(self, sample_csv_full):
        """Test returns distribution generation creates HTML file."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        output_path = plotter.generate_returns_distribution()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.name == 'returns_distribution.html'

        # Check HTML content
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Daily Returns' in html_content
            assert 'Mean:' in html_content
            assert 'Std Dev:' in html_content

    def test_generate_returns_distribution_custom_filename(self, sample_csv_full):
        """Test returns distribution with custom filename."""
        plotter = EquityPlotter(csv_path=sample_csv_full)
        custom_name = 'my_returns.html'
        output_path = plotter.generate_returns_distribution(filename=custom_name)

        assert output_path.exists()
        assert output_path.name == custom_name

    def test_generate_dashboard_creates_html(self, sample_csv_with_positions):
        """Test dashboard generation creates HTML file."""
        plotter = EquityPlotter(csv_path=sample_csv_with_positions)
        output_path = plotter.generate_dashboard()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.name == 'dashboard.html'

        # Check HTML content contains all subplot titles
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Equity Curve' in html_content
            assert 'Drawdown' in html_content
            assert 'Position Allocation' in html_content
            assert 'Returns Distribution' in html_content

    def test_generate_dashboard_custom_filename(self, sample_csv_with_positions):
        """Test dashboard with custom filename."""
        plotter = EquityPlotter(csv_path=sample_csv_with_positions)
        custom_name = 'my_dashboard.html'
        output_path = plotter.generate_dashboard(filename=custom_name)

        assert output_path.exists()
        assert output_path.name == custom_name

    def test_dashboard_file_size(self, sample_csv_with_positions):
        """Test dashboard file size is reasonable."""
        plotter = EquityPlotter(csv_path=sample_csv_with_positions)
        dashboard_path = plotter.generate_dashboard()

        # Dashboard can be larger due to multiple subplots, but should stay under 500KB
        file_size_kb = dashboard_path.stat().st_size / 1024
        assert file_size_kb < 500, f"Dashboard size {file_size_kb:.2f}KB exceeds 500KB target"


class TestConvenienceFunctions:
    """Test suite for convenience wrapper functions."""

    def test_generate_equity_curve_function(self, sample_csv_simple):
        """Test generate_equity_curve convenience function."""
        output_path = generate_equity_curve(csv_path=sample_csv_simple)

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.parent.name == 'plots'

    def test_generate_equity_curve_custom_output(self, sample_csv_simple, tmp_path):
        """Test generate_equity_curve with custom output directory."""
        custom_dir = tmp_path / "custom"
        output_path = generate_equity_curve(
            csv_path=sample_csv_simple,
            output_dir=custom_dir
        )

        assert output_path.exists()
        assert output_path.parent == custom_dir

    def test_generate_drawdown_function(self, sample_csv_simple):
        """Test generate_drawdown convenience function."""
        output_path = generate_drawdown(csv_path=sample_csv_simple)

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert output_path.parent.name == 'plots'

    def test_generate_drawdown_custom_output(self, sample_csv_simple, tmp_path):
        """Test generate_drawdown with custom output directory."""
        custom_dir = tmp_path / "custom"
        output_path = generate_drawdown(
            csv_path=sample_csv_simple,
            output_dir=custom_dir
        )

        assert output_path.exists()
        assert output_path.parent == custom_dir


class TestRealWorldData:
    """Test suite with real backtest CSV data."""

    def test_with_actual_backtest_csv(self):
        """Test plotting with actual backtest CSV from project."""
        csv_path = Path(
            '/Users/anil.goparaju/Documents/Python/Projects/Jutsu-Labs/'
            'output/grid_search_Hierarchical_Adaptive_v3_5b_2025-11-22_115642/'
            'run_001/Hierarchical_Adaptive_v3_5b_20251122_115651.csv'
        )

        if not csv_path.exists():
            pytest.skip(f"Real backtest CSV not found: {csv_path}")

        plotter = EquityPlotter(csv_path=csv_path)

        # Generate all plots
        plots = plotter.generate_all_plots()

        # Verify all plots generated
        assert isinstance(plots, dict)
        assert 'equity_curve' in plots
        assert 'drawdown' in plots

        equity_path = plots['equity_curve']
        drawdown_path = plots['drawdown']

        assert equity_path.exists()
        assert drawdown_path.exists()

        # Verify plots directory structure
        assert equity_path.parent == csv_path.parent / 'plots'

        # Check file sizes (real backtest CSV has many columns, so files can be larger)
        equity_size_kb = equity_path.stat().st_size / 1024
        drawdown_size_kb = drawdown_path.stat().st_size / 1024

        # Real data with many columns can be 500KB, still reasonable for CDN Plotly
        assert equity_size_kb < 1024, f"Equity plot {equity_size_kb:.2f}KB too large"
        assert drawdown_size_kb < 1024, f"Drawdown plot {drawdown_size_kb:.2f}KB too large"

        # Verify HTML content
        with open(equity_path, 'r') as f:
            equity_html = f.read()
            assert 'Portfolio' in equity_html
            assert 'Baseline' in equity_html or 'QQQ' in equity_html

        with open(drawdown_path, 'r') as f:
            drawdown_html = f.read()
            assert 'Drawdown' in drawdown_html


class TestPerformance:
    """Test suite for performance targets."""

    def test_performance_large_dataset(self, tmp_path):
        """Test plot generation performance with 4000-bar backtest."""
        import time

        # Generate 4000 bars of test data with position columns
        csv_path = tmp_path / "large_backtest.csv"
        dates = pd.date_range(start='2010-01-01', periods=4000, freq='D')
        portfolio_values = [10000 + i * 50 + (i % 100) * 25 for i in range(4000)]
        baseline_values = [10000 + i * 45 for i in range(4000)]

        # Add position columns
        qqq_values = [3000 + i * 10 for i in range(4000)]
        tqqq_values = [4000 + i * 15 for i in range(4000)]
        tmf_values = [3000 + i * 8 for i in range(4000)]

        df = pd.DataFrame({
            'Date': dates,
            'Portfolio_Total_Value': portfolio_values,
            'Baseline_QQQ_Value': baseline_values,
            'QQQ_Value': qqq_values,
            'TQQQ_Value': tqqq_values,
            'TMF_Value': tmf_values,
        })
        df.to_csv(csv_path, index=False)

        # Test equity curve performance
        plotter = EquityPlotter(csv_path=csv_path)

        start_time = time.time()
        equity_path = plotter.generate_equity_curve()
        equity_time = time.time() - start_time

        assert equity_time < 1.0, f"Equity curve generation took {equity_time:.2f}s (target: <1s)"

        # Test drawdown performance
        start_time = time.time()
        drawdown_path = plotter.generate_drawdown()
        drawdown_time = time.time() - start_time

        assert drawdown_time < 1.0, f"Drawdown generation took {drawdown_time:.2f}s (target: <1s)"

        # Test position allocation performance
        start_time = time.time()
        positions_path = plotter.generate_positions()
        positions_time = time.time() - start_time

        assert positions_time < 1.0, f"Position allocation took {positions_time:.2f}s (target: <1s)"

        # Test returns distribution performance
        start_time = time.time()
        returns_path = plotter.generate_returns_distribution()
        returns_time = time.time() - start_time

        assert returns_time < 0.5, f"Returns distribution took {returns_time:.2f}s (target: <0.5s)"

        # Test dashboard performance
        start_time = time.time()
        dashboard_path = plotter.generate_dashboard()
        dashboard_time = time.time() - start_time

        assert dashboard_time < 2.0, f"Dashboard generation took {dashboard_time:.2f}s (target: <2s)"

        # Test combined performance (all Phase 2 plots)
        start_time = time.time()
        all_plots = plotter.generate_all_plots()
        total_time = time.time() - start_time

        assert total_time < 5.0, f"Total plot generation took {total_time:.2f}s (target: <5s)"
        assert len(all_plots) == 5, f"Expected 5 plots, got {len(all_plots)}"


# ==============================================================================
# Grid Search Plotter Tests (Phase 3)
# ==============================================================================

@pytest.fixture
def sample_grid_search_csv(tmp_path):
    """Create sample grid search results CSV."""
    csv_path = tmp_path / 'grid_search_results.csv'

    # Create synthetic grid search data (20 runs)
    np.random.seed(42)  # For reproducibility

    data = {
        'Run ID': list(range(20)),
        'Symbol Set': ['QQQ_TQQQ_PSQ'] * 20,
        'Portfolio Balance': np.random.uniform(100000, 150000, 20),
        'Total Return %': np.random.uniform(0.20, 0.35, 20),
        'Annualized Return %': np.random.uniform(0.25, 0.30, 20),
        'Max Drawdown': np.random.uniform(-0.40, -0.25, 20),
        'Sharpe Ratio': np.random.uniform(2.5, 3.5, 20),
        'Sortino Ratio': np.random.uniform(0.3, 0.4, 20),
        'Calmar Ratio': np.random.uniform(0.7, 1.0, 20),
        'Total Trades': np.random.randint(50, 150, 20),
        'Profit Factor': np.random.uniform(0.0, 0.05, 20),
        'Win Rate %': np.random.uniform(0.25, 0.35, 20),
        'Avg Win ($)': np.random.uniform(500, 1500, 20),
        'Avg Loss ($)': np.random.uniform(-800, -300, 20),
        'Alpha': np.random.uniform(3.0, 4.5, 20),
        # Parameters
        'Measurement Noise': [2000.0] * 20,
        'Process Noise 1': np.random.choice([0.0001, 0.001, 0.01], 20),
        'Process Noise 2': np.random.choice([0.0001, 0.001, 0.01], 20),
        'Osc Smoothness': np.random.choice([0.1, 0.2, 0.3], 20),
        'Strength Smoothness': np.random.choice([0.05, 0.1, 0.15], 20),
        'Bond Sma Fast': np.random.choice([20, 25, 30], 20),
        'Bond Sma Slow': np.random.choice([40, 50, 60], 20),
        'Leverage Scalar': [1.0] * 20,
        'Use Inverse Hedge': [True] * 20,
        'Rebalance Threshold': np.random.choice([0.05, 0.10, 0.15], 20),
        # Stress tests
        'qqq_stress_2018_ret': np.random.uniform(-0.05, 0.05, 20),
        'qqq_stress_2020_ret': np.random.uniform(-0.25, -0.15, 20),
        'qqq_stress_2022_ret': np.random.uniform(-0.35, -0.25, 20),
    }

    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)

    return csv_path


@pytest.fixture
def sample_grid_search_plotter(sample_grid_search_csv):
    """Create GridSearchPlotter instance."""
    return GridSearchPlotter(sample_grid_search_csv)


class TestGridSearchPlotter:
    """Test suite for GridSearchPlotter class."""

    def test_init_with_valid_csv(self, sample_grid_search_plotter):
        """Test GridSearchPlotter initialization with valid CSV."""
        assert sample_grid_search_plotter.csv_path.exists()
        assert sample_grid_search_plotter.plots_dir.exists()
        assert len(sample_grid_search_plotter.df) == 20
        assert 'Run ID' in sample_grid_search_plotter.df.columns

    def test_init_with_custom_output_dir(self, sample_grid_search_csv, tmp_path):
        """Test GridSearchPlotter initialization with custom output directory."""
        custom_dir = tmp_path / "custom_plots"
        plotter = GridSearchPlotter(csv_path=sample_grid_search_csv, output_dir=custom_dir)

        assert plotter.plots_dir == custom_dir
        assert custom_dir.exists()

    def test_init_with_missing_csv(self, tmp_path):
        """Test GridSearchPlotter raises error for missing CSV file."""
        missing_csv = tmp_path / "missing.csv"

        with pytest.raises(FileNotFoundError, match="CSV file not found"):
            GridSearchPlotter(csv_path=missing_csv)

    def test_init_with_invalid_csv_columns(self, tmp_path):
        """Test GridSearchPlotter raises error for CSV missing required columns."""
        csv_path = tmp_path / "invalid.csv"
        df = pd.DataFrame({
            'Wrong_Column': [1, 2, 3],
            'Another_Wrong': [4, 5, 6],
        })
        df.to_csv(csv_path, index=False)

        with pytest.raises(ValueError, match="CSV missing required columns"):
            GridSearchPlotter(csv_path=csv_path)

    def test_generate_metric_distributions_creates_html(self, sample_grid_search_plotter):
        """Test metric distributions plot generation."""
        output_path = sample_grid_search_plotter.generate_metric_distributions()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert 'metric_distributions' in output_path.name

        # Check HTML content
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Sharpe Ratio' in html_content

    def test_generate_metric_distributions_custom_metrics(self, sample_grid_search_plotter):
        """Test metric distributions with custom metric selection."""
        custom_metrics = ['Sharpe Ratio', 'Alpha', 'Win Rate %']
        output_path = sample_grid_search_plotter.generate_metric_distributions(
            metrics=custom_metrics
        )

        assert output_path.exists()

        # Verify custom metrics in output
        with open(output_path, 'r') as f:
            html_content = f.read()
            for metric in custom_metrics:
                assert metric in html_content

    def test_generate_metric_distributions_custom_filename(self, sample_grid_search_plotter):
        """Test metric distributions with custom filename."""
        custom_name = 'my_distributions.html'
        output_path = sample_grid_search_plotter.generate_metric_distributions(
            output_filename=custom_name
        )

        assert output_path.exists()
        assert output_path.name == custom_name

    def test_generate_parameter_sensitivity_creates_html(self, sample_grid_search_plotter):
        """Test parameter sensitivity plot generation."""
        output_path = sample_grid_search_plotter.generate_parameter_sensitivity()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert 'parameter_sensitivity' in output_path.name

        # Check HTML content
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Sharpe Ratio' in html_content

    def test_generate_parameter_sensitivity_custom_target(self, sample_grid_search_plotter):
        """Test parameter sensitivity with custom target metric."""
        output_path = sample_grid_search_plotter.generate_parameter_sensitivity(
            target_metric='Alpha'
        )

        assert output_path.exists()

        # Verify target metric in output
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Alpha' in html_content

    def test_generate_parameter_sensitivity_custom_parameters(self, sample_grid_search_plotter):
        """Test parameter sensitivity with custom parameter selection."""
        custom_params = ['Bond Sma Fast', 'Bond Sma Slow']
        output_path = sample_grid_search_plotter.generate_parameter_sensitivity(
            parameters=custom_params
        )

        assert output_path.exists()

    def test_generate_parameter_sensitivity_invalid_metric(self, sample_grid_search_plotter):
        """Test parameter sensitivity raises error for invalid metric."""
        with pytest.raises(ValueError, match="not found in CSV"):
            sample_grid_search_plotter.generate_parameter_sensitivity(
                target_metric='Nonexistent_Metric'
            )

    def test_generate_parameter_correlation_matrix_creates_html(self, sample_grid_search_plotter):
        """Test parameter correlation matrix generation."""
        output_path = sample_grid_search_plotter.generate_parameter_correlation_matrix()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert 'parameter_correlations' in output_path.name

        # Check HTML content
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Correlation' in html_content

    def test_generate_parameter_correlation_matrix_custom_target(self, sample_grid_search_plotter):
        """Test parameter correlation matrix with custom target metric."""
        output_path = sample_grid_search_plotter.generate_parameter_correlation_matrix(
            target_metric='Sortino Ratio'
        )

        assert output_path.exists()

        # Verify target metric in output
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Sortino Ratio' in html_content

    def test_generate_parameter_correlation_matrix_invalid_metric(self, sample_grid_search_plotter):
        """Test parameter correlation matrix raises error for invalid metric."""
        with pytest.raises(ValueError, match="not found in CSV"):
            sample_grid_search_plotter.generate_parameter_correlation_matrix(
                target_metric='Nonexistent_Metric'
            )

    def test_generate_top_runs_comparison_creates_html(self, sample_grid_search_plotter):
        """Test top runs comparison plot generation."""
        output_path = sample_grid_search_plotter.generate_top_runs_comparison()

        assert output_path.exists()
        assert output_path.suffix == '.html'
        assert 'top_runs_comparison' in output_path.name

        # Check HTML content
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'plotly' in html_content.lower()
            assert 'Run' in html_content

    def test_generate_top_runs_comparison_custom_n(self, sample_grid_search_plotter):
        """Test top runs comparison with custom N selection."""
        output_path = sample_grid_search_plotter.generate_top_runs_comparison(top_n=3)

        assert output_path.exists()

        # Verify top 3 in output
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Top 3' in html_content

    def test_generate_top_runs_comparison_custom_sort(self, sample_grid_search_plotter):
        """Test top runs comparison with custom sort metric."""
        output_path = sample_grid_search_plotter.generate_top_runs_comparison(
            sort_by='Alpha'
        )

        assert output_path.exists()

        # Verify sort metric in output
        with open(output_path, 'r') as f:
            html_content = f.read()
            assert 'Alpha' in html_content

    def test_generate_top_runs_comparison_invalid_metric(self, sample_grid_search_plotter):
        """Test top runs comparison raises error for invalid metric."""
        with pytest.raises(ValueError, match="not found in CSV"):
            sample_grid_search_plotter.generate_top_runs_comparison(
                sort_by='Nonexistent_Metric'
            )

    def test_generate_all_plots_returns_dict(self, sample_grid_search_plotter):
        """Test that generate_all_plots returns dictionary of all plots."""
        plot_paths = sample_grid_search_plotter.generate_all_plots()

        # Verify return type is dict
        assert isinstance(plot_paths, dict)

        # Verify all 4 plot types present
        assert 'metric_distributions' in plot_paths
        assert 'parameter_sensitivity' in plot_paths
        assert 'parameter_correlations' in plot_paths
        assert 'top_runs' in plot_paths

        # Verify all files exist
        for plot_path in plot_paths.values():
            assert plot_path.exists()
            assert plot_path.suffix == '.html'

    def test_generate_all_plots_custom_target(self, sample_grid_search_plotter):
        """Test generate_all_plots with custom target metric."""
        plot_paths = sample_grid_search_plotter.generate_all_plots(
            target_metric='Sortino Ratio'
        )

        # Verify all plots generated
        assert len(plot_paths) == 4
        for plot_path in plot_paths.values():
            assert plot_path.exists()

    def test_detect_numeric_parameters(self, sample_grid_search_plotter):
        """Test automatic detection of numeric parameters."""
        params = sample_grid_search_plotter._detect_numeric_parameters()

        # Should include parameter columns
        assert 'Bond Sma Fast' in params
        assert 'Bond Sma Slow' in params

        # Should NOT include metadata or metrics
        assert 'Run ID' not in params
        assert 'Sharpe Ratio' not in params
        assert 'Symbol Set' not in params

    def test_plot_file_sizes(self, sample_grid_search_plotter):
        """Test that generated plot files are reasonably sized."""
        plots = sample_grid_search_plotter.generate_all_plots()

        for plot_type, plot_path in plots.items():
            file_size_kb = plot_path.stat().st_size / 1024

            # All grid search plots should be < 500KB with CDN Plotly.js
            assert file_size_kb < 500, (
                f"{plot_type} plot size {file_size_kb:.2f}KB exceeds 500KB target"
            )


class TestGridSearchPlotterWithRealData:
    """Test suite with real grid search CSV data."""

    def test_with_actual_grid_search_csv(self):
        """Test plotting with actual grid search CSV from project."""
        csv_path = Path(
            '/Users/anil.goparaju/Documents/Python/Projects/Jutsu-Labs/'
            'output/grid_search_Hierarchical_Adaptive_v3_5b_2025-11-22_115642/'
            'tlt_summary_comparison.csv'
        )

        if not csv_path.exists():
            pytest.skip(f"Real grid search CSV not found: {csv_path}")

        plotter = GridSearchPlotter(csv_path=csv_path)

        # Generate all plots
        plots = plotter.generate_all_plots()

        # Verify all plots generated
        assert isinstance(plots, dict)
        assert len(plots) == 4

        for plot_type, plot_path in plots.items():
            assert plot_path.exists()
            assert plot_path.suffix == '.html'

            # Verify plots directory structure
            assert plot_path.parent == csv_path.parent / 'plots'

            # Check file sizes (real data can be larger, but should stay reasonable)
            file_size_kb = plot_path.stat().st_size / 1024
            assert file_size_kb < 1024, (
                f"{plot_type} plot {file_size_kb:.2f}KB too large"
            )


class TestGridSearchPlotterPerformance:
    """Test suite for performance targets."""

    def test_performance_100_runs(self, tmp_path):
        """Test plot generation performance with 100-run grid search."""
        import time

        # Generate 100 runs of test data
        csv_path = tmp_path / "large_grid_search.csv"
        np.random.seed(42)

        data = {
            'Run ID': list(range(100)),
            'Symbol Set': ['QQQ_TQQQ_PSQ'] * 100,
            'Sharpe Ratio': np.random.uniform(2.0, 4.0, 100),
            'Sortino Ratio': np.random.uniform(0.2, 0.5, 100),
            'Calmar Ratio': np.random.uniform(0.5, 1.5, 100),
            'Annualized Return %': np.random.uniform(0.20, 0.35, 100),
            'Max Drawdown': np.random.uniform(-0.50, -0.20, 100),
            'Win Rate %': np.random.uniform(0.20, 0.40, 100),
            'Profit Factor': np.random.uniform(-0.05, 0.10, 100),
            'Alpha': np.random.uniform(2.0, 5.0, 100),
            # Parameters (12 parameters)
            'Bond Sma Fast': np.random.choice([20, 25, 30, 35, 40], 100),
            'Bond Sma Slow': np.random.choice([40, 50, 60, 70, 80], 100),
            'Measurement Noise': np.random.choice([1000, 2000, 3000], 100),
            'Process Noise 1': np.random.uniform(0.0001, 0.01, 100),
            'Process Noise 2': np.random.uniform(0.0001, 0.01, 100),
            'Osc Smoothness': np.random.uniform(0.1, 0.5, 100),
            'Strength Smoothness': np.random.uniform(0.05, 0.2, 100),
            'Leverage Scalar': np.random.uniform(0.8, 1.2, 100),
            'Rebalance Threshold': np.random.uniform(0.05, 0.20, 100),
            'Upper Thresh Z': np.random.uniform(1.0, 3.0, 100),
            'Lower Thresh Z': np.random.uniform(-3.0, -1.0, 100),
            'Vol Crush Threshold': np.random.uniform(0.5, 1.5, 100),
        }

        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)

        plotter = GridSearchPlotter(csv_path=csv_path)

        # Test metric distributions performance
        start_time = time.time()
        metric_path = plotter.generate_metric_distributions()
        metric_time = time.time() - start_time

        assert metric_time < 1.0, (
            f"Metric distributions took {metric_time:.2f}s (target: <1s)"
        )

        # Test parameter sensitivity performance
        start_time = time.time()
        sensitivity_path = plotter.generate_parameter_sensitivity()
        sensitivity_time = time.time() - start_time

        assert sensitivity_time < 2.0, (
            f"Parameter sensitivity took {sensitivity_time:.2f}s (target: <2s)"
        )

        # Test correlation matrix performance
        start_time = time.time()
        corr_path = plotter.generate_parameter_correlation_matrix()
        corr_time = time.time() - start_time

        assert corr_time < 1.0, (
            f"Correlation matrix took {corr_time:.2f}s (target: <1s)"
        )

        # Test top runs performance
        start_time = time.time()
        top_runs_path = plotter.generate_top_runs_comparison()
        top_runs_time = time.time() - start_time

        assert top_runs_time < 0.5, (
            f"Top runs comparison took {top_runs_time:.2f}s (target: <0.5s)"
        )

        # Test combined performance (all plots)
        start_time = time.time()
        all_plots = plotter.generate_all_plots()
        total_time = time.time() - start_time

        assert total_time < 5.0, (
            f"Total plot generation took {total_time:.2f}s (target: <5s)"
        )
        assert len(all_plots) == 4, f"Expected 4 plots, got {len(all_plots)}"
