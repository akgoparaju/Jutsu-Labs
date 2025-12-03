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
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.utils.config import get_config
from jutsu_engine.utils.logging_config import setup_logger
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.application.data_sync import DataSync
from jutsu_engine.application.grid_search_runner import GridSearchRunner
from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher
from jutsu_engine.data.models import Base
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

logger = setup_logger('CLI', log_to_console=True)

# Load environment variables from .env file
load_dotenv()

# Load generic backtest parameters from .env
env_initial_capital = float(os.getenv('INITIAL_CAPITAL', '100000'))
env_commission = float(os.getenv('DEFAULT_COMMISSION', '0.01'))
env_slippage = float(os.getenv('DEFAULT_SLIPPAGE', '0.0'))

# Load MACD_Trend_v4 parameters from .env
macd_v4_signal = os.getenv('STRATEGY_MACD_V4_SIGNAL_SYMBOL', 'QQQ')
macd_v4_bull = os.getenv('STRATEGY_MACD_V4_BULL_SYMBOL', 'TQQQ')
macd_v4_defense = os.getenv('STRATEGY_MACD_V4_DEFENSE_SYMBOL', 'QQQ')
macd_v4_fast = int(os.getenv('STRATEGY_MACD_V4_FAST_PERIOD', '12'))
macd_v4_slow = int(os.getenv('STRATEGY_MACD_V4_SLOW_PERIOD', '26'))
macd_v4_signal_period = int(os.getenv('STRATEGY_MACD_V4_SIGNAL_PERIOD', '9'))
macd_v4_ema = int(os.getenv('STRATEGY_MACD_V4_EMA_PERIOD', '100'))
macd_v4_atr = int(os.getenv('STRATEGY_MACD_V4_ATR_PERIOD', '14'))
macd_v4_atr_mult = float(os.getenv('STRATEGY_MACD_V4_ATR_STOP_MULTIPLIER', '3.0'))
macd_v4_risk_bull = float(os.getenv('STRATEGY_MACD_V4_RISK_BULL', '0.025'))
macd_v4_alloc_defense = float(os.getenv('STRATEGY_MACD_V4_ALLOCATION_DEFENSE', '0.60'))

# Load MACD_Trend_v5 parameters from .env
macd_v5_signal = os.getenv('STRATEGY_MACD_V5_SIGNAL_SYMBOL', 'QQQ')
macd_v5_bull = os.getenv('STRATEGY_MACD_V5_BULL_SYMBOL', 'TQQQ')
macd_v5_defense = os.getenv('STRATEGY_MACD_V5_DEFENSE_SYMBOL', 'QQQ')
# Normalize VIX symbol (add $ prefix if not present, as data is stored with $ prefix)
vix_from_env = os.getenv('STRATEGY_MACD_V5_VIX_SYMBOL', 'VIX')
macd_v5_vix_symbol = f'${vix_from_env}' if not vix_from_env.startswith('$') else vix_from_env
macd_v5_vix_ema = int(os.getenv('STRATEGY_MACD_V5_VIX_EMA_PERIOD', '50'))
macd_v5_ema_calm = int(os.getenv('STRATEGY_MACD_V5_EMA_PERIOD_CALM', '200'))
macd_v5_atr_calm = float(os.getenv('STRATEGY_MACD_V5_ATR_STOP_CALM', '3.0'))
macd_v5_ema_choppy = int(os.getenv('STRATEGY_MACD_V5_EMA_PERIOD_CHOPPY', '75'))
macd_v5_atr_choppy = float(os.getenv('STRATEGY_MACD_V5_ATR_STOP_CHOPPY', '2.0'))
macd_v5_fast = int(os.getenv('STRATEGY_MACD_V5_FAST_PERIOD', '12'))
macd_v5_slow = int(os.getenv('STRATEGY_MACD_V5_SLOW_PERIOD', '26'))
macd_v5_signal_period = int(os.getenv('STRATEGY_MACD_V5_SIGNAL_PERIOD', '9'))
macd_v5_atr = int(os.getenv('STRATEGY_MACD_V5_ATR_PERIOD', '14'))
macd_v5_risk_bull = float(os.getenv('STRATEGY_MACD_V5_RISK_BULL', '0.025'))
macd_v5_alloc_defense = float(os.getenv('STRATEGY_MACD_V5_ALLOCATION_DEFENSE', '0.60'))


# Known index symbols that require $ prefix in database
INDEX_SYMBOLS = {'VIX', 'DJI', 'SPX', 'NDX', 'RUT', 'VXN'}


def normalize_index_symbols(symbols: tuple) -> tuple:
    """
    Normalize index symbols by adding $ prefix if missing.

    Allows users to type 'VIX' instead of escaping '$VIX' in shell.

    Args:
        symbols: Tuple of symbol strings

    Returns:
        Tuple with normalized symbols (index symbols get $ prefix)

    Examples:
        ('QQQ', 'VIX', 'TQQQ') → ('QQQ', '$VIX', 'TQQQ')
        ('QQQ', '$VIX', 'TQQQ') → ('QQQ', '$VIX', 'TQQQ')  # Already prefixed
        ('AAPL', 'MSFT') → ('AAPL', 'MSFT')  # No change
    """
    if not symbols:
        return symbols

    normalized = []
    for symbol in symbols:
        # Check if it's a known index symbol WITHOUT $ prefix
        if symbol.upper() in INDEX_SYMBOLS and not symbol.startswith('$'):
            normalized_symbol = f'${symbol.upper()}'
            logger.info(f"Normalized index symbol: {symbol} → {normalized_symbol}")
            normalized.append(normalized_symbol)
        else:
            # Keep as is (regular symbols or already prefixed)
            normalized.append(symbol.upper())

    return tuple(normalized)


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


