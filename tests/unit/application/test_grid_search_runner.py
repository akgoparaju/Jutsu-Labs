"""
Unit tests for GridSearchRunner module.

Tests configuration loading, combination generation, checkpoint functionality,
CSV generation, and error handling.
"""
import pytest
import json
import yaml
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import pandas as pd
import tempfile
import shutil

from jutsu_engine.application.grid_search_runner import (
    GridSearchRunner,
    GridSearchConfig,
    SymbolSet,
    RunConfig,
    RunResult,
    GridSearchResult
)


@pytest.fixture
def temp_dir():
    """Create temporary directory for test outputs."""
    temp = tempfile.mkdtemp()
    yield Path(temp)
    shutil.rmtree(temp)


@pytest.fixture
def sample_symbol_sets():
    """Create sample symbol sets."""
    return [
        SymbolSet(
            name="NVDA-NVDL",
            signal_symbol="NVDA",
            bull_symbol="NVDL",
            defense_symbol="NVDA"
        ),
        SymbolSet(
            name="QQQ-TQQQ",
            signal_symbol="QQQ",
            bull_symbol="TQQQ",
            defense_symbol="QQQ"
        )
    ]


@pytest.fixture
def sample_config(sample_symbol_sets):
    """Create sample grid search configuration."""
    return GridSearchConfig(
        strategy_name="MACD_Trend_v4",
        symbol_sets=sample_symbol_sets,
        base_config={
            'start_date': '2020-01-01',
            'end_date': '2023-12-31',
            'timeframe': '1D',
            'initial_capital': 100000,
            'commission': 0.01,
            'slippage': 0.0
        },
        parameters={
            'ema_period': [50, 100],
            'atr_stop_multiplier': [2.0, 3.0],
            'risk_bull': [0.02, 0.025]
        },
        max_combinations=500,
        checkpoint_interval=10
    )


@pytest.fixture
def sample_yaml_config(temp_dir, sample_symbol_sets):
    """Create sample YAML configuration file."""
    config_data = {
        'strategy': 'MACD_Trend_v4',
        'symbol_sets': [
            {
                'name': 'NVDA-NVDL',
                'signal_symbol': 'NVDA',
                'bull_symbol': 'NVDL',
                'defense_symbol': 'NVDA'
            }
        ],
        'base_config': {
            'start_date': '2020-01-01',
            'end_date': '2023-12-31',
            'timeframe': '1D',
            'initial_capital': 100000,
            'commission': 0.01,
            'slippage': 0.0
        },
        'parameters': {
            'ema_period': [50, 100],
            'atr_stop_multiplier': [2.0]
        },
        'max_combinations': 500,
        'checkpoint_interval': 10
    }

    config_file = temp_dir / "test_config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f)

    return config_file


class TestSymbolSet:
    """Test SymbolSet data class."""

    def test_creation(self):
        """Test SymbolSet creation."""
        symbol_set = SymbolSet(
            name="NVDA-NVDL",
            signal_symbol="NVDA",
            bull_symbol="NVDL",
            defense_symbol="NVDA"
        )

        assert symbol_set.name == "NVDA-NVDL"
        assert symbol_set.signal_symbol == "NVDA"
        assert symbol_set.bull_symbol == "NVDL"
        assert symbol_set.defense_symbol == "NVDA"


class TestRunConfig:
    """Test RunConfig data class."""

    def test_creation(self, sample_symbol_sets):
        """Test RunConfig creation."""
        run_config = RunConfig(
            run_id="001",
            symbol_set=sample_symbol_sets[0],
            parameters={'ema_period': 50, 'atr_stop': 2.0}
        )

        assert run_config.run_id == "001"
        assert run_config.symbol_set.name == "NVDA-NVDL"
        assert run_config.parameters == {'ema_period': 50, 'atr_stop': 2.0}

    def test_to_dict(self, sample_symbol_sets):
        """Test RunConfig to_dict flattening."""
        run_config = RunConfig(
            run_id="001",
            symbol_set=sample_symbol_sets[0],
            parameters={'ema_period': 50, 'atr_stop': 2.0}
        )

        result = run_config.to_dict()

        assert result['run_id'] == "001"
        assert result['symbol_set'] == "NVDA-NVDL"
        assert result['signal_symbol'] == "NVDA"
        assert result['bull_symbol'] == "NVDL"
        assert result['defense_symbol'] == "NVDA"
        assert result['ema_period'] == 50
        assert result['atr_stop'] == 2.0


