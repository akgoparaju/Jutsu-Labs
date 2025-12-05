"""
Fill Reconciliation - Compare local trades with Schwab records.

This module validates trade execution by comparing local database records
with Schwab order history. Identifies discrepancies for investigation
and generates reconciliation reports.

Version: 2.0 (PRD v2.0.1 Compliant - Phase 2 Task 6.2.3)
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta, time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session
from sqlalchemy import desc

from jutsu_engine.data.models import LiveTrade
from jutsu_engine.live.mode import TradingMode

logger = logging.getLogger('LIVE.RECONCILIATION')


# Default reconciliation time: 17:00 ET (1 hour after close)
RECONCILIATION_TIME = time(17, 0)


@dataclass
class ReconciliationResult:
    """
    Result of trade reconciliation between local and Schwab records.

    Attributes:
        timestamp: When reconciliation was performed
        date_range: (start_date, end_date) of reconciled period
        matched: List of trades that match between local and Schwab
        missing_local: Trades in Schwab but not in local database
        missing_schwab: Trades in local database but not found in Schwab
        price_discrepancies: Trades with fill price mismatches
        quantity_discrepancies: Trades with quantity mismatches
        total_local: Total trades in local database for period
        total_schwab: Total trades in Schwab for period
        is_reconciled: True if no discrepancies found
    """
    timestamp: datetime
    date_range: Tuple[datetime, datetime]
    matched: List[Dict] = field(default_factory=list)
    missing_local: List[Dict] = field(default_factory=list)
    missing_schwab: List[Dict] = field(default_factory=list)
    price_discrepancies: List[Dict] = field(default_factory=list)
    quantity_discrepancies: List[Dict] = field(default_factory=list)
    total_local: int = 0
    total_schwab: int = 0
    is_reconciled: bool = True

    @property
    def discrepancy_count(self) -> int:
        """Total number of discrepancies found."""
        return (
            len(self.missing_local) +
            len(self.missing_schwab) +
            len(self.price_discrepancies) +
            len(self.quantity_discrepancies)
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'date_range': {
                'start': self.date_range[0].isoformat(),
                'end': self.date_range[1].isoformat()
            },
            'summary': {
                'total_local': self.total_local,
                'total_schwab': self.total_schwab,
                'matched': len(self.matched),
                'missing_local': len(self.missing_local),
                'missing_schwab': len(self.missing_schwab),
                'price_discrepancies': len(self.price_discrepancies),
                'quantity_discrepancies': len(self.quantity_discrepancies),
                'is_reconciled': self.is_reconciled
            },
            'discrepancies': {
                'missing_local': self.missing_local,
                'missing_schwab': [
                    {
                        'symbol': t.symbol,
                        'action': t.action,
                        'quantity': t.quantity,
                        'order_id': t.schwab_order_id,
                        'timestamp': t.timestamp.isoformat() if t.timestamp else None
                    }
                    for t in self.missing_schwab
                ],
                'price_discrepancies': self.price_discrepancies,
                'quantity_discrepancies': self.quantity_discrepancies
            }
        }


class FillReconciler:
    """
    Reconcile local trades with Schwab order history.

    Compares trades logged in local database with Schwab API order
    history to ensure accuracy and identify discrepancies.

    Features:
        - Daily reconciliation at 17:00 ET
        - Match by Schwab order ID
        - Detect missing trades (both directions)
        - Identify price and quantity mismatches
        - Generate reconciliation reports
        - Alert on discrepancies

    Usage:
        reconciler = FillReconciler(session, client, account_hash)

        # Run daily reconciliation
        result = reconciler.reconcile_today()

        # Check for discrepancies
        if not result.is_reconciled:
            for missing in result.missing_local:
                print(f"Missing in local: {missing}")
    """

    def __init__(
        self,
        session: Session,
        client,
        account_hash: str,
        mode: TradingMode = TradingMode.ONLINE_LIVE,
        price_tolerance_pct: Decimal = Decimal('0.01')
    ):
        """
        Initialize fill reconciler.

        Args:
            session: SQLAlchemy database session
            client: Authenticated schwab-py client
            account_hash: Schwab account hash
            mode: Trading mode to reconcile (default: ONLINE_LIVE)
            price_tolerance_pct: Acceptable price difference % (default: 0.01%)
        """
        self.session = session
        self.client = client
        self.account_hash = account_hash
        self.mode = mode
        self.price_tolerance_pct = price_tolerance_pct

        logger.info(
            f"FillReconciler initialized: mode={mode.value}, "
            f"price_tolerance={price_tolerance_pct}%"
        )

    def reconcile_today(self) -> ReconciliationResult:
        """
        Reconcile today's trades.

        Compares local trades from today with Schwab order history.

        Returns:
            ReconciliationResult with matched and discrepant trades
        """
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(today, time.min).replace(tzinfo=timezone.utc)
        end = datetime.combine(today, time.max).replace(tzinfo=timezone.utc)

        return self.reconcile_period(start, end)

    def reconcile_period(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> ReconciliationResult:
        """
        Reconcile trades for a specific date range.

        Args:
            start_date: Start of reconciliation period
            end_date: End of reconciliation period

        Returns:
            ReconciliationResult with matched and discrepant trades
        """
        logger.info(
            f"Starting reconciliation: {start_date.date()} to {end_date.date()}"
        )

        # Initialize result
        result = ReconciliationResult(
            timestamp=datetime.now(timezone.utc),
            date_range=(start_date, end_date)
        )

        # Fetch local trades
        local_trades = self._fetch_local_trades(start_date, end_date)
        result.total_local = len(local_trades)
        logger.info(f"Found {len(local_trades)} local trades")

        # Fetch Schwab order history
        schwab_orders = self._fetch_schwab_orders(start_date, end_date)
        result.total_schwab = len(schwab_orders)
        logger.info(f"Found {len(schwab_orders)} Schwab orders")

        # Build lookup by Schwab order ID
        local_by_order_id = {
            t.schwab_order_id: t for t in local_trades
            if t.schwab_order_id
        }
        schwab_by_order_id = {
            o['orderId']: o for o in schwab_orders
            if o.get('orderId')
        }

        # Match trades
        for order_id, schwab_order in schwab_by_order_id.items():
            local_trade = local_by_order_id.get(str(order_id))

            if local_trade is None:
                # Trade in Schwab but not in local database
                result.missing_local.append(self._schwab_order_to_dict(schwab_order))
                continue

            # Check for discrepancies
            discrepancy = self._compare_trades(local_trade, schwab_order)

            if discrepancy is None:
                result.matched.append({
                    'order_id': order_id,
                    'symbol': local_trade.symbol,
                    'action': local_trade.action,
                    'quantity': local_trade.quantity,
                    'fill_price': float(local_trade.fill_price) if local_trade.fill_price else None
                })
            else:
                if discrepancy['type'] == 'price':
                    result.price_discrepancies.append(discrepancy)
                elif discrepancy['type'] == 'quantity':
                    result.quantity_discrepancies.append(discrepancy)

        # Check for trades in local but not in Schwab
        schwab_order_ids = set(str(oid) for oid in schwab_by_order_id.keys())
        for trade in local_trades:
            if trade.schwab_order_id and trade.schwab_order_id not in schwab_order_ids:
                result.missing_schwab.append(trade)

        # Determine if fully reconciled
        result.is_reconciled = result.discrepancy_count == 0

        # Log summary
        self._log_reconciliation_summary(result)

        return result

    def _fetch_local_trades(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[LiveTrade]:
        """
        Fetch local trades for the given period.

        Args:
            start_date: Start of period
            end_date: End of period

        Returns:
            List of LiveTrade records
        """
        return self.session.query(LiveTrade).filter(
            LiveTrade.mode == self.mode.db_value,
            LiveTrade.timestamp >= start_date,
            LiveTrade.timestamp <= end_date
        ).order_by(LiveTrade.timestamp).all()

    def _fetch_schwab_orders(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """
        Fetch Schwab order history for the given period.

        Args:
            start_date: Start of period
            end_date: End of period

        Returns:
            List of Schwab order dictionaries
        """
        try:
            # Schwab API expects date in specific format
            from_date = start_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            to_date = end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')

            response = self.client.get_orders_for_account(
                account_hash=self.account_hash,
                from_entered_time=from_date,
                to_entered_time=to_date,
                status='FILLED'
            )

            if hasattr(response, 'json'):
                orders = response.json()
            else:
                orders = response

            # Filter to only filled equity orders
            filled_orders = [
                o for o in orders
                if o.get('status') == 'FILLED'
                and o.get('orderType') == 'MARKET'
            ]

            return filled_orders

        except Exception as e:
            logger.error(f"Failed to fetch Schwab orders: {e}")
            return []

    def _compare_trades(
        self,
        local_trade: LiveTrade,
        schwab_order: Dict
    ) -> Optional[Dict]:
        """
        Compare local trade with Schwab order for discrepancies.

        Args:
            local_trade: Local LiveTrade record
            schwab_order: Schwab order dictionary

        Returns:
            Discrepancy dict if mismatch found, None if matched
        """
        # Extract Schwab fill details
        schwab_fill = self._extract_fill_from_order(schwab_order)

        if schwab_fill is None:
            return {
                'type': 'parse_error',
                'order_id': schwab_order.get('orderId'),
                'message': 'Could not extract fill details from Schwab order'
            }

        # Compare quantities
        if local_trade.quantity != schwab_fill['quantity']:
            return {
                'type': 'quantity',
                'order_id': schwab_order.get('orderId'),
                'symbol': local_trade.symbol,
                'local_quantity': local_trade.quantity,
                'schwab_quantity': schwab_fill['quantity']
            }

        # Compare prices (with tolerance)
        if local_trade.fill_price is not None and schwab_fill['price'] is not None:
            local_price = Decimal(str(local_trade.fill_price))
            schwab_price = Decimal(str(schwab_fill['price']))

            if local_price > 0:
                price_diff_pct = abs(schwab_price - local_price) / local_price * 100

                if price_diff_pct > self.price_tolerance_pct:
                    return {
                        'type': 'price',
                        'order_id': schwab_order.get('orderId'),
                        'symbol': local_trade.symbol,
                        'local_price': float(local_price),
                        'schwab_price': float(schwab_price),
                        'difference_pct': float(price_diff_pct)
                    }

        return None  # No discrepancy

    def _extract_fill_from_order(self, schwab_order: Dict) -> Optional[Dict]:
        """
        Extract fill details from Schwab order.

        Args:
            schwab_order: Schwab order dictionary

        Returns:
            Dictionary with symbol, action, quantity, price or None
        """
        try:
            # Get order legs
            legs = schwab_order.get('orderLegCollection', [])
            if not legs:
                return None

            leg = legs[0]
            instrument = leg.get('instrument', {})

            # Get execution details
            activities = schwab_order.get('orderActivityCollection', [])
            price = None
            filled_qty = 0

            for activity in activities:
                exec_legs = activity.get('executionLegs', [])
                for exec_leg in exec_legs:
                    price = exec_leg.get('price')
                    filled_qty += exec_leg.get('quantity', 0)

            return {
                'symbol': instrument.get('symbol'),
                'action': leg.get('instruction'),
                'quantity': filled_qty or schwab_order.get('filledQuantity', 0),
                'price': price
            }

        except Exception as e:
            logger.error(f"Error extracting fill from order: {e}")
            return None

    def _schwab_order_to_dict(self, schwab_order: Dict) -> Dict:
        """
        Convert Schwab order to standardized dictionary.

        Args:
            schwab_order: Raw Schwab order dictionary

        Returns:
            Standardized dictionary for logging
        """
        fill = self._extract_fill_from_order(schwab_order)
        return {
            'order_id': schwab_order.get('orderId'),
            'symbol': fill['symbol'] if fill else None,
            'action': fill['action'] if fill else None,
            'quantity': fill['quantity'] if fill else None,
            'fill_price': fill['price'] if fill else None,
            'entered_time': schwab_order.get('enteredTime'),
            'close_time': schwab_order.get('closeTime')
        }

    def _log_reconciliation_summary(self, result: ReconciliationResult) -> None:
        """
        Log reconciliation summary.

        Args:
            result: ReconciliationResult to log
        """
        if result.is_reconciled:
            logger.info(
                f"Reconciliation PASSED: {len(result.matched)} trades matched, "
                f"0 discrepancies"
            )
        else:
            logger.warning(
                f"Reconciliation FAILED: {result.discrepancy_count} discrepancies found"
            )

            if result.missing_local:
                logger.warning(
                    f"  - Missing in local database: {len(result.missing_local)}"
                )
                for trade in result.missing_local[:5]:  # Log first 5
                    logger.warning(f"    {trade}")

            if result.missing_schwab:
                logger.warning(
                    f"  - Missing in Schwab: {len(result.missing_schwab)}"
                )
                for trade in result.missing_schwab[:5]:
                    logger.warning(
                        f"    {trade.symbol} {trade.action} {trade.quantity} "
                        f"(order_id={trade.schwab_order_id})"
                    )

            if result.price_discrepancies:
                logger.warning(
                    f"  - Price discrepancies: {len(result.price_discrepancies)}"
                )
                for disc in result.price_discrepancies[:5]:
                    logger.warning(
                        f"    {disc['symbol']}: local=${disc['local_price']:.2f}, "
                        f"schwab=${disc['schwab_price']:.2f} ({disc['difference_pct']:.3f}%)"
                    )

            if result.quantity_discrepancies:
                logger.warning(
                    f"  - Quantity discrepancies: {len(result.quantity_discrepancies)}"
                )
                for disc in result.quantity_discrepancies[:5]:
                    logger.warning(
                        f"    {disc['symbol']}: local={disc['local_quantity']}, "
                        f"schwab={disc['schwab_quantity']}"
                    )

    def generate_report(
        self,
        result: ReconciliationResult,
        format: str = 'text'
    ) -> str:
        """
        Generate reconciliation report.

        Args:
            result: ReconciliationResult to report on
            format: Report format ('text' or 'json')

        Returns:
            Formatted report string
        """
        if format == 'json':
            import json
            return json.dumps(result.to_dict(), indent=2)

        # Text format
        lines = [
            "=" * 60,
            "FILL RECONCILIATION REPORT",
            "=" * 60,
            f"Timestamp: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Period: {result.date_range[0].date()} to {result.date_range[1].date()}",
            "",
            "SUMMARY",
            "-" * 40,
            f"Local trades:     {result.total_local}",
            f"Schwab orders:    {result.total_schwab}",
            f"Matched:          {len(result.matched)}",
            f"Missing (local):  {len(result.missing_local)}",
            f"Missing (Schwab): {len(result.missing_schwab)}",
            f"Price issues:     {len(result.price_discrepancies)}",
            f"Quantity issues:  {len(result.quantity_discrepancies)}",
            "",
            f"STATUS: {'RECONCILED' if result.is_reconciled else 'DISCREPANCIES FOUND'}",
            ""
        ]

        # Add discrepancy details
        if not result.is_reconciled:
            lines.extend([
                "DISCREPANCY DETAILS",
                "-" * 40
            ])

            if result.missing_local:
                lines.append("\nMissing in local database:")
                for trade in result.missing_local:
                    lines.append(
                        f"  - {trade['symbol']} {trade['action']} "
                        f"{trade['quantity']} @ ${trade['fill_price']:.2f} "
                        f"(order_id={trade['order_id']})"
                    )

            if result.missing_schwab:
                lines.append("\nMissing in Schwab:")
                for trade in result.missing_schwab:
                    lines.append(
                        f"  - {trade.symbol} {trade.action} {trade.quantity} "
                        f"(order_id={trade.schwab_order_id})"
                    )

            if result.price_discrepancies:
                lines.append("\nPrice discrepancies:")
                for disc in result.price_discrepancies:
                    lines.append(
                        f"  - {disc['symbol']}: local=${disc['local_price']:.2f}, "
                        f"schwab=${disc['schwab_price']:.2f} "
                        f"(diff={disc['difference_pct']:.3f}%)"
                    )

            if result.quantity_discrepancies:
                lines.append("\nQuantity discrepancies:")
                for disc in result.quantity_discrepancies:
                    lines.append(
                        f"  - {disc['symbol']}: local={disc['local_quantity']}, "
                        f"schwab={disc['schwab_quantity']}"
                    )

        lines.append("=" * 60)
        return "\n".join(lines)

    def is_reconciliation_time(self, current_time: Optional[time] = None) -> bool:
        """
        Check if current time is reconciliation time (17:00 ET).

        Args:
            current_time: Time to check (defaults to now)

        Returns:
            True if within reconciliation window (17:00-17:15 ET)
        """
        if current_time is None:
            from zoneinfo import ZoneInfo
            et = ZoneInfo('America/New_York')
            current_time = datetime.now(et).time()

        # Reconciliation window: 17:00 to 17:15 ET
        window_start = RECONCILIATION_TIME
        window_end = time(17, 15)

        return window_start <= current_time <= window_end


def main():
    """Test FillReconciler functionality."""
    logging.basicConfig(level=logging.INFO)

    print("\n>>> FillReconciler Test")
    print("This module requires authenticated Schwab API client and database session.")
    print("\nCore functionality:")
    print("  - Compare local trades with Schwab order history")
    print("  - Identify missing trades (both directions)")
    print("  - Detect price and quantity discrepancies")
    print("  - Generate reconciliation reports")
    print("\nReconciliation time: 17:00 ET (1 hour after close)")
    print("\nUsage:")
    print("  reconciler = FillReconciler(session, client, account_hash)")
    print("  result = reconciler.reconcile_today()")
    print("  report = reconciler.generate_report(result)")


if __name__ == "__main__":
    main()
