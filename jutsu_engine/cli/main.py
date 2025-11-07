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
from datetime import datetime, timezone
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
    end_date = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc)

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
            
            # Get strategy class (assume class name matches file name)
            strategy_class = getattr(strategy_module, strategy)
            
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

            # Apply priority logic for MACD-Trend-v4 parameters: CLI > .env > strategy defaults
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
