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
from sqlalchemy import create_engine, and_
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
        trades_output_path: Optional[str] = None,
        output_dir: str = "output"
    ) -> Dict[str, Any]:
        """
        Run backtest with given strategy.

        Args:
            strategy: Strategy instance to backtest
            trades_output_path: Custom path for trade log CSV (default: None)
                If None, uses output_dir with auto-generated timestamp filename
            output_dir: Output directory for CSV files (default: "output")

        Returns:
            Dictionary with comprehensive backtest results
            Always includes 'trades_csv_path' key with path to exported CSV

        Example:
            strategy = SMA_Crossover(short_period=20, long_period=50)

            # Default - CSVs auto-generated in output/ folder
            results = runner.run(strategy)
            # Creates: output/{strategy}_{timestamp}.csv (portfolio)
            #          output/{strategy}_{timestamp}_trades.csv (trades)

            # Custom output directory
            results = runner.run(strategy, output_dir='custom/path')

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

        # Extract signal_symbol from strategy for buy-and-hold comparison (if available)
        signal_symbol = getattr(strategy, 'signal_symbol', None)
        signal_prices = None

        if signal_symbol:
            logger.info(f"Buy-and-hold benchmark enabled: {signal_symbol}")

            # Collect signal prices directly from database
            try:
                from jutsu_engine.data.models import MarketData

                signal_bars = (
                    self.session.query(MarketData)
                    .filter(
                        and_(
                            MarketData.symbol == signal_symbol,
                            MarketData.timeframe == self.config['timeframe'],
                            MarketData.timestamp >= self.config['start_date'],
                            MarketData.timestamp <= self.config['end_date'],
                            MarketData.is_valid == True,  # noqa: E712
                        )
                    )
                    .order_by(MarketData.timestamp.asc())
                    .all()
                )

                signal_prices = {
                    bar.timestamp.strftime("%Y-%m-%d"): bar.close
                    for bar in signal_bars
                }

                logger.info(f"Collected {len(signal_prices)} price points for {signal_symbol}")

            except Exception as e:
                logger.warning(f"Failed to collect signal prices for {signal_symbol}: {e}")
                signal_prices = None
        else:
            logger.debug("No signal_symbol found in strategy, skipping buy-and-hold benchmark")

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

        # Calculate baseline (QQQ buy-and-hold comparison)
        baseline_result = None
        try:
            # Default baseline symbol is QQQ (NASDAQ-100 ETF)
            baseline_symbol = 'QQQ'

            # First check if QQQ is already loaded in event loop (multi-symbol strategy)
            if baseline_symbol in symbols:
                # Extract QQQ bars from event loop
                qqq_bars = [bar for bar in event_loop.all_bars if bar.symbol == baseline_symbol]
            else:
                # QQQ not in strategy symbols - query directly from database
                from jutsu_engine.data.models import MarketData

                qqq_db_bars = (
                    self.session.query(MarketData)
                    .filter(
                        and_(
                            MarketData.symbol == baseline_symbol,
                            MarketData.timeframe == self.config['timeframe'],
                            MarketData.timestamp >= self.config['start_date'],
                            MarketData.timestamp <= self.config['end_date'],
                            MarketData.is_valid == True,  # noqa: E712
                        )
                    )
                    .order_by(MarketData.timestamp.asc())
                    .all()
                )

                if qqq_db_bars:
                    # Convert to simple objects with just the data we need
                    qqq_bars = [
                        type('Bar', (), {
                            'symbol': bar.symbol,
                            'timestamp': bar.timestamp,
                            'close': bar.close
                        })()
                        for bar in qqq_db_bars
                    ]
                else:
                    qqq_bars = []

            # Calculate baseline if we have sufficient data
            if len(qqq_bars) >= 2:
                # Get start and end prices
                start_bar = qqq_bars[0]
                end_bar = qqq_bars[-1]

                # Calculate baseline metrics
                baseline_result = analyzer.calculate_baseline(
                    symbol=baseline_symbol,
                    start_price=start_bar.close,
                    end_price=end_bar.close,
                    start_date=start_bar.timestamp,
                    end_date=end_bar.timestamp
                )

                if baseline_result:
                    # Calculate alpha (strategy outperformance vs baseline)
                    strategy_return = metrics.get('total_return', 0)
                    baseline_return = baseline_result['baseline_total_return']

                    if baseline_return != 0:
                        # Alpha as ratio (e.g., 1.20 means 20% better than baseline)
                        alpha = strategy_return / baseline_return
                        baseline_result['alpha'] = alpha
                        logger.info(
                            f"Baseline calculated: {baseline_symbol} return = {baseline_return:.2%}"
                        )
                        logger.info(f"Strategy alpha vs baseline: {alpha:.2f}x")
                    else:
                        # Cannot calculate ratio when baseline return is zero
                        baseline_result['alpha'] = None
                        baseline_result['alpha_note'] = 'Cannot calculate ratio (baseline return = 0)'
                        logger.info(
                            f"Baseline calculated: {baseline_symbol} return = {baseline_return:.2%}"
                        )
                        logger.info("Alpha: N/A (baseline return = 0)")
            elif len(qqq_bars) == 0:
                logger.info(
                    f"{baseline_symbol} data not found in database for the backtest period"
                )
            else:
                logger.warning(
                    f"Insufficient {baseline_symbol} data for baseline "
                    f"({len(qqq_bars)} bars, need >= 2)"
                )

        except Exception as e:
            logger.error(f"Baseline calculation failed: {e}", exc_info=True)
            baseline_result = None

        # ALWAYS export trades and portfolio CSVs to output directory
        try:
            # Export trades CSV
            trades_csv_path = trade_logger.export_trades_csv(
                output_path=output_dir,
                strategy_name=strategy.name
            )
            metrics['trades_csv_path'] = trades_csv_path
            logger.info(f"Trade log exported to: {trades_csv_path}")
        except ValueError as e:
            logger.warning(f"No trades to export: {e}")
            metrics['trades_csv_path'] = None
        except IOError as e:
            logger.error(f"Failed to export trades: {e}")
            metrics['trades_csv_path'] = None
        
        # Prepare baseline info for CSV export
        baseline_csv_info = None
        if baseline_result:
            try:
                qqq_symbol = baseline_result['baseline_symbol']

                # Get QQQ price history using data_handler
                qqq_bars = data_handler.get_bars(
                    symbol=qqq_symbol,
                    start_date=self.config['start_date'],
                    end_date=self.config['end_date']
                )

                if qqq_bars:
                    # Build price history dict: {date: price}
                    price_history = {
                        bar.timestamp.date(): bar.close
                        for bar in qqq_bars
                    }

                    # Get start price
                    first_bar = qqq_bars[0]

                    baseline_csv_info = {
                        'symbol': qqq_symbol,
                        'start_price': first_bar.close,
                        'price_history': price_history
                    }
                    logger.debug(
                        f"Baseline CSV info prepared: {len(price_history)} price points for {qqq_symbol}"
                    )
                else:
                    logger.warning(f"No bars found for {qqq_symbol}, baseline columns will be empty")

            except Exception as e:
                logger.warning(f"Could not prepare baseline info for CSV: {e}")
                baseline_csv_info = None

        # Export portfolio daily snapshots CSV
        try:
            from jutsu_engine.performance.portfolio_exporter import PortfolioCSVExporter

            exporter = PortfolioCSVExporter(initial_capital=self.config['initial_capital'])
            portfolio_csv_path = exporter.export_daily_portfolio_csv(
                daily_snapshots=portfolio.get_daily_snapshots(),
                output_path=output_dir,
                strategy_name=strategy.name,
                signal_symbol=signal_symbol,
                signal_prices=signal_prices,
                baseline_info=baseline_csv_info,
            )
            metrics['portfolio_csv_path'] = portfolio_csv_path
            logger.info(f"Portfolio CSV exported to: {portfolio_csv_path}")

            if signal_symbol and signal_prices:
                logger.info(f"Buy-and-hold benchmark included for {signal_symbol}")

            if baseline_csv_info:
                logger.info(f"Baseline comparison columns added for {baseline_csv_info['symbol']}")
        except ValueError as e:
            logger.warning(f"No daily snapshots to export: {e}")
            metrics['portfolio_csv_path'] = None
        except IOError as e:
            logger.error(f"Failed to export portfolio CSV: {e}")
            metrics['portfolio_csv_path'] = None

        # Export summary metrics CSV
        try:
            from jutsu_engine.performance.summary_exporter import SummaryCSVExporter

            summary_exporter = SummaryCSVExporter()
            # Prepare metrics dict for summary export
            temp_metrics = {**metrics}
            temp_metrics['config'] = self.config
            summary_csv_path = summary_exporter.export_summary_csv(
                results=temp_metrics,
                baseline=baseline_result,
                output_dir=output_dir,
                strategy_name=strategy.name
            )
            metrics['summary_csv_path'] = summary_csv_path
            logger.info(f"Summary metrics CSV exported to: {summary_csv_path}")
        except Exception as e:
            logger.error(f"Failed to export summary CSV: {e}")
            metrics['summary_csv_path'] = None

        # Add event loop results
        loop_results = event_loop.get_results()
        results = {**metrics, **loop_results}

        # Add baseline comparison (if available)
        results['baseline'] = baseline_result

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
