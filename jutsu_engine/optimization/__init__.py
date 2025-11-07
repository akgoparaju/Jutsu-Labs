"""
Parameter Optimization Module for Jutsu Labs Backtesting Engine.

This module provides tools for optimizing strategy parameters through various methods:
- Grid Search: Exhaustive parameter space exploration
- Genetic Algorithm: Heuristic optimization with crossover/mutation
- Walk-Forward Analysis: Rolling window out-of-sample validation

Example:
    from jutsu_engine.optimization import GridSearchOptimizer
    from jutsu_engine.strategies.sma_crossover import SMA_Crossover
    from datetime import datetime

    optimizer = GridSearchOptimizer(
        strategy_class=SMA_Crossover,
        parameter_space={
            'short_period': [10, 20, 30],
            'long_period': [50, 100, 200]
        },
        objective='sharpe_ratio'
    )

    results = optimizer.optimize(
        symbol='AAPL',
        timeframe='1D',
        start_date=datetime(2020, 1, 1),
        end_date=datetime(2023, 1, 1),
        initial_capital=Decimal('100000')
    )

    print(f"Best parameters: {results['parameters']}")
    print(f"Best Sharpe: {results['objective_value']:.2f}")
"""

from jutsu_engine.optimization.base import Optimizer
from jutsu_engine.optimization.grid_search import GridSearchOptimizer
from jutsu_engine.optimization.genetic import GeneticOptimizer
from jutsu_engine.optimization.walk_forward import WalkForwardAnalyzer
from jutsu_engine.optimization.results import OptimizationResults
from jutsu_engine.optimization.visualizer import OptimizationVisualizer
from jutsu_engine.optimization.parallel import ParallelExecutor

__all__ = [
    'Optimizer',
    'GridSearchOptimizer',
    'GeneticOptimizer',
    'WalkForwardAnalyzer',
    'OptimizationResults',
    'OptimizationVisualizer',
    'ParallelExecutor',
]
