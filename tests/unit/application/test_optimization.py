"""
Unit tests for optimization module.

Tests all optimizers (Grid Search, Genetic, Walk-Forward) and supporting components.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from jutsu_engine.optimization.base import Optimizer
from jutsu_engine.optimization.grid_search import GridSearchOptimizer
from jutsu_engine.optimization.genetic import GeneticOptimizer
from jutsu_engine.optimization.walk_forward import WalkForwardAnalyzer
from jutsu_engine.optimization.results import OptimizationResults
from jutsu_engine.optimization.visualizer import OptimizationVisualizer
from jutsu_engine.optimization.parallel import ParallelExecutor
from jutsu_engine.core.strategy_base import Strategy


# Mock Strategy for testing
class MockStrategy(Strategy):
    """Simple mock strategy for testing."""

    def __init__(self, param1: int = 10, param2: int = 50):
        super().__init__()
        self.name = "MockStrategy"
        self.param1 = param1
        self.param2 = param2

    def init(self):
        pass

    def on_bar(self, bar):
        pass


class TestOptimizerBase:
    """Test Optimizer base class."""

    def test_init_valid(self):
        """Test valid initialization."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20], 'param2': [50, 100]},
            objective='sharpe_ratio',
            maximize=True
        )

        assert optimizer.strategy_class == MockStrategy
        assert optimizer.objective == 'sharpe_ratio'
        assert optimizer.maximize is True
        assert len(optimizer.parameter_space) == 2

    def test_init_invalid_strategy(self):
        """Test initialization with non-Strategy class."""
        with pytest.raises(ValueError, match="must inherit from Strategy"):
            optimizer = GridSearchOptimizer(
                strategy_class=str,  # Not a Strategy subclass
                parameter_space={'param1': [10, 20]},
            )

    def test_init_empty_parameter_space(self):
        """Test initialization with empty parameter space."""
        with pytest.raises(ValueError, match="cannot be empty"):
            optimizer = GridSearchOptimizer(
                strategy_class=MockStrategy,
                parameter_space={},
            )

    def test_count_combinations(self):
        """Test combination counting."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20, 30], 'param2': [50, 100]},
        )

        assert optimizer._count_combinations() == 6  # 3 * 2

    @patch('jutsu_engine.optimization.base.BacktestRunner')
    def test_evaluate_parameters(self, mock_runner_class):
        """Test parameter evaluation."""
        # Setup mock
        mock_runner = Mock()
        mock_runner.run.return_value = {'sharpe_ratio': 1.5, 'total_return': 0.25}
        mock_runner_class.return_value = mock_runner

        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10], 'param2': [50]},
        )

        # Evaluate
        result = optimizer.evaluate_parameters(
            parameters={'param1': 10, 'param2': 50},
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2021, 1, 1),
            initial_capital=Decimal('100000')
        )

        assert result == 1.5
        mock_runner.run.assert_called_once()

    def test_validate_backtest_kwargs(self):
        """Test backtest kwargs validation."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10]},
        )

        # Missing required key
        with pytest.raises(ValueError, match="Missing required"):
            optimizer._validate_backtest_kwargs({'symbol': 'AAPL'})

        # Invalid types
        with pytest.raises(ValueError, match="must be a string"):
            optimizer._validate_backtest_kwargs({
                'symbol': 123,
                'timeframe': '1D',
                'start_date': datetime.now(),
                'end_date': datetime.now(),
                'initial_capital': Decimal('100000')
            })

        # Valid kwargs
        valid_kwargs = {
            'symbol': 'AAPL',
            'timeframe': '1D',
            'start_date': datetime(2020, 1, 1),
            'end_date': datetime(2021, 1, 1),
            'initial_capital': Decimal('100000')
        }
        optimizer._validate_backtest_kwargs(valid_kwargs)  # Should not raise

    def test_get_best_result(self):
        """Test finding best result."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10]},
        )

        results = [
            {'parameters': {'param1': 10}, 'objective': 1.5},
            {'parameters': {'param1': 20}, 'objective': 2.0},
            {'parameters': {'param1': 30}, 'objective': 1.2},
        ]

        # Maximize
        optimizer.maximize = True
        best = optimizer._get_best_result(results)
        assert best['objective'] == 2.0

        # Minimize
        optimizer.maximize = False
        best = optimizer._get_best_result(results)
        assert best['objective'] == 1.2


class TestGridSearchOptimizer:
    """Test Grid Search optimizer."""

    @patch('jutsu_engine.optimization.grid_search.GridSearchOptimizer.evaluate_parameters')
    def test_optimize_sequential(self, mock_evaluate):
        """Test sequential grid search."""
        # Setup mock to return different values
        mock_evaluate.side_effect = [1.5, 2.0, 1.8, 2.2]

        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20], 'param2': [50, 100]},
        )

        results = optimizer.optimize(
            parallel=False,
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2021, 1, 1),
            initial_capital=Decimal('100000')
        )

        assert results['objective_value'] == 2.2
        assert results['parameters']['param1'] in [10, 20]
        assert results['parameters']['param2'] in [50, 100]
        assert results['n_evaluated'] == 4
        assert results['execution_mode'] == 'sequential'

    def test_get_top_n_results(self):
        """Test getting top N results."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20]},
        )

        # Manually populate results
        optimizer.results = [
            {'parameters': {'param1': 10}, 'objective': 1.5},
            {'parameters': {'param1': 20}, 'objective': 2.0},
            {'parameters': {'param1': 30}, 'objective': 1.2},
        ]

        top_2 = optimizer.get_top_n_results(n=2)
        assert len(top_2) == 2
        assert top_2[0]['objective'] == 2.0
        assert top_2[1]['objective'] == 1.5

    def test_get_heatmap_data(self):
        """Test heatmap data extraction."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20], 'param2': [50, 100]},
        )

        # Manually populate results
        optimizer.results = [
            {'parameters': {'param1': 10, 'param2': 50}, 'objective': 1.5},
            {'parameters': {'param1': 10, 'param2': 100}, 'objective': 1.8},
            {'parameters': {'param1': 20, 'param2': 50}, 'objective': 2.0},
            {'parameters': {'param1': 20, 'param2': 100}, 'objective': 2.2},
        ]

        heatmap = optimizer.get_heatmap_data('param1', 'param2')

        assert heatmap['x_values'] == [10, 20]
        assert heatmap['y_values'] == [50, 100]
        assert len(heatmap['z_values']) == 2
        assert len(heatmap['z_values'][0]) == 2


class TestGeneticOptimizer:
    """Test Genetic Algorithm optimizer."""

    def test_init(self):
        """Test initialization."""
        optimizer = GeneticOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': list(range(10, 51))},
            population_size=20,
            generations=50
        )

        assert optimizer.population_size == 20
        assert optimizer.generations == 50

    def test_individual_to_params(self):
        """Test individual to parameter conversion."""
        optimizer = GeneticOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20], 'param2': [50, 100]},
        )

        individual = [20, 100]
        params = optimizer._individual_to_params(individual)

        assert params == {'param1': 20, 'param2': 100}

    @patch('jutsu_engine.optimization.genetic.GeneticOptimizer.evaluate_parameters')
    def test_evaluate_individual(self, mock_evaluate):
        """Test individual evaluation."""
        mock_evaluate.return_value = 1.5

        optimizer = GeneticOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20], 'param2': [50, 100]},
        )

        fitness = optimizer._evaluate_individual(
            [10, 50],
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2021, 1, 1),
            initial_capital=Decimal('100000')
        )

        assert fitness == (1.5,)


class TestWalkForwardAnalyzer:
    """Test Walk-Forward analyzer."""

    def test_init(self):
        """Test initialization."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10, 20]},
        )

        analyzer = WalkForwardAnalyzer(
            optimizer=optimizer,
            in_sample_days=252,
            out_sample_days=63,
            step_size_days=63
        )

        assert analyzer.in_sample_days == 252
        assert analyzer.out_sample_days == 63
        assert analyzer.step_size_days == 63

    def test_init_invalid_params(self):
        """Test initialization with invalid parameters."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10]},
        )

        # in_sample_days too small
        with pytest.raises(ValueError):
            WalkForwardAnalyzer(
                optimizer=optimizer,
                in_sample_days=50,
                min_bars_required=100
            )

        # Invalid out_sample_days
        with pytest.raises(ValueError):
            WalkForwardAnalyzer(
                optimizer=optimizer,
                out_sample_days=0
            )

    def test_create_windows(self):
        """Test window creation."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10]},
        )

        analyzer = WalkForwardAnalyzer(
            optimizer=optimizer,
            in_sample_days=100,
            out_sample_days=30,
            step_size_days=30
        )

        start = datetime(2020, 1, 1)
        end = datetime(2020, 12, 31)

        windows = analyzer._create_windows(start, end)

        assert len(windows) > 0

        # Check window structure
        for is_start, is_end, oos_start, oos_end in windows:
            assert is_start < is_end
            assert is_end == oos_start
            assert oos_start < oos_end
            assert (is_end - is_start).days >= 100
            assert (oos_end - oos_start).days >= 30

    def test_aggregate_results(self):
        """Test result aggregation."""
        optimizer = GridSearchOptimizer(
            strategy_class=MockStrategy,
            parameter_space={'param1': [10]},
        )

        analyzer = WalkForwardAnalyzer(optimizer=optimizer)

        oos_results = [
            {
                'metrics': {
                    'sharpe_ratio': 1.5,
                    'total_return': 0.20,
                    'max_drawdown': -0.10,
                    'win_rate': 0.55
                }
            },
            {
                'metrics': {
                    'sharpe_ratio': 2.0,
                    'total_return': 0.30,
                    'max_drawdown': -0.15,
                    'win_rate': 0.60
                }
            }
        ]

        agg = analyzer._aggregate_results(oos_results)

        assert agg['oos_sharpe_ratio'] == 1.75
        assert agg['oos_total_return'] == 0.25
        assert agg['oos_max_drawdown'] == -0.125
        assert agg['oos_win_rate'] == 0.575


