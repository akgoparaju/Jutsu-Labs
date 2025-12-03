"""
Tests for BacktestRunner warmup coordination.

Tests verify that BacktestRunner properly coordinates warmup period:
- Queries strategy for warmup requirements
- Passes warmup_bars to DatabaseHandler
- Passes warmup_end_date to EventLoop
- Backwards compatible (no warmup)
"""
import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch, call
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.data.models import Base


class MockStrategy(Strategy):
    """Mock strategy for testing warmup coordination."""

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


class TestBacktestRunnerWarmup:
    """Test BacktestRunner warmup coordination."""

    @pytest.fixture
    def in_memory_db(self):
        """Create in-memory database for testing."""
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        return Session()

    @pytest.fixture
    def config(self):
        """Standard backtest configuration."""
        return {
            'symbols': ['AAPL'],
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1),
            'end_date': datetime(2024, 12, 31),
            'initial_capital': Decimal('100000'),
        }

    @patch('jutsu_engine.application.backtest_runner.DatabaseDataHandler')
    @patch('jutsu_engine.application.backtest_runner.EventLoop')
    @patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
    @patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
    @patch('jutsu_engine.performance.trade_logger.TradeLogger')
    def test_warmup_coordination_with_warmup_required(
        self,
        mock_trade_logger,
        mock_analyzer,
        mock_portfolio,
        mock_event_loop,
        mock_data_handler,
        config,
        in_memory_db
    ):
        """Test warmup coordination when strategy requires warmup."""
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
            'annualized_return': 0.15,
            'sharpe_ratio': 1.2,
            'max_drawdown': -0.10,
            'total_trades': 10,
            'win_rate': 0.60,
            'final_value': Decimal('115000')
        }

        # Create strategy that requires warmup
        strategy = MockStrategy(warmup_bars=147)

        # Create runner with mocked database
        with patch('jutsu_engine.application.backtest_runner.create_engine'):
            with patch('jutsu_engine.application.backtest_runner.sessionmaker') as mock_sessionmaker:
                mock_sessionmaker.return_value.return_value = in_memory_db
                runner = BacktestRunner(config)

                # Run backtest
                results = runner.run(strategy, output_dir='output')

        # Verify strategy was initialized (called once)
        assert strategy._warmup_bars == 147

        # Verify warmup_bars passed to DatabaseDataHandler
        mock_data_handler.assert_called_once()
        call_kwargs = mock_data_handler.call_args[1]
        assert call_kwargs['warmup_bars'] == 147
        assert call_kwargs['start_date'] == datetime(2024, 1, 1)
        assert call_kwargs['end_date'] == datetime(2024, 12, 31)

        # Verify warmup_end_date passed to EventLoop
        mock_event_loop.assert_called_once()
        event_loop_kwargs = mock_event_loop.call_args[1]
        assert event_loop_kwargs['warmup_end_date'] == datetime(2024, 1, 1)
        assert event_loop_kwargs['data_handler'] == mock_data_handler_instance
        assert event_loop_kwargs['strategy'] == strategy

        # Verify results returned
        assert results['total_return'] == 0.15
        assert results['total_trades'] == 10

    @patch('jutsu_engine.application.backtest_runner.DatabaseDataHandler')
    @patch('jutsu_engine.application.backtest_runner.EventLoop')
    @patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
    @patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
    @patch('jutsu_engine.performance.trade_logger.TradeLogger')
    def test_no_warmup_backwards_compatible(
        self,
        mock_trade_logger,
        mock_analyzer,
        mock_portfolio,
        mock_event_loop,
        mock_data_handler,
        config,
        in_memory_db
    ):
        """Test backwards compatibility when strategy doesn't require warmup."""
        # Setup mocks
        mock_data_handler_instance = MagicMock()
        mock_data_handler.return_value = mock_data_handler_instance

        mock_event_loop_instance = MagicMock()
        mock_event_loop.return_value = mock_event_loop_instance
        mock_event_loop_instance.all_fills = []
        mock_event_loop_instance.all_bars = []
        mock_event_loop_instance.get_results.return_value = {
            'total_bars': 252,
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
            'total_return': 0.10,
            'annualized_return': 0.10,
            'sharpe_ratio': 1.0,
            'max_drawdown': -0.08,
            'total_trades': 5,
            'win_rate': 0.50,
            'final_value': Decimal('110000')
        }

        # Create strategy that doesn't require warmup
        strategy = MockStrategy(warmup_bars=0)

        # Create runner with mocked database
        with patch('jutsu_engine.application.backtest_runner.create_engine'):
            with patch('jutsu_engine.application.backtest_runner.sessionmaker') as mock_sessionmaker:
                mock_sessionmaker.return_value.return_value = in_memory_db
                runner = BacktestRunner(config)

                # Run backtest
                results = runner.run(strategy, output_dir='output')

        # Verify warmup_bars=0 passed to DatabaseDataHandler
        mock_data_handler.assert_called_once()
        call_kwargs = mock_data_handler.call_args[1]
        assert call_kwargs['warmup_bars'] == 0

        # Verify warmup_end_date=None passed to EventLoop (no warmup)
        mock_event_loop.assert_called_once()
        event_loop_kwargs = mock_event_loop.call_args[1]
        assert event_loop_kwargs['warmup_end_date'] is None

        # Verify results returned
        assert results['total_return'] == 0.10
        assert results['total_trades'] == 5

    @patch('jutsu_engine.application.backtest_runner.MultiSymbolDataHandler')
    @patch('jutsu_engine.application.backtest_runner.EventLoop')
    @patch('jutsu_engine.application.backtest_runner.PortfolioSimulator')
    @patch('jutsu_engine.application.backtest_runner.PerformanceAnalyzer')
    @patch('jutsu_engine.performance.trade_logger.TradeLogger')
    def test_warmup_coordination_multi_symbol(
        self,
        mock_trade_logger,
        mock_analyzer,
        mock_portfolio,
        mock_event_loop,
        mock_multi_handler,
        in_memory_db
    ):
        """Test warmup coordination with multi-symbol strategies."""
        # Multi-symbol config
        config = {
            'symbols': ['QQQ', 'TQQQ', 'SQQQ'],
            'timeframe': '1D',
            'start_date': datetime(2024, 1, 1),
            'end_date': datetime(2024, 12, 31),
            'initial_capital': Decimal('100000'),
        }

        # Setup mocks
        mock_multi_handler_instance = MagicMock()
        mock_multi_handler.return_value = mock_multi_handler_instance

        mock_event_loop_instance = MagicMock()
        mock_event_loop.return_value = mock_event_loop_instance
        mock_event_loop_instance.all_fills = []
        mock_event_loop_instance.all_bars = []
        mock_event_loop_instance.get_results.return_value = {
            'total_bars': 756,  # 252 bars * 3 symbols
            'signals_generated': 20,
            'orders_executed': 20
        }

        mock_portfolio_instance = MagicMock()
        mock_portfolio.return_value = mock_portfolio_instance
        mock_portfolio_instance.get_equity_curve.return_value = []
        mock_portfolio_instance.get_daily_snapshots.return_value = []

        mock_analyzer_instance = MagicMock()
        mock_analyzer.return_value = mock_analyzer_instance
        mock_analyzer_instance.calculate_metrics.return_value = {
            'total_return': 0.25,
            'annualized_return': 0.25,
            'sharpe_ratio': 1.5,
            'max_drawdown': -0.12,
            'total_trades': 20,
            'win_rate': 0.65,
            'final_value': Decimal('125000')
        }

        # Create strategy that requires warmup
        strategy = MockStrategy(warmup_bars=147)

        # Create runner with mocked database
        with patch('jutsu_engine.application.backtest_runner.create_engine'):
            with patch('jutsu_engine.application.backtest_runner.sessionmaker') as mock_sessionmaker:
                mock_sessionmaker.return_value.return_value = in_memory_db
                runner = BacktestRunner(config)

                # Run backtest
                results = runner.run(strategy, output_dir='output')

        # Verify warmup_bars passed to MultiSymbolDataHandler
        mock_multi_handler.assert_called_once()
        call_kwargs = mock_multi_handler.call_args[1]
        assert call_kwargs['warmup_bars'] == 147
        assert call_kwargs['symbols'] == ['QQQ', 'TQQQ', 'SQQQ']

        # Verify warmup_end_date passed to EventLoop
        mock_event_loop.assert_called_once()
        event_loop_kwargs = mock_event_loop.call_args[1]
        assert event_loop_kwargs['warmup_end_date'] == datetime(2024, 1, 1)

        # Verify results returned
        assert results['total_return'] == 0.25
        assert results['total_trades'] == 20
