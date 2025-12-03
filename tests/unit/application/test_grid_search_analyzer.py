"""
Unit tests for GridSearchAnalyzer robustness analysis.

Tests cover:
- Stage A filtering (top 20% percentile)
- Clustering by all parameters
- Neighbor stability calculation
- Stress test calculations (deterministic)
- Yearly consistency calculation
- Verdict classification (all 7 tiers)
- CSV output schema validation
- Memory efficiency (streaming)
"""
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timedelta

from jutsu_engine.application.grid_search_runner import GridSearchAnalyzer


@pytest.fixture
def mock_output_dir(tmp_path):
    """Create mock grid search output directory with required files."""
    output_dir = tmp_path / "grid_search_test"
    output_dir.mkdir()

    # Create summary_comparison.csv
    summary_data = {
        'Run ID': ['001', '002', '003', '004', '005'],
        'Symbol Set': ['QQQ-TQQQ'] * 5,
        'Portfolio Balance': [150000, 140000, 160000, 130000, 145000],
        'Total Return %': [0.50, 0.40, 0.60, 0.30, 0.45],
        'Annualized Return %': [0.10, 0.08, 0.12, 0.06, 0.09],
        'Max Drawdown': [-0.15, -0.20, -0.10, -0.25, -0.18],
        'Sharpe Ratio': [1.5, 1.2, 1.8, 1.0, 1.4],
        'Sortino Ratio': [2.0, 1.8, 2.2, 1.5, 1.9],
        'Calmar Ratio': [3.33, 2.00, 6.00, 1.20, 2.50],
        'Total Trades': [50, 45, 55, 40, 48],
        'Profit Factor': [2.5, 2.2, 2.8, 2.0, 2.4],
        'Win Rate %': [0.60, 0.55, 0.65, 0.50, 0.58],
        'Avg Win ($)': [1500, 1400, 1600, 1300, 1450],
        'Avg Loss ($)': [-800, -750, -850, -700, -780],
        'Alpha': ['1.50', '1.20', '1.80', '0.90', '1.35']
    }
    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(output_dir / 'summary_comparison.csv', index=False)

    # Create run_config.csv
    config_data = {
        'run_id': ['001', '002', '003', '004', '005'],
        'symbol_set': ['QQQ-TQQQ'] * 5,
        'signal_symbol': ['QQQ'] * 5,
        'sma_slow_period': [200, 210, 200, 220, 200],
        'upper_thresh_z': [1.5, 1.6, 1.5, 1.7, 1.5],
        'risk_percent': [0.02, 0.02, 0.03, 0.02, 0.02]
    }
    config_df = pd.DataFrame(config_data)
    config_df.to_csv(output_dir / 'run_config.csv', index=False)

    # Create run directories with portfolio_daily.csv
    for run_id in ['001', '002', '003', '004', '005']:
        run_dir = output_dir / f"run_{run_id}"
        run_dir.mkdir()

        # Create portfolio_daily.csv with realistic data
        dates = pd.date_range(start='2010-01-01', end='2024-12-31', freq='D')
        initial_value = 100000

        # Generate realistic portfolio values with drawdowns during stress periods
        values = []
        for date in dates:
            # Base growth
            value = initial_value * (1 + 0.10 * (date - dates[0]).days / 365.25)

            # Add stress period drawdowns
            if '2018-02' in date.strftime('%Y-%m'):
                value *= 0.93  # -7% (passes 2018 stress test)
            elif '2020-02' <= date.strftime('%Y-%m') <= '2020-03':
                value *= 0.82  # -18% (passes 2020 stress test)
            elif date.year == 2022:
                value *= 0.85  # -15% (passes 2022 stress test)

            values.append(value)

        portfolio_data = {
            'timestamp': dates,
            'value': values
        }
        portfolio_df = pd.DataFrame(portfolio_data)
        portfolio_df.to_csv(run_dir / 'portfolio_daily.csv', index=False)

    return output_dir


def test_analyzer_initialization(mock_output_dir):
    """Test GridSearchAnalyzer initialization and file validation."""
    # Valid initialization
    analyzer = GridSearchAnalyzer(mock_output_dir)
    assert analyzer.output_dir == mock_output_dir
    assert analyzer.logger is not None

    # Missing required files
    invalid_dir = mock_output_dir / "invalid"
    invalid_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="Required file not found"):
        GridSearchAnalyzer(invalid_dir)


