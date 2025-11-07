"""
Walk-forward analysis for out-of-sample validation.

Divides time series into rolling windows with in-sample optimization
and out-of-sample testing to prevent overfitting.
"""
from typing import Dict, List, Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta
import pandas as pd

from jutsu_engine.optimization.base import Optimizer
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.data.handlers.database import DatabaseDataHandler
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APP.OPTIMIZATION.WALKFORWARD')


class WalkForwardAnalyzer:
    """
    Walk-forward analysis for out-of-sample validation.

    Divides time series into rolling windows:
    - In-sample period: Optimize parameters on historical data
    - Out-of-sample period: Test optimized parameters on unseen data

    This helps detect overfitting by validating on truly unseen data.

    Example:
        >>> from jutsu_engine.optimization import GridSearchOptimizer
        >>> from jutsu_engine.strategies.sma_crossover import SMA_Crossover
        >>>
        >>> optimizer = GridSearchOptimizer(
        ...     strategy_class=SMA_Crossover,
        ...     parameter_space={'short_period': [10, 20], 'long_period': [50, 100]}
        ... )
        >>>
        >>> analyzer = WalkForwardAnalyzer(
        ...     optimizer=optimizer,
        ...     in_sample_days=252,  # 1 year
        ...     out_sample_days=63,  # 3 months
        ...     step_size_days=63    # Roll forward 3 months
        ... )
        >>>
        >>> results = analyzer.analyze(
        ...     symbol='AAPL',
        ...     timeframe='1D',
        ...     start_date=datetime(2020, 1, 1),
        ...     end_date=datetime(2023, 1, 1),
        ...     initial_capital=Decimal('100000')
        ... )
        >>>
        >>> print(f"Out-of-sample Sharpe: {results['oos_sharpe_ratio']:.2f}")
        >>> print(f"Windows tested: {results['n_windows']}")
    """

    def __init__(
        self,
        optimizer: Optimizer,
        in_sample_days: int = 252,
        out_sample_days: int = 63,
        step_size_days: int = 63,
        min_bars_required: int = 100
    ):
        """
        Initialize walk-forward analyzer.

        Args:
            optimizer: Optimizer to use for in-sample optimization
            in_sample_days: Number of days for in-sample optimization period
            out_sample_days: Number of days for out-of-sample testing period
            step_size_days: Number of days to roll forward between windows
            min_bars_required: Minimum bars required in a window

        Raises:
            ValueError: If window sizes are invalid
        """
        if in_sample_days < min_bars_required:
            raise ValueError(
                f"in_sample_days ({in_sample_days}) must be >= "
                f"min_bars_required ({min_bars_required})"
            )

        if out_sample_days < 1:
            raise ValueError(f"out_sample_days must be positive, got {out_sample_days}")

        if step_size_days < 1:
            raise ValueError(f"step_size_days must be positive, got {step_size_days}")

        self.optimizer = optimizer
        self.in_sample_days = in_sample_days
        self.out_sample_days = out_sample_days
        self.step_size_days = step_size_days
        self.min_bars_required = min_bars_required

        logger.info(
            f"Walk-forward analyzer: in_sample={in_sample_days} days, "
            f"out_sample={out_sample_days} days, step={step_size_days} days"
        )

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: Decimal,
        **optimizer_kwargs
    ) -> Dict[str, Any]:
        """
        Run walk-forward analysis.

        Args:
            symbol: Stock ticker symbol
            timeframe: Data timeframe ('1D', '1H', etc.)
            start_date: Analysis start date
            end_date: Analysis end date
            initial_capital: Initial capital for backtests
            **optimizer_kwargs: Additional arguments for optimizer.optimize()

        Returns:
            Dictionary with:
            - 'in_sample_results': List of optimization results per window
            - 'out_sample_results': List of out-of-sample performance per window
            - 'oos_sharpe_ratio': Combined out-of-sample Sharpe ratio
            - 'oos_total_return': Combined out-of-sample total return
            - 'n_windows': Number of windows analyzed
            - 'windows': List of window date ranges

        Raises:
            ValueError: If date range is too short for analysis
        """
        logger.info(
            f"Starting walk-forward analysis: {symbol} {timeframe} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        # Create windows
        windows = self._create_windows(start_date, end_date)

        if not windows:
            raise ValueError(
                f"Date range too short for walk-forward analysis. "
                f"Need at least {self.in_sample_days + self.out_sample_days} days."
            )

        logger.info(f"Created {len(windows)} walk-forward windows")

        in_sample_results = []
        out_sample_results = []

        for i, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
            logger.info(
                f"\nWindow {i+1}/{len(windows)}: "
                f"IS {is_start.date()} to {is_end.date()}, "
                f"OOS {oos_start.date()} to {oos_end.date()}"
            )

            # Optimize on in-sample data
            logger.info("  Optimizing on in-sample data...")
            opt_result = self.optimizer.optimize(
                symbol=symbol,
                timeframe=timeframe,
                start_date=is_start,
                end_date=is_end,
                initial_capital=initial_capital,
                **optimizer_kwargs
            )
            in_sample_results.append(opt_result)

            logger.info(
                f"  Best parameters: {opt_result['parameters']}, "
                f"{self.optimizer.objective}={opt_result['objective_value']:.4f}"
            )

            # Test on out-of-sample data
            logger.info("  Testing on out-of-sample data...")
            strategy = self.optimizer.strategy_class(**opt_result['parameters'])

            config = {
                'symbol': symbol,
                'timeframe': timeframe,
                'start_date': oos_start,
                'end_date': oos_end,
                'initial_capital': initial_capital,
            }

            runner = BacktestRunner(config)
            oos_result = runner.run(strategy)

            out_sample_results.append({
                'metrics': oos_result,
                'parameters': opt_result['parameters'],
                'window_start': oos_start,
                'window_end': oos_end
            })

            logger.info(
                f"  Out-of-sample {self.optimizer.objective}: "
                f"{oos_result[self.optimizer.objective]:.4f}"
            )

        # Aggregate results
        aggregated = self._aggregate_results(out_sample_results)

        logger.info(
            f"\nWalk-forward analysis complete: "
            f"OOS Sharpe={aggregated['oos_sharpe_ratio']:.2f}, "
            f"OOS Return={aggregated['oos_total_return']:.2%}"
        )

        return {
            'in_sample_results': in_sample_results,
            'out_sample_results': out_sample_results,
            'oos_sharpe_ratio': aggregated['oos_sharpe_ratio'],
            'oos_total_return': aggregated['oos_total_return'],
            'oos_max_drawdown': aggregated['oos_max_drawdown'],
            'oos_win_rate': aggregated['oos_win_rate'],
            'n_windows': len(windows),
            'windows': [
                {
                    'is_start': is_start,
                    'is_end': is_end,
                    'oos_start': oos_start,
                    'oos_end': oos_end
                }
                for is_start, is_end, oos_start, oos_end in windows
            ]
        }

    def _create_windows(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[tuple[datetime, datetime, datetime, datetime]]:
        """
        Create in-sample and out-of-sample windows.

        Args:
            start_date: Analysis start date
            end_date: Analysis end date

        Returns:
            List of tuples: (is_start, is_end, oos_start, oos_end)
        """
        windows = []
        current_start = start_date

        while True:
            # Calculate window boundaries
            is_start = current_start
            is_end = is_start + timedelta(days=self.in_sample_days)
            oos_start = is_end
            oos_end = oos_start + timedelta(days=self.out_sample_days)

            # Check if we have enough data for this window
            if oos_end > end_date:
                break

            windows.append((is_start, is_end, oos_start, oos_end))

            # Roll forward
            current_start += timedelta(days=self.step_size_days)

        return windows

    def _aggregate_results(
        self,
        oos_results: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Aggregate out-of-sample results across windows.

        Args:
            oos_results: List of out-of-sample result dictionaries

        Returns:
            Dictionary with aggregated metrics
        """
        if not oos_results:
            return {
                'oos_sharpe_ratio': 0.0,
                'oos_total_return': 0.0,
                'oos_max_drawdown': 0.0,
                'oos_win_rate': 0.0
            }

        # Extract metrics from each window
        sharpe_ratios = [r['metrics']['sharpe_ratio'] for r in oos_results]
        total_returns = [r['metrics']['total_return'] for r in oos_results]
        max_drawdowns = [r['metrics']['max_drawdown'] for r in oos_results]
        win_rates = [r['metrics']['win_rate'] for r in oos_results]

        # Calculate averages
        return {
            'oos_sharpe_ratio': sum(sharpe_ratios) / len(sharpe_ratios),
            'oos_total_return': sum(total_returns) / len(total_returns),
            'oos_max_drawdown': sum(max_drawdowns) / len(max_drawdowns),
            'oos_win_rate': sum(win_rates) / len(win_rates)
        }

    def plot_window_performance(
        self,
        oos_results: List[Dict[str, Any]],
        metric: str = 'sharpe_ratio'
    ) -> None:
        """
        Plot metric across walk-forward windows.

        Args:
            oos_results: Out-of-sample results from analyze()
            metric: Metric to plot

        Note:
            Requires matplotlib. Implementation left for visualizer module.
        """
        logger.warning(
            "plot_window_performance() should use OptimizationVisualizer. "
            "This is a placeholder method."
        )
        pass
