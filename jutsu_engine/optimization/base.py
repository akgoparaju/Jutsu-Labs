"""
Base class for all optimization strategies.

Provides common interface and functionality for parameter optimization.
All concrete optimizers (GridSearch, Genetic, etc.) inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any
from decimal import Decimal
from datetime import datetime

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APP.OPTIMIZATION')


class Optimizer(ABC):
    """
    Abstract base class for all optimization strategies.

    Defines the common interface that all optimizers must implement.
    Handles parameter evaluation by running backtests via BacktestRunner.

    Attributes:
        strategy_class: Strategy class to optimize (not instance)
        parameter_space: Dict mapping parameter names to possible values
        objective: Metric to optimize (e.g., 'sharpe_ratio', 'total_return')
        maximize: Whether to maximize (True) or minimize (False) the objective
        results: List of all evaluated parameter combinations

    Example:
        class MyOptimizer(Optimizer):
            def optimize(self, **kwargs) -> Dict[str, Any]:
                # Implementation here
                pass
    """

    def __init__(
        self,
        strategy_class: type[Strategy],
        parameter_space: Dict[str, List[Any]],
        objective: str = 'sharpe_ratio',
        maximize: bool = True
    ):
        """
        Initialize optimizer.

        Args:
            strategy_class: Strategy class to optimize (must inherit from Strategy)
            parameter_space: Dict of parameter names to lists of possible values
                Example: {'short_period': [10, 20, 30], 'long_period': [50, 100]}
            objective: Metric to optimize. Must be a key in backtest results.
                Common options: 'sharpe_ratio', 'total_return', 'max_drawdown'
            maximize: True to maximize objective, False to minimize

        Raises:
            ValueError: If strategy_class doesn't inherit from Strategy
            ValueError: If parameter_space is empty
        """
        if not issubclass(strategy_class, Strategy):
            raise ValueError(
                f"strategy_class must inherit from Strategy, got {strategy_class}"
            )

        if not parameter_space:
            raise ValueError("parameter_space cannot be empty")

        self.strategy_class = strategy_class
        self.parameter_space = parameter_space
        self.objective = objective
        self.maximize = maximize
        self.results: List[Dict[str, Any]] = []

        logger.info(
            f"Initialized {self.__class__.__name__} for {strategy_class.__name__}"
        )
        logger.info(f"Objective: {'maximize' if maximize else 'minimize'} {objective}")
        logger.info(
            f"Parameter space: {len(parameter_space)} parameters, "
            f"{self._count_combinations()} total combinations"
        )

    def _count_combinations(self) -> int:
        """Count total number of parameter combinations."""
        count = 1
        for values in self.parameter_space.values():
            count *= len(values)
        return count

    @abstractmethod
    def optimize(self, **backtest_kwargs) -> Dict[str, Any]:
        """
        Run optimization and return best parameters.

        This method must be implemented by all concrete optimizer classes.

        Args:
            **backtest_kwargs: Arguments passed to BacktestRunner
                Required keys:
                - symbol: str
                - timeframe: str
                - start_date: datetime
                - end_date: datetime
                - initial_capital: Decimal

        Returns:
            Dictionary with:
            - 'parameters': Dict of best parameter values
            - 'objective_value': Best objective function value
            - 'all_results': List of all evaluated combinations (optional)
            - Other optimizer-specific data

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError("Subclasses must implement optimize()")

    def evaluate_parameters(
        self,
        parameters: Dict[str, Any],
        **backtest_kwargs
    ) -> float:
        """
        Evaluate a parameter set by running a backtest.

        This is the core evaluation function used by all optimizers.
        It creates a strategy instance with the given parameters,
        runs a backtest, and returns the objective function value.

        Args:
            parameters: Parameter dict to test
                Example: {'short_period': 20, 'long_period': 50}
            **backtest_kwargs: Arguments for BacktestRunner
                Required keys:
                - symbol: str
                - timeframe: str
                - start_date: datetime
                - end_date: datetime
                - initial_capital: Decimal

        Returns:
            Objective function value (e.g., Sharpe ratio)

        Raises:
            Exception: If backtest fails, re-raises for caller to handle
        """
        try:
            # Create strategy instance with parameters
            strategy = self.strategy_class(**parameters)

            # Configure backtest
            config = {
                'symbol': backtest_kwargs['symbol'],
                'timeframe': backtest_kwargs['timeframe'],
                'start_date': backtest_kwargs['start_date'],
                'end_date': backtest_kwargs['end_date'],
                'initial_capital': backtest_kwargs['initial_capital'],
                'commission_per_share': backtest_kwargs.get(
                    'commission_per_share',
                    Decimal('0.01')
                ),
                'slippage_percent': backtest_kwargs.get(
                    'slippage_percent',
                    Decimal('0.001')
                ),
            }

            # Run backtest
            runner = BacktestRunner(config)
            results = runner.run(strategy)

            # Extract objective value
            objective_value = results[self.objective]

            logger.debug(
                f"Evaluated {parameters}: {self.objective}={objective_value:.4f}"
            )

            return objective_value

        except Exception as e:
            logger.error(
                f"Failed to evaluate parameters {parameters}: {e}",
                exc_info=True
            )
            raise

    def _get_best_result(
        self,
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Find best result from a list of results.

        Args:
            results: List of dicts with 'parameters' and 'objective' keys

        Returns:
            Best result dict

        Raises:
            ValueError: If results list is empty
        """
        if not results:
            raise ValueError("Cannot find best result from empty list")

        if self.maximize:
            return max(results, key=lambda x: x['objective'])
        else:
            return min(results, key=lambda x: x['objective'])

    def _validate_backtest_kwargs(self, backtest_kwargs: Dict[str, Any]) -> None:
        """
        Validate required backtest arguments.

        Args:
            backtest_kwargs: Arguments to validate

        Raises:
            ValueError: If required arguments are missing
        """
        required = ['symbol', 'timeframe', 'start_date', 'end_date', 'initial_capital']

        for key in required:
            if key not in backtest_kwargs:
                raise ValueError(f"Missing required backtest argument: {key}")

        # Validate types
        if not isinstance(backtest_kwargs['symbol'], str):
            raise ValueError("symbol must be a string")

        if not isinstance(backtest_kwargs['start_date'], datetime):
            raise ValueError("start_date must be a datetime object")

        if not isinstance(backtest_kwargs['end_date'], datetime):
            raise ValueError("end_date must be a datetime object")

        if not isinstance(backtest_kwargs['initial_capital'], Decimal):
            raise ValueError("initial_capital must be a Decimal")

        if backtest_kwargs['start_date'] >= backtest_kwargs['end_date']:
            raise ValueError("start_date must be before end_date")
