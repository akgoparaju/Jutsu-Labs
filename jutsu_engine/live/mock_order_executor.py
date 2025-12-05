"""
Mock Order Executor - Log hypothetical trades without real execution.

This module implements ExecutorInterface for offline/dry-run mode.
All trades are logged to DATABASE (primary) and CSV (backup) without placing actual orders.

Version: 2.1 (Database-first implementation - PRD v2.0.1 Compliant)
"""

import logging
import json
from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
import csv
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from jutsu_engine.live.executor_router import ExecutorInterface
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.data.models import LiveTrade, Position, PerformanceSnapshot

logger = logging.getLogger('LIVE.MOCK_EXECUTOR')

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/market_data.db')


class MockOrderExecutor(ExecutorInterface):
    """
    Execute hypothetical trades in offline/dry-run mode.

    Implements ExecutorInterface to provide consistent behavior
    with live executors. All trades are logged to CSV with strategy
    context for post-market validation.

    Features:
        - Logs all hypothetical orders to CSV
        - Captures strategy context (cell, trend_state, vol_state)
        - Applies rebalance threshold filtering
        - SELL-first, BUY-second order sequence
        - No actual orders placed

    Usage:
        executor = MockOrderExecutor(config, trade_log_path)
        fills, fill_prices = executor.execute_rebalance(
            position_diffs={'TQQQ': 100, 'TMF': -50},
            current_prices={'TQQQ': Decimal('50.00'), 'TMF': Decimal('10.00')},
            reason="Rebalance",
            strategy_context={'cell': 1, 'trend_state': 'BullStrong', 'vol_state': 'Low'}
        )
    """

    def __init__(
        self,
        config: Dict[str, Any],
        trade_log_path: Path = Path('logs/live_trades.csv'),
        rebalance_threshold_pct: float = 5.0,
        db_session: Optional[Session] = None
    ):
        """
        Initialize mock order executor.

        Args:
            config: Configuration dictionary
            trade_log_path: Path to trade log CSV file (backup)
            rebalance_threshold_pct: Only trade if position diff >X% of account
            db_session: Optional database session (creates own if not provided)
        """
        self.config = config
        self.trade_log_path = trade_log_path
        self.rebalance_threshold_pct = rebalance_threshold_pct
        self._mode = TradingMode.OFFLINE_MOCK

        # Database connection setup
        if db_session:
            self._session = db_session
            self._owns_session = False
        else:
            # Create database engine and session
            if DATABASE_URL.startswith('sqlite'):
                engine = create_engine(
                    DATABASE_URL,
                    connect_args={'check_same_thread': False}
                )
            else:
                engine = create_engine(DATABASE_URL)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            self._session = SessionLocal()
            self._owns_session = True

        # Create logs directory if needed (for CSV backup)
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize CSV if doesn't exist
        if not self.trade_log_path.exists():
            self._initialize_csv()

        logger.info(
            f"MockOrderExecutor initialized: DB={DATABASE_URL}, CSV={self.trade_log_path}, "
            f"threshold={self.rebalance_threshold_pct}%"
        )

    def _initialize_csv(self) -> None:
        """Create CSV with header if doesn't exist."""
        with open(self.trade_log_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Date', 'Time', 'Ticker', 'Action', 'Qty',
                'Expected_Price', 'Fill_Price', 'Slippage_%',
                'Value', 'Reason', 'Mode',
                'Cell', 'Trend_State', 'Vol_State', 'T_Norm', 'Z_Score'
            ])
        logger.debug(f"Initialized trade log: {self.trade_log_path}")

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
        Execute hypothetical rebalance (log orders without execution).

        Implements ExecutorInterface.execute_rebalance().

        SELL orders are logged first, then BUY orders (matching live sequence).

        Args:
            position_diffs: {symbol: diff} where positive = buy, negative = sell
            current_prices: {symbol: Decimal} expected execution prices
            reason: Trade rationale for logging
            strategy_context: Optional strategy state for logging

        Returns:
            Tuple of:
                - fills: List of fill dictionaries
                - fill_prices: {symbol: fill_price} (same as expected in mock mode)
        """
        if not position_diffs:
            logger.info("No orders to execute (empty position_diffs)")
            return [], {}

        logger.info(f"Starting mock rebalance execution: {len(position_diffs)} orders")

        # Split orders into SELL and BUY (matching live sequence)
        sell_orders = {sym: diff for sym, diff in position_diffs.items() if diff < 0}
        buy_orders = {sym: diff for sym, diff in position_diffs.items() if diff > 0}

        logger.info(f"Order split: {len(sell_orders)} SELL, {len(buy_orders)} BUY")

        all_fills = []
        fill_prices = {}

        # Extract strategy context for logging
        context = strategy_context or {}

        # STEP 1: Log SELL orders first
        if sell_orders:
            logger.info("Logging SELL orders first...")
            for symbol, diff in sell_orders.items():
                if symbol not in current_prices:
                    logger.warning(f"Missing price for {symbol}, skipping")
                    continue

                quantity = abs(diff)
                price = current_prices[symbol]

                fill = self._create_fill(
                    symbol=symbol,
                    action='SELL',
                    quantity=quantity,
                    expected_price=price,
                    fill_price=price,  # Mock: fill = expected
                    reason=reason,
                    context=context
                )

                all_fills.append(fill)
                fill_prices[symbol] = price

        # STEP 2: Log BUY orders second
        if buy_orders:
            logger.info("Logging BUY orders...")
            for symbol, diff in buy_orders.items():
                if symbol not in current_prices:
                    logger.warning(f"Missing price for {symbol}, skipping")
                    continue

                quantity = diff  # Already positive
                price = current_prices[symbol]

                fill = self._create_fill(
                    symbol=symbol,
                    action='BUY',
                    quantity=quantity,
                    expected_price=price,
                    fill_price=price,  # Mock: fill = expected
                    reason=reason,
                    context=context
                )

                all_fills.append(fill)
                fill_prices[symbol] = price

        # Log all trades to CSV
        self._log_trades(all_fills, context)

        logger.info(f"Mock rebalance complete: {len(all_fills)} hypothetical fills")
        return all_fills, fill_prices

    def _create_fill(
        self,
        symbol: str,
        action: str,
        quantity: int,
        expected_price: Decimal,
        fill_price: Decimal,
        reason: str,
        context: Dict[str, Any]
    ) -> Dict:
        """
        Create fill dictionary for a hypothetical order.

        Args:
            symbol: Stock ticker
            action: "BUY" or "SELL"
            quantity: Number of shares
            expected_price: Expected execution price
            fill_price: Actual fill price (same as expected in mock)
            reason: Trade rationale
            context: Strategy context

        Returns:
            Fill dictionary
        """
        now = datetime.now(timezone.utc)
        value = quantity * fill_price

        # Calculate slippage (always 0 in mock mode)
        slippage_pct = Decimal('0')

        fill = {
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'expected_price': expected_price,
            'fill_price': fill_price,
            'slippage_pct': slippage_pct,
            'value': value,
            'order_id': None,  # No order ID in mock mode
            'timestamp': now.isoformat(),
            'reason': reason,
            'mode': self._mode.db_value,
            # Strategy context
            'cell': context.get('current_cell'),
            'trend_state': context.get('trend_state'),
            'vol_state': context.get('vol_state'),
            't_norm': context.get('t_norm'),
            'z_score': context.get('z_score'),
        }

        logger.info(
            f"MOCK {action}: {quantity} {symbol} @ ${fill_price:.2f} "
            f"= ${value:,.2f} ({reason})"
        )

        return fill

    def _log_trades(
        self,
        fills: List[Dict],
        context: Dict[str, Any]
    ) -> None:
        """
        Log executed trades to CSV with strategy context.

        Args:
            fills: List of fill dictionaries
            context: Strategy context
        """
        if not fills:
            return

        with open(self.trade_log_path, 'a', newline='') as f:
            writer = csv.writer(f)

            for fill in fills:
                date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                time_str = datetime.now(timezone.utc).strftime('%H:%M:%S')

                writer.writerow([
                    date_str,
                    time_str,
                    fill['symbol'],
                    fill['action'],
                    fill['quantity'],
                    f"{fill['expected_price']:.2f}",
                    f"{fill['fill_price']:.2f}",
                    f"{fill['slippage_pct']:.3f}",
                    f"{fill['value']:.2f}",
                    fill['reason'],
                    "MOCK",
                    fill.get('cell', ''),
                    fill.get('trend_state', ''),
                    fill.get('vol_state', ''),
                    fill.get('t_norm', ''),
                    fill.get('z_score', '')
                ])

        logger.info(f"Logged {len(fills)} trades to CSV: {self.trade_log_path}")

        # Save to database (PRIMARY storage)
        self._save_to_database(fills, context)

    def _save_to_database(
        self,
        fills: List[Dict],
        context: Dict[str, Any]
    ) -> None:
        """
        Save executed trades to database (PRIMARY storage).

        Args:
            fills: List of fill dictionaries
            context: Strategy context
        """
        if not fills:
            return

        try:
            for fill in fills:
                # Create LiveTrade record
                trade = LiveTrade(
                    symbol=fill['symbol'],
                    timestamp=datetime.now(timezone.utc),
                    action=fill['action'],
                    quantity=fill['quantity'],
                    target_price=float(fill['expected_price']),
                    fill_price=float(fill['fill_price']),
                    fill_value=float(fill['value']),
                    slippage_pct=float(fill['slippage_pct']) if fill.get('slippage_pct') is not None else 0.0,
                    strategy_cell=fill.get('cell'),
                    trend_state=fill.get('trend_state'),
                    vol_state=fill.get('vol_state'),
                    t_norm=float(fill['t_norm']) if fill.get('t_norm') is not None else None,
                    z_score=float(fill['z_score']) if fill.get('z_score') is not None else None,
                    reason=fill['reason'],
                    mode=self._mode.db_value
                )
                self._session.add(trade)

            self._session.commit()
            logger.info(f"Saved {len(fills)} trades to database")

        except Exception as e:
            logger.error(f"Failed to save trades to database: {e}")
            self._session.rollback()
            raise

    def update_positions(
        self,
        target_positions: Dict[str, int],
        current_prices: Dict[str, Decimal],
        account_equity: Decimal
    ) -> None:
        """
        Update positions in database after rebalance.

        Args:
            target_positions: {symbol: quantity} target position quantities
            current_prices: {symbol: price} current market prices
            account_equity: Total account equity
        """
        try:
            # Clear existing positions for this mode (full state replacement)
            self._session.query(Position).filter(
                Position.mode == self._mode.db_value
            ).delete()

            # Insert new positions (include all, even zero quantities for tracking)
            for symbol, quantity in target_positions.items():
                if quantity >= 0:  # Include all non-negative positions
                    price = current_prices.get(symbol, Decimal('0'))
                    market_value = float(price * quantity)

                    position = Position(
                        symbol=symbol,
                        quantity=quantity,
                        avg_cost=float(price),
                        market_value=market_value,
                        unrealized_pnl=0.0,  # No PnL in mock mode at creation
                        mode=self._mode.db_value
                    )
                    self._session.add(position)

            self._session.commit()
            logger.info(f"Updated {len(target_positions)} positions in database")

        except Exception as e:
            logger.error(f"Failed to update positions in database: {e}")
            self._session.rollback()
            raise

    def save_performance_snapshot(
        self,
        account_equity: Decimal,
        cash_balance: Decimal,
        positions_value: Decimal,
        initial_capital: Decimal = Decimal('10000'),
        strategy_context: Optional[Dict[str, Any]] = None,
        baseline_value: Optional[Decimal] = None,
        baseline_return: Optional[float] = None
    ) -> None:
        """
        Save daily performance snapshot to database with calculated P&L.

        Args:
            account_equity: Total account value
            cash_balance: Cash available
            positions_value: Total value of positions
            initial_capital: Starting capital for total P&L calculation
            strategy_context: Optional strategy context with regime info
            baseline_value: Optional QQQ buy-and-hold value for comparison
            baseline_return: Optional QQQ buy-and-hold cumulative return %
        """
        try:
            # Query previous snapshot for this mode to calculate daily P&L
            from sqlalchemy import desc, func

            previous_snapshot = self._session.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == self._mode.db_value
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()

            # Calculate daily P&L
            if previous_snapshot:
                previous_equity = Decimal(str(previous_snapshot.total_equity))
                daily_pnl = account_equity - previous_equity
                daily_pnl_pct = float((daily_pnl / previous_equity) * 100) if previous_equity > 0 else 0.0
            else:
                # First snapshot - no daily P&L
                daily_pnl = Decimal('0')
                daily_pnl_pct = 0.0

            # Calculate total P&L from initial capital
            total_pnl = account_equity - initial_capital
            total_pnl_pct = float((total_pnl / initial_capital) * 100) if initial_capital > 0 else 0.0

            # Calculate drawdown (peak to current)
            # Query max equity for this mode
            max_equity_result = self._session.query(
                func.max(PerformanceSnapshot.total_equity)
            ).filter(
                PerformanceSnapshot.mode == self._mode.db_value
            ).scalar()

            if max_equity_result and max_equity_result > float(account_equity):
                peak_equity = Decimal(str(max_equity_result))
                drawdown = float((peak_equity - account_equity) / peak_equity * 100)
            else:
                drawdown = 0.0

            # Extract strategy context for regime fields
            context = strategy_context or {}

            # Query current positions for position breakdown
            current_positions = self._session.query(Position).filter(
                Position.mode == self._mode.db_value,
                Position.quantity > 0
            ).all()

            # Build positions JSON for snapshot
            positions_data = []
            for pos in current_positions:
                positions_data.append({
                    'symbol': pos.symbol,
                    'quantity': pos.quantity,
                    'value': float(pos.market_value) if pos.market_value else 0.0
                })

            snapshot = PerformanceSnapshot(
                timestamp=datetime.now(timezone.utc),
                total_equity=float(account_equity),
                cash=float(cash_balance),
                positions_value=float(positions_value),
                daily_return=daily_pnl_pct,
                cumulative_return=total_pnl_pct,
                drawdown=drawdown,
                strategy_cell=context.get('current_cell'),
                trend_state=context.get('trend_state'),
                vol_state=context.get('vol_state'),
                positions_json=json.dumps(positions_data) if positions_data else None,
                baseline_value=float(baseline_value) if baseline_value else None,
                baseline_return=baseline_return,
                mode=self._mode.db_value
            )
            self._session.add(snapshot)
            self._session.commit()

            logger.info(
                f"Saved performance snapshot: equity=${account_equity:,.2f}, "
                f"daily_pnl={daily_pnl_pct:+.2f}%, total_pnl={total_pnl_pct:+.2f}%, "
                f"drawdown={drawdown:.2f}%"
            )

        except Exception as e:
            logger.error(f"Failed to save performance snapshot: {e}")
            self._session.rollback()
            raise

    def close(self) -> None:
        """Close database session if owned by this executor."""
        if self._owns_session and self._session:
            self._session.close()
            logger.debug("Closed database session")

    def filter_by_threshold(
        self,
        position_diffs: Dict[str, int],
        current_prices: Dict[str, Decimal],
        account_equity: Decimal
    ) -> Dict[str, int]:
        """
        Filter trades below rebalance threshold.

        Prevents churning - don't trade if position change is below
        the threshold percentage of account equity.

        Args:
            position_diffs: {symbol: diff} position differences
            current_prices: {symbol: price} current market prices
            account_equity: Total account value

        Returns:
            Filtered {symbol: diff} with only significant trades
        """
        threshold_value = account_equity * Decimal(str(self.rebalance_threshold_pct / 100))

        filtered = {}

        for symbol, diff in position_diffs.items():
            if symbol not in current_prices:
                logger.warning(f"Missing price for {symbol}, including in output")
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
                    f"-> KEEP (>= {self.rebalance_threshold_pct}% threshold)"
                )
            else:
                logger.info(
                    f"{symbol}: {diff:+d} shares (${trade_value:,.2f}, {trade_pct:.1f}%) "
                    f"-> SKIP (< {self.rebalance_threshold_pct}% threshold)"
                )

        if not filtered:
            logger.info("No trades exceed rebalance threshold - no action needed")

        return filtered


def main():
    """Test MockOrderExecutor."""
    logging.basicConfig(level=logging.INFO)

    config = {'execution': {'rebalance_threshold_pct': 5.0}}

    executor = MockOrderExecutor(
        config=config,
        trade_log_path=Path('/tmp/test_mock_trades.csv')
    )

    print(f"\nMode: {executor.get_mode()}")
    print(f"Is mock: {executor.get_mode().is_mock}")

    # Test mock rebalance
    position_diffs = {'TQQQ': 100, 'TMF': -50}
    prices = {'TQQQ': Decimal('50.00'), 'TMF': Decimal('10.00')}
    context = {
        'current_cell': 1,
        'trend_state': 'BullStrong',
        'vol_state': 'Low',
        't_norm': Decimal('0.5'),
        'z_score': Decimal('0.3')
    }

    fills, fill_prices = executor.execute_rebalance(
        position_diffs=position_diffs,
        current_prices=prices,
        reason="Test Rebalance",
        strategy_context=context
    )

    print(f"\nFills: {len(fills)}")
    for fill in fills:
        print(f"  {fill['action']} {fill['quantity']} {fill['symbol']} @ ${fill['fill_price']}")

    print(f"\nFill prices: {fill_prices}")


if __name__ == "__main__":
    main()
