"""
Daily Dry-Run Script - 15:49-15:56 EST Workflow.

This is the main execution script for Phase 1 (Dry-Run Mode).
Runs daily at 15:49 EST to execute the complete trading workflow
WITHOUT placing actual orders.

Version: 2.1 (Unified Executor with Data Freshness Check - PRD v2.0.1 Compliant)

Workflow (7 minutes):
15:44:00 - [OPTIONAL] Pre-execution data freshness check (--check-freshness)
15:49:30 - OAuth validation
15:50:00 - Market calendar check
15:50:30 - Fetch historical bars (QQQ, TLT)
15:51:00 - Fetch current quotes (TQQQ, TMF, TMV, QQQ, TLT)
15:51:30 - Validate corporate actions
15:52:00 - Create synthetic daily bar
15:52:30 - Run strategy (Hierarchical_Adaptive_v3_5b)
15:53:00 - Fetch account positions
15:53:30 - Convert weights to shares (PositionRounder)
15:54:00 - Calculate rebalance diff
15:54:30 - Log hypothetical orders (MOCK MODE)
15:55:00 - Save state

Usage:
    python scripts/daily_dry_run.py                    # Standard execution
    python scripts/daily_dry_run.py --check-freshness  # With data freshness check
"""

import argparse
import sys
import logging
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict
import pandas as pd
import os

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from schwab import auth, client
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.live.market_calendar import is_trading_day
from jutsu_engine.live.data_fetcher import LiveDataFetcher
from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.position_rounder import PositionRounder
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.live.executor_router import ExecutorRouter
from jutsu_engine.live.data_freshness import DataFreshnessChecker, DataFreshnessError
from jutsu_engine.data.models import Position
from jutsu_engine.utils.config import get_database_url, get_database_type, DATABASE_TYPE_SQLITE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/daily_dry_run_{datetime.now():%Y%m%d}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('LIVE.DAILY_DRY_RUN')


def load_config(config_path: Path = Path('config/live_trading_config.yaml')) -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    logger.info(f"Config loaded: {config['strategy']['name']}")
    return config


def initialize_schwab_client():
    """Initialize Schwab API client with OAuth."""
    load_dotenv()
    import os

    project_root = Path(__file__).parent.parent

    # Handle Docker paths - match logic in schwab_auth.py and schwab.py
    # In Docker, /app exists and token files are stored in /app/data/
    token_path_raw = 'token.json'
    if Path('/app').exists():
        token_path = Path('/app/data') / token_path_raw
    else:
        token_path = project_root / token_path_raw

    # CRITICAL: Check if token exists BEFORE calling easy_client
    # In Docker/headless environments, easy_client blocks forever waiting for
    # interactive OAuth flow if no token exists
    # See: https://schwab-py.readthedocs.io/en/latest/auth.html
    if not token_path.exists():
        logger.error(
            f"No Schwab token found at {token_path}. "
            "Please authenticate via dashboard /config page first."
        )
        raise FileNotFoundError(
            f"Schwab token not found at {token_path}. "
            "Authenticate via dashboard before running dry-run."
        )

    try:
        # IMPORTANT: schwab-py only allows 127.0.0.1, NOT localhost
        # See: https://schwab-py.readthedocs.io/en/latest/auth.html#callback-url-advisory
        schwab_client = auth.easy_client(
            api_key=os.getenv('SCHWAB_API_KEY'),
            app_secret=os.getenv('SCHWAB_API_SECRET'),
            callback_url=os.getenv('SCHWAB_CALLBACK_URL', 'https://127.0.0.1:8182'),
            token_path=str(token_path)
        )
        logger.info(f"Schwab client initialized successfully (token: {token_path})")
        return schwab_client
    except Exception as e:
        logger.error(f"Failed to initialize Schwab client: {e}")
        raise


