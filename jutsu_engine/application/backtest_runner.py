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
from typing import Dict, Any, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.event_loop import EventLoop
from jutsu_engine.data.handlers.database import DatabaseDataHandler, MultiSymbolDataHandler
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
                - symbols: List[str] (preferred) or symbol: str (backward compat)
                - timeframe: str
                - start_date: datetime
                - end_date: datetime
                - initial_capital: Decimal
                Optional keys:
                - commission_per_share: Decimal (default: from config)
                - slippage_percent: Decimal (default: 0.001)
                - database_url: str (default: from config)

        Example (single symbol):
            config = {
                'symbol': 'AAPL',
                'timeframe': '1D',
                'start_date': datetime(2024, 1, 1),
                'end_date': datetime(2024, 12, 31),
                'initial_capital': Decimal('100000'),
            }
            runner = BacktestRunner(config)

        Example (multi-symbol):
            config = {
                'symbols': ['QQQ', 'TQQQ', 'SQQQ'],
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

        # Get symbols list (supports both old and new format)
        if 'symbols' in config:
            symbols = config['symbols']
        elif 'symbol' in config:
            symbols = [config['symbol']]
        else:
            raise ValueError("Must provide either 'symbols' or 'symbol' in config")

        logger.info(
            f"BacktestRunner initialized: "
            f"{', '.join(symbols)} {config['timeframe']} "
            f"from {config['start_date'].date()} to {config['end_date'].date()}"
        )

    def _validate_config(self):
        """Validate required configuration keys."""
        required_keys = [
            'timeframe',
            'start_date',
            'end_date',
            'initial_capital',
        ]

        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

        # Must have either 'symbol' or 'symbols'
        if 'symbol' not in self.config and 'symbols' not in self.config:
            raise ValueError("Must provide either 'symbol' or 'symbols' in config")

    def _generate_default_trade_path(self, strategy_name: str) -> str:
        """
        Generate default trade log path: trades/{strategy_name}_{timestamp}.csv

        Args:
            strategy_name: Name of strategy being backtested

        Returns:
            Default path string for trade log CSV

        Example:
            >>> runner._generate_default_trade_path("ADX_Trend")
            'trades/ADX_Trend_2025-11-06_112054.csv'
        """
        from pathlib import Path
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')

        # Ensure trades directory exists
        trades_dir = Path('trades')
        trades_dir.mkdir(parents=True, exist_ok=True)

        return f'trades/{strategy_name}_{timestamp}.csv'

    def run(
        self,
        strategy: Strategy,
        trades_output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run backtest with given strategy.

        Args:
            strategy: Strategy instance to backtest
            trades_output_path: Custom path for trade log CSV (default: None)
                If None, auto-generates path as trades/{strategy_name}_{timestamp}.csv

        Returns:
            Dictionary with comprehensive backtest results
            Always includes 'trades_csv_path' key with path to exported CSV

        Example:
            strategy = SMA_Crossover(short_period=20, long_period=50)

            # Default - CSV auto-generated in trades/ folder
            results = runner.run(strategy)

            # Custom path - user override
            results = runner.run(strategy, trades_output_path='custom/my_backtest.csv')

            print(f"Total Return: {results['total_return']:.2%}")
            print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
            print(f"Max Drawdown: {results['max_drawdown']:.2%}")
            print(f"Trade log: {results['trades_csv_path']}")
        """
        logger.info("=" * 60)
        logger.info(f"Starting backtest with strategy: {strategy.name}")
        logger.info("=" * 60)

        # Determine symbols (backward compatible)
        if 'symbols' in self.config:
            symbols = self.config['symbols']
        elif 'symbol' in self.config:
            symbols = [self.config['symbol']]
        else:
            raise ValueError("Must provide either 'symbols' or 'symbol' in config")

        # Create appropriate data handler (single vs multi-symbol)
        if len(symbols) == 1:
            # Single symbol - use existing DatabaseDataHandler
            data_handler = DatabaseDataHandler(
                session=self.session,
                symbol=symbols[0],
                timeframe=self.config['timeframe'],
                start_date=self.config['start_date'],
                end_date=self.config['end_date'],
            )
        else:
            # Multiple symbols - use new MultiSymbolDataHandler
            data_handler = MultiSymbolDataHandler(
                session=self.session,
                symbols=symbols,
                timeframe=self.config['timeframe'],
                start_date=self.config['start_date'],
                end_date=self.config['end_date'],
            )

        # ALWAYS create TradeLogger (default behavior)
        from jutsu_engine.performance.trade_logger import TradeLogger
        trade_logger = TradeLogger(initial_capital=self.config['initial_capital'])

        # Generate default path if not provided
        if trades_output_path is None:
            trades_output_path = self._generate_default_trade_path(strategy.name)

        logger.info(f"TradeLogger enabled, will export to: {trades_output_path}")

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
            trade_logger=trade_logger,
        )

        # Initialize strategy
        strategy.init()

        # Create and run event loop
        event_loop = EventLoop(
            data_handler=data_handler,
            strategy=strategy,
            portfolio=portfolio,
            trade_logger=trade_logger,
        )

        event_loop.run()

        # Analyze performance
        analyzer = PerformanceAnalyzer(
            fills=event_loop.all_fills,
            equity_curve=portfolio.get_equity_curve(),
            initial_capital=self.config['initial_capital'],
        )

        metrics = analyzer.calculate_metrics()

        # ALWAYS export trades to CSV (default behavior)
        try:
            csv_path = analyzer.export_trades_to_csv(
                trade_logger,
                strategy.name,
                trades_output_path
            )
            metrics['trades_csv_path'] = csv_path
            logger.info(f"Trade log exported to: {csv_path}")
        except ValueError as e:
            logger.warning(f"No trades to export: {e}")
            metrics['trades_csv_path'] = None
        except IOError as e:
            logger.error(f"Failed to export trades: {e}")
            metrics['trades_csv_path'] = None

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
        logger.info(f"Symbols: {', '.join(symbols)}")
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
