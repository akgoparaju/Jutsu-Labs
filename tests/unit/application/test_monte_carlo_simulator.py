"""
Unit tests for Monte Carlo Simulator.

Tests bootstrap resampling algorithm, statistical analysis, and result generation.

Author: Jutsu Labs
Date: 2025-11-10
"""

import pytest
import numpy as np
import pandas as pd
from decimal import Decimal
from pathlib import Path
from jutsu_engine.application.monte_carlo_simulator import (
    MonteCarloSimulator,
    MonteCarloConfig
)


@pytest.fixture
def sample_returns():
    """Sample returns for testing (as percentages)."""
    return np.array([2.15, -1.56, 4.12, 0.89, -2.34, 5.67, 1.23, -0.78, 3.45, 0.12,
                    1.89, -1.23, 2.67, 0.45, -0.89, 3.21, 1.45, -0.67, 2.34, 0.78])


@pytest.fixture
def monte_carlo_input_csv(tmp_path, sample_returns):
    """Create sample monte_carlo_input.csv file."""
    input_file = tmp_path / "monte_carlo_input.csv"

    # Create DataFrame
    df = pd.DataFrame({
        'Portfolio_Return_Percent': sample_returns,
        'Exit_Date': ['2024-01-01'] * len(sample_returns),
        'Entry_Date': ['2024-01-01'] * len(sample_returns),
        'Symbol': ['AAPL'] * len(sample_returns),
        'OOS_Period_ID': [1] * len(sample_returns)
    })

    df.to_csv(input_file, index=False)
    return input_file


@pytest.fixture
def monte_carlo_config(tmp_path, monte_carlo_input_csv):
    """Test configuration."""
    return MonteCarloConfig(
        input_file=monte_carlo_input_csv,
        output_directory=tmp_path / "output",
        iterations=100,  # Small for fast tests
        initial_capital=Decimal('10000'),
        random_seed=42  # For reproducibility
    )


def test_monte_carlo_config_validation():
    """Test configuration validation."""
    # Valid config
    config = MonteCarloConfig(
        input_file=Path('test.csv'),
        output_directory=Path('output'),
        iterations=100,
        initial_capital=Decimal('10000')
    )
    assert config.iterations == 100

    # Invalid iterations
    with pytest.raises(ValueError, match="Iterations must be positive"):
        config = MonteCarloConfig(
            input_file=Path('test.csv'),
            output_directory=Path('output'),
            iterations=-1,
            initial_capital=Decimal('10000')
        )
        simulator = MonteCarloSimulator(config)

    # Invalid initial capital
    with pytest.raises(ValueError, match="Initial capital must be positive"):
        config = MonteCarloConfig(
            input_file=Path('test.csv'),
            output_directory=Path('output'),
            iterations=100,
            initial_capital=Decimal('-1000')
        )
        simulator = MonteCarloSimulator(config)

    # Invalid confidence level
    with pytest.raises(ValueError, match="Confidence level must be between"):
        config = MonteCarloConfig(
            input_file=Path('test.csv'),
            output_directory=Path('output'),
            iterations=100,
            initial_capital=Decimal('10000'),
            confidence_level=1.5
        )
        simulator = MonteCarloSimulator(config)


def test_monte_carlo_basic(monte_carlo_config):
    """Test basic simulation with 100 iterations."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    # Check return structure
    assert 'results_file' in results
    assert 'summary_file' in results
    assert 'analysis' in results

    # Check files were created
    assert results['results_file'].exists()
    assert results['summary_file'].exists()

    # Load and validate results CSV
    df = pd.read_csv(results['results_file'])
    assert len(df) == 100  # Should have 100 runs
    assert 'Run_ID' in df.columns
    assert 'Final_Equity' in df.columns
    assert 'Annualized_Return' in df.columns
    assert 'Max_Drawdown' in df.columns

    # Check all runs completed
    assert df['Run_ID'].nunique() == 100

    # Check values are reasonable
    assert (df['Final_Equity'] > 0).all()  # All equity values positive
    assert (df['Max_Drawdown'] >= 0).all()  # All drawdowns non-negative


def test_monte_carlo_percentiles(monte_carlo_config):
    """Test percentile calculation accuracy."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    analysis = results['analysis']
    percentiles = analysis['percentiles']

    # Check all metrics have percentiles
    assert 'Final_Equity' in percentiles
    assert 'Annualized_Return' in percentiles
    assert 'Max_Drawdown' in percentiles

    # Check all requested percentiles exist
    for p in [5, 25, 50, 75, 95]:
        assert p in percentiles['Final_Equity']

    # Check ordering: 5th < 25th < 50th < 75th < 95th
    equity_percentiles = [percentiles['Final_Equity'][p] for p in [5, 25, 50, 75, 95]]
    assert equity_percentiles == sorted(equity_percentiles), "Percentiles should be in ascending order"


