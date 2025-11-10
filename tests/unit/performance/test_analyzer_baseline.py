"""
Unit tests for PerformanceAnalyzer baseline calculation.

Tests the calculate_baseline() method which calculates buy-and-hold returns
for benchmark comparison (typically QQQ).
"""
import pytest
from decimal import Decimal
from datetime import datetime, timedelta
import pandas as pd

from jutsu_engine.performance.analyzer import PerformanceAnalyzer


@pytest.fixture
def mock_equity_curve():
    """Create minimal equity curve for PerformanceAnalyzer initialization."""
    # Simple equity curve: start at 100k, end at 110k over 1 year
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2024, 1, 1)

    equity_curve = [
        (start_date, Decimal('100000')),
        (end_date, Decimal('110000'))
    ]
    return equity_curve


@pytest.fixture
def analyzer(mock_equity_curve):
    """Create PerformanceAnalyzer instance for testing."""
    initial_capital = Decimal('100000')
    fills = []  # No fills needed for baseline tests

    return PerformanceAnalyzer(
        fills=fills,
        equity_curve=mock_equity_curve,
        initial_capital=initial_capital
    )


class TestCalculateBaselineSimple:
    """Test basic baseline calculations with simple scenarios."""

    def test_calculate_baseline_simple_gain(self, analyzer):
        """Test baseline with 10% gain."""
        # Start: $100, End: $110 (10% gain)
        # Expected: 10% total return
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('110'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None
        assert result['baseline_symbol'] == 'QQQ'
        assert result['baseline_total_return'] == pytest.approx(0.10)

        # Final value: 100000 / 100 * 110 = 110000
        assert result['baseline_final_value'] == pytest.approx(110000)

        # Over 1 year, annualized should be same as total
        assert result['baseline_annualized_return'] == pytest.approx(0.10, abs=0.001)

    def test_calculate_baseline_loss(self, analyzer):
        """Test baseline with negative return."""
        # Start: $100, End: $80 (20% loss)
        # Expected: -20% total return
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('80'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None
        assert result['baseline_symbol'] == 'QQQ'
        assert result['baseline_total_return'] == pytest.approx(-0.20)

        # Final value: 100000 / 100 * 80 = 80000
        assert result['baseline_final_value'] == pytest.approx(80000)

        # Over 1 year, annualized should be same as total
        assert result['baseline_annualized_return'] == pytest.approx(-0.20, abs=0.001)

    def test_calculate_baseline_no_change(self, analyzer):
        """Test baseline with zero return."""
        # Start: $100, End: $100 (0% change)
        result = analyzer.calculate_baseline(
            symbol='SPY',
            start_price=Decimal('100'),
            end_price=Decimal('100'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None
        assert result['baseline_total_return'] == pytest.approx(0.0)
        assert result['baseline_final_value'] == pytest.approx(100000)
        assert result['baseline_annualized_return'] == pytest.approx(0.0, abs=0.001)


class TestCalculateBaselineAnnualized:
    """Test annualized return calculations over different time periods."""

    def test_calculate_baseline_annualized_2_years(self, analyzer):
        """Test annualized return calculation over 2 years."""
        # 25% total return over 2 years
        # Expected annualized: (1.25)^(1/2) - 1 ≈ 11.8%
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('125'),  # 25% gain
            start_date=datetime(2022, 1, 1),
            end_date=datetime(2024, 1, 1)  # Exactly 2 years
        )

        assert result is not None
        assert result['baseline_total_return'] == pytest.approx(0.25)

        # Annualized: (1.25)^(1/2) - 1 = 0.118033...
        expected_annualized = (1.25 ** 0.5) - 1
        assert result['baseline_annualized_return'] == pytest.approx(expected_annualized, abs=0.001)

    def test_calculate_baseline_annualized_6_months(self, analyzer):
        """Test annualized return over 6 months."""
        # 10% return over 6 months (~182.5 days)
        # Expected annualized: (1.10)^(365.25/182.5) - 1 ≈ 20.7%
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 7, 1)  # ~6 months

        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('110'),
            start_date=start_date,
            end_date=end_date
        )

        assert result is not None
        assert result['baseline_total_return'] == pytest.approx(0.10)

        # Calculate expected annualized
        days = (end_date - start_date).days
        years = days / 365.25
        expected_annualized = (1.10 ** (1 / years)) - 1

        assert result['baseline_annualized_return'] == pytest.approx(expected_annualized, abs=0.01)

    def test_calculate_baseline_short_period(self, analyzer):
        """Test with very short period (<4 days)."""
        # Should return total_return (can't annualize)
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 1, 3)  # 2 days

        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('105'),  # 5% gain
            start_date=start_date,
            end_date=end_date
        )

        assert result is not None
        assert result['baseline_total_return'] == pytest.approx(0.05)

        # For very short periods, annualized should equal total
        assert result['baseline_annualized_return'] == pytest.approx(0.05)


