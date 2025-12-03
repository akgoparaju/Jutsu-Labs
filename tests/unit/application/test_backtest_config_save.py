"""Test backtest configuration YAML saving."""
import pytest
import yaml
from pathlib import Path
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.strategies.sma_crossover import SMA_Crossover
from jutsu_engine.core.strategy_base import Strategy


class MockStrategy(Strategy):
    """Mock strategy for testing."""

    def __init__(self, warmup_bars: int = 0):
        super().__init__()
        self.name = "MockStrategy"
        self._warmup_bars = warmup_bars

    def init(self):
        """Initialize strategy."""
        pass

    def on_bar(self, bar):
        """Process bar (no-op for testing)."""
        pass

    def get_required_warmup_bars(self) -> int:
        """Return warmup bars for testing."""
        return self._warmup_bars


@pytest.fixture
def config():
    """Standard backtest configuration."""
    return {
        'symbols': ['AAPL'],
        'timeframe': '1D',
        'start_date': datetime(2020, 1, 1),
        'end_date': datetime(2020, 12, 31),
        'initial_capital': Decimal('100000'),
        'commission_per_share': Decimal('0.01'),
        'slippage_percent': Decimal('0.001'),
    }


@patch('jutsu_engine.application.backtest_runner.DatabaseDataHandler')
@patch('jutsu_engine.application.backtest_runner.EventLoop')
@patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
@patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
@patch('jutsu_engine.performance.trade_logger.TradeLogger')
def test_backtest_saves_config_yaml(
    mock_trade_logger,
    mock_analyzer,
    mock_portfolio,
    mock_event_loop,
    mock_data_handler,
    config,
    tmp_path
):
    """Test that backtest saves config YAML file."""
    # Setup mocks
    mock_data_handler_instance = MagicMock()
    mock_data_handler.return_value = mock_data_handler_instance

    mock_event_loop_instance = MagicMock()
    mock_event_loop.return_value = mock_event_loop_instance
    mock_event_loop_instance.all_fills = []
    mock_event_loop_instance.all_bars = []
    mock_event_loop_instance.get_results.return_value = {
        'total_bars': 252,
        'signals_generated': 10,
        'orders_executed': 10
    }

    mock_portfolio_instance = MagicMock()
    mock_portfolio.return_value = mock_portfolio_instance
    mock_portfolio_instance.get_equity_curve.return_value = []
    mock_portfolio_instance.get_daily_snapshots.return_value = []

    mock_analyzer_instance = MagicMock()
    mock_analyzer.return_value = mock_analyzer_instance
    mock_analyzer_instance.calculate_metrics.return_value = {
        'total_return': 0.15,
        'annualized_return': 0.12,
        'sharpe_ratio': 1.2,
        'max_drawdown': -0.08,
        'total_trades': 10,
        'win_rate': 0.6,
        'final_value': 115000.0,
        'trades_csv_path': '/tmp/trades.csv'
    }
    mock_analyzer_instance.generate_report.return_value = "Mock Report"

    mock_trade_logger_instance = MagicMock()
    mock_trade_logger.return_value = mock_trade_logger_instance
    mock_trade_logger_instance.export_to_csv.return_value = '/tmp/trades.csv'

    runner = BacktestRunner(config)
    strategy = SMA_Crossover(short_period=20, long_period=50)

    # Run backtest
    results = runner.run(strategy, output_dir=str(tmp_path))

    # Verify config YAML created
    assert 'config_yaml_path' in results
    config_file = Path(results['config_yaml_path'])
    assert config_file.exists()
    assert config_file.name == 'config.yaml'

    # Load and validate YAML content
    with open(config_file, 'r') as f:
        saved_config = yaml.safe_load(f)

    # Validate structure
    assert 'timestamp' in saved_config
    assert 'execution_type' in saved_config
    assert 'strategy' in saved_config
    assert 'backtest_config' in saved_config
    assert 'warmup' in saved_config
    assert 'results_summary' in saved_config

    # Validate strategy section
    assert saved_config['strategy']['name'] == 'SMA_Crossover'
    assert 'short_period' in saved_config['strategy']['parameters']
    assert saved_config['strategy']['parameters']['short_period'] == 20
    assert saved_config['strategy']['parameters']['long_period'] == 50

    # Validate backtest_config section
    assert saved_config['backtest_config']['symbols'] == ['AAPL']
    assert saved_config['backtest_config']['start_date'] == '2020-01-01'
    assert saved_config['backtest_config']['end_date'] == '2020-12-31'

    # Validate results_summary section
    assert 'total_return' in saved_config['results_summary']
    assert saved_config['results_summary']['total_return'] == 0.15
    assert saved_config['results_summary']['sharpe_ratio'] == 1.2