def test_monte_carlo_risk_of_ruin(monte_carlo_config):
    """Test risk of ruin calculation accuracy."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    analysis = results['analysis']
    risk_of_ruin = analysis['risk_of_ruin']

    # Check all thresholds exist
    for threshold in [30, 40, 50]:
        assert threshold in risk_of_ruin

    # Check risk values are percentages (0-100)
    for threshold, risk_pct in risk_of_ruin.items():
        assert 0 <= risk_pct <= 100, f"Risk percentage should be between 0-100, got {risk_pct}"

    # Higher thresholds should have lower risk (or equal)
    # Risk of >30% loss >= Risk of >40% loss >= Risk of >50% loss
    assert risk_of_ruin[30] >= risk_of_ruin[40] >= risk_of_ruin[50]


def test_monte_carlo_confidence_intervals(monte_carlo_config):
    """Test confidence interval calculation."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    analysis = results['analysis']
    ci = analysis['confidence_intervals']

    # Check all metrics have CIs
    assert 'Final_Equity' in ci
    assert 'Annualized_Return' in ci
    assert 'Max_Drawdown' in ci

    # Check CI structure
    for metric in ci.values():
        assert 'lower' in metric
        assert 'upper' in metric
        assert metric['lower'] <= metric['upper'], "Lower bound should be <= upper bound"


def test_monte_carlo_reproducibility(monte_carlo_config):
    """Test that random seed produces consistent results."""
    # Run 1
    simulator1 = MonteCarloSimulator(monte_carlo_config)
    results1 = simulator1.run()

    # Run 2 with same seed
    simulator2 = MonteCarloSimulator(monte_carlo_config)
    results2 = simulator2.run()

    # Load both result files
    df1 = pd.read_csv(results1['results_file'])
    df2 = pd.read_csv(results2['results_file'])

    # Results should be identical
    pd.testing.assert_frame_equal(df1, df2)


def test_monte_carlo_invalid_input(tmp_path):
    """Test error handling for invalid input."""
    # Missing file
    config = MonteCarloConfig(
        input_file=tmp_path / "nonexistent.csv",
        output_directory=tmp_path / "output",
        iterations=100,
        initial_capital=Decimal('10000')
    )

    simulator = MonteCarloSimulator(config)
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        simulator.run()


def test_monte_carlo_missing_column(tmp_path):
    """Test error handling for missing required column."""
    # Create CSV without Portfolio_Return_Percent column
    input_file = tmp_path / "bad_input.csv"
    df = pd.DataFrame({
        'Wrong_Column': [1.0, 2.0, 3.0]
    })
    df.to_csv(input_file, index=False)

    config = MonteCarloConfig(
        input_file=input_file,
        output_directory=tmp_path / "output",
        iterations=100,
        initial_capital=Decimal('10000')
    )

    simulator = MonteCarloSimulator(config)
    with pytest.raises(ValueError, match="Required column 'Portfolio_Return_Percent' not found"):
        simulator.run()


def test_monte_carlo_nan_values(tmp_path):
    """Test error handling for NaN values in returns."""
    # Create CSV with NaN values
    input_file = tmp_path / "nan_input.csv"
    df = pd.DataFrame({
        'Portfolio_Return_Percent': [1.0, 2.0, np.nan, 4.0, 5.0]
    })
    df.to_csv(input_file, index=False)

    config = MonteCarloConfig(
        input_file=input_file,
        output_directory=tmp_path / "output",
        iterations=100,
        initial_capital=Decimal('10000')
    )

    simulator = MonteCarloSimulator(config)
    with pytest.raises(ValueError, match="NaN values detected"):
        simulator.run()


