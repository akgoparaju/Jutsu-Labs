"""
Parallel execution utilities for optimization.

Provides process pool management and progress tracking for parallel optimization.
"""
from typing import Dict, List, Any, Callable, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from tqdm import tqdm

from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APP.OPTIMIZATION.PARALLEL')


class ParallelExecutor:
    """
    Manages parallel execution of parameter evaluations.

    Uses ProcessPoolExecutor for CPU-bound optimization tasks.
    Provides progress tracking and error handling.

    Attributes:
        n_jobs: Number of parallel workers (-1 for all cores)
        show_progress: Whether to show progress bar
    """

    def __init__(self, n_jobs: int = -1, show_progress: bool = True):
        """
        Initialize parallel executor.

        Args:
            n_jobs: Number of parallel workers. -1 uses all available cores.
            show_progress: Whether to display progress bar
        """
        if n_jobs == -1:
            n_jobs = multiprocessing.cpu_count()
        elif n_jobs < 1:
            raise ValueError(f"n_jobs must be -1 or positive, got {n_jobs}")

        self.n_jobs = min(n_jobs, multiprocessing.cpu_count())
        self.show_progress = show_progress

        logger.info(
            f"ParallelExecutor initialized with {self.n_jobs} workers "
            f"(max: {multiprocessing.cpu_count()})"
        )

    def execute(
        self,
        func: Callable,
        tasks: List[Any],
        task_description: str = "Processing"
    ) -> List[Dict[str, Any]]:
        """
        Execute function on tasks in parallel.

        Args:
            func: Function to execute. Should take a task and return a result dict.
            tasks: List of tasks to process
            task_description: Description for progress bar

        Returns:
            List of result dictionaries from successful executions

        Example:
            def evaluate_params(params):
                value = run_backtest(params)
                return {'parameters': params, 'objective': value}

            executor = ParallelExecutor(n_jobs=4)
            results = executor.execute(evaluate_params, param_list)
        """
        results = []
        failed_count = 0

        logger.info(f"Starting parallel execution: {len(tasks)} tasks")

        with ProcessPoolExecutor(max_workers=self.n_jobs) as executor:
            # Submit all tasks
            futures = {executor.submit(func, task): task for task in tasks}

            # Process completed tasks with progress bar
            if self.show_progress:
                progress = tqdm(
                    as_completed(futures),
                    total=len(tasks),
                    desc=task_description
                )
            else:
                progress = as_completed(futures)

            for future in progress:
                task = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Task failed for {task}: {e}")

        logger.info(
            f"Parallel execution complete: "
            f"{len(results)} succeeded, {failed_count} failed"
        )

        return results

    def should_use_parallel(self, n_tasks: int, threshold: int = 20) -> bool:
        """
        Determine if parallel execution is beneficial.

        For small numbers of tasks, parallel overhead may exceed benefits.

        Args:
            n_tasks: Number of tasks to execute
            threshold: Minimum number of tasks to use parallel execution

        Returns:
            True if parallel execution is recommended
        """
        use_parallel = n_tasks >= threshold and self.n_jobs > 1

        if not use_parallel:
            logger.info(
                f"Using sequential execution ({n_tasks} tasks < {threshold} threshold "
                f"or only 1 worker available)"
            )
        else:
            logger.info(
                f"Using parallel execution ({n_tasks} tasks, {self.n_jobs} workers)"
            )

        return use_parallel


def create_evaluation_task(
    parameters: Dict[str, Any],
    evaluator: Callable,
    **backtest_kwargs
) -> Dict[str, Any]:
    """
    Create a standalone evaluation task for parallel execution.

    This function is designed to be pickled and executed in a separate process.

    Args:
        parameters: Parameter dict to evaluate
        evaluator: Evaluation function
        **backtest_kwargs: Additional arguments for evaluator

    Returns:
        Dict with 'parameters' and 'objective' keys
    """
    try:
        objective_value = evaluator(parameters, **backtest_kwargs)
        return {
            'parameters': parameters,
            'objective': objective_value,
            'success': True
        }
    except Exception as e:
        logger.error(f"Evaluation failed for {parameters}: {e}")
        return {
            'parameters': parameters,
            'objective': float('-inf'),  # Worst possible value
            'success': False,
            'error': str(e)
        }
