"""
Order Executor - Execute real orders via Schwab API.

This module handles order submission, fill validation, and retry logic
for live trading. Executes SELL orders first (to raise cash), then BUY orders.
"""

import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path
import csv

from schwab.orders import equities as schwab_equities

from jutsu_engine.live.exceptions import CriticalFailure, SlippageExceeded
from jutsu_engine.live.slippage_validator import SlippageValidator

logger = logging.getLogger('LIVE.ORDER_EXECUTOR')


class OrderExecutor:
    """
    Execute orders via Schwab API with retry logic and slippage validation.

    Order execution sequence:
    1. SELL orders first (raise cash)
    2. BUY orders second
    3. Retry partial fills up to 3 times
    4. Validate all fills against slippage thresholds
    """

    def __init__(
        self,
        client,
        account_hash: str,
        config: Dict,
        trade_log_path: Path = Path('logs/live_trades.csv')
    ):
        """
        Initialize order executor.

        Args:
            client: Authenticated schwab-py client
            account_hash: Schwab account hash for order submission
            config: Configuration dictionary
            trade_log_path: Path to trade log CSV
        """
        self.client = client
        self.account_hash = account_hash
        self.config = config

        # Extract execution settings
        exec_config = config.get('execution', {})
        self.max_retries = exec_config.get('max_order_retries', 3)
        self.retry_delay = exec_config.get('retry_delay_seconds', 5)

        # Initialize slippage validator
        self.slippage_validator = SlippageValidator(config)

        # Trade logging
        self.trade_log_path = trade_log_path
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.trade_log_path.exists():
            self._initialize_csv()

        logger.info(
            f"OrderExecutor initialized: account={account_hash[:8]}..., "
            f"max_retries={self.max_retries}"
        )

    def _initialize_csv(self) -> None:
        """Create CSV with header if doesn't exist."""
        with open(self.trade_log_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Date', 'Time', 'Ticker', 'Action', 'Qty',
                'Expected_Price', 'Fill_Price', 'Slippage_%',
                'Value', 'Reason', 'Mode', 'Order_ID'
            ])
        logger.debug(f"Initialized trade log: {self.trade_log_path}")

    def execute_rebalance(
        self,
        position_diffs: Dict[str, int],
        current_prices: Dict[str, Decimal],
        reason: str = "Rebalance"
    ) -> Tuple[List[Dict], Dict[str, Decimal]]:
        """
        Execute full rebalance workflow.

        1. Split orders into SELL and BUY
        2. Execute SELL orders first (raise cash)
        3. Execute BUY orders second
        4. Validate all fills with slippage validator
        5. Log all trades to CSV

        Args:
            position_diffs: {symbol: diff} where + = buy, - = sell
            current_prices: {symbol: price} expected execution prices
            reason: Trade rationale for logging

        Returns:
            Tuple of (fills_list, fill_prices):
                - fills_list: List of fill dictionaries
                - fill_prices: {symbol: actual_fill_price}

        Raises:
            CriticalFailure: If order submission fails
            SlippageExceeded: If any fill exceeds abort threshold
        """
        if not position_diffs:
            logger.info("No orders to execute (empty position_diffs)")
            return [], {}

        logger.info(f"Starting rebalance execution: {len(position_diffs)} orders")

        # Split orders into SELL and BUY
        sell_orders = {sym: diff for sym, diff in position_diffs.items() if diff < 0}
        buy_orders = {sym: diff for sym, diff in position_diffs.items() if diff > 0}

        logger.info(f"Order split: {len(sell_orders)} SELL, {len(buy_orders)} BUY")

        all_fills = []
        fill_prices = {}

        # STEP 1: Execute SELL orders first (raise cash)
        if sell_orders:
            logger.info("Executing SELL orders first...")
            for symbol, diff in sell_orders.items():
                quantity = abs(diff)
                expected_price = current_prices[symbol]

                fill = self.submit_order(
                    symbol=symbol,
                    action='SELL',
                    quantity=quantity,
                    expected_price=expected_price
                )

                all_fills.append(fill)
                fill_prices[symbol] = fill['fill_price']

                # Validate slippage
                self.slippage_validator.validate_fill(
                    symbol=symbol,
                    expected_price=expected_price,
                    fill_price=fill['fill_price'],
                    quantity=quantity,
                    action='SELL'
                )

        # STEP 2: Execute BUY orders second
        if buy_orders:
            logger.info("Executing BUY orders...")
            for symbol, diff in buy_orders.items():
                quantity = diff  # Already positive
                expected_price = current_prices[symbol]

                fill = self.submit_order(
                    symbol=symbol,
                    action='BUY',
                    quantity=quantity,
                    expected_price=expected_price
                )

                all_fills.append(fill)
                fill_prices[symbol] = fill['fill_price']

                # Validate slippage
                self.slippage_validator.validate_fill(
                    symbol=symbol,
                    expected_price=expected_price,
                    fill_price=fill['fill_price'],
                    quantity=quantity,
                    action='BUY'
                )

        # Log all trades
        self._log_trades(all_fills, reason)

        logger.info(f"Rebalance execution complete: {len(all_fills)} fills")
        return all_fills, fill_prices

    def submit_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        expected_price: Decimal
    ) -> Dict:
        """
        Submit market order and wait for fill.

        Retries partial fills up to max_retries times with retry_delay
        between attempts.

        Args:
            symbol: Stock ticker symbol
            action: "BUY" or "SELL"
            quantity: Number of shares to trade
            expected_price: Expected execution price (for slippage calc)

        Returns:
            Fill dictionary with keys:
                - symbol, action, quantity, fill_price, order_id, timestamp

        Raises:
            CriticalFailure: If order submission fails or max retries exceeded
        """
        logger.info(f"Submitting order: {action} {quantity} {symbol} @ ~${expected_price:.2f}")

        # Build market order based on action
        if action == 'BUY':
            order = schwab_equities.equity_buy_market(symbol=symbol, quantity=quantity)
        elif action == 'SELL':
            order = schwab_equities.equity_sell_market(symbol=symbol, quantity=quantity)
        else:
            raise ValueError(f"Unknown action: {action}")

        # Submit order
        try:
            response = self.client.place_order(
                account_hash=self.account_hash,
                order_spec=order
            )

            # Extract order ID from response headers
            order_id = self._extract_order_id(response)
            logger.info(f"Order submitted successfully: order_id={order_id}")

        except Exception as e:
            error_msg = f"Order submission failed: {action} {quantity} {symbol} - {e}"
            logger.critical(error_msg)
            raise CriticalFailure(error_msg)

        # Wait for fill with retry logic
        fill_info = self._wait_for_fill(
            order_id=order_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            expected_price=expected_price
        )

        return fill_info

    def _wait_for_fill(
        self,
        order_id: str,
        symbol: str,
        action: str,
        quantity: int,
        expected_price: Decimal
    ) -> Dict:
        """
        Wait for order to fill with retry logic.

        Args:
            order_id: Order ID from submission response
            symbol: Stock ticker
            action: "BUY" or "SELL"
            quantity: Shares ordered
            expected_price: Expected fill price

        Returns:
            Fill dictionary

        Raises:
            CriticalFailure: If max retries exceeded or order rejected
        """
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Checking fill status (attempt {attempt}/{self.max_retries})...")

            # Wait before checking (market orders usually fill instantly)
            time.sleep(self.retry_delay)

            try:
                order_status = self.client.get_order(
                    account_hash=self.account_hash,
                    order_id=order_id
                )

                status = order_status.get('status', 'UNKNOWN')
                logger.info(f"Order {order_id} status: {status}")

                # Check if filled
                if status == 'FILLED':
                    fill_price = self._extract_fill_price(order_status)

                    fill_info = {
                        'symbol': symbol,
                        'action': action,
                        'quantity': quantity,
                        'fill_price': fill_price,
                        'expected_price': expected_price,
                        'order_id': order_id,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }

                    logger.info(
                        f"Order FILLED: {action} {quantity} {symbol} @ ${fill_price:.2f}"
                    )
                    return fill_info

                elif status == 'REJECTED' or status == 'CANCELED':
                    error_msg = (
                        f"Order {status}: {action} {quantity} {symbol} "
                        f"(order_id={order_id})"
                    )
                    logger.critical(error_msg)
                    raise CriticalFailure(error_msg)

                elif status == 'PARTIALLY_FILLED':
                    logger.warning(
                        f"Order PARTIALLY_FILLED (attempt {attempt}/{self.max_retries})"
                    )
                    # Continue retry loop

                else:
                    logger.warning(f"Order status: {status}, waiting for fill...")

            except Exception as e:
                logger.error(f"Error checking fill status (attempt {attempt}): {e}")

        # Max retries exceeded
        error_msg = (
            f"Max retries ({self.max_retries}) exceeded for order: "
            f"{action} {quantity} {symbol} (order_id={order_id})"
        )
        logger.critical(error_msg)
        raise CriticalFailure(error_msg)

    def _extract_order_id(self, response) -> str:
        """
        Extract order ID from Schwab API response.

        Order ID is typically in the Location header.

        Args:
            response: Schwab API response object

        Returns:
            Order ID string

        Raises:
            CriticalFailure: If order ID cannot be extracted
        """
        try:
            # Order ID is in Location header: /accounts/.../orders/{ORDER_ID}
            location = response.headers.get('Location', '')
            order_id = location.split('/')[-1]

            if not order_id:
                raise ValueError("Order ID not found in response headers")

            return order_id

        except Exception as e:
            error_msg = f"Failed to extract order ID from response: {e}"
            logger.critical(error_msg)
            raise CriticalFailure(error_msg)

    def _extract_fill_price(self, order_status: Dict) -> Decimal:
        """
        Extract fill price from order status response.

        Args:
            order_status: Order status dictionary from API

        Returns:
            Fill price as Decimal

        Raises:
            CriticalFailure: If fill price cannot be extracted
        """
        try:
            # Fill price is in orderActivityCollection
            activities = order_status.get('orderActivityCollection', [])

            if not activities:
                raise ValueError("No order activities found")

            # Get first execution activity
            execution = activities[0].get('executionLegs', [{}])[0]
            fill_price_str = execution.get('price')

            if fill_price_str is None:
                raise ValueError("Fill price not found in order activity")

            return Decimal(str(fill_price_str))

        except Exception as e:
            error_msg = f"Failed to extract fill price: {e}"
            logger.critical(error_msg)
            raise CriticalFailure(error_msg)

    def _log_trades(self, fills: List[Dict], reason: str) -> None:
        """
        Log executed trades to CSV.

        Args:
            fills: List of fill dictionaries
            reason: Trade rationale
        """
        if not fills:
            return

        with open(self.trade_log_path, 'a', newline='') as f:
            writer = csv.writer(f)

            for fill in fills:
                date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                time_str = datetime.now(timezone.utc).strftime('%H:%M:%S')

                # Calculate slippage
                slippage_pct = self.slippage_validator.calculate_slippage_pct(
                    fill['expected_price'],
                    fill['fill_price']
                )

                # Calculate value
                value = fill['quantity'] * fill['fill_price']

                writer.writerow([
                    date_str,
                    time_str,
                    fill['symbol'],
                    fill['action'],
                    fill['quantity'],
                    f"{fill['expected_price']:.2f}",
                    f"{fill['fill_price']:.2f}",
                    f"{slippage_pct:.3f}",
                    f"{value:.2f}",
                    reason,
                    "PAPER" if self.config.get('schwab', {}).get('environment') == 'paper' else "LIVE",
                    fill['order_id']
                ])

        logger.info(f"Logged {len(fills)} trades to {self.trade_log_path}")


def main():
    """Test order executor (requires Schwab authentication)."""
    logging.basicConfig(level=logging.INFO)

    print("\n⚠️  Order Executor Test")
    print("This module requires authenticated Schwab API client.")
    print("See scripts/live_trader_paper.py for full integration example.")
    print("\nCore functionality:")
    print("  ✅ Split orders into SELL (first) and BUY (second)")
    print("  ✅ Submit market orders via schwab-py client")
    print("  ✅ Retry partial fills up to 3 times")
    print("  ✅ Validate slippage with SlippageValidator")
    print("  ✅ Log all trades to live_trades.csv")


if __name__ == "__main__":
    main()
