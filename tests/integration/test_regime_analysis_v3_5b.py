"""
Integration test for RegimePerformanceAnalyzer with Hierarchical_Adaptive_v3_5b.

Tests end-to-end workflow: backtest → regime tracking → CSV export.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pandas as pd
import tempfile
import shutil

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_results_dir():
    """Create temporary results directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def backtest_config(temp_results_dir):
    """Create minimal backtest config for v3.5b integration test."""
    return {
        # Time period (1 month for fast test)
        'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'end_date': datetime(2024, 1, 31, tzinfo=timezone.utc),

        # Portfolio
        'initial_capital': Decimal('100000'),
        'commission': Decimal('0.001'),
        'slippage': Decimal('0.001'),

        # Symbols (QQQ + TQQQ + PSQ + TLT + TMF + TMV for v3.5b with Treasury Overlay)
        'symbols': ['QQQ', 'TQQQ', 'PSQ', 'TLT', 'TMF', 'TMV'],

        # Data source
        'data_source': 'database',
        'timeframe': '1day',

        # Strategy
        'strategy_name': 'Hierarchical_Adaptive_v3_5b',
        'strategy_params': {
            # Symbol configuration
            'signal_symbol': 'QQQ',
            'core_long_symbol': 'QQQ',
            'leveraged_long_symbol': 'TQQQ',
            'inverse_hedge_symbol': 'PSQ',

            # Kalman filter
            'measurement_noise': Decimal('2000.0'),
            'process_noise_1': Decimal('0.01'),
            'process_noise_2': Decimal('0.01'),
            'osc_smoothness': 15,
            'strength_smoothness': 15,
            'T_max': Decimal('50.0'),

            # Trend detection (SMA-based)
            'sma_fast': 50,
            'sma_slow': 200,
            't_norm_bull_thresh': Decimal('0.3'),
            't_norm_bear_thresh': Decimal('-0.3'),

            # Volatility detection
            'realized_vol_window': 21,
            'vol_baseline_window': 126,
            'upper_thresh_z': Decimal('1.0'),
            'lower_thresh_z': Decimal('0.0'),
            'vol_crush_threshold': Decimal('-0.20'),
            'vol_crush_lookback': 5,

            # Allocation parameters
            'leverage_scalar': Decimal('1.0'),
            'use_inverse_hedge': False,
            'w_PSQ_max': Decimal('0.5'),

            # Treasury Overlay parameters
            'allow_treasury': True,
            'bond_sma_fast': 20,
            'bond_sma_slow': 60,
            'max_bond_weight': Decimal('0.4'),
            'treasury_trend_symbol': 'TLT',
            'bull_bond_symbol': 'TMF',
            'bear_bond_symbol': 'TMV',

            # Rebalancing
            'rebalance_threshold': Decimal('0.025'),
        },

        # Output
        'output_directory': temp_results_dir,
        'save_results': True,
    }


# ============================================================================
# Integration Tests
# ============================================================================

def test_regime_analysis_csv_generation(backtest_config):
    """Test full backtest with v3.5b generates regime CSV files."""
    # Create strategy instance
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])

    # Run backtest
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Verify regime CSV paths are in metrics
    assert 'regime_summary_csv' in metrics
    assert 'regime_timeseries_csv' in metrics

    # Verify files exist
    summary_path = metrics['regime_summary_csv']
    timeseries_path = metrics['regime_timeseries_csv']

    assert summary_path is not None
    assert timeseries_path is not None
    assert Path(summary_path).exists()
    assert Path(timeseries_path).exists()


def test_regime_summary_csv_content(backtest_config):
    """Test regime summary CSV has correct structure and content."""
    # Create strategy and run backtest
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Read summary CSV
    summary_path = metrics['regime_summary_csv']
    summary_df = pd.read_csv(summary_path)

    # Verify structure: 6 regime cells
    assert len(summary_df) == 6

    # Verify columns
    expected_columns = [
        'Regime', 'Trend', 'Vol', 'Days',
        'QQQ_Total_Return', 'QQQ_Daily_Avg', 'QQQ_Annualized',
        'Strategy_Total_Return', 'Strategy_Daily_Avg', 'Strategy_Annualized',
    ]
    for col in expected_columns:
        assert col in summary_df.columns, f"Missing column: {col}"

    # Verify all 6 cells present
    regime_cells = summary_df['Regime'].tolist()
    for i in range(1, 7):
        assert f'Cell_{i}' in regime_cells

    # Verify total days matches backtest period (approx 21 trading days in Jan 2024)
    total_days = summary_df['Days'].sum()
    assert total_days > 0, "No days recorded in regime analysis"
    assert total_days <= 31, "Too many days (exceeds month)"

    # Verify trend and vol states
    trend_states = summary_df['Trend'].unique()
    assert set(trend_states).issubset({'BullStrong', 'Sideways', 'BearStrong'})

    vol_states = summary_df['Vol'].unique()
    assert set(vol_states).issubset({'Low', 'High'})


