"""
Multi-Strategy State Manager - Manage state for multiple strategies.

This module provides a wrapper around StateManager to handle state persistence
for multiple trading strategies, each with its own state file and backups.
Part of the Multi-Strategy Engine implementation.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone

from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.strategy_registry import StrategyRegistry, StrategyConfig

logger = logging.getLogger('LIVE.MULTI_STATE')


class MultiStrategyStateManager:
    """
    Manage state for multiple trading strategies.

    Creates and manages individual StateManager instances for each active
    strategy, providing a unified interface for state operations across
    all strategies.

    Example:
        registry = StrategyRegistry()
        state_manager = MultiStrategyStateManager(registry)

        # Load state for all strategies
        states = state_manager.load_all_states()

        # Get state for specific strategy
        v3_5b_state = state_manager.get_state('v3_5b')

        # Save state for specific strategy
        state_manager.save_state('v3_5b', new_state)

        # Get primary strategy state
        primary_state = state_manager.get_primary_state()
    """

    def __init__(self, registry: StrategyRegistry):
        """
        Initialize multi-strategy state manager.

        Creates StateManager instances for each active strategy in the registry.

        Args:
            registry: StrategyRegistry instance with loaded strategy configs
        """
        self.registry = registry
        self._managers: Dict[str, StateManager] = {}
        self._states: Dict[str, Dict[str, Any]] = {}

        # Initialize state managers for each active strategy
        for strategy in registry.get_active_strategies():
            self._managers[strategy.id] = StateManager(
                state_file=Path(strategy.state_file_path),
                backup_enabled=True,
                backup_dir=Path(strategy.backup_path)
            )
            logger.debug(f"Initialized StateManager for strategy: {strategy.id}")

        logger.info(
            f"MultiStrategyStateManager initialized with {len(self._managers)} strategies"
        )

    def load_state(self, strategy_id: str) -> Dict[str, Any]:
        """
        Load state for a specific strategy.

        Args:
            strategy_id: Strategy identifier

        Returns:
            State dictionary for the strategy

        Raises:
            ValueError: If strategy not found
        """
        if strategy_id not in self._managers:
            raise ValueError(f"Strategy not found in state managers: {strategy_id}")

        state = self._managers[strategy_id].load_state()

        # Add strategy_id to state metadata if not present
        if 'metadata' not in state:
            state['metadata'] = {}
        state['metadata']['strategy_id'] = strategy_id

        self._states[strategy_id] = state
        logger.debug(f"Loaded state for {strategy_id}: last_run={state.get('last_run')}")

        return state

    def load_all_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Load state for all active strategies.

        Returns:
            Dictionary mapping strategy_id to state dict
        """
        for strategy_id in self._managers.keys():
            self.load_state(strategy_id)

        logger.info(f"Loaded states for {len(self._states)} strategies")
        return self._states.copy()

    def save_state(self, strategy_id: str, state: Dict[str, Any]) -> None:
        """
        Save state for a specific strategy.

        Args:
            strategy_id: Strategy identifier
            state: State dictionary to save

        Raises:
            ValueError: If strategy not found
        """
        if strategy_id not in self._managers:
            raise ValueError(f"Strategy not found in state managers: {strategy_id}")

        # Ensure strategy_id in metadata
        if 'metadata' not in state:
            state['metadata'] = {}
        state['metadata']['strategy_id'] = strategy_id

        self._managers[strategy_id].save_state(state)
        self._states[strategy_id] = state

        logger.debug(f"Saved state for {strategy_id}")

    def save_all_states(self) -> None:
        """Save state for all strategies with cached states."""
        for strategy_id, state in self._states.items():
            if state:
                self.save_state(strategy_id, state)

        logger.info(f"Saved states for {len(self._states)} strategies")

    def get_state(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached state for a strategy.

        Args:
            strategy_id: Strategy identifier

        Returns:
            Cached state dict or None if not loaded
        """
        return self._states.get(strategy_id)

    def get_primary_state(self) -> Optional[Dict[str, Any]]:
        """
        Get state for the primary strategy.

        Returns:
            Primary strategy state or None if not loaded
        """
        primary = self.registry.get_primary_strategy()
        if primary:
            return self.get_state(primary.id)
        return None

    def get_manager(self, strategy_id: str) -> Optional[StateManager]:
        """
        Get the underlying StateManager for a strategy.

        Args:
            strategy_id: Strategy identifier

        Returns:
            StateManager instance or None if not found
        """
        return self._managers.get(strategy_id)

    def reconcile_all_with_account(
        self,
        api_positions: Dict[str, int],
        threshold_pct: float = 2.0
    ) -> Dict[str, Dict[str, Dict[str, int]]]:
        """
        Reconcile all strategy states with actual account positions.

        Note: In paper trading mode, each strategy tracks its own virtual
        positions. This method is primarily used for the primary strategy
        that may be in live mode.

        Args:
            api_positions: Positions from broker API {symbol: qty}
            threshold_pct: Warning threshold for position drift

        Returns:
            Dictionary mapping strategy_id to discrepancies dict
        """
        all_discrepancies = {}

        for strategy_id, state in self._states.items():
            strategy = self.registry.get_strategy(strategy_id)
            if not strategy:
                continue

            state_positions = state.get('current_positions', {})
            manager = self._managers[strategy_id]

            try:
                discrepancies = manager.reconcile_with_account(
                    state_positions,
                    api_positions,
                    threshold_pct
                )
                if discrepancies:
                    all_discrepancies[strategy_id] = discrepancies
            except ValueError as e:
                # Critical drift detected
                logger.error(f"Critical drift for {strategy_id}: {e}")
                all_discrepancies[strategy_id] = {'error': str(e)}

        return all_discrepancies

    def update_positions(
        self,
        strategy_id: str,
        positions: Dict[str, int],
        allocation: Dict[str, float],
        equity: float
    ) -> None:
        """
        Update positions and allocation for a strategy.

        Convenience method to update common state fields after execution.

        Args:
            strategy_id: Strategy identifier
            positions: New positions {symbol: quantity}
            allocation: Target allocation {symbol: weight}
            equity: Account equity value
        """
        state = self._states.get(strategy_id)
        if not state:
            state = self.load_state(strategy_id)

        state['current_positions'] = positions
        state['last_allocation'] = allocation
        state['account_equity'] = equity
        state['last_run'] = datetime.now(timezone.utc).isoformat()

        self._states[strategy_id] = state
        logger.debug(
            f"Updated positions for {strategy_id}: "
            f"{len(positions)} positions, equity=${equity:.2f}"
        )

    def update_regime_state(
        self,
        strategy_id: str,
        vol_state: int,
        trend_state: str
    ) -> None:
        """
        Update regime state for a strategy.

        Args:
            strategy_id: Strategy identifier
            vol_state: Volatility state (-1, 0, 1)
            trend_state: Trend state string (e.g., 'BullStrong', 'Sideways')
        """
        state = self._states.get(strategy_id)
        if not state:
            state = self.load_state(strategy_id)

        state['vol_state'] = vol_state
        state['trend_state'] = trend_state

        self._states[strategy_id] = state
        logger.debug(
            f"Updated regime for {strategy_id}: vol={vol_state}, trend={trend_state}"
        )

    def get_all_strategy_ids(self) -> List[str]:
        """
        Get list of all managed strategy IDs.

        Returns:
            List of strategy IDs
        """
        return list(self._managers.keys())

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MultiStrategyStateManager("
            f"strategies={list(self._managers.keys())}, "
            f"loaded={list(self._states.keys())})"
        )


def main():
    """Test multi-strategy state manager functionality."""
    logging.basicConfig(level=logging.INFO)

    try:
        # Initialize registry and state manager
        registry = StrategyRegistry()
        state_manager = MultiStrategyStateManager(registry)

        print(f"\nState Manager: {state_manager}")

        # Load all states
        print(f"\nLoading all states...")
        states = state_manager.load_all_states()

        for strategy_id, state in states.items():
            print(f"\n{strategy_id}:")
            print(f"  last_run: {state.get('last_run')}")
            print(f"  vol_state: {state.get('vol_state')}")
            print(f"  trend_state: {state.get('trend_state')}")
            print(f"  positions: {state.get('current_positions', {})}")
            print(f"  equity: {state.get('account_equity')}")

        # Get primary state
        print(f"\nPrimary strategy state:")
        primary = registry.get_primary_strategy()
        if primary:
            primary_state = state_manager.get_primary_state()
            print(f"  {primary.id}: {primary_state.get('current_positions', {})}")

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
