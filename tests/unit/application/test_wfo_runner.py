"""
Unit tests for WFO Runner.

Tests WFO components in isolation with mocked dependencies.
"""
import pytest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import pandas as pd
from unittest.mock import Mock, patch, MagicMock

from jutsu_engine.application.wfo_runner import (
    WFORunner,
    WFOWindow,
    WindowResult,
    WFOConfigError,
    WFOWindowError,
    WFOOptimizationError,
    WFOTestingError
)


class TestWFOWindowCalculation:
    """Test WFO window date calculation."""

    def test_calculate_windows_basic(self, tmp_path):
        """Test basic window calculation."""
        # Create minimal config
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{
                'name': 'QQQ_TQQQ_VIX',
                'signal_symbol': 'QQQ',
                'bull_symbol': 'TQQQ',
                'defense_symbol': 'QQQ',
                'vix_symbol': '$VIX'
            }],
            'base_config': {
                'timeframe': '1D',
                'initial_capital': 10000
            },
            'parameters': {
                'ema_period': [100]
            },
            'walk_forward': {
                'total_start_date': '2010-01-01',
                'total_end_date': '2013-01-01',
                'window_size_years': 2.0,
                'in_sample_years': 1.5,
                'out_of_sample_years': 0.5,
                'slide_years': 0.5,
                'selection_metric': 'sharpe_ratio'
            }
        }

        # Save config
        config_path = tmp_path / "test_wfo_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        # Create runner
        runner = WFORunner(config_path=str(config_path))

        # Calculate windows
        windows = runner.calculate_windows()

        # Should have 3 windows (based on configuration)
        # Window 1: IS 2010-01-01 to 2011-07-01, OOS 2011-07-01 to 2012-01-01
        # Window 2: IS 2010-07-01 to 2012-01-01, OOS 2012-01-01 to 2012-07-01
        # Window 3: IS 2011-01-01 to 2012-07-01, OOS 2012-07-01 to 2013-01-01
        assert len(windows) == 3

        # First window
        assert windows[0].window_id == 1
        assert windows[0].is_start.year == 2010
        assert windows[0].is_start.month == 1

        # Last window
        assert windows[-1].window_id == 3
        assert windows[-1].oos_end <= datetime(2013, 1, 1)

    def test_calculate_windows_no_overlap_possible(self, tmp_path):
        """Test when no windows can fit in date range."""
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{
                'name': 'QQQ_TQQQ_VIX',
                'signal_symbol': 'QQQ',
                'bull_symbol': 'TQQQ',
                'defense_symbol': 'QQQ'
            }],
            'base_config': {
                'timeframe': '1D',
                'initial_capital': 10000
            },
            'parameters': {
                'ema_period': [100]
            },
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2020-12-31',
                'window_size_years': 3.0,  # Too large for 1-year range
                'in_sample_years': 2.5,
                'out_of_sample_years': 0.5,
                'slide_years': 0.5,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_wfo_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        with pytest.raises(WFOWindowError, match="No windows generated"):
            runner.calculate_windows()


class TestParameterSelection:
    """Test best parameter selection from grid results."""

    def test_select_best_parameters_by_sharpe(self, tmp_path):
        """Test parameter selection by Sharpe ratio."""
        # Create mock grid results
        grid_results = pd.DataFrame({
            'Run ID': ['001', '002', '003'],
            'Sharpe Ratio': [1.5, 2.3, 1.8],
            'EMA Period': [100, 150, 200],
            'Risk Bull': [0.015, 0.020, 0.025]
        })

        # Create minimal runner
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{
                'name': 'QQQ_TQQQ_VIX',
                'signal_symbol': 'QQQ',
                'bull_symbol': 'TQQQ',
                'defense_symbol': 'QQQ'
            }],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        # Select best
        best_params, metric_value = runner.select_best_parameters(
            grid_results,
            'sharpe_ratio'
        )

        # Should select run 002 (highest Sharpe)
        assert metric_value == 2.3
        assert best_params['ema_period'] == 150
        assert best_params['risk_bull'] == 0.020

    def test_select_best_parameters_filters_na(self, tmp_path):
        """Test that N/A values are filtered out."""
        grid_results = pd.DataFrame({
            'Run ID': ['001', '002', '003'],
            'Sharpe Ratio': [1.5, 'N/A', 1.8],
            'EMA Period': [100, 150, 200]
        })

        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        best_params, metric_value = runner.select_best_parameters(
            grid_results,
            'sharpe_ratio'
        )

        # Should select run 003 (1.8, skipping N/A)
        assert metric_value == 1.8
        assert best_params['ema_period'] == 200

    def test_select_best_parameters_no_valid_results(self, tmp_path):
        """Test error when all results are N/A."""
        grid_results = pd.DataFrame({
            'Run ID': ['001', '002'],
            'Sharpe Ratio': ['N/A', 'N/A'],
            'EMA Period': [100, 150]
        })

        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        with pytest.raises(WFOOptimizationError, match="No valid results"):
            runner.select_best_parameters(grid_results, 'sharpe_ratio')