@cli.group(invoke_without_command=True)
@click.pass_context
@click.option('--symbol', default=None, help='Stock ticker symbol (e.g., AAPL)')
@click.option(
    '--timeframe',
    default='1D',
    help='Bar timeframe (1m, 5m, 1H, 1D, etc.)',
)
@click.option(
    '--start',
    default=None,
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
@click.option(
    '--all',
    'sync_all',
    is_flag=True,
    help='Sync all symbols to latest date (today)',
)
@click.option(
    '--list',
    'list_symbols',
    is_flag=True,
    help='List all symbols with date ranges',
)
@click.option(
    '--output',
    default=None,
    help='Output file for CSV export (used with --list)',
)
def sync(
    ctx: click.Context,
    symbol: Optional[str],
    timeframe: str,
    start: Optional[str],
    end: Optional[str],
    force: bool,
    sync_all: bool,
    list_symbols: bool,
    output: Optional[str],
):
    """
    Synchronize market data from Schwab API.

    Fetches historical price data and stores it in the database.
    Supports incremental updates to avoid re-fetching existing data.

    Modes:
        # List all symbols with date ranges
        jutsu sync --list
        jutsu sync --list --output symbols.csv

        # Sync all symbols to today
        jutsu sync --all

        # Sync single symbol
        jutsu sync --symbol AAPL --timeframe 1D --start 2024-01-01
        jutsu sync --symbol MSFT --timeframe 1H --start 2024-01-01 --end 2024-12-31

        # Delete symbol data
        jutsu sync delete --symbol TQQQ
    """
    # If a subcommand was invoked, skip this function
    if ctx.invoked_subcommand is not None:
        return
    config = get_config()

    try:
        # Create database session
        engine = create_engine(config.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        sync_manager = DataSync(session)

        # MODE 1: List symbols with date ranges
        if list_symbols:
            metadata_list = sync_manager.get_all_symbols_metadata()

            if not metadata_list:
                click.echo(click.style("✗ No symbols found in database", fg='yellow'))
                session.close()
                return

            # Display in terminal table
            click.echo("=" * 90)
            click.echo(f"{'Symbol':<12} {'Timeframe':<10} {'First Bar':<12} {'Last Bar':<12} {'Total Bars':>12}")
            click.echo("=" * 90)

            for item in metadata_list:
                first_bar_str = item['first_bar'].strftime('%Y-%m-%d') if item['first_bar'] else 'N/A'
                last_bar_str = item['last_bar'].strftime('%Y-%m-%d') if item['last_bar'] else 'N/A'

                click.echo(
                    f"{item['symbol']:<12} {item['timeframe']:<10} {first_bar_str:<12} "
                    f"{last_bar_str:<12} {item['total_bars']:>12,}"
                )

            click.echo("=" * 90)
            click.echo(click.style(f"\n✓ Found {len(metadata_list)} symbol/timeframe combinations", fg='green'))

            # Export to CSV if requested
            if output:
                import csv
                from pathlib import Path

                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, 'w', newline='') as csvfile:
                    fieldnames = ['symbol', 'timeframe', 'first_bar', 'last_bar', 'total_bars']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                    writer.writeheader()
                    for item in metadata_list:
                        writer.writerow({
                            'symbol': item['symbol'],
                            'timeframe': item['timeframe'],
                            'first_bar': item['first_bar'].strftime('%Y-%m-%d') if item['first_bar'] else '',
                            'last_bar': item['last_bar'].strftime('%Y-%m-%d') if item['last_bar'] else '',
                            'total_bars': item['total_bars'],
                        })

                click.echo(click.style(f"✓ Exported to {output}", fg='green'))

            session.close()
            return

        # MODE 2: Sync all symbols to today
        if sync_all:
            click.echo("=" * 60)
            if force:
                click.echo("SYNC ALL SYMBOLS TO TODAY (FORCE MODE)")
                click.echo(click.style("⚠️  Force mode: May fetch incomplete bars if market is open", fg='yellow'))
            else:
                click.echo("SYNC ALL SYMBOLS TO TODAY")
            click.echo("=" * 60)

            # Create fetcher
            fetcher = SchwabDataFetcher()

            # Run sync all
            with click.progressbar(
                length=1,
                label='Syncing all symbols',
                show_eta=False,
            ) as bar:
                result = sync_manager.sync_all_symbols(fetcher=fetcher, force=force)
                bar.update(1)

            # Display summary
            click.echo("\n" + "=" * 60)
            click.echo("SYNC RESULTS")
            click.echo("=" * 60)
            click.echo(f"Total Symbols:      {result['total_symbols']}")
            click.echo(f"Successful Syncs:   {result['successful_syncs']}")
            click.echo(f"Failed Syncs:       {result['failed_syncs']}")

            # Display details
            click.echo("\nDetails:")
            click.echo(f"{'Symbol':<15} {'Status':<20} {'Bars Added':>12} {'Date Range':<25}")
            click.echo("-" * 80)

            for symbol_key, info in result['results'].items():
                start_str = info['start_date'].strftime('%Y-%m-%d')
                end_str = info['end_date'].strftime('%Y-%m-%d')
                date_range = f"{start_str} to {end_str}"

                status_str = info['status']
                if info['status'] == 'success':
                    status_color = 'green'
                elif info['status'] == 'success_after_retry':
                    status_color = 'yellow'
                    status_str += " (retry)"
                else:
                    status_color = 'red'
                    status_str = f"FAILED: {info['error'][:30]}"

                click.secho(
                    f"{symbol_key:<15} {status_str:<20} {info['bars_added']:>12,} {date_range:<25}",
                    fg=status_color
                )

            click.echo("=" * 60)

            if result['successful_syncs'] == result['total_symbols']:
                click.echo(click.style("\n✓ All symbols synced successfully!", fg='green'))
            elif result['successful_syncs'] > 0:
                click.echo(click.style(f"\n⚠ Partial success: {result['successful_syncs']}/{result['total_symbols']} synced", fg='yellow'))
            else:
                click.echo(click.style("\n✗ All syncs failed", fg='red'))

            session.close()
            return

        # MODE 3: Normal single-symbol sync
        if not symbol:
            click.echo(click.style("✗ Error: Must provide --symbol, --all, or --list", fg='red'))
            session.close()
            raise click.Abort()

        if not start:
            click.echo(click.style("✗ Error: --start is required for single symbol sync", fg='red'))
            session.close()
            raise click.Abort()

        # Parse dates
        start_date = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        # Parse end date and set to end-of-day (23:59:59) to include all bars from that date
        # Database bars may have timestamps like 2025-11-24 05:00:00, which would be excluded
        # if end_date is midnight (2025-11-24 00:00:00)
        if end:
            end_date = datetime.strptime(end, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        else:
            # For daily bars, cap at last trading day (accounting for weekends)
            # Use start-of-day (midnight) timestamp for compatibility with Schwab API
            if timeframe == '1D':
                # Go back 4 days to account for weekend + UTC timezone offset
                safe_date = datetime.now(timezone.utc).date() - timedelta(days=4)
                end_date = datetime.combine(safe_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            else:
                end_date = datetime.now(timezone.utc)

        click.echo(f"Syncing {symbol} {timeframe} from {start_date.date()} to {end_date.date()}")

        # Create fetcher
        fetcher = SchwabDataFetcher()

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


@sync.command(name='delete')
@click.option('--symbol', required=True, help='Stock ticker symbol to delete (e.g., TQQQ)')
@click.option(
    '--force',
    is_flag=True,
    help='Skip confirmation prompt',
)
def delete_data(symbol: str, force: bool):
    """
    Delete all market data for a symbol.

    WARNING: This operation is irreversible. All market_data and data_metadata
    entries for the symbol will be permanently deleted across all timeframes.

    Example:
        jutsu sync delete --symbol TQQQ
        jutsu sync delete --symbol AAPL --force
    """
    config = get_config()

    try:
        # Create database session
        engine = create_engine(config.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        sync_manager = DataSync(session)

        # Get current data count for confirmation message
        from jutsu_engine.data.models import MarketData
        row_count = (
            session.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .count()
        )

        if row_count == 0:
            click.echo(click.style(f"✗ No data found for {symbol}", fg='yellow'))
            session.close()
            return

        # Confirmation prompt (unless --force)
        if not force:
            click.echo(f"\n⚠  WARNING: This will permanently delete {row_count:,} bars for {symbol}")
            click.echo("This operation cannot be undone.\n")
            if not click.confirm(f"Delete all data for {symbol}?"):
                click.echo("Deletion cancelled.")
                session.close()
                return

        # Perform deletion
        click.echo(f"\nDeleting data for {symbol}...")
        result = sync_manager.delete_symbol_data(symbol=symbol, force=True)

        # Display results
        if result['success']:
            if result['rows_deleted'] > 0:
                click.echo(
                    click.style(
                        f"✓ {result['message']} ({result['rows_deleted']:,} bars removed)",
                        fg='green',
                    )
                )
                if result['metadata_deleted']:
                    click.echo(click.style("✓ Metadata removed", fg='green'))
            else:
                click.echo(click.style(result['message'], fg='yellow'))
        else:
            click.echo(click.style(f"✗ Deletion failed", fg='red'))

        session.close()

    except ValueError as e:
        click.echo(click.style(f"✗ Invalid input: {e}", fg='red'))
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"✗ Deletion failed: {e}", fg='red'))
        logger.error(f"Delete operation failed: {e}", exc_info=True)
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


def _get_strategy_class_from_module(module):
    """
    Auto-detect Strategy subclass from module using introspection.

    Handles cases where module name (snake_case) differs from class name (PascalCase).

    Args:
        module: Imported strategy module

    Returns:
        Strategy subclass found in module

    Raises:
        ValueError: If no Strategy subclass found or multiple found
    """
    from jutsu_engine.core.strategy_base import Strategy

    # Get all classes defined in this module
    members = inspect.getmembers(module, inspect.isclass)

    # Filter for Strategy subclasses (but not Strategy itself, and defined in this module)
    strategy_classes = [
        cls for name, cls in members
        if issubclass(cls, Strategy)
        and cls is not Strategy
        and cls.__module__ == module.__name__
    ]

    if not strategy_classes:
        raise ValueError(f"No Strategy subclass found in {module.__name__}")
    if len(strategy_classes) > 1:
        raise ValueError(f"Multiple Strategy subclasses found in {module.__name__}: {[cls.__name__ for cls in strategy_classes]}")

    return strategy_classes[0]


def _display_baseline_section(baseline: dict):
    """
    Display baseline (buy-and-hold) metrics.

    Args:
        baseline: Dictionary with baseline metrics from PerformanceAnalyzer
    """
    symbol = baseline.get('baseline_symbol', 'QQQ')
    final_value = baseline.get('baseline_final_value', 0)
    total_return = baseline.get('baseline_total_return', 0)
    annual_return = baseline.get('baseline_annualized_return', 0)

    click.echo(f"BASELINE (Buy & Hold {symbol}):")
    click.echo(f"  Final Value:        ${final_value:,.2f}")
    click.echo(f"  Total Return:       {total_return:.2%}")
    click.echo(f"  Annualized Return:  {annual_return:.2%}")


def _display_comparison_section(results: dict, baseline: dict):
    """
    Display strategy vs baseline comparison.

    Args:
        results: Full backtest results dictionary
        baseline: Baseline metrics dictionary
    """
    # Extract metrics (cast to float to prevent Decimal/float type mixing)
    strategy_return = float(results.get('total_return', 0))
    baseline_return = float(baseline.get('baseline_total_return', 0))
    alpha = baseline.get('alpha')

    click.echo("PERFORMANCE vs BASELINE:")

    # Alpha display with color coding
    if alpha is not None:
        if alpha >= 1:
            outperformance = (alpha - 1) * 100
            alpha_text = f"{alpha:.2f}x ({outperformance:+.2f}% outperformance)"
            click.secho(f"  Alpha:              {alpha_text}", fg='green', bold=True)
        else:
            underperformance = (1 - alpha) * 100
            alpha_text = f"{alpha:.2f}x ({underperformance:.2f}% underperformance)"
            click.secho(f"  Alpha:              {alpha_text}", fg='red')
    else:
        # Alpha is None (baseline return = 0)
        alpha_note = baseline.get('alpha_note', 'Cannot calculate')
        click.secho(f"  Alpha:              N/A ({alpha_note})", fg='yellow')

    # Excess return with color coding
    excess_return = strategy_return - baseline_return
    excess_text = f"{excess_return:+.2%}"
    excess_color = 'green' if excess_return > 0 else 'red'
    click.secho(f"  Excess Return:      {excess_text}", fg=excess_color)

    # Return ratio (only if baseline return != 0)
    if baseline_return != 0:
        ratio = strategy_return / baseline_return
        click.echo(f"  Return Ratio:       {ratio:.2f}:1 (strategy:baseline)")


@cli.command()
@click.option('--symbol', default=None, help='Stock ticker symbol (single symbol mode)')
@click.option(
    '--symbols',
    multiple=True,
    callback=parse_symbols_callback,
    help='Stock ticker symbols for multi-symbol strategies. Index symbols (VIX, DJI, SPX) are auto-normalized with $ prefix. Examples: --symbols QQQ,VIX,TQQQ,SQQQ (comma-separated) OR --symbols "QQQ VIX TQQQ SQQQ" (space-separated in quotes)'
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
    default=None,
    type=float,
    help='Initial capital (default from .env: INITIAL_CAPITAL)',
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
    default=None,
    type=float,
    help='Commission per share (default from .env: DEFAULT_COMMISSION)',
)
@click.option(
    '--slippage',
    default=None,
    type=float,
    help='Slippage percent (default from .env: DEFAULT_SLIPPAGE)',
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
# Momentum-ATR Strategy Parameters (override .env values)
@click.option(
    '--macd-fast-period',
    type=int,
    default=None,
    help='MACD fast period (default from .env: STRATEGY_MACD_FAST_PERIOD)',
)
@click.option(
    '--macd-slow-period',
    type=int,
    default=None,
    help='MACD slow period (default from .env: STRATEGY_MACD_SLOW_PERIOD)',
)
@click.option(
    '--macd-signal-period',
    type=int,
    default=None,
    help='MACD signal period (default from .env: STRATEGY_MACD_SIGNAL_PERIOD)',
)
@click.option(
    '--vix-kill-switch',
    type=float,
    default=None,
    help='VIX kill switch level (default from .env: STRATEGY_VIX_KILL_SWITCH)',
)
@click.option(
    '--atr-period',
    type=int,
    default=None,
    help='ATR period (default from .env: STRATEGY_ATR_PERIOD)',
)
@click.option(
    '--atr-stop-multiplier',
    type=float,
    default=None,
    help='ATR stop multiplier (default from .env: STRATEGY_ATR_STOP_MULTIPLIER)',
)
@click.option(
    '--risk-strong-trend',
    type=float,
    default=None,
    help='Risk percent for strong trends (default from .env: STRATEGY_RISK_STRONG_TREND)',
)
@click.option(
    '--risk-waning-trend',
    type=float,
    default=None,
    help='Risk percent for waning trends (default from .env: STRATEGY_RISK_WANING_TREND)',
)
# MACD-Trend-v4 Strategy Parameters (override .env values)
@click.option(
    '--signal-symbol',
    type=str,
    default=None,
    help='Signal symbol for MACD_Trend_v4 (default from .env: STRATEGY_MACD_V4_SIGNAL_SYMBOL)',
)
@click.option(
    '--bull-symbol',
    type=str,
    default=None,
    help='Bull symbol for MACD_Trend_v4 (default from .env: STRATEGY_MACD_V4_BULL_SYMBOL)',
)
@click.option(
    '--defense-symbol',
    type=str,
    default=None,
    help='Defense symbol for MACD_Trend_v4 (default from .env: STRATEGY_MACD_V4_DEFENSE_SYMBOL)',
)
@click.option(
    '--ema-trend-period',
    type=int,
    default=None,
    help='EMA trend period for MACD_Trend_v4 (default from .env: STRATEGY_MACD_V4_EMA_PERIOD)',
)
@click.option(
    '--risk-bull',
    type=float,
    default=None,
    help='Risk allocation for bull trades (default from .env: STRATEGY_MACD_V4_RISK_BULL)',
)
@click.option(
    '--allocation-defense',
    type=float,
    default=None,
    help='Allocation for defense trades (default from .env: STRATEGY_MACD_V4_ALLOCATION_DEFENSE)',
)
@click.option(
    '--plot/--no-plot',
    default=True,
    help='Generate interactive plots (default: enabled)',
)
def backtest(
    symbol: Optional[str],
    symbols: tuple,
    timeframe: str,
    start: str,
    end: str,
    capital: Optional[float],
    strategy: str,
    short_period: int,
    long_period: int,
    position_size: int,
    commission: Optional[float],
    slippage: Optional[float],
    output: Optional[str],
    export_trades: Optional[str],
    # Momentum-ATR parameters
    macd_fast_period: Optional[int],
    macd_slow_period: Optional[int],
    macd_signal_period: Optional[int],
    vix_kill_switch: Optional[float],
    atr_period: Optional[int],
    atr_stop_multiplier: Optional[float],
    risk_strong_trend: Optional[float],
    risk_waning_trend: Optional[float],
    # MACD-Trend-v4 parameters
    signal_symbol: Optional[str],
    bull_symbol: Optional[str],
    defense_symbol: Optional[str],
    ema_trend_period: Optional[int],
    risk_bull: Optional[float],
    allocation_defense: Optional[float],
    # Plotting
    plot: bool,
):
    """
    Run a backtest with specified parameters.

    Tests a trading strategy against historical data and reports performance metrics.

    Single-symbol example:
        jutsu backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31

    Multi-symbol examples:
        # Index symbols auto-normalized (VIX → $VIX):
        jutsu backtest --strategy Momentum_ATR --symbols QQQ,VIX,TQQQ,SQQQ \\
            --start 2024-01-01 --end 2024-12-31 --capital 100000

        # Comma-separated (recommended):
        jutsu backtest --strategy ADX_Trend --symbols QQQ,TQQQ,SQQQ \\
            --start 2023-01-01 --end 2024-12-31 --capital 10000

        # Space-separated (use quotes):
        jutsu backtest --strategy ADX_Trend --symbols "QQQ TQQQ SQQQ" \\
            --start 2023-01-01 --end 2024-12-31 --capital 10000
    """
    # Determine which symbols to use
    if symbols:
        # Multi-symbol mode (--symbols takes precedence)
        # Normalize index symbols (add $ prefix for VIX, DJI, etc.)
        normalized_symbols = normalize_index_symbols(symbols)
        symbol_list = list(normalized_symbols)
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
    # Parse end date and set to end-of-day (23:59:59) to include all bars from that date
    # Database bars may have timestamps throughout the day (e.g., 2025-11-24 05:00:00)
    # Setting to 23:59:59 ensures ALL bars from the end date are included
    end_date = datetime.strptime(end, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)

    # Apply priority: CLI > .env > hardcoded
    final_capital = capital if capital is not None else env_initial_capital
    final_commission = commission if commission is not None else env_commission
    final_slippage = slippage if slippage is not None else env_slippage

    # Log loaded values
    logger.info(
        f"Backtest config: capital=${final_capital:,.2f}, "
        f"commission={final_commission}, slippage={final_slippage}"
    )

    # Display header
    click.echo("=" * 60)
    if is_multi_symbol:
        click.echo(f"BACKTEST: {', '.join(symbol_list)} {timeframe}")
    else:
        click.echo(f"BACKTEST: {symbol_list[0]} {timeframe}")
    click.echo(f"Period: {start_date.date()} to {end_date.date()}")
    click.echo(f"Initial Capital: ${final_capital:,.2f}")
    click.echo("=" * 60)

    try:
        # Create backtest configuration
        config = {
            'symbols': symbol_list,  # Now always a list
            'timeframe': timeframe,
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': Decimal(str(final_capital)),
            'commission_per_share': Decimal(str(final_commission)),
            'slippage_percent': Decimal(str(final_slippage)),
        }

        # Create strategy - dynamically load from strategies module
        try:
            # Try to import strategy module
            module_name = f"jutsu_engine.strategies.{strategy}"
            strategy_module = importlib.import_module(module_name)

            # Get strategy class (auto-detect Strategy subclass)
            strategy_class = _get_strategy_class_from_module(strategy_module)
            
            # Inspect constructor to build parameter dict dynamically
            sig = inspect.signature(strategy_class.__init__)
            params = sig.parameters
            
            # Load strategy parameters from .env with CLI overrides
            # Priority: CLI args > .env values > strategy defaults
            
            # Load .env values (with fallbacks to strategy defaults)
            env_macd_fast = int(os.getenv('STRATEGY_MACD_FAST_PERIOD', '12'))
            env_macd_slow = int(os.getenv('STRATEGY_MACD_SLOW_PERIOD', '26'))
            env_macd_signal = int(os.getenv('STRATEGY_MACD_SIGNAL_PERIOD', '9'))
            env_vix_kill_switch = float(os.getenv('STRATEGY_VIX_KILL_SWITCH', '30.0'))
            env_atr_period = int(os.getenv('STRATEGY_ATR_PERIOD', '14'))
            env_atr_stop_multiplier = float(os.getenv('STRATEGY_ATR_STOP_MULTIPLIER', '2.0'))
            env_risk_strong = float(os.getenv('STRATEGY_RISK_STRONG_TREND', '0.03'))
            env_risk_waning = float(os.getenv('STRATEGY_RISK_WANING_TREND', '0.015'))
            
            # Apply CLI overrides (if provided)
            final_macd_fast = macd_fast_period if macd_fast_period is not None else env_macd_fast
            final_macd_slow = macd_slow_period if macd_slow_period is not None else env_macd_slow
            final_macd_signal = macd_signal_period if macd_signal_period is not None else env_macd_signal
            final_vix_kill_switch = vix_kill_switch if vix_kill_switch is not None else env_vix_kill_switch
            final_atr_period = atr_period if atr_period is not None else env_atr_period
            final_atr_stop_multiplier = atr_stop_multiplier if atr_stop_multiplier is not None else env_atr_stop_multiplier
            final_risk_strong = risk_strong_trend if risk_strong_trend is not None else env_risk_strong
            final_risk_waning = risk_waning_trend if risk_waning_trend is not None else env_risk_waning

            # Determine which parameter set to use based on strategy name
            if strategy == "MACD_Trend_v5":
                # Use v5 parameters
                final_signal_symbol = signal_symbol if signal_symbol is not None else macd_v5_signal
                final_bull_symbol = bull_symbol if bull_symbol is not None else macd_v5_bull
                final_defense_symbol = defense_symbol if defense_symbol is not None else macd_v5_defense
                final_ema_trend = ema_trend_period if ema_trend_period is not None else macd_v5_ema_calm  # Default to CALM
                final_risk_bull = risk_bull if risk_bull is not None else macd_v5_risk_bull
                final_alloc_defense = allocation_defense if allocation_defense is not None else macd_v5_alloc_defense

                # v5-specific parameters
                final_vix_symbol = macd_v5_vix_symbol
                final_vix_ema = macd_v5_vix_ema
                final_ema_calm = macd_v5_ema_calm
                final_atr_calm = macd_v5_atr_calm
                final_ema_choppy = macd_v5_ema_choppy
                final_atr_choppy = macd_v5_atr_choppy

                # Override MACD/ATR with v5 values
                final_macd_fast = macd_fast_period if macd_fast_period is not None else macd_v5_fast
                final_macd_slow = macd_slow_period if macd_slow_period is not None else macd_v5_slow
                final_macd_signal = macd_signal_period if macd_signal_period is not None else macd_v5_signal_period
                final_atr_period = atr_period if atr_period is not None else macd_v5_atr

            else:
                # Use v4 parameters (default for MACD_Trend_v4 and generic strategies)
                final_signal_symbol = signal_symbol if signal_symbol is not None else macd_v4_signal
                final_bull_symbol = bull_symbol if bull_symbol is not None else macd_v4_bull
                final_defense_symbol = defense_symbol if defense_symbol is not None else macd_v4_defense
                final_ema_trend = ema_trend_period if ema_trend_period is not None else macd_v4_ema
                final_risk_bull = risk_bull if risk_bull is not None else macd_v4_risk_bull
                final_alloc_defense = allocation_defense if allocation_defense is not None else macd_v4_alloc_defense

            # Build kwargs based on what the strategy constructor accepts
            strategy_kwargs = {}
            
            # Legacy parameters (for backward compatibility with old strategies)
            if 'short_period' in params:
                strategy_kwargs['short_period'] = short_period
            if 'long_period' in params:
                strategy_kwargs['long_period'] = long_period
            if 'position_size' in params:
                strategy_kwargs['position_size'] = position_size
            
            # Momentum-ATR parameters (only add if strategy accepts them)
            if 'macd_fast_period' in params:
                strategy_kwargs['macd_fast_period'] = final_macd_fast
            if 'macd_slow_period' in params:
                strategy_kwargs['macd_slow_period'] = final_macd_slow
            if 'macd_signal_period' in params:
                strategy_kwargs['macd_signal_period'] = final_macd_signal
            if 'vix_kill_switch' in params:
                strategy_kwargs['vix_kill_switch'] = Decimal(str(final_vix_kill_switch))
            if 'atr_period' in params:
                strategy_kwargs['atr_period'] = final_atr_period
            if 'atr_stop_multiplier' in params:
                strategy_kwargs['atr_stop_multiplier'] = Decimal(str(final_atr_stop_multiplier))
            if 'risk_strong_trend' in params:
                strategy_kwargs['risk_strong_trend'] = Decimal(str(final_risk_strong))
            if 'risk_waning_trend' in params:
                strategy_kwargs['risk_waning_trend'] = Decimal(str(final_risk_waning))
            # NOTE: Let strategy use its own default position_size_percent
            # CLI --position-size is for old share-based strategies
            # if 'position_size_percent' in params:
            #     strategy_kwargs['position_size_percent'] = Decimal('1.0')

            # MACD-Trend-v4 parameters (only add if strategy accepts them)
            if 'signal_symbol' in params:
                strategy_kwargs['signal_symbol'] = final_signal_symbol
            if 'bull_symbol' in params:
                strategy_kwargs['bull_symbol'] = final_bull_symbol
            if 'defense_symbol' in params:
                strategy_kwargs['defense_symbol'] = final_defense_symbol
            if 'ema_period' in params:  # Note: parameter name in strategy is 'ema_period'
                strategy_kwargs['ema_period'] = final_ema_trend
            if 'risk_bull' in params:
                strategy_kwargs['risk_bull'] = Decimal(str(final_risk_bull))
            if 'allocation_defense' in params:
                strategy_kwargs['allocation_defense'] = Decimal(str(final_alloc_defense))

            # MACD-Trend-v5 specific parameters
            if strategy == "MACD_Trend_v5":
                if 'vix_symbol' in params:
                    strategy_kwargs['vix_symbol'] = final_vix_symbol
                if 'vix_ema_period' in params:
                    strategy_kwargs['vix_ema_period'] = final_vix_ema
                if 'ema_period_calm' in params:
                    strategy_kwargs['ema_period_calm'] = final_ema_calm
                if 'atr_stop_calm' in params:
                    strategy_kwargs['atr_stop_calm'] = Decimal(str(final_atr_calm))
                if 'ema_period_choppy' in params:
                    strategy_kwargs['ema_period_choppy'] = final_ema_choppy
                if 'atr_stop_choppy' in params:
                    strategy_kwargs['atr_stop_choppy'] = Decimal(str(final_atr_choppy))

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
        click.echo("BACKTEST RESULTS")
        click.echo("=" * 60)

        # Display baseline section if available
        baseline = results.get('baseline')
        if baseline:
            _display_baseline_section(baseline)
            click.echo("\n" + "-" * 60 + "\n")

        # Display strategy results
        click.echo(f"STRATEGY ({strategy}):")
        click.echo(f"  Initial Capital:    ${results['config']['initial_capital']:,.2f}")
        click.echo(f"  Final Value:        ${results['final_value']:,.2f}")
        click.echo(f"  Total Return:       {results['total_return']:.2%}")
        click.echo(f"  Annualized Return:  {results['annualized_return']:.2%}")
        click.echo(f"  Sharpe Ratio:       {results['sharpe_ratio']:.2f}")
        click.echo(f"  Max Drawdown:       {results['max_drawdown']:.2%}")
        click.echo(f"  Win Rate:           {results['win_rate']:.2%}")
        click.echo(f"  Total Trades:       {results['total_trades']}")

        # Display comparison section if baseline available
        if baseline and baseline.get('alpha') is not None:
            click.echo("\n" + "-" * 60 + "\n")
            _display_comparison_section(results, baseline)

        click.echo("\n" + "=" * 60)

        # Display CSV export paths
        click.echo("\nCSV EXPORTS:")

        # Trades CSV
        if 'trades_csv_path' in results and results['trades_csv_path']:
            click.echo(f"  ✓ Trade log: {results['trades_csv_path']}")
        elif 'trades_csv_path' in results and results['trades_csv_path'] is None:
            click.echo(f"  ⚠ Trade log: No trades to export")

        # Portfolio CSV
        if 'portfolio_csv_path' in results and results['portfolio_csv_path']:
            click.echo(f"  ✓ Portfolio daily: {results['portfolio_csv_path']}")

        # Summary CSV
        if 'summary_csv_path' in results and results['summary_csv_path']:
            click.echo(f"  ✓ Summary metrics: {results['summary_csv_path']}")

        click.echo()  # Blank line after exports

        # Generate plots if requested
        if plot and 'portfolio_csv_path' in results and results['portfolio_csv_path']:
            try:
                from jutsu_engine.infrastructure.visualization import EquityPlotter

                click.echo("Generating interactive plots...")

                # Create plotter
                plotter = EquityPlotter(csv_path=results['portfolio_csv_path'])

                # Generate all plots
                equity_path, drawdown_path = plotter.generate_all_plots()

                # Display plot paths
                click.echo("\nPLOTS GENERATED:")
                click.echo(f"  ✓ Equity curve: {equity_path}")
                click.echo(f"  ✓ Drawdown: {drawdown_path}")
                click.echo()

            except Exception as e:
                logger.warning(f"Plot generation failed: {e}")
                click.echo(click.style(f"  ⚠ Plot generation failed: {e}", fg='yellow'))
                click.echo()

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
    # Parse end date and set to end-of-day (23:59:59) to include all bars from that date
    # Database bars may have timestamps throughout the day (e.g., 2025-11-24 05:00:00)
    # Setting to 23:59:59 ensures ALL bars from the end date are included
    end_date = (
        datetime.strptime(end, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        if end
        else None
    )

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


@cli.command()
@click.option(
    '--config',
    '-c',
    required=True,
    type=click.Path(exists=True),
    help='Path to grid search YAML configuration',
)
@click.option(
    '--output',
    '-o',
    default='output',
    help='Base output directory (default: output/)',
)
@click.option(
    '--analyze',
    is_flag=True,
    help='Run robustness analysis after grid search',
)
@click.option(
    '--plot/--no-plot',
    default=True,
    help='Generate interactive plots (default: enabled)',
)
def grid_search(config: str, output: str, analyze: bool, plot: bool):
    """
    Run parameter grid search optimization.

    Performs exhaustive backtest across all parameter combinations
    and generates comparison CSV with key metrics.

    Example:
        jutsu grid-search --config grid-configs/macd_optimization.yaml
        jutsu grid-search -c grid-configs/macd_optimization.yaml -o results/
    """
    click.echo("=" * 60)
    click.echo("Grid Search Parameter Optimization")
    click.echo("=" * 60)

    # Load configuration
    click.echo(f"\nLoading config: {config}")
    try:
        grid_config = GridSearchRunner.load_config(config)
    except Exception as e:
        click.echo(click.style(f"✗ Configuration error: {e}", fg='red'))
        logger.error(f"Failed to load config: {e}", exc_info=True)
        raise click.Abort()

    # Display configuration summary
    click.echo(f"\nStrategy: {grid_config.strategy_name}")
    click.echo(f"Symbol Sets: {len(grid_config.symbol_sets)}")
    click.echo(f"Parameters: {len(grid_config.parameters)}")

    # Create runner
    runner = GridSearchRunner(grid_config)

    # Generate combinations (preview)
    try:
        combinations = runner.generate_combinations()
    except Exception as e:
        click.echo(click.style(f"✗ Error generating combinations: {e}", fg='red'))
        logger.error(f"Combination generation failed: {e}", exc_info=True)
        raise click.Abort()

    click.echo(f"Total Combinations: {len(combinations)}")

    # Confirm if > 100 combinations
    if len(combinations) > 100:
        click.echo(f"\n⚠  Warning: {len(combinations)} backtests will take significant time")
        if not click.confirm("Continue?"):
            click.echo("Aborted.")
            return

    # Execute grid search
    click.echo(f"\nRunning grid search...")
    click.echo("(Progress bar will appear below)\n")

    try:
        result = runner.execute_grid_search(
            output_base=output,
            config_path=config,
            generate_plots=plot
        )
    except Exception as e:
        click.echo(click.style(f"\n✗ Grid search failed: {e}", fg='red'))
        logger.error(f"Grid search execution failed: {e}", exc_info=True)
        raise click.Abort()

    # Display summary
    click.echo("\n" + "=" * 60)
    click.echo(click.style("✓ Grid Search Complete!", fg='green'))
    click.echo("=" * 60)
    click.echo(f"Total Runs: {len(result.run_results)}")
    click.echo(f"Output Directory: {result.output_dir}")
    click.echo(f"\nFiles Generated:")
    click.echo(f"  - summary_comparison.csv (metrics comparison)")
    click.echo(f"  - run_config.csv (parameter mapping)")
    click.echo(f"  - {len(result.run_results)} run directories")
    if plot:
        click.echo(f"  - plots/ directory (4 interactive HTML visualizations)")

    # Best run (by Sharpe Ratio)
    if len(result.summary_df) > 0 and 'sharpe_ratio' in result.summary_df.columns:
        click.echo("\nBest Run (by Sharpe Ratio):")
        best_idx = result.summary_df['sharpe_ratio'].idxmax()
        best = result.summary_df.loc[best_idx]
        click.echo(f"  Run ID: {best['run_id']}")
        click.echo(f"  Symbol Set: {best['symbol_set']}")
        click.echo(f"  Sharpe Ratio: {best['sharpe_ratio']:.2f}")
        click.echo(f"  Annualized Return: {best['annualized_return_pct']:.2f}%")
        click.echo(f"  Max Drawdown: {best['max_drawdown_pct']:.2f}%")
    else:
        click.echo(click.style("\n⚠ No valid results to display", fg='yellow'))

    click.echo("=" * 60)

    # Run analyzer if flag set
    if analyze:
        from jutsu_engine.application.grid_search_runner import GridSearchAnalyzer

        click.echo("\n" + "=" * 60)
        click.echo("Running Robustness Analysis...")
        click.echo("=" * 60)

        try:
            analyzer = GridSearchAnalyzer(output_dir=result.output_dir)
            summary = analyzer.analyze()

            # Display summary
            click.echo(f"\nAnalysis complete: {len(summary)} configurations analyzed")

            # Check if we have results
            if len(summary) == 0:
                click.echo(click.style("\n⚠ No configurations analyzed (all runs filtered or missing data)", fg='yellow'))
                click.echo(f"\nOutput: {result.output_dir / 'analyzer_summary.csv'}")
            else:
                click.echo(f"\nVerdict Breakdown:")
                verdict_counts = summary['verdict'].value_counts()
                for verdict, count in verdict_counts.items():
                    click.echo(f"  {verdict}: {count}")

                # Highlight TITAN configs
                titan_configs = summary[summary['verdict'] == 'TITAN CONFIG']
                if len(titan_configs) > 0:
                    click.echo(click.style(f"\n✓ Found {len(titan_configs)} TITAN CONFIG(s)!", fg='green', bold=True))

                click.echo(f"\nOutput: {result.output_dir / 'analyzer_summary.csv'}")

        except Exception as e:
            click.echo(click.style(f"\n✗ Analysis failed: {e}", fg='red'))
            logger.error(f"Analyzer execution failed: {e}", exc_info=True)


@cli.command()
@click.option(
    '--config',
    '-c',
    required=True,
    type=click.Path(exists=True),
    help='Path to WFO YAML configuration',
)
@click.option(
    '--output-dir',
    '-o',
    type=click.Path(),
    help='Custom output directory (default: auto-generated)',
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Show window plan without running',
)
@click.option(
    '--plot/--no-plot',
    default=True,
    help='Generate interactive plots (default: enabled)',
)
def wfo(config: str, output_dir: Optional[str], dry_run: bool, plot: bool):
    """
    Walk-Forward Optimization - defeat curve-fitting through periodic re-optimization.

    Implements rigorous WFO methodology:
    - Divide total period into sliding windows (IS + OOS)
    - Optimize on In-Sample period (grid search)
    - Test on Out-of-Sample period (backtest)
    - Stitch all OOS results for true performance

    Example:
        jutsu wfo --config grid-configs/examples/wfo_macd_v6.yaml
        jutsu wfo -c grid-configs/examples/wfo_macd_v6.yaml --dry-run
    """
    from jutsu_engine.application.wfo_runner import WFORunner

    click.echo("=" * 60)
    click.echo("Walk-Forward Optimization")
    click.echo("=" * 60)

    # Load configuration
    click.echo(f"\nLoading config: {config}")
    try:
        runner = WFORunner(config_path=config, output_dir=output_dir)
    except Exception as e:
        click.echo(click.style(f"✗ Configuration error: {e}", fg='red'))
        logger.error(f"Failed to load config: {e}", exc_info=True)
        raise click.Abort()

    # Display configuration summary
    click.echo(f"\nStrategy: {runner.config['strategy']}")
    click.echo(f"Date Range: {runner.config['walk_forward']['total_start_date']} to "
              f"{runner.config['walk_forward']['total_end_date']}")
    click.echo(f"Window: {runner.config['walk_forward']['in_sample_years']}y IS + "
              f"{runner.config['walk_forward']['out_of_sample_years']}y OOS")
    click.echo(f"Slide: {runner.config['walk_forward']['slide_years']}y")
    click.echo(f"Selection Metric: {runner.config['walk_forward']['selection_metric']}")

    # Calculate windows
    try:
        windows = runner.calculate_windows()
        click.echo(f"\nTotal Windows: {len(windows)}")
    except Exception as e:
        click.echo(click.style(f"✗ Window calculation failed: {e}", fg='red'))
        logger.error(f"Failed to calculate windows: {e}", exc_info=True)
        raise click.Abort()

    # Dry run - show window plan
    if dry_run:
        click.echo("\n" + "=" * 60)
        click.echo("Window Plan (Dry Run)")
        click.echo("=" * 60)
        for w in windows:
            click.echo(f"\nWindow {w.window_id}:")
            click.echo(f"  IS:  {w.is_start.date()} to {w.is_end.date()}")
            click.echo(f"  OOS: {w.oos_start.date()} to {w.oos_end.date()}")
        click.echo("\n" + "=" * 60)
        click.echo(click.style("✓ Dry run complete (no execution)", fg='green'))
        return

    # Calculate total combinations
    param_values = [len(v) for v in runner.config['parameters'].values()]
    import functools
    import operator
    total_combinations = functools.reduce(operator.mul, param_values, 1)
    total_backtests = len(windows) * total_combinations

    click.echo(f"\nParameter Combinations: {total_combinations}")
    click.echo(f"Total Backtests: {total_backtests}")
    click.echo(click.style(f"\n⚠ This will take significant time!", fg='yellow'))

    # Confirm execution
    if not click.confirm("\nProceed with WFO?"):
        click.echo("Aborted.")
        return

    # Run WFO
    click.echo("\n" + "=" * 60)
    click.echo("Executing Walk-Forward Optimization")
    click.echo("=" * 60)

    try:
        result = runner.run()
    except Exception as e:
        click.echo(click.style(f"\n✗ WFO failed: {e}", fg='red'))
        logger.error(f"WFO execution failed: {e}", exc_info=True)
        raise click.Abort()

    # Display results
    click.echo("\n" + "=" * 60)
    click.echo(click.style("✓ Walk-Forward Optimization Complete!", fg='green'))
    click.echo("=" * 60)

    click.echo(f"\nWindows Processed: {result['num_windows']}")
    click.echo(f"Total OOS Trades: {result['total_oos_trades']}")
    click.echo(f"Final Equity: ${result['final_equity']:,.2f}")
    click.echo(f"OOS Return: {result['oos_return_pct']:.2%}")

    click.echo(f"\nOutput Directory: {result['output_dir']}")
    click.echo("\nOutput Files:")
    for file_type, path in result['output_files'].items():
        click.echo(f"  - {file_type}: {path}")

    # Parameter stability
    if result.get('parameter_stability'):
        click.echo("\nParameter Stability (CV%):")
        for param, cv in sorted(result['parameter_stability'].items()):
            if param != 'mean_cv':
                status = "✓" if cv < 20 else ("⚠" if cv < 50 else "✗")
                click.echo(f"  {status} {param}: {cv:.2f}%")

    click.echo("=" * 60)


# Import and register Monte Carlo command
from jutsu_engine.cli.commands.monte_carlo import monte_carlo as monte_carlo_cmd
cli.add_command(monte_carlo_cmd, name='monte-carlo')


if __name__ == '__main__':
    cli()
