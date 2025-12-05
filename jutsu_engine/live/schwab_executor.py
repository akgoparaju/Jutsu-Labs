"""
Schwab Order Executor - Execute real orders via Schwab API with database logging.

This module implements ExecutorInterface with database persistence,
replacing the legacy CSV-based OrderExecutor. Provides production-ready
order execution with slippage validation, retry logic, and audit trail.

Version: 2.0 (PRD v2.0.1 Compliant - Phase 2)
"""

import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone

from schwab import order_spec
from sqlalchemy.orm import Session

from jutsu_engine.live.executor_router import ExecutorInterface
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.live.exceptions import CriticalFailure, SlippageExceeded
from jutsu_engine.data.models import LiveTrade

logger = logging.getLogger('LIVE.SCHWAB_EXECUTOR')


class SchwabOrderExecutor(ExecutorInterface):
    """
    Execute real orders via Schwab API with database logging.

    Implements ExecutorInterface with full database persistence for
    audit trail and reconciliation. Replaces legacy CSV-based OrderExecutor.

    Features:
        - ExecutorInterface compliance
        - SQLite database logging (LiveTrade model)
        - Slippage validation with configurable thresholds
        - Slippage abort mechanism (default 1%)
        - SELL-first, BUY-second order sequence
        - Retry logic for partial fills
        - Schwab order ID capture
        - Strategy context persistence

    Usage:
        executor = SchwabOrderExecutor(client, account_hash, session, config)
        fills, fill_prices = executor.execute_rebalance(
            position_diffs={'TQQQ': 100, 'TMF': -50},
            current_prices={'TQQQ': Decimal('50.00'), 'TMF': Decimal('10.00')},
            reason="Rebalance",
            strategy_context={'current_cell': 1, 'trend_state': 'BullStrong', 'vol_state': 'Low'}
        )
    """

    def __init__(
        self,
        client,
        account_hash: str,
        session: Session,
        config: Dict[str, Any]
    ):
        """
        Initialize Schwab order executor.

        Args:
            client: Authenticated schwab-py client
            account_hash: Schwab account hash for order submission
            session: SQLAlchemy database session
            config: Configuration dictionary with execution settings:
                    - execution.max_order_retries: Max retries for partial fills (default: 3)
                    - execution.retry_delay_seconds: Delay between retries (default: 5)
                    - execution.slippage_abort_pct: Abort threshold (default: 1.0)
                    - execution.slippage_warning_pct: Warning threshold (default: 0.3)
                    - execution.max_slippage_pct: Max allowed slippage (default: 0.5)
        """
        self.client = client
        self.account_hash = account_hash
        self.session = session
        self.config = config
        self._mode = TradingMode.ONLINE_LIVE

        # Extract execution settings
        exec_config = config.get('execution', {})
        self.max_retries = exec_config.get('max_order_retries', 3)
        self.retry_delay = exec_config.get('retry_delay_seconds', 5)

        # Slippage thresholds
        self.slippage_abort_pct = Decimal(str(exec_config.get('slippage_abort_pct', 1.0)))
        self.slippage_warning_pct = Decimal(str(exec_config.get('slippage_warning_pct', 0.3)))
        self.max_slippage_pct = Decimal(str(exec_config.get('max_slippage_pct', 0.5)))

        logger.info(
            f"SchwabOrderExecutor initialized: account={account_hash[:8]}..., "
            f"max_retries={self.max_retries}, abort_threshold={self.slippage_abort_pct}%"
        )

    def get_mode(self) -> TradingMode:
        """Return the trading mode of this executor."""
        return self._mode

    def execute_rebalance(
        self,
        position_diffs: Dict[str, int],
        current_prices: Dict[str, Decimal],
        reason: str = "Rebalance",
        strategy_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict], Dict[str, Decimal]]:
        """
        Execute real rebalance via Schwab API with database logging.

        SELL orders executed first (raise cash), then BUY orders.
        All fills validated against slippage thresholds.
        Trades logged to database with strategy context.

        Args:
            position_diffs: {symbol: diff} where positive = buy, negative = sell
            current_prices: {symbol: Decimal} expected execution prices
            reason: Trade rationale for logging
            strategy_context: Optional strategy state for logging

        Returns:
            Tuple of:
                - fills: List of fill dictionaries with strategy context
                - fill_prices: {symbol: actual_fill_price}

        Raises:
            CriticalFailure: If order submission fails
            SlippageExceeded: If fill exceeds abort threshold
        """
        if not position_diffs:
            logger.info("No orders to execute (empty position_diffs)")
            return [], {}

        logger.info(f"Starting LIVE rebalance execution: {len(position_diffs)} orders")

        # Split orders into SELL and BUY
        sell_orders = {sym: diff for sym, diff in position_diffs.items() if diff < 0}
        buy_orders = {sym: diff for sym, diff in position_diffs.items() if diff > 0}

        logger.info(f"Order split: {len(sell_orders)} SELL, {len(buy_orders)} BUY")

        all_fills = []
        fill_prices = {}
        context = strategy_context or {}

        # STEP 1: Execute SELL orders first (raise cash)
        if sell_orders:
            logger.info("Executing SELL orders first...")
            for symbol, diff in sell_orders.items():
                quantity = abs(diff)
                expected_price = current_prices[symbol]

                fill = self._submit_and_validate_order(
                    symbol=symbol,
                    action='SELL',
                    quantity=quantity,
                    expected_price=expected_price,
                    reason=reason,
                    context=context
                )

                all_fills.append(fill)
                fill_prices[symbol] = fill['fill_price']

        # STEP 2: Execute BUY orders second
        if buy_orders:
            logger.info("Executing BUY orders...")
            for symbol, diff in buy_orders.items():
                quantity = diff  # Already positive
                expected_price = current_prices[symbol]

                fill = self._submit_and_validate_order(
                    symbol=symbol,
                    action='BUY',
                    quantity=quantity,
                    expected_price=expected_price,
                    reason=reason,
                    context=context
                )

                all_fills.append(fill)
                fill_prices[symbol] = fill['fill_price']

        logger.info(f"LIVE rebalance complete: {len(all_fills)} fills")
        return all_fills, fill_prices

    def _submit_and_validate_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        expected_price: Decimal,
        reason: str,
        context: Dict[str, Any]
    ) -> Dict:
        """
        Submit order, validate slippage, and log to database.

        Args:
            symbol: Stock ticker symbol
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            expected_price: Expected execution price
            reason: Trade rationale
            context: Strategy context

        Returns:
            Fill dictionary with all trade details

        Raises:
            CriticalFailure: If order submission fails
            SlippageExceeded: If slippage exceeds abort threshold
        """
        # Submit order to Schwab
        fill_info = self._submit_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            expected_price=expected_price
        )

        # Validate slippage (may raise SlippageExceeded)
        slippage_pct = self._validate_slippage(
            symbol=symbol,
            action=action,
            quantity=quantity,
            expected_price=expected_price,
            fill_price=fill_info['fill_price']
        )

        # Enrich fill with context
        fill_info['mode'] = self._mode.db_value
        fill_info['reason'] = reason
        fill_info['slippage_pct'] = slippage_pct
        fill_info['cell'] = context.get('current_cell')
        fill_info['trend_state'] = context.get('trend_state')
        fill_info['vol_state'] = context.get('vol_state')
        fill_info['t_norm'] = context.get('t_norm')
        fill_info['z_score'] = context.get('z_score')

        # Log to database
        self._log_trade_to_database(fill_info)

        return fill_info

    def _submit_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        expected_price: Decimal
    ) -> Dict:
        """
        Submit market order and wait for fill.

        Args:
            symbol: Stock ticker symbol
            action: "BUY" or "SELL"
            quantity: Number of shares to trade
            expected_price: Expected execution price

        Returns:
            Fill dictionary with keys:
                - symbol, action, quantity, fill_price, expected_price, order_id, timestamp

        Raises:
            CriticalFailure: If order submission fails or max retries exceeded
        """
        logger.info(f"Submitting order: {action} {quantity} {symbol} @ ~${expected_price:.2f}")

        # Build market order
        order = order_spec.market_order(
            symbol=symbol,
            quantity=quantity,
            instruction=action
        )

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

                if hasattr(order_status, 'json'):
                    order_status = order_status.json()

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
                        'timestamp': datetime.now(timezone.utc)
                    }

                    logger.info(
                        f"Order FILLED: {action} {quantity} {symbol} @ ${fill_price:.2f}"
                    )
                    return fill_info

                elif status in ('REJECTED', 'CANCELED'):
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

            except CriticalFailure:
                raise
            except Exception as e:
                logger.error(f"Error checking fill status (attempt {attempt}): {e}")

        # Max retries exceeded
        error_msg = (
            f"Max retries ({self.max_retries}) exceeded for order: "
            f"{action} {quantity} {symbol} (order_id={order_id})"
        )
        logger.critical(error_msg)
        raise CriticalFailure(error_msg)

    def _validate_slippage(
        self,
        symbol: str,
        action: str,
        quantity: int,
        expected_price: Decimal,
        fill_price: Decimal
    ) -> Decimal:
        """
        Validate fill price against slippage thresholds.

        Implements slippage abort mechanism per Task 6.2.2.

        Args:
            symbol: Stock ticker
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            expected_price: Expected execution price
            fill_price: Actual fill price

        Returns:
            Slippage percentage as Decimal

        Raises:
            SlippageExceeded: If slippage exceeds abort threshold
        """
        if expected_price <= 0:
            raise ValueError(f"Invalid expected_price: {expected_price}")

        # Calculate slippage percentage
        slippage_pct = abs(fill_price - expected_price) / expected_price * Decimal('100')
        slippage_cost = abs(fill_price - expected_price) * quantity

        logger.info(
            f"Slippage validation: {action} {quantity} {symbol} @ ${fill_price:.2f} "
            f"(expected ${expected_price:.2f}, slippage {slippage_pct:.3f}%, "
            f"cost ${slippage_cost:.2f})"
        )

        # Check abort threshold (1% default)
        if slippage_pct >= self.slippage_abort_pct:
            error_msg = (
                f"SLIPPAGE ABORT: {symbol} {action} slippage={slippage_pct:.3f}% "
                f"exceeds abort threshold {self.slippage_abort_pct}% "
                f"(expected ${expected_price:.2f}, fill ${fill_price:.2f})"
            )
            logger.critical(error_msg)
            raise SlippageExceeded(error_msg)

        # Check max threshold
        if slippage_pct >= self.max_slippage_pct:
            logger.error(
                f"SLIPPAGE EXCEEDED: {symbol} slippage={slippage_pct:.3f}% > "
                f"max {self.max_slippage_pct}%"
            )

        # Check warning threshold
        elif slippage_pct >= self.slippage_warning_pct:
            logger.warning(
                f"High slippage: {symbol} slippage={slippage_pct:.3f}% > "
                f"warning {self.slippage_warning_pct}%"
            )

        return slippage_pct

    def _log_trade_to_database(self, fill_info: Dict) -> None:
        """
        Log trade to database using LiveTrade model.

        Replaces legacy CSV logging with SQLite persistence.

        Args:
            fill_info: Fill dictionary with all trade details
        """
        try:
            trade = LiveTrade(
                symbol=fill_info['symbol'],
                timestamp=fill_info['timestamp'],
                action=fill_info['action'],
                quantity=fill_info['quantity'],
                target_price=fill_info['expected_price'],
                fill_price=fill_info['fill_price'],
                fill_value=fill_info['quantity'] * fill_info['fill_price'],
                slippage_pct=fill_info.get('slippage_pct'),
                schwab_order_id=fill_info.get('order_id'),
                strategy_cell=fill_info.get('cell'),
                trend_state=fill_info.get('trend_state'),
                vol_state=fill_info.get('vol_state'),
                t_norm=fill_info.get('t_norm'),
                z_score=fill_info.get('z_score'),
                reason=fill_info.get('reason', 'Rebalance'),
                mode=self._mode.db_value
            )

            self.session.add(trade)
            self.session.commit()

            logger.info(
                f"Trade logged to database: {trade.action} {trade.quantity} "
                f"{trade.symbol} @ ${trade.fill_price:.2f} (id={trade.id})"
            )

        except Exception as e:
            logger.error(f"Failed to log trade to database: {e}")
            self.session.rollback()
            # Don't raise - logging failure shouldn't abort trading
            # But log critical for investigation
            logger.critical(f"DATABASE LOGGING FAILED: Trade not recorded - {fill_info}")

    def _extract_order_id(self, response) -> str:
        """
        Extract order ID from Schwab API response.

        Order ID is in the Location header.

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

    def abort_order(self, order_id: str) -> bool:
        """
        Cancel/abort an open order.

        Used when slippage exceeds threshold before fill.

        Args:
            order_id: Schwab order ID to cancel

        Returns:
            True if cancel successful, False otherwise
        """
        try:
            logger.warning(f"Aborting order: {order_id}")
            response = self.client.cancel_order(
                account_hash=self.account_hash,
                order_id=order_id
            )

            if response.status_code in (200, 201, 204):
                logger.info(f"Order {order_id} cancelled successfully")
                return True
            else:
                logger.error(f"Failed to cancel order {order_id}: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Exception cancelling order {order_id}: {e}")
            return False


def main():
    """Test SchwabOrderExecutor (requires Schwab authentication)."""
    logging.basicConfig(level=logging.INFO)

    print("\n>>> SchwabOrderExecutor Test")
    print("This module requires authenticated Schwab API client and database session.")
    print("\nCore functionality:")
    print("  - Implements ExecutorInterface")
    print("  - Database logging (LiveTrade model)")
    print("  - Slippage validation with abort mechanism")
    print("  - SELL-first, BUY-second order sequence")
    print("  - Schwab order ID capture")
    print("  - Strategy context persistence")
    print("\nSlippage thresholds:")
    print("  - Warning: 0.3%")
    print("  - Max: 0.5%")
    print("  - Abort: 1.0%")


if __name__ == "__main__":
    main()