def test_regime_timeseries_csv_content(backtest_config):
    """Test regime timeseries CSV has correct bar-by-bar data."""
    # Create strategy and run backtest
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Read timeseries CSV
    timeseries_path = metrics['regime_timeseries_csv']
    timeseries_df = pd.read_csv(timeseries_path)

    # Verify columns
    expected_columns = [
        'Date', 'Regime', 'Trend', 'Vol',
        'QQQ_Close', 'QQQ_Daily_Return',
        'Portfolio_Value', 'Strategy_Daily_Return',
    ]
    for col in expected_columns:
        assert col in timeseries_df.columns, f"Missing column: {col}"

    # Verify data
    assert len(timeseries_df) > 0, "No timeseries data recorded"

    # Verify QQQ prices are positive
    assert (timeseries_df['QQQ_Close'] > 0).all(), "Invalid QQQ prices"

    # Verify portfolio values are positive
    assert (timeseries_df['Portfolio_Value'] > 0).all(), "Invalid portfolio values"

    # Verify regime cells are 1-6
    regime_cells = timeseries_df['Regime'].str.extract(r'Cell_(\d+)')[0].astype(int)
    assert (regime_cells >= 1).all() and (regime_cells <= 6).all(), "Invalid regime cells"


def test_regime_normalized_returns(backtest_config):
    """Test normalized return metrics (daily avg and annualized)."""
    # Create strategy and run backtest
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Read summary CSV
    summary_path = metrics['regime_summary_csv']
    summary_df = pd.read_csv(summary_path)

    # For regimes with >0 days, verify normalized returns are calculated
    active_regimes = summary_df[summary_df['Days'] > 0]

    if len(active_regimes) > 0:
        # Check daily average exists
        assert active_regimes['QQQ_Daily_Avg'].notna().all()
        assert active_regimes['Strategy_Daily_Avg'].notna().all()

        # Check annualized exists
        assert active_regimes['QQQ_Annualized'].notna().all()
        assert active_regimes['Strategy_Annualized'].notna().all()

        # Verify relationship: annualized = daily_avg * 252
        for _, row in active_regimes.iterrows():
            expected_qqq_annual = row['QQQ_Daily_Avg'] * 252
            expected_strat_annual = row['Strategy_Daily_Avg'] * 252

            # Allow small floating point error
            assert abs(row['QQQ_Annualized'] - expected_qqq_annual) < 0.01
            assert abs(row['Strategy_Annualized'] - expected_strat_annual) < 0.01


def test_regime_analysis_only_for_v3_5b(temp_results_dir):
    """Test regime analysis only activates for v3.5b strategy."""
    from jutsu_engine.strategies.sma_crossover import SMA_Crossover

    # Create config for non-v3.5b strategy (e.g., SMA Crossover)
    config = {
        'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'end_date': datetime(2024, 1, 31, tzinfo=timezone.utc),
        'initial_capital': Decimal('100000'),
        'commission': Decimal('0.001'),
        'slippage': Decimal('0.001'),
        'symbols': ['AAPL'],
        'data_source': 'database',
        'timeframe': '1day',
        'output_directory': temp_results_dir,
        'save_results': True,
    }

    # Create strategy instance
    strategy = SMA_Crossover(short_period=20, long_period=50)

    # Run backtest
    runner = BacktestRunner(config)
    metrics = runner.run(strategy, output_dir=temp_results_dir)

    # Verify regime CSV paths are None (not generated)
    assert metrics.get('regime_summary_csv') is None
    assert metrics.get('regime_timeseries_csv') is None


def test_regime_cell_mapping_consistency(backtest_config):
    """Test regime cell mapping is consistent with v3.5b strategy."""
    # Create strategy and run backtest
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Read summary CSV
    summary_path = metrics['regime_summary_csv']
    summary_df = pd.read_csv(summary_path)

    # Verify cell mapping matches v3.5b specification:
    # Cell 1: BullStrong + Low
    # Cell 2: BullStrong + High
    # Cell 3: Sideways + Low
    # Cell 4: Sideways + High
    # Cell 5: BearStrong + Low
    # Cell 6: BearStrong + High

    cell_mapping = {
        'Cell_1': ('BullStrong', 'Low'),
        'Cell_2': ('BullStrong', 'High'),
        'Cell_3': ('Sideways', 'Low'),
        'Cell_4': ('Sideways', 'High'),
        'Cell_5': ('BearStrong', 'Low'),
        'Cell_6': ('BearStrong', 'High'),
    }

    for regime, (expected_trend, expected_vol) in cell_mapping.items():
        row = summary_df[summary_df['Regime'] == regime].iloc[0]
        assert row['Trend'] == expected_trend, f"{regime}: Expected trend={expected_trend}, got {row['Trend']}"
        assert row['Vol'] == expected_vol, f"{regime}: Expected vol={expected_vol}, got {row['Vol']}"


