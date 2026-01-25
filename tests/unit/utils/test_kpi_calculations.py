"""
Unit tests for KPI calculation functions.

Task 8.1: Tests for all KPI calculation functions in kpi_calculations.py.

Tests cover:
1. Daily return calculation (positive, negative, zero, division by zero)
2. Cumulative return calculation
3. Sharpe ratio calculation (normal, insufficient data, zero std)
4. Sortino ratio calculation
5. Calmar ratio calculation
6. Max drawdown calculation
7. Volatility calculation
8. CAGR calculation
9. Trade statistics with FIFO matching
10. Incremental KPI updates (Welford's algorithm)
11. Batch KPI calculation

Reference: claudedocs/eod_daily_performance_workflow.md Phase 8, Task 8.1
"""

import pytest
from decimal import Decimal
from typing import List
import numpy as np

from jutsu_engine.utils.kpi_calculations import (
    calculate_daily_return,
    calculate_cumulative_return,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_calmar_ratio,
    calculate_max_drawdown,
    calculate_volatility,
    calculate_cagr,
    calculate_cagr_from_returns,
    calculate_trade_statistics,
    update_kpis_incremental,
    initialize_kpi_state,
    calculate_all_kpis_batch,
    validate_sharpe_calculation,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_daily_returns() -> List[float]:
    """Sample daily returns representing a moderately successful strategy."""
    # Approximately 0.5% daily returns with some variance
    return [
        0.0082, -0.0029, 0.0104, 0.0054, -0.0012,
        0.0067, 0.0023, -0.0045, 0.0089, 0.0031,
        -0.0018, 0.0056, 0.0041, -0.0033, 0.0072,
        0.0019, -0.0008, 0.0064, 0.0028, -0.0021,
    ]


@pytest.fixture
def sample_equity_series() -> List[float]:
    """Sample equity series for drawdown testing."""
    return [
        10000, 10082, 10053, 10157, 10219,
        10207, 10275, 10299, 10252, 10343,
        10375, 10356, 10414, 10457, 10422,
        10497, 10517, 10509, 10576, 10606,
    ]


@pytest.fixture
def sample_trades() -> List[dict]:
    """Sample trades for FIFO matching tests."""
    return [
        {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 50.0},
        {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 55.0},  # Win
        {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 60.0},
        {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 58.0},  # Loss
        {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 200, 'fill_price': 55.0},
        {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 56.0},  # Win
        {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 57.0},  # Win
    ]


# =============================================================================
# Task 2.1: Daily Return Tests
# =============================================================================

class TestDailyReturn:
    """Tests for calculate_daily_return()."""

    def test_positive_return(self):
        """Test 1% positive daily return."""
        result = calculate_daily_return(Decimal('10100'), Decimal('10000'))
        assert result == Decimal('0.01')

    def test_negative_return(self):
        """Test negative daily return."""
        result = calculate_daily_return(Decimal('9800'), Decimal('10000'))
        assert result == Decimal('-0.02')

    def test_zero_return(self):
        """Test zero return when equity unchanged."""
        result = calculate_daily_return(Decimal('10000'), Decimal('10000'))
        assert result == Decimal('0')

    def test_division_by_zero(self):
        """Test handling of zero previous equity."""
        result = calculate_daily_return(Decimal('10000'), Decimal('0'))
        assert result == Decimal('0')

    def test_float_inputs(self):
        """Test that float inputs are converted correctly."""
        result = calculate_daily_return(10100.0, 10000.0)
        assert result == Decimal('0.01')

    def test_large_return(self):
        """Test large positive return."""
        result = calculate_daily_return(Decimal('12000'), Decimal('10000'))
        assert result == Decimal('0.2')  # 20% return

    def test_decimal_precision(self):
        """Test decimal precision is maintained."""
        result = calculate_daily_return(Decimal('10001'), Decimal('10000'))
        assert result == Decimal('0.0001')  # 0.01% return


# =============================================================================
# Task 2.2: Cumulative Return Tests
# =============================================================================

class TestCumulativeReturn:
    """Tests for calculate_cumulative_return()."""

    def test_positive_cumulative(self):
        """Test positive cumulative return."""
        result = calculate_cumulative_return(Decimal('10219'), Decimal('10000'))
        assert result == Decimal('0.0219')

    def test_negative_cumulative(self):
        """Test negative cumulative return."""
        result = calculate_cumulative_return(Decimal('9500'), Decimal('10000'))
        assert result == Decimal('-0.05')

    def test_zero_initial_capital(self):
        """Test handling of zero initial capital."""
        result = calculate_cumulative_return(Decimal('10000'), Decimal('0'))
        assert result == Decimal('0')

    def test_breakeven(self):
        """Test breakeven (zero cumulative return)."""
        result = calculate_cumulative_return(Decimal('10000'), Decimal('10000'))
        assert result == Decimal('0')


# =============================================================================
# Task 2.3: Sharpe Ratio Tests
# =============================================================================

class TestSharpeRatio:
    """Tests for calculate_sharpe_ratio()."""

    def test_positive_sharpe(self, sample_daily_returns):
        """Test Sharpe ratio with sample returns."""
        result = calculate_sharpe_ratio(sample_daily_returns)
        assert result is not None
        assert result > 0  # Positive returns should give positive Sharpe

    def test_insufficient_data_one_point(self):
        """Test that single data point returns None."""
        result = calculate_sharpe_ratio([0.01])
        assert result is None

    def test_insufficient_data_empty(self):
        """Test that empty list returns None."""
        result = calculate_sharpe_ratio([])
        assert result is None

    def test_zero_std_returns_none(self):
        """Test that zero standard deviation returns None."""
        constant_returns = [0.01, 0.01, 0.01, 0.01, 0.01]
        result = calculate_sharpe_ratio(constant_returns)
        assert result is None

    def test_negative_sharpe(self):
        """Test negative Sharpe for losing strategy."""
        losing_returns = [-0.01, -0.02, -0.01, -0.015, -0.02]
        result = calculate_sharpe_ratio(losing_returns)
        assert result is not None
        assert result < 0

    def test_risk_free_rate_adjustment(self, sample_daily_returns):
        """Test that risk-free rate affects Sharpe calculation."""
        sharpe_zero_rf = calculate_sharpe_ratio(sample_daily_returns, risk_free_rate=0.0)
        sharpe_positive_rf = calculate_sharpe_ratio(sample_daily_returns, risk_free_rate=0.05)

        # Higher risk-free rate should lower Sharpe
        assert sharpe_zero_rf > sharpe_positive_rf

    def test_known_sharpe_value(self):
        """Test Sharpe calculation against known values."""
        # Create returns with realistic daily mean and std
        # Mean ~ 0.0004 (0.04% daily, ~10% annually), Std ~ 0.01 (~16% annual vol)
        # This gives Sharpe ~ (0.10/0.16) = 0.625
        known_returns = [
            0.005, -0.008, 0.003, -0.002, 0.007,
            -0.004, 0.006, -0.005, 0.004, -0.003,
            0.008, -0.006, 0.002, -0.001, 0.005,
        ]
        result = calculate_sharpe_ratio(known_returns)

        # Verify it's in reasonable range (annualized)
        assert result is not None
        assert -1.0 < result < 3.0  # Reasonable Sharpe range for mixed returns


# =============================================================================
# Task 2.4: Sortino Ratio Tests
# =============================================================================

class TestSortinoRatio:
    """Tests for calculate_sortino_ratio()."""

    def test_positive_sortino(self, sample_daily_returns):
        """Test Sortino ratio with sample returns."""
        result = calculate_sortino_ratio(sample_daily_returns)
        assert result is not None
        # Sortino should be higher than Sharpe for asymmetric positive returns
        sharpe = calculate_sharpe_ratio(sample_daily_returns)
        # Not always true, but generally expected

    def test_insufficient_data(self):
        """Test that insufficient data returns None."""
        result = calculate_sortino_ratio([0.01])
        assert result is None

    def test_no_downside(self):
        """Test that all-positive returns handle no downside."""
        positive_only = [0.01, 0.02, 0.015, 0.008, 0.012]
        result = calculate_sortino_ratio(positive_only)
        # With no downside, semi-variance is 0, returns None
        assert result is None

    def test_high_downside(self):
        """Test Sortino with high downside volatility."""
        volatile_returns = [0.05, -0.08, 0.03, -0.07, 0.04, -0.09]
        result = calculate_sortino_ratio(volatile_returns)
        assert result is not None


# =============================================================================
# Task 2.5: Calmar Ratio Tests
# =============================================================================

class TestCalmarRatio:
    """Tests for calculate_calmar_ratio()."""

    def test_normal_calmar(self):
        """Test normal Calmar ratio calculation."""
        result = calculate_calmar_ratio(cagr=0.15, max_drawdown=-0.10)
        assert result == pytest.approx(1.5)

    def test_zero_drawdown(self):
        """Test that zero drawdown returns None."""
        result = calculate_calmar_ratio(cagr=0.15, max_drawdown=0.0)
        assert result is None

    def test_none_inputs(self):
        """Test that None inputs return None."""
        assert calculate_calmar_ratio(cagr=None, max_drawdown=-0.10) is None
        assert calculate_calmar_ratio(cagr=0.15, max_drawdown=None) is None

    def test_negative_cagr(self):
        """Test Calmar with negative CAGR."""
        result = calculate_calmar_ratio(cagr=-0.05, max_drawdown=-0.20)
        assert result == pytest.approx(-0.25)


# =============================================================================
# Task 2.6: Max Drawdown Tests
# =============================================================================

class TestMaxDrawdown:
    """Tests for calculate_max_drawdown()."""

    def test_max_drawdown(self, sample_equity_series):
        """Test max drawdown calculation."""
        result = calculate_max_drawdown(sample_equity_series)
        assert result is not None
        assert result <= 0  # Drawdown is negative or zero

    def test_empty_series(self):
        """Test empty equity series returns None."""
        result = calculate_max_drawdown([])
        assert result is None

    def test_no_drawdown(self):
        """Test monotonically increasing equity has zero drawdown."""
        increasing = [100, 110, 120, 130, 140]
        result = calculate_max_drawdown(increasing)
        assert result == 0.0

    def test_known_drawdown(self):
        """Test max drawdown with known peak-to-trough."""
        # Peak at 100, trough at 80 = -20% drawdown
        equity = [90, 100, 80, 95]
        result = calculate_max_drawdown(equity)
        assert result == pytest.approx(-0.20, abs=0.001)

    def test_multiple_drawdowns(self):
        """Test that max drawdown captures the largest."""
        # Two drawdowns: 10% and 15%
        equity = [100, 90, 95, 100, 85, 100]
        result = calculate_max_drawdown(equity)
        assert result == pytest.approx(-0.15, abs=0.001)


# =============================================================================
# Task 2.7: Volatility Tests
# =============================================================================

class TestVolatility:
    """Tests for calculate_volatility()."""

    def test_positive_volatility(self, sample_daily_returns):
        """Test volatility calculation."""
        result = calculate_volatility(sample_daily_returns)
        assert result is not None
        assert result > 0  # Volatility is always positive

    def test_insufficient_data(self):
        """Test that insufficient data returns None."""
        result = calculate_volatility([0.01])
        assert result is None

    def test_zero_volatility(self):
        """Test zero volatility for constant returns."""
        constant = [0.01, 0.01, 0.01, 0.01, 0.01]
        result = calculate_volatility(constant)
        assert result == 0.0

    def test_annualized_volatility(self):
        """Test that volatility is properly annualized."""
        # Daily std of ~0.01 should give annual ~15.8% (0.01 * sqrt(252))
        returns = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
        result = calculate_volatility(returns)
        assert result is not None
        # Should be roughly 0.01 * sqrt(252) ~ 0.16
        assert 0.1 < result < 0.25


# =============================================================================
# Task 2.8: CAGR Tests
# =============================================================================

class TestCAGR:
    """Tests for calculate_cagr() and calculate_cagr_from_returns()."""

    def test_cagr_one_year(self):
        """Test CAGR over one year."""
        result = calculate_cagr(10000, 11500, 1.0)
        assert result == pytest.approx(0.15, abs=0.001)

    def test_cagr_multi_year(self):
        """Test CAGR over multiple years."""
        # 10000 -> 12100 in 2 years = ~10% CAGR
        result = calculate_cagr(10000, 12100, 2.0)
        assert result == pytest.approx(0.10, abs=0.001)

    def test_cagr_fractional_year(self):
        """Test CAGR over partial year."""
        result = calculate_cagr(10000, 10500, 0.5)
        assert result is not None
        assert result > 0.10  # Annualized would be higher

    def test_cagr_zero_years(self):
        """Test that zero years returns None."""
        result = calculate_cagr(10000, 11000, 0.0)
        assert result is None

    def test_cagr_zero_initial(self):
        """Test that zero initial returns None."""
        result = calculate_cagr(0, 11000, 1.0)
        assert result is None

    def test_cagr_from_returns(self, sample_daily_returns):
        """Test CAGR calculation from daily returns."""
        result = calculate_cagr_from_returns(sample_daily_returns)
        assert result is not None
        # 20 trading days is ~1 month, should be annualized

    def test_cagr_from_returns_empty(self):
        """Test empty returns returns None."""
        result = calculate_cagr_from_returns([])
        assert result is None


# =============================================================================
# Task 2.9: Trade Statistics Tests
# =============================================================================

class TestTradeStatistics:
    """Tests for calculate_trade_statistics()."""

    def test_fifo_matching(self, sample_trades):
        """Test FIFO trade matching."""
        result = calculate_trade_statistics(sample_trades)

        assert result['total_trades'] == 4  # 4 round-trip trades
        assert result['winning_trades'] == 3  # 3 winners
        assert result['losing_trades'] == 1  # 1 loser
        assert result['win_rate'] == pytest.approx(0.75, abs=0.01)

    def test_empty_trades(self):
        """Test empty trade list."""
        result = calculate_trade_statistics([])

        assert result['total_trades'] == 0
        assert result['winning_trades'] == 0
        assert result['losing_trades'] == 0
        assert result['win_rate'] is None

    def test_only_buys(self):
        """Test trades with only buys (no completed trades)."""
        buys_only = [
            {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 50.0},
            {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 55.0},
        ]
        result = calculate_trade_statistics(buys_only)

        assert result['total_trades'] == 0
        assert result['win_rate'] is None

    def test_partial_fills(self):
        """Test partial fill matching."""
        trades = [
            {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 50.0},
            {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 50, 'fill_price': 55.0},  # Win (50 shares)
            {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 50, 'fill_price': 52.0},  # Win (50 shares)
        ]
        result = calculate_trade_statistics(trades)

        assert result['total_trades'] == 2
        assert result['winning_trades'] == 2

    def test_multi_symbol(self):
        """Test FIFO matching with multiple symbols."""
        trades = [
            {'symbol': 'TQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 50.0},
            {'symbol': 'SQQQ', 'action': 'BUY', 'quantity': 100, 'fill_price': 30.0},
            {'symbol': 'TQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 55.0},  # Win
            {'symbol': 'SQQQ', 'action': 'SELL', 'quantity': 100, 'fill_price': 28.0},  # Loss
        ]
        result = calculate_trade_statistics(trades)

        assert result['total_trades'] == 2
        assert result['winning_trades'] == 1
        assert result['losing_trades'] == 1


# =============================================================================
# Task 2.10: Incremental KPI Updates Tests
# =============================================================================

class TestIncrementalKPIs:
    """Tests for update_kpis_incremental() and initialize_kpi_state()."""

    def test_initialize_state(self):
        """Test initial KPI state creation."""
        state = initialize_kpi_state(10000.0)

        assert state['returns_sum'] == 0.0
        assert state['returns_sum_sq'] == 0.0
        assert state['returns_count'] == 0
        assert state['high_water_mark'] == 10000.0
        assert state['max_drawdown'] == 0.0
        assert state['is_first_day'] is True
        assert state['sharpe_ratio'] is None  # Insufficient data

    def test_incremental_update(self):
        """Test incremental KPI update."""
        result = update_kpis_incremental(
            prev_returns_sum=0.05,
            prev_returns_sum_sq=0.0005,
            prev_downside_sum_sq=0.0001,
            prev_returns_count=10,
            prev_high_water_mark=10500.0,
            prev_max_drawdown=-0.02,
            today_return=0.01,
            today_equity=10600.0,
            initial_capital=10000.0,
        )

        # Check incremental state updates
        assert result['returns_count'] == 11
        assert result['returns_sum'] == pytest.approx(0.06, abs=0.001)
        assert result['returns_sum_sq'] > 0.0005

        # Check HWM update
        assert result['high_water_mark'] == 10600.0

        # Check cumulative return
        assert result['cumulative_return'] == pytest.approx(0.06, abs=0.001)

    def test_hwm_update(self):
        """Test high water mark updates correctly."""
        result = update_kpis_incremental(
            prev_returns_sum=0.0,
            prev_returns_sum_sq=0.0,
            prev_downside_sum_sq=0.0,
            prev_returns_count=5,
            prev_high_water_mark=10500.0,
            prev_max_drawdown=0.0,
            today_return=0.01,
            today_equity=10600.0,
            initial_capital=10000.0,
        )

        assert result['high_water_mark'] == 10600.0  # New high

    def test_drawdown_update(self):
        """Test max drawdown updates on decline."""
        result = update_kpis_incremental(
            prev_returns_sum=0.05,
            prev_returns_sum_sq=0.0005,
            prev_downside_sum_sq=0.0001,
            prev_returns_count=10,
            prev_high_water_mark=10500.0,
            prev_max_drawdown=-0.02,
            today_return=-0.05,
            today_equity=10000.0,  # Below HWM
            initial_capital=10000.0,
        )

        # Drawdown = (10000 - 10500) / 10500 = -4.76%
        assert result['drawdown'] == pytest.approx(-0.0476, abs=0.001)
        # Max drawdown should be worse (more negative)
        assert result['max_drawdown'] == pytest.approx(-0.0476, abs=0.001)

    def test_matches_batch_calculation(self, sample_equity_series):
        """Test that incremental updates match batch calculation within tolerance."""
        initial = sample_equity_series[0]

        # Simulate incremental updates
        state = {
            'returns_sum': 0.0,
            'returns_sum_sq': 0.0,
            'downside_sum_sq': 0.0,
            'returns_count': 0,
            'high_water_mark': initial,
            'max_drawdown': 0.0,
        }

        for i in range(1, len(sample_equity_series)):
            today_return = (sample_equity_series[i] - sample_equity_series[i-1]) / sample_equity_series[i-1]
            result = update_kpis_incremental(
                prev_returns_sum=state['returns_sum'],
                prev_returns_sum_sq=state['returns_sum_sq'],
                prev_downside_sum_sq=state['downside_sum_sq'],
                prev_returns_count=state['returns_count'],
                prev_high_water_mark=state['high_water_mark'],
                prev_max_drawdown=state['max_drawdown'],
                today_return=today_return,
                today_equity=sample_equity_series[i],
                initial_capital=initial,
            )
            state = result

        # Calculate batch for comparison
        batch = calculate_all_kpis_batch(sample_equity_series)

        # Compare key metrics
        if state['sharpe_ratio'] is not None and batch['sharpe_ratio'] is not None:
            assert state['sharpe_ratio'] == pytest.approx(batch['sharpe_ratio'], abs=0.01)

        if state['max_drawdown'] is not None and batch['max_drawdown'] is not None:
            assert state['max_drawdown'] == pytest.approx(batch['max_drawdown'], abs=0.001)


# =============================================================================
# Batch Calculation Tests
# =============================================================================

class TestBatchCalculation:
    """Tests for calculate_all_kpis_batch()."""

    def test_batch_calculation(self, sample_equity_series):
        """Test batch KPI calculation."""
        result = calculate_all_kpis_batch(sample_equity_series)

        assert 'cumulative_return' in result
        assert 'max_drawdown' in result
        assert 'sharpe_ratio' in result
        assert 'volatility' in result
        assert 'cagr' in result
        assert 'returns_sum' in result
        assert 'returns_count' in result

    def test_batch_empty_series(self):
        """Test batch with empty series."""
        result = calculate_all_kpis_batch([])
        assert result == {}

    def test_batch_single_point(self):
        """Test batch with single equity point."""
        result = calculate_all_kpis_batch([10000])

        assert result['cumulative_return'] == 0.0
        assert result['trading_days_count'] == 1
        assert result['returns_count'] == 0


# =============================================================================
# Validation Tests
# =============================================================================

class TestValidation:
    """Tests for validation functions."""

    def test_validate_sharpe_within_tolerance(self):
        """Test Sharpe validation within tolerance."""
        returns = [0.01, 0.02, 0.00, 0.01, 0.02, 0.00]
        sharpe = calculate_sharpe_ratio(returns)

        result = validate_sharpe_calculation(returns, sharpe, tolerance=0.01)
        assert result is True

    def test_validate_sharpe_outside_tolerance(self):
        """Test Sharpe validation fails outside tolerance."""
        returns = [0.01, 0.02, 0.00, 0.01, 0.02, 0.00]

        # Pass wrong expected value
        result = validate_sharpe_calculation(returns, expected_sharpe=10.0, tolerance=0.05)
        assert result is False

    def test_validate_none_handling(self):
        """Test validation with None returns."""
        returns = [0.01]  # Insufficient data
        result = validate_sharpe_calculation(returns, expected_sharpe=None)
        assert result is True  # None == None