def test_monte_carlo_empty_input(tmp_path):
    """Test error handling for insufficient trades."""
    # Create CSV with only 5 trades (< 10 minimum)
    input_file = tmp_path / "empty_input.csv"
    df = pd.DataFrame({
        'Portfolio_Return_Percent': [1.0, 2.0, 3.0, 4.0, 5.0]
    })
    df.to_csv(input_file, index=False)

    config = MonteCarloConfig(
        input_file=input_file,
        output_directory=tmp_path / "output",
        iterations=100,
        initial_capital=Decimal('10000')
    )

    simulator = MonteCarloSimulator(config)
    with pytest.raises(ValueError, match="Need at least 10 for meaningful Monte Carlo"):
        simulator.run()


def test_monte_carlo_output_files(monte_carlo_config):
    """Test that output files are created with correct format."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    # Check results CSV
    results_df = pd.read_csv(results['results_file'])
    assert len(results_df) == 100
    assert list(results_df.columns) == ['Run_ID', 'Final_Equity', 'Annualized_Return', 'Max_Drawdown']

    # Check summary file
    with open(results['summary_file'], 'r') as f:
        summary = f.read()
        assert 'Monte Carlo Simulation Results' in summary
        assert 'Percentile Analysis' in summary
        assert 'Risk of Ruin' in summary
        assert 'Confidence Intervals' in summary
        assert 'Interpretation' in summary
        assert 'Recommendation' in summary


def test_monte_carlo_single_run_logic(monte_carlo_config):
    """Test single simulation run logic."""
    simulator = MonteCarloSimulator(monte_carlo_config)

    # Load returns
    returns, _ = simulator._load_input()

    # Run single simulation
    result = simulator._simulate_single_run(returns / 100.0, run_id=1)

    # Check result structure
    assert 'Run_ID' in result
    assert 'Final_Equity' in result
    assert 'Annualized_Return' in result
    assert 'Max_Drawdown' in result

    # Check values are reasonable
    assert result['Final_Equity'] > 0
    assert result['Max_Drawdown'] >= 0


def test_monte_carlo_load_input(monte_carlo_config):
    """Test input loading and validation."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    returns, original_equity = simulator._load_input()

    # Check returns array
    assert isinstance(returns, np.ndarray)
    assert len(returns) == 20  # Sample has 20 returns

    # Returns should be decimals (not percentages)
    assert np.abs(returns).max() < 1.0  # Should be < 1 (not percentages like 50%)

    # Check original equity was calculated
    assert original_equity is not None
    assert original_equity > 0


