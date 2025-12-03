#!/usr/bin/env python3
"""
One-time cleanup script to remove weekend-dated market data records.

This script addresses a data quality issue where weekend dates (Saturday/Sunday)
were incorrectly stored in the database from external data sources. Market data
should only exist for trading days (Monday-Friday).

Usage:
    python scripts/cleanup_weekend_data.py           # Dry-run (report only)
    python scripts/cleanup_weekend_data.py --execute  # Actually delete

Evidence of weekend data:
    Symbol   Total   Weekend    %
    ------   -----   -------   ----
    QQQ      6725      0       0.0% ✅
    TQQQ     3963    739      18.6% ❌
    PSQ      4896    916      18.7% ❌
    TLT      5877   1099      18.7% ❌
    TMF      4186    782      18.7% ❌
    TMV      8364    781       9.3% ❌

Author: Database Handler Agent
Date: 2025-12-01
Category: Data Quality / One-Time Maintenance
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from jutsu_engine.data.models import MarketData, Base
from jutsu_engine.utils.logging_config import get_data_logger

# Configure logging
logger = get_data_logger('CLEANUP')
logger.setLevel(logging.INFO)


def is_weekend(timestamp: datetime) -> bool:
    """
    Check if timestamp falls on a weekend.

    Args:
        timestamp: datetime to check

    Returns:
        True if Saturday (5) or Sunday (6), False otherwise
    """
    return timestamp.weekday() in (5, 6)


def analyze_weekend_data(session) -> Dict[str, Dict[str, int]]:
    """
    Analyze database to count weekend records per symbol.

    Args:
        session: SQLAlchemy session

    Returns:
        Dict mapping symbol to {'total': count, 'weekend': count}
    """
    logger.info("Analyzing database for weekend data...")

    # Get all unique symbols
    symbols = session.query(MarketData.symbol).distinct().all()
    symbol_list = [s[0] for s in symbols]

    logger.info(f"Found {len(symbol_list)} unique symbols in database")

    results = {}

    for symbol in symbol_list:
        # Count total records
        total = session.query(MarketData).filter(
            MarketData.symbol == symbol
        ).count()

        # Count weekend records
        all_bars = session.query(MarketData).filter(
            MarketData.symbol == symbol
        ).all()

        weekend_count = sum(1 for bar in all_bars if is_weekend(bar.timestamp))

        results[symbol] = {
            'total': total,
            'weekend': weekend_count
        }

        logger.debug(
            f"{symbol}: {total} total bars, {weekend_count} weekend bars "
            f"({weekend_count/total*100:.1f}%)"
        )

    return results


def print_analysis_report(analysis: Dict[str, Dict[str, int]]) -> None:
    """
    Print formatted analysis report.

    Args:
        analysis: Results from analyze_weekend_data()
    """
    print("\n" + "="*60)
    print("Weekend Data Analysis Report")
    print("="*60)
    print(f"\n{'Symbol':<10} {'Total':<10} {'Weekend':<10} {'Percentage':<10}")
    print("-" * 60)

    total_bars = 0
    total_weekend = 0

    # Sort by symbol for consistent output
    for symbol in sorted(analysis.keys()):
        data = analysis[symbol]
        total = data['total']
        weekend = data['weekend']
        percentage = (weekend / total * 100) if total > 0 else 0.0

        status = "✅" if weekend == 0 else "❌"

        print(f"{symbol:<10} {total:<10} {weekend:<10} {percentage:<9.1f}% {status}")

        total_bars += total
        total_weekend += weekend

    print("-" * 60)
    overall_pct = (total_weekend / total_bars * 100) if total_bars > 0 else 0.0
    print(f"{'TOTAL':<10} {total_bars:<10} {total_weekend:<10} {overall_pct:<9.1f}%")
    print("="*60)

    if total_weekend > 0:
        print(f"\n⚠️  Found {total_weekend:,} weekend records ({overall_pct:.1f}% of total)")
        print("   Weekend dates indicate data quality issues that should be removed.")
    else:
        print("\n✅ No weekend data found - database is clean!")


def delete_weekend_data(session, dry_run: bool = True) -> Dict[str, int]:
    """
    Delete weekend records from database.

    Args:
        session: SQLAlchemy session
        dry_run: If True, only report what would be deleted (don't actually delete)

    Returns:
        Dict mapping symbol to number of records deleted
    """
    if dry_run:
        logger.info("DRY RUN MODE - No records will be deleted")
    else:
        logger.warning("EXECUTE MODE - Weekend records will be PERMANENTLY deleted")

    # Get all unique symbols
    symbols = session.query(MarketData.symbol).distinct().all()
    symbol_list = [s[0] for s in symbols]

    deletion_counts = {}

    for symbol in symbol_list:
        # Query all bars for this symbol
        all_bars = session.query(MarketData).filter(
            MarketData.symbol == symbol
        ).all()

        # Identify weekend bars
        weekend_bars = [bar for bar in all_bars if is_weekend(bar.timestamp)]

        count = len(weekend_bars)
        deletion_counts[symbol] = count

        if count > 0:
            if dry_run:
                logger.info(f"[DRY RUN] Would delete {count} weekend bars for {symbol}")
            else:
                # Actually delete the records
                for bar in weekend_bars:
                    session.delete(bar)

                logger.info(f"[DELETED] {count} weekend bars for {symbol}")

    if not dry_run:
        # Commit the deletions
        session.commit()
        logger.warning("Changes committed to database")

    return deletion_counts


def print_deletion_summary(deletions: Dict[str, int], dry_run: bool) -> None:
    """
    Print formatted deletion summary.

    Args:
        deletions: Dict mapping symbol to deletion count
        dry_run: Whether this was a dry run
    """
    action = "Would delete" if dry_run else "Deleted"
    mode = "DRY RUN" if dry_run else "EXECUTED"

    print("\n" + "="*60)
    print(f"Deletion Summary ({mode})")
    print("="*60)

    total_deleted = 0

    for symbol in sorted(deletions.keys()):
        count = deletions[symbol]
        if count > 0:
            print(f"  {symbol:<10} {action} {count:,} weekend records")
            total_deleted += count

    print("-" * 60)
    print(f"  {'TOTAL':<10} {action} {total_deleted:,} weekend records")
    print("="*60)

    if dry_run and total_deleted > 0:
        print("\n💡 To actually delete these records, run with --execute flag:")
        print("   python scripts/cleanup_weekend_data.py --execute")
    elif not dry_run and total_deleted > 0:
        print(f"\n✅ Successfully removed {total_deleted:,} weekend records from database")
    elif total_deleted == 0:
        print("\n✅ No weekend records to delete - database is clean!")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Clean weekend-dated records from market data database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (default) - report what would be deleted
  python scripts/cleanup_weekend_data.py

  # Actually delete weekend records
  python scripts/cleanup_weekend_data.py --execute

  # Use custom database file
  python scripts/cleanup_weekend_data.py --db data/custom.db --execute
        """
    )

    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually delete records (default is dry-run)'
    )

    parser.add_argument(
        '--db',
        type=str,
        default='data/market_data.db',
        help='Path to database file (default: data/market_data.db)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Validate database file exists
    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"Database file not found: {db_path}")
        logger.error("Please verify the database path is correct")
        sys.exit(1)

    # Create database engine and session
    db_url = f"sqlite:///{db_path}"
    logger.info(f"Connecting to database: {db_path}")

    engine = create_engine(db_url, echo=args.verbose)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Phase 1: Analysis
        print("\n🔍 Phase 1: Analyzing database for weekend data...")
        analysis = analyze_weekend_data(session)
        print_analysis_report(analysis)

        # Phase 2: Deletion (or dry-run)
        total_weekend = sum(data['weekend'] for data in analysis.values())

        if total_weekend == 0:
            logger.info("No weekend data found - nothing to delete")
            return

        mode = "EXECUTE" if args.execute else "DRY RUN"
        print(f"\n🗑️  Phase 2: Deletion ({mode})...")

        if not args.execute:
            print("\n⚠️  Running in DRY RUN mode - no records will be deleted")
            print("   Use --execute flag to actually delete records\n")
        else:
            print("\n⚠️  WARNING: About to PERMANENTLY delete weekend records")
            print("   Press Ctrl+C within 3 seconds to cancel...\n")
            import time
            time.sleep(3)

        deletions = delete_weekend_data(session, dry_run=not args.execute)
        print_deletion_summary(deletions, dry_run=not args.execute)

        # Phase 3: Verification (if executed)
        if args.execute:
            print("\n✓ Phase 3: Verifying cleanup...")
            verification = analyze_weekend_data(session)
            remaining_weekend = sum(data['weekend'] for data in verification.values())

            if remaining_weekend == 0:
                print("✅ Verification passed - no weekend records remain")
            else:
                print(f"⚠️  WARNING: {remaining_weekend} weekend records still exist")
                logger.error("Cleanup may have failed - please investigate")

    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user")
        session.rollback()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        session.rollback()
        raise
    finally:
        session.close()
        logger.info("Database connection closed")


if __name__ == '__main__':
    main()
