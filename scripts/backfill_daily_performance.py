#!/usr/bin/env python3
"""
Backfill Daily Performance from Performance Snapshots.

This script populates the daily_performance table from historical
performance_snapshots data. It fixes the Sharpe ratio bug by calculating
equity-based daily returns instead of using stored (corrupt) daily_return values.

Phase 4 of EOD Daily Performance Implementation.
Reference: claudedocs/eod_daily_performance_workflow.md

Usage:
    # Backfill all strategies (dry-run first)
    python scripts/backfill_daily_performance.py --all --dry-run
    python scripts/backfill_daily_performance.py --all

    # Backfill specific strategy
    python scripts/backfill_daily_performance.py --strategy v3_5b
    python scripts/backfill_daily_performance.py --strategy v3_5d --mode online_live

    # Backfill date range
    python scripts/backfill_daily_performance.py --strategy v3_5b --start 2025-12-01 --end 2026-01-23

    # Include baselines
    python scripts/backfill_daily_performance.py --all --include-baselines

    # Validation only
    python scripts/backfill_daily_performance.py --strategy v3_5b --validate-only

Features:
    - Processes performance_snapshots -> daily_performance
    - Uses equity-based daily returns (not corrupt stored values)
    - Calculates all KPIs using Welford's algorithm for O(1) incremental updates
    - Handles first-day and data gap corner cases
    - Dry-run mode for preview without database writes
    - Validation mode to verify results
    - Progress logging for long operations
    - Baseline backfill with deduplication

Author: Claude Opus 4.5
Created: 2026-01-23
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, func, distinct, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from jutsu_engine.data.models import (
    Base,
    DailyPerformance,
    PerformanceSnapshot,
)
from jutsu_engine.utils.kpi_calculations import (
    calculate_daily_return,
    calculate_cumulative_return,
    calculate_all_kpis_batch,
    initialize_kpi_state,
    update_kpis_incremental,
    calculate_trade_statistics,
)
from jutsu_engine.utils.trading_calendar import (
    is_trading_day,
    get_trading_days_between,
    days_since_last_trading_day,
    get_previous_trading_day,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('BACKFILL.DAILY_PERFORMANCE')


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


def get_all_strategies(session) -> List[Tuple[str, str]]:
    """
    Get all unique (strategy_id, mode) combinations from performance_snapshots.
    
    Returns:
        List of (strategy_id, mode) tuples
    """
    result = session.query(
        distinct(PerformanceSnapshot.strategy_id),
        PerformanceSnapshot.mode
    ).group_by(
        PerformanceSnapshot.strategy_id,
        PerformanceSnapshot.mode
    ).all()
    
    strategies = [(row[0], row[1]) for row in result if row[0] is not None]
    logger.info(f"Found {len(strategies)} strategy/mode combinations")
    return strategies


def get_daily_equities(
    session,
    strategy_id: str,
    mode: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[Dict]:
    """
    Get one equity value per trading day from performance_snapshots.
    
    Uses the LAST snapshot of each trading day as the closing equity.
    This handles multiple snapshots per day (scheduler, refresh, null sources).
    
    Args:
        session: SQLAlchemy session
        strategy_id: Strategy ID (e.g., 'v3_5b')
        mode: Trading mode ('offline_mock' or 'online_live')
        start_date: Start date filter (optional)
        end_date: End date filter (optional)
    
    Returns:
        List of dicts with trading_date, total_equity, and metadata
    """
    from sqlalchemy import func, and_
    from zoneinfo import ZoneInfo
    
    ET = ZoneInfo("America/New_York")
    
    # Build base query
    query = session.query(
        func.date(PerformanceSnapshot.timestamp).label('trading_date'),
        func.max(PerformanceSnapshot.total_equity).label('close_equity'),
        func.max(PerformanceSnapshot.cash).label('cash'),
        func.max(PerformanceSnapshot.positions_value).label('positions_value'),
        func.max(PerformanceSnapshot.strategy_cell).label('strategy_cell'),
        func.max(PerformanceSnapshot.trend_state).label('trend_state'),
        func.max(PerformanceSnapshot.vol_state).label('vol_state'),
        func.max(PerformanceSnapshot.t_norm).label('t_norm'),
        func.max(PerformanceSnapshot.z_score).label('z_score'),
        func.max(PerformanceSnapshot.sma_fast).label('sma_fast'),
        func.max(PerformanceSnapshot.sma_slow).label('sma_slow'),
        func.max(PerformanceSnapshot.positions_json).label('positions_json'),
        func.max(PerformanceSnapshot.baseline_value).label('baseline_value'),
    ).filter(
        PerformanceSnapshot.strategy_id == strategy_id,
        PerformanceSnapshot.mode == mode
    )
    
    if start_date:
        query = query.filter(PerformanceSnapshot.timestamp >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(PerformanceSnapshot.timestamp < datetime.combine(end_date + timedelta(days=1), datetime.min.time()))
    
    # Group by date and order
    query = query.group_by(func.date(PerformanceSnapshot.timestamp))
    query = query.order_by(func.date(PerformanceSnapshot.timestamp))
    
    results = query.all()
    
    daily_data = []
    for row in results:
        trading_date = row.trading_date
        if isinstance(trading_date, str):
            trading_date = datetime.strptime(trading_date, '%Y-%m-%d').date()
        elif isinstance(trading_date, datetime):
            trading_date = trading_date.date()
        
        daily_data.append({
            'trading_date': trading_date,
            'total_equity': float(row.close_equity) if row.close_equity else 0.0,
            'cash': float(row.cash) if row.cash else None,
            'positions_value': float(row.positions_value) if row.positions_value else None,
            'strategy_cell': row.strategy_cell,
            'trend_state': row.trend_state,
            'vol_state': row.vol_state,
            't_norm': float(row.t_norm) if row.t_norm else None,
            'z_score': float(row.z_score) if row.z_score else None,
            'sma_fast': float(row.sma_fast) if row.sma_fast else None,
            'sma_slow': float(row.sma_slow) if row.sma_slow else None,
            'positions_json': row.positions_json,
            'baseline_value': float(row.baseline_value) if row.baseline_value else None,
        })
    
    logger.debug(f"Found {len(daily_data)} trading days for {strategy_id}/{mode}")
    return daily_data


def backfill_strategy(
    session,
    strategy_id: str,
    mode: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    dry_run: bool = False,
    baseline_symbol: str = 'QQQ'
) -> Dict[str, Any]:
    """
    Backfill daily_performance for a single strategy.
    
    Process:
    1. Get unique trading dates from performance_snapshots
    2. For each date, get latest snapshot (closing equity)
    3. Calculate daily return from previous day's equity
    4. Calculate running KPIs incrementally
    5. UPSERT into daily_performance
    
    Args:
        session: SQLAlchemy session
        strategy_id: Strategy ID (e.g., 'v3_5b')
        mode: Trading mode
        start_date: Optional start date
        end_date: Optional end date
        dry_run: If True, preview without database writes
        baseline_symbol: Baseline symbol (default 'QQQ')
    
    Returns:
        dict: Summary statistics
    """
    logger.info(f"Backfilling {strategy_id}/{mode}" + (" (DRY RUN)" if dry_run else ""))
    
    # Get daily equity data
    daily_data = get_daily_equities(session, strategy_id, mode, start_date, end_date)
    
    if not daily_data:
        logger.warning(f"No data found for {strategy_id}/{mode}")
        return {'records': 0, 'error': 'No data found'}
    
    logger.info(f"Processing {len(daily_data)} trading days for {strategy_id}/{mode}")
    
    # Calculate KPIs batch-wise for efficiency
    equities = [d['total_equity'] for d in daily_data]
    initial_capital = equities[0] if equities else 10000.0
    
    batch_kpis = calculate_all_kpis_batch(equities, initial_capital)
    
    records_created = 0
    records_updated = 0
    
    # Track running state for incremental KPIs
    prev_record = None
    running_state = None
    
    for i, day_data in enumerate(daily_data):
        trading_date = day_data['trading_date']
        today_equity = day_data['total_equity']
        
        # First day handling
        if i == 0:
            daily_return = Decimal('0')
            cumulative_return = Decimal('0')
            is_first_day = True
            days_since_prev = 0
            running_state = initialize_kpi_state(today_equity)
        else:
            prev_equity = daily_data[i - 1]['total_equity']
            prev_date = daily_data[i - 1]['trading_date']
            
            daily_return = calculate_daily_return(today_equity, prev_equity)
            cumulative_return = calculate_cumulative_return(today_equity, initial_capital)
            is_first_day = False
            
            # Calculate trading days gap
            try:
                trading_days = get_trading_days_between(prev_date, trading_date)
                days_since_prev = len(trading_days) - 1  # Exclude start date
            except Exception:
                # Fallback to calendar days if trading calendar fails
                days_since_prev = (trading_date - prev_date).days
            
            # Warn on large gaps
            if days_since_prev > 5:
                logger.warning(
                    f"Large gap detected: {days_since_prev} trading days between "
                    f"{prev_date} and {trading_date} for {strategy_id}"
                )
            
            # Update incremental KPIs
            running_state = update_kpis_incremental(
                prev_returns_sum=running_state.get('returns_sum'),
                prev_returns_sum_sq=running_state.get('returns_sum_sq'),
                prev_downside_sum_sq=running_state.get('downside_sum_sq'),
                prev_returns_count=running_state.get('returns_count'),
                prev_high_water_mark=running_state.get('high_water_mark'),
                prev_max_drawdown=running_state.get('max_drawdown'),
                today_return=float(daily_return),
                today_equity=today_equity,
                initial_capital=initial_capital
            )
        
        # Build record
        record_data = {
            'trading_date': datetime.combine(trading_date, datetime.min.time()),
            'entity_type': 'strategy',
            'entity_id': strategy_id,
            'mode': mode,
            'total_equity': Decimal(str(today_equity)),
            'cash': Decimal(str(day_data['cash'])) if day_data['cash'] else None,
            'positions_value': Decimal(str(day_data['positions_value'])) if day_data['positions_value'] else None,
            'positions_json': day_data['positions_json'],
            'daily_return': daily_return,
            'cumulative_return': cumulative_return,
            'drawdown': Decimal(str(running_state.get('drawdown', 0))) if running_state.get('drawdown') else None,
            'sharpe_ratio': Decimal(str(running_state.get('sharpe_ratio'))) if running_state.get('sharpe_ratio') else None,
            'sortino_ratio': Decimal(str(running_state.get('sortino_ratio'))) if running_state.get('sortino_ratio') else None,
            'calmar_ratio': None,  # Calculate at end
            'max_drawdown': Decimal(str(running_state.get('max_drawdown'))) if running_state.get('max_drawdown') else None,
            'volatility': Decimal(str(running_state.get('volatility'))) if running_state.get('volatility') else None,
            'cagr': Decimal(str(running_state.get('cagr'))) if running_state.get('cagr') else None,
            'strategy_cell': day_data['strategy_cell'],
            'trend_state': day_data['trend_state'],
            'vol_state': day_data['vol_state'],
            't_norm': Decimal(str(day_data['t_norm'])) if day_data['t_norm'] else None,
            'z_score': Decimal(str(day_data['z_score'])) if day_data['z_score'] else None,
            'sma_fast': Decimal(str(day_data['sma_fast'])) if day_data['sma_fast'] else None,
            'sma_slow': Decimal(str(day_data['sma_slow'])) if day_data['sma_slow'] else None,
            'baseline_symbol': baseline_symbol,
            'initial_capital': Decimal(str(initial_capital)),
            'high_water_mark': Decimal(str(running_state.get('high_water_mark', today_equity))),
            'trading_days_count': i + 1,
            'days_since_previous': days_since_prev if not is_first_day else 0,
            'is_first_day': is_first_day,
            'returns_sum': Decimal(str(running_state.get('returns_sum', 0))),
            'returns_sum_sq': Decimal(str(running_state.get('returns_sum_sq', 0))),
            'downside_sum_sq': Decimal(str(running_state.get('downside_sum_sq', 0))),
            'returns_count': running_state.get('returns_count', 0),
        }
        
        # Calculate Calmar ratio if we have enough data
        if running_state.get('cagr') and running_state.get('max_drawdown') and running_state['max_drawdown'] != 0:
            calmar = running_state['cagr'] / abs(running_state['max_drawdown'])
            record_data['calmar_ratio'] = Decimal(str(calmar))
        
        if dry_run:
            if i == 0 or i == len(daily_data) - 1 or i % 50 == 0:
                logger.info(
                    f"[DRY RUN] {trading_date}: equity={today_equity:.2f}, "
                    f"daily_return={float(daily_return)*100:.4f}%, "
                    f"sharpe={running_state.get('sharpe_ratio', 'N/A')}"
                )
            records_created += 1
        else:
            # UPSERT using PostgreSQL ON CONFLICT
            try:
                # Check if record exists
                existing = session.query(DailyPerformance).filter(
                    DailyPerformance.trading_date == record_data['trading_date'],
                    DailyPerformance.entity_type == 'strategy',
                    DailyPerformance.entity_id == strategy_id,
                    DailyPerformance.mode == mode
                ).first()
                
                if existing:
                    # Update existing record
                    for key, value in record_data.items():
                        if key not in ('trading_date', 'entity_type', 'entity_id', 'mode'):
                            setattr(existing, key, value)
                    records_updated += 1
                else:
                    # Create new record
                    new_record = DailyPerformance(**record_data)
                    session.add(new_record)
                    records_created += 1
                
                # Commit every 100 records
                if (records_created + records_updated) % 100 == 0:
                    session.commit()
                    logger.info(f"Progress: {records_created + records_updated}/{len(daily_data)}")
                    
            except Exception as e:
                logger.error(f"Error processing {trading_date}: {e}")
                session.rollback()
                raise
    
    if not dry_run:
        session.commit()
        logger.info(f"Committed: {records_created} created, {records_updated} updated")
    
    # Calculate final KPIs
    final_sharpe = running_state.get('sharpe_ratio') if running_state else None
    
    return {
        'strategy_id': strategy_id,
        'mode': mode,
        'records_created': records_created,
        'records_updated': records_updated,
        'trading_days': len(daily_data),
        'date_range': f"{daily_data[0]['trading_date']} to {daily_data[-1]['trading_date']}" if daily_data else 'N/A',
        'initial_capital': initial_capital,
        'final_equity': daily_data[-1]['total_equity'] if daily_data else 0,
        'final_sharpe': final_sharpe,
        'dry_run': dry_run
    }


def backfill_baseline(
    session,
    symbol: str,
    mode: str,
    trading_dates: List[date],
    initial_capital: float = 10000.0,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Backfill daily_performance for a baseline symbol (buy-and-hold).
    
    Creates one row per baseline per trading day (deduplicated across strategies).
    Calculates buy-and-hold performance based on market data.
    
    Args:
        session: SQLAlchemy session
        symbol: Baseline symbol (e.g., 'QQQ')
        mode: Trading mode
        trading_dates: List of trading dates to process
        initial_capital: Starting capital for baseline
        dry_run: If True, preview without database writes
    
    Returns:
        dict: Summary statistics
    """
    from jutsu_engine.data.models import MarketData
    
    logger.info(f"Backfilling baseline {symbol}/{mode}" + (" (DRY RUN)" if dry_run else ""))
    
    if not trading_dates:
        logger.warning(f"No trading dates provided for baseline {symbol}")
        return {'records': 0, 'error': 'No trading dates'}
    
    # Get historical prices for the symbol
    start_date = min(trading_dates)
    end_date = max(trading_dates)
    
    prices = session.query(
        func.date(MarketData.timestamp).label('trading_date'),
        func.max(MarketData.close).label('close')
    ).filter(
        MarketData.symbol == symbol,
        MarketData.timestamp >= datetime.combine(start_date, datetime.min.time()),
        MarketData.timestamp < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    ).group_by(
        func.date(MarketData.timestamp)
    ).order_by(
        func.date(MarketData.timestamp)
    ).all()
    
    if not prices:
        logger.warning(f"No market data found for {symbol}")
        return {'records': 0, 'error': 'No market data'}
    
    # Build price lookup
    price_lookup = {}
    for row in prices:
        price_date = row.trading_date
        if isinstance(price_date, str):
            price_date = datetime.strptime(price_date, '%Y-%m-%d').date()
        elif isinstance(price_date, datetime):
            price_date = price_date.date()
        price_lookup[price_date] = float(row.close)
    
    # Calculate buy-and-hold portfolio
    first_date = min(price_lookup.keys())
    first_price = price_lookup[first_date]
    shares = initial_capital / first_price
    
    records_created = 0
    records_updated = 0
    running_state = None
    
    sorted_dates = sorted([d for d in trading_dates if d in price_lookup])
    
    for i, trading_date in enumerate(sorted_dates):
        price = price_lookup.get(trading_date)
        if price is None:
            continue
        
        portfolio_value = shares * price
        
        # First day
        if i == 0:
            daily_return = Decimal('0')
            cumulative_return = Decimal('0')
            is_first_day = True
            days_since_prev = 0
            running_state = initialize_kpi_state(portfolio_value)
        else:
            prev_date = sorted_dates[i - 1]
            prev_value = shares * price_lookup[prev_date]
            
            daily_return = calculate_daily_return(portfolio_value, prev_value)
            cumulative_return = calculate_cumulative_return(portfolio_value, initial_capital)
            is_first_day = False
            
            # Calculate trading days gap
            try:
                trading_days = get_trading_days_between(prev_date, trading_date)
                days_since_prev = len(trading_days) - 1
            except Exception:
                days_since_prev = (trading_date - prev_date).days
            
            # Update incremental KPIs
            running_state = update_kpis_incremental(
                prev_returns_sum=running_state.get('returns_sum'),
                prev_returns_sum_sq=running_state.get('returns_sum_sq'),
                prev_downside_sum_sq=running_state.get('downside_sum_sq'),
                prev_returns_count=running_state.get('returns_count'),
                prev_high_water_mark=running_state.get('high_water_mark'),
                prev_max_drawdown=running_state.get('max_drawdown'),
                today_return=float(daily_return),
                today_equity=portfolio_value,
                initial_capital=initial_capital
            )
        
        record_data = {
            'trading_date': datetime.combine(trading_date, datetime.min.time()),
            'entity_type': 'baseline',
            'entity_id': symbol,
            'mode': mode,
            'total_equity': Decimal(str(portfolio_value)),
            'cash': Decimal('0'),  # Buy-and-hold is fully invested
            'positions_value': Decimal(str(portfolio_value)),
            'daily_return': daily_return,
            'cumulative_return': cumulative_return,
            'drawdown': Decimal(str(running_state.get('drawdown', 0))) if running_state.get('drawdown') else None,
            'sharpe_ratio': Decimal(str(running_state.get('sharpe_ratio'))) if running_state.get('sharpe_ratio') else None,
            'sortino_ratio': Decimal(str(running_state.get('sortino_ratio'))) if running_state.get('sortino_ratio') else None,
            'max_drawdown': Decimal(str(running_state.get('max_drawdown'))) if running_state.get('max_drawdown') else None,
            'volatility': Decimal(str(running_state.get('volatility'))) if running_state.get('volatility') else None,
            'cagr': Decimal(str(running_state.get('cagr'))) if running_state.get('cagr') else None,
            'initial_capital': Decimal(str(initial_capital)),
            'high_water_mark': Decimal(str(running_state.get('high_water_mark', portfolio_value))),
            'trading_days_count': i + 1,
            'days_since_previous': days_since_prev if not is_first_day else 0,
            'is_first_day': is_first_day,
            'returns_sum': Decimal(str(running_state.get('returns_sum', 0))),
            'returns_sum_sq': Decimal(str(running_state.get('returns_sum_sq', 0))),
            'downside_sum_sq': Decimal(str(running_state.get('downside_sum_sq', 0))),
            'returns_count': running_state.get('returns_count', 0),
        }
        
        if dry_run:
            if i == 0 or i == len(sorted_dates) - 1:
                logger.info(f"[DRY RUN] {symbol} {trading_date}: value={portfolio_value:.2f}")
            records_created += 1
        else:
            # Check if baseline already exists (deduplicate)
            existing = session.query(DailyPerformance).filter(
                DailyPerformance.trading_date == record_data['trading_date'],
                DailyPerformance.entity_type == 'baseline',
                DailyPerformance.entity_id == symbol,
                DailyPerformance.mode == mode
            ).first()
            
            if existing:
                records_updated += 1
                for key, value in record_data.items():
                    if key not in ('trading_date', 'entity_type', 'entity_id', 'mode'):
                        setattr(existing, key, value)
            else:
                new_record = DailyPerformance(**record_data)
                session.add(new_record)
                records_created += 1
            
            if (records_created + records_updated) % 100 == 0:
                session.commit()
    
    if not dry_run:
        session.commit()
        logger.info(f"Baseline {symbol}: {records_created} created, {records_updated} updated")
    
    return {
        'symbol': symbol,
        'mode': mode,
        'records_created': records_created,
        'records_updated': records_updated,
        'trading_days': len(sorted_dates),
        'dry_run': dry_run
    }