class TestCalculateBaselineEdgeCases:
    """Test edge cases and error handling."""

    def test_calculate_baseline_invalid_start_price_zero(self, analyzer):
        """Test with zero start price."""
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('0'),
            end_price=Decimal('110'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        # Should return None with warning log
        assert result is None

    def test_calculate_baseline_invalid_start_price_negative(self, analyzer):
        """Test with negative start price."""
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('-100'),
            end_price=Decimal('110'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        # Should return None with warning log
        assert result is None

    def test_calculate_baseline_invalid_end_price_zero(self, analyzer):
        """Test with zero end price."""
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('0'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        # Should return None with warning log
        assert result is None

    def test_calculate_baseline_invalid_end_price_negative(self, analyzer):
        """Test with negative end price."""
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('-110'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        # Should return None with warning log
        assert result is None

    def test_calculate_baseline_both_prices_invalid(self, analyzer):
        """Test with both prices invalid."""
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('0'),
            end_price=Decimal('0'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        # Should return None
        assert result is None


class TestCalculateBaselineCapital:
    """Test that calculation uses analyzer's initial capital correctly."""

    def test_calculate_baseline_uses_initial_capital(self, mock_equity_curve):
        """Test that calculation uses analyzer's initial_capital."""
        # Create analyzer with different initial capital
        initial_capital = Decimal('50000')  # Half the previous test amount
        analyzer = PerformanceAnalyzer(
            fills=[],
            equity_curve=mock_equity_curve,
            initial_capital=initial_capital
        )

        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('110'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None

        # Verify shares_bought calculation
        # shares_bought = 50000 / 100 = 500 shares
        # final_value = 500 * 110 = 55000
        assert result['baseline_final_value'] == pytest.approx(55000)
        assert result['baseline_total_return'] == pytest.approx(0.10)

    def test_calculate_baseline_large_capital(self, mock_equity_curve):
        """Test with large initial capital."""
        initial_capital = Decimal('1000000')  # $1M
        analyzer = PerformanceAnalyzer(
            fills=[],
            equity_curve=mock_equity_curve,
            initial_capital=initial_capital
        )

        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('250.50'),
            end_price=Decimal('275.55'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None

        # Calculate expected values
        shares_bought = initial_capital / Decimal('250.50')
        expected_final = float(shares_bought * Decimal('275.55'))

        assert result['baseline_final_value'] == pytest.approx(expected_final, rel=0.0001)


class TestCalculateBaselineRealWorld:
    """Test with realistic market scenarios."""

    def test_calculate_baseline_qqq_bull_market(self, analyzer):
        """Test with realistic QQQ bull market returns."""
        # Simulate QQQ: ~30% annual return in bull market
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('300.00'),
            end_price=Decimal('390.00'),  # 30% gain
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None
        assert result['baseline_symbol'] == 'QQQ'
        assert result['baseline_total_return'] == pytest.approx(0.30)
        assert result['baseline_annualized_return'] == pytest.approx(0.30, abs=0.01)

    def test_calculate_baseline_spy_typical_year(self, analyzer):
        """Test with realistic SPY typical year returns."""
        # Simulate SPY: ~10% average annual return
        result = analyzer.calculate_baseline(
            symbol='SPY',
            start_price=Decimal('400.00'),
            end_price=Decimal('440.00'),  # 10% gain
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None
        assert result['baseline_symbol'] == 'SPY'
        assert result['baseline_total_return'] == pytest.approx(0.10)

    def test_calculate_baseline_market_crash(self, analyzer):
        """Test with market crash scenario."""
        # Simulate 2008-style crash: -37% (S&P 500 in 2008)
        result = analyzer.calculate_baseline(
            symbol='SPY',
            start_price=Decimal('150.00'),
            end_price=Decimal('94.50'),  # -37%
            start_date=datetime(2008, 1, 1),
            end_date=datetime(2009, 1, 1)
        )

        assert result is not None
        assert result['baseline_total_return'] == pytest.approx(-0.37)
        assert result['baseline_annualized_return'] == pytest.approx(-0.37, abs=0.01)


class TestCalculateBaselineSymbols:
    """Test with different benchmark symbols."""

    def test_calculate_baseline_different_symbols(self, analyzer):
        """Test that symbol name is correctly stored in result."""
        symbols = ['QQQ', 'SPY', 'DIA', 'IWM', 'VTI']

        for symbol in symbols:
            result = analyzer.calculate_baseline(
                symbol=symbol,
                start_price=Decimal('100'),
                end_price=Decimal('110'),
                start_date=datetime(2023, 1, 1),
                end_date=datetime(2024, 1, 1)
            )

            assert result is not None
            assert result['baseline_symbol'] == symbol


class TestCalculateBaselinePrecision:
    """Test decimal precision in calculations."""

    def test_calculate_baseline_decimal_precision(self, analyzer):
        """Test that Decimal is used for financial calculations."""
        # Use prices with many decimal places
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('123.456789'),
            end_price=Decimal('135.802468'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None

        # Calculate expected with high precision
        shares = Decimal('100000') / Decimal('123.456789')
        expected_final = float(shares * Decimal('135.802468'))

        # Should match to high precision (allow small floating point error)
        assert result['baseline_final_value'] == pytest.approx(expected_final, rel=1e-6)

    def test_calculate_baseline_return_types(self, analyzer):
        """Test that return types are correct (float for dict values)."""
        result = analyzer.calculate_baseline(
            symbol='QQQ',
            start_price=Decimal('100'),
            end_price=Decimal('110'),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 1, 1)
        )

        assert result is not None

        # Check types - all numeric values should be float for JSON serialization
        assert isinstance(result['baseline_symbol'], str)
        assert isinstance(result['baseline_final_value'], float)
        assert isinstance(result['baseline_total_return'], float)
        assert isinstance(result['baseline_annualized_return'], float)
