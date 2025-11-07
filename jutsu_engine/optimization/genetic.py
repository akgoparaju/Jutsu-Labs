"""
Genetic algorithm optimizer using DEAP library.

Heuristic optimization with crossover and mutation for large parameter spaces.
More efficient than grid search for spaces with >1000 combinations.
"""
from typing import Dict, List, Any, Optional
from decimal import Decimal
from datetime import datetime
import random

try:
    from deap import base, creator, tools, algorithms
    import numpy as np
    DEAP_AVAILABLE = True
except ImportError:
    DEAP_AVAILABLE = False

from jutsu_engine.optimization.base import Optimizer
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APP.OPTIMIZATION.GENETIC')


class GeneticOptimizer(Optimizer):
    """
    Genetic algorithm optimization with crossover and mutation.

    Based on DEAP library for evolutionary computation.
    Suitable for large parameter spaces where exhaustive search is infeasible.

    Uses tournament selection, two-point crossover, and uniform mutation.

    Example:
        >>> from jutsu_engine.strategies.sma_crossover import SMA_Crossover
        >>> from decimal import Decimal
        >>> from datetime import datetime
        >>>
        >>> optimizer = GeneticOptimizer(
        ...     strategy_class=SMA_Crossover,
        ...     parameter_space={
        ...         'short_period': list(range(5, 51)),  # 46 values
        ...         'long_period': list(range(50, 201))  # 151 values
        ...     },
        ...     objective='sharpe_ratio',
        ...     population_size=50,
        ...     generations=100
        ... )
        >>>
        >>> results = optimizer.optimize(
        ...     symbol='AAPL',
        ...     timeframe='1D',
        ...     start_date=datetime(2020, 1, 1),
        ...     end_date=datetime(2023, 1, 1),
        ...     initial_capital=Decimal('100000')
        ... )
        >>>
        >>> print(f"Best parameters: {results['parameters']}")
        >>> print(f"Best Sharpe: {results['objective_value']:.2f}")
        >>> print(f"Converged in {results['generations_run']} generations")
    """

    def __init__(
        self,
        *args,
        population_size: int = 50,
        generations: int = 100,
        **kwargs
    ):
        """
        Initialize genetic algorithm optimizer.

        Args:
            *args: Arguments for Optimizer base class
            population_size: Number of individuals in population
            generations: Maximum number of generations to evolve
            **kwargs: Additional arguments for Optimizer base class

        Raises:
            ImportError: If DEAP library is not installed
        """
        if not DEAP_AVAILABLE:
            raise ImportError(
                "DEAP library is required for GeneticOptimizer. "
                "Install with: pip install deap"
            )

        super().__init__(*args, **kwargs)

        self.population_size = population_size
        self.generations = generations

        logger.info(
            f"Genetic optimizer: population={population_size}, "
            f"generations={generations}"
        )

    def optimize(
        self,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.2,
        tournament_size: int = 3,
        verbose: bool = True,
        **backtest_kwargs
    ) -> Dict[str, Any]:
        """
        Run genetic algorithm optimization.

        Args:
            crossover_prob: Probability of crossover (0.0-1.0)
            mutation_prob: Probability of mutation (0.0-1.0)
            tournament_size: Number of individuals in tournament selection
            verbose: Whether to print generation statistics
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
            - 'convergence_history': Statistics for each generation
            - 'generations_run': Number of generations evolved
            - 'final_population': Final population parameters

        Raises:
            ValueError: If backtest_kwargs are invalid
            ValueError: If crossover_prob or mutation_prob not in [0, 1]
        """
        self._validate_backtest_kwargs(backtest_kwargs)

        if not 0 <= crossover_prob <= 1:
            raise ValueError(f"crossover_prob must be in [0, 1], got {crossover_prob}")

        if not 0 <= mutation_prob <= 1:
            raise ValueError(f"mutation_prob must be in [0, 1], got {mutation_prob}")

        logger.info("Starting genetic algorithm optimization")

        # Setup DEAP framework
        self._setup_deap()

        # Create toolbox
        toolbox = self._create_toolbox(tournament_size, **backtest_kwargs)

        # Initialize population
        population = toolbox.population(n=self.population_size)

        # Create hall of fame to keep best individual
        hof = tools.HallOfFame(1)

        # Setup statistics
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("avg", lambda x: np.mean(x) if x else 0)
        stats.register("std", lambda x: np.std(x) if x else 0)
        stats.register("min", lambda x: np.min(x) if x else 0)
        stats.register("max", lambda x: np.max(x) if x else 0)

        # Run evolution
        logger.info(
            f"Evolving population: {self.population_size} individuals, "
            f"{self.generations} generations"
        )

        population, logbook = algorithms.eaSimple(
            population,
            toolbox,
            cxpb=crossover_prob,
            mutpb=mutation_prob,
            ngen=self.generations,
            stats=stats,
            halloffame=hof,
            verbose=verbose
        )

        # Extract best individual
        best_individual = hof[0]
        best_params = self._individual_to_params(best_individual)

        logger.info(
            f"Genetic algorithm complete: Best {self.objective} = "
            f"{best_individual.fitness.values[0]:.4f} with parameters {best_params}"
        )

        # Extract final population parameters
        final_population = [
            self._individual_to_params(ind) for ind in population
        ]

        return {
            'parameters': best_params,
            'objective_value': best_individual.fitness.values[0],
            'convergence_history': logbook,
            'generations_run': len(logbook),
            'final_population': final_population
        }

    def _setup_deap(self):
        """Setup DEAP creator classes."""
        # Clear any existing classes
        if hasattr(creator, "FitnessMax"):
            del creator.FitnessMax
        if hasattr(creator, "Individual"):
            del creator.Individual

        # Create fitness class
        if self.maximize:
            creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        else:
            creator.create("FitnessMax", base.Fitness, weights=(-1.0,))

        # Create individual class
        creator.create("Individual", list, fitness=creator.FitnessMax)

    def _create_toolbox(
        self,
        tournament_size: int,
        **backtest_kwargs
    ) -> base.Toolbox:
        """
        Create DEAP toolbox with genetic operators.

        Args:
            tournament_size: Number of individuals in tournament
            **backtest_kwargs: Arguments for evaluation

        Returns:
            Configured DEAP toolbox
        """
        toolbox = base.Toolbox()

        # Register parameter attribute generators
        param_names = list(self.parameter_space.keys())

        for param_name in param_names:
            param_values = self.parameter_space[param_name]
            toolbox.register(
                f"attr_{param_name}",
                random.choice,
                param_values
            )

        # Register individual and population creators
        toolbox.register(
            "individual",
            tools.initCycle,
            creator.Individual,
            [getattr(toolbox, f"attr_{p}") for p in param_names],
            n=1
        )
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)

        # Register genetic operators
        toolbox.register("evaluate", self._evaluate_individual, **backtest_kwargs)
        toolbox.register("mate", tools.cxTwoPoint)

        # Register mutation operator with parameter bounds
        param_indices = {}
        for i, param_name in enumerate(param_names):
            param_values = self.parameter_space[param_name]
            param_indices[i] = param_values

        toolbox.register(
            "mutate",
            self._mutate_individual,
            param_indices=param_indices,
            indpb=0.2
        )

        toolbox.register("select", tools.selTournament, tournsize=tournament_size)

        return toolbox

    def _evaluate_individual(self, individual: list, **backtest_kwargs) -> tuple:
        """
        Evaluate fitness of an individual.

        Args:
            individual: List of parameter values
            **backtest_kwargs: Arguments for BacktestRunner

        Returns:
            Tuple with single fitness value
        """
        params = self._individual_to_params(individual)

        try:
            objective_value = self.evaluate_parameters(params, **backtest_kwargs)
            return (objective_value,)
        except Exception as e:
            logger.error(f"Failed to evaluate individual {params}: {e}")
            # Return worst possible fitness
            worst_value = float('-inf') if self.maximize else float('inf')
            return (worst_value,)

    def _individual_to_params(self, individual: list) -> Dict[str, Any]:
        """
        Convert individual (list) to parameter dictionary.

        Args:
            individual: List of parameter values

        Returns:
            Dictionary mapping parameter names to values
        """
        param_names = list(self.parameter_space.keys())
        return {name: individual[i] for i, name in enumerate(param_names)}

    def _mutate_individual(
        self,
        individual: list,
        param_indices: Dict[int, List[Any]],
        indpb: float
    ) -> tuple:
        """
        Mutate an individual by randomly changing parameters.

        Args:
            individual: Individual to mutate
            param_indices: Dict mapping index to valid parameter values
            indpb: Probability of mutating each parameter

        Returns:
            Tuple with mutated individual
        """
        for i in range(len(individual)):
            if random.random() < indpb:
                # Mutate this parameter to a random valid value
                individual[i] = random.choice(param_indices[i])

        return (individual,)

    def get_convergence_data(self) -> Optional[Dict[str, Any]]:
        """
        Get convergence statistics for plotting.

        Returns:
            Dictionary with convergence data or None if not optimized yet

        Note:
            Must be called after optimize()
        """
        # This would require storing logbook as instance variable
        # Left as exercise or future enhancement
        logger.warning(
            "get_convergence_data() not fully implemented. "
            "Use 'convergence_history' from optimize() return value."
        )
        return None