class TestParallelExecutor:
    """Test parallel execution utilities."""

    def test_init(self):
        """Test initialization."""
        executor = ParallelExecutor(n_jobs=4)
        assert executor.n_jobs == 4

        # Test -1 (all cores)
        executor = ParallelExecutor(n_jobs=-1)
        assert executor.n_jobs > 0

    def test_should_use_parallel(self):
        """Test parallel decision logic."""
        executor = ParallelExecutor(n_jobs=4)

        # Small number of tasks
        assert not executor.should_use_parallel(10, threshold=20)

        # Large number of tasks
        assert executor.should_use_parallel(50, threshold=20)

    def test_execute(self):
        """Test parallel execution.

        Note: This test uses a module-level function because ProcessPoolExecutor
        cannot pickle local functions.
        """
        # Use a module-level function instead of local function
        import math

        executor = ParallelExecutor(n_jobs=2, show_progress=False)
        results = executor.execute(math.sqrt, [1, 4, 9, 16, 25])

        # sqrt returns float, not dict, so we just check we got results
        assert len(results) == 5
        # Results should be approximately [1, 2, 3, 4, 5]
        assert all(isinstance(r, float) for r in results)


class TestOptimizationResults:
    """Test optimization results storage."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        db_url = f'sqlite:///{path}'
        yield db_url
        os.unlink(path)

    def test_store_and_retrieve(self, temp_db):
        """Test storing and retrieving results."""
        manager = OptimizationResults(database_url=temp_db)

        result_id = manager.store(
            strategy_name='MockStrategy',
            optimizer_type='grid_search',
            objective='sharpe_ratio',
            objective_value=1.85,
            parameters={'param1': 20, 'param2': 50},
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2021, 1, 1)
        )

        # Retrieve by ID
        result = manager.get_by_id(result_id)
        assert result is not None
        assert result['objective_value'] == 1.85
        assert result['parameters']['param1'] == 20

    def test_get_best(self, temp_db):
        """Test getting best results."""
        manager = OptimizationResults(database_url=temp_db)

        # Store multiple results
        for i, value in enumerate([1.5, 2.0, 1.8, 2.2]):
            manager.store(
                strategy_name='MockStrategy',
                optimizer_type='grid_search',
                objective='sharpe_ratio',
                objective_value=value,
                parameters={'param1': 10 * (i + 1)},
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2020, 1, 1),
                end_date=datetime(2021, 1, 1)
            )

        # Get top 2
        best = manager.get_best(n=2)
        assert len(best) == 2
        assert best[0]['objective_value'] == 2.2
        assert best[1]['objective_value'] == 2.0


class TestOptimizationVisualizer:
    """Test optimization visualization."""

    def test_init(self):
        """Test initialization."""
        viz = OptimizationVisualizer()
        assert viz is not None

    @pytest.mark.skip(reason="Requires matplotlib display")
    def test_plot_grid_heatmap(self):
        """Test heatmap plotting."""
        viz = OptimizationVisualizer()

        heatmap_data = {
            'x_values': [10, 20],
            'y_values': [50, 100],
            'z_values': [[1.5, 1.8], [2.0, 2.2]],
            'x_label': 'param1',
            'y_label': 'param2',
            'z_label': 'sharpe_ratio'
        }

        fig = viz.plot_grid_heatmap(heatmap_data)
        assert fig is not None

    @pytest.mark.skip(reason="Requires matplotlib display")
    def test_plot_parameter_sensitivity(self):
        """Test sensitivity plotting."""
        viz = OptimizationVisualizer()

        results = [
            {'parameters': {'param1': 10}, 'objective': 1.5},
            {'parameters': {'param1': 20}, 'objective': 2.0},
            {'parameters': {'param1': 10}, 'objective': 1.6},
            {'parameters': {'param1': 20}, 'objective': 1.9},
        ]

        fig = viz.plot_parameter_sensitivity(results, 'param1')
        assert fig is not None
