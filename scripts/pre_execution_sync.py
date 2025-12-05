#!/usr/bin/env python3
"""
Pre-Execution Data Sync Script

Purpose:
    Ensures local database has fresh market data before live trading execution.
    Scheduled to run at 15:44 EST (5 minutes before 15:49 execution).

PRD Compliance:
    - Validates data freshness for all strategy symbols
    - Auto-triggers `jutsu sync` if data is stale
    - Logs detailed freshness report for audit trail
    - Exits with appropriate code for monitoring (0=success, 1=failure)

Scheduling (cron example):
    # Run at 15:44 EST (20:44 UTC in winter, 19:44 UTC in summer)
    44 15 * * 1-5 /path/to/venv/bin/python /path/to/scripts/pre_execution_sync.py

Usage:
    python scripts/pre_execution_sync.py [--no-sync] [--symbols SYM1,SYM2]

Options:
    --no-sync     Check freshness only, don't trigger sync
    --symbols     Comma-separated list of symbols to check (default: all)
    --db-path     Path to database file (default: data/market_data.db)
    --verbose     Enable verbose logging
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from jutsu_engine.live.data_freshness import (
    DataFreshnessChecker,
    DataFreshnessError,
    SyncError
)
from jutsu_engine.live.market_calendar import is_trading_day

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/pre_execution_sync_{datetime.now():%Y%m%d}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('LIVE.PRE_EXECUTION_SYNC')


def main():
    """
    Pre-execution data freshness check and sync workflow.

    Exit Codes:
        0 - Success (data is fresh or sync succeeded)
        1 - Failure (data is stale and sync failed or disabled)
        2 - Skipped (not a trading day)
        3 - Error (exception during check)
    """
    parser = argparse.ArgumentParser(
        description='Pre-execution data freshness check and sync',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Standard check and auto-sync
    python scripts/pre_execution_sync.py

    # Check only, no sync
    python scripts/pre_execution_sync.py --no-sync

    # Check specific symbols
    python scripts/pre_execution_sync.py --symbols QQQ,TLT,TQQQ

    # Use custom database path
    python scripts/pre_execution_sync.py --db-path data/custom.db
        """
    )

    parser.add_argument(
        '--no-sync',
        action='store_true',
        help='Check freshness only, do not trigger sync'
    )

    parser.add_argument(
        '--symbols',
        type=str,
        default=None,
        help='Comma-separated list of symbols to check (default: all strategy symbols)'
    )

    parser.add_argument(
        '--db-path',
        type=str,
        default='data/market_data.db',
        help='Path to SQLite database (default: data/market_data.db)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Run even if not a trading day (for testing)'
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 80)
    logger.info("PRE-EXECUTION DATA SYNC - Starting")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 80)

    try:
        # Step 1: Check if trading day
        if not args.force and not is_trading_day():
            logger.info("Not a trading day - skipping freshness check")
            print("Not a trading day - skipping freshness check")
            return 2

        # Step 2: Initialize checker
        logger.info(f"Database: {args.db_path}")

        symbols = None
        if args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(',')]
            logger.info(f"Checking specific symbols: {symbols}")

        checker = DataFreshnessChecker(
            db_path=args.db_path,
            required_symbols=symbols
        )

        # Step 3: Check freshness (and optionally sync)
        auto_sync = not args.no_sync

        if auto_sync:
            logger.info("Auto-sync ENABLED - will sync if data is stale")
        else:
            logger.info("Auto-sync DISABLED - check only mode")

        success, details = checker.ensure_fresh_data(auto_sync=auto_sync)

        # Step 4: Generate and print report
        report = checker.generate_report(details)
        print("\n" + report)

        # Also log the report
        for line in report.split('\n'):
            logger.info(line)

        # Step 5: Cleanup
        checker.close()

        # Step 6: Return appropriate exit code
        if success:
            logger.info("PRE-EXECUTION DATA SYNC - SUCCESS")
            print("\nResult: SUCCESS - All data is fresh")
            return 0
        else:
            logger.warning("PRE-EXECUTION DATA SYNC - FAILED")
            print("\nResult: FAILED - Data is stale")
            return 1

    except DataFreshnessError as e:
        logger.error(f"Data freshness error: {e}")
        print(f"\nError: {e}")
        return 3

    except SyncError as e:
        logger.error(f"Sync error: {e}")
        print(f"\nSync Error: {e}")
        return 1

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\nUnexpected Error: {e}")
        return 3


if __name__ == '__main__':
    sys.exit(main())
