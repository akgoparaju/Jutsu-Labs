#!/usr/bin/env python3
"""
Emergency Exit Script

Immediately close ALL positions and move to 100% cash.
Manual script for emergency situations.

⚠️  WARNING: This script will:
    1. SELL ALL positions immediately (market orders)
    2. Move account to 100% CASH
    3. Update state.json to reflect empty positions
    4. Send notification alert

Usage:
    python scripts/emergency_exit.py [--confirm]

Options:
    --confirm    Required flag to confirm emergency exit
"""

import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from schwab import auth

from jutsu_engine.live.order_executor import OrderExecutor
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.alert_manager import AlertManager
from jutsu_engine.live.data_fetcher import DataFetcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/emergency_exit_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('LIVE.EMERGENCY_EXIT')


def load_config() -> dict:
    """Load configuration from YAML file."""
    config_path = project_root / 'config' / 'live_trading_config.yaml'

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    return config


def authenticate_schwab(config: dict):
    """Authenticate with Schwab API."""
    logger.info("Authenticating with Schwab API...")

    api_key = config['schwab']['api_key']
    api_secret = config['schwab']['api_secret']
    token_path = config['schwab']['token_path']

    schwab_client = auth.client_from_token_file(
        token_path=token_path,
        api_key=api_key,
        app_secret=api_secret
    )

    account_hash = config['schwab']['account_number']

    logger.info(f"Authentication successful: account={account_hash[:8]}...")
    return schwab_client, account_hash


def confirm_emergency_exit() -> bool:
    """
    Interactive confirmation for emergency exit.

    Returns:
        True if user confirms, False otherwise
    """
    print("\n" + "=" * 80)
    print("⚠️  EMERGENCY EXIT CONFIRMATION")
    print("=" * 80)
    print("\nThis will:")
    print("  1. SELL ALL positions immediately (market orders)")
    print("  2. Move account to 100% CASH")
    print("  3. Update state.json to empty positions")
    print("  4. Send alert notification")
    print("\n⚠️  This action cannot be undone!")
    print("=" * 80)

    response = input("\nType 'CONFIRM' to proceed: ")

    return response.strip().upper() == "CONFIRM"


def main():
    """Execute emergency exit workflow."""
    parser = argparse.ArgumentParser(description="Emergency exit - close all positions")
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Skip interactive confirmation'
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("EMERGENCY EXIT SCRIPT")
    logger.info("=" * 80)

    try:
        # Confirmation
        if not args.confirm:
            if not confirm_emergency_exit():
                logger.info("Emergency exit CANCELLED by user")
                print("\n❌ Emergency exit cancelled")
                return 0

        logger.info("\n⚠️  EMERGENCY EXIT CONFIRMED - Proceeding...")

        # Load configuration
        logger.info("\n[STEP 1] Loading configuration...")
        config = load_config()

        # Initialize components
        logger.info("\n[STEP 2] Initializing components...")
        alert_manager = AlertManager(config)
        state_manager = StateManager()

        # Authenticate
        logger.info("\n[STEP 3] Authenticating...")
        schwab_client, account_hash = authenticate_schwab(config)

        # Initialize trading components
        data_fetcher = DataFetcher(schwab_client, config)
        order_executor = OrderExecutor(schwab_client, account_hash, config)

        # Load current state
        logger.info("\n[STEP 4] Loading current state...")
        state = state_manager.load_state()
        current_positions = state.get('current_positions', {})

        if not current_positions:
            logger.info("No positions to close - account already 100% cash")
            alert_manager.send_info("Emergency exit: No positions to close")
            return 0

        logger.info(f"Current positions: {current_positions}")

        # Fetch current prices
        logger.info("\n[STEP 5] Fetching current market prices...")
        symbols = list(current_positions.keys())
        quotes = data_fetcher.fetch_current_quotes(symbols)
        current_prices = {
            symbol: Decimal(str(quote['lastPrice']))
            for symbol, quote in quotes.items()
        }

        # Build SELL orders for ALL positions
        logger.info("\n[STEP 6] Building SELL orders for all positions...")

        sell_diffs = {
            symbol: -quantity  # Negative = SELL
            for symbol, quantity in current_positions.items()
            if quantity > 0
        }

        logger.info(f"SELL orders: {sell_diffs}")

        # EXECUTE EMERGENCY EXIT
        logger.info("\n[STEP 7] ⚠️  EXECUTING EMERGENCY EXIT...")

        fills, fill_prices = order_executor.execute_rebalance(
            sell_diffs,
            current_prices,
            reason="EMERGENCY EXIT"
        )

        logger.info(f"Emergency exit complete: {len(fills)} fills")

        # Update state to 100% cash
        logger.info("\n[STEP 8] Updating state to 100% cash...")

        state['current_positions'] = {}  # Empty positions
        state['last_allocation'] = {'CASH': 1.0}  # 100% cash
        state['last_run'] = datetime.now(timezone.utc).isoformat()
        state['metadata']['emergency_exit'] = datetime.now(timezone.utc).isoformat()

        state_manager.save_state(state)

        logger.info("State updated: 100% CASH ✅")

        # Generate summary
        logger.info("\n[STEP 9] Generating summary...")

        total_value = sum(
            fill['quantity'] * fill['fill_price']
            for fill in fills
        )

        summary = f"""
EMERGENCY EXIT COMPLETE
=======================
Timestamp: {datetime.now()}
Positions Closed: {len(fills)}
Total Value: ${total_value:,.2f}

Fills:
{chr(10).join([f"  SOLD {fill['quantity']} {fill['symbol']} @ ${fill['fill_price']:.2f}" for fill in fills])}

Account Status: 100% CASH
        """

        logger.info(summary)

        # Send critical alert
        alert_manager.send_critical_alert(
            error="EMERGENCY EXIT EXECUTED",
            context=summary
        )

        logger.info("=" * 80)
        logger.info("✅ EMERGENCY EXIT SUCCESSFUL")
        logger.info("=" * 80)

        print("\n" + "=" * 80)
        print("✅ EMERGENCY EXIT SUCCESSFUL")
        print("=" * 80)
        print(summary)

        return 0

    except Exception as e:
        logger.error(f"Emergency exit failed: {e}", exc_info=True)

        try:
            alert_manager.send_critical_alert(
                error=f"EMERGENCY EXIT FAILED: {e}",
                context="Manual intervention required"
            )
        except:
            pass

        print(f"\n❌ EMERGENCY EXIT FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
