"""
Multi-Strategy Runner - Execute multiple trading strategies in parallel.

This module provides a unified runner for executing multiple strategies
with shared data fetching and isolated state management. Part of the
Multi-Strategy Engine implementation.

Key Features:
- Shared data fetch (single API call for all strategies)
- Isolated state per strategy
- Primary strategy protection (secondary failures don't affect primary)
- Unified execution with timing metrics
"""

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Any, List, Type
import pandas as pd
import importlib

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.live.strategy_registry import StrategyRegistry, StrategyConfig
from jutsu_engine.live.multi_state_manager import MultiStrategyStateManager
from jutsu_engine.live.strategy_runner import LiveStrategyRunner

logger = logging.getLogger('LIVE.MULTI_RUNNER')


@dataclass
class StrategyExecutionResult:
    """
    Result of a single strategy execution.

    Attributes:
        strategy_id: Strategy identifier
        success: Whether execution completed successfully
        signals: Trading signals generated (if successful)
        allocation: Target allocation (if successful)
        error: Error message (if failed)
        execution_time_ms: Time taken for execution in milliseconds
        context: Strategy context for logging
    """
    strategy_id: str
    success: bool
    signals: Dict[str, Any] = field(default_factory=dict)
    allocation: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiExecutionResult:
    """
    Combined result of all strategy executions.

    Attributes:
        results: Dictionary mapping strategy_id to StrategyExecutionResult
        primary_success: Whether primary strategy succeeded
        all_success: Whether all strategies succeeded
        total_time_ms: Total execution time in milliseconds
    """
    results: Dict[str, StrategyExecutionResult] = field(default_factory=dict)
    primary_success: bool = False
    all_success: bool = False
    total_time_ms: float = 0.0

    def get_primary_result(self) -> Optional[StrategyExecutionResult]:
        """Get the primary strategy result."""
        for result in self.results.values():
            # Find primary by checking registry later
            pass
        return None

    def get_failed_strategies(self) -> List[str]:
        """Get list of strategy IDs that failed."""
        return [
            strategy_id for strategy_id, result in self.results.items()
            if not result.success
        ]


