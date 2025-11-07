"""
Grid search optimizer for exhaustive parameter space exploration.

Evaluates all possible combinations of parameters to find the optimal set.
Supports parallel execution for efficiency.
"""
from typing import Dict, List, Any
import itertools
from decimal import Decimal
from datetime import datetime

from jutsu_engine.optimization.base import Optimizer
from jutsu_engine.optimization.parallel import ParallelExecutor
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APP.OPTIMIZATION.GRID')


class GridSearchOptimizer(Optimizer):
    """
    Exhaustive grid search over parameter space.

    Evaluates every possible combination of parameters in the defined space.
    Use for small parameter spaces where exhaustive search is feasible.

    For large spaces (>1000 combinations), consider GeneticOptimizer instead.

    Example:
        >>> from jutsu_engine.strategies.sma_crossover import SMA_Crossover
        >>> from decimal import Decimal
        >>> from datetime import datetime
        >>>
        >>> optimizer = GridSearchOptimizer(
        ...     strategy_class=SMA_Crossover,
        ...     parameter_space={
        ...         'short_period': [10, 20, 30],
        ...         'long_period': [50, 100, 200]
        ...     },
        ...     objective='sharpe_ratio'
        ... )
        >>>
        >>> results = optimizer.optimize(
        ...     symbol='AAPL',
        ...     timeframe='1D',
        ...     start_date=datetime(2020, 1, 1),
        ...     end_date=datetime(2023, 1, 1),
        ...     initial_capital=Decimal('100000'),
        ...     parallel=True
        ... )
        >>>
        >>> print(f"Best parameters: {results['parameters']}")
        >>> print(f"Best Sharpe: {results['objective_value']:.2f}")
    """

    def optimize(
        self,
        parallel: bool = True,
        n_jobs: int = -1,
        **backtest_kwargs
    ) -> Dict[str, Any]:
        """
        Run grid search optimization.

        Args:
            parallel: Whether to use parallel execution
            n_jobs: Number of parallel jobs (-1 = all cores)
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
            - 'all_results': List of all evaluated combinations
            - 'n_evaluated': Number of combinations evaluated
            - 'execution_mode': 'parallel' or 'sequential'

        Raises:
            ValueError: If backtest_kwargs are invalid
        """
        self._validate_backtest_kwargs(backtest_kwargs)

        # Generate all parameter combinations
        param_names = list(self.parameter_space.keys())
        param_values = list(self.parameter_space.values())
        combinations = list(itertools.product(*param_values))

        logger.info(
            f"Grid search: {len(combinations)} combinations to evaluate"
        )

        # Decide on execution mode
        executor = ParallelExecutor(n_jobs=n_jobs, show_progress=True)
        use_parallel = parallel and executor.should_use_parallel(len(combinations))

        if use_parallel:
            results = self._optimize_parallel(
                combinations,
                param_names,
                executor,
                **backtest_kwargs
            )
            execution_mode = 'parallel'
        else:
            results = self._optimize_sequential(
                combinations,
                param_names,
                **backtest_kwargs
            )
            execution_mode = 'sequential'

        # Store all results
        self.results = results

        # Find best result
        if not results:
            raise RuntimeError("Grid search failed: no results obtained")

        best_result = self._get_best_result(results)

        logger.info(
            f"Grid search complete: Best {self.objective} = "
            f"{best_result['objective']:.4f} with parameters {best_result['parameters']}"
        )

        return {
            'parameters': best_result['parameters'],
            'objective_value': best_result['objective'],
            'all_results': results,
            'n_evaluated': len(results),
            'execution_mode': execution_mode
        }

    def _optimize_parallel(
        self,
        combinations: List[tuple],
        param_names: List[str],
        executor: ParallelExecutor,
        **backtest_kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute grid search in parallel using ProcessPoolExecutor.

        Args:
            combinations: List of parameter value tuples
            param_names: List of parameter names
            executor: ParallelExecutor instance
            **backtest_kwargs: Arguments for BacktestRunner

        Returns:
            List of result dictionaries
        """
        def evaluate_combo(combo: tuple) -> Dict[str, Any]:
            """Evaluate a single parameter combination."""
            params = dict(zip(param_names, combo))
            try:
                objective_value = self.evaluate_parameters(params, **backtest_kwargs)
                return {
                    'parameters': params,
                    'objective': objective_value,
                    'success': True
                }
            except Exception as e:
                logger.error(f"Failed to evaluate {params}: {e}")
                # Return worst possible value
                worst_value = float('-inf') if self.maximize else float('inf')
                return {
                    'parameters': params,
                    'objective': worst_value,
                    'success': False,
                    'error': str(e)
                }

        results = executor.execute(
            evaluate_combo,
            combinations,
            task_description="Grid Search"
        )

        # Filter out failed evaluations
        successful_results = [r for r in results if r.get('success', False)]

        logger.info(
            f"Parallel evaluation: {len(successful_results)} successful, "
            f"{len(results) - len(successful_results)} failed"
        )

        return successful_results

    def _optimize_sequential(
        self,
        combinations: List[tuple],
        param_names: List[str],
        **backtest_kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute grid search sequentially (single-threaded).

        Args:
            combinations: List of parameter value tuples
            param_names: List of parameter names
            **backtest_kwargs: Arguments for BacktestRunner

        Returns:
            List of result dictionaries
        """
        results = []

        for i, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))

            try:
                objective_value = self.evaluate_parameters(params, **backtest_kwargs)
                results.append({
                    'parameters': params,
                    'objective': objective_value,
                    'success': True
                })

                logger.info(
                    f"[{i+1}/{len(combinations)}] Evaluated {params}: "
                    f"{self.objective}={objective_value:.4f}"
                )

            except Exception as e:
                logger.error(f"Failed to evaluate {params}: {e}")
                # Continue with next combination

        return results

    def get_top_n_results(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        Get top N parameter combinations.

        Args:
            n: Number of top results to return

        Returns:
            List of top N results sorted by objective value

        Raises:
            ValueError: If optimization hasn't been run yet
        """
        if not self.results:
            raise ValueError("No results available. Run optimize() first.")

        sorted_results = sorted(
            self.results,
            key=lambda x: x['objective'],
            reverse=self.maximize
        )

        return sorted_results[:n]

    def get_heatmap_data(
        self,
        param_x: str,
        param_y: str
    ) -> Dict[str, Any]:
        """
        Get data for creating a 2D heatmap.

        Useful for visualizing parameter sensitivity.

        Args:
            param_x: Parameter name for x-axis
            param_y: Parameter name for y-axis

        Returns:
            Dictionary with:
            - 'x_values': Unique values for x parameter
            - 'y_values': Unique values for y parameter
            - 'z_values': 2D array of objective values

        Raises:
            ValueError: If parameters not in parameter space or no results
        """
        if not self.results:
            raise ValueError("No results available. Run optimize() first.")

        if param_x not in self.parameter_space:
            raise ValueError(f"Parameter '{param_x}' not in parameter space")

        if param_y not in self.parameter_space:
            raise ValueError(f"Parameter '{param_y}' not in parameter space")

        # Extract unique values
        x_values = sorted(set(r['parameters'][param_x] for r in self.results))
        y_values = sorted(set(r['parameters'][param_y] for r in self.results))

        # Create 2D grid of objective values
        z_values = [[None for _ in x_values] for _ in y_values]

        for result in self.results:
            x_idx = x_values.index(result['parameters'][param_x])
            y_idx = y_values.index(result['parameters'][param_y])
            z_values[y_idx][x_idx] = result['objective']

        return {
            'x_values': x_values,
            'y_values': y_values,
            'z_values': z_values,
            'x_label': param_x,
            'y_label': param_y,
            'z_label': self.objective
        }
