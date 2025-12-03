"""
Unit tests for SlippageValidator module.

Tests slippage calculation, validation thresholds, and batch validation.
"""

import pytest
from decimal import Decimal

from jutsu_engine.live.slippage_validator import SlippageValidator
from jutsu_engine.live.exceptions import SlippageExceeded


@pytest.fixture
def config():
    """Standard test configuration."""
    return {
        'execution': {
            'max_slippage_pct': 0.5,
            'slippage_warning_pct': 0.3,
            'slippage_abort_pct': 1.0
        }
    }


@pytest.fixture
def validator(config):
    """Create SlippageValidator instance."""
    return SlippageValidator(config)


class TestSlippageCalculation:
    """Test slippage percentage calculation."""

    def test_calculate_slippage_zero(self, validator):
        """Test zero slippage (exact fill price)."""
        slippage = validator.calculate_slippage_pct(
            Decimal('100.00'),
            Decimal('100.00')
        )
        assert slippage == 0.0

    def test_calculate_slippage_positive(self, validator):
        """Test positive slippage (worse fill for buy)."""
        slippage = validator.calculate_slippage_pct(
            Decimal('100.00'),
            Decimal('100.50')
        )
        assert slippage == 0.5

    def test_calculate_slippage_negative(self, validator):
        """Test negative slippage (better fill)."""
        # Slippage is absolute value
        slippage = validator.calculate_slippage_pct(
            Decimal('100.00'),
            Decimal('99.50')
        )
        assert slippage == 0.5

    def test_calculate_slippage_high(self, validator):
        """Test high slippage calculation."""
        slippage = validator.calculate_slippage_pct(
            Decimal('100.00'),
            Decimal('102.00')
        )
        assert slippage == 2.0

    def test_calculate_slippage_invalid_price(self, validator):
        """Test invalid expected price raises ValueError."""
        with pytest.raises(ValueError):
            validator.calculate_slippage_pct(
                Decimal('0.00'),  # Invalid
                Decimal('100.00')
            )


class TestValidateFill:
    """Test fill validation against thresholds."""

    def test_validate_acceptable_slippage(self, validator):
        """Test acceptable slippage (<0.3%) passes."""
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('50.10'),  # 0.2% slippage
            quantity=100,
            action='BUY'
        )
        assert is_valid is True

    def test_validate_warning_slippage(self, validator):
        """Test warning slippage (0.3-0.5%) passes with warning."""
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('50.20'),  # 0.4% slippage
            quantity=100,
            action='BUY'
        )
        assert is_valid is True  # Still valid, just warning

    def test_validate_max_slippage_exceeded(self, validator):
        """Test max slippage exceeded (0.5-1.0%) fails validation."""
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('50.30'),  # 0.6% slippage
            quantity=100,
            action='BUY'
        )
        assert is_valid is False  # Failed validation

    def test_validate_abort_slippage_raises_exception(self, validator):
        """Test abort slippage (>1.0%) raises SlippageExceeded."""
        with pytest.raises(SlippageExceeded):
            validator.validate_fill(
                symbol='TQQQ',
                expected_price=Decimal('50.00'),
                fill_price=Decimal('50.75'),  # 1.5% slippage
                quantity=100,
                action='BUY'
            )

    def test_validate_sell_order(self, validator):
        """Test slippage validation for SELL orders."""
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('49.90'),  # 0.2% slippage (worse for sell)
            quantity=100,
            action='SELL'
        )
        assert is_valid is True

    def test_validate_large_quantity(self, validator):
        """Test slippage validation with large quantities."""
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('50.10'),  # 0.2% slippage
            quantity=10000,  # Large quantity
            action='BUY'
        )
        assert is_valid is True