class TestEquityCurveGeneration:
    """Test WFO equity curve generation."""

    def test_generate_equity_curve_positive_returns(self, tmp_path):
        """Test equity curve with positive returns."""
        trades_df = pd.DataFrame({
            'Exit_Date': ['2020-01-15', '2020-02-20', '2020-03-10'],
            'Portfolio_Return_Percent': [0.02, 0.01, 0.03]
        })

        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        initial_capital = Decimal('10000')
        equity_curve = runner.generate_equity_curve(trades_df, initial_capital)

        # Check structure
        assert len(equity_curve) == 4  # Initial + 3 trades
        assert equity_curve['Trade_Number'].iloc[0] == 0
        assert equity_curve['Trade_Number'].iloc[-1] == 3

        # Check compounding (10000 * 1.02 * 1.01 * 1.03 = 10618.06)
        expected_final = 10000 * 1.02 * 1.01 * 1.03
        assert abs(equity_curve['Equity'].iloc[-1] - expected_final) < 0.01

    def test_generate_equity_curve_with_losses(self, tmp_path):
        """Test equity curve with mixed wins/losses."""
        trades_df = pd.DataFrame({
            'Exit_Date': ['2020-01-15', '2020-02-20'],
            'Portfolio_Return_Percent': [0.05, -0.02]
        })

        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        initial_capital = Decimal('10000')
        equity_curve = runner.generate_equity_curve(trades_df, initial_capital)

        # Check compounding (10000 * 1.05 * 0.98 = 10290)
        expected_final = 10000 * 1.05 * 0.98
        assert abs(equity_curve['Equity'].iloc[-1] - expected_final) < 0.01

    def test_generate_equity_curve_chronological_sort(self, tmp_path):
        """Test that trades are sorted chronologically before processing."""
        # Create trades in wrong order
        trades_df = pd.DataFrame({
            'Exit_Date': ['2020-03-10', '2020-01-15', '2020-02-20'],  # Wrong order
            'Portfolio_Return_Percent': [0.03, 0.02, 0.01]
        })

        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        runner = WFORunner(config_path=str(config_path))

        initial_capital = Decimal('10000')
        equity_curve = runner.generate_equity_curve(trades_df, initial_capital)

        # Should be sorted correctly (01-15, 02-20, 03-10)
        # Compounding: 10000 * 1.02 * 1.01 * 1.03 = 10618.06
        expected_final = 10000 * 1.02 * 1.01 * 1.03
        assert abs(equity_curve['Equity'].iloc[-1] - expected_final) < 0.01


class TestConfigValidation:
    """Test WFO configuration validation."""

    def test_missing_walk_forward_section(self, tmp_path):
        """Test error when walk_forward section is missing."""
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D'},
            'parameters': {'ema_period': [100]}
            # Missing walk_forward
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(WFOConfigError, match="Missing required sections"):
            WFORunner(config_path=str(config_path))

    def test_invalid_window_configuration(self, tmp_path):
        """Test error when IS + OOS != window size."""
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2020-01-01',
                'total_end_date': '2021-01-01',
                'window_size_years': 3.0,
                'in_sample_years': 2.0,  # 2.0 + 0.5 = 2.5 != 3.0
                'out_of_sample_years': 0.5,
                'slide_years': 0.5,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(WFOConfigError, match="must equal window_size_years"):
            WFORunner(config_path=str(config_path))

    def test_invalid_date_format(self, tmp_path):
        """Test error with invalid date format."""
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{'name': 'Test', 'signal_symbol': 'QQQ', 'bull_symbol': 'TQQQ', 'defense_symbol': 'QQQ'}],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '01/01/2020',  # Wrong format
                'total_end_date': '2021-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "test_config.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        with pytest.raises(WFOConfigError, match="Invalid date format"):
            WFORunner(config_path=str(config_path))
