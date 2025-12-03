"""
Daily Dry-Run Script - 15:49-15:56 EST Workflow.

This is the main execution script for Phase 1 (Dry-Run Mode).
Runs daily at 15:49 EST to execute the complete trading workflow
WITHOUT placing actual orders.

Workflow (7 minutes):
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
15:54:30 - Log hypothetical orders (DRY-RUN)
15:55:00 - Save state
"""

import sys
import logging
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from schwab import auth, client
import yaml

from jutsu_engine.live.market_calendar import is_trading_day
from jutsu_engine.live.data_fetcher import LiveDataFetcher
from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.position_rounder import PositionRounder
from jutsu_engine.live.dry_run_executor import DryRunExecutor

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
    token_path = project_root / 'token.json'

    try:
        schwab_client = auth.easy_client(
            api_key=os.getenv('SCHWAB_API_KEY'),
            app_secret=os.getenv('SCHWAB_API_SECRET'),
            callback_url='https://localhost:8182',
            token_path=str(token_path)
        )
        logger.info("Schwab client initialized successfully")
        return schwab_client
    except Exception as e:
        logger.error(f"Failed to initialize Schwab client: {e}")
        raise


def main():
    """
    Main daily dry-run execution workflow.

    This function orchestrates the complete trading workflow:
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
        # Step 1: Load configuration
        logger.info("Step 1: Loading configuration")
        config = load_config()

        # Extract config sections
        strategy_config = config['strategy']
        execution_config = config['execution']
        state_config = config['state']

        symbols = {
            'signal_symbol': strategy_config['universe']['signal_symbol'],
            'bull_symbol': strategy_config['universe']['bull_symbol'],
            'bond_signal': strategy_config['universe']['bond_signal'],
            'bull_bond': strategy_config['universe']['bull_bond'],
            'bear_bond': strategy_config['universe']['bear_bond']
        }

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
        dry_run_executor = DryRunExecutor(
            rebalance_threshold_pct=execution_config['rebalance_threshold_pct']
        )

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

        # Step 8: Run strategy (15:52:30)
        logger.info("Step 8: Running strategy (Hierarchical_Adaptive_v3_5b)")
        signals = strategy_runner.calculate_signals(market_data)
        logger.info(f"  Signals: Cell {signals['current_cell']}, Vol State {signals['vol_state']}")

        # Step 9: Fetch account positions (15:53:00)
        logger.info("Step 9: Fetching account positions")

        # Get account numbers dynamically
        accounts_response = schwab_client.get_account_numbers()
        if accounts_response.status_code != 200:
            logger.error(f"Account numbers API error: status {accounts_response.status_code}")
            return

        accounts = accounts_response.json()
        if not accounts:
            logger.error("No accounts found")
            return

        # Use first account hash
        account_hash = accounts[0]['hashValue']
        account_number = accounts[0].get('accountNumber', 'N/A')
        logger.info(f"  Using account: {account_number} (hash: {account_hash[:8]}...)")

        # Get account details with positions
        response = schwab_client.get_account(
            account_hash,
            fields=schwab_client.Account.Fields.POSITIONS
        )
        if response.status_code != 200:
            logger.error(f"Account details API error: status {response.status_code}")
            return

        account_info = response.json()

        # Extract account equity and positions
        account_equity = Decimal(str(account_info['securitiesAccount']['currentBalances']['liquidationValue']))
        logger.info(f"  Account Equity: ${account_equity:,.2f}")

        # Parse current positions from API
        api_positions = {}
        if 'positions' in account_info['securitiesAccount']:
            for pos in account_info['securitiesAccount']['positions']:
                symbol = pos['instrument']['symbol']
                qty = int(pos['longQuantity'])
                api_positions[symbol] = qty
        logger.info(f"  Current Positions: {api_positions}")

        # Load state and reconcile
        state = state_manager.load_state()
        state_positions = state.get('current_positions', {})

        # Check for first run (no state file or empty positions)
        is_first_run = not state_positions

        if is_first_run:
            logger.info("First run detected - initializing state from current API positions")
            logger.info(f"  API Positions: {api_positions}")
            current_positions = api_positions
        else:
            # Reconcile state with API (subsequent runs)
            discrepancies = state_manager.reconcile_with_account(
                state_positions,
                api_positions,
                threshold_pct=state_config['reconciliation_threshold_pct']
            )

            if discrepancies:
                logger.warning(f"Position drift detected: {discrepancies}")
                # Use API positions as source of truth
                current_positions = api_positions
            else:
                current_positions = state_positions

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

        # Step 12: Calculate rebalance diff (15:54:00)
        logger.info("Step 12: Calculating rebalance diff")
        orders, position_diffs = dry_run_executor.execute_dry_run(
            current_positions,
            target_positions,
            current_prices,
            account_equity
        )

        if orders:
            logger.info(f"  {len(orders)} hypothetical orders logged:")
            for order in orders:
                logger.info(f"    {order['action']} {order['qty']} {order['symbol']} @ ${order['price']:.2f}")
        else:
            logger.info("  No orders - portfolio already at target or below threshold")

        # Step 13: Save state (15:55:00)
        logger.info("Step 13: Saving state")
        state['vol_state'] = signals['vol_state']
        state['current_positions'] = target_positions  # Update to target (dry-run assumes filled)
        state['account_equity'] = float(account_equity)
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
        logger.info(f"Hypothetical Orders: {len(orders)}")
        logger.info(f"Cash Remainder: ${cash_amount:,.2f} ({cash_pct:.2f}%)")
        logger.info("Mode: DRY-RUN (no actual orders placed)")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Daily dry-run failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
