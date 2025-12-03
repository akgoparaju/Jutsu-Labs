"""
Slippage Validator - Validate fill quality against expected prices.

This module validates order fills by calculating slippage percentage and
comparing against configured thresholds. Issues warnings for moderate slippage
and raises critical errors for excessive slippage.
"""

import logging
from decimal import Decimal
from typing import Dict

from jutsu_engine.live.exceptions import SlippageExceeded

logger = logging.getLogger('LIVE.SLIPPAGE')


class SlippageValidator:
    """
    Validate order fills against expected prices with slippage thresholds.

    Slippage is calculated as: |fill_price - expected_price| / expected_price
    Three thresholds: warning (0.3%), max (0.5%), and abort (1.0%).
    """

    def __init__(self, config: Dict):
        """
        Initialize slippage validator with configured thresholds.

        Args:
            config: Configuration dictionary with execution settings
                    Expected keys:
                        execution.max_slippage_pct: Maximum allowed slippage (default: 0.5)
                        execution.slippage_warning_pct: Warning threshold (default: 0.3)
                        execution.slippage_abort_pct: Abort threshold (default: 1.0)
        """
        exec_config = config.get('execution', {})

        self.max_slippage_pct = exec_config.get('max_slippage_pct', 0.5)
        self.warning_pct = exec_config.get('slippage_warning_pct', 0.3)
        self.abort_pct = exec_config.get('slippage_abort_pct', 1.0)

        logger.info(
            f"SlippageValidator initialized: "
            f"warning={self.warning_pct}%, max={self.max_slippage_pct}%, "
            f"abort={self.abort_pct}%"
        )

    def calculate_slippage_pct(
        self,
        expected_price: Decimal,
        fill_price: Decimal
    ) -> float:
        """
        Calculate slippage percentage.

        Slippage formula: |fill_price - expected_price| / expected_price * 100

        Args:
            expected_price: Expected execution price (Decimal)
            fill_price: Actual fill price (Decimal)

        Returns:
            Slippage percentage (float)

        Examples:
            >>> calculate_slippage_pct(Decimal('100.00'), Decimal('100.50'))
            0.5  # 0.5% slippage

            >>> calculate_slippage_pct(Decimal('100.00'), Decimal('99.50'))
            0.5  # 0.5% slippage (absolute value)
        """
        if expected_price <= 0:
            raise ValueError(f"Invalid expected_price: {expected_price}")

        slippage = abs(fill_price - expected_price) / expected_price
        slippage_pct = float(slippage * 100)

        logger.debug(
            f"Slippage calculation: expected=${expected_price:.2f}, "
            f"fill=${fill_price:.2f}, slippage={slippage_pct:.3f}%"
        )

        return slippage_pct

    def validate_fill(
        self,
        symbol: str,
        expected_price: Decimal,
        fill_price: Decimal,
        quantity: int,
        action: str
    ) -> bool:
        """
        Validate fill price against slippage thresholds.

        Logs WARNING if slippage exceeds warning_pct.
        Logs ERROR and returns False if slippage exceeds max_slippage_pct.
        Raises SlippageExceeded if slippage exceeds abort_pct.

        Args:
            symbol: Stock ticker symbol
            expected_price: Expected execution price (Decimal)
            fill_price: Actual fill price (Decimal)
            quantity: Number of shares executed
            action: "BUY" or "SELL"

        Returns:
            True if slippage is acceptable (<=max_slippage_pct)
            False if slippage exceeds max but below abort threshold

        Raises:
            SlippageExceeded: If slippage >abort_pct (critical failure)
        """
        slippage_pct = self.calculate_slippage_pct(expected_price, fill_price)

        # Calculate cost impact
        slippage_per_share = abs(fill_price - expected_price)
        total_slippage_cost = slippage_per_share * quantity

        # Log fill details
        logger.info(
            f"Fill validation: {action} {quantity} {symbol} @ ${fill_price:.2f} "
            f"(expected ${expected_price:.2f}, slippage {slippage_pct:.3f}%, "
            f"cost ${total_slippage_cost:.2f})"
        )

        # Check abort threshold (critical - raise exception)
        if slippage_pct >= self.abort_pct:
            error_msg = (
                f"CRITICAL SLIPPAGE: {symbol} {action} slippage={slippage_pct:.3f}% "
                f"exceeds abort threshold {self.abort_pct}% "
                f"(expected ${expected_price:.2f}, fill ${fill_price:.2f}, "
                f"cost ${total_slippage_cost:.2f})"
            )
            logger.critical(error_msg)
            raise SlippageExceeded(error_msg)

        # Check max threshold (error but continue)
        if slippage_pct >= self.max_slippage_pct:
            logger.error(
                f"SLIPPAGE EXCEEDED: {symbol} {action} slippage={slippage_pct:.3f}% "
                f"exceeds max {self.max_slippage_pct}% "
                f"(expected ${expected_price:.2f}, fill ${fill_price:.2f}, "
                f"cost ${total_slippage_cost:.2f})"
            )
            return False

        # Check warning threshold
        if slippage_pct >= self.warning_pct:
            logger.warning(
                f"High slippage: {symbol} {action} slippage={slippage_pct:.3f}% "
                f"exceeds warning {self.warning_pct}% "
                f"(expected ${expected_price:.2f}, fill ${fill_price:.2f}, "
                f"cost ${total_slippage_cost:.2f})"
            )

        # Acceptable slippage
        logger.info(f"Slippage validation PASSED for {symbol}: {slippage_pct:.3f}% ✅")
        return True

    def validate_batch(
        self,
        fills: Dict[str, Dict]
    ) -> Dict[str, bool]:
        """
        Validate multiple fills in batch.

        Args:
            fills: Dictionary of fills:
                {symbol: {
                    'expected_price': Decimal,
                    'fill_price': Decimal,
                    'quantity': int,
                    'action': str
                }}

        Returns:
            Dictionary of validation results: {symbol: is_valid}

        Raises:
            SlippageExceeded: If any fill exceeds abort threshold
        """
        results = {}

        for symbol, fill_info in fills.items():
            is_valid = self.validate_fill(
                symbol=symbol,
                expected_price=fill_info['expected_price'],
                fill_price=fill_info['fill_price'],
                quantity=fill_info['quantity'],
                action=fill_info['action']
            )
            results[symbol] = is_valid

        # Summary logging
        passed = sum(1 for v in results.values() if v)
        failed = len(results) - passed

        if failed > 0:
            logger.warning(f"Batch validation: {passed} passed, {failed} failed")
        else:
            logger.info(f"Batch validation: All {passed} fills passed ✅")

        return results


