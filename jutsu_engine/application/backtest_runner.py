"""
High-level API for running backtests.

Orchestrates all components to run a complete backtest:
- Creates database connection
- Initializes data handler
- Creates portfolio simulator
- Runs event loop
- Analyzes performance
- Returns results

Example:
    from jutsu_engine.application.backtest_runner import BacktestRunner
    from jutsu_engine.strategies.sma_crossover import SMA_Crossover

    config = {
        'symbol': 'AAPL',
        'timeframe': '1D',
        'start_date': datetime(2024, 1, 1),
        'end_date': datetime(2024, 12, 31),
        'initial_capital': Decimal('100000'),
        'commission_per_share': Decimal('0.01'),
    }

    strategy = SMA_Crossover(short_period=20, long_period=50)

    runner = BacktestRunner(config)
    results = runner.run(strategy)

    print(f"Total Return: {results['total_return']:.2%}")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
"""
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.event_loop import EventLoop
from jutsu_engine.data.handlers.database import DatabaseDataHandler
from jutsu_engine.portfolio.simulator import PortfolioSimulator
from jutsu_engine.performance.analyzer import PerformanceAnalyzer
from jutsu_engine.utils.config import get_config
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('BACKTEST', log_to_console=True)


class BacktestRunner:
    """
    High-level backtest orchestrator.

    Coordinates all components to run complete backtests.
    Provides simple API for running strategies with minimal configuration.

    Attributes:
        config: Backtest configuration dictionary
        session: Database session
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize backtest runner.

        Args:
            config: Dictionary with backtest configuration
                Required keys:
                - symbol: str
                - timeframe: str
                - start_date: datetime
                - end_date: datetime
                - initial_capital: Decimal
                Optional keys:
                - commission_per_share: Decimal (default: from config)
                - slippage_percent: Decimal (default: 0.001)
                - database_url: str (default: from config)

        Example:
            config = {
                'symbol': 'AAPL',
                'timeframe': '1D',
                'start_date': datetime(2024, 1, 1),
                'end_date': datetime(2024, 12, 31),
                'initial_capital': Decimal('100000'),
            }
            runner = BacktestRunner(config)
        """
        self.config = config
        self._validate_config()

        # Get global config for defaults
        global_config = get_config()

        # Initialize database connection
        db_url = config.get('database_url', global_config.database_url)
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        self.session = Session()

        logger.info(
            f"BacktestRunner initialized: "
            f"{config['symbol']} {config['timeframe']} "
            f"from {config['start_date'].date()} to {config['end_date'].date()}"
        )

    def _validate_config(self):
        """Validate required configuration keys."""
        required_keys = [
            'symbol',
            'timeframe',
            'start_date',
            'end_date',
            'initial_capital',
        ]

        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

    def run(self, strategy: Strategy) -> Dict[str, Any]:
        """
        Run backtest with given strategy.

        Args:
            strategy: Strategy instance to backtest

        Returns:
            Dictionary with comprehensive backtest results

        Example:
            strategy = SMA_Crossover(short_period=20, long_period=50)
            results = runner.run(strategy)

            print(f"Total Return: {results['total_return']:.2%}")
            print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
            print(f"Max Drawdown: {results['max_drawdown']:.2%}")
        """
        logger.info("=" * 60)
        logger.info(f"Starting backtest with strategy: {strategy.name}")
        logger.info("=" * 60)

        # Create data handler
        data_handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.config['symbol'],
            timeframe=self.config['timeframe'],
            start_date=self.config['start_date'],
            end_date=self.config['end_date'],
        )

        # Create portfolio
        portfolio = PortfolioSimulator(
            initial_capital=self.config['initial_capital'],
            commission_per_share=self.config.get(
                'commission_per_share',
                Decimal('0.01')
            ),
            slippage_percent=self.config.get(
                'slippage_percent',
                Decimal('0.001')
            ),
        )

        # Initialize strategy
        strategy.init()

        # Create and run event loop
        event_loop = EventLoop(
            data_handler=data_handler,
            strategy=strategy,
            portfolio=portfolio,
        )

        event_loop.run()

        # Analyze performance
        analyzer = PerformanceAnalyzer(
            fills=event_loop.all_fills,
            equity_curve=portfolio.get_equity_curve(),
            initial_capital=self.config['initial_capital'],
        )

        metrics = analyzer.calculate_metrics()

        # Add event loop results
        loop_results = event_loop.get_results()
        results = {**metrics, **loop_results}

        # Add configuration
        results['config'] = self.config
        results['strategy_name'] = strategy.name

        # Log summary
        logger.info("=" * 60)
        logger.info("BACKTEST COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Strategy: {strategy.name}")
        logger.info(f"Symbol: {self.config['symbol']}")
        logger.info(f"Period: {self.config['start_date'].date()} to {self.config['end_date'].date()}")
        logger.info(f"Initial Capital: ${self.config['initial_capital']:,.2f}")
        logger.info(f"Final Value: ${results['final_value']:,.2f}")
        logger.info(f"Total Return: {results['total_return']:.2%}")
        logger.info(f"Annualized Return: {results['annualized_return']:.2%}")
        logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        logger.info(f"Max Drawdown: {results['max_drawdown']:.2%}")
        logger.info(f"Total Trades: {results['total_trades']}")
        logger.info(f"Win Rate: {results['win_rate']:.2%}")
        logger.info("=" * 60)

        # Generate and log detailed report
        report = analyzer.generate_report()
        logger.info("\n" + report)

        return results

    def __del__(self):
        """Cleanup database connection."""
        if hasattr(self, 'session'):
            self.session.close()