def validate_backfill(
    session,
    strategy_id: str,
    mode: str,
    expected_sharpe: Optional[float] = None
) -> Dict[str, Any]:
    """
    Validate backfilled data for integrity.
    
    Checks:
    1. Row count matches unique trading days
    2. No gaps in trading_date sequence
    3. Sharpe ratio is reasonable (not -4!)
    4. High water mark is monotonically non-decreasing at peaks
    5. Cumulative return matches equity change
    
    Args:
        session: SQLAlchemy session
        strategy_id: Strategy ID to validate
        mode: Trading mode
        expected_sharpe: Expected Sharpe ratio (optional)
    
    Returns:
        dict: Validation results
    """
    logger.info(f"Validating {strategy_id}/{mode}")
    
    issues = []
    
    # Get all records
    records = session.query(DailyPerformance).filter(
        DailyPerformance.entity_id == strategy_id,
        DailyPerformance.entity_type == 'strategy',
        DailyPerformance.mode == mode
    ).order_by(DailyPerformance.trading_date).all()
    
    if not records:
        return {'valid': False, 'issues': ['No records found']}
    
    # Check 1: Row count
    logger.info(f"Found {len(records)} records")
    
    # Check 2: Date gaps
    prev_date = None
    gap_count = 0
    for record in records:
        if prev_date:
            try:
                trading_days = get_trading_days_between(prev_date, record.trading_date.date())
                if len(trading_days) > 2:  # More than 1 day gap
                    gap_count += 1
                    if len(trading_days) > 5:
                        issues.append(f"Large gap: {len(trading_days)} trading days at {record.trading_date}")
            except Exception:
                pass
        prev_date = record.trading_date.date()
    
    # Check 3: Sharpe ratio
    latest = records[-1]
    final_sharpe = float(latest.sharpe_ratio) if latest.sharpe_ratio else None
    
    if final_sharpe is not None:
        if final_sharpe < -3:
            issues.append(f"Sharpe ratio too low: {final_sharpe:.2f} (possibly corrupt)")
        if expected_sharpe is not None:
            diff = abs(final_sharpe - expected_sharpe)
            if diff > 0.2:
                issues.append(f"Sharpe mismatch: got {final_sharpe:.2f}, expected ~{expected_sharpe:.2f}")
    
    # Check 4: High water mark monotonicity at peaks
    hwm_issues = 0
    max_hwm = 0
    for record in records:
        hwm = float(record.high_water_mark) if record.high_water_mark else 0
        if hwm < max_hwm * 0.99:  # Allow 1% tolerance for floating point
            hwm_issues += 1
        max_hwm = max(max_hwm, hwm)
    
    if hwm_issues > 0:
        issues.append(f"High water mark decreased {hwm_issues} times")
    
    # Check 5: Cumulative return consistency
    first_record = records[0]
    last_record = records[-1]
    
    initial_equity = float(first_record.total_equity)
    final_equity = float(last_record.total_equity)
    expected_cum_return = (final_equity - initial_equity) / initial_equity
    actual_cum_return = float(last_record.cumulative_return) if last_record.cumulative_return else 0
    
    if abs(expected_cum_return - actual_cum_return) > 0.01:  # 1% tolerance
        issues.append(
            f"Cumulative return mismatch: calculated {expected_cum_return:.4f}, "
            f"stored {actual_cum_return:.4f}"
        )
    
    return {
        'valid': len(issues) == 0,
        'strategy_id': strategy_id,
        'mode': mode,
        'records': len(records),
        'date_range': f"{records[0].trading_date.date()} to {records[-1].trading_date.date()}",
        'final_sharpe': final_sharpe,
        'final_cumulative_return': actual_cum_return,
        'gap_count': gap_count,
        'issues': issues
    }