def main():
    """Test slippage validator functionality."""
    logging.basicConfig(level=logging.INFO)

    # Test configuration
    config = {
        'execution': {
            'max_slippage_pct': 0.5,
            'slippage_warning_pct': 0.3,
            'slippage_abort_pct': 1.0
        }
    }

    validator = SlippageValidator(config)

    # Test 1: Acceptable slippage (<0.3%)
    print("\nTest 1: Acceptable slippage (0.1%)")
    is_valid = validator.validate_fill(
        'TQQQ',
        Decimal('50.00'),
        Decimal('50.05'),  # 0.1% slippage
        100,
        'BUY'
    )
    assert is_valid is True
    print("  ✅ PASSED")

    # Test 2: Warning slippage (0.3-0.5%)
    print("\nTest 2: Warning slippage (0.4%)")
    is_valid = validator.validate_fill(
        'TQQQ',
        Decimal('50.00'),
        Decimal('50.20'),  # 0.4% slippage
        100,
        'BUY'
    )
    assert is_valid is True  # Still valid, just warning
    print("  ✅ WARNING logged but PASSED")

    # Test 3: Max slippage exceeded (0.5-1.0%)
    print("\nTest 3: Max slippage exceeded (0.6%)")
    is_valid = validator.validate_fill(
        'TQQQ',
        Decimal('50.00'),
        Decimal('50.30'),  # 0.6% slippage
        100,
        'BUY'
    )
    assert is_valid is False  # Failed validation
    print("  ✅ FAILED validation (as expected)")

    # Test 4: Abort slippage (>1.0%) - should raise exception
    print("\nTest 4: Abort slippage (1.5%) - should raise exception")
    try:
        validator.validate_fill(
            'TQQQ',
            Decimal('50.00'),
            Decimal('50.75'),  # 1.5% slippage
            100,
            'BUY'
        )
        print("  ❌ FAILED - Should have raised SlippageExceeded")
    except SlippageExceeded as e:
        print(f"  ✅ SlippageExceeded raised correctly: {e}")

    # Test 5: Batch validation
    print("\nTest 5: Batch validation")
    fills = {
        'TQQQ': {
            'expected_price': Decimal('50.00'),
            'fill_price': Decimal('50.10'),  # 0.2% slippage
            'quantity': 100,
            'action': 'BUY'
        },
        'TMF': {
            'expected_price': Decimal('20.00'),
            'fill_price': Decimal('20.05'),  # 0.25% slippage
            'quantity': 50,
            'action': 'BUY'
        }
    }
    results = validator.validate_batch(fills)
    print(f"  Results: {results}")
    assert all(results.values())
    print("  ✅ All fills passed")

    print("\n✅ All slippage validator tests passed")


if __name__ == "__main__":
    main()
