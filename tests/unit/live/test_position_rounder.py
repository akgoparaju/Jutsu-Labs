"""
Unit tests for Position Rounder.

Tests the NO FRACTIONAL SHARES requirement - all rounding must be DOWN.
"""

import pytest
from decimal import Decimal

from jutsu_engine.live.position_rounder import PositionRounder


class TestPositionRounder:
    """Test suite for PositionRounder class."""

    def test_round_to_shares_basic(self):
        """Test basic share rounding - always rounds DOWN."""
        # $10,000 at $503.45/share = 19.862... → 19 shares (NOT 20)
        shares = PositionRounder.round_to_shares(
            Decimal('10000'),
            Decimal('503.45')
        )
        assert shares == 19
        assert isinstance(shares, int)

    def test_round_to_shares_always_rounds_down(self):
        """Verify ALWAYS rounds down, never up."""
        # $100.99 at $1.00 = 100.99 → 100 shares (NOT 101)
        shares = PositionRounder.round_to_shares(
            Decimal('100.99'),
            Decimal('1.00')
        )
        assert shares == 100

        # $99.01 at $1.00 = 99.01 → 99 shares
        shares = PositionRounder.round_to_shares(
            Decimal('99.01'),
            Decimal('1.00')
        )
        assert shares == 99

    def test_round_to_shares_exact_amount(self):
        """Test exact amounts (no fractional shares)."""
        # $100 at $1.00 = exactly 100 shares
        shares = PositionRounder.round_to_shares(
            Decimal('100.00'),
            Decimal('1.00')
        )
        assert shares == 100

    def test_round_to_shares_small_amount(self):
        """Test small amounts that can't buy a full share."""
        # $0.50 at $1.00 = 0 shares (can't afford one)
        shares = PositionRounder.round_to_shares(
            Decimal('0.50'),
            Decimal('1.00')
        )
        assert shares == 0

    def test_round_to_shares_invalid_price(self):
        """Test error handling for invalid price."""
        with pytest.raises(ValueError, match="Invalid price"):
            PositionRounder.round_to_shares(Decimal('1000'), Decimal('0'))

        with pytest.raises(ValueError, match="Invalid price"):
            PositionRounder.round_to_shares(Decimal('1000'), Decimal('-50'))

    def test_round_to_shares_invalid_amount(self):
        """Test error handling for negative dollar amount."""
        with pytest.raises(ValueError, match="Invalid dollar amount"):
            PositionRounder.round_to_shares(Decimal('-1000'), Decimal('50'))

    def test_convert_weights_to_shares_basic(self):
        """Test converting allocation weights to whole shares."""
        weights = {'TQQQ': 0.60, 'TMF': 0.25, 'CASH': 0.15}
        equity = Decimal('100000')
        prices = {'TQQQ': Decimal('50.00'), 'TMF': Decimal('20.00')}

        target_shares = PositionRounder.convert_weights_to_shares(
            weights, equity, prices
        )

        # TQQQ: 60% of $100K = $60K / $50 = 1200 shares
        # TMF: 25% of $100K = $25K / $20 = 1250 shares
        # CASH: Ignored (implicit remainder)
        assert target_shares == {'TQQQ': 1200, 'TMF': 1250}

    def test_convert_weights_to_shares_fractional_rounding(self):
        """Test that fractional shares round DOWN."""
        weights = {'TQQQ': 0.333}  # 33.3% allocation
        equity = Decimal('100000')
        prices = {'TQQQ': Decimal('503.45')}

        target_shares = PositionRounder.convert_weights_to_shares(
            weights, equity, prices
        )

        # 33.3% of $100K = $33,300 / $503.45 = 66.14... → 66 shares
        assert target_shares == {'TQQQ': 66}

    def test_convert_weights_to_shares_skips_cash(self):
        """Test that CASH symbol is skipped (implicit)."""
        weights = {'TQQQ': 0.80, 'CASH': 0.20}
        equity = Decimal('100000')
        prices = {'TQQQ': Decimal('50.00')}

        target_shares = PositionRounder.convert_weights_to_shares(
            weights, equity, prices
        )

        # Only TQQQ, no CASH key
        assert 'CASH' not in target_shares
        assert target_shares == {'TQQQ': 1600}

    def test_convert_weights_to_shares_skips_zero_weight(self):
        """Test that zero-weight positions are skipped."""
        weights = {'TQQQ': 0.60, 'TMF': 0.0}
        equity = Decimal('100000')
        prices = {'TQQQ': Decimal('50.00'), 'TMF': Decimal('20.00')}

        target_shares = PositionRounder.convert_weights_to_shares(
            weights, equity, prices
        )

        # Only TQQQ (TMF has 0 weight)
        assert target_shares == {'TQQQ': 1200}

    def test_convert_weights_invalid_weight(self):
        """Test error for invalid weight (outside 0-1 range)."""
        weights = {'TQQQ': 1.5}  # Invalid (>1)
        equity = Decimal('100000')
        prices = {'TQQQ': Decimal('50.00')}

        with pytest.raises(ValueError, match="Invalid weight"):
            PositionRounder.convert_weights_to_shares(weights, equity, prices)

    def test_convert_weights_missing_price(self):
        """Test error for missing price."""
        weights = {'TQQQ': 0.60}
        equity = Decimal('100000')
        prices = {}  # Missing TQQQ price

        with pytest.raises(ValueError, match="Price missing"):
            PositionRounder.convert_weights_to_shares(weights, equity, prices)

    def test_calculate_cash_remainder(self):
        """Test cash remainder calculation."""
        target_shares = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('50.45')}
        equity = Decimal('10000')

        cash, cash_pct = PositionRounder.calculate_cash_remainder(
            target_shares, prices, equity
        )

        # 100 shares @ $50.45 = $5,045
        # Cash = $10,000 - $5,045 = $4,955 (49.55%)
        assert cash == Decimal('4955.00')
        assert cash_pct == pytest.approx(49.55, rel=0.01)

    def test_validate_no_over_allocation_valid(self):
        """Test validation passes for valid allocation."""
        target_shares = {'TQQQ': 100}
        prices = {'TQQQ': Decimal('50.00')}
        equity = Decimal('10000')

        # 100 * $50 = $5,000 (50% of equity) → VALID
        is_valid = PositionRounder.validate_no_over_allocation(
            target_shares, prices, equity
        )
        assert is_valid is True

    def test_validate_no_over_allocation_at_100_percent(self):
        """Test validation passes at exactly 100% allocation."""
        target_shares = {'TQQQ': 200}
        prices = {'TQQQ': Decimal('50.00')}
        equity = Decimal('10000')

        # 200 * $50 = $10,000 (100% of equity) → VALID
        is_valid = PositionRounder.validate_no_over_allocation(
            target_shares, prices, equity
        )
        assert is_valid is True

    def test_validate_no_over_allocation_over_100_percent(self):
        """Test validation FAILS for over-allocation."""
        target_shares = {'TQQQ': 300}
        prices = {'TQQQ': Decimal('50.00')}
        equity = Decimal('10000')

        # 300 * $50 = $15,000 (150% of equity) → INVALID
        with pytest.raises(ValueError, match="Over-allocation"):
            PositionRounder.validate_no_over_allocation(
                target_shares, prices, equity
            )

    def test_no_fractional_shares_all_values_int(self):
        """Comprehensive test: verify NO FRACTIONAL SHARES anywhere."""
        weights = {
            'TQQQ': 0.333,  # Fractional weight
            'TMF': 0.666,   # Fractional weight
        }
        equity = Decimal('99999.99')  # Odd equity
        prices = {
            'TQQQ': Decimal('503.45'),  # Odd price
            'TMF': Decimal('19.87')     # Odd price
        }

        target_shares = PositionRounder.convert_weights_to_shares(
            weights, equity, prices
        )

        # ALL shares must be integers
        for symbol, qty in target_shares.items():
            assert isinstance(qty, int), f"{symbol} quantity is not int: {type(qty)}"
            assert qty >= 0, f"{symbol} quantity is negative: {qty}"

    def test_precision_decimal_not_float(self):
        """Test that Decimal precision is maintained (not float)."""
        # This should use Decimal internally, not float
        shares = PositionRounder.round_to_shares(
            Decimal('10000.00'),
            Decimal('3.00')
        )

        # 10000 / 3 = 3333.333... → 3333 shares (exact, not float error)
        assert shares == 3333
        assert isinstance(shares, int)
