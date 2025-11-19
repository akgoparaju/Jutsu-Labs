"""
Integration tests for grid search baseline row (row 000) and alpha column.

Tests the complete workflow of:
1. Baseline calculation before grid search
2. Baseline row (000) added to summary CSV
3. Alpha column calculated for all strategy rows
4. Edge cases (no baseline data, zero returns, etc.)
"""
import os
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from jutsu_engine.application.grid_search_runner import GridSearchRunner, GridSearchConfig, SymbolSet


class TestGridSearchBaseline:
    """Integration tests for grid search baseline integration."""

    @pytest.fixture
    def sample_config(self):
        """Create minimal grid search configuration for testing."""
        return GridSearchConfig(
            strategy_name='MACD_Trend_v4',
            symbol_sets=[
                SymbolSet(
                    name='QQQ-TQQQ',
                    signal_symbol='QQQ',
                    bull_symbol='TQQQ',
                    defense_symbol='QQQ'
                )
            ],
            base_config={
                'start_date': '2023-01-01',
                'end_date': '2024-01-01',
                'timeframe': '1D',
                'initial_capital': 100000
            },
            parameters={
                'ema_period': [100],
                'atr_stop_multiplier': [3.0]
            }
        )

    @pytest.fixture
    def mock_baseline_result(self):
        """Mock baseline calculation result."""
        return {
            'baseline_symbol': 'QQQ',
            'baseline_final_value': 125000.0,
            'baseline_total_return': 0.25,  # 25% total return
            'baseline_annualized_return': 0.08  # 8% annualized
        }

    def test_format_baseline_row(self, sample_config, mock_baseline_result):
        """Test baseline row formatting matches CSV schema."""
        runner = GridSearchRunner(sample_config)

        baseline_row = runner._format_baseline_row(mock_baseline_result)

        # Verify structure
        assert baseline_row['Run ID'] == '000'
        assert baseline_row['Symbol Set'] == 'Buy & Hold QQQ'
        assert baseline_row['Portfolio Balance'] == 125000.0
        assert baseline_row['Total Return %'] == 0.25
        assert baseline_row['Annualized Return %'] == 0.08

        # Verify N/A for strategy-specific metrics
        assert baseline_row['Sharpe Ratio'] == 'N/A'
        assert baseline_row['Sortino Ratio'] == 'N/A'
        assert baseline_row['Max Drawdown'] == 'N/A'
        assert baseline_row['Win Rate %'] == 'N/A'
        assert baseline_row['Profit Factor'] == 'N/A'

        # Verify trades and alpha
        assert baseline_row['Total Trades'] == 0
        assert baseline_row['Alpha'] == '1.00'

    def test_baseline_row_column_order(self, sample_config, mock_baseline_result):
        """Test baseline row has all required columns in correct order."""
        runner = GridSearchRunner(sample_config)
        baseline_row = runner._format_baseline_row(mock_baseline_result)

        # Expected columns (matching summary CSV)
        expected_columns = [
            'Run ID', 'Symbol Set', 'Portfolio Balance',
            'Total Return %', 'Annualized Return %', 'Max Drawdown',
            'Sharpe Ratio', 'Sortino Ratio', 'Calmar Ratio',
            'Total Trades', 'Profit Factor', 'Win Rate %',
            'Avg Win ($)', 'Avg Loss ($)', 'Alpha'
        ]

        # Check all columns present
        for col in expected_columns:
            assert col in baseline_row, f"Missing column: {col}"

    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._run_single_backtest')
    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._calculate_baseline_for_grid_search')
    def test_alpha_calculation_in_strategy_rows(
        self,
        mock_calculate_baseline,
        mock_run_backtest,
        sample_config,
        mock_baseline_result,
        tmp_path
    ):
        """Test alpha column calculated correctly for strategy rows."""
        # Setup mocks
        mock_calculate_baseline.return_value = mock_baseline_result

        # Mock backtest result with 50% return (2x baseline)
        from jutsu_engine.application.grid_search_runner import RunResult, RunConfig
        mock_result = RunResult(
            run_config=RunConfig(
                run_id='001',
                symbol_set=sample_config.symbol_sets[0],
                parameters={'ema_period': 100, 'atr_stop_multiplier': 3.0}
            ),
            metrics={
                'final_value': 150000.0,
                'total_return_pct': 50.0,  # 50% (will be divided by 100 in CSV)
                'annualized_return_pct': 16.0,
                'sharpe_ratio': 2.5,
                'max_drawdown_pct': 15.0,
                'total_trades': 20,
                'win_rate_pct': 65.0,
                'profit_factor': 2.1,
                'sortino_ratio': 3.0,
                'calmar_ratio': 1.5,
                'avg_win_usd': 500.0,
                'avg_loss_usd': -300.0
            },
            output_dir=tmp_path / "run_001"
        )
        mock_run_backtest.return_value = mock_result

        # Execute grid search
        runner = GridSearchRunner(sample_config)
        result = runner.execute_grid_search(output_base=str(tmp_path))

        # Read summary CSV (dtype='str' to preserve Run ID as string)
        summary_path = result.output_dir / "summary_comparison.csv"
        df = pd.read_csv(summary_path, dtype={'Run ID': str})

        # Verify baseline row (000)
        baseline_row = df[df['Run ID'] == '000']
        assert len(baseline_row) == 1
        assert str(baseline_row['Alpha'].values[0]) == '1.0'  # pandas reads as float

        # Verify strategy row (001) has correct alpha
        strategy_row = df[df['Run ID'] == '001']
        assert len(strategy_row) == 1

        # Alpha = strategy_return / baseline_return
        # Strategy: 50% / 100 = 0.50 (decimal)
        # Baseline: 25% = 0.25 (decimal)
        # Alpha: 0.50 / 0.25 = 2.00
        assert str(strategy_row['Alpha'].values[0]) == '2.0'  # pandas reads as float

    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._run_single_backtest')
    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._calculate_baseline_for_grid_search')
    def test_grid_search_without_baseline(
        self,
        mock_calculate_baseline,
        mock_run_backtest,
        sample_config,
        tmp_path
    ):
        """Test grid search works if baseline calculation fails."""
        # Mock baseline calculation failure
        mock_calculate_baseline.return_value = None

        # Mock successful backtest
        from jutsu_engine.application.grid_search_runner import RunResult, RunConfig
        mock_result = RunResult(
            run_config=RunConfig(
                run_id='001',
                symbol_set=sample_config.symbol_sets[0],
                parameters={'ema_period': 100, 'atr_stop_multiplier': 3.0}
            ),
            metrics={
                'final_value': 150000.0,
                'total_return_pct': 50.0,
                'annualized_return_pct': 16.0,
                'sharpe_ratio': 2.5,
                'max_drawdown_pct': 15.0,
                'total_trades': 20,
                'win_rate_pct': 65.0,
                'profit_factor': 2.1,
                'sortino_ratio': 3.0,
                'calmar_ratio': 1.5,
                'avg_win_usd': 500.0,
                'avg_loss_usd': -300.0
            },
            output_dir=tmp_path / "run_001"
        )
        mock_run_backtest.return_value = mock_result

        # Execute grid search
        runner = GridSearchRunner(sample_config)
        result = runner.execute_grid_search(output_base=str(tmp_path))

        # Read summary CSV (dtype='str' to preserve Run ID as string)
        summary_path = result.output_dir / "summary_comparison.csv"
        df = pd.read_csv(summary_path, dtype={'Run ID': str})

        # Verify NO baseline row (000)
        baseline_row = df[df['Run ID'] == '000']
        assert len(baseline_row) == 0

        # Verify strategy row has alpha = 'N/A' (no baseline to compare)
        strategy_row = df[df['Run ID'] == '001']
        assert len(strategy_row) == 1
        # pandas reads 'N/A' as NaN
        import numpy as np
        assert np.isnan(strategy_row['Alpha'].values[0]) or str(strategy_row['Alpha'].values[0]) == 'N/A'

    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._run_single_backtest')
    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._calculate_baseline_for_grid_search')
    def test_baseline_with_zero_return(
        self,
        mock_calculate_baseline,
        mock_run_backtest,
        sample_config,
        tmp_path
    ):
        """Test alpha = N/A when baseline return is zero."""
        # Mock baseline with zero return
        zero_baseline = {
            'baseline_symbol': 'QQQ',
            'baseline_final_value': 100000.0,  # No gain
            'baseline_total_return': 0.0,  # 0% return
            'baseline_annualized_return': 0.0
        }
        mock_calculate_baseline.return_value = zero_baseline

        # Mock successful backtest with positive return
        from jutsu_engine.application.grid_search_runner import RunResult, RunConfig
        mock_result = RunResult(
            run_config=RunConfig(
                run_id='001',
                symbol_set=sample_config.symbol_sets[0],
                parameters={'ema_period': 100, 'atr_stop_multiplier': 3.0}
            ),
            metrics={
                'final_value': 150000.0,
                'total_return_pct': 50.0,
                'annualized_return_pct': 16.0,
                'sharpe_ratio': 2.5,
                'max_drawdown_pct': 15.0,
                'total_trades': 20,
                'win_rate_pct': 65.0,
                'profit_factor': 2.1,
                'sortino_ratio': 3.0,
                'calmar_ratio': 1.5,
                'avg_win_usd': 500.0,
                'avg_loss_usd': -300.0
            },
            output_dir=tmp_path / "run_001"
        )
        mock_run_backtest.return_value = mock_result

        # Execute grid search
        runner = GridSearchRunner(sample_config)
        result = runner.execute_grid_search(output_base=str(tmp_path))

        # Read summary CSV (dtype='str' to preserve Run ID as string)
        summary_path = result.output_dir / "summary_comparison.csv"
        df = pd.read_csv(summary_path, dtype={'Run ID': str})

        # Verify baseline row exists
        baseline_row = df[df['Run ID'] == '000']
        assert len(baseline_row) == 1
        assert baseline_row['Total Return %'].values[0] == 0.0

        # Verify strategy row has alpha = 'N/A' (cannot divide by zero)
        strategy_row = df[df['Run ID'] == '001']
        assert len(strategy_row) == 1
        # pandas reads 'N/A' as NaN
        import numpy as np
        assert np.isnan(strategy_row['Alpha'].values[0]) or str(strategy_row['Alpha'].values[0]) == 'N/A'

    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._run_single_backtest')
    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._calculate_baseline_for_grid_search')
    def test_negative_alpha_calculation(
        self,
        mock_calculate_baseline,
        mock_run_backtest,
        sample_config,
        mock_baseline_result,
        tmp_path
    ):
        """Test alpha can be negative (strategy underperforms baseline)."""
        # Mock baseline with 25% return
        mock_calculate_baseline.return_value = mock_baseline_result

        # Mock backtest with negative return (worse than baseline)
        from jutsu_engine.application.grid_search_runner import RunResult, RunConfig
        mock_result = RunResult(
            run_config=RunConfig(
                run_id='001',
                symbol_set=sample_config.symbol_sets[0],
                parameters={'ema_period': 100, 'atr_stop_multiplier': 3.0}
            ),
            metrics={
                'final_value': 90000.0,  # Lost money
                'total_return_pct': -10.0,  # -10% return
                'annualized_return_pct': -3.5,
                'sharpe_ratio': -0.5,
                'max_drawdown_pct': 25.0,
                'total_trades': 20,
                'win_rate_pct': 35.0,
                'profit_factor': 0.8,
                'sortino_ratio': -0.7,
                'calmar_ratio': -0.2,
                'avg_win_usd': 300.0,
                'avg_loss_usd': -500.0
            },
            output_dir=tmp_path / "run_001"
        )
        mock_run_backtest.return_value = mock_result

        # Execute grid search
        runner = GridSearchRunner(sample_config)
        result = runner.execute_grid_search(output_base=str(tmp_path))

        # Read summary CSV (dtype='str' to preserve Run ID as string)
        summary_path = result.output_dir / "summary_comparison.csv"
        df = pd.read_csv(summary_path, dtype={'Run ID': str})

        # Verify strategy row has negative alpha
        strategy_row = df[df['Run ID'] == '001']
        assert len(strategy_row) == 1

        # Alpha = strategy_return / baseline_return
        # Strategy: -10% / 100 = -0.10 (decimal)
        # Baseline: 25% = 0.25 (decimal)
        # Alpha: -0.10 / 0.25 = -0.40
        alpha_value = float(strategy_row['Alpha'].values[0])
        assert alpha_value < 0  # Negative alpha (underperformance)
        assert alpha_value == pytest.approx(-0.40, rel=0.01)

    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._run_single_backtest')
    @patch('jutsu_engine.application.grid_search_runner.GridSearchRunner._calculate_baseline_for_grid_search')
    def test_summary_csv_column_order_with_alpha(
        self,
        mock_calculate_baseline,
        mock_run_backtest,
        sample_config,
        mock_baseline_result,
        tmp_path
    ):
        """Test Alpha column is at the end of CSV."""
        mock_calculate_baseline.return_value = mock_baseline_result

        from jutsu_engine.application.grid_search_runner import RunResult, RunConfig
        mock_result = RunResult(
            run_config=RunConfig(
                run_id='001',
                symbol_set=sample_config.symbol_sets[0],
                parameters={'ema_period': 100, 'atr_stop_multiplier': 3.0}
            ),
            metrics={
                'final_value': 150000.0,
                'total_return_pct': 50.0,
                'annualized_return_pct': 16.0,
                'sharpe_ratio': 2.5,
                'max_drawdown_pct': 15.0,
                'total_trades': 20,
                'win_rate_pct': 65.0,
                'profit_factor': 2.1,
                'sortino_ratio': 3.0,
                'calmar_ratio': 1.5,
                'avg_win_usd': 500.0,
                'avg_loss_usd': -300.0
            },
            output_dir=tmp_path / "run_001"
        )
        mock_run_backtest.return_value = mock_result

        # Execute grid search
        runner = GridSearchRunner(sample_config)
        result = runner.execute_grid_search(output_base=str(tmp_path))

        # Read summary CSV (dtype='str' to preserve Run ID as string)
        summary_path = result.output_dir / "summary_comparison.csv"
        df = pd.read_csv(summary_path, dtype={'Run ID': str})

        # Verify Alpha is last column (after parameters)
        columns = df.columns.tolist()
        assert 'Alpha' in columns

        # Alpha should be after all standard metrics and parameters
        alpha_index = columns.index('Alpha')

        # Check that metrics come before Alpha
        metrics_columns = [
            'Run ID', 'Symbol Set', 'Portfolio Balance',
            'Total Return %', 'Annualized Return %', 'Max Drawdown',
            'Sharpe Ratio', 'Sortino Ratio', 'Calmar Ratio',
            'Total Trades', 'Profit Factor', 'Win Rate %',
            'Avg Win ($)', 'Avg Loss ($)'
        ]

        for metric in metrics_columns:
            if metric in columns:
                assert columns.index(metric) < alpha_index


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