class MultiStrategyRunner:
    """
    Execute multiple trading strategies with shared data and isolated state.

    Manages the lifecycle of multiple strategy runners, coordinating
    data fetching, signal calculation, and state updates while
    maintaining isolation between strategies.

    Example:
        runner = MultiStrategyRunner()

        # Run all strategies
        result = runner.run_all_strategies(market_data, account_equity)

        # Check results
        if result.primary_success:
            primary = result.results['v3_5b']
            print(f"Primary allocation: {primary.allocation}")

        for strategy_id, strategy_result in result.results.items():
            print(f"{strategy_id}: {'OK' if strategy_result.success else 'FAILED'}")
    """

    def __init__(
        self,
        registry_path: Path = Path("config/strategies_registry.yaml")
    ):
        """
        Initialize multi-strategy runner.

        Args:
            registry_path: Path to strategies_registry.yaml
        """
        self.registry = StrategyRegistry(registry_path)
        self.state_manager = MultiStrategyStateManager(self.registry)
        self._runners: Dict[str, LiveStrategyRunner] = {}
        self._strategy_classes: Dict[str, Type[Strategy]] = {}

        # Initialize runners for each active strategy
        self._initialize_runners()

        logger.info(
            f"MultiStrategyRunner initialized with {len(self._runners)} strategies"
        )

    def _get_strategy_class(self, class_name: str) -> Type[Strategy]:
        """
        Dynamically import and return strategy class.

        Args:
            class_name: Name of the strategy class

        Returns:
            Strategy class type

        Raises:
            ImportError: If class cannot be imported
        """
        if class_name in self._strategy_classes:
            return self._strategy_classes[class_name]

        try:
            # Import from strategies module
            module_name = f"jutsu_engine.strategies.{class_name}"
            module = importlib.import_module(module_name)
            strategy_class = getattr(module, class_name)
            self._strategy_classes[class_name] = strategy_class
            return strategy_class
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to import strategy class {class_name}: {e}")
            raise ImportError(f"Cannot import strategy class: {class_name}")

    def _initialize_runners(self) -> None:
        """Initialize LiveStrategyRunner for each active strategy."""
        for strategy in self.registry.get_active_strategies():
            try:
                strategy_class = self._get_strategy_class(strategy.strategy_class)
                config_path = Path(strategy.config_file)

                runner = LiveStrategyRunner(
                    strategy_class=strategy_class,
                    config_path=config_path
                )
                self._runners[strategy.id] = runner

                logger.info(f"Initialized runner for strategy: {strategy.id}")

            except Exception as e:
                logger.error(f"Failed to initialize runner for {strategy.id}: {e}")
                # Don't raise for secondary strategies if isolate_failures is True
                if strategy.is_primary:
                    raise
                elif not self.registry.get_settings().isolate_failures:
                    raise

    def get_runner(self, strategy_id: str) -> Optional[LiveStrategyRunner]:
        """
        Get the runner for a specific strategy.

        Args:
            strategy_id: Strategy identifier

        Returns:
            LiveStrategyRunner or None if not found
        """
        return self._runners.get(strategy_id)

    def get_all_symbols(self) -> List[str]:
        """
        Get all unique trading symbols across all strategies.

        Returns:
            List of unique symbols needed for data fetching
        """
        all_symbols = set()
        for runner in self._runners.values():
            all_symbols.update(runner.get_all_symbols())
        return list(all_symbols)

    def run_strategy(
        self,
        strategy_id: str,
        market_data: Dict[str, pd.DataFrame],
        account_equity: Decimal
    ) -> StrategyExecutionResult:
        """
        Run a single strategy.

        Args:
            strategy_id: Strategy to run
            market_data: Market data for all symbols
            account_equity: Current account equity

        Returns:
            StrategyExecutionResult with signals and allocation
        """
        start_time = time.time()

        if strategy_id not in self._runners:
            return StrategyExecutionResult(
                strategy_id=strategy_id,
                success=False,
                error=f"Strategy not found: {strategy_id}"
            )

        runner = self._runners[strategy_id]

        try:
            # Calculate signals
            signals = runner.calculate_signals(market_data)

            # Determine allocation
            allocation = runner.determine_target_allocation(signals, account_equity)

            # Get strategy context
            context = runner.get_strategy_context()

            execution_time = (time.time() - start_time) * 1000

            logger.info(
                f"Strategy {strategy_id} completed in {execution_time:.1f}ms: "
                f"Cell {signals.get('current_cell')}"
            )

            return StrategyExecutionResult(
                strategy_id=strategy_id,
                success=True,
                signals=signals,
                allocation=allocation,
                context=context,
                execution_time_ms=execution_time
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Strategy {strategy_id} failed: {e}")

            return StrategyExecutionResult(
                strategy_id=strategy_id,
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )

    def run_all_strategies(
        self,
        market_data: Dict[str, pd.DataFrame],
        account_equity: Decimal
    ) -> MultiExecutionResult:
        """
        Run all active strategies in execution order.

        Primary strategy runs first and its failure will abort if
        isolate_failures is False. Secondary strategy failures are
        logged but don't affect other strategies.

        Args:
            market_data: Market data for all symbols
            account_equity: Current account equity

        Returns:
            MultiExecutionResult with all strategy results
        """
        start_time = time.time()
        results: Dict[str, StrategyExecutionResult] = {}
        settings = self.registry.get_settings()

        logger.info(f"Running {len(self._runners)} strategies...")

        for strategy in self.registry.get_active_strategies():
            if strategy.id not in self._runners:
                logger.warning(f"Skipping strategy without runner: {strategy.id}")
                continue

            # Log timing if enabled
            if settings.detailed_timing_logs:
                logger.info(f"Starting strategy: {strategy.id}")

            # Run strategy
            result = self.run_strategy(strategy.id, market_data, account_equity)
            results[strategy.id] = result

            # Handle failures
            if not result.success:
                if strategy.is_primary:
                    logger.error(f"PRIMARY strategy failed: {strategy.id}")
                    if not settings.isolate_failures:
                        logger.error("Aborting remaining strategies due to primary failure")
                        break
                else:
                    logger.warning(
                        f"Secondary strategy failed: {strategy.id} - {result.error}"
                    )

            # Update state with results
            if result.success:
                self._update_strategy_state(strategy.id, result)

        total_time = (time.time() - start_time) * 1000

        # Determine overall success
        primary = self.registry.get_primary_strategy()
        primary_success = primary and results.get(primary.id, StrategyExecutionResult(
            strategy_id=primary.id, success=False
        )).success

        all_success = all(r.success for r in results.values())

        logger.info(
            f"All strategies completed in {total_time:.1f}ms. "
            f"Primary: {'OK' if primary_success else 'FAILED'}, "
            f"All: {'OK' if all_success else 'PARTIAL'}"
        )

        return MultiExecutionResult(
            results=results,
            primary_success=primary_success,
            all_success=all_success,
            total_time_ms=total_time
        )

    def _update_strategy_state(
        self,
        strategy_id: str,
        result: StrategyExecutionResult
    ) -> None:
        """
        Update strategy state after successful execution.

        Args:
            strategy_id: Strategy identifier
            result: Execution result with signals
        """
        try:
            # Update regime state
            self.state_manager.update_regime_state(
                strategy_id,
                vol_state=result.signals.get('vol_state', 0),
                trend_state=result.signals.get('trend_state', 'Unknown')
            )

            logger.debug(f"Updated state for {strategy_id}")

        except Exception as e:
            logger.warning(f"Failed to update state for {strategy_id}: {e}")

    def save_all_states(self) -> None:
        """Save state for all strategies."""
        self.state_manager.save_all_states()

    def get_strategy_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Get states for all strategies.

        Returns:
            Dictionary mapping strategy_id to state dict
        """
        return self.state_manager.load_all_states()

    def reload_registry(self) -> None:
        """
        Reload strategy registry and reinitialize runners.

        Useful for hot-reloading configuration changes.
        """
        logger.info("Reloading multi-strategy runner...")
        self.registry.reload()
        self._runners.clear()
        self._initialize_runners()
        logger.info("Multi-strategy runner reloaded")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MultiStrategyRunner("
            f"strategies={list(self._runners.keys())}, "
            f"primary='{self.registry.get_primary_strategy().id if self.registry.get_primary_strategy() else None}')"
        )


def main():
    """Test multi-strategy runner."""
    logging.basicConfig(level=logging.INFO)

    try:
        runner = MultiStrategyRunner()
        print(f"\nRunner: {runner}")

        # List all symbols needed
        symbols = runner.get_all_symbols()
        print(f"\nRequired symbols: {symbols}")

        # Get strategy states
        states = runner.get_strategy_states()
        for strategy_id, state in states.items():
            print(f"\n{strategy_id} state:")
            print(f"  vol_state: {state.get('vol_state')}")
            print(f"  trend_state: {state.get('trend_state')}")
            print(f"  positions: {state.get('current_positions', {})}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
