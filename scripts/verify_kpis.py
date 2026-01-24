#!/usr/bin/env python3
"""
Verify KPI Calculations in daily_performance Table.

This script validates that backfilled KPIs are correct by:
1. Checking Sharpe ratio is reasonable (not -4!)
2. Verifying cumulative return matches equity change
3. Detecting data gaps and anomalies
4. Comparing incremental vs batch KPI calculations

Phase 4.4 of EOD Daily Performance Implementation.
Reference: claudedocs/eod_daily_performance_workflow.md

Usage:
    # Verify specific strategy
    python scripts/verify_kpis.py --strategy v3_5b

    # Verify with expected Sharpe
    python scripts/verify_kpis.py --strategy v3_5b --expected-sharpe 0.82

    # Verify all strategies
    python scripts/verify_kpis.py --all

    # Detailed output
    python scripts/verify_kpis.py --strategy v3_5b --verbose

    # Compare with batch recalculation
    python scripts/verify_kpis.py --strategy v3_5b --recalculate

Author: Claude Opus 4.5
Created: 2026-01-23
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, func, distinct
from sqlalchemy.orm import sessionmaker

from jutsu_engine.data.models import DailyPerformance, PerformanceSnapshot
from jutsu_engine.utils.kpi_calculations import (
    calculate_sharpe_ratio,
    calculate_all_kpis_batch,
)
from jutsu_engine.utils.trading_calendar import get_trading_days_between

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('VERIFY.KPIs')


class ValidationResult:
    """Structured validation result."""
    
    def __init__(self, strategy_id: str, mode: str):
        self.strategy_id = strategy_id
        self.mode = mode
        self.checks = []
        self.warnings = []
        self.errors = []
        self.metrics = {}
    
    def add_check(self, name: str, passed: bool, message: str):
        self.checks.append({'name': name, 'passed': passed, 'message': message})
        if not passed:
            self.errors.append(f"{name}: {message}")
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def is_valid(self) -> bool:
        return len(self.errors) == 0
    
    def summary(self) -> str:
        status = "✅ VALID" if self.is_valid() else "❌ FAILED"
        lines = [f"\n{self.strategy_id}/{self.mode}: {status}"]
        
        for check in self.checks:
            icon = "✓" if check['passed'] else "✗"
            lines.append(f"  {icon} {check['name']}: {check['message']}")
        
        if self.warnings:
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")
        
        return "\n".join(lines)


def get_database_url() -> str:
    """Get database URL from environment or config.

    Uses PostgreSQL connection from .env file with proper password encoding.
    """
    import os
    from urllib.parse import quote_plus
    from dotenv import load_dotenv

    load_dotenv()

    # Try full DATABASE_URL first
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        return db_url

    # Build from PostgreSQL parts (password needs URL encoding)
    host = os.environ.get('POSTGRES_HOST')
    if host:
        password = quote_plus(os.environ.get('POSTGRES_PASSWORD', ''))
        user = os.environ.get('POSTGRES_USER', 'jutsu')
        port = os.environ.get('POSTGRES_PORT', '5432')
        database = os.environ.get('POSTGRES_DATABASE', 'jutsu_labs')
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    # Fallback to centralized config utility
    try:
        from jutsu_engine.utils.config import get_database_url as get_db_url
        return get_db_url()
    except ImportError:
        pass

    raise ValueError("No database configuration found. Set POSTGRES_HOST in .env or DATABASE_URL environment variable.")


def get_session():
    """Create database session."""
    db_url = get_database_url()
    logger.info(f"Connecting to database: {db_url.split('@')[-1] if '@' in db_url else 'local'}")
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def verify_sharpe_ratio(
    result: ValidationResult,
    records: List[DailyPerformance],
    expected_sharpe: Optional[float] = None
) -> None:
    """Verify Sharpe ratio is reasonable."""
    if not records:
        result.add_check("Sharpe Ratio", False, "No records to validate")
        return
    
    latest = records[-1]
    sharpe = float(latest.sharpe_ratio) if latest.sharpe_ratio else None
    
    result.metrics['sharpe_ratio'] = sharpe
    
    if sharpe is None:
        result.add_check("Sharpe Ratio", False, "Sharpe ratio is NULL")
        return
    
    # Check for the known bug (-4 instead of ~0.82)
    if sharpe < -3:
        result.add_check(
            "Sharpe Ratio", False,
            f"Sharpe ratio {sharpe:.4f} is unreasonably low (bug indicator)"
        )
        return
    
    # Check against expected value
    if expected_sharpe is not None:
        diff = abs(sharpe - expected_sharpe)
        if diff > 0.1:
            result.add_check(
                "Sharpe Ratio", False,
                f"Got {sharpe:.4f}, expected ~{expected_sharpe:.2f} (diff: {diff:.4f})"
            )
        else:
            result.add_check(
                "Sharpe Ratio", True,
                f"{sharpe:.4f} matches expected ~{expected_sharpe:.2f}"
            )
    else:
        # Just check it's reasonable
        if -2 < sharpe < 5:
            result.add_check("Sharpe Ratio", True, f"{sharpe:.4f} is within reasonable range")
        else:
            result.add_check(
                "Sharpe Ratio", False,
                f"{sharpe:.4f} is outside reasonable range (-2 to 5)"
            )


def verify_cumulative_return(
    result: ValidationResult,
    records: List[DailyPerformance]
) -> None:
    """Verify cumulative return matches equity change."""
    if len(records) < 2:
        result.add_check("Cumulative Return", False, "Insufficient records")
        return
    
    first = records[0]
    last = records[-1]
    
    initial_equity = float(first.total_equity)
    final_equity = float(last.total_equity)
    
    # Calculate expected cumulative return
    expected = (final_equity - initial_equity) / initial_equity
    actual = float(last.cumulative_return) if last.cumulative_return else 0
    
    result.metrics['cumulative_return'] = actual
    result.metrics['expected_cumulative_return'] = expected
    
    diff = abs(expected - actual)
    
    if diff < 0.001:  # 0.1% tolerance
        result.add_check(
            "Cumulative Return", True,
            f"{actual:.4f} matches equity change ({expected:.4f})"
        )
    else:
        result.add_check(
            "Cumulative Return", False,
            f"Stored: {actual:.4f}, Expected: {expected:.4f} (diff: {diff:.4f})"
        )


def verify_data_gaps(
    result: ValidationResult,
    records: List[DailyPerformance]
) -> None:
    """Check for unexpected gaps in trading dates."""
    if len(records) < 2:
        result.add_check("Data Gaps", True, "Insufficient records to check gaps")
        return
    
    gap_count = 0
    large_gaps = []
    
    for i in range(1, len(records)):
        prev_date = records[i - 1].trading_date
        curr_date = records[i].trading_date
        
        try:
            trading_days = get_trading_days_between(prev_date, curr_date)
            days_between = len(trading_days) - 1  # Exclude start date
            
            if days_between > 1:
                gap_count += 1
                if days_between > 5:
                    large_gaps.append(f"{prev_date} -> {curr_date} ({days_between} days)")
        except Exception:
            # Fallback to calendar days
            calendar_days = (curr_date - prev_date).days
            if calendar_days > 4:  # More than a weekend + 1 day
                gap_count += 1
                if calendar_days > 10:
                    large_gaps.append(f"{prev_date} -> {curr_date} ({calendar_days} calendar days)")
    
    result.metrics['gap_count'] = gap_count
    
    if large_gaps:
        result.add_warning(f"Large gaps detected: {'; '.join(large_gaps)}")
    
    if gap_count > 10:
        result.add_check(
            "Data Gaps", False,
            f"{gap_count} gaps detected (>10 is concerning)"
        )
    else:
        result.add_check(
            "Data Gaps", True,
            f"{gap_count} gaps detected (acceptable)"
        )


def verify_high_water_mark(
    result: ValidationResult,
    records: List[DailyPerformance]
) -> None:
    """Verify high water mark is correctly maintained."""
    if not records:
        result.add_check("High Water Mark", False, "No records")
        return
    
    issues = 0
    max_hwm = 0
    
    for record in records:
        hwm = float(record.high_water_mark) if record.high_water_mark else 0
        equity = float(record.total_equity)
        
        # HWM should never be less than current equity (when at a peak)
        if hwm < equity * 0.999:  # 0.1% tolerance
            issues += 1
        
        # HWM should never decrease
        if hwm < max_hwm * 0.999:
            issues += 1
        
        max_hwm = max(max_hwm, hwm)
    
    if issues == 0:
        result.add_check("High Water Mark", True, "Correctly maintained")
    else:
        result.add_check(
            "High Water Mark", False,
            f"{issues} inconsistencies detected"
        )


def verify_incremental_state(
    result: ValidationResult,
    records: List[DailyPerformance]
) -> None:
    """Verify incremental KPI state is consistent."""
    if len(records) < 2:
        result.add_check("Incremental State", True, "Insufficient records")
        return
    
    issues = []
    
    # Check returns_count matches record position
    for i, record in enumerate(records):
        expected_count = i  # First day has count 0, second has 1, etc.
        actual_count = record.returns_count or 0
        
        if actual_count != expected_count and i > 0:  # Skip first day
            if abs(actual_count - expected_count) > 1:
                issues.append(f"Day {i}: returns_count={actual_count}, expected ~{expected_count}")
    
    # Check returns_sum is cumulative
    if records[-1].returns_sum:
        final_sum = float(records[-1].returns_sum)
        # Rough sanity check: sum shouldn't be absurdly large
        if abs(final_sum) > 100:  # 10000% cumulative returns is suspicious
            issues.append(f"returns_sum={final_sum:.4f} seems too large")
    
    if issues:
        result.add_check(
            "Incremental State", False,
            f"{len(issues)} issues: {issues[0]}" + ("..." if len(issues) > 1 else "")
        )
    else:
        result.add_check("Incremental State", True, "Consistent")


def verify_with_recalculation(
    result: ValidationResult,
    records: List[DailyPerformance]
) -> None:
    """Recalculate KPIs from equity series and compare."""
    if len(records) < 10:
        result.add_check("Recalculation", True, "Too few records for meaningful comparison")
        return
    
    # Extract equity series
    equities = [float(r.total_equity) for r in records]
    initial_capital = equities[0]
    
    # Batch recalculate
    batch_kpis = calculate_all_kpis_batch(equities, initial_capital)
    
    # Compare Sharpe
    stored_sharpe = float(records[-1].sharpe_ratio) if records[-1].sharpe_ratio else None
    batch_sharpe = batch_kpis.get('sharpe_ratio')
    
    result.metrics['batch_sharpe'] = batch_sharpe
    
    if stored_sharpe is not None and batch_sharpe is not None:
        diff = abs(stored_sharpe - batch_sharpe)
        if diff < 0.01:  # Very close tolerance
            result.add_check(
                "Recalculation", True,
                f"Stored {stored_sharpe:.4f} ≈ Batch {batch_sharpe:.4f}"
            )
        elif diff < 0.05:
            result.add_check(
                "Recalculation", True,
                f"Stored {stored_sharpe:.4f} ~ Batch {batch_sharpe:.4f} (within tolerance)"
            )
        else:
            result.add_check(
                "Recalculation", False,
                f"Stored {stored_sharpe:.4f} ≠ Batch {batch_sharpe:.4f} (diff: {diff:.4f})"
            )
    else:
        result.add_check("Recalculation", False, "Missing Sharpe values for comparison")


def verify_strategy(
    session,
    strategy_id: str,
    mode: str,
    expected_sharpe: Optional[float] = None,
    recalculate: bool = False,
    verbose: bool = False
) -> ValidationResult:
    """
    Run all verification checks for a strategy.
    
    Args:
        session: SQLAlchemy session
        strategy_id: Strategy ID to verify
        mode: Trading mode
        expected_sharpe: Expected Sharpe ratio (optional)
        recalculate: Whether to recalculate KPIs for comparison
        verbose: Verbose output
    
    Returns:
        ValidationResult with all check results
    """
    result = ValidationResult(strategy_id, mode)
    
    # Fetch records
    records = session.query(DailyPerformance).filter(
        DailyPerformance.entity_id == strategy_id,
        DailyPerformance.entity_type == 'strategy',
        DailyPerformance.mode == mode
    ).order_by(DailyPerformance.trading_date).all()
    
    if not records:
        result.add_check("Data Exists", False, "No records found in daily_performance")
        return result
    
    result.add_check("Data Exists", True, f"Found {len(records)} records")
    result.metrics['record_count'] = len(records)
    result.metrics['date_range'] = f"{records[0].trading_date} to {records[-1].trading_date}"
    
    # Run checks
    verify_sharpe_ratio(result, records, expected_sharpe)
    verify_cumulative_return(result, records)
    verify_data_gaps(result, records)
    verify_high_water_mark(result, records)
    verify_incremental_state(result, records)
    
    if recalculate:
        verify_with_recalculation(result, records)
    
    if verbose:
        logger.info(f"Metrics: {json.dumps(result.metrics, indent=2, default=str)}")
    
    return result


def get_all_strategies(session) -> List[tuple]:
    """Get all unique strategies from daily_performance."""
    result = session.query(
        distinct(DailyPerformance.entity_id),
        DailyPerformance.mode
    ).filter(
        DailyPerformance.entity_type == 'strategy'
    ).group_by(
        DailyPerformance.entity_id,
        DailyPerformance.mode
    ).all()
    
    return [(row[0], row[1]) for row in result]


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Verify KPI calculations in daily_performance table',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        '--all',
        action='store_true',
        help='Verify all strategies'
    )
    target_group.add_argument(
        '--strategy',
        type=str,
        help='Specific strategy ID'
    )
    
    parser.add_argument(
        '--mode',
        type=str,
        default='offline_mock',
        help='Trading mode (default: offline_mock)'
    )
    parser.add_argument(
        '--expected-sharpe',
        type=float,
        help='Expected Sharpe ratio for comparison'
    )
    parser.add_argument(
        '--recalculate',
        action='store_true',
        help='Recalculate KPIs from equity and compare'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Specific date to check (YYYY-MM-DD)'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    session, engine = get_session()
    
    try:
        results = []
        
        if args.all:
            strategies = get_all_strategies(session)
            if not strategies:
                logger.warning("No strategies found in daily_performance")
                return
        else:
            strategies = [(args.strategy, args.mode)]
        
        for strategy_id, mode in strategies:
            result = verify_strategy(
                session,
                strategy_id,
                mode,
                args.expected_sharpe,
                args.recalculate,
                args.verbose
            )
            results.append(result)
            print(result.summary())
        
        # Overall summary
        print("\n" + "=" * 60)
        print("VERIFICATION SUMMARY")
        print("=" * 60)
        
        valid_count = sum(1 for r in results if r.is_valid())
        total_count = len(results)
        
        print(f"Strategies verified: {total_count}")
        print(f"Valid: {valid_count}")
        print(f"Failed: {total_count - valid_count}")
        
        if valid_count == total_count:
            print("\n✅ ALL CHECKS PASSED")
        else:
            print("\n❌ SOME CHECKS FAILED")
            for r in results:
                if not r.is_valid():
                    print(f"  - {r.strategy_id}/{r.mode}")
        
        print("=" * 60)
        
        # Exit with error code if any failed
        sys.exit(0 if valid_count == total_count else 1)
        
    finally:
        session.close()


if __name__ == '__main__':
    main()
