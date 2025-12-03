"""
Test parameter case sensitivity fix for WFO Runner.

Tests that WFO correctly preserves parameter case from strategy signatures,
specifically for Hierarchical_Adaptive_v3_5b which uses T_max (uppercase T).
"""
import pytest
import pandas as pd
from decimal import Decimal
from pathlib import Path
import tempfile
import yaml
from unittest.mock import Mock, patch
import inspect

from jutsu_engine.application.wfo_runner import WFORunner
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b


class TestParameterCasePreservation:
    """Test that WFO preserves parameter case from strategy signatures."""

    def test_parameter_case_sensitivity_hierarchical_v3_5b(self, tmp_path):
        """
        Test that T_max (uppercase) is correctly passed to Hierarchical_Adaptive_v3_5b.

        Bug: Line 529 in wfo_runner.py converted all params to lowercase,
        causing TypeError: got 't_max' instead of 'T_max'.

        Fix: Use inspect.signature() to get correct case from strategy __init__.
        """
        # Create minimal WFO config
        config = {
            'strategy': 'Hierarchical_Adaptive_v3_5b',
            'symbol_sets': [{
                'name': 'test_set',
                'signal_symbol': 'QQQ',
                'leveraged_long_symbol': 'TQQQ',
                'core_long_symbol': 'QQQ',
                'inverse_hedge_symbol': 'SQQQ',
                'treasury_trend_symbol': 'TLT',
                'bull_bond_symbol': 'TMF',
                'bear_bond_symbol': 'TMV',
            }],
            'base_config': {
                'timeframe': '1D',
                'initial_capital': 10000
            },
            'parameters': {'T_max': [50.0]},
            'walk_forward': {
                'total_start_date': '2010-01-01',
                'total_end_date': '2011-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "wfo_test.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        # Create WFORunner instance
        runner = WFORunner(config_path=str(config_path))

        # Create mock grid search results with T Max parameter (title case from grid search)
        # AND include metadata parameter 'version' that should be filtered out
        grid_results = {
            'Run ID': ['run_1', 'run_2'],
            'Sharpe Ratio': [1.5, 1.2],
            'Symbol Set': ['set1', 'set1'],
            'Measurement Noise': [2000.0, 2500.0],
            'Process Noise 1': [0.01, 0.02],
            'Process Noise 2': [0.01, 0.015],
            'Osc Smoothness': [15, 20],
            'Strength Smoothness': [15, 18],
            'T Max': [50.0, 60.0],  # Title case from grid search
            'SMA Fast': [40, 45],
            'SMA Slow': [140, 150],
            'version': ['3.5', '3.5'],  # Metadata parameter - should be filtered out
        }

        df = pd.DataFrame(grid_results)

        # Call select_best_parameters method
        best_params, metric_value = runner.select_best_parameters(
            grid_results_df=df,
            selection_metric='sharpe_ratio'
        )

        # Verify T_max (uppercase) is present, not t_max (lowercase)
        assert 'T_max' in best_params, f"Expected 'T_max' in params, got: {list(best_params.keys())}"
        assert 't_max' not in best_params, "Should not have lowercase 't_max'"

        # Verify value is correct (best Sharpe = 1.5, first row)
        assert best_params['T_max'] == 50.0

        # Verify other case-sensitive parameters
        assert 'measurement_noise' in best_params
        assert best_params['measurement_noise'] == 2000.0

        # CRITICAL: Verify metadata parameter 'version' is NOT in best_params
        assert 'version' not in best_params, "Metadata parameter 'version' should be filtered out"

        # CRITICAL: Actually instantiate the strategy to verify parameters work
        # This is the real test - if case is wrong, this will raise TypeError
        try:
            strategy = Hierarchical_Adaptive_v3_5b(
                signal_symbol='QQQ',
                leveraged_long_symbol='TQQQ',
                core_long_symbol='QQQ',
                inverse_hedge_symbol='SQQQ',
                treasury_trend_symbol='TLT',
                bull_bond_symbol='TMF',
                bear_bond_symbol='TMV',
                **best_params  # Pass all WFO parameters
            )
            # If we get here, parameters are correctly case-matched
            assert strategy.T_max == Decimal('50.0')
        except TypeError as e:
            pytest.fail(f"Strategy instantiation failed with TypeError: {e}")

    def test_case_insensitive_matching_preserves_original_case(self):
        """
        Test that case-insensitive matching works but preserves original case.

        Grid search outputs: 'T Max' (title case)
        Strategy expects: 'T_max' (camelCase with uppercase T)
        Fix should: Match 't_max' → 'T_max' via signature introspection
        """
        # Get strategy signature
        sig = inspect.signature(Hierarchical_Adaptive_v3_5b.__init__)
        params = {p for p in sig.parameters.keys() if p != 'self'}

        # Verify T_max is in signature (uppercase T)
        assert 'T_max' in params, f"Expected 'T_max' in signature, got: {params}"

        # Verify measurement_noise is in signature (lowercase)
        assert 'measurement_noise' in params

        # Create lowercase → correct case mapping (what our fix does)
        param_case_map = {p.lower(): p for p in params}

        # Test mapping works
        assert param_case_map['t_max'] == 'T_max'
        assert param_case_map['measurement_noise'] == 'measurement_noise'
        assert param_case_map['process_noise_1'] == 'process_noise_1'

    def test_all_hierarchical_v3_5b_parameters_preserved(self, tmp_path):
        """
        Test that ALL Hierarchical_Adaptive_v3_5b parameters maintain correct case.

        Comprehensive test for all 25+ parameters.
        """
        # Create minimal WFO config
        config = {
            'strategy': 'Hierarchical_Adaptive_v3_5b',
            'symbol_sets': [{
                'name': 'test_set',
                'signal_symbol': 'QQQ',
                'leveraged_long_symbol': 'TQQQ',
                'core_long_symbol': 'QQQ',
                'inverse_hedge_symbol': 'SQQQ',
                'treasury_trend_symbol': 'TLT',
                'bull_bond_symbol': 'TMF',
                'bear_bond_symbol': 'TMV',
            }],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'T_max': [50.0]},
            'walk_forward': {
                'total_start_date': '2010-01-01',
                'total_end_date': '2011-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "wfo_test.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        runner = WFORunner(config_path=str(config_path))

        # Create comprehensive grid results with ACTUAL v3.5b parameters
        # PLUS metadata parameters that should be filtered out
        grid_results = {
            'Run ID': ['run_1'],
            'Sharpe Ratio': [1.5],
            'Symbol Set': ['set1'],
            # Kalman Trend Parameters (6)
            'Measurement Noise': [2000.0],
            'Process Noise 1': [0.01],
            'Process Noise 2': [0.01],
            'Osc Smoothness': [15],
            'Strength Smoothness': [15],
            'T Max': [50.0],  # CRITICAL: Uppercase T
            # Structural Trend Parameters (4)
            'SMA Fast': [40],
            'SMA Slow': [140],
            'T Norm Bull Thresh': [0.2],
            'T Norm Bear Thresh': [-0.3],
            # Bond Trend Parameters (2)
            'Bond SMA Fast': [20],
            'Bond SMA Slow': [60],
            # Volatility Regime Parameters (5)
            'Realized Vol Window': [20],
            'Vol Baseline Window': [252],
            'Vol Crush Lookback': [20],
            'Vol Crush Threshold': [0.5],
            'Lower Thresh Z': [-1.0],
            'Upper Thresh Z': [1.5],
            # Risk Management (3)
            'W PSQ Max': [0.5],
            'Max Bond Weight': [0.3],
            'Rebalance Threshold': [0.05],
            # Feature Flags (2)
            'Allow Treasury': [True],
            'Use Inverse Hedge': [False],
            # Leverage (1)
            'Leverage Scalar': [1.0],
            # Metadata parameters (should be filtered out)
            'version': ['3.5'],
            'description': ['Comprehensive test'],
        }

        df = pd.DataFrame(grid_results)

        best_params, _ = runner.select_best_parameters(
            grid_results_df=df,
            selection_metric='sharpe_ratio'
        )

        # Verify critical case-sensitive parameters
        assert 'T_max' in best_params  # Uppercase T
        assert 't_max' not in best_params

        # Verify all ACTUAL v3.5b parameters are present (26 parameters)
        expected_params = {
            # Kalman (6)
            'measurement_noise', 'process_noise_1', 'process_noise_2',
            'osc_smoothness', 'strength_smoothness', 'T_max',
            # Structural (4)
            'sma_fast', 'sma_slow', 't_norm_bull_thresh', 't_norm_bear_thresh',
            # Bond (2)
            'bond_sma_fast', 'bond_sma_slow',
            # Volatility (6)
            'realized_vol_window', 'vol_baseline_window', 'vol_crush_lookback',
            'vol_crush_threshold', 'lower_thresh_z', 'upper_thresh_z',
            # Risk (3)
            'w_PSQ_max', 'max_bond_weight', 'rebalance_threshold',
            # Flags (2)
            'allow_treasury', 'use_inverse_hedge',
            # Leverage (1)
            'leverage_scalar',
        }

        for param in expected_params:
            assert param in best_params, f"Missing parameter: {param}"

        # Verify metadata parameters are filtered out
        assert 'version' not in best_params, "Metadata 'version' should be filtered out"
        assert 'description' not in best_params, "Metadata 'description' should be filtered out"

    def test_metadata_parameters_filtered_out(self, tmp_path):
        """
        Test that metadata parameters (version, description, author, etc.) are filtered out.

        Bug: WFO passes ALL parameters from grid-search CSV to strategy,
        including metadata parameters that strategy doesn't accept.

        Fix: Filter best_params to only include parameters in strategy signature.
        """
        # Create minimal WFO config
        config = {
            'strategy': 'Hierarchical_Adaptive_v3_5b',
            'symbol_sets': [{
                'name': 'test_set',
                'signal_symbol': 'QQQ',
                'leveraged_long_symbol': 'TQQQ',
                'core_long_symbol': 'QQQ',
                'inverse_hedge_symbol': 'SQQQ',
                'treasury_trend_symbol': 'TLT',
                'bull_bond_symbol': 'TMF',
                'bear_bond_symbol': 'TMV',
            }],
            'base_config': {
                'timeframe': '1D',
                'initial_capital': 10000
            },
            'parameters': {'T_max': [50.0]},
            'walk_forward': {
                'total_start_date': '2010-01-01',
                'total_end_date': '2011-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "wfo_test.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        runner = WFORunner(config_path=str(config_path))

        # Grid results with BOTH real strategy parameters AND metadata parameters
        grid_results = {
            'Run ID': ['run_1'],
            'Sharpe Ratio': [1.5],
            'Symbol Set': ['set1'],
            # Real strategy parameters
            'Measurement Noise': [2000.0],
            'Process Noise 1': [0.01],
            'Process Noise 2': [0.01],
            'T Max': [50.0],  # Real param
            'SMA Fast': [40],
            'SMA Slow': [140],
            # Metadata parameters (should be filtered out)
            'version': ['3.5'],
            'description': ['Test config'],
            'author': ['Test User'],
            'created_date': ['2025-11-02'],
        }

        df = pd.DataFrame(grid_results)

        best_params, _ = runner.select_best_parameters(
            grid_results_df=df,
            selection_metric='sharpe_ratio'
        )

        # Verify REAL parameters ARE present
        assert 'T_max' in best_params
        assert 'measurement_noise' in best_params
        assert 'process_noise_1' in best_params
        assert 'sma_fast' in best_params

        # Verify METADATA parameters are NOT present
        assert 'version' not in best_params, "Metadata 'version' should be filtered out"
        assert 'description' not in best_params, "Metadata 'description' should be filtered out"
        assert 'author' not in best_params, "Metadata 'author' should be filtered out"
        assert 'created_date' not in best_params, "Metadata 'created_date' should be filtered out"

        # CRITICAL: Verify strategy instantiation succeeds (no TypeError)
        try:
            strategy = Hierarchical_Adaptive_v3_5b(
                signal_symbol='QQQ',
                leveraged_long_symbol='TQQQ',
                core_long_symbol='QQQ',
                inverse_hedge_symbol='SQQQ',
                treasury_trend_symbol='TLT',
                bull_bond_symbol='TMF',
                bear_bond_symbol='TMV',
                **best_params  # Should only contain real strategy params
            )
            # If we get here, metadata was successfully filtered out
            assert strategy.T_max == Decimal('50.0')
        except TypeError as e:
            pytest.fail(f"Strategy instantiation failed - metadata not filtered: {e}")

    def test_legacy_strategy_compatibility(self, tmp_path):
        """
        Test that fix doesn't break legacy strategies (MACD, KalmanGearing).

        Legacy strategies use all lowercase parameters, should still work.
        """
        from jutsu_engine.strategies.Hierarchical_Adaptive_v2_8 import Hierarchical_Adaptive_v2_8

        # Create minimal WFO config for v2.8 (no inverse_hedge_symbol)
        config = {
            'strategy': 'Hierarchical_Adaptive_v2_8',
            'symbol_sets': [{
                'name': 'test_set',
                'signal_symbol': 'QQQ',
                'leveraged_long_symbol': 'TQQQ',
                'core_long_symbol': 'QQQ',
            }],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {'ema_period': [100]},
            'walk_forward': {
                'total_start_date': '2010-01-01',
                'total_end_date': '2011-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "wfo_test_v28.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        runner = WFORunner(config_path=str(config_path))

        # v2.8 uses lowercase parameters AND has T_max (uppercase T)!
        # This tests that case preservation works for v2.8 too
        grid_results = {
            'Run ID': ['run_1'],
            'Sharpe Ratio': [1.5],
            'Symbol Set': ['set1'],
            'Measurement Noise': [2000.0],
            'T Max': [60.0],  # v2.8 also has T_max (uppercase T)
        }

        df = pd.DataFrame(grid_results)

        best_params, _ = runner.select_best_parameters(
            grid_results_df=df,
            selection_metric='sharpe_ratio'
        )

        # Should have correct case parameters (T_max, not t_max)
        assert 'T_max' in best_params
        assert 't_max' not in best_params
        assert best_params['T_max'] == 60.0

        # Verify strategy instantiation works (legacy compatibility)
        # Note: v2.8 doesn't have inverse_hedge_symbol or ema_period
        try:
            strategy = Hierarchical_Adaptive_v2_8(
                signal_symbol='QQQ',
                leveraged_long_symbol='TQQQ',
                core_long_symbol='QQQ',
                **best_params
            )
            # Just verify strategy was created successfully
            assert strategy.signal_symbol == 'QQQ'
        except TypeError as e:
            pytest.fail(f"Legacy strategy compatibility broken: {e}")


class TestParameterTypeConversion:
    """Test that CSV Decimal values convert to expected types for strategy signatures."""

    def test_parameter_type_conversion_from_csv(self):
        """Test that CSV Decimal values convert to int/bool/Decimal per strategy signature."""
        # Simulate CSV data (all Decimals)
        best_params_csv = {
            'sma_slow': Decimal('140.0'),  # Should become int
            'realized_vol_window': Decimal('21.0'),  # Should become int
            'leverage_scalar': Decimal('1.5'),  # Should stay Decimal
            'use_inverse_hedge': Decimal('1.0'),  # Should become bool
            'allow_treasury': Decimal('0.0'),  # Should become bool (False)
        }

        # Get strategy signature
        sig = inspect.signature(Hierarchical_Adaptive_v3_5b.__init__)

        # Apply type conversion logic (copy from wfo_runner.py lines 551-561)
        for param_name in list(best_params_csv.keys()):
            if param_name in sig.parameters:
                expected_type = sig.parameters[param_name].annotation
                if expected_type == int:
                    best_params_csv[param_name] = int(best_params_csv[param_name])
                elif expected_type == bool:
                    # Handle bool conversion (Decimal(1.0) → True)
                    best_params_csv[param_name] = bool(int(best_params_csv[param_name]))
                # Decimal type passes through as-is (financial precision)

        # Validate types
        assert isinstance(best_params_csv['sma_slow'], int)
        assert best_params_csv['sma_slow'] == 140
        assert isinstance(best_params_csv['realized_vol_window'], int)
        assert best_params_csv['realized_vol_window'] == 21
        assert isinstance(best_params_csv['leverage_scalar'], Decimal)
        assert best_params_csv['leverage_scalar'] == Decimal('1.5')
        assert isinstance(best_params_csv['use_inverse_hedge'], bool)
        assert best_params_csv['use_inverse_hedge'] is True
        assert isinstance(best_params_csv['allow_treasury'], bool)
        assert best_params_csv['allow_treasury'] is False

        # CRITICAL: Test actual strategy instantiation with converted types
        strategy = Hierarchical_Adaptive_v3_5b(
            signal_symbol='QQQ',
            leveraged_long_symbol='TQQQ',
            core_long_symbol='QQQ',
            inverse_hedge_symbol='SQQQ',
            treasury_trend_symbol='TLT',
            bull_bond_symbol='TMF',
            bear_bond_symbol='TMV',
            **best_params_csv
        )

        # Verify strategy received correct types
        assert isinstance(strategy.sma_slow, int)
        assert strategy.sma_slow == 140
        assert isinstance(strategy.realized_vol_window, int)
        assert isinstance(strategy.leverage_scalar, Decimal)
        assert isinstance(strategy.use_inverse_hedge, bool)

    def test_type_conversion_prevents_slice_error(self):
        """
        Test that int type conversion prevents TypeError in strategy_base.get_closes().

        Bug: CSV Decimal → strategy arithmetic → Decimal lookback → slice error
        Fix: Convert int parameters before passing to strategy
        """
        # Simulate CSV data with lookback parameters as Decimal
        best_params = {
            'sma_slow': Decimal('140.0'),  # Will become int
            'sma_fast': Decimal('40.0'),   # Will become int
            'realized_vol_window': Decimal('21.0'),  # Will become int
            'vol_baseline_window': Decimal('126.0'),  # Will become int
        }

        # Get strategy signature and convert types
        sig = inspect.signature(Hierarchical_Adaptive_v3_5b.__init__)
        for param_name in list(best_params.keys()):
            if param_name in sig.parameters:
                expected_type = sig.parameters[param_name].annotation
                if expected_type == int:
                    best_params[param_name] = int(best_params[param_name])

        # Create strategy with converted types
        strategy = Hierarchical_Adaptive_v3_5b(
            signal_symbol='QQQ',
            leveraged_long_symbol='TQQQ',
            core_long_symbol='QQQ',
            inverse_hedge_symbol='SQQQ',
            treasury_trend_symbol='TLT',
            bull_bond_symbol='TMF',
            bear_bond_symbol='TMV',
            **best_params
        )

        # Critical: Test that lookback calculations work (int + int = int, not Decimal)
        # From Hierarchical_Adaptive_v3_5b.py:414-416
        sma_lookback = strategy.sma_slow + 10
        assert isinstance(sma_lookback, int), f"Expected int, got {type(sma_lookback)}"

        vol_lookback = strategy.vol_baseline_window + strategy.realized_vol_window
        assert isinstance(vol_lookback, int), f"Expected int, got {type(vol_lookback)}"

        # This should be an int, not Decimal (prevents slice error)
        required_lookback = max(sma_lookback, vol_lookback)
        assert isinstance(required_lookback, int), f"Expected int, got {type(required_lookback)}"

        # Verify it can be used for slicing (would fail if Decimal)
        test_list = list(range(200))
        try:
            sliced = test_list[-required_lookback:]  # This would fail if Decimal
            assert len(sliced) == required_lookback
        except TypeError as e:
            pytest.fail(f"Slice failed with int lookback: {e}")

    def test_actual_wfo_parameter_selection_with_type_conversion(self, tmp_path):
        """
        Integration test: Full WFO parameter selection with type conversion.

        Tests the COMPLETE flow:
        1. CSV → DataFrame (all Decimals)
        2. select_best_parameters() → type conversion
        3. Strategy instantiation → success (no TypeError)
        """
        # Create minimal WFO config
        config = {
            'strategy': 'Hierarchical_Adaptive_v3_5b',
            'symbol_sets': [{
                'name': 'test_set',
                'signal_symbol': 'QQQ',
                'leveraged_long_symbol': 'TQQQ',
                'core_long_symbol': 'QQQ',
                'inverse_hedge_symbol': 'SQQQ',
                'treasury_trend_symbol': 'TLT',
                'bull_bond_symbol': 'TMF',
                'bear_bond_symbol': 'TMV',
            }],
            'base_config': {'timeframe': '1D', 'initial_capital': 10000},
            'parameters': {},
            'walk_forward': {
                'total_start_date': '2010-01-01',
                'total_end_date': '2011-01-01',
                'window_size_years': 1.0,
                'in_sample_years': 0.75,
                'out_of_sample_years': 0.25,
                'slide_years': 0.25,
                'selection_metric': 'sharpe_ratio'
            }
        }

        config_path = tmp_path / "wfo_type_test.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        runner = WFORunner(config_path=str(config_path))

        # Grid results with mixed types (as they appear in CSV)
        grid_results = {
            'Run ID': ['run_1'],
            'Sharpe Ratio': [1.5],
            'Symbol Set': ['set1'],
            # Int parameters (will be Decimal from CSV)
            'SMA Fast': [Decimal('40.0')],
            'SMA Slow': [Decimal('140.0')],
            'Realized Vol Window': [Decimal('21.0')],
            'Vol Baseline Window': [Decimal('126.0')],
            'T Max': [Decimal('50.0')],
            # Decimal parameters (should stay Decimal)
            'Leverage Scalar': [Decimal('1.5')],
            'Vol Crush Threshold': [Decimal('-0.15')],
            # Bool parameters (will be Decimal from CSV)
            'Use Inverse Hedge': [Decimal('1.0')],
            'Allow Treasury': [Decimal('0.0')],
        }

        df = pd.DataFrame(grid_results)

        # Call select_best_parameters (should apply type conversion)
        best_params, _ = runner.select_best_parameters(
            grid_results_df=df,
            selection_metric='sharpe_ratio'
        )

        # Verify types after conversion
        assert isinstance(best_params['sma_fast'], int)
        assert isinstance(best_params['sma_slow'], int)
        assert isinstance(best_params['realized_vol_window'], int)
        assert isinstance(best_params['vol_baseline_window'], int)
        # T_max is Decimal in strategy signature, should stay Decimal
        assert isinstance(best_params['T_max'], Decimal)
        assert isinstance(best_params['leverage_scalar'], Decimal)
        assert isinstance(best_params['vol_crush_threshold'], Decimal)
        assert isinstance(best_params['use_inverse_hedge'], bool)
        assert isinstance(best_params['allow_treasury'], bool)

        # CRITICAL: Actually instantiate strategy (the real test)
        try:
            strategy = Hierarchical_Adaptive_v3_5b(
                signal_symbol='QQQ',
                leveraged_long_symbol='TQQQ',
                core_long_symbol='QQQ',
                inverse_hedge_symbol='SQQQ',
                treasury_trend_symbol='TLT',
                bull_bond_symbol='TMF',
                bear_bond_symbol='TMV',
                **best_params
            )

            # Verify strategy has correct types
            assert isinstance(strategy.sma_slow, int)
            assert isinstance(strategy.leverage_scalar, Decimal)
            assert isinstance(strategy.use_inverse_hedge, bool)

            # Verify lookback calculations work (int arithmetic)
            sma_lookback = strategy.sma_slow + 10
            assert isinstance(sma_lookback, int)

        except TypeError as e:
            pytest.fail(f"Strategy instantiation failed with TypeError: {e}")