def test_monte_carlo_analysis_with_original_equity(monte_carlo_config):
    """Test analysis includes original result percentile ranking."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    analysis = results['analysis']

    # Should have original percentile
    assert 'original_percentile' in analysis
    assert analysis['original_percentile'] is not None

    # Percentile should be between 0 and 100
    assert 0 <= analysis['original_percentile'] <= 100


def test_monte_carlo_custom_percentiles(tmp_path, monte_carlo_input_csv):
    """Test custom percentile configuration."""
    config = MonteCarloConfig(
        input_file=monte_carlo_input_csv,
        output_directory=tmp_path / "output",
        iterations=100,
        initial_capital=Decimal('10000'),
        percentiles=[10, 50, 90],  # Custom percentiles
        random_seed=42
    )

    simulator = MonteCarloSimulator(config)
    results = simulator.run()

    analysis = results['analysis']
    percentiles = analysis['percentiles']['Final_Equity']

    # Should have exactly the requested percentiles
    assert set(percentiles.keys()) == {10, 50, 90}


def test_monte_carlo_custom_risk_thresholds(tmp_path, monte_carlo_input_csv):
    """Test custom risk threshold configuration."""
    config = MonteCarloConfig(
        input_file=monte_carlo_input_csv,
        output_directory=tmp_path / "output",
        iterations=100,
        initial_capital=Decimal('10000'),
        risk_thresholds=[20, 35, 60],  # Custom thresholds
        random_seed=42
    )

    simulator = MonteCarloSimulator(config)
    results = simulator.run()

    analysis = results['analysis']
    risk_of_ruin = analysis['risk_of_ruin']

    # Should have exactly the requested thresholds
    assert set(risk_of_ruin.keys()) == {20, 35, 60}


def test_monte_carlo_performance(monte_carlo_config):
    """Test performance target: 100 iterations should complete quickly."""
    import time

    simulator = MonteCarloSimulator(monte_carlo_config)

    start = time.time()
    results = simulator.run()
    duration = time.time() - start

    # 100 iterations should complete in under 5 seconds
    assert duration < 5.0, f"Performance issue: 100 iterations took {duration:.1f}s (expected <5s)"

    # Check duration was recorded
    assert 'duration_seconds' in results
    assert results['duration_seconds'] > 0


def test_histogram_files_created(monte_carlo_config):
    """Test that histogram PNG files are created when enabled."""
    # Ensure visualization is enabled
    monte_carlo_config.visualization_enabled = True

    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    # Check histogram files exist
    output_dir = monte_carlo_config.output_directory
    returns_histogram = output_dir / 'monte_carlo_returns_histogram.png'
    drawdown_histogram = output_dir / 'monte_carlo_drawdown_histogram.png'

    assert returns_histogram.exists(), "Returns histogram file not created"
    assert drawdown_histogram.exists(), "Drawdown histogram file not created"

    # Check file sizes are reasonable (> 0 bytes)
    assert returns_histogram.stat().st_size > 0, "Returns histogram file is empty"
    assert drawdown_histogram.stat().st_size > 0, "Drawdown histogram file is empty"


def test_histogram_disabled(monte_carlo_config):
    """Test that histograms are NOT created when disabled."""
    # Disable visualization
    monte_carlo_config.visualization_enabled = False

    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    # Check histogram files do NOT exist
    output_dir = monte_carlo_config.output_directory
    returns_histogram = output_dir / 'monte_carlo_returns_histogram.png'
    drawdown_histogram = output_dir / 'monte_carlo_drawdown_histogram.png'

    assert not returns_histogram.exists(), "Returns histogram should not be created when disabled"
    assert not drawdown_histogram.exists(), "Drawdown histogram should not be created when disabled"


def test_actual_result_calculation(monte_carlo_config):
    """Test that _calculate_actual_result matches sequential compounding."""
    simulator = MonteCarloSimulator(monte_carlo_config)

    # Load returns
    returns, _ = simulator._load_input()

    # Calculate actual result
    actual_equity, actual_dd = simulator._calculate_actual_result(returns / 100.0)

    # Manually verify sequential compounding
    equity = float(monte_carlo_config.initial_capital)
    for ret in returns / 100.0:
        equity *= (1 + ret)

    # Check final equity matches
    assert abs(float(actual_equity) - equity) < 0.01, "Actual equity calculation mismatch"

    # Check drawdown is non-negative
    assert actual_dd >= 0, "Max drawdown should be non-negative"


def test_original_result_ranking(monte_carlo_config):
    """Test that original result ranking appears in analysis."""
    simulator = MonteCarloSimulator(monte_carlo_config)
    results = simulator.run()

    analysis = results['analysis']

    # Check original_result dict exists
    assert 'original_result' in analysis
    assert analysis['original_result'] is not None

    original_result = analysis['original_result']

    # Check all required fields
    assert 'final_equity' in original_result
    assert 'annualized_return' in original_result
    assert 'max_drawdown' in original_result
    assert 'return_percentile' in original_result
    assert 'drawdown_percentile' in original_result

    # Check percentiles are valid (0-100)
    assert 0 <= original_result['return_percentile'] <= 100
    assert 0 <= original_result['drawdown_percentile'] <= 100

    # Check values are reasonable
    assert original_result['final_equity'] > 0
    assert original_result['max_drawdown'] >= 0