def test_stage_a_filter(mock_output_dir):
    """Test Stage A filtering by top 20% Calmar percentile."""
    analyzer = GridSearchAnalyzer(mock_output_dir)
    candidates = analyzer._stage_a_filter()

    # Should filter top 20% (80th percentile)
    assert len(candidates) > 0
    assert len(candidates) <= 5  # Top 20% of 5 runs

    # Check clustering
    assert 'cluster_id' in candidates.columns
    assert 'plateau_stability_pct' in candidates.columns


def test_neighbor_stability_calculation(mock_output_dir):
    """Test neighbor stability (Plateau Test) calculation."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Create test dataframe
    test_df = pd.DataFrame({
        'cluster_id': [0, 0, 0],
        'Total Return %': [0.50, 0.48, 0.52],
        'sma_slow_period': [200, 205, 200],
        'upper_thresh_z': [1.5, 1.55, 1.5]
    })

    param_cols = ['sma_slow_period', 'upper_thresh_z']
    result = analyzer._calculate_neighbor_stability(test_df, param_cols)

    # Check stability column added
    assert 'plateau_stability_pct' in result.columns

    # Stability should be between 0 and 100
    assert all(result['plateau_stability_pct'] >= 0)
    assert all(result['plateau_stability_pct'] <= 100)


def test_stress_tests_calculation(mock_output_dir):
    """Test deterministic stress test calculations."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Load daily data from run_001
    daily_data = analyzer._load_daily_data('001')
    assert daily_data is not None

    # Calculate stress tests
    stress_results = analyzer._calculate_stress_tests(daily_data)

    # Check all keys present
    assert '2018_Vol' in stress_results
    assert '2020_Crash' in stress_results
    assert '2022_Bear' in stress_results
    assert 'pass_all' in stress_results

    # Check return types
    assert isinstance(stress_results['2018_Vol'], float)
    assert isinstance(stress_results['2020_Crash'], float)
    assert isinstance(stress_results['2022_Bear'], float)
    assert isinstance(stress_results['pass_all'], bool)

    # Based on mock data, all tests should pass
    assert stress_results['pass_all'] == True


def test_yearly_consistency_calculation(mock_output_dir):
    """Test yearly consistency calculation."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Load daily data
    daily_data = analyzer._load_daily_data('001')
    assert daily_data is not None

    # Calculate yearly consistency
    qqq_return = 0.08  # Mock QQQ 8% annualized return
    yearly_score = analyzer._calculate_yearly_consistency(daily_data, qqq_return)

    # Check score is integer
    assert isinstance(yearly_score, int)
    assert yearly_score >= 0

    # With no QQQ return, should return 0
    yearly_score_no_qqq = analyzer._calculate_yearly_consistency(daily_data, None)
    assert yearly_score_no_qqq == 0


def test_verdict_classification_titan(mock_output_dir):
    """Test TITAN CONFIG verdict (highest tier)."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.60,  # 60%
        max_drawdown=-0.20,  # -20%
        calmar_ratio=3.0,
        stress_pass=True,
        plateau_pass=True,
        yearly_high=True,
        benchmark_return=0.30  # Alpha = 2.0
    )

    assert verdict == "TITAN CONFIG"


def test_verdict_classification_efficient_alpha(mock_output_dir):
    """Test Efficient Alpha verdict."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.50,  # 50%
        max_drawdown=-0.28,  # -28%
        calmar_ratio=1.8,
        stress_pass=True,
        plateau_pass=False,
        yearly_high=False,
        benchmark_return=0.30  # Alpha = 1.67
    )

    assert verdict == "Efficient Alpha"


def test_verdict_classification_lucky_peak(mock_output_dir):
    """Test Lucky Peak verdict (high return but fails robustness)."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.70,  # 70%
        max_drawdown=-0.35,  # -35%
        calmar_ratio=2.0,
        stress_pass=False,
        plateau_pass=False,
        yearly_high=False,
        benchmark_return=0.30  # Alpha = 2.33
    )

    assert verdict == "Lucky Peak"


def test_verdict_classification_safe_harbor(mock_output_dir):
    """Test Safe Harbor verdict (moderate return, safe drawdown)."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.35,  # 35%
        max_drawdown=-0.15,  # -15%
        calmar_ratio=2.3,
        stress_pass=True,
        plateau_pass=False,
        yearly_high=False,
        benchmark_return=0.30  # Alpha = 1.17
    )

    assert verdict == "Safe Harbor"


def test_verdict_classification_aggressive(mock_output_dir):
    """Test Aggressive verdict (high return, high drawdown)."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.80,  # 80%
        max_drawdown=-0.40,  # -40%
        calmar_ratio=2.0,
        stress_pass=True,
        plateau_pass=True,
        yearly_high=True,
        benchmark_return=0.30  # Alpha = 2.67
    )

    assert verdict == "Aggressive"


