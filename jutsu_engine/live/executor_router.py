"""
Executor Router - Unified execution interface and factory.

This module provides:
- ExecutorInterface: Abstract base class for all executors
- ExecutorRouter: Factory that routes to appropriate executor based on mode

Version: 2.0 (PRD v2.0.1 Compliant)
"""

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path

from jutsu_engine.live.mode import TradingMode

logger = logging.getLogger('LIVE.EXECUTOR_ROUTER')


class ExecutorInterface(ABC):
    """
    Abstract base class for order executors.

    All executors (mock, paper, live) must implement this interface
    to ensure consistent behavior across trading modes.

    Methods:
        execute_rebalance: Execute position rebalancing
        get_mode: Return the trading mode
    """

    @abstractmethod
    def execute_rebalance(
        self,
        position_diffs: Dict[str, int],
        current_prices: Dict[str, Decimal],
        reason: str = "Rebalance",
        strategy_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict], Dict[str, Decimal]]:
        """
        Execute rebalance by processing position differences.

        SELL orders are executed first (to raise cash), then BUY orders.

        Args:
            position_diffs: {symbol: diff} where positive = buy, negative = sell
            current_prices: {symbol: Decimal} current/expected execution prices
            reason: Trade rationale for logging (e.g., "Rebalance", "Signal Change")
            strategy_context: Optional strategy state for logging (cell, trend_state, etc.)

        Returns:
            Tuple of:
                - fills: List of fill dictionaries with keys:
                    symbol, action, quantity, fill_price, expected_price,
                    timestamp, order_id (None for mock)
                - fill_prices: {symbol: actual_fill_price}

        Raises:
            CriticalFailure: If execution fails (live mode)
            SlippageExceeded: If fill exceeds slippage threshold (live mode)
        """
        pass

    @abstractmethod
    def get_mode(self) -> TradingMode:
        """
        Return the trading mode of this executor.

        Returns:
            TradingMode enum value
        """
        pass


class ExecutorRouter:
    """
    Factory that creates the appropriate executor based on trading mode.

    Routes execution requests to either:
    - MockOrderExecutor (OFFLINE_MOCK mode)
    - OrderExecutor (ONLINE_LIVE mode)

    Usage:
        from jutsu_engine.live.executor_router import ExecutorRouter
        from jutsu_engine.live.mode import TradingMode

        # Create mock executor
        executor = ExecutorRouter.create(
            mode=TradingMode.OFFLINE_MOCK,
            config=config
        )

        # Create live executor (requires Schwab client)
        executor = ExecutorRouter.create(
            mode=TradingMode.ONLINE_LIVE,
            config=config,
            client=authenticated_client,
            account_hash=account_hash
        )
    """

    @staticmethod
    def create(
        mode: TradingMode,
        config: Dict[str, Any],
        client: Any = None,
        account_hash: str = None,
        trade_log_path: Optional[Path] = None,
        strategy_id: str = 'v3_5b',
        execution_id: Optional[str] = None
    ) -> ExecutorInterface:
        """
        Create an executor instance based on trading mode.

        Args:
            mode: TradingMode enum value
            config: Configuration dictionary
            client: Schwab API client (required for ONLINE_LIVE mode)
            account_hash: Schwab account hash (required for ONLINE_LIVE mode)
            trade_log_path: Optional path for trade log CSV
            strategy_id: Strategy identifier for multi-strategy support
            execution_id: Unique execution run ID for tracing (uuid4[:8])

        Returns:
            ExecutorInterface implementation

        Raises:
            ValueError: If required parameters missing for selected mode
            ImportError: If executor module not available
        """
        logger.info(f"Creating executor for mode: {mode}, strategy_id: {strategy_id}, execution_id: {execution_id}")

        if mode == TradingMode.OFFLINE_MOCK:
            return ExecutorRouter._create_mock_executor(config, trade_log_path, strategy_id, execution_id)
        elif mode == TradingMode.ONLINE_LIVE:
            return ExecutorRouter._create_live_executor(
                config, client, account_hash, trade_log_path, strategy_id
            )
        else:
            raise ValueError(f"Unknown trading mode: {mode}")

    @staticmethod
    def _create_mock_executor(
        config: Dict[str, Any],
        trade_log_path: Optional[Path] = None,
        strategy_id: str = 'v3_5b',
        execution_id: Optional[str] = None
    ) -> ExecutorInterface:
        """
        Create MockOrderExecutor for offline/dry-run mode.

        Args:
            config: Configuration dictionary
            trade_log_path: Optional path for trade log CSV
            strategy_id: Strategy identifier for multi-strategy support
            execution_id: Unique execution run ID for tracing (uuid4[:8])

        Returns:
            MockOrderExecutor instance
        """
        # Import here to avoid circular imports
        from jutsu_engine.live.mock_order_executor import MockOrderExecutor

        log_path = trade_log_path or Path('logs/live_trades.csv')
        rebalance_threshold = config.get('execution', {}).get(
            'rebalance_threshold_pct', 5.0
        )

        logger.info(
            f"Creating MockOrderExecutor: strategy_id={strategy_id}, log_path={log_path}, "
            f"threshold={rebalance_threshold}%, execution_id={execution_id}"
        )

        return MockOrderExecutor(
            config=config,
            trade_log_path=log_path,
            rebalance_threshold_pct=rebalance_threshold,
            strategy_id=strategy_id,
            execution_id=execution_id
        )

    @staticmethod
    def _create_live_executor(
        config: Dict[str, Any],
        client: Any,
        account_hash: str,
        trade_log_path: Optional[Path] = None,
        strategy_id: str = 'v3_5b'
    ) -> ExecutorInterface:
        """
        Create OrderExecutor for live trading mode.

        Args:
            config: Configuration dictionary
            client: Authenticated Schwab API client
            account_hash: Schwab account hash
            trade_log_path: Optional path for trade log CSV
            strategy_id: Strategy identifier for multi-strategy support

        Returns:
            OrderExecutor instance (wrapped to implement ExecutorInterface)

        Raises:
            ValueError: If client or account_hash is None
        """
        if client is None:
            raise ValueError(
                "Schwab client required for ONLINE_LIVE mode. "
                "Authenticate with schwab-py first."
            )

        if account_hash is None:
            raise ValueError(
                "Account hash required for ONLINE_LIVE mode. "
                "Get account hash from Schwab API."
            )

        # Import here to avoid circular imports
        from jutsu_engine.live.live_order_executor import LiveOrderExecutor

        log_path = trade_log_path or Path('logs/live_trades.csv')

        logger.info(
            f"Creating LiveOrderExecutor: strategy_id={strategy_id}, account={account_hash[:8]}..."
        )

        return LiveOrderExecutor(
            client=client,
            account_hash=account_hash,
            config=config,
            trade_log_path=log_path,
            strategy_id=strategy_id
        )

    @staticmethod
    def from_string(
        mode_str: str,
        config: Dict[str, Any],
        **kwargs
    ) -> ExecutorInterface:
        """
        Create executor from mode string (convenience method).

        Args:
            mode_str: Mode string ("mock", "live", "dry_run", etc.)
            config: Configuration dictionary
            **kwargs: Additional arguments passed to create()

        Returns:
            ExecutorInterface implementation
        """
        mode = TradingMode.from_string(mode_str)
        return ExecutorRouter.create(mode=mode, config=config, **kwargs)
