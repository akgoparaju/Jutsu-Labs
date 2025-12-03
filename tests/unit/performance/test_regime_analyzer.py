"""
Unit tests for RegimePerformanceAnalyzer.

Tests regime-specific performance tracking for Hierarchical_Adaptive_v3_5b strategy.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pandas as pd
import tempfile
import shutil

from jutsu_engine.performance.regime_analyzer import (
    RegimeBar,
    RegimePerformanceAnalyzer,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def initial_capital():
    """Initial capital for testing."""
    return Decimal('100000')


@pytest.fixture
def analyzer(initial_capital):
    """Create a RegimePerformanceAnalyzer instance."""
    return RegimePerformanceAnalyzer(initial_capital=initial_capital)


@pytest.fixture
def sample_bars():
    """Create sample bar data for testing."""
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Create 10 bars across different regimes
    bars = []

    # Cell 1: BullStrong + Low Vol (5 bars)
    for i in range(5):
        bars.append({
            'timestamp': datetime(2024, 1, i+1, tzinfo=timezone.utc),
            'regime_cell': 1,
            'trend_state': 'BullStrong',
            'vol_state': 'Low',
            'qqq_close': Decimal('400.00') + Decimal(i),  # Rising
            'portfolio_value': Decimal('100000') + Decimal(i * 1000),  # Rising
        })

    # Cell 3: Sideways + Low Vol (3 bars)
    for i in range(3):
        bars.append({
            'timestamp': datetime(2024, 1, i+6, tzinfo=timezone.utc),
            'regime_cell': 3,
            'trend_state': 'Sideways',
            'vol_state': 'Low',
            'qqq_close': Decimal('405.00'),  # Flat
            'portfolio_value': Decimal('105000') + Decimal(i * 100),  # Slight rise
        })

    # Cell 5: BearStrong + Low Vol (2 bars)
    for i in range(2):
        bars.append({
            'timestamp': datetime(2024, 1, i+9, tzinfo=timezone.utc),
            'regime_cell': 5,
            'trend_state': 'BearStrong',
            'vol_state': 'Low',
            'qqq_close': Decimal('405.00') - Decimal(i * 5),  # Falling
            'portfolio_value': Decimal('105300') + Decimal(i * 500),  # Rising (good strategy)
        })

    return bars


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for CSV tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


# ============================================================================
# RegimeBar Dataclass Tests
# ============================================================================

def test_regime_bar_creation():
    """Test RegimeBar dataclass instantiation."""
    bar = RegimeBar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('400.00'),
        qqq_return=Decimal('0.01'),
        portfolio_value=Decimal('101000'),
        strategy_return=Decimal('0.01'),
    )

    assert bar.timestamp.year == 2024
    assert bar.regime_cell == 1
    assert bar.trend_state == 'BullStrong'
    assert bar.vol_state == 'Low'
    assert bar.qqq_close == Decimal('400.00')
    assert bar.qqq_return == Decimal('0.01')
    assert bar.portfolio_value == Decimal('101000')
    assert bar.strategy_return == Decimal('0.01')


# ============================================================================
# RegimePerformanceAnalyzer Initialization Tests
# ============================================================================

def test_analyzer_initialization(initial_capital):
    """Test analyzer initialization."""
    analyzer = RegimePerformanceAnalyzer(initial_capital=initial_capital)

    assert analyzer._initial_capital == initial_capital
    assert len(analyzer._bars) == 0
    assert analyzer._last_qqq_close is None
    assert analyzer._last_portfolio_value is None


# ============================================================================
# record_bar() Tests
# ============================================================================

def test_record_bar_first_bar(analyzer):
    """Test recording first bar (zero returns)."""
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('400.00'),
        portfolio_value=Decimal('100000'),
    )

    assert len(analyzer._bars) == 1
    bar = analyzer._bars[0]

    assert bar.qqq_return == Decimal('0')  # First bar = 0 return
    assert bar.strategy_return == Decimal('0')  # First bar = 0 return
    assert analyzer._last_qqq_close == Decimal('400.00')
    assert analyzer._last_portfolio_value == Decimal('100000')


def test_record_bar_subsequent_bars(analyzer):
    """Test recording subsequent bars (calculated returns)."""
    # First bar
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('400.00'),
        portfolio_value=Decimal('100000'),
    )

    # Second bar (QQQ up 1%, Portfolio up 1.5%)
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('404.00'),  # +1%
        portfolio_value=Decimal('101500'),  # +1.5%
    )

    assert len(analyzer._bars) == 2
    bar2 = analyzer._bars[1]

    # QQQ return: (404 - 400) / 400 = 0.01
    expected_qqq_return = (Decimal('404.00') - Decimal('400.00')) / Decimal('400.00')
    assert bar2.qqq_return == expected_qqq_return

    # Strategy return: (101500 - 100000) / 100000 = 0.015
    expected_strat_return = (Decimal('101500') - Decimal('100000')) / Decimal('100000')
    assert bar2.strategy_return == expected_strat_return


def test_record_bar_multiple_regimes(analyzer, sample_bars):
    """Test recording bars across multiple regimes."""
    for bar_data in sample_bars:
        analyzer.record_bar(**bar_data)

    assert len(analyzer._bars) == len(sample_bars)

    # Verify regime cells are tracked
    regime_cells = [bar.regime_cell for bar in analyzer._bars]
    assert 1 in regime_cells  # BullStrong + Low
    assert 3 in regime_cells  # Sideways + Low
    assert 5 in regime_cells  # BearStrong + Low


# ============================================================================
# generate_summary() Tests
# ============================================================================

def test_generate_summary_empty(analyzer):
    """Test summary generation with no bars."""
    summary = analyzer.generate_summary()

    assert isinstance(summary, pd.DataFrame)
    assert len(summary) == 0


def test_generate_summary_single_regime(analyzer):
    """Test summary generation with single regime."""
    # Add 3 bars in Cell 1
    for i in range(3):
        analyzer.record_bar(
            timestamp=datetime(2024, 1, i+1, tzinfo=timezone.utc),
            regime_cell=1,
            trend_state='BullStrong',
            vol_state='Low',
            qqq_close=Decimal('400.00') + Decimal(i),
            portfolio_value=Decimal('100000') + Decimal(i * 1000),
        )

    summary = analyzer.generate_summary()

    assert len(summary) == 6  # Always 6 cells (some may be 0 days)

    # Find Cell 1 data
    cell1 = summary[summary['Regime'] == 'Cell_1'].iloc[0]

    assert cell1['Days'] == 3
    assert cell1['Trend'] == 'BullStrong'
    assert cell1['Vol'] == 'Low'


def test_generate_summary_multiple_regimes(analyzer, sample_bars):
    """Test summary generation with multiple regimes."""
    for bar_data in sample_bars:
        analyzer.record_bar(**bar_data)

    summary = analyzer.generate_summary()

    assert len(summary) == 6  # All 6 regime cells

    # Check Cell 1 (BullStrong + Low) - 5 bars
    cell1 = summary[summary['Regime'] == 'Cell_1'].iloc[0]
    assert cell1['Days'] == 5
    assert cell1['Trend'] == 'BullStrong'
    assert cell1['Vol'] == 'Low'

    # Check Cell 3 (Sideways + Low) - 3 bars
    cell3 = summary[summary['Regime'] == 'Cell_3'].iloc[0]
    assert cell3['Days'] == 3
    assert cell3['Trend'] == 'Sideways'
    assert cell3['Vol'] == 'Low'

    # Check Cell 5 (BearStrong + Low) - 2 bars
    cell5 = summary[summary['Regime'] == 'Cell_5'].iloc[0]
    assert cell5['Days'] == 2
    assert cell5['Trend'] == 'BearStrong'
    assert cell5['Vol'] == 'Low'

    # Check unused cells have 0 days
    cell2 = summary[summary['Regime'] == 'Cell_2'].iloc[0]
    assert cell2['Days'] == 0


def test_generate_summary_return_metrics(analyzer):
    """Test return metric calculations in summary."""
    # Add bars with known returns
    # Bar 1: QQQ=400, Portfolio=100000 (baseline)
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('400.00'),
        portfolio_value=Decimal('100000'),
    )

    # Bar 2: QQQ=404 (+1%), Portfolio=101000 (+1%)
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('404.00'),
        portfolio_value=Decimal('101000'),
    )

    # Bar 3: QQQ=408.04 (+1% from 404), Portfolio=102010 (+1% from 101000)
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('408.04'),
        portfolio_value=Decimal('102010'),
    )

    summary = analyzer.generate_summary()
    cell1 = summary[summary['Regime'] == 'Cell_1'].iloc[0]

    # QQQ total return: (1 + 0) * (1 + 0.01) * (1 + 0.01) - 1 ≈ 0.0201
    # Strategy total return: same
    # Daily avg: total / 3 days
    # Annualized: daily_avg * 252

    assert cell1['Days'] == 3
    assert 'QQQ_Total_Return' in summary.columns
    assert 'QQQ_Daily_Avg' in summary.columns
    assert 'QQQ_Annualized' in summary.columns
    assert 'Strategy_Total_Return' in summary.columns
    assert 'Strategy_Daily_Avg' in summary.columns
    assert 'Strategy_Annualized' in summary.columns


# ============================================================================
# generate_timeseries() Tests
# ============================================================================

def test_generate_timeseries_empty(analyzer):
    """Test timeseries generation with no bars."""
    timeseries = analyzer.generate_timeseries()

    assert isinstance(timeseries, pd.DataFrame)
    assert len(timeseries) == 0


def test_generate_timeseries_format(analyzer, sample_bars):
    """Test timeseries output format."""
    for bar_data in sample_bars:
        analyzer.record_bar(**bar_data)

    timeseries = analyzer.generate_timeseries()

    assert len(timeseries) == len(sample_bars)

    # Check columns
    expected_columns = [
        'Date', 'Regime', 'Trend', 'Vol',
        'QQQ_Close', 'QQQ_Daily_Return',
        'Portfolio_Value', 'Strategy_Daily_Return'
    ]
    for col in expected_columns:
        assert col in timeseries.columns

    # Check first row
    row1 = timeseries.iloc[0]
    assert row1['Regime'] == 'Cell_1'
    assert row1['Trend'] == 'BullStrong'
    assert row1['Vol'] == 'Low'


# ============================================================================
# export_csv() Tests
# ============================================================================

def test_export_csv_creates_files(analyzer, sample_bars, temp_output_dir):
    """Test CSV export creates both files."""
    for bar_data in sample_bars:
        analyzer.record_bar(**bar_data)

    summary_path, timeseries_path = analyzer.export_csv(
        strategy_name='Hierarchical_Adaptive_v3_5b',
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        output_dir=temp_output_dir
    )

    # Check files exist
    assert Path(summary_path).exists()
    assert Path(timeseries_path).exists()

    # Check filenames
    assert 'regime_summary' in summary_path
    assert 'regime_timeseries' in timeseries_path
    assert '20240101_20240110' in summary_path


def test_export_csv_summary_content(analyzer, sample_bars, temp_output_dir):
    """Test summary CSV content."""
    for bar_data in sample_bars:
        analyzer.record_bar(**bar_data)

    summary_path, _ = analyzer.export_csv(
        strategy_name='Test_Strategy',
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        output_dir=temp_output_dir
    )

    # Read CSV
    summary_df = pd.read_csv(summary_path)

    assert len(summary_df) == 6  # All 6 regime cells
    assert 'Regime' in summary_df.columns
    assert 'Days' in summary_df.columns

    # Check Cell 1 has 5 days
    cell1 = summary_df[summary_df['Regime'] == 'Cell_1'].iloc[0]
    assert cell1['Days'] == 5


def test_export_csv_timeseries_content(analyzer, sample_bars, temp_output_dir):
    """Test timeseries CSV content."""
    for bar_data in sample_bars:
        analyzer.record_bar(**bar_data)

    _, timeseries_path = analyzer.export_csv(
        strategy_name='Test_Strategy',
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
        output_dir=temp_output_dir
    )

    # Read CSV
    timeseries_df = pd.read_csv(timeseries_path)

    assert len(timeseries_df) == len(sample_bars)
    assert 'Date' in timeseries_df.columns
    assert 'Regime' in timeseries_df.columns
    assert 'QQQ_Close' in timeseries_df.columns
    assert 'Portfolio_Value' in timeseries_df.columns


# ============================================================================
# Edge Case Tests
# ============================================================================

def test_analyzer_with_zero_days_in_regime(analyzer):
    """Test analyzer handles regimes with 0 days correctly."""
    # Only add bars for Cell 1
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        regime_cell=1,
        trend_state='BullStrong',
        vol_state='Low',
        qqq_close=Decimal('400.00'),
        portfolio_value=Decimal('100000'),
    )

    summary = analyzer.generate_summary()

    # All 6 cells should be present
    assert len(summary) == 6

    # Cell 1 should have 1 day
    cell1 = summary[summary['Regime'] == 'Cell_1'].iloc[0]
    assert cell1['Days'] == 1

    # Other cells should have 0 days
    cell2 = summary[summary['Regime'] == 'Cell_2'].iloc[0]
    assert cell2['Days'] == 0
    assert cell2['QQQ_Total_Return'] == 0.0


def test_get_trend_for_cell():
    """Test trend state mapping for each cell."""
    assert RegimePerformanceAnalyzer._get_trend_for_cell(1) == "BullStrong"
    assert RegimePerformanceAnalyzer._get_trend_for_cell(2) == "BullStrong"
    assert RegimePerformanceAnalyzer._get_trend_for_cell(3) == "Sideways"
    assert RegimePerformanceAnalyzer._get_trend_for_cell(4) == "Sideways"
    assert RegimePerformanceAnalyzer._get_trend_for_cell(5) == "BearStrong"
    assert RegimePerformanceAnalyzer._get_trend_for_cell(6) == "BearStrong"


def test_get_vol_for_cell():
    """Test volatility state mapping for each cell."""
    assert RegimePerformanceAnalyzer._get_vol_for_cell(1) == "Low"
    assert RegimePerformanceAnalyzer._get_vol_for_cell(2) == "High"
    assert RegimePerformanceAnalyzer._get_vol_for_cell(3) == "Low"
    assert RegimePerformanceAnalyzer._get_vol_for_cell(4) == "High"
    assert RegimePerformanceAnalyzer._get_vol_for_cell(5) == "Low"
    assert RegimePerformanceAnalyzer._get_vol_for_cell(6) == "High"


def test_negative_returns(analyzer):
    """Test analyzer handles negative returns correctly."""
    # Bar 1: baseline
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        regime_cell=5,
        trend_state='BearStrong',
        vol_state='Low',
        qqq_close=Decimal('400.00'),
        portfolio_value=Decimal('100000'),
    )

    # Bar 2: QQQ down 5%, Portfolio down 3%
    analyzer.record_bar(
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        regime_cell=5,
        trend_state='BearStrong',
        vol_state='Low',
        qqq_close=Decimal('380.00'),  # -5%
        portfolio_value=Decimal('97000'),  # -3%
    )

    bar2 = analyzer._bars[1]

    # Check negative returns
    expected_qqq_return = (Decimal('380.00') - Decimal('400.00')) / Decimal('400.00')
    assert bar2.qqq_return == expected_qqq_return
    assert bar2.qqq_return < 0

    expected_strat_return = (Decimal('97000') - Decimal('100000')) / Decimal('100000')
    assert bar2.strategy_return == expected_strat_return
    assert bar2.strategy_return < 0