def test_execution_type_detection(config):
    """Test execution type detection from output path."""
    runner = BacktestRunner(config)

    # WFO paths
    assert runner._detect_execution_type('wfo_results/window_001/oos_backtest') == 'wfo'
    assert runner._detect_execution_type('output/WFO_run/window_05') == 'wfo'

    # Grid search paths
    assert runner._detect_execution_type('grid_search_results/run_001') == 'grid_search'
    assert runner._detect_execution_type('output/grid/run_10') == 'grid_search'

    # Direct backtest
    assert runner._detect_execution_type('output') == 'direct'
    assert runner._detect_execution_type('custom/path') == 'direct'


def test_strategy_param_extraction_with_decimals(config):
    """Test that Decimal parameters are converted to float in YAML."""
    runner = BacktestRunner(config)

    strategy = SMA_Crossover(
        short_period=10,
        long_period=30,
        position_percent=Decimal('0.8')
    )

    params = runner._extract_strategy_params(strategy)

    # Decimals should be converted to float
    assert isinstance(params['position_percent'], float)
    assert params['position_percent'] == 0.8

    # Ints should stay as-is
    assert isinstance(params['short_period'], int)
    assert params['short_period'] == 10
    assert isinstance(params['long_period'], int)
    assert params['long_period'] == 30


@patch('jutsu_engine.application.backtest_runner.DatabaseDataHandler')
@patch('jutsu_engine.application.backtest_runner.EventLoop')
@patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
@patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
@patch('jutsu_engine.performance.trade_logger.TradeLogger')
def test_wfo_backtest_saves_config(
    mock_trade_logger,
    mock_analyzer,
    mock_portfolio,
    mock_event_loop,
    mock_data_handler,
    config,
    tmp_path
):
    """Test that WFO backtests save config files."""
    # Setup mocks
    mock_data_handler_instance = MagicMock()
    mock_data_handler.return_value = mock_data_handler_instance

    mock_event_loop_instance = MagicMock()
    mock_event_loop.return_value = mock_event_loop_instance
    mock_event_loop_instance.all_fills = []
    mock_event_loop_instance.all_bars = []
    mock_event_loop_instance.get_results.return_value = {
        'total_bars': 126,
        'signals_generated': 5,
        'orders_executed': 5
    }

    mock_portfolio_instance = MagicMock()
    mock_portfolio.return_value = mock_portfolio_instance
    mock_portfolio_instance.get_equity_curve.return_value = []
    mock_portfolio_instance.get_daily_snapshots.return_value = []

    mock_analyzer_instance = MagicMock()
    mock_analyzer.return_value = mock_analyzer_instance
    mock_analyzer_instance.calculate_metrics.return_value = {
        'total_return': 0.12,
        'annualized_return': 0.10,
        'sharpe_ratio': 1.1,
        'max_drawdown': -0.05,
        'total_trades': 5,
        'win_rate': 0.6,
        'final_value': 112000.0,
        'trades_csv_path': '/tmp/trades.csv'
    }
    mock_analyzer_instance.generate_report.return_value = "Mock Report"

    mock_trade_logger_instance = MagicMock()
    mock_trade_logger.return_value = mock_trade_logger_instance
    mock_trade_logger_instance.export_to_csv.return_value = '/tmp/trades.csv'

    runner = BacktestRunner(config)
    strategy = SMA_Crossover(short_period=10, long_period=30)

    # Simulate WFO path
    wfo_output = tmp_path / 'wfo_results' / 'window_001' / 'oos_backtest'

    results = runner.run(strategy, output_dir=str(wfo_output))

    # Verify config saved
    assert 'config_yaml_path' in results
    config_file = Path(results['config_yaml_path'])
    assert config_file.exists()

    # Verify execution type detected
    with open(config_file, 'r') as f:
        saved_config = yaml.safe_load(f)

    assert saved_config['execution_type'] == 'wfo'


