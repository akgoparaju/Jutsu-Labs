"""
Unit tests for grid-search CLI command.

Tests the Click command interface for parameter grid search optimization.
"""
import pytest
from click.testing import CliRunner
from pathlib import Path
from unittest.mock import patch, MagicMock

from jutsu_engine.cli.main import cli
from jutsu_engine.application.grid_search_runner import GridSearchConfig, GridSearchResult, SymbolSet
import pandas as pd


@pytest.fixture
def runner():
    """Create Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_grid_config():
    """Mock GridSearchConfig for testing."""
    return GridSearchConfig(
        strategy_name="MACD_Trend_v4",
        symbol_sets=[
            SymbolSet(
                name="QQQ-TQQQ",
                signal_symbol="QQQ",
                bull_symbol="TQQQ",
                defense_symbol="QQQ"
            )
        ],
        base_config={
            'timeframe': '1D',
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'initial_capital': 100000
        },
        parameters={
            'fast_period': [12, 14],
            'slow_period': [26, 28]
        }
    )


@pytest.fixture
def mock_grid_result(tmp_path, mock_grid_config):
    """Mock GridSearchResult for testing."""
    return GridSearchResult(
        config=mock_grid_config,
        output_dir=tmp_path / "grid_search_output",
        run_results=[],
        summary_df=pd.DataFrame({
            'run_id': ['001', '002'],
            'symbol_set': ['QQQ-TQQQ', 'QQQ-TQQQ'],
            'sharpe_ratio': [1.5, 2.0],
            'annualized_return_pct': [15.0, 20.0],
            'max_drawdown_pct': [-10.0, -8.0]
        })
    )


class TestGridSearchCommand:
    """Test suite for grid-search CLI command."""

    def test_command_exists(self, runner):
        """Test that grid-search command is registered."""
        result = runner.invoke(cli, ['--help'])
        assert result.exit_code == 0
        assert 'grid-search' in result.output

    def test_help_output(self, runner):
        """Test grid-search --help displays correct information."""
        result = runner.invoke(cli, ['grid-search', '--help'])
        assert result.exit_code == 0
        assert 'Run parameter grid search optimization' in result.output
        assert '--config' in result.output
        assert '--output' in result.output

    def test_config_required(self, runner):
        """Test that --config option is required."""
        result = runner.invoke(cli, ['grid-search'])
        assert result.exit_code != 0
        assert 'Missing option' in result.output or 'required' in result.output.lower()

    def test_config_file_must_exist(self, runner):
        """Test that config file path must exist."""
        result = runner.invoke(cli, ['grid-search', '--config', 'nonexistent.yaml'])
        assert result.exit_code != 0

    @patch('jutsu_engine.cli.main.GridSearchRunner.load_config')
    def test_invalid_config_handling(self, mock_load_config, runner, tmp_path):
        """Test graceful handling of invalid configuration."""
        # Create a temporary config file
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: content")

        # Mock load_config to raise exception
        mock_load_config.side_effect = ValueError("Invalid YAML structure")

        result = runner.invoke(cli, ['grid-search', '--config', str(config_file)])

        assert result.exit_code != 0
        assert 'Configuration error' in result.output

    @patch('jutsu_engine.cli.main.GridSearchRunner')
    def test_successful_execution_flow(
        self,
        mock_runner_class,
        runner,
        tmp_path,
        mock_grid_config,
        mock_grid_result
    ):
        """Test successful grid search execution flow."""
        # Create a temporary config file
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
strategy_name: MACD_Trend_v4
symbol_sets:
  - name: QQQ-TQQQ
    signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: QQQ
base_config:
  timeframe: 1D
  start_date: 2024-01-01
  end_date: 2024-12-31
  initial_capital: 100000
parameters:
  fast_period: [12, 14]
  slow_period: [26, 28]
""")

        # Mock GridSearchRunner
        mock_runner = MagicMock()
        mock_runner_class.load_config.return_value = mock_grid_config
        mock_runner_class.return_value = mock_runner
        mock_runner.generate_combinations.return_value = [
            MagicMock(run_id='001'),
            MagicMock(run_id='002')
        ]
        mock_runner.execute_grid_search.return_value = mock_grid_result

        # Execute command
        result = runner.invoke(
            cli,
            ['grid-search', '--config', str(config_file), '--output', str(tmp_path / 'output')]
        )

        # Assertions
        assert result.exit_code == 0
        assert 'Grid Search Parameter Optimization' in result.output
        assert 'Strategy: MACD_Trend_v4' in result.output
        assert 'Total Combinations: 2' in result.output
        assert 'Grid Search Complete!' in result.output
        assert 'Total Runs: 0' in result.output  # Empty run_results in mock

        # Verify methods were called
        mock_runner_class.load_config.assert_called_once_with(str(config_file))
        mock_runner.generate_combinations.assert_called_once()
        mock_runner.execute_grid_search.assert_called_once()

    @patch('jutsu_engine.cli.main.GridSearchRunner')
    def test_large_combination_warning(
        self,
        mock_runner_class,
        runner,
        tmp_path,
        mock_grid_config
    ):
        """Test warning message for large number of combinations."""
        config_file = tmp_path / "large_config.yaml"
        config_file.write_text("strategy_name: Test\nparameters: {}")

        # Mock to return many combinations
        mock_runner = MagicMock()
        mock_runner_class.load_config.return_value = mock_grid_config
        mock_runner_class.return_value = mock_runner
        mock_runner.generate_combinations.return_value = [MagicMock()] * 150

        # Execute with auto-abort (no user input)
        result = runner.invoke(
            cli,
            ['grid-search', '--config', str(config_file)],
            input='n\n'  # Abort when prompted
        )

        assert result.exit_code == 0
        assert 'Warning: 150 backtests will take significant time' in result.output
        assert 'Aborted' in result.output

    @patch('jutsu_engine.cli.main.GridSearchRunner')
    def test_execution_error_handling(
        self,
        mock_runner_class,
        runner,
        tmp_path,
        mock_grid_config
    ):
        """Test graceful handling of execution errors."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("strategy_name: Test\nparameters: {}")

        # Mock to raise error during execution
        mock_runner = MagicMock()
        mock_runner_class.load_config.return_value = mock_grid_config
        mock_runner_class.return_value = mock_runner
        mock_runner.generate_combinations.return_value = [MagicMock()]
        mock_runner.execute_grid_search.side_effect = RuntimeError("Database connection failed")

        result = runner.invoke(cli, ['grid-search', '--config', str(config_file)])

        assert result.exit_code != 0
        assert 'Grid search failed' in result.output

    @patch('jutsu_engine.cli.main.GridSearchRunner')
    def test_custom_output_directory(
        self,
        mock_runner_class,
        runner,
        tmp_path,
        mock_grid_config,
        mock_grid_result
    ):
        """Test custom output directory option."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("strategy_name: Test\nparameters: {}")
        custom_output = tmp_path / "custom_results"

        mock_runner = MagicMock()
        mock_runner_class.load_config.return_value = mock_grid_config
        mock_runner_class.return_value = mock_runner
        mock_runner.generate_combinations.return_value = [MagicMock()]
        mock_runner.execute_grid_search.return_value = mock_grid_result

        result = runner.invoke(
            cli,
            ['grid-search', '--config', str(config_file), '--output', str(custom_output)]
        )

        assert result.exit_code == 0
        # Verify output directory was passed to execute_grid_search
        call_args = mock_runner.execute_grid_search.call_args
        assert call_args[1]['output_base'] == str(custom_output)

    @patch('jutsu_engine.cli.main.GridSearchRunner')
    def test_best_run_display(
        self,
        mock_runner_class,
        runner,
        tmp_path,
        mock_grid_config,
        mock_grid_result
    ):
        """Test that best run information is displayed."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("strategy_name: Test\nparameters: {}")

        mock_runner = MagicMock()
        mock_runner_class.load_config.return_value = mock_grid_config
        mock_runner_class.return_value = mock_runner
        mock_runner.generate_combinations.return_value = [MagicMock()]
        mock_runner.execute_grid_search.return_value = mock_grid_result

        result = runner.invoke(cli, ['grid-search', '--config', str(config_file)])

        assert result.exit_code == 0
        assert 'Best Run (by Sharpe Ratio)' in result.output
        assert 'Run ID: 002' in result.output  # Second run has higher Sharpe
        assert 'Sharpe Ratio: 2.00' in result.output

    @patch('jutsu_engine.cli.main.GridSearchRunner')
    def test_short_option_syntax(
        self,
        mock_runner_class,
        runner,
        tmp_path,
        mock_grid_config,
        mock_grid_result
    ):
        """Test short option syntax (-c, -o)."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("strategy_name: Test\nparameters: {}")

        mock_runner = MagicMock()
        mock_runner_class.load_config.return_value = mock_grid_config
        mock_runner_class.return_value = mock_runner
        mock_runner.generate_combinations.return_value = [MagicMock()]
        mock_runner.execute_grid_search.return_value = mock_grid_result

        result = runner.invoke(
            cli,
            [
                'grid-search',
                '-c', str(config_file),
                '-o', str(tmp_path / 'out')
            ]
        )

        assert result.exit_code == 0
        assert 'Grid Search Complete!' in result.output
