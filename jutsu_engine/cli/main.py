"""
Command-line interface for Jutsu Labs backtesting engine.

Provides commands for running backtests, syncing data, and managing the system.

Usage:
    # Run a backtest
    jutsu backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31

    # Sync data from Schwab
    jutsu sync --symbol AAPL --timeframe 1D

    # View backtest results
    jutsu results --backtest-id 123

    # Initialize database
    jutsu init
"""
import click
import importlib
import inspect
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.utils.config import get_config
from jutsu_engine.utils.logging_config import setup_logger
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.application.data_sync import DataSync
from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher
from jutsu_engine.data.models import Base
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

logger = setup_logger('CLI', log_to_console=True)


@click.group()
@click.version_option(version='0.1.0', prog_name='Jutsu')
def cli():
    """
    Jutsu - Professional backtesting engine for algorithmic trading.

    A modular, event-driven backtesting framework with database-first data management.
    """
    pass


@cli.command()
@click.option(
    '--db-url',
    default=None,
    help='Database URL (default: from config)',
)
def init(db_url: Optional[str]):
    """
    Initialize database schema.

    Creates all required tables for market data, metadata, and audit logs.

    Example:
        jutsu init
        jutsu init --db-url sqlite:///custom.db
    """
    config = get_config()
    database_url = db_url or config.database_url

    click.echo(f"Initializing database: {database_url}")

    try:
        engine = create_engine(database_url)
        Base.metadata.create_all(engine)
        click.echo(click.style("✓ Database initialized successfully", fg='green'))

    except Exception as e:
        click.echo(click.style(f"✗ Database initialization failed: {e}", fg='red'))
        raise click.Abort()


