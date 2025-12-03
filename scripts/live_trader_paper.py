#!/usr/bin/env python3
"""
Live Trader - Paper Trading Script (Phase 2)

Main execution script for paper trading with real orders in paper account.
Runs daily at 15:50 EST via cron.

Usage:
    python scripts/live_trader_paper.py

Cron Entry:
    50 15 * * 1-5 cd /path/to/jutsu-labs && python3 scripts/live_trader_paper.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from schwab import auth, client

from jutsu_engine.live.data_fetcher import DataFetcher
from jutsu_engine.live.strategy_runner import StrategyRunner
from jutsu_engine.live.order_executor import OrderExecutor
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.position_rounder import PositionRounder
from jutsu_engine.live.market_calendar import MarketCalendar
from jutsu_engine.live.alert_manager import AlertManager
from jutsu_engine.live.exceptions import CriticalFailure

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/live_trading_{datetime.now().strftime("%Y-%m-%d")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('LIVE.TRADER_PAPER')


def load_config() -> dict:
    """Load configuration from YAML file."""
    config_path = project_root / 'config' / 'live_trading_config.yaml'

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    logger.info(f"Configuration loaded from {config_path}")
    return config


def authenticate_schwab(config: dict):
    """
    Authenticate with Schwab API.

    Returns:
        Tuple of (client, account_hash)
    """
    logger.info("Authenticating with Schwab API...")

    api_key = config['schwab']['api_key']
    api_secret = config['schwab']['api_secret']
    redirect_uri = config['schwab']['redirect_uri']
    token_path = config['schwab']['token_path']

    # Create authenticated client
    schwab_client = auth.client_from_token_file(
        token_path=token_path,
        api_key=api_key,
        app_secret=api_secret
    )

    account_hash = config['schwab']['account_number']

    logger.info(f"Authentication successful: account={account_hash[:8]}...")
    return schwab_client, account_hash


def main():
    """Main execution workflow for paper trading."""
    logger.info("=" * 80)
    logger.info("LIVE TRADER - PAPER TRADING MODE")
    logger.info("=" * 80)

    start_time = datetime.now(timezone.utc)

    try:
        # STEP 0: Load configuration
        logger.info("\n[STEP 0] Loading configuration...")
        config = load_config()

        # STEP 1: Initialize components
        logger.info("\n[STEP 1] Initializing components...")

        # Alert manager
        alert_manager = AlertManager(config)

        # Market calendar
        market_calendar = MarketCalendar()

        # Check if trading day
        is_trading_day = market_calendar.is_trading_day()

        if not is_trading_day:
            logger.info("Not a trading day - exiting")
            alert_manager.send_info("Skipped execution: Not a trading day")
            return 0

        logger.info("Trading day confirmed ✅")

        # STEP 2: Authenticate with Schwab API
        logger.info("\n[STEP 2] Authenticating with Schwab API...")
        schwab_client, account_hash = authenticate_schwab(config)

        # STEP 3: Initialize trading components
        logger.info("\n[STEP 3] Initializing trading components...")

        data_fetcher = DataFetcher(schwab_client, config)
        strategy_runner = StrategyRunner(config)
        order_executor = OrderExecutor(schwab_client, account_hash, config)
        state_manager = StateManager()

        # STEP 4: Fetch historical data
        logger.info("\n[STEP 4] Fetching historical market data...")

        universe = config['strategy']['universe']
        symbols = [
            universe['signal_symbol'],
            universe['bull_symbol'],
            universe['bond_signal'],
            universe['bull_bond'],
            universe['bear_bond']
        ]

        historical_data = data_fetcher.fetch_historical_bars(
            symbols,
            lookback_days=250
        )

        # STEP 5: Fetch current quotes
        logger.info("\n[STEP 5] Fetching current market quotes...")

        quotes = data_fetcher.fetch_current_quotes(symbols)
        current_prices = {
            symbol: Decimal(str(quote['lastPrice']))
            for symbol, quote in quotes.items()
        }

        logger.info(f"Current prices: {current_prices}")

        # STEP 6: Create synthetic daily bar
        logger.info("\n[STEP 6] Creating synthetic daily bar...")

        synthetic_bar = data_fetcher.create_synthetic_daily_bar(quotes)

        # STEP 7: Run strategy logic
        logger.info("\n[STEP 7] Running strategy logic...")

        # Load state
        state = state_manager.load_state()

        # Run strategy
        target_allocation = strategy_runner.run_strategy(
            historical_data=historical_data,
            current_bar=synthetic_bar,
            vol_state=state.get('vol_state', 0)
        )

        logger.info(f"Target allocation: {target_allocation}")

        # STEP 8: Fetch account equity
        logger.info("\n[STEP 8] Fetching account equity...")

        account_info = schwab_client.get_account(account_hash)
        account_data = account_info.json()
        account_equity = Decimal(
            str(account_data['securitiesAccount']['currentBalances']['liquidationValue'])
        )

        logger.info(f"Account equity: ${account_equity:,.2f}")

        # STEP 9: Convert weights to shares
        logger.info("\n[STEP 9] Converting allocation weights to shares...")

        target_shares = PositionRounder.convert_weights_to_shares(
            target_allocation,
            account_equity,
            current_prices
        )

        logger.info(f"Target shares: {target_shares}")

        # STEP 10: Calculate rebalance diff
        logger.info("\n[STEP 10] Calculating rebalance differences...")

        current_positions = state.get('current_positions', {})

        from jutsu_engine.live.dry_run_executor import DryRunExecutor
        dry_run_executor = DryRunExecutor()

        position_diffs = dry_run_executor.calculate_rebalance_diff(
            current_positions,
            target_shares
        )

        # STEP 11: Filter by threshold
        logger.info("\n[STEP 11] Filtering orders by threshold...")

        filtered_diffs = dry_run_executor.filter_by_threshold(
            position_diffs,
            current_positions,
            current_prices,
            account_equity
        )

        if not filtered_diffs:
            logger.info("No trades needed - portfolio within threshold ✅")
            alert_manager.send_info("No rebalance needed - portfolio at target")

            # Update state with current allocation
            state['last_run'] = datetime.now(timezone.utc).isoformat()
            state['account_equity'] = float(account_equity)
            state_manager.save_state(state)

            return 0

        # STEP 12: EXECUTE ORDERS (PAPER TRADING)
        logger.info("\n[STEP 12] EXECUTING ORDERS (PAPER ACCOUNT)...")

        fills, fill_prices = order_executor.execute_rebalance(
            filtered_diffs,
            current_prices,
            reason="Daily Rebalance"
        )

        logger.info(f"Execution complete: {len(fills)} fills")

        # STEP 13: Update state
        logger.info("\n[STEP 13] Updating state...")

        # Update positions from fills
        new_positions = current_positions.copy()

        for fill in fills:
            symbol = fill['symbol']
            if fill['action'] == 'BUY':
                new_positions[symbol] = new_positions.get(symbol, 0) + fill['quantity']
            else:  # SELL
                new_positions[symbol] = new_positions.get(symbol, 0) - fill['quantity']

        state['current_positions'] = new_positions
        state['last_allocation'] = target_allocation
        state['account_equity'] = float(account_equity)
        state['last_run'] = datetime.now(timezone.utc).isoformat()

        state_manager.save_state(state)

        logger.info("State updated successfully ✅")

        # STEP 14: Generate summary
        logger.info("\n[STEP 14] Execution summary...")

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        summary = f"""
Paper Trading Execution Complete
=================================
Date: {datetime.now().strftime('%Y-%m-%d')}
Duration: {duration:.1f} seconds
Fills: {len(fills)}
Account Equity: ${account_equity:,.2f}
Target Allocation: {target_allocation}
New Positions: {new_positions}

Fill Details:
{chr(10).join([f"  {fill['action']} {fill['quantity']} {fill['symbol']} @ ${fill['fill_price']:.2f}" for fill in fills])}
        """

        logger.info(summary)

        # Send success notification
        alert_manager.send_info(summary)

        logger.info("=" * 80)
        logger.info("PAPER TRADING EXECUTION SUCCESSFUL ✅")
        logger.info("=" * 80)

        return 0

    except CriticalFailure as e:
        logger.critical(f"CRITICAL FAILURE: {e}")

        try:
            alert_manager.send_critical_alert(
                error=str(e),
                context=f"Paper trading execution failed at {datetime.now()}"
            )
        except:
            pass  # Alert system also failed

        return 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)

        try:
            alert_manager.send_critical_alert(
                error=f"Unexpected error: {e}",
                context="Paper trading execution"
            )
        except:
            pass

        return 1


if __name__ == "__main__":
    sys.exit(main())
