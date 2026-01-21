"""
Strategy Registry - Central registry for multi-strategy management.

This module provides a registry pattern for loading, validating, and managing
multiple trading strategies from the strategies_registry.yaml configuration.
Part of the Multi-Strategy Engine implementation.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml

logger = logging.getLogger('LIVE.REGISTRY')


@dataclass
class StrategyConfig:
    """
    Configuration for a single trading strategy.

    Attributes:
        id: Unique strategy identifier (e.g., 'v3_5b', 'v3_5d')
        display_name: Human-readable name for UI display
        strategy_class: Python class name in jutsu_engine/strategies/
        config_file: Path to strategy-specific YAML config
        is_primary: If True, this is the protected primary strategy
        is_active: If True, strategy is enabled for execution
        paper_trading: If True, strategy runs in paper trading mode
        description: Brief description of strategy characteristics
    """
    id: str
    display_name: str
    strategy_class: str
    config_file: str
    is_primary: bool = False
    is_active: bool = True
    paper_trading: bool = True
    description: str = ""

    # Derived paths (set after initialization)
    state_file_path: str = field(default="", init=False)
    backup_path: str = field(default="", init=False)

    def __post_init__(self):
        """Set derived paths based on strategy ID."""
        self.state_file_path = f"state/strategies/{self.id}/state.json"
        self.backup_path = f"state/strategies/{self.id}/backups/"

    @classmethod
    def from_dict(cls, strategy_id: str, data: Dict[str, Any]) -> 'StrategyConfig':
        """
        Create StrategyConfig from dictionary data.

        Args:
            strategy_id: Strategy identifier
            data: Dictionary from YAML config

        Returns:
            StrategyConfig instance
        """
        return cls(
            id=strategy_id,
            display_name=data.get('display_name', strategy_id),
            strategy_class=data.get('strategy_class', ''),
            config_file=data.get('config_file', ''),
            is_primary=data.get('is_primary', False),
            is_active=data.get('is_active', True),
            paper_trading=data.get('paper_trading', True),
            description=data.get('description', '')
        )


@dataclass
class RegistrySettings:
    """
    Global settings from the strategy registry.

    Attributes:
        isolate_failures: If True, secondary strategy failures don't affect primary
        execution_timeout: Maximum seconds for single strategy execution
        detailed_timing_logs: Enable detailed timing logs for each strategy
        shared_data_fetch: All strategies use same market data fetch
    """
    isolate_failures: bool = True
    execution_timeout: int = 300
    detailed_timing_logs: bool = True
    shared_data_fetch: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RegistrySettings':
        """Create RegistrySettings from dictionary."""
        return cls(
            isolate_failures=data.get('isolate_failures', True),
            execution_timeout=data.get('execution_timeout', 300),
            detailed_timing_logs=data.get('detailed_timing_logs', True),
            shared_data_fetch=data.get('shared_data_fetch', True)
        )


class StrategyRegistry:
    """
    Central registry for managing multiple trading strategies.

    Loads strategies from strategies_registry.yaml and provides methods
    for querying active strategies, the primary strategy, and individual
    strategy configurations.

    Example:
        registry = StrategyRegistry()

        # Get all active strategies
        for strategy in registry.get_active_strategies():
            print(f"{strategy.id}: {strategy.display_name}")

        # Get the primary strategy
        primary = registry.get_primary_strategy()

        # Get specific strategy
        v3_5d = registry.get_strategy('v3_5d')
    """

    def __init__(
        self,
        registry_path: Path = Path("config/strategies_registry.yaml")
    ):
        """
        Initialize strategy registry from YAML configuration.

        Args:
            registry_path: Path to strategies_registry.yaml

        Raises:
            FileNotFoundError: If registry file doesn't exist
            ValueError: If registry validation fails
        """
        self.registry_path = Path(registry_path)
        self._strategies: Dict[str, StrategyConfig] = {}
        self._execution_order: List[str] = []
        self._settings: RegistrySettings = RegistrySettings()

        self._load_registry()
        self._validate_registry()

        logger.info(
            f"StrategyRegistry initialized: {len(self._strategies)} strategies, "
            f"primary={self.get_primary_strategy().id if self.get_primary_strategy() else 'None'}"
        )

    def _load_registry(self) -> None:
        """Load and parse the registry YAML file."""
        if not self.registry_path.exists():
            raise FileNotFoundError(
                f"Strategy registry not found: {self.registry_path}. "
                f"Please create the file or check the path."
            )

        try:
            with open(self.registry_path, 'r') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in registry file: {e}")

        # Load strategies
        strategies_data = data.get('strategies', {})
        for strategy_id, strategy_data in strategies_data.items():
            self._strategies[strategy_id] = StrategyConfig.from_dict(
                strategy_id, strategy_data
            )
            logger.debug(f"Loaded strategy: {strategy_id}")

        # Load execution order
        self._execution_order = data.get('execution_order', list(strategies_data.keys()))

        # Load settings
        settings_data = data.get('settings', {})
        self._settings = RegistrySettings.from_dict(settings_data)

    def _validate_registry(self) -> None:
        """
        Validate registry configuration.

        Raises:
            ValueError: If validation fails
        """
        # Check at least one strategy exists
        if not self._strategies:
            raise ValueError("Registry must contain at least one strategy")

        # Check exactly one primary strategy
        primary_count = sum(1 for s in self._strategies.values() if s.is_primary)
        if primary_count == 0:
            raise ValueError("Registry must have exactly one primary strategy (is_primary: true)")
        if primary_count > 1:
            raise ValueError(
                f"Registry has {primary_count} primary strategies, must have exactly one"
            )

        # Check primary strategy is active
        primary = self.get_primary_strategy()
        if primary and not primary.is_active:
            raise ValueError(f"Primary strategy '{primary.id}' must be active")

        # Check execution order contains valid strategy IDs
        for strategy_id in self._execution_order:
            if strategy_id not in self._strategies:
                raise ValueError(
                    f"Execution order contains unknown strategy: {strategy_id}"
                )

        # Check config files exist for active strategies
        for strategy in self.get_active_strategies():
            config_path = Path(strategy.config_file)
            if not config_path.exists():
                logger.warning(
                    f"Config file not found for strategy '{strategy.id}': {config_path}"
                )

        # Validate primary strategy is first in execution order
        if self._execution_order:
            first_strategy_id = self._execution_order[0]
            first_strategy = self._strategies.get(first_strategy_id)
            if first_strategy and not first_strategy.is_primary:
                logger.warning(
                    f"Primary strategy should be first in execution order. "
                    f"Found '{first_strategy_id}' first, but '{primary.id}' is primary."
                )

        logger.info("Registry validation: PASSED")

    def get_active_strategies(self) -> List[StrategyConfig]:
        """
        Return all active strategies in execution order.

        Returns:
            List of active StrategyConfig objects in execution order
        """
        active = []
        for strategy_id in self._execution_order:
            strategy = self._strategies.get(strategy_id)
            if strategy and strategy.is_active:
                active.append(strategy)
        return active

    def get_primary_strategy(self) -> Optional[StrategyConfig]:
        """
        Return the primary strategy.

        Returns:
            Primary StrategyConfig or None if not found
        """
        for strategy in self._strategies.values():
            if strategy.is_primary:
                return strategy
        return None

    def get_strategy(self, strategy_id: str) -> Optional[StrategyConfig]:
        """
        Get strategy by ID.

        Args:
            strategy_id: Strategy identifier (e.g., 'v3_5b')

        Returns:
            StrategyConfig or None if not found
        """
        return self._strategies.get(strategy_id)

    def is_strategy_active(self, strategy_id: str) -> bool:
        """
        Check if a strategy is active.

        Args:
            strategy_id: Strategy identifier

        Returns:
            True if strategy exists and is active
        """
        strategy = self._strategies.get(strategy_id)
        return strategy is not None and strategy.is_active

    def get_all_strategy_ids(self) -> List[str]:
        """
        Get all registered strategy IDs.

        Returns:
            List of all strategy IDs (active and inactive)
        """
        return list(self._strategies.keys())

    def get_settings(self) -> RegistrySettings:
        """
        Get registry global settings.

        Returns:
            RegistrySettings instance
        """
        return self._settings

    def load_strategy_config(self, strategy_id: str) -> Dict[str, Any]:
        """
        Load the full configuration for a strategy.

        Args:
            strategy_id: Strategy identifier

        Returns:
            Full strategy configuration dictionary from its config file

        Raises:
            ValueError: If strategy not found or config file missing
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_id}")

        config_path = Path(strategy.config_file)
        if not config_path.exists():
            raise ValueError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def reload(self) -> None:
        """
        Reload registry from file.

        Useful for hot-reloading configuration changes.
        """
        logger.info("Reloading strategy registry...")
        self._strategies.clear()
        self._execution_order.clear()
        self._load_registry()
        self._validate_registry()
        logger.info("Strategy registry reloaded successfully")

    def __repr__(self) -> str:
        """String representation of registry."""
        active_ids = [s.id for s in self.get_active_strategies()]
        primary_id = self.get_primary_strategy().id if self.get_primary_strategy() else 'None'
        return (
            f"StrategyRegistry("
            f"strategies={list(self._strategies.keys())}, "
            f"active={active_ids}, "
            f"primary='{primary_id}')"
        )