@cli.command()
@click.option('--symbol', required=True, help='Stock ticker symbol (e.g., AAPL)')
@click.option(
    '--timeframe',
    default='1D',
    help='Bar timeframe (1m, 5m, 1H, 1D, etc.)',
)
@click.option(
    '--start',
    required=True,
    help='Start date (YYYY-MM-DD)',
)
@click.option(
    '--end',
    default=None,
    help='End date (YYYY-MM-DD, default: today)',
)
@click.option(
    '--force',
    is_flag=True,
    help='Force refresh, ignore existing data',
)
def sync(
    symbol: str,
    timeframe: str,
    start: str,
    end: Optional[str],
    force: bool,
):
    """
    Synchronize market data from Schwab API.

    Fetches historical price data and stores it in the database.
    Supports incremental updates to avoid re-fetching existing data.

    Example:
        jutsu sync --symbol AAPL --timeframe 1D --start 2024-01-01
        jutsu sync --symbol MSFT --timeframe 1H --start 2024-01-01 --end 2024-12-31
    """
    config = get_config()

    # Parse dates
    start_date = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    end_date = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)

    click.echo(f"Syncing {symbol} {timeframe} from {start_date.date()} to {end_date.date()}")

    try:
        # Create database session
        engine = create_engine(config.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Create fetcher and sync manager
        fetcher = SchwabDataFetcher()
        sync_manager = DataSync(session)

        # Sync data
        with click.progressbar(
            length=1,
            label='Fetching data',
            show_eta=False,
        ) as bar:
            result = sync_manager.sync_symbol(
                fetcher=fetcher,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                force_refresh=force,
            )
            bar.update(1)

        # Display results
        click.echo(
            click.style(
                f"✓ Sync complete: {result['bars_stored']} bars stored, "
                f"{result['bars_updated']} updated",
                fg='green',
            )
        )

        session.close()

    except Exception as e:
        click.echo(click.style(f"✗ Sync failed: {e}", fg='red'))
        raise click.Abort()


def parse_symbols_callback(ctx, param, value):
    """
    Parse symbols from space-separated, comma-separated, or multiple values.
    
    Supports all common syntaxes:
    - Space-separated: --symbols "QQQ TQQQ SQQQ"
    - Comma-separated: --symbols QQQ,TQQQ,SQQQ
    - Multiple flags: --symbols QQQ --symbols TQQQ --symbols SQQQ
    - Mixed: --symbols "QQQ TQQQ" --symbols SQQQ
    
    Returns:
        tuple of symbols or None
    """
    if not value:
        return None
    
    # Flatten and split by commas and spaces
    all_symbols = []
    for item in value:
        # First split by comma, then by space
        for part in item.split(','):
            symbols = [s.strip().upper() for s in part.split() if s.strip()]
            all_symbols.extend(symbols)
    
    return tuple(all_symbols) if all_symbols else None


@cli.command()
@click.option('--symbol', default=None, help='Stock ticker symbol (single symbol mode)')
@click.option(
    '--symbols',
    multiple=True,
    callback=parse_symbols_callback,
    help='Stock ticker symbols for multi-symbol strategies (space/comma-separated or repeated: --symbols "QQQ TQQQ SQQQ" OR --symbols QQQ,TQQQ,SQQQ)'
)
@click.option(
    '--timeframe',
    default='1D',
    help='Bar timeframe',
)
@click.option(
    '--start',
    required=True,
    help='Backtest start date (YYYY-MM-DD)',
)
@click.option(
    '--end',
    required=True,
    help='Backtest end date (YYYY-MM-DD)',
)
@click.option(
    '--capital',
    default=100000,
    type=float,
    help='Initial capital',
)
@click.option(
    '--strategy',
    default='sma_crossover',
    help='Strategy to run (sma_crossover)',
)
@click.option(
    '--short-period',
    default=20,
    type=int,
    help='Short SMA period',
)
@click.option(
    '--long-period',
    default=50,
    type=int,
    help='Long SMA period',
)
@click.option(
    '--position-size',
    default=100,
    type=int,
    help='Position size (shares per trade)',
)
@click.option(
    '--commission',
    default=0.01,
    type=float,
    help='Commission per share',
)
@click.option(
    '--output',
    default=None,
    help='Output file for results (JSON)',
)
@click.option(
    '--export-trades',
    default=None,
    help='Custom path for trade log CSV (default: auto-generated as trades/{strategy}_{timestamp}.csv)',
)
def backtest(
    symbol: Optional[str],
    symbols: tuple,
    timeframe: str,
    start: str,
    end: str,
    capital: float,
    strategy: str,
    short_period: int,
    long_period: int,
    position_size: int,
    commission: float,
    output: Optional[str],
    export_trades: Optional[str],
):
    """
    Run a backtest with specified parameters.

    Tests a trading strategy against historical data and reports performance metrics.

    Single-symbol example:
        jutsu backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31
        jutsu backtest --symbol MSFT --start 2024-01-01 --end 2024-12-31 \\
            --capital 50000 --short-period 10 --long-period 30

    Multi-symbol examples:
        # Comma-separated (recommended):
        jutsu backtest --strategy ADX_Trend --symbols QQQ,TQQQ,SQQQ \
            --start 2023-01-01 --end 2024-12-31 --capital 10000
        
        # Space-separated (use quotes):
        jutsu backtest --strategy ADX_Trend --symbols "QQQ TQQQ SQQQ" \
            --start 2023-01-01 --end 2024-12-31 --capital 10000
        
        # Repeated flag (also supported):
        jutsu backtest --strategy ADX_Trend --symbols QQQ --symbols TQQQ --symbols SQQQ \
            --start 2023-01-01 --end 2024-12-31 --capital 10000
    """
    # Determine which symbols to use
    if symbols:
        # Multi-symbol mode (--symbols takes precedence)
        symbol_list = list(symbols)
        is_multi_symbol = True
    elif symbol:
        # Single-symbol mode (backward compatible)
        symbol_list = [symbol]
        is_multi_symbol = False
    else:
        # Error: must provide at least one symbol
        click.echo(click.style("✗ Error: Must provide either --symbol or --symbols", fg='red'))
        raise click.Abort()

    # Parse dates
    start_date = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    end_date = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc)

    # Display header
    click.echo("=" * 60)
    if is_multi_symbol:
        click.echo(f"BACKTEST: {', '.join(symbol_list)} {timeframe}")
    else:
        click.echo(f"BACKTEST: {symbol_list[0]} {timeframe}")
    click.echo(f"Period: {start_date.date()} to {end_date.date()}")
    click.echo(f"Initial Capital: ${capital:,.2f}")
    click.echo("=" * 60)

    try:
        # Create backtest configuration
        config = {
            'symbols': symbol_list,  # Now always a list
            'timeframe': timeframe,
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': Decimal(str(capital)),
            'commission_per_share': Decimal(str(commission)),
        }

        # Create strategy - dynamically load from strategies module
        try:
            # Try to import strategy module
            module_name = f"jutsu_engine.strategies.{strategy}"
            strategy_module = importlib.import_module(module_name)
            
            # Get strategy class (assume class name matches file name)
            strategy_class = getattr(strategy_module, strategy)
            
            # Inspect constructor to build parameter dict dynamically
            sig = inspect.signature(strategy_class.__init__)
            params = sig.parameters
            
            # Build kwargs based on what the strategy constructor accepts
            strategy_kwargs = {}
            
            # Add parameters only if they exist in the constructor
            if 'short_period' in params:
                strategy_kwargs['short_period'] = short_period
            if 'long_period' in params:
                strategy_kwargs['long_period'] = long_period
            if 'position_size' in params:
                strategy_kwargs['position_size'] = position_size
            # NOTE: Let strategy use its own default position_size_percent
            # CLI --position-size is for old share-based strategies
            # if 'position_size_percent' in params:
            #     strategy_kwargs['position_size_percent'] = Decimal('1.0')
            
            # Instantiate strategy with only accepted parameters
            strategy_instance = strategy_class(**strategy_kwargs)
            
            logger.info(f"Loaded strategy: {strategy} with params: {strategy_kwargs}")
            
        except ImportError as e:
            click.echo(click.style(f"✗ Strategy module not found: {strategy}", fg='red'))
            click.echo(click.style(f"  Looked for: jutsu_engine/strategies/{strategy}.py", fg='yellow'))
            logger.error(f"Strategy import failed: {e}")
            raise click.Abort()
        except AttributeError as e:
            click.echo(click.style(f"✗ Strategy class not found in module: {strategy}", fg='red'))
            click.echo(click.style(f"  Module exists but class '{strategy}' not defined", fg='yellow'))
            logger.error(f"Strategy class not found: {e}")
            raise click.Abort()
        except Exception as e:
            click.echo(click.style(f"✗ Error loading strategy: {strategy}", fg='red'))
            click.echo(click.style(f"  {type(e).__name__}: {e}", fg='yellow'))
            logger.error(f"Strategy initialization failed: {e}", exc_info=True)
            raise click.Abort()

        # Run backtest
        runner = BacktestRunner(config)

        with click.progressbar(
            length=1,
            label='Running backtest',
            show_eta=False,
        ) as bar:
            results = runner.run(
                strategy_instance,
                trades_output_path=export_trades
            )
            bar.update(1)

        # Display results
        click.echo("\n" + "=" * 60)
        click.echo("RESULTS")
        click.echo("=" * 60)
        click.echo(f"Final Value:        ${results['final_value']:,.2f}")
        click.echo(f"Total Return:       {results['total_return']:.2%}")
        click.echo(f"Annualized Return:  {results['annualized_return']:.2%}")
        click.echo(f"Sharpe Ratio:       {results['sharpe_ratio']:.2f}")
        click.echo(f"Max Drawdown:       {results['max_drawdown']:.2%}")
        click.echo(f"Win Rate:           {results['win_rate']:.2%}")
        click.echo(f"Total Trades:       {results['total_trades']}")
        click.echo("=" * 60)

        # Always display trades CSV path (default behavior)
        if 'trades_csv_path' in results and results['trades_csv_path']:
            click.echo(f"\n✓ Trade log exported to: {results['trades_csv_path']}")
        elif 'trades_csv_path' in results and results['trades_csv_path'] is None:
            click.echo(f"\n⚠ No trades to export")

        # Save to file if requested
        if output:
            import json

            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert Decimal to float for JSON serialization
            json_results = {
                k: (float(v) if isinstance(v, Decimal) else v)
                for k, v in results.items()
                if k != 'config'  # Skip config dict
            }

            with open(output_path, 'w') as f:
                json.dump(json_results, f, indent=2, default=str)

            click.echo(f"\n✓ Results saved to {output}")

    except Exception as e:
        click.echo(click.style(f"\n✗ Backtest failed: {e}", fg='red'))
        raise click.Abort()


