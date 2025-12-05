"""
Live Order Executor - Execute real orders via Schwab API.

This module wraps OrderExecutor to implement ExecutorInterface,
providing a unified interface for live trading with real order execution.

Version: 2.0 (PRD v2.0.1 Compliant)
"""

import logging
from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
import csv

from jutsu_engine.live.executor_router import ExecutorInterface
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.live.order_executor import OrderExecutor
from jutsu_engine.live.exceptions import CriticalFailure, SlippageExceeded

logger = logging.getLogger('LIVE.LIVE_EXECUTOR')


class LiveOrderExecutor(ExecutorInterface):
    """
    Execute real orders via Schwab API.

    Implements ExecutorInterface by wrapping OrderExecutor with
    additional strategy context logging.

    Features:
        - Real order execution via Schwab API
        - Slippage validation and abort thresholds
        - Strategy context capture for audit trail
        - SELL-first, BUY-second order sequence
        - Retry logic for partial fills

    Usage:
        executor = LiveOrderExecutor(client, account_hash, config)
        fills, fill_prices = executor.execute_rebalance(
            position_diffs={'TQQQ': 100, 'TMF': -50},
            current_prices={'TQQQ': Decimal('50.00'), 'TMF': Decimal('10.00')},
            reason="Rebalance",
            strategy_context={'cell': 1, 'trend_state': 'BullStrong', 'vol_state': 'Low'}
        )
    """

    def __init__(
        self,
        client,
        account_hash: str,
        config: Dict[str, Any],
        trade_log_path: Path = Path('logs/live_trades.csv')
    ):
        """
        Initialize live order executor.

        Args:
            client: Authenticated schwab-py client
            account_hash: Schwab account hash for order submission
            config: Configuration dictionary
            trade_log_path: Path to trade log CSV
        """
        self.client = client
        self.account_hash = account_hash
        self.config = config
        self.trade_log_path = trade_log_path
        self._mode = TradingMode.ONLINE_LIVE

        # Create underlying OrderExecutor
        self._order_executor = OrderExecutor(
            client=client,
            account_hash=account_hash,
            config=config,
            trade_log_path=trade_log_path
        )

        # Ensure directory exists
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"LiveOrderExecutor initialized: account={account_hash[:8]}..."
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
        Execute real rebalance via Schwab API.

        Implements ExecutorInterface.execute_rebalance().

        SELL orders executed first (raise cash), then BUY orders.
        All fills are validated against slippage thresholds.

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

        # Execute via underlying OrderExecutor
        fills, fill_prices = self._order_executor.execute_rebalance(
            position_diffs=position_diffs,
            current_prices=current_prices,
            reason=reason
        )

        # Enrich fills with strategy context
        context = strategy_context or {}
        enriched_fills = self._enrich_fills_with_context(fills, context)

        # Log with strategy context
        self._log_trades_with_context(enriched_fills, context)

        logger.info(f"LIVE rebalance complete: {len(fills)} fills")
        return enriched_fills, fill_prices

    def _enrich_fills_with_context(
        self,
        fills: List[Dict],
        context: Dict[str, Any]
    ) -> List[Dict]:
        """
        Add strategy context to fill dictionaries.

        Args:
            fills: List of fill dictionaries from OrderExecutor
            context: Strategy context

        Returns:
            Enriched fill dictionaries
        """
        enriched = []
        for fill in fills:
            enriched_fill = fill.copy()
            enriched_fill['mode'] = self._mode.db_value
            enriched_fill['cell'] = context.get('current_cell')
            enriched_fill['trend_state'] = context.get('trend_state')
            enriched_fill['vol_state'] = context.get('vol_state')
            enriched_fill['t_norm'] = context.get('t_norm')
            enriched_fill['z_score'] = context.get('z_score')
            enriched.append(enriched_fill)
        return enriched

    def _log_trades_with_context(
        self,
        fills: List[Dict],
        context: Dict[str, Any]
    ) -> None:
        """
        Log trades with strategy context to separate extended CSV.

        The underlying OrderExecutor already logs basic trade info.
        This adds an extended log with strategy context.

        Args:
            fills: List of enriched fill dictionaries
            context: Strategy context
        """
        if not fills:
            return

        # Log to extended file with strategy context
        extended_log_path = self.trade_log_path.with_suffix('.extended.csv')

        # Create header if file doesn't exist
        if not extended_log_path.exists():
            with open(extended_log_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Date', 'Time', 'Ticker', 'Action', 'Qty',
                    'Expected_Price', 'Fill_Price', 'Slippage_%',
                    'Value', 'Reason', 'Mode', 'Order_ID',
                    'Cell', 'Trend_State', 'Vol_State', 'T_Norm', 'Z_Score'
                ])

        with open(extended_log_path, 'a', newline='') as f:
            writer = csv.writer(f)

            for fill in fills:
                date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                time_str = datetime.now(timezone.utc).strftime('%H:%M:%S')

                # Calculate slippage
                expected = fill.get('expected_price', Decimal('0'))
                actual = fill.get('fill_price', Decimal('0'))
                slippage = Decimal('0')
                if expected > 0:
                    slippage = ((actual - expected) / expected) * 100

                value = fill['quantity'] * fill['fill_price']

                writer.writerow([
                    date_str,
                    time_str,
                    fill['symbol'],
                    fill['action'],
                    fill['quantity'],
                    f"{expected:.2f}",
                    f"{actual:.2f}",
                    f"{slippage:.3f}",
                    f"{value:.2f}",
                    fill.get('reason', 'Rebalance'),
                    "LIVE",
                    fill.get('order_id', ''),
                    fill.get('cell', ''),
                    fill.get('trend_state', ''),
                    fill.get('vol_state', ''),
                    fill.get('t_norm', ''),
                    fill.get('z_score', '')
                ])

        logger.info(f"Logged {len(fills)} trades with context to {extended_log_path}")


def main():
    """Test LiveOrderExecutor (requires Schwab authentication)."""
    logging.basicConfig(level=logging.INFO)

    print("\n>>> LiveOrderExecutor Test")
    print("This module requires authenticated Schwab API client.")
    print("See scripts/live_trader_paper.py for full integration example.")
    print("\nCore functionality:")
    print("  - Implements ExecutorInterface")
    print("  - Wraps OrderExecutor for Schwab API calls")
    print("  - Adds strategy context to fills")
    print("  - Logs extended trade info with regime data")


if __name__ == "__main__":
    main()