def main():
    """Test strategy registry functionality."""
    logging.basicConfig(level=logging.INFO)

    try:
        registry = StrategyRegistry()
        print(f"\nRegistry: {registry}")

        print(f"\nAll strategies:")
        for strategy_id in registry.get_all_strategy_ids():
            strategy = registry.get_strategy(strategy_id)
            status = "PRIMARY" if strategy.is_primary else "SECONDARY"
            active = "ACTIVE" if strategy.is_active else "INACTIVE"
            print(f"  - {strategy.id}: {strategy.display_name} [{status}] [{active}]")

        print(f"\nActive strategies (execution order):")
        for strategy in registry.get_active_strategies():
            print(f"  {strategy.id}: {strategy.state_file_path}")

        print(f"\nSettings:")
        settings = registry.get_settings()
        print(f"  isolate_failures: {settings.isolate_failures}")
        print(f"  execution_timeout: {settings.execution_timeout}s")
        print(f"  shared_data_fetch: {settings.shared_data_fetch}")

        # Load full config for primary
        primary = registry.get_primary_strategy()
        if primary:
            print(f"\nPrimary strategy config ({primary.id}):")
            config = registry.load_strategy_config(primary.id)
            print(f"  strategy_id: {config.get('strategy_id')}")
            print(f"  version: {config.get('version')}")

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