def test_regime_csv_filenames(backtest_config):
    """Test regime CSV filenames follow naming convention."""
    # Create strategy and run backtest
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    summary_path = metrics['regime_summary_csv']
    timeseries_path = metrics['regime_timeseries_csv']

    # Verify filename format: regime_<type>_v3_5b_<strategy>_<dates>.csv
    assert 'regime_summary' in summary_path
    assert 'regime_timeseries' in timeseries_path
    assert 'v3_5b' in summary_path
    assert 'v3_5b' in timeseries_path
    assert '20240101_20240131' in summary_path  # Date range
    assert '20240101_20240131' in timeseries_path


# ============================================================================
# Edge Case Tests
# ============================================================================

@pytest.mark.skip(reason="Requires specific market data for regime transitions")
def test_regime_transitions():
    """Test regime transitions are captured correctly in timeseries."""
    # This test would require specific market data with known regime transitions
    # Skipped for now as it depends on database content
    pass


@pytest.mark.skip(reason="Requires extended backtest period")
def test_all_regimes_visited():
    """Test that strategy visits all 6 regime cells during backtest."""
    # This would require a longer backtest period to ensure all regimes are visited
    # Skipped for now to keep tests fast
    pass


# ============================================================================
# Treasury Overlay Tests
# ============================================================================

def test_treasury_overlay_enabled(backtest_config):
    """Test v3.5b backtest with Treasury Overlay enabled."""
    # Create strategy instance with Treasury Overlay
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])

    # Run backtest
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Verify backtest completes successfully
    assert 'total_return' in metrics
    assert 'sharpe_ratio' in metrics

    # Verify strategy used Treasury Overlay
    assert strategy.allow_treasury is True
    assert strategy.bond_sma_fast == 20
    assert strategy.bond_sma_slow == 60
    assert strategy.max_bond_weight == Decimal('0.4')


def test_treasury_overlay_disabled(temp_results_dir):
    """Test v3.5b backtest with Treasury Overlay disabled (backwards compatibility)."""
    # Create config with Treasury Overlay disabled
    config = {
        'start_date': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'end_date': datetime(2024, 1, 31, tzinfo=timezone.utc),
        'initial_capital': Decimal('100000'),
        'commission': Decimal('0.001'),
        'slippage': Decimal('0.001'),
        'symbols': ['QQQ', 'TQQQ', 'PSQ'],  # No bond symbols needed
        'data_source': 'database',
        'timeframe': '1day',
        'strategy_name': 'Hierarchical_Adaptive_v3_5b',
        'strategy_params': {
            'signal_symbol': 'QQQ',
            'core_long_symbol': 'QQQ',
            'leveraged_long_symbol': 'TQQQ',
            'inverse_hedge_symbol': 'PSQ',
            'measurement_noise': Decimal('2000.0'),
            'process_noise_1': Decimal('0.01'),
            'process_noise_2': Decimal('0.01'),
            'osc_smoothness': 15,
            'strength_smoothness': 15,
            'T_max': Decimal('50.0'),
            'sma_fast': 50,
            'sma_slow': 200,
            't_norm_bull_thresh': Decimal('0.3'),
            't_norm_bear_thresh': Decimal('-0.3'),
            'realized_vol_window': 21,
            'vol_baseline_window': 126,
            'upper_thresh_z': Decimal('1.0'),
            'lower_thresh_z': Decimal('0.0'),
            'vol_crush_threshold': Decimal('-0.20'),
            'vol_crush_lookback': 5,
            'leverage_scalar': Decimal('1.0'),
            'use_inverse_hedge': False,
            'w_PSQ_max': Decimal('0.5'),
            'allow_treasury': False,  # Disable Treasury Overlay
            'rebalance_threshold': Decimal('0.025'),
        },
        'output_directory': temp_results_dir,
        'save_results': True,
    }

    # Create strategy instance
    strategy = Hierarchical_Adaptive_v3_5b(**config['strategy_params'])

    # Run backtest
    runner = BacktestRunner(config)
    metrics = runner.run(strategy, output_dir=temp_results_dir)

    # Verify backtest completes successfully
    assert 'total_return' in metrics
    assert 'sharpe_ratio' in metrics

    # Verify Treasury Overlay is disabled
    assert strategy.allow_treasury is False


def test_treasury_overlay_bond_allocation_tracking(backtest_config):
    """Test that bond allocations are tracked during backtest with Treasury Overlay."""
    # Create strategy instance
    strategy = Hierarchical_Adaptive_v3_5b(**backtest_config['strategy_params'])

    # Run backtest
    runner = BacktestRunner(backtest_config)
    metrics = runner.run(strategy, output_dir=backtest_config['output_directory'])

    # Verify strategy state includes bond weights
    assert hasattr(strategy, 'current_tmf_weight')
    assert hasattr(strategy, 'current_tmv_weight')

    # Verify bond weights are Decimal type
    assert isinstance(strategy.current_tmf_weight, Decimal)
    assert isinstance(strategy.current_tmv_weight, Decimal)

    # Verify bond weights are within valid range [0, max_bond_weight]
    assert Decimal("0") <= strategy.current_tmf_weight <= strategy.max_bond_weight
    assert Decimal("0") <= strategy.current_tmv_weight <= strategy.max_bond_weight