def main(check_freshness: bool = False):
    """
    Main daily dry-run execution workflow.

    Args:
        check_freshness: If True, validates local DB data freshness before execution.
                        Auto-triggers sync if data is stale.

    This function orchestrates the complete trading workflow:
    0. [Optional] Check data freshness and sync if needed
    1. Load configuration and initialize clients
    2. Validate trading day and OAuth
    3. Fetch market data (historical + quotes)
    4. Run strategy to generate signals
    5. Calculate target allocation
    6. Convert to shares (NO FRACTIONAL SHARES)
    7. Calculate rebalance diff
    8. Log hypothetical orders (DRY-RUN)
    9. Save state for next run
    """
    logger.info("=" * 80)
    logger.info("Daily Dry-Run Starting - Phase 1 Workflow")
    logger.info("=" * 80)

    try:
        # Step 0: [Optional] Data freshness check
        if check_freshness:
            logger.info("Step 0: Checking data freshness")
            try:
                # Required symbols for strategy
                required_symbols = ['QQQ', 'TLT', 'TQQQ', 'PSQ', 'TMF', 'TMV']
                checker = DataFreshnessChecker(
                    db_path='data/market_data.db',
                    required_symbols=required_symbols
                )

                is_fresh, details = checker.ensure_fresh_data(auto_sync=True)
                checker.close()

                if is_fresh:
                    logger.info("  Data freshness check PASSED - all symbols up to date")
                else:
                    logger.warning("  Data freshness check WARNING - some symbols may be stale")
                    # Continue execution - live trading uses Schwab API directly anyway
                    logger.info("  Continuing with execution (live data will be fetched from Schwab)")

            except DataFreshnessError as e:
                logger.warning(f"  Data freshness check skipped: {e}")
                logger.info("  Continuing with execution (live data will be fetched from Schwab)")
        else:
            logger.info("Step 0: Data freshness check SKIPPED (use --check-freshness to enable)")

        # Step 1: Load configuration
        logger.info("Step 1: Loading configuration")
        config = load_config()

        # Extract config sections
        strategy_config = config['strategy']
        execution_config = config['execution']
        state_config = config['state']

        # v2.0 FLAT CONFIG: Extract symbols from parameters (not universe)
        params = strategy_config['parameters']
        symbols = {
            'signal_symbol': params['signal_symbol'],           # QQQ
            'bull_symbol': params['leveraged_long_symbol'],     # TQQQ
            'bond_signal': params['treasury_trend_symbol'],     # TLT
            'bull_bond': params['bull_bond_symbol'],            # TMF
            'bear_bond': params['bear_bond_symbol']             # TMV
        }
        logger.info(f"  Symbols loaded: {symbols}")

        # Step 2: Initialize components
        logger.info("Step 2: Initializing components")
        schwab_client = initialize_schwab_client()
        data_fetcher = LiveDataFetcher(schwab_client)
        strategy_runner = LiveStrategyRunner()
        state_manager = StateManager(
            state_file=Path(state_config['file_path']),
            backup_enabled=state_config['backup_enabled']
        )
        position_rounder = PositionRounder()

        # Create executor via unified router (MOCK mode for dry-run)
        executor = ExecutorRouter.create(
            mode=TradingMode.OFFLINE_MOCK,
            config=config,
            trade_log_path=Path('logs/live_trades.csv')
        )
        logger.info(f"Executor created: mode={executor.get_mode().value}")

        # Step 3: Check if trading day (15:50:00)
        logger.info("Step 3: Checking if trading day")
        if not is_trading_day():
            logger.info("Not a trading day (weekend/holiday) - exiting")
            return

        # Step 4: Fetch historical bars (15:50:30)
        logger.info("Step 4: Fetching historical data (QQQ, TLT)")
        historical_data = {}

        for key in ['signal_symbol', 'bond_signal']:
            symbol = symbols[key]
            logger.info(f"  Fetching {symbol} historical bars (250 days)")
            df = data_fetcher.fetch_historical_bars(symbol, lookback=250)
            historical_data[symbol] = df
            logger.info(f"  {symbol}: {len(df)} bars retrieved")

        # Step 5: Fetch current quotes (15:51:00)
        logger.info("Step 5: Fetching current quotes (all 5 symbols)")
        current_quotes = {}
        current_prices = {}

        for key, symbol in symbols.items():
            logger.info(f"  Fetching {symbol} quote")
            response = schwab_client.get_quote(symbol)
            if response.status_code != 200:
                logger.error(f"Quote API error for {symbol}: status {response.status_code}")
                return
            data = response.json()
            if symbol not in data:
                logger.error(f"Symbol {symbol} not in quote response")
                return
            quote_info = data[symbol].get('quote', {})
            last_price = Decimal(str(quote_info.get('lastPrice', 0)))
            current_quotes[symbol] = data[symbol]
            current_prices[symbol] = last_price
            logger.info(f"  {symbol}: ${last_price:.2f}")

        # Step 6: Validate corporate actions (15:51:30)
        logger.info("Step 6: Validating corporate actions")
        for symbol, df in historical_data.items():
            is_valid = data_fetcher.validate_corporate_actions(df)
            if not is_valid:
                logger.error(f"Corporate action detected in {symbol} - ABORTING")
                logger.error("Manual review required before trading")
                return
        logger.info("  No corporate actions detected ✅")

        # Step 7: Create synthetic daily bar (15:52:00)
        logger.info("Step 7: Creating synthetic daily bars")
        market_data = {}

        for key in ['signal_symbol', 'bond_signal']:
            symbol = symbols[key]
            hist_df = historical_data[symbol]
            current_quote = current_prices[symbol]

            synthetic_df = data_fetcher.create_synthetic_daily_bar(
                hist_df,
                current_quote
            )
            market_data[symbol] = synthetic_df
            logger.info(f"  {symbol}: {len(synthetic_df)} bars (historical + synthetic)")

        # Step 8: Load LOCAL portfolio state from DATABASE FIRST (primary source of truth)
        # OFFLINE MOCK MODE: Use LOCAL state, NOT real Schwab account
        # FIX: Load positions from database to prevent stale state.json causing duplicate trades
        logger.info("Step 8: Loading LOCAL portfolio state (OFFLINE MOCK MODE)")

        # Load state from local file for equity and other metadata
        state = state_manager.load_state()
        state_equity = state.get('account_equity')

        # Get initial capital from config (default $10K)
        portfolio_config = config.get('portfolio', {})
        initial_capital = Decimal(str(portfolio_config.get('initial_capital', 10000)))

        # Check for first run (no state file or empty state)
        is_first_run = state_equity is None

        # Load current positions from DATABASE (primary source of truth)
        # This prevents duplicate trades when scheduler "Run Now" loads stale state.json
        # FIX: Use centralized get_database_url() instead of hardcoded SQLite default
        # This ensures Docker deployments use PostgreSQL correctly
        db_url = get_database_url()
        db_type = get_database_type()
        if db_type == DATABASE_TYPE_SQLITE:
            engine = create_engine(db_url, connect_args={'check_same_thread': False})
        else:
            engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        db_session = Session()

        try:
            # Query positions table for offline_mock mode
            db_positions = db_session.query(Position).filter(
                Position.mode == 'offline_mock'
            ).all()

            if db_positions:
                # Database has positions - use as primary source
                current_positions = {p.symbol: p.quantity for p in db_positions}
                logger.info(f"  Loaded {len(current_positions)} positions from DATABASE (primary source)")
                for symbol, qty in current_positions.items():
                    logger.info(f"    {symbol}: {qty} shares")
            else:
                # No positions in database - fall back to state.json
                state_positions = state.get('current_positions', {})
                if state_positions:
                    current_positions = state_positions
                    logger.info(f"  Loaded {len(current_positions)} positions from state.json (DB empty)")
                else:
                    # Truly first run - no positions anywhere
                    current_positions = {}
                    logger.info("  No positions found in database or state.json (first run)")

        except Exception as e:
            logger.error(f"  Failed to load positions from database: {e}")
            logger.warning("  Falling back to state.json positions")
            current_positions = state.get('current_positions', {})
        finally:
            db_session.close()

        if is_first_run:
            logger.info("First run detected - initializing LOCAL portfolio")
            logger.info(f"  Initial Capital: ${initial_capital:,.2f}")
            account_equity = initial_capital
        else:
            # Calculate current equity from positions × current prices
            position_value = Decimal('0')
            for symbol, qty in current_positions.items():
                if symbol in current_prices:
                    position_value += current_prices[symbol] * qty
                else:
                    logger.warning(f"  No current price for {symbol}, position value unknown")

            # Use stored equity or calculate from positions
            if state_equity:
                account_equity = Decimal(str(state_equity))
            else:
                account_equity = initial_capital

            logger.info(f"  Loaded LOCAL state:")
            logger.info(f"    Positions: {current_positions}")
            logger.info(f"    Portfolio Equity: ${account_equity:,.2f}")

        logger.info(f"  OFFLINE MOCK MODE - Using LOCAL portfolio (NOT real Schwab account)")

        # Step 9: Run strategy (15:52:30)
        logger.info("Step 9: Running strategy (Hierarchical_Adaptive_v3_5b)")
        signals = strategy_runner.calculate_signals(market_data)
        logger.info(f"  Signals: Cell {signals['current_cell']}, Vol State {signals['vol_state']}")

        # Inject portfolio capital into strategy for weight validation
        # CRITICAL: Must happen AFTER calculate_signals() warmup, BEFORE determine_target_allocation()
        # The warmup phase depletes internal backtest cash, so we restore live capital here
        strategy_runner.strategy._cash = account_equity
        logger.info(f"  Injected ${account_equity:,.2f} into strategy after warmup for weight calculation")

        # Step 10: Determine target allocation (15:53:00)
        logger.info("Step 10: Determining target allocation")
        target_weights = strategy_runner.determine_target_allocation(
            signals,
            account_equity
        )
        logger.info(f"  Target Weights: {target_weights}")

        # Step 11: Convert weights to shares (15:53:30)
        logger.info("Step 11: Converting weights to shares (NO FRACTIONAL SHARES)")
        target_positions = position_rounder.convert_weights_to_shares(
            target_weights,
            account_equity,
            current_prices
        )
        logger.info(f"  Target Positions: {target_positions}")

        # Validate no over-allocation
        position_rounder.validate_no_over_allocation(
            target_positions,
            current_prices,
            account_equity
        )

        # Calculate cash remainder
        cash_amount, cash_pct = position_rounder.calculate_cash_remainder(
            target_positions,
            current_prices,
            account_equity
        )
        logger.info(f"  Cash Remainder: ${cash_amount:,.2f} ({cash_pct:.2f}%)")

        # Step 12: Calculate rebalance diff and execute via unified executor (15:54:00)
        logger.info("Step 12: Calculating rebalance diff")

        # Calculate position diffs (target - current)
        position_diffs = {}
        all_symbols = set(current_positions.keys()) | set(target_positions.keys())
        for symbol in all_symbols:
            current = current_positions.get(symbol, 0)
            target = target_positions.get(symbol, 0)
            diff = target - current
            if diff != 0:
                position_diffs[symbol] = diff

        logger.info(f"  Position diffs (before filtering): {position_diffs}")

        if not position_diffs:
            logger.info("  No position changes needed - portfolio already at target")
            fills = []
        else:
            # Filter by rebalance threshold (5% default)
            filtered_diffs = executor.filter_by_threshold(
                position_diffs,
                current_prices,
                account_equity
            )

            if not filtered_diffs:
                logger.info("  No trades exceed threshold - no action needed")
                fills = []
            else:
                # BUDGET VALIDATION: Prevent duplicate trades by validating total buy value
                # Calculate total cost of all BUY orders
                total_buy_value = Decimal('0')
                total_sell_value = Decimal('0')
                for symbol, diff in filtered_diffs.items():
                    price = current_prices.get(symbol, Decimal('0'))
                    if diff > 0:  # BUY order
                        total_buy_value += price * diff
                    else:  # SELL order
                        total_sell_value += abs(price * diff)

                # Calculate current position value
                current_position_value = sum(
                    current_prices.get(sym, Decimal('0')) * qty
                    for sym, qty in current_positions.items()
                )

                # Calculate available cash (equity - current position value)
                available_cash = account_equity - current_position_value

                # Add proceeds from sells to available cash
                available_cash_after_sells = available_cash + total_sell_value

                logger.info(f"  Budget validation:")
                logger.info(f"    Current position value: ${current_position_value:,.2f}")
                logger.info(f"    Available cash: ${available_cash:,.2f}")
                logger.info(f"    Sell proceeds: ${total_sell_value:,.2f}")
                logger.info(f"    Cash after sells: ${available_cash_after_sells:,.2f}")
                logger.info(f"    Total buy cost: ${total_buy_value:,.2f}")

                # Validate buy orders don't exceed available budget
                if total_buy_value > available_cash_after_sells:
                    logger.error(f"  BUDGET EXCEEDED: Trades require ${total_buy_value:,.2f} but only ${available_cash_after_sells:,.2f} available")
                    logger.error(f"  ABORTING - Cannot execute trades that exceed portfolio budget")
                    logger.error(f"  This indicates duplicate trades or stale position data")
                    return

                logger.info(f"  Budget check PASSED: ${total_buy_value:,.2f} <= ${available_cash_after_sells:,.2f}")

                # Build strategy context for logging
                strategy_context = {
                    'current_cell': signals.get('current_cell'),
                    'trend_state': signals.get('trend_state'),
                    'vol_state': signals.get('vol_state'),
                    't_norm': signals.get('t_norm'),
                    'z_score': signals.get('z_score'),
                }

                # Execute via unified executor
                fills, fill_prices = executor.execute_rebalance(
                    position_diffs=filtered_diffs,
                    current_prices=current_prices,
                    reason="Rebalance",
                    strategy_context=strategy_context
                )

        if fills:
            logger.info(f"  {len(fills)} hypothetical orders logged:")
            for fill in fills:
                logger.info(f"    {fill['action']} {fill['quantity']} {fill['symbol']} @ ${fill['fill_price']:.2f}")
        else:
            logger.info("  No orders - portfolio already at target or below threshold")

        # Step 12b: Update positions in database ONLY if trades executed
        # BUG FIX: Previously updated positions unconditionally, causing quantities
        # to change without trades (recalculated based on price changes)
        if fills:
            logger.info("Step 12b: Updating positions in database (trades executed)")
            executor.update_positions(
                target_positions=target_positions,
                current_prices=current_prices,
                account_equity=account_equity
            )
            logger.info("  Positions updated in database ✅")
            # After trades, use target positions for snapshot
            positions_for_snapshot = target_positions
        else:
            logger.info("Step 12b: Skipping position update (no trades executed)")
            logger.info("  Positions unchanged in database ✅")
            # No trades - use current positions for snapshot
            positions_for_snapshot = current_positions

        # Step 12c: Save performance snapshot (with auto-calculated P&L)
        logger.info("Step 12c: Saving performance snapshot")

        # BUG FIX: Calculate positions_value from ACTUAL positions, not targets
        # This ensures equity reflects real portfolio value changes from price movements
        positions_value = sum(
            current_prices.get(sym, Decimal('0')) * qty
            for sym, qty in positions_for_snapshot.items()
        )

        # BUG FIX: Calculate ACTUAL equity from positions + cash
        # Previously used static initial_capital, never reflecting P&L
        # Cash is what remains after allocating to positions
        if fills:
            # After trades, use the calculated cash remainder
            actual_cash = cash_amount
        else:
            # No trades - calculate cash from equity minus position value
            # Use stored equity from state, then recalculate
            actual_cash = account_equity - positions_value

        # Actual equity = positions at current prices + cash
        actual_equity = positions_value + actual_cash

        logger.info(f"  Actual equity calculation:")
        logger.info(f"    Positions value: ${positions_value:,.2f}")
        logger.info(f"    Cash: ${actual_cash:,.2f}")
        logger.info(f"    Actual equity: ${actual_equity:,.2f}")

        # Get initial capital from config
        initial_capital = Decimal(str(portfolio_config.get('initial_capital', 10000)))

        # Calculate QQQ baseline (buy-and-hold comparison)
        # Get current QQQ price
        qqq_price = current_prices.get('QQQ', current_prices.get(symbols['signal_symbol']))

        # Get initial QQQ price from state (stored on first run)
        initial_qqq_price = state.get('initial_qqq_price')

        if initial_qqq_price is None:
            # First run - store initial QQQ price
            initial_qqq_price = float(qqq_price)
            state['initial_qqq_price'] = initial_qqq_price
            logger.info(f"  QQQ baseline initialized: ${initial_qqq_price:.2f}")
            baseline_value = initial_capital
            baseline_return = 0.0
        else:
            # Calculate baseline based on QQQ price change since inception
            qqq_return = (float(qqq_price) / initial_qqq_price) - 1
            baseline_value = initial_capital * Decimal(str(1 + qqq_return))
            baseline_return = qqq_return * 100

        logger.info(f"  QQQ Baseline: ${baseline_value:,.2f} ({baseline_return:+.2f}%)")

        executor.save_performance_snapshot(
            account_equity=actual_equity,  # BUG FIX: Use actual equity, not static
            cash_balance=actual_cash,      # BUG FIX: Use actual cash
            positions_value=positions_value,
            initial_capital=initial_capital,
            strategy_context={
                'current_cell': signals.get('current_cell'),
                'trend_state': signals.get('trend_state'),
                'vol_state': signals.get('vol_state'),
            },
            baseline_value=baseline_value,
            baseline_return=baseline_return
        )
        logger.info("  Performance snapshot saved ✅")

        # Step 13: Save state (15:55:00)
        logger.info("Step 13: Saving state")
        # Convert string vol_state to integer for state manager
        # State manager expects: -1, 0, 1, or None (integers)
        # Strategy returns: "Low" or "High" (strings)
        vol_state_map = {'Low': 0, 'High': 1, None: None}
        vol_state_str = signals['vol_state']
        state['vol_state'] = vol_state_map.get(vol_state_str, 0)
        # BUG FIX: Only update positions in state if trades executed
        if fills:
            state['current_positions'] = target_positions
        # else: keep existing current_positions unchanged
        state['account_equity'] = float(actual_equity)  # BUG FIX: Save actual equity
        state['last_allocation'] = target_weights

        state_manager.save_state(state)
        logger.info("  State saved successfully ✅")

        # Summary
        logger.info("=" * 80)
        logger.info("Daily Dry-Run Complete - Summary")
        logger.info("=" * 80)
        logger.info(f"Strategy Cell: {signals['current_cell']}")
        logger.info(f"Vol State: {signals['vol_state']}")
        logger.info(f"Account Equity: ${account_equity:,.2f}")
        logger.info(f"Hypothetical Orders: {len(fills)}")
        logger.info(f"Cash Remainder: ${cash_amount:,.2f} ({cash_pct:.2f}%)")
        logger.info(f"Mode: {executor.get_mode().value.upper()} (no actual orders placed)")
        logger.info("=" * 80)

        # Cleanup executor database session
        executor.close()

    except Exception as e:
        logger.error(f"Daily dry-run failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Daily dry-run execution workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--check-freshness',
        action='store_true',
        help='Check local DB data freshness before execution. Auto-syncs if stale.'
    )

    args = parser.parse_args()
    main(check_freshness=args.check_freshness)
