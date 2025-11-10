"""
Unit tests for baseline display in CLI backtest command.

Tests the display of baseline comparison metrics in CLI output.
"""
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from decimal import Decimal

from jutsu_engine.cli.main import cli, _display_baseline_section, _display_comparison_section


@pytest.fixture
def runner():
    """Create Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_backtest_results_with_baseline():
    """Mock backtest results with baseline comparison."""
    return {
        'strategy_name': 'MACD_Trend_v6',
        'final_value': 150000,
        'total_return': 0.50,  # 50%
        'annualized_return': 0.1587,  # 15.87%
        'sharpe_ratio': 2.78,
        'max_drawdown': -0.125,  # -12.5%
        'win_rate': 0.65,  # 65%
        'total_trades': 42,
        'config': {
            'initial_capital': Decimal('100000'),
            'symbols': ['QQQ'],
        },
        'baseline': {
            'baseline_symbol': 'QQQ',
            'baseline_final_value': 125000,
            'baseline_total_return': 0.25,  # 25%
            'baseline_annualized_return': 0.08,  # 8%
            'alpha': 2.00  # 2x outperformance
        }
    }


@pytest.fixture
def mock_backtest_results_without_baseline():
    """Mock backtest results without baseline (baseline = None)."""
    return {
        'strategy_name': 'MACD_Trend_v6',
        'final_value': 150000,
        'total_return': 0.50,
        'annualized_return': 0.1587,
        'sharpe_ratio': 2.78,
        'max_drawdown': -0.125,
        'win_rate': 0.65,
        'total_trades': 42,
        'config': {
            'initial_capital': Decimal('100000'),
            'symbols': ['QQQ'],
        },
        'baseline': None  # No baseline
    }


@pytest.fixture
def mock_backtest_results_alpha_none():
    """Mock backtest results with alpha=None (baseline return = 0)."""
    return {
        'strategy_name': 'MACD_Trend_v6',
        'final_value': 150000,
        'total_return': 0.50,
        'annualized_return': 0.1587,
        'sharpe_ratio': 2.78,
        'max_drawdown': -0.125,
        'win_rate': 0.65,
        'total_trades': 42,
        'config': {
            'initial_capital': Decimal('100000'),
            'symbols': ['QQQ'],
        },
        'baseline': {
            'baseline_symbol': 'QQQ',
            'baseline_final_value': 100000,
            'baseline_total_return': 0.0,  # 0% return
            'baseline_annualized_return': 0.0,
            'alpha': None,  # Cannot calculate
            'alpha_note': 'Cannot calculate ratio (baseline return = 0)'
        }
    }


@pytest.fixture
def mock_backtest_results_underperformance():
    """Mock backtest results with underperformance (alpha < 1)."""
    return {
        'strategy_name': 'MACD_Trend_v6',
        'final_value': 110000,
        'total_return': 0.10,  # 10%
        'annualized_return': 0.03,
        'sharpe_ratio': 1.2,
        'max_drawdown': -0.15,
        'win_rate': 0.55,
        'total_trades': 30,
        'config': {
            'initial_capital': Decimal('100000'),
            'symbols': ['QQQ'],
        },
        'baseline': {
            'baseline_symbol': 'QQQ',
            'baseline_final_value': 125000,
            'baseline_total_return': 0.25,  # 25%
            'baseline_annualized_return': 0.08,
            'alpha': 0.40  # Underperformance
        }
    }


class TestBaselineDisplayHelpers:
    """Test baseline display helper functions."""

    def test_display_baseline_section(self, runner):
        """Test baseline section displays correctly."""
        baseline = {
            'baseline_symbol': 'QQQ',
            'baseline_final_value': 125000,
            'baseline_total_return': 0.25,
            'baseline_annualized_return': 0.08
        }

        # Use CliRunner.invoke to capture output with click context
        # (We need Click's context for secho to work properly)
        with runner.isolated_filesystem():
            from click import echo
            import io
            import sys

            # Capture stdout
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            _display_baseline_section(baseline)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

        # Assert baseline content
        assert 'BASELINE (Buy & Hold QQQ):' in output
        assert '$125,000.00' in output
        assert '25.00%' in output
        assert '8.00%' in output

    def test_display_comparison_section_outperformance(self, runner):
        """Test comparison section with outperformance (alpha > 1)."""
        results = {
            'total_return': 0.50
        }
        baseline = {
            'baseline_total_return': 0.25,
            'alpha': 2.00
        }

        # Capture output
        with runner.isolated_filesystem():
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            _display_comparison_section(results, baseline)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

        # Assert comparison content
        assert 'PERFORMANCE vs BASELINE:' in output
        assert '2.00x' in output
        assert 'outperformance' in output
        assert '+25.00%' in output  # Excess return
        assert '2.00:1' in output  # Return ratio

    def test_display_comparison_section_underperformance(self, runner):
        """Test comparison section with underperformance (alpha < 1)."""
        results = {
            'total_return': 0.10
        }
        baseline = {
            'baseline_total_return': 0.25,
            'alpha': 0.40
        }

        # Capture output
        with runner.isolated_filesystem():
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            _display_comparison_section(results, baseline)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

        # Assert comparison content
        assert 'PERFORMANCE vs BASELINE:' in output
        assert '0.40x' in output
        assert 'underperformance' in output
        assert '-15.00%' in output  # Excess return (negative)

    def test_display_comparison_section_alpha_none(self, runner):
        """Test comparison section when alpha is None."""
        results = {
            'total_return': 0.50
        }
        baseline = {
            'baseline_total_return': 0.0,
            'alpha': None,
            'alpha_note': 'Cannot calculate ratio (baseline return = 0)'
        }

        # Capture output
        with runner.isolated_filesystem():
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            _display_comparison_section(results, baseline)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

        # Assert alpha N/A displayed
        assert 'N/A' in output
        assert 'Cannot calculate' in output


class TestBacktestCommandBaseline:
    """Test backtest command with baseline integration."""

    @patch('jutsu_engine.cli.main.importlib.import_module')
    @patch('jutsu_engine.cli.main.BacktestRunner')
    def test_backtest_displays_baseline_section(
        self,
        mock_runner_class,
        mock_import,
        runner,
        mock_backtest_results_with_baseline
    ):
        """Test backtest command displays baseline section when available."""
        # Mock strategy import
        mock_strategy_module = MagicMock()
        mock_strategy_class = MagicMock()
        mock_strategy_module.sma_crossover = mock_strategy_class
        mock_import.return_value = mock_strategy_module

        # Mock BacktestRunner.run() to return results with baseline
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_backtest_results_with_baseline
        mock_runner_class.return_value = mock_runner

        # Run backtest command (minimal args)
        result = runner.invoke(cli, [
            'backtest',
            '--symbol', 'QQQ',
            '--start', '2024-01-01',
            '--end', '2024-12-31'
        ])

        # Assert baseline section present
        assert 'BASELINE (Buy & Hold QQQ):' in result.output
        assert '$125,000.00' in result.output
        assert '25.00%' in result.output

    @patch('jutsu_engine.cli.main.importlib.import_module')
    @patch('jutsu_engine.cli.main.BacktestRunner')
    def test_backtest_displays_comparison_section(
        self,
        mock_runner_class,
        mock_import,
        runner,
        mock_backtest_results_with_baseline
    ):
        """Test backtest command displays comparison section."""
        # Mock strategy import
        mock_strategy_module = MagicMock()
        mock_strategy_class = MagicMock()
        mock_strategy_module.sma_crossover = mock_strategy_class
        mock_import.return_value = mock_strategy_module

        # Mock BacktestRunner.run() to return results with baseline
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_backtest_results_with_baseline
        mock_runner_class.return_value = mock_runner

        # Run backtest command
        result = runner.invoke(cli, [
            'backtest',
            '--symbol', 'QQQ',
            '--start', '2024-01-01',
            '--end', '2024-12-31'
        ])

        # Assert comparison section present
        assert 'PERFORMANCE vs BASELINE:' in result.output
        assert '2.00x' in result.output
        assert 'outperformance' in result.output

    @patch('jutsu_engine.cli.main.importlib.import_module')
    @patch('jutsu_engine.cli.main.BacktestRunner')
    def test_backtest_without_baseline(
        self,
        mock_runner_class,
        mock_import,
        runner,
        mock_backtest_results_without_baseline
    ):
        """Test backtest command works without baseline (baseline=None)."""
        # Mock strategy import
        mock_strategy_module = MagicMock()
        mock_strategy_class = MagicMock()
        mock_strategy_module.sma_crossover = mock_strategy_class
        mock_import.return_value = mock_strategy_module

        # Mock BacktestRunner.run() to return results without baseline
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_backtest_results_without_baseline
        mock_runner_class.return_value = mock_runner

        # Run backtest command
        result = runner.invoke(cli, [
            'backtest',
            '--symbol', 'AAPL',
            '--start', '2024-01-01',
            '--end', '2024-12-31'
        ])

        # Assert baseline section NOT present
        assert 'BASELINE (Buy & Hold' not in result.output
        assert 'PERFORMANCE vs BASELINE:' not in result.output

        # Assert strategy section still displays
        assert 'STRATEGY' in result.output
        assert 'Final Value:' in result.output

    @patch('jutsu_engine.cli.main.importlib.import_module')
    @patch('jutsu_engine.cli.main.BacktestRunner')
    def test_backtest_alpha_none_display(
        self,
        mock_runner_class,
        mock_import,
        runner,
        mock_backtest_results_alpha_none
    ):
        """Test backtest displays N/A for alpha when baseline return = 0."""
        # Mock strategy import
        mock_strategy_module = MagicMock()
        mock_strategy_class = MagicMock()
        mock_strategy_module.sma_crossover = mock_strategy_class
        mock_import.return_value = mock_strategy_module

        # Mock BacktestRunner.run() to return results with alpha=None
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_backtest_results_alpha_none
        mock_runner_class.return_value = mock_runner

        # Run backtest command
        result = runner.invoke(cli, [
            'backtest',
            '--symbol', 'QQQ',
            '--start', '2024-01-01',
            '--end', '2024-12-31'
        ])

        # Assert baseline section present (but no comparison)
        assert 'BASELINE (Buy & Hold QQQ):' in result.output

        # Assert comparison section NOT present (alpha is None)
        assert 'PERFORMANCE vs BASELINE:' not in result.output

    @patch('jutsu_engine.cli.main.importlib.import_module')
    @patch('jutsu_engine.cli.main.BacktestRunner')
    def test_backtest_underperformance_display(
        self,
        mock_runner_class,
        mock_import,
        runner,
        mock_backtest_results_underperformance
    ):
        """Test backtest displays underperformance correctly."""
        # Mock strategy import
        mock_strategy_module = MagicMock()
        mock_strategy_class = MagicMock()
        mock_strategy_module.sma_crossover = mock_strategy_class
        mock_import.return_value = mock_strategy_module

        # Mock BacktestRunner.run() to return underperformance results
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_backtest_results_underperformance
        mock_runner_class.return_value = mock_runner

        # Run backtest command
        result = runner.invoke(cli, [
            'backtest',
            '--symbol', 'QQQ',
            '--start', '2024-01-01',
            '--end', '2024-12-31'
        ])

        # Assert comparison section shows underperformance
        assert 'PERFORMANCE vs BASELINE:' in result.output
        assert '0.40x' in result.output
        assert 'underperformance' in result.output
        assert '-15.00%' in result.output  # Negative excess return

    @patch('jutsu_engine.cli.main.importlib.import_module')
    @patch('jutsu_engine.cli.main.BacktestRunner')
    def test_backtest_output_formatting(
        self,
        mock_runner_class,
        mock_import,
        runner,
        mock_backtest_results_with_baseline
    ):
        """Test backtest output has correct formatting (separators, alignment)."""
        # Mock strategy import
        mock_strategy_module = MagicMock()
        mock_strategy_class = MagicMock()
        mock_strategy_module.sma_crossover = mock_strategy_class
        mock_import.return_value = mock_strategy_module

        # Mock BacktestRunner.run() to return results with baseline
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_backtest_results_with_baseline
        mock_runner_class.return_value = mock_runner

        # Run backtest command
        result = runner.invoke(cli, [
            'backtest',
            '--symbol', 'QQQ',
            '--start', '2024-01-01',
            '--end', '2024-12-31'
        ])

        # Assert separators present
        assert '=' * 60 in result.output  # Main section separator
        assert '-' * 60 in result.output  # Subsection separator

        # Assert sections in correct order
        output_lines = result.output.split('\n')
        baseline_idx = next(i for i, line in enumerate(output_lines) if 'BASELINE' in line)
        strategy_idx = next(i for i, line in enumerate(output_lines) if 'STRATEGY' in line)
        comparison_idx = next(i for i, line in enumerate(output_lines) if 'PERFORMANCE vs BASELINE' in line)

        # Baseline comes first, then strategy, then comparison
        assert baseline_idx < strategy_idx < comparison_idx
