"""
Dry-Run Order Executor - Log hypothetical trades without execution.

This module calculates position differences and logs hypothetical orders
for validation purposes. NO ACTUAL ORDERS are placed in dry-run mode.
"""

import logging
from decimal import Decimal
from typing import Dict, List, Tuple
from datetime import datetime, timezone
from pathlib import Path
import csv

logger = logging.getLogger('LIVE.DRY_RUN')


class DryRunExecutor:
    """
    Calculate and log hypothetical trades without execution.

    Dry-run mode validates the complete workflow without placing actual
    orders. All trades are logged to CSV for post-market validation.
    """

    def __init__(
        self,
        trade_log_path: Path = Path('logs/live_trades.csv'),
        rebalance_threshold_pct: float = 5.0
    ):
        """
        Initialize dry-run executor.

        Args:
            trade_log_path: Path to trade log CSV file
            rebalance_threshold_pct: Only trade if position diff >5%
        """
        self.trade_log_path = trade_log_path
        self.rebalance_threshold_pct = rebalance_threshold_pct

        # Create logs directory if needed
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize CSV if doesn't exist
        if not self.trade_log_path.exists():
            self._initialize_csv()

        logger.info(f"DryRunExecutor initialized: {self.trade_log_path}")

    def _initialize_csv(self) -> None:
        """Create CSV with header if doesn't exist."""
        with open(self.trade_log_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Date', 'Time', 'Ticker', 'Action', 'Qty',
                'Price', 'Value', 'Reason', 'Mode'
            ])
        logger.debug(f"Initialized trade log: {self.trade_log_path}")

    def calculate_rebalance_diff(
        self,
        current_positions: Dict[str, int],
        target_positions: Dict[str, int]
    ) -> Dict[str, int]:
        """
        Calculate position differences (target - current).

        Args:
            current_positions: {symbol: quantity} currently held
            target_positions: {symbol: quantity} desired

        Returns:
            {symbol: diff} where positive = buy, negative = sell

        Examples:
            >>> calculate_rebalance_diff({'TQQQ': 100}, {'TQQQ': 120})
            {'TQQQ': 20}  # Buy 20

            >>> calculate_rebalance_diff({'TQQQ': 100}, {'TQQQ': 80})
            {'TQQQ': -20}  # Sell 20

            >>> calculate_rebalance_diff({'TQQQ': 100}, {'TMF': 50})
            {'TQQQ': -100, 'TMF': 50}  # Sell all TQQQ, buy 50 TMF
        """
        diffs = {}

        # Get all symbols from both positions
        all_symbols = set(current_positions.keys()) | set(target_positions.keys())

        for symbol in all_symbols:
            current = current_positions.get(symbol, 0)
            target = target_positions.get(symbol, 0)
            diff = target - current

            if diff != 0:
                diffs[symbol] = diff

        logger.info(f"Rebalance diff calculated: {diffs}")
        return diffs

    def filter_by_threshold(
        self,
        position_diffs: Dict[str, int],
        current_positions: Dict[str, int],
        current_prices: Dict[str, Decimal],
        account_equity: Decimal
    ) -> Dict[str, int]:
        """
        Filter trades below rebalance threshold (5% default).

        Prevents churning - don't trade if position change is <5%
        of account equity.

        Args:
            position_diffs: {symbol: diff} from calculate_rebalance_diff
            current_positions: {symbol: qty} currently held
            current_prices: {symbol: price} current market prices
            account_equity: Total account value

        Returns:
            Filtered {symbol: diff} with only significant trades

        Examples:
            >>> # $100K account, 5% threshold = $5K minimum trade
            >>> filter_by_threshold(
            ...     {'TQQQ': 10},  # $500 trade at $50/share
            ...     {'TQQQ': 100},
            ...     {'TQQQ': Decimal('50.00')},
            ...     Decimal('100000')
            ... )
            {}  # Filtered out (0.5% < 5%)

            >>> filter_by_threshold(
            ...     {'TQQQ': 200},  # $10K trade at $50/share
            ...     {'TQQQ': 100},
            ...     {'TQQQ': Decimal('50.00')},
            ...     Decimal('100000')
            ... )
            {'TQQQ': 200}  # Kept (10% > 5%)
        """
        threshold_value = account_equity * Decimal(str(self.rebalance_threshold_pct / 100))

        filtered = {}

        for symbol, diff in position_diffs.items():
            if symbol not in current_prices:
                logger.warning(f"Missing price for {symbol}, skipping filter check")
                filtered[symbol] = diff
                continue

            # Calculate trade value
            price = current_prices[symbol]
            trade_value = abs(diff) * price

            # Calculate as % of account
            trade_pct = (trade_value / account_equity) * 100

            if trade_value >= threshold_value:
                filtered[symbol] = diff
                logger.info(
                    f"{symbol}: {diff:+d} shares (${trade_value:,.2f}, {trade_pct:.1f}%) "
                    f"→ KEEP (>= {self.rebalance_threshold_pct}% threshold)"
                )
            else:
                logger.info(
                    f"{symbol}: {diff:+d} shares (${trade_value:,.2f}, {trade_pct:.1f}%) "
                    f"→ SKIP (< {self.rebalance_threshold_pct}% threshold)"
                )

        if not filtered:
            logger.info("No trades exceed rebalance threshold - no action needed")

        return filtered

    def log_hypothetical_orders(
        self,
        position_diffs: Dict[str, int],
        current_prices: Dict[str, Decimal],
        reason: str = "Rebalance"
    ) -> List[Dict]:
        """
        Log hypothetical orders to CSV.

        Args:
            position_diffs: {symbol: diff} after threshold filtering
            current_prices: {symbol: price} current market prices
            reason: Trade rationale (e.g., "Rebalance", "Signal Change")

        Returns:
            List of order dictionaries (for validation reporting)
        """
        if not position_diffs:
            logger.info("No orders to log (empty position_diffs)")
            return []

        now = datetime.now(timezone.utc)
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')

        orders = []

        with open(self.trade_log_path, 'a', newline='') as f:
            writer = csv.writer(f)

            for symbol, diff in position_diffs.items():
                if symbol not in current_prices:
                    logger.warning(f"Missing price for {symbol}, skipping order log")
                    continue

                price = current_prices[symbol]
                action = "BUY" if diff > 0 else "SELL"
                qty = abs(diff)
                value = qty * price

                # Write to CSV
                writer.writerow([
                    date_str,
                    time_str,
                    symbol,
                    action,
                    qty,
                    f"{price:.2f}",
                    f"{value:.2f}",
                    reason,
                    "DRY-RUN"
                ])

                # Build order dict for return
                order = {
                    'date': date_str,
                    'time': time_str,
                    'symbol': symbol,
                    'action': action,
                    'qty': qty,
                    'price': price,
                    'value': value,
                    'reason': reason,
                    'mode': 'DRY-RUN'
                }
                orders.append(order)

                logger.info(
                    f"HYPOTHETICAL {action}: {qty} {symbol} @ ${price:.2f} "
                    f"= ${value:,.2f} ({reason})"
                )

        logger.info(f"Logged {len(orders)} hypothetical orders to {self.trade_log_path}")
        return orders

    def execute_dry_run(
        self,
        current_positions: Dict[str, int],
        target_positions: Dict[str, int],
        current_prices: Dict[str, Decimal],
        account_equity: Decimal
    ) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Complete dry-run execution workflow.

        1. Calculate position diffs (target - current)
        2. Filter by rebalance threshold (5% default)
        3. Log hypothetical orders to CSV

        Args:
            current_positions: {symbol: qty} currently held
            target_positions: {symbol: qty} desired
            current_prices: {symbol: price} current market prices
            account_equity: Total account value

        Returns:
            Tuple of (orders, final_diffs):
                - orders: List of hypothetical orders logged
                - final_diffs: Position diffs after threshold filtering
        """
        logger.info("Starting dry-run execution workflow")

        # Step 1: Calculate rebalance diff
        position_diffs = self.calculate_rebalance_diff(
            current_positions,
            target_positions
        )

        if not position_diffs:
            logger.info("No position changes needed - portfolio already at target")
            return [], {}

        # Step 2: Filter by threshold
        filtered_diffs = self.filter_by_threshold(
            position_diffs,
            current_positions,
            current_prices,
            account_equity
        )

        if not filtered_diffs:
            logger.info("No trades exceed threshold - dry-run complete (no action)")
            return [], {}

        # Step 3: Log hypothetical orders
        orders = self.log_hypothetical_orders(
            filtered_diffs,
            current_prices,
            reason="Rebalance"
        )

        logger.info(f"Dry-run complete: {len(orders)} hypothetical orders logged")
        return orders, filtered_diffs


def main():
    """Test dry-run executor functionality."""
    logging.basicConfig(level=logging.INFO)

    executor = DryRunExecutor()

    # Test 1: Calculate rebalance diff
    print("\nTest 1: Calculate rebalance diff")
    current = {'TQQQ': 100, 'TMF': 50}
    target = {'TQQQ': 120, 'TMF': 30, 'CASH': 0}
    diffs = executor.calculate_rebalance_diff(current, target)
    print(f"  Current: {current}")
    print(f"  Target: {target}")
    print(f"  Diffs: {diffs}")
    assert diffs == {'TQQQ': 20, 'TMF': -20}

    # Test 2: Filter by threshold
    print("\nTest 2: Filter by threshold (5% of $100K = $5K)")
    prices = {'TQQQ': Decimal('50.00'), 'TMF': Decimal('20.00')}
    equity = Decimal('100000')

    # Small trade (below threshold)
    small_diff = {'TQQQ': 10}  # $500 = 0.5%
    filtered = executor.filter_by_threshold(small_diff, current, prices, equity)
    print(f"  Small trade (0.5%): {filtered}")
    assert filtered == {}  # Filtered out

    # Large trade (above threshold)
    large_diff = {'TQQQ': 200}  # $10K = 10%
    filtered = executor.filter_by_threshold(large_diff, current, prices, equity)
    print(f"  Large trade (10%): {filtered}")
    assert filtered == {'TQQQ': 200}  # Kept

    # Test 3: Log hypothetical orders
    print("\nTest 3: Log hypothetical orders")
    orders = executor.log_hypothetical_orders(diffs, prices)
    print(f"  Logged {len(orders)} orders:")
    for order in orders:
        print(f"    {order['action']} {order['qty']} {order['symbol']} @ ${order['price']}")

    # Test 4: Complete dry-run workflow
    print("\nTest 4: Complete dry-run workflow")
    orders, final_diffs = executor.execute_dry_run(
        current, target, prices, equity
    )
    print(f"  Orders: {len(orders)}")
    print(f"  Final diffs: {final_diffs}")

    print("\n✅ All tests passed - hypothetical orders logged to logs/live_trades.csv")


if __name__ == "__main__":
    main()