class TestConfigurationLoading:
    """Test configuration loading and validation."""

    def test_load_valid_config(self, sample_yaml_config):
        """Test loading valid YAML configuration."""
        config = GridSearchRunner.load_config(str(sample_yaml_config))

        assert config.strategy_name == "MACD_Trend_v4"
        assert len(config.symbol_sets) == 1
        assert config.symbol_sets[0].name == "NVDA-NVDL"
        assert config.base_config['start_date'] == '2020-01-01'
        assert config.parameters['ema_period'] == [50, 100]

    def test_load_nonexistent_file(self):
        """Test loading nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            GridSearchRunner.load_config("nonexistent.yaml")

    def test_invalid_yaml(self, temp_dir):
        """Test invalid YAML raises ValueError."""
        invalid_file = temp_dir / "invalid.yaml"
        with open(invalid_file, 'w') as f:
            f.write("invalid: yaml: content: [")

        with pytest.raises(ValueError, match="Invalid YAML"):
            GridSearchRunner.load_config(str(invalid_file))

    def test_missing_required_keys(self, temp_dir):
        """Test missing required keys raises ValueError."""
        config_data = {
            'strategy': 'MACD_Trend_v4',
            # Missing symbol_sets, base_config, parameters
        }

        config_file = temp_dir / "missing_keys.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(ValueError, match="Missing required keys"):
            GridSearchRunner.load_config(str(config_file))

    def test_empty_symbol_sets(self, temp_dir):
        """Test empty symbol_sets raises ValueError."""
        config_data = {
            'strategy': 'MACD_Trend_v4',
            'symbol_sets': [],
            'base_config': {'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            'parameters': {'ema_period': [50]}
        }

        config_file = temp_dir / "empty_symbols.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(ValueError, match="At least one symbol_set required"):
            GridSearchRunner.load_config(str(config_file))

    def test_invalid_date_range(self, temp_dir):
        """Test invalid date range raises ValueError."""
        config_data = {
            'strategy': 'MACD_Trend_v4',
            'symbol_sets': [{'name': 'TEST', 'signal_symbol': 'A', 'bull_symbol': 'B', 'defense_symbol': 'A'}],
            'base_config': {
                'start_date': '2023-12-31',
                'end_date': '2020-01-01',  # End before start
                'timeframe': '1D',
                'initial_capital': 100000
            },
            'parameters': {'ema_period': [50]}
        }

        config_file = temp_dir / "invalid_dates.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(ValueError, match="Invalid date range"):
            GridSearchRunner.load_config(str(config_file))

    def test_parameters_not_list(self, temp_dir):
        """Test parameter values not being lists raises ValueError."""
        config_data = {
            'strategy': 'MACD_Trend_v4',
            'symbol_sets': [{'name': 'TEST', 'signal_symbol': 'A', 'bull_symbol': 'B', 'defense_symbol': 'A'}],
            'base_config': {'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            'parameters': {'ema_period': 50}  # Not a list
        }

        config_file = temp_dir / "param_not_list.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(ValueError, match="must be a list"):
            GridSearchRunner.load_config(str(config_file))

    def test_empty_parameter_values(self, temp_dir):
        """Test empty parameter values raises ValueError."""
        config_data = {
            'strategy': 'MACD_Trend_v4',
            'symbol_sets': [{'name': 'TEST', 'signal_symbol': 'A', 'bull_symbol': 'B', 'defense_symbol': 'A'}],
            'base_config': {'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            'parameters': {'ema_period': []}  # Empty list
        }

        config_file = temp_dir / "empty_params.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(ValueError, match="has empty values list"):
            GridSearchRunner.load_config(str(config_file))


class TestCombinationGeneration:
    """Test combination generation."""

    def test_combination_count(self, sample_config):
        """Test correct number of combinations generated."""
        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        # 2 symbol_sets × (2 ema × 2 atr × 2 risk) = 2 × 8 = 16
        assert len(combinations) == 16

    def test_unique_run_ids(self, sample_config):
        """Test all run IDs are unique."""
        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        run_ids = [c.run_id for c in combinations]
        assert len(run_ids) == len(set(run_ids))

    def test_run_id_format(self, sample_config):
        """Test run IDs are zero-padded."""
        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        # Check first and last run IDs
        assert combinations[0].run_id == "001"
        assert combinations[-1].run_id == "016"

    def test_symbol_grouping_preserved(self, sample_config):
        """Test symbol sets are properly grouped."""
        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        # First 8 should be NVDA-NVDL
        for combo in combinations[:8]:
            assert combo.symbol_set.name == "NVDA-NVDL"

        # Next 8 should be QQQ-TQQQ
        for combo in combinations[8:16]:
            assert combo.symbol_set.name == "QQQ-TQQQ"

    def test_parameter_combinations(self, sample_config):
        """Test parameter Cartesian product is correct."""
        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        # Verify all parameter combinations exist
        param_combos = set()
        for combo in combinations:
            params = combo.parameters
            param_tuple = (params['ema_period'], params['atr_stop_multiplier'], params['risk_bull'])
            param_combos.add(param_tuple)

        # Should have 2 × 2 × 2 = 8 unique parameter combinations
        assert len(param_combos) == 8

        # Check specific combinations exist
        assert (50, 2.0, 0.02) in param_combos
        assert (100, 3.0, 0.025) in param_combos

    def test_max_combinations_warning(self, sample_config, caplog):
        """Test warning when combinations exceed max."""
        # Set very low max to trigger warning
        sample_config.max_combinations = 5

        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        # Should still generate all combinations
        assert len(combinations) == 16

        # But should log warning
        assert "Generated 16 combinations" in caplog.text
        assert "max: 5" in caplog.text


class TestCheckpointFunctionality:
    """Test checkpoint save/load."""

    def test_save_checkpoint(self, temp_dir):
        """Test checkpoint save creates JSON."""
        config = GridSearchConfig(
            strategy_name="TEST",
            symbol_sets=[SymbolSet("A-B", "A", "B", "A")],
            base_config={'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            parameters={'ema': [50]}
        )

        runner = GridSearchRunner(config)
        checkpoint_file = temp_dir / "checkpoint.json"

        runner._save_checkpoint(checkpoint_file, ["001", "002", "003"])

        assert checkpoint_file.exists()

        with open(checkpoint_file) as f:
            data = json.load(f)

        assert data['completed_runs'] == ["001", "002", "003"]
        assert 'timestamp' in data

    def test_load_checkpoint_success(self, temp_dir):
        """Test checkpoint load returns correct set."""
        config = GridSearchConfig(
            strategy_name="TEST",
            symbol_sets=[SymbolSet("A-B", "A", "B", "A")],
            base_config={'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            parameters={'ema': [50]}
        )

        runner = GridSearchRunner(config)
        checkpoint_file = temp_dir / "checkpoint.json"

        # Save checkpoint
        runner._save_checkpoint(checkpoint_file, ["001", "002", "003"])

        # Load checkpoint
        completed = runner._load_checkpoint(checkpoint_file)

        assert completed == {"001", "002", "003"}

    def test_load_checkpoint_nonexistent(self, temp_dir):
        """Test loading nonexistent checkpoint returns empty set."""
        config = GridSearchConfig(
            strategy_name="TEST",
            symbol_sets=[SymbolSet("A-B", "A", "B", "A")],
            base_config={'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            parameters={'ema': [50]}
        )

        runner = GridSearchRunner(config)
        checkpoint_file = temp_dir / "nonexistent.json"

        completed = runner._load_checkpoint(checkpoint_file)

        assert completed == set()

    def test_load_corrupted_checkpoint(self, temp_dir, caplog):
        """Test corrupted checkpoint handled gracefully."""
        config = GridSearchConfig(
            strategy_name="TEST",
            symbol_sets=[SymbolSet("A-B", "A", "B", "A")],
            base_config={'start_date': '2020-01-01', 'end_date': '2023-12-31', 'timeframe': '1D', 'initial_capital': 100000},
            parameters={'ema': [50]}
        )

        runner = GridSearchRunner(config)
        checkpoint_file = temp_dir / "corrupted.json"

        # Write invalid JSON
        with open(checkpoint_file, 'w') as f:
            f.write("invalid json {")

        completed = runner._load_checkpoint(checkpoint_file)

        assert completed == set()
        assert "Checkpoint corrupted" in caplog.text


class TestCSVGeneration:
    """Test CSV generation."""

    def test_run_config_csv_schema(self, temp_dir, sample_config):
        """Test run_config.csv has correct schema."""
        runner = GridSearchRunner(sample_config)
        combinations = runner.generate_combinations()

        runner._save_run_config_csv(combinations, temp_dir)

        csv_path = temp_dir / "run_config.csv"
        assert csv_path.exists()

        df = pd.read_csv(csv_path)

        # Check columns
        expected_columns = [
            'run_id', 'symbol_set', 'signal_symbol', 'bull_symbol', 'defense_symbol',
            'ema_period', 'atr_stop_multiplier', 'risk_bull'
        ]
        assert all(col in df.columns for col in expected_columns)

        # Check row count
        assert len(df) == 16

    def test_summary_comparison_csv_schema(self, temp_dir, sample_config):
        """Test summary_comparison.csv has correct schema."""
        runner = GridSearchRunner(sample_config)

        # Create mock results
        symbol_set = sample_config.symbol_sets[0]
        run_config = RunConfig("001", symbol_set, {'ema_period': 50})

        results = [
            RunResult(
                run_config=run_config,
                metrics={
                    'final_value': 150000.0,
                    'total_return_pct': 50.0,
                    'sharpe_ratio': 2.5
                },
                output_dir=temp_dir / "run_001"
            )
        ]

        summary_df = runner._generate_summary_comparison(results, temp_dir)

        csv_path = temp_dir / "summary_comparison.csv"
        assert csv_path.exists()

        # Check columns
        assert 'run_id' in summary_df.columns
        assert 'symbol_set' in summary_df.columns
        assert 'config_summary' in summary_df.columns
        assert 'final_value' in summary_df.columns
        assert 'sharpe_ratio' in summary_df.columns


class TestErrorHandling:
    """Test error handling."""

    def test_backtest_failure_doesnt_crash(self, temp_dir, sample_config):
        """Test individual backtest failure doesn't crash grid search."""
        runner = GridSearchRunner(sample_config)

        # Create run config
        run_config = RunConfig(
            "001",
            sample_config.symbol_sets[0],
            {'ema_period': 50, 'atr_stop_multiplier': 2.0, 'risk_bull': 0.02}
        )

        # Mock BacktestRunner to raise exception
        with patch('jutsu_engine.application.grid_search_runner.BacktestRunner') as mock_runner_class:
            mock_runner_class.side_effect = Exception("Test error")

            result = runner._run_single_backtest(run_config, temp_dir)

            assert result.error is not None
            assert "Test error" in result.error
            assert result.metrics == {}

    def test_format_progress(self, sample_config):
        """Test progress message formatting."""
        runner = GridSearchRunner(sample_config)

        run_config = RunConfig(
            "001",
            sample_config.symbol_sets[0],
            {'ema_period': 50, 'atr_stop': 2.0}
        )

        msg = runner._format_progress(run_config, 5, 100)

        assert "5/100" in msg
        assert "NVDA-NVDL" in msg
        assert "ema_period:50" in msg
        assert "atr_stop:2.0" in msg