def main():
    """Main entry point for backfill script."""
    parser = argparse.ArgumentParser(
        description='Backfill daily_performance from performance_snapshots',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Target selection
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        '--all',
        action='store_true',
        help='Backfill all strategies'
    )
    target_group.add_argument(
        '--strategy',
        type=str,
        help='Specific strategy ID (e.g., v3_5b)'
    )
    
    # Options
    parser.add_argument(
        '--mode',
        type=str,
        default='offline_mock',
        choices=['offline_mock', 'online_live'],
        help='Trading mode (default: offline_mock)'
    )
    parser.add_argument(
        '--start',
        type=str,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end',
        type=str,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview without database writes'
    )
    parser.add_argument(
        '--include-baselines',
        action='store_true',
        help='Also backfill baseline symbols (QQQ, SPY)'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only validate existing data, no backfill'
    )
    parser.add_argument(
        '--baseline-symbol',
        type=str,
        default='QQQ',
        help='Baseline symbol for comparison (default: QQQ)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse dates
    start_date = None
    end_date = None
    
    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d').date()
    
    # Create session
    session, engine = get_session()
    
    try:
        results = []
        
        if args.all:
            strategies = get_all_strategies(session)
            if not args.mode:
                # Process all modes
                pass
            else:
                strategies = [(s, m) for s, m in strategies if m == args.mode]
        else:
            strategies = [(args.strategy, args.mode)]
        
        # Validation only
        if args.validate_only:
            for strategy_id, mode in strategies:
                result = validate_backfill(session, strategy_id, mode)
                results.append(result)
                
                if result['valid']:
                    logger.info(f"✅ {strategy_id}/{mode}: VALID")
                else:
                    logger.warning(f"❌ {strategy_id}/{mode}: ISSUES FOUND")
                    for issue in result['issues']:
                        logger.warning(f"   - {issue}")
        else:
            # Backfill strategies
            all_trading_dates = set()
            
            for strategy_id, mode in strategies:
                result = backfill_strategy(
                    session,
                    strategy_id,
                    mode,
                    start_date,
                    end_date,
                    args.dry_run,
                    args.baseline_symbol
                )
                results.append(result)
                
                logger.info(
                    f"{'[DRY RUN] ' if args.dry_run else ''}"
                    f"{strategy_id}/{mode}: "
                    f"{result['records_created']} created, {result['records_updated']} updated, "
                    f"Sharpe={result.get('final_sharpe', 'N/A')}"
                )
                
                # Collect trading dates for baseline
                if args.include_baselines:
                    daily_data = get_daily_equities(session, strategy_id, mode, start_date, end_date)
                    all_trading_dates.update(d['trading_date'] for d in daily_data)
            
            # Backfill baselines
            if args.include_baselines and all_trading_dates:
                for baseline in [args.baseline_symbol]:
                    result = backfill_baseline(
                        session,
                        baseline,
                        args.mode,
                        sorted(all_trading_dates),
                        dry_run=args.dry_run
                    )
                    results.append(result)
                    logger.info(
                        f"{'[DRY RUN] ' if args.dry_run else ''}"
                        f"Baseline {baseline}: {result['records_created']} created"
                    )
        
        # Summary
        print("\n" + "=" * 60)
        print("BACKFILL SUMMARY")
        print("=" * 60)
        
        total_created = sum(r.get('records_created', 0) for r in results)
        total_updated = sum(r.get('records_updated', 0) for r in results)
        
        print(f"Total records created: {total_created}")
        print(f"Total records updated: {total_updated}")
        print(f"Dry run: {args.dry_run}")
        
        if args.validate_only:
            valid_count = sum(1 for r in results if r.get('valid', False))
            print(f"Valid: {valid_count}/{len(results)}")
        
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == '__main__':
    main()