@cli.command()
@click.option('--symbol', required=True, help='Stock ticker symbol')
@click.option(
    '--timeframe',
    default='1D',
    help='Bar timeframe',
)
def status(symbol: str, timeframe: str):
    """
    Check data synchronization status.

    Shows information about available data for a symbol and timeframe.

    Example:
        jutsu status --symbol AAPL --timeframe 1D
    """
    config = get_config()

    try:
        # Create database session
        engine = create_engine(config.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Check status
        sync_manager = DataSync(session)
        status_info = sync_manager.get_sync_status(symbol, timeframe)

        click.echo("=" * 60)
        click.echo(f"DATA STATUS: {symbol} {timeframe}")
        click.echo("=" * 60)

        if status_info['has_data']:
            click.echo(f"Total Bars:         {status_info['total_bars']:,}")
            click.echo(f"First Bar:          {status_info['first_bar_timestamp']}")
            click.echo(f"Last Bar:           {status_info['last_bar_timestamp']}")
            click.echo(f"Last Update:        {status_info['last_update']}")
            click.echo(click.style("✓ Data available", fg='green'))
        else:
            click.echo(click.style("✗ No data found", fg='yellow'))
            click.echo("\nRun: jutsu sync --symbol {symbol} --timeframe {timeframe} --start YYYY-MM-DD")

        click.echo("=" * 60)

        session.close()

    except Exception as e:
        click.echo(click.style(f"✗ Status check failed: {e}", fg='red'))
        raise click.Abort()


@cli.command()
@click.option('--symbol', required=True, help='Stock ticker symbol')
@click.option(
    '--timeframe',
    default='1D',
    help='Bar timeframe',
)
@click.option(
    '--start',
    default=None,
    help='Start date for validation (YYYY-MM-DD)',
)
@click.option(
    '--end',
    default=None,
    help='End date for validation (YYYY-MM-DD)',
)
def validate(
    symbol: str,
    timeframe: str,
    start: Optional[str],
    end: Optional[str],
):
    """
    Validate data quality.

    Checks for missing bars, invalid OHLC relationships, and other data issues.

    Example:
        jutsu validate --symbol AAPL --timeframe 1D
        jutsu validate --symbol AAPL --timeframe 1D --start 2024-01-01 --end 2024-12-31
    """
    config = get_config()

    # Parse dates if provided
    start_date = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc) if start else None
    end_date = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc) if end else None

    try:
        # Create database session
        engine = create_engine(config.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Validate data
        sync_manager = DataSync(session)

        with click.progressbar(
            length=1,
            label='Validating data',
            show_eta=False,
        ) as bar:
            validation = sync_manager.validate_data(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
            )
            bar.update(1)

        # Display results
        click.echo("\n" + "=" * 60)
        click.echo("VALIDATION RESULTS")
        click.echo("=" * 60)
        click.echo(f"Total Bars:         {validation['total_bars']:,}")
        click.echo(f"Valid Bars:         {validation['valid_bars']:,}")
        click.echo(f"Invalid Bars:       {validation['invalid_bars']:,}")

        if validation['invalid_bars'] > 0:
            click.echo(click.style("\n⚠ Issues found:", fg='yellow'))
            for issue in validation['issues'][:10]:  # Show first 10
                click.echo(f"  - {issue}")

            if len(validation['issues']) > 10:
                click.echo(f"  ... and {len(validation['issues']) - 10} more")

            click.echo(click.style("\n✗ Data validation failed", fg='red'))
        else:
            click.echo(click.style("\n✓ All data valid", fg='green'))

        click.echo("=" * 60)

        session.close()

    except Exception as e:
        click.echo(click.style(f"\n✗ Validation failed: {e}", fg='red'))
        raise click.Abort()


if __name__ == '__main__':
    cli()