class TestBatchValidation:
    """Test batch fill validation."""

    def test_validate_batch_all_pass(self, validator):
        """Test batch validation with all fills passing."""
        fills = {
            'TQQQ': {
                'expected_price': Decimal('50.00'),
                'fill_price': Decimal('50.10'),  # 0.2%
                'quantity': 100,
                'action': 'BUY'
            },
            'TMF': {
                'expected_price': Decimal('20.00'),
                'fill_price': Decimal('20.05'),  # 0.25%
                'quantity': 50,
                'action': 'BUY'
            }
        }

        results = validator.validate_batch(fills)

        assert len(results) == 2
        assert all(results.values())  # All pass

    def test_validate_batch_some_fail(self, validator):
        """Test batch validation with some fails."""
        fills = {
            'TQQQ': {
                'expected_price': Decimal('50.00'),
                'fill_price': Decimal('50.10'),  # 0.2% - PASS
                'quantity': 100,
                'action': 'BUY'
            },
            'TMF': {
                'expected_price': Decimal('20.00'),
                'fill_price': Decimal('20.15'),  # 0.75% - FAIL
                'quantity': 50,
                'action': 'BUY'
            }
        }

        results = validator.validate_batch(fills)

        assert results['TQQQ'] is True
        assert results['TMF'] is False

    def test_validate_batch_abort_exception(self, validator):
        """Test batch validation raises on abort threshold."""
        fills = {
            'TQQQ': {
                'expected_price': Decimal('50.00'),
                'fill_price': Decimal('50.10'),  # 0.2% - OK
                'quantity': 100,
                'action': 'BUY'
            },
            'TMF': {
                'expected_price': Decimal('20.00'),
                'fill_price': Decimal('20.30'),  # 1.5% - ABORT
                'quantity': 50,
                'action': 'BUY'
            }
        }

        with pytest.raises(SlippageExceeded):
            validator.validate_batch(fills)


class TestConfiguration:
    """Test different configurations."""

    def test_custom_thresholds(self):
        """Test validator with custom thresholds."""
        config = {
            'execution': {
                'max_slippage_pct': 1.0,  # More lenient
                'slippage_warning_pct': 0.5,
                'slippage_abort_pct': 2.0
            }
        }

        validator = SlippageValidator(config)

        # 0.8% slippage should pass now (was fail with 0.5% max)
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('50.40'),  # 0.8% slippage
            quantity=100,
            action='BUY'
        )
        assert is_valid is True

    def test_strict_thresholds(self):
        """Test validator with strict thresholds."""
        config = {
            'execution': {
                'max_slippage_pct': 0.2,  # Very strict
                'slippage_warning_pct': 0.1,
                'slippage_abort_pct': 0.5
            }
        }

        validator = SlippageValidator(config)

        # 0.3% slippage should fail (exceeds 0.2% max)
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('50.00'),
            fill_price=Decimal('50.15'),  # 0.3% slippage
            quantity=100,
            action='BUY'
        )
        assert is_valid is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_exact_max_threshold(self, validator):
        """Test slippage exactly at max threshold."""
        # 0.5% exactly (at boundary)
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('100.00'),
            fill_price=Decimal('100.50'),
            quantity=100,
            action='BUY'
        )
        # At boundary, should trigger error
        assert is_valid is False

    def test_exact_abort_threshold(self, validator):
        """Test slippage exactly at abort threshold."""
        # 1.0% exactly (at boundary)
        with pytest.raises(SlippageExceeded):
            validator.validate_fill(
                symbol='TQQQ',
                expected_price=Decimal('100.00'),
                fill_price=Decimal('101.00'),
                quantity=100,
                action='BUY'
            )

    def test_very_small_slippage(self, validator):
        """Test very small slippage (< 0.01%)."""
        is_valid = validator.validate_fill(
            symbol='TQQQ',
            expected_price=Decimal('100.00'),
            fill_price=Decimal('100.005'),  # 0.005%
            quantity=100,
            action='BUY'
        )
        assert is_valid is True

    def test_high_price_stock(self, validator):
        """Test slippage calculation for high-price stocks."""
        # $1000 stock with $5 slippage = 0.5%
        slippage = validator.calculate_slippage_pct(
            Decimal('1000.00'),
            Decimal('1005.00')
        )
        assert slippage == 0.5

    def test_low_price_stock(self, validator):
        """Test slippage calculation for low-price stocks."""
        # $5 stock with $0.025 slippage = 0.5%
        slippage = validator.calculate_slippage_pct(
            Decimal('5.00'),
            Decimal('5.025')
        )
        assert slippage == 0.5