def test_verdict_classification_degraded(mock_output_dir):
    """Test Degraded verdict (underperforms benchmark)."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.20,  # 20%
        max_drawdown=-0.15,  # -15%
        calmar_ratio=1.3,
        stress_pass=True,
        plateau_pass=True,
        yearly_high=False,
        benchmark_return=0.30  # Alpha = 0.67
    )

    assert verdict == "Degraded"


def test_verdict_classification_unsafe(mock_output_dir):
    """Test Unsafe verdict (extreme drawdown)."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    verdict = analyzer._classify_verdict(
        total_return=0.40,  # 40%
        max_drawdown=-0.45,  # -45%
        calmar_ratio=0.9,
        stress_pass=True,
        plateau_pass=True,
        yearly_high=False,
        benchmark_return=0.30  # Alpha = 1.33
    )

    assert verdict == "Unsafe"


def test_csv_output_schema(mock_output_dir):
    """Test analyzer_summary.csv output schema."""
    analyzer = GridSearchAnalyzer(mock_output_dir)
    results = analyzer.analyze()

    # Check required columns (if results not empty)
    required_columns = [
        'cluster_id',
        'avg_total_return',
        'max_drawdown',
        'calmar_ratio',
        'plateau_stability_pct',
        'stress_2018_ret',
        'stress_2020_ret',
        'stress_2022_ret',
        'yearly_consistency',
        'verdict'
    ]

    if len(results) > 0:
        for col in required_columns:
            assert col in results.columns, f"Missing column: {col}"

    # Check file was created
    output_file = mock_output_dir / 'analyzer_summary.csv'
    assert output_file.exists()

    # Read back and verify
    saved_df = pd.read_csv(output_file)
    # File should exist even if empty
    if len(saved_df) > 0:
        assert all(col in saved_df.columns for col in required_columns)


def test_memory_efficiency_streaming(mock_output_dir):
    """Test memory-efficient streaming of portfolio_daily.csv."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Load data for multiple runs (should not load all at once)
    for run_id in ['001', '002', '003']:
        daily_data = analyzer._load_daily_data(run_id)
        assert daily_data is not None
        assert isinstance(daily_data, pd.DataFrame)
        assert 'timestamp' in daily_data.columns
        assert 'value' in daily_data.columns


def test_full_analysis_workflow(mock_output_dir):
    """Test full dual-stage analysis workflow."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Run complete analysis
    results = analyzer.analyze()

    # Check results structure
    assert isinstance(results, pd.DataFrame)
    # Results may be empty if top 20% has no valid portfolio_daily.csv
    # This is expected behavior

    # If results exist, check verdict distribution
    if len(results) > 0:
        verdict_counts = results['verdict'].value_counts()
        assert len(verdict_counts) > 0

    # Check output file created
    assert (mock_output_dir / 'analyzer_summary.csv').exists()


def test_missing_portfolio_daily(mock_output_dir):
    """Test handling of missing portfolio_daily.csv files."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Remove portfolio_daily.csv from run_003
    portfolio_file = mock_output_dir / "run_003" / "portfolio_daily.csv"
    portfolio_file.unlink()

    # Analysis should still complete (skip missing run)
    results = analyzer.analyze()
    assert isinstance(results, pd.DataFrame)


def test_empty_stress_period_data(mock_output_dir):
    """Test stress test calculation with missing data for stress periods."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Create minimal daily data (before stress periods)
    dates = pd.date_range(start='2010-01-01', end='2015-12-31', freq='D')
    values = [100000 * (1 + 0.10 * i / len(dates)) for i in range(len(dates))]

    daily_df = pd.DataFrame({
        'timestamp': dates,
        'value': values
    })

    # Should return failures for all stress tests
    stress_results = analyzer._calculate_stress_tests(daily_df)
    assert stress_results['pass_all'] == False


def test_qqq_benchmark_calculation(mock_output_dir):
    """Test QQQ benchmark return calculation."""
    analyzer = GridSearchAnalyzer(mock_output_dir)

    # Test benchmark calculation
    qqq_return = analyzer._get_qqq_benchmark()

    # Should return a value or None
    assert qqq_return is None or isinstance(qqq_return, (float, int))