class TestIntegration:
    """Integration tests."""

    @pytest.mark.slow
    def test_small_grid_search_end_to_end(self, temp_dir, sample_yaml_config):
        """Test small grid search runs end-to-end."""
        # Note: This would require full BacktestRunner integration
        # For now, we'll skip this in unit tests and leave for integration tests
        pytest.skip("Full integration test - requires database and strategies")


class TestRunResult:
    """Test RunResult data class."""

    def test_creation_success(self, sample_config, temp_dir):
        """Test RunResult creation for successful run."""
        run_config = RunConfig(
            "001",
            sample_config.symbol_sets[0],
            {'ema_period': 50}
        )

        result = RunResult(
            run_config=run_config,
            metrics={'sharpe_ratio': 2.5},
            output_dir=temp_dir / "run_001",
            error=None
        )

        assert result.error is None
        assert result.metrics['sharpe_ratio'] == 2.5

    def test_creation_failure(self, sample_config, temp_dir):
        """Test RunResult creation for failed run."""
        run_config = RunConfig(
            "001",
            sample_config.symbol_sets[0],
            {'ema_period': 50}
        )

        result = RunResult(
            run_config=run_config,
            metrics={},
            output_dir=temp_dir / "run_001",
            error="Division by zero"
        )

        assert result.error == "Division by zero"
        assert result.metrics == {}
