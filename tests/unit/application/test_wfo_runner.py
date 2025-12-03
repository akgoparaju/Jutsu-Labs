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


class TestSymbolNamingCompatibility:
    """Test WFO runner handles both legacy and new symbol naming conventions."""

    def test_legacy_naming_macd_strategies(self, tmp_path):
        """Test legacy naming convention (MACD v4/v5/v6: bull_symbol, defense_symbol, vix_symbol)."""
        config_data = {
            'strategy': 'MACD_Trend_v6',
            'symbol_sets': [{
                'name': 'QQQ_TQQQ_VIX',
                'signal_symbol': 'QQQ',
                'bull_symbol': 'TQQQ',        # Legacy naming
                'defense_symbol': 'QQQ',       # Legacy naming
                'vix_symbol': '$VIX'           # Legacy naming
            }],
            'base_config': {
                'timeframe': '1D',
                'initial_capital': 100000,
                'commission': 0.0,
                'slippage': 0.0005
            },
            'parameters': {
                'ema_period': [100]
            },
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

        config_path = tmp_path / "test_legacy_naming.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        # Should not raise KeyError with legacy naming
        runner = WFORunner(config_path=str(config_path))
        assert runner.config['symbol_sets'][0]['bull_symbol'] == 'TQQQ'
        assert runner.config['symbol_sets'][0]['defense_symbol'] == 'QQQ'
        assert runner.config['symbol_sets'][0]['vix_symbol'] == '$VIX'

    def test_new_naming_hierarchical_v3_5b(self, tmp_path):
        """Test new naming convention (Hierarchical v3.5b: leveraged_long_symbol, core_long_symbol, etc.)."""
        config_data = {
            'strategy': 'Hierarchical_Adaptive_v3_5b',
            'symbol_sets': [{
                'name': 'QQQ_TQQQ_PSQ_Bonds',
                'signal_symbol': 'QQQ',
                'core_long_symbol': 'QQQ',             # New naming
                'leveraged_long_symbol': 'TQQQ',       # New naming
                'inverse_hedge_symbol': 'PSQ',         # New naming
                'treasury_trend_symbol': 'TLT',        # New naming
                'bull_bond_symbol': 'TMF',             # New naming
                'bear_bond_symbol': 'TMV'              # New naming
            }],
            'base_config': {
                'timeframe': '1D',
                'initial_capital': 100000,
                'commission': 0.0,
                'slippage': 0.0005
            },
            'parameters': {
                'measurement_noise': [2000.0]
            },
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

        config_path = tmp_path / "test_new_naming.yaml"
        import yaml
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        # Should not raise KeyError with new naming
        runner = WFORunner(config_path=str(config_path))
        assert runner.config['symbol_sets'][0]['core_long_symbol'] == 'QQQ'
        assert runner.config['symbol_sets'][0]['leveraged_long_symbol'] == 'TQQQ'
        assert runner.config['symbol_sets'][0]['inverse_hedge_symbol'] == 'PSQ'
        assert runner.config['symbol_sets'][0]['treasury_trend_symbol'] == 'TLT'

    def test_symbol_list_generation_legacy(self):
        """Test symbols list generation with legacy naming."""
        # This tests the logic in _run_oos_testing that previously caused KeyError
        symbol_set = {
            'signal_symbol': 'QQQ',
            'bull_symbol': 'TQQQ',
            'defense_symbol': 'QQQ',
            'vix_symbol': '$VIX'
        }

        # Replicate the symbol list generation logic from wfo_runner.py
        symbols = [symbol_set['signal_symbol']]  # Always required

        # Add leveraged/bull symbol (handles both naming conventions)
        if 'leveraged_long_symbol' in symbol_set:
            symbols.append(symbol_set['leveraged_long_symbol'])
        elif 'bull_symbol' in symbol_set:
            symbols.append(symbol_set['bull_symbol'])

        # Add core/defense symbol (handles both naming conventions)
        if 'core_long_symbol' in symbol_set:
            symbols.append(symbol_set['core_long_symbol'])
        elif 'defense_symbol' in symbol_set:
            symbols.append(symbol_set['defense_symbol'])

        # Add optional VIX symbol (legacy strategies)
        if symbol_set.get('vix_symbol'):
            symbols.append(symbol_set['vix_symbol'])

        # Should have QQQ, TQQQ, QQQ, $VIX
        assert len(symbols) == 4
        assert symbols[0] == 'QQQ'
        assert symbols[1] == 'TQQQ'
        assert symbols[2] == 'QQQ'
        assert symbols[3] == '$VIX'

    def test_symbol_list_generation_new_naming(self):
        """Test symbols list generation with new naming (v3.5b)."""
        symbol_set = {
            'signal_symbol': 'QQQ',
            'leveraged_long_symbol': 'TQQQ',
            'core_long_symbol': 'QQQ',
            'inverse_hedge_symbol': 'PSQ',
            'treasury_trend_symbol': 'TLT',
            'bull_bond_symbol': 'TMF',
            'bear_bond_symbol': 'TMV'
        }

        # Replicate the symbol list generation logic from wfo_runner.py
        symbols = [symbol_set['signal_symbol']]  # Always required

        # Add leveraged/bull symbol (handles both naming conventions)
        if 'leveraged_long_symbol' in symbol_set:
            symbols.append(symbol_set['leveraged_long_symbol'])
        elif 'bull_symbol' in symbol_set:
            symbols.append(symbol_set['bull_symbol'])

        # Add core/defense symbol (handles both naming conventions)
        if 'core_long_symbol' in symbol_set:
            symbols.append(symbol_set['core_long_symbol'])
        elif 'defense_symbol' in symbol_set:
            symbols.append(symbol_set['defense_symbol'])

        # Add optional inverse hedge symbol (v3.5b only)
        if symbol_set.get('inverse_hedge_symbol'):
            symbols.append(symbol_set['inverse_hedge_symbol'])

        # Add optional treasury symbols (v3.5b Treasury Overlay)
        if symbol_set.get('treasury_trend_symbol'):
            symbols.append(symbol_set['treasury_trend_symbol'])
        if symbol_set.get('bull_bond_symbol'):
            symbols.append(symbol_set['bull_bond_symbol'])
        if symbol_set.get('bear_bond_symbol'):
            symbols.append(symbol_set['bear_bond_symbol'])

        # Should have QQQ, TQQQ, QQQ, PSQ, TLT, TMF, TMV
        assert len(symbols) == 7
        assert symbols[0] == 'QQQ'
        assert symbols[1] == 'TQQQ'
        assert symbols[2] == 'QQQ'
        assert symbols[3] == 'PSQ'
        assert symbols[4] == 'TLT'
        assert symbols[5] == 'TMF'
        assert symbols[6] == 'TMV'

    def test_symbol_list_generation_no_optional_symbols(self):
        """Test symbols list generation with only required symbols."""
        symbol_set = {
            'signal_symbol': 'QQQ',
            'leveraged_long_symbol': 'TQQQ',
            'core_long_symbol': 'QQQ'
            # No optional symbols (inverse_hedge, treasury, vix)
        }

        # Replicate the symbol list generation logic
        symbols = [symbol_set['signal_symbol']]

        if 'leveraged_long_symbol' in symbol_set:
            symbols.append(symbol_set['leveraged_long_symbol'])
        elif 'bull_symbol' in symbol_set:
            symbols.append(symbol_set['bull_symbol'])

        if 'core_long_symbol' in symbol_set:
            symbols.append(symbol_set['core_long_symbol'])
        elif 'defense_symbol' in symbol_set:
            symbols.append(symbol_set['defense_symbol'])

        # Optional symbols should not cause errors when missing
        if symbol_set.get('inverse_hedge_symbol'):
            symbols.append(symbol_set['inverse_hedge_symbol'])
        if symbol_set.get('vix_symbol'):
            symbols.append(symbol_set['vix_symbol'])

        # Should have only QQQ, TQQQ, QQQ (no optional symbols)
        assert len(symbols) == 3
        assert symbols[0] == 'QQQ'
        assert symbols[1] == 'TQQQ'
        assert symbols[2] == 'QQQ'


class TestSymbolNamingCompatibility:
    """Test WFO runner handles both legacy and new symbol naming conventions."""

    def test_new_naming_hierarchical_v3_5(self):
        """Test new naming convention (Hierarchical v3.5 - no treasury)."""
        from jutsu_engine.application.wfo_runner import _build_strategy_params
        from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5 import Hierarchical_Adaptive_v3_5

        # New naming convention (v3.5)
        new_symbols = {
            'signal_symbol': 'QQQ',
            'leveraged_long_symbol': 'TQQQ',
            'core_long_symbol': 'QQQ',
            'inverse_hedge_symbol': 'PSQ'
        }

        params_new = _build_strategy_params(
            Hierarchical_Adaptive_v3_5,
            new_symbols,
            {'measurement_noise': 2000.0}
        )

        # Verify all new symbol names are mapped correctly
        assert params_new['signal_symbol'] == 'QQQ'
        assert params_new['leveraged_long_symbol'] == 'TQQQ'
        assert params_new['core_long_symbol'] == 'QQQ'
        assert params_new['inverse_hedge_symbol'] == 'PSQ'
        assert params_new['measurement_noise'] == 2000.0

    def test_legacy_naming_macd_v6(self):
        """Test legacy naming convention (MACD v6)."""
        from jutsu_engine.application.wfo_runner import _build_strategy_params
        from jutsu_engine.strategies.MACD_Trend_v6 import MACD_Trend_v6

        # Legacy naming convention
        legacy_symbols = {
            'signal_symbol': 'QQQ',
            'bull_symbol': 'TQQQ',
            'defense_symbol': 'QQQ',
            'vix_symbol': '$VIX'
        }

        params_legacy = _build_strategy_params(
            MACD_Trend_v6,
            legacy_symbols,
            {'vix_kill_switch': 25.0}
        )

        # Verify legacy symbol names are mapped correctly
        assert params_legacy['signal_symbol'] == 'QQQ'
        assert params_legacy['bull_symbol'] == 'TQQQ'
        assert params_legacy['defense_symbol'] == 'QQQ'
        assert params_legacy['vix_symbol'] == '$VIX'
        assert params_legacy['vix_kill_switch'] == 25.0

    def test_symbol_list_generation_new_naming(self):
        """Test symbol list generation with new naming convention."""
        # Simulate the symbol list generation code from _run_oos_testing
        symbol_set = {
            'signal_symbol': 'QQQ',
            'leveraged_long_symbol': 'TQQQ',
            'core_long_symbol': 'QQQ',
            'inverse_hedge_symbol': 'PSQ',
            'treasury_trend_symbol': 'TLT',
            'bull_bond_symbol': 'TMF',
            'bear_bond_symbol': 'TMV'
        }

        symbols = [symbol_set['signal_symbol']]

        # Add leveraged/bull symbol (handles both naming conventions)
        if 'leveraged_long_symbol' in symbol_set:
            symbols.append(symbol_set['leveraged_long_symbol'])
        elif 'bull_symbol' in symbol_set:
            symbols.append(symbol_set['bull_symbol'])

        # Add core/defense symbol (handles both naming conventions)
        if 'core_long_symbol' in symbol_set:
            symbols.append(symbol_set['core_long_symbol'])
        elif 'defense_symbol' in symbol_set:
            symbols.append(symbol_set['defense_symbol'])

        # Add optional symbols
        if symbol_set.get('inverse_hedge_symbol'):
            symbols.append(symbol_set['inverse_hedge_symbol'])
        if symbol_set.get('vix_symbol'):
            symbols.append(symbol_set['vix_symbol'])
        if symbol_set.get('treasury_trend_symbol'):
            symbols.append(symbol_set['treasury_trend_symbol'])
        if symbol_set.get('bull_bond_symbol'):
            symbols.append(symbol_set['bull_bond_symbol'])
        if symbol_set.get('bear_bond_symbol'):
            symbols.append(symbol_set['bear_bond_symbol'])

        # Verify all symbols are present
        assert len(symbols) == 7
        assert 'QQQ' in symbols
        assert 'TQQQ' in symbols
        assert 'PSQ' in symbols
        assert 'TLT' in symbols
        assert 'TMF' in symbols
        assert 'TMV' in symbols

    def test_symbol_list_generation_legacy_naming(self):
        """Test symbol list generation with legacy naming convention."""
        # Simulate the symbol list generation code from _run_oos_testing
        symbol_set = {
            'signal_symbol': 'QQQ',
            'bull_symbol': 'TQQQ',
            'defense_symbol': 'QQQ',
            'vix_symbol': '$VIX'
        }

        symbols = [symbol_set['signal_symbol']]

        # Add leveraged/bull symbol (handles both naming conventions)
        if 'leveraged_long_symbol' in symbol_set:
            symbols.append(symbol_set['leveraged_long_symbol'])
        elif 'bull_symbol' in symbol_set:
            symbols.append(symbol_set['bull_symbol'])

        # Add core/defense symbol (handles both naming conventions)
        if 'core_long_symbol' in symbol_set:
            symbols.append(symbol_set['core_long_symbol'])
        elif 'defense_symbol' in symbol_set:
            symbols.append(symbol_set['defense_symbol'])

        # Add optional symbols
        if symbol_set.get('inverse_hedge_symbol'):
            symbols.append(symbol_set['inverse_hedge_symbol'])
        if symbol_set.get('vix_symbol'):
            symbols.append(symbol_set['vix_symbol'])

        # Verify all symbols are present
        assert len(symbols) == 4
        assert 'QQQ' in symbols
        assert 'TQQQ' in symbols
        assert '$VIX' in symbols

    def test_backward_compatibility_fallback(self):
        """Test that new config with old-style symbols still works via fallback."""
        from jutsu_engine.application.wfo_runner import _build_strategy_params
        from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5 import Hierarchical_Adaptive_v3_5

        # Mixed scenario: New strategy with legacy symbol names in config
        # The _build_strategy_params should map bull_symbol → leveraged_long_symbol
        mixed_symbols = {
            'signal_symbol': 'QQQ',
            'bull_symbol': 'TQQQ',          # Old name
            'defense_symbol': 'QQQ',         # Old name
        }

        params = _build_strategy_params(
            Hierarchical_Adaptive_v3_5,
            mixed_symbols,
            {}
        )

        # Strategy expects new names, _build_strategy_params should map correctly
        assert params['signal_symbol'] == 'QQQ'
        assert params['leveraged_long_symbol'] == 'TQQQ'  # Mapped from bull_symbol
        assert params['core_long_symbol'] == 'QQQ'        # Mapped from defense_symbol
