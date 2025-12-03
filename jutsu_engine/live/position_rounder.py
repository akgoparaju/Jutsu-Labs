"""
Position Rounder - Convert dollar allocations to whole shares.

This module ensures NO FRACTIONAL SHARES are allocated. All position
calculations round DOWN to avoid over-allocation and maintain compliance
with broker restrictions.
"""

import logging
from decimal import Decimal
from typing import Dict, Tuple

logger = logging.getLogger('LIVE.POSITION_ROUNDER')


class PositionRounder:
    """
    Convert dollar allocations to whole shares (no fractional shares).

    CRITICAL: Always rounds DOWN to avoid over-allocating capital.
    Never uses round() or ceil() - only int() which truncates.
    """

    @staticmethod
    def round_to_shares(dollar_amount: Decimal, price: Decimal) -> int:
        """
        Convert dollar amount to whole shares (round down).

        NO FRACTIONAL SHARES - Always rounds DOWN to avoid over-allocation.
        Uses int() which truncates decimal, never round() or ceil().

        Args:
            dollar_amount: Amount to allocate in dollars (Decimal)
            price: Current share price (Decimal)

        Returns:
            Number of whole shares (int, always rounded DOWN)

        Raises:
            ValueError: If price <= 0 or dollar_amount < 0

        Examples:
            >>> round_to_shares(Decimal('10000'), Decimal('503.45'))
            19  # NOT 20, always round down
            >>> round_to_shares(Decimal('100.70'), Decimal('1.00'))
            100  # NOT 101, truncate decimal
        """
        if price <= 0:
            raise ValueError(f"Invalid price: {price} (must be > 0)")

        if dollar_amount < 0:
            raise ValueError(f"Invalid dollar amount: {dollar_amount} (must be >= 0)")

        # NO FRACTIONAL SHARES - Always round DOWN
        # int() truncates decimal, giving us floor behavior
        shares = int(dollar_amount / price)

        logger.debug(
            f"${dollar_amount:.2f} at ${price:.2f}/share = {shares} shares "
            f"(${shares * price:.2f} allocated, ${dollar_amount - (shares * price):.2f} remainder)"
        )

        return shares

    @staticmethod
    def convert_weights_to_shares(
        target_weights: Dict[str, float],
        account_equity: Decimal,
        current_prices: Dict[str, Decimal]
    ) -> Dict[str, int]:
        """
        Convert percentage weights to whole shares.

        Converts allocation weights (0-1) into exact share quantities,
        rounding down for each position. Cash allocation is implicit
        (remaining unallocated capital).

        Args:
            target_weights: {symbol: weight} where weight is 0-1
            account_equity: Total account value (Decimal)
            current_prices: {symbol: price} (Decimal)

        Returns:
            {symbol: shares} where all shares are whole numbers (int)

        Raises:
            ValueError: If weights invalid or price missing

        Examples:
            >>> convert_weights_to_shares(
            ...     {'TQQQ': 0.60, 'TMF': 0.25, 'CASH': 0.15},
            ...     Decimal('100000'),
            ...     {'TQQQ': Decimal('50.00'), 'TMF': Decimal('20.00')}
            ... )
            {'TQQQ': 1200, 'TMF': 1250}  # CASH implicit in remainder
        """
        target_shares = {}
        total_allocated = Decimal('0')

        for symbol, weight in target_weights.items():
            # Skip CASH - it's implicit (unallocated remainder)
            if symbol == 'CASH' or weight == 0:
                continue

            # Validate weight range
            if not (0 <= weight <= 1):
                raise ValueError(f"Invalid weight for {symbol}: {weight} (must be 0-1)")

            # Check price availability
            if symbol not in current_prices:
                raise ValueError(f"Price missing for {symbol}")

            # Calculate dollar allocation
            dollar_allocation = account_equity * Decimal(str(weight))
            price = current_prices[symbol]

            # Convert to shares (always round down)
            shares = PositionRounder.round_to_shares(dollar_allocation, price)

            # Track allocation
            target_shares[symbol] = shares
            allocated_value = shares * price
            total_allocated += allocated_value

            logger.info(
                f"{symbol}: {weight*100:.1f}% = ${dollar_allocation:,.2f} "
                f"→ {shares} shares @ ${price:.2f} = ${allocated_value:,.2f}"
            )

        # Calculate cash remainder
        cash_remainder = account_equity - total_allocated
        cash_pct = (cash_remainder / account_equity) * 100

        logger.info(f"Total allocated: ${total_allocated:,.2f}")
        logger.info(f"Cash remainder: ${cash_remainder:,.2f} ({cash_pct:.2f}%)")

        return target_shares

    @staticmethod
    def calculate_cash_remainder(
        target_shares: Dict[str, int],
        current_prices: Dict[str, Decimal],
        account_equity: Decimal
    ) -> Tuple[Decimal, float]:
        """
        Calculate unallocated cash after share rounding.

        Due to rounding down, there will always be some cash left over.
        This is expected and prevents over-allocation.

        Args:
            target_shares: {symbol: shares}
            current_prices: {symbol: price}
            account_equity: Total account value

        Returns:
            Tuple of (cash_amount, cash_percentage)

        Examples:
            >>> calculate_cash_remainder(
            ...     {'TQQQ': 100},
            ...     {'TQQQ': Decimal('50.45')},
            ...     Decimal('10000')
            ... )
            (Decimal('4955.00'), 49.55)  # $4,955 (49.55%) cash
        """
        total_allocated = Decimal('0')

        for symbol, shares in target_shares.items():
            if symbol in current_prices:
                allocated_value = shares * current_prices[symbol]
                total_allocated += allocated_value

        cash_amount = account_equity - total_allocated
        cash_pct = float((cash_amount / account_equity) * 100) if account_equity > 0 else 0.0

        logger.debug(
            f"Cash remainder: ${cash_amount:,.2f} ({cash_pct:.2f}%) "
            f"from ${account_equity:,.2f} equity"
        )

        return cash_amount, cash_pct

    @staticmethod
    def validate_no_over_allocation(
        target_shares: Dict[str, int],
        current_prices: Dict[str, Decimal],
        account_equity: Decimal,
        tolerance_pct: float = 0.01
    ) -> bool:
        """
        Validate that target allocation doesn't exceed account equity.

        Should always pass if round_to_shares() is used correctly.
        Provides safety check against implementation bugs.

        Args:
            target_shares: {symbol: shares}
            current_prices: {symbol: price}
            account_equity: Total account value
            tolerance_pct: Allowed tolerance for float arithmetic (default 0.01%)

        Returns:
            True if allocation is valid (<=100%), False if over-allocated

        Raises:
            ValueError: If over-allocation detected (critical error)
        """
        total_value = Decimal('0')

        for symbol, shares in target_shares.items():
            if symbol in current_prices:
                position_value = shares * current_prices[symbol]
                total_value += position_value

        allocation_pct = float((total_value / account_equity) * 100) if account_equity > 0 else 0.0

        if allocation_pct > (100 + tolerance_pct):
            error_msg = (
                f"CRITICAL: Over-allocation detected! "
                f"Allocated ${total_value:,.2f} ({allocation_pct:.2f}%) "
                f"exceeds equity ${account_equity:,.2f}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        logger.info(f"Allocation validation: {allocation_pct:.2f}% of equity ✅")
        return True


def main():
    """Test position rounder functionality."""
    logging.basicConfig(level=logging.INFO)

    # Test 1: Basic share rounding
    print("Test 1: Basic share rounding")
    shares = PositionRounder.round_to_shares(Decimal('10000'), Decimal('503.45'))
    print(f"  $10,000 at $503.45 = {shares} shares")
    assert shares == 19, f"Expected 19 shares, got {shares}"

    # Test 2: Fractional amount always rounds down
    print("\nTest 2: Fractional rounding (should round DOWN)")
    shares = PositionRounder.round_to_shares(Decimal('100.99'), Decimal('1.00'))
    print(f"  $100.99 at $1.00 = {shares} shares")
    assert shares == 100, f"Expected 100 shares (rounded down), got {shares}"

    # Test 3: Convert weights to shares
    print("\nTest 3: Convert weights to shares")
    weights = {'TQQQ': 0.60, 'TMF': 0.25, 'CASH': 0.15}
    equity = Decimal('100000')
    prices = {'TQQQ': Decimal('50.00'), 'TMF': Decimal('20.00')}

    target_shares = PositionRounder.convert_weights_to_shares(weights, equity, prices)
    print(f"  Target shares: {target_shares}")

    # Test 4: Cash remainder
    print("\nTest 4: Cash remainder calculation")
    cash, cash_pct = PositionRounder.calculate_cash_remainder(
        target_shares,
        prices,
        equity
    )
    print(f"  Cash remainder: ${cash:,.2f} ({cash_pct:.2f}%)")

    # Test 5: Validate no over-allocation
    print("\nTest 5: Validate no over-allocation")
    is_valid = PositionRounder.validate_no_over_allocation(
        target_shares,
        prices,
        equity
    )
    print(f"  Validation: {'PASSED' if is_valid else 'FAILED'} ✅")

    print("\n✅ All tests passed - NO FRACTIONAL SHARES allocated")


if __name__ == "__main__":
    main()
