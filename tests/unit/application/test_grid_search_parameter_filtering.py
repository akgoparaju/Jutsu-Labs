"""Test grid search parameter filtering.

This test validates the fix for the 'unexpected keyword argument version' bug
where metadata parameters from YAML configs were being passed to strategy __init__.
"""
import pytest
from decimal import Decimal
import subprocess
from pathlib import Path
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b
from jutsu_engine.application.grid_search_runner import _build_strategy_params


def test_grid_search_filters_metadata_parameters():
    """Test that metadata parameters are filtered out.

    Bug Scenario: YAML config contains metadata like 'version', 'description'
    Expected: These are filtered out before strategy instantiation
    """
    # Simulate optimization params from YAML (includes metadata)
    optimization_params = {
        'T_max': 50.0,  # Real param
        'sma_slow': 140,  # Real param
        'leverage_scalar': 1.5,  # Real param
        'version': '3.5',  # Metadata - should be filtered
        'description': 'Test config',  # Metadata - should be filtered
    }

    symbol_set = {
        'signal_symbol': 'QQQ',
        'bull_symbol': 'TQQQ',
        'defense_symbol': 'PSQ'
    }

    # Build strategy params
    strategy_params = _build_strategy_params(
        Hierarchical_Adaptive_v3_5b,
        symbol_set,
        optimization_params
    )

    # Verify metadata filtered out
    assert 'version' not in strategy_params, "Metadata 'version' should be filtered"
    assert 'description' not in strategy_params, "Metadata 'description' should be filtered"

    # Verify real params present
    assert 'T_max' in strategy_params, "Real param 'T_max' should be present"
    assert 'sma_slow' in strategy_params, "Real param 'sma_slow' should be present"
    assert 'leverage_scalar' in strategy_params, "Real param 'leverage_scalar' should be present"

    # CRITICAL: Test actual strategy instantiation
    strategy = Hierarchical_Adaptive_v3_5b(**strategy_params)
    assert isinstance(strategy, Hierarchical_Adaptive_v3_5b), "Strategy should instantiate successfully"


def test_grid_search_type_conversion_with_filtering():
    """Test type conversion + filtering together.

    Validates that:
    1. Type conversion happens correctly (float -> Decimal)
    2. Filtering happens after conversion
    3. Strategy can be instantiated with converted+filtered params
    """
    optimization_params = {
        'sma_slow': 140,  # Should stay int
        'T_max': 50.0,  # Should convert to Decimal
        'use_inverse_hedge': False,  # Should stay bool
        'version': '3.5',  # Should be filtered out
        'unknown_param': 'test',  # Should be filtered out (not in signature)
    }

    symbol_set = {
        'signal_symbol': 'QQQ',
        'bull_symbol': 'TQQQ',
        'defense_symbol': 'PSQ'
    }

    strategy_params = _build_strategy_params(
        Hierarchical_Adaptive_v3_5b,
        symbol_set,
        optimization_params
    )

    # Verify types
    assert isinstance(strategy_params['sma_slow'], int), "sma_slow should be int"
    assert isinstance(strategy_params['T_max'], Decimal), "T_max should be Decimal"
    assert isinstance(strategy_params['use_inverse_hedge'], bool), "use_inverse_hedge should be bool"

    # Verify metadata filtered
    assert 'version' not in strategy_params, "'version' should be filtered"
    assert 'unknown_param' not in strategy_params, "'unknown_param' should be filtered"

    # Test instantiation works
    strategy = Hierarchical_Adaptive_v3_5b(**strategy_params)
    assert strategy.sma_slow == 140, "sma_slow should be 140"
    assert strategy.T_max == Decimal('50.0'), "T_max should be Decimal('50.0')"


def test_grid_search_only_valid_params_passed():
    """Test that only params in strategy signature are passed.

    Validates the core filtering logic:
    - Only parameters that exist in strategy.__init__ are included
    - Extra params from config are silently ignored (not passed)
    """
    optimization_params = {
        'T_max': 50.0,
        'extra_param_1': 'should_be_filtered',
        'extra_param_2': 123,
        'another_metadata': True,
    }

    symbol_set = {'signal_symbol': 'QQQ'}

    strategy_params = _build_strategy_params(
        Hierarchical_Adaptive_v3_5b,
        symbol_set,
        optimization_params
    )

    # Only T_max and signal_symbol should be present
    assert 'T_max' in strategy_params
    assert 'signal_symbol' in strategy_params
    assert 'extra_param_1' not in strategy_params
    assert 'extra_param_2' not in strategy_params
    assert 'another_metadata' not in strategy_params

    # Should instantiate without errors
    strategy = Hierarchical_Adaptive_v3_5b(**strategy_params)
    assert isinstance(strategy, Hierarchical_Adaptive_v3_5b)


def test_actual_grid_search_execution():
    """Test actual grid search execution with v3.5b config.

    User requirement: 'JUST RUN A COMMAND WITH WFO CONFIG FILE'

    This integration test runs the actual grid search command with a config
    that contains metadata parameters like 'version'. Before the fix, this
    would fail with "unexpected keyword argument 'version'".

    NOTE: This is a MINIMAL test - just verifies the command starts and doesn't
    fail with parameter errors. Full grid search would take too long for unit tests.
    """
    # Path to actual config file (relative to project root)
    project_root = Path(__file__).parent.parent.parent.parent
    config_path = project_root / "grid-configs" / "examples" / "grid_search_hierarchical_adaptive_v3_5b.yaml"

    # Verify config exists
    assert config_path.exists(), f"Config not found: {config_path}"

    # Python interpreter from venv
    python_exe = project_root / "venv" / "bin" / "python"

    # Run actual grid search with config that has metadata params
    # NOTE: Grid search doesn't have --runs option, config controls iterations
    cmd = [
        str(python_exe),
        '-m', 'jutsu_engine.cli.main',
        'grid-search',
        '--config', str(config_path),
        '--no-plot'  # Disable plotting to speed up test
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,  # Grid search may take longer
        cwd=str(project_root)
    )

    # Should complete without 'version' error
    # NOTE: We're primarily checking that it doesn't fail with parameter errors
    # Grid search might still fail for other reasons (missing data, etc.)
    assert 'unexpected keyword argument' not in result.stderr, \
        f"Still has unexpected keyword error:\n{result.stderr}"
    assert "unexpected keyword argument 'version'" not in result.stderr, \
        f"Still has version error:\n{result.stderr}"

    # If it did fail, it should NOT be due to parameter errors
    if result.returncode != 0:
        # Acceptable failures: missing data, database issues, etc.
        # NOT acceptable: parameter/argument errors
        error_lower = result.stderr.lower()
        assert 'unexpected keyword' not in error_lower, \
            f"Failed with parameter error:\n{result.stderr}"
        assert 'got an unexpected' not in error_lower, \
            f"Failed with parameter error:\n{result.stderr}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