@patch('jutsu_engine.application.backtest_runner.DatabaseDataHandler')
@patch('jutsu_engine.application.backtest_runner.EventLoop')
@patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
@patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
@patch('jutsu_engine.performance.trade_logger.TradeLogger')
def test_config_yaml_includes_warmup_info(
    mock_trade_logger,
    mock_analyzer,
    mock_portfolio,
    mock_event_loop,
    mock_data_handler,
    config,
    tmp_path
):
    """Test that config YAML includes warmup information."""
    # Setup mocks
    mock_data_handler_instance = MagicMock()
    mock_data_handler.return_value = mock_data_handler_instance

    mock_event_loop_instance = MagicMock()
    mock_event_loop.return_value = mock_event_loop_instance
    mock_event_loop_instance.all_fills = []
    mock_event_loop_instance.all_bars = []
    mock_event_loop_instance.get_results.return_value = {
        'total_bars': 252,
        'signals_generated': 10,
        'orders_executed': 10
    }

    mock_portfolio_instance = MagicMock()
    mock_portfolio.return_value = mock_portfolio_instance
    mock_portfolio_instance.get_equity_curve.return_value = []
    mock_portfolio_instance.get_daily_snapshots.return_value = []

    mock_analyzer_instance = MagicMock()
    mock_analyzer.return_value = mock_analyzer_instance
    mock_analyzer_instance.calculate_metrics.return_value = {
        'total_return': 0.15,
        'annualized_return': 0.12,
        'sharpe_ratio': 1.2,
        'max_drawdown': -0.08,
        'total_trades': 10,
        'win_rate': 0.6,
        'final_value': 115000.0,
        'trades_csv_path': '/tmp/trades.csv'
    }
    mock_analyzer_instance.generate_report.return_value = "Mock Report"

    mock_trade_logger_instance = MagicMock()
    mock_trade_logger.return_value = mock_trade_logger_instance
    mock_trade_logger_instance.export_to_csv.return_value = '/tmp/trades.csv'

    runner = BacktestRunner(config)
    strategy = SMA_Crossover(short_period=20, long_period=50)

    # Run backtest
    results = runner.run(strategy, output_dir=str(tmp_path))

    # Load config
    with open(results['config_yaml_path'], 'r') as f:
        saved_config = yaml.safe_load(f)

    # Validate warmup section
    assert 'warmup' in saved_config
    assert 'required_bars' in saved_config['warmup']
    assert 'warmup_enabled' in saved_config['warmup']
    assert 'warmup_end_date' in saved_config['warmup']

    # SMA_Crossover doesn't override get_required_warmup_bars(), so defaults to 0
    # (It relies on EventLoop to accumulate bars before signals are valid)
    assert saved_config['warmup']['required_bars'] == 0
    assert saved_config['warmup']['warmup_enabled'] is False
    assert saved_config['warmup']['warmup_end_date'] is None


@patch('jutsu_engine.application.backtest_runner.DatabaseDataHandler')
@patch('jutsu_engine.application.backtest_runner.EventLoop')
@patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
@patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
@patch('jutsu_engine.performance.trade_logger.TradeLogger')
def test_config_yaml_decimal_conversion(
    mock_trade_logger,
    mock_analyzer,
    mock_portfolio,
    mock_event_loop,
    mock_data_handler,
    tmp_path
):
    """Test that all Decimal values are properly converted to float in YAML."""
    config = {
        'symbols': ['AAPL'],
        'timeframe': '1D',
        'start_date': datetime(2020, 1, 1),
        'end_date': datetime(2020, 12, 31),
        'initial_capital': Decimal('100000.50'),
        'commission_per_share': Decimal('0.015'),
        'slippage_percent': Decimal('0.0012'),
    }

    # Setup mocks
    mock_data_handler_instance = MagicMock()
    mock_data_handler.return_value = mock_data_handler_instance

    mock_event_loop_instance = MagicMock()
    mock_event_loop.return_value = mock_event_loop_instance
    mock_event_loop_instance.all_fills = []
    mock_event_loop_instance.all_bars = []
    mock_event_loop_instance.get_results.return_value = {
        'total_bars': 252,
        'signals_generated': 8,
        'orders_executed': 8
    }

    mock_portfolio_instance = MagicMock()
    mock_portfolio.return_value = mock_portfolio_instance
    mock_portfolio_instance.get_equity_curve.return_value = []
    mock_portfolio_instance.get_daily_snapshots.return_value = []

    mock_analyzer_instance = MagicMock()
    mock_analyzer.return_value = mock_analyzer_instance
    mock_analyzer_instance.calculate_metrics.return_value = {
        'total_return': 0.18,
        'annualized_return': 0.15,
        'sharpe_ratio': 1.3,
        'max_drawdown': -0.06,
        'total_trades': 8,
        'win_rate': 0.625,
        'final_value': 118000.5,
        'trades_csv_path': '/tmp/trades.csv'
    }
    mock_analyzer_instance.generate_report.return_value = "Mock Report"

    mock_trade_logger_instance = MagicMock()
    mock_trade_logger.return_value = mock_trade_logger_instance
    mock_trade_logger_instance.export_to_csv.return_value = '/tmp/trades.csv'

    runner = BacktestRunner(config)
    strategy = SMA_Crossover(
        short_period=15,
        long_period=45,
        position_percent=Decimal('0.75')
    )

    # Run backtest
    results = runner.run(strategy, output_dir=str(tmp_path))

    # Load config
    with open(results['config_yaml_path'], 'r') as f:
        saved_config = yaml.safe_load(f)

    # Verify all numeric values are proper types (not Decimal strings)
    assert isinstance(saved_config['backtest_config']['initial_capital'], float)
    assert saved_config['backtest_config']['initial_capital'] == 100000.5

    assert isinstance(saved_config['backtest_config']['commission_per_share'], float)
    assert saved_config['backtest_config']['commission_per_share'] == 0.015

    assert isinstance(saved_config['backtest_config']['slippage_percent'], float)
    assert saved_config['backtest_config']['slippage_percent'] == 0.0012

    assert isinstance(saved_config['strategy']['parameters']['position_percent'], float)
    assert saved_config['strategy']['parameters']['position_percent'] == 0.75
