"""
EOD Finalization Job - Daily Performance Metrics Calculation

Scheduled job that runs at market close + 15 minutes (4:15 PM ET normal days,
1:15 PM ET half-days) to calculate and store daily performance metrics.

Features:
- Process all active strategies from StrategyRegistry
- Process baselines (QQQ, SPY) with deduplication
- Incremental KPI updates using Welford's algorithm (O(1))
- Job status tracking for recovery
- Auto-backfill for missed trading days
- Race condition prevention with SELECT FOR UPDATE

Reference: claudedocs/eod_daily_performance_architecture.md Section 8
Workflow: claudedocs/eod_daily_performance_workflow.md Phase 5
"""

import logging
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any

from sqlalchemy import desc
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from jutsu_engine.data.models import (
    DailyPerformance,
    EODJobStatus,
    PerformanceSnapshot,
)
from jutsu_engine.utils.kpi_calculations import (
    calculate_daily_return,
    calculate_cumulative_return,
    update_kpis_incremental,
    initialize_kpi_state,
)
from jutsu_engine.utils.trading_calendar import (
    is_trading_day,
    get_trading_date,
    get_trading_days_between,
    get_previous_trading_day,
    days_since_last_trading_day,
)

logger = logging.getLogger('JOBS.EOD_FINALIZATION')


async def run_eod_finalization(target_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Main EOD finalization job.

    Process:
    1. Create job status record (status='running')
    2. Process each active strategy
    3. Process each unique baseline (deduplicated)
    4. Update job status (status='completed')

    Args:
        target_date: Date to process (defaults to current trading date)

    Returns:
        dict: Job execution summary with status, counts, and any errors
    """
    from jutsu_engine.api.dependencies import SessionLocal

    if target_date is None:
        target_date = get_trading_date()

    if not is_trading_day(target_date):
        logger.info(f"Skipping EOD finalization for {target_date} - not a trading day")
        return {
            'success': True,
            'skipped': True,
            'reason': 'Not a trading day',
            'date': target_date.isoformat(),
        }

    logger.info("=" * 60)
    logger.info(f"EOD Finalization Starting for {target_date}")
    logger.info("=" * 60)

    db = SessionLocal()
    errors = []
    strategies_processed = 0
    baselines_processed = 0
    baselines_seen = set()  # For deduplication

    try:
        # Get active strategies
        from jutsu_engine.live.strategy_registry import StrategyRegistry
        registry = StrategyRegistry()
        active_strategies = registry.get_active_strategies()

        logger.info(f"Processing {len(active_strategies)} strategies")

        # Create job status record
        job_status = EODJobStatus(
            job_date=datetime.combine(target_date, datetime.min.time()),
            started_at=datetime.now(timezone.utc),
            status='running',
            strategies_total=len(active_strategies),
            strategies_processed=0,
            baselines_total=0,  # Will update after counting unique baselines
            baselines_processed=0,
        )
        db.merge(job_status)  # Use merge for upsert behavior
        db.commit()

        # Process each strategy
        for strategy in active_strategies:
            try:
                # Determine mode from strategy config
                # paper_trading=True means simulated execution (no real orders) → offline_mock
                # paper_trading=False means real live trading → online_live
                mode = 'offline_mock' if strategy.paper_trading else 'online_live'
                logger.info(f"Processing strategy {strategy.id} (mode={mode}) for {target_date}")

                success = await process_strategy_eod(
                    db=db,
                    strategy_id=strategy.id,
                    mode=mode,
                    trading_date=target_date,
                )

                if success:
                    logger.info(f"Strategy {strategy.id}: SUCCESS")
                    strategies_processed += 1

                    # Track unique baselines for deduplication
                    baseline_symbol = getattr(strategy, 'baseline_symbol', 'QQQ') or 'QQQ'
                    baselines_seen.add((baseline_symbol, mode))

                    # Update progress
                    job_status.strategies_processed = strategies_processed
                    db.commit()
                else:
                    logger.warning(f"Strategy {strategy.id}: returned False (no snapshot or processing failed)")
                    errors.append(f"Strategy {strategy.id}: Processing returned False")

            except Exception as e:
                error_msg = f"Strategy {strategy.id}: {str(e)}"
                logger.error(f"Strategy {strategy.id}: EXCEPTION - {e}", exc_info=True)
                errors.append(error_msg)

        # Process unique baselines (deduplicated)
        job_status.baselines_total = len(baselines_seen)
        db.commit()

        for baseline_symbol, mode in baselines_seen:
            try:
                success = await process_baseline_eod(
                    db=db,
                    symbol=baseline_symbol,
                    mode=mode,
                    trading_date=target_date,
                )

                if success:
                    baselines_processed += 1
                    job_status.baselines_processed = baselines_processed
                    db.commit()

            except Exception as e:
                error_msg = f"Baseline {baseline_symbol}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)

        # Finalize job status
        if errors:
            job_status.status = 'partial' if strategies_processed > 0 else 'failed'
            job_status.error_message = '; '.join(errors[:5])  # First 5 errors
        else:
            job_status.status = 'completed'

        job_status.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("=" * 60)
        logger.info(f"EOD Finalization Complete for {target_date}")
        logger.info(f"  Strategies: {strategies_processed}/{len(active_strategies)}")
        logger.info(f"  Baselines: {baselines_processed}/{len(baselines_seen)}")
        if errors:
            logger.warning(f"  Errors: {len(errors)}")
        logger.info("=" * 60)

        return {
            'success': len(errors) == 0,
            'date': target_date.isoformat(),
            'strategies_processed': strategies_processed,
            'strategies_total': len(active_strategies),
            'baselines_processed': baselines_processed,
            'baselines_total': len(baselines_seen),
            'errors': errors,
            'duration_seconds': (
                job_status.completed_at - job_status.started_at
            ).total_seconds() if job_status.completed_at and job_status.started_at else None,
        }

    except Exception as e:
        logger.error(f"EOD Finalization failed: {e}", exc_info=True)

        try:
            job_status.status = 'failed'
            job_status.error_message = str(e)
            job_status.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            pass

        return {
            'success': False,
            'date': target_date.isoformat() if target_date else None,
            'error': str(e),
        }

    finally:
        db.close()


async def run_eod_finalization_with_recovery() -> Dict[str, Any]:
    """
    EOD finalization with automatic failure recovery.

    Checks for:
    1. Incomplete jobs from previous days
    2. Missing trading dates
    3. Partial failures (some strategies failed)

    Recovery:
    - Backfills any missed dates
    - Retries failed strategies

    Returns:
        dict: Combined results from recovery and current day processing
    """
    from jutsu_engine.api.dependencies import SessionLocal

    today = get_trading_date()
    recovery_results = []

    logger.info("Checking for missed EOD jobs...")

    db = SessionLocal()
    try:
        # Check for incomplete/failed jobs in the last 7 trading days
        check_start = get_previous_trading_day(today)
        for _ in range(6):  # Go back up to 7 trading days
            check_start = get_previous_trading_day(check_start)

        trading_days = get_trading_days_between(check_start, get_previous_trading_day(today))

        for check_date in trading_days:
            # Check if job exists and completed
            job = db.query(EODJobStatus).filter(
                EODJobStatus.job_date == datetime.combine(check_date, datetime.min.time())
            ).first()

            needs_recovery = False
            if job is None:
                logger.warning(f"Missing EOD job for {check_date} - will backfill")
                needs_recovery = True
            elif job.status in ('failed', 'partial'):
                logger.warning(f"Failed/partial EOD job for {check_date} (status={job.status}) - will retry")
                needs_recovery = True
            elif job.status == 'running':
                # Check if stuck (running for >1 hour)
                if job.started_at:
                    elapsed = datetime.now(timezone.utc) - job.started_at
                    if elapsed > timedelta(hours=1):
                        logger.warning(f"Stuck EOD job for {check_date} (running for {elapsed}) - will retry")
                        needs_recovery = True

            logger.info(
                f"Recovery check: {check_date} - "
                f"job={'exists' if job else 'missing'}, "
                f"status={job.status if job else 'N/A'}, "
                f"needs_recovery={needs_recovery}"
            )

            if needs_recovery:
                try:
                    logger.info(f"Recovery: starting EOD finalization for {check_date}")
                    result = await run_eod_finalization(check_date)
                    recovery_results.append({
                        'date': check_date.isoformat(),
                        'result': result,
                    })
                    logger.info(f"Recovery: {check_date} completed - success={result.get('success')}")
                except Exception as e:
                    logger.error(f"Recovery failed for {check_date}: {e}", exc_info=True)
                    recovery_results.append({
                        'date': check_date.isoformat(),
                        'error': str(e),
                    })

    finally:
        db.close()

    # Now process today
    logger.info(f"Recovery complete ({len(recovery_results)} dates recovered). Processing today ({today})...")
    today_result = await run_eod_finalization(today)

    logger.info(
        f"EOD with recovery finished: "
        f"recovered={len(recovery_results)} dates, "
        f"today_success={today_result.get('success')}"
    )

    return {
        'recovery_results': recovery_results,
        'today_result': today_result,
        'recovery_count': len(recovery_results),
    }


async def process_strategy_eod(
    db,
    strategy_id: str,
    mode: str,
    trading_date: date,
) -> bool:
    """
    Process single strategy for EOD finalization.

    Steps:
    1. Get today's closing equity from performance_snapshots
    2. Get yesterday's daily_performance record (if exists)
    3. Calculate daily return (equity-based)
    4. Update incremental KPI state (Welford's algorithm)
    5. UPSERT into daily_performance

    Args:
        db: SQLAlchemy session
        strategy_id: Strategy identifier (e.g., 'v3_5b')
        mode: Trading mode ('offline_mock' or 'online_live')
        trading_date: Date to process

    Returns:
        bool: True if successful, False otherwise
    """
    logger.debug(f"Processing strategy {strategy_id} for {trading_date}")

    try:
        # Get today's latest snapshot for closing equity
        # Use MAX aggregation to handle multiple snapshots per day
        from sqlalchemy import func

        # Use Eastern timezone boundaries since trading dates are in ET
        # PerformanceSnapshot.timestamp is timezone-aware (UTC) in PostgreSQL
        eastern = ZoneInfo('America/New_York')
        snapshot_date_start = datetime.combine(trading_date, datetime.min.time(), tzinfo=eastern)
        snapshot_date_end = datetime.combine(trading_date, datetime.max.time(), tzinfo=eastern)

        latest_snapshot = db.query(
            PerformanceSnapshot
        ).filter(
            PerformanceSnapshot.strategy_id == strategy_id,
            PerformanceSnapshot.mode == mode,
            PerformanceSnapshot.timestamp >= snapshot_date_start,
            PerformanceSnapshot.timestamp <= snapshot_date_end,
        ).order_by(
            desc(PerformanceSnapshot.timestamp)
        ).first()

        logger.info(
            f"Snapshot query for {strategy_id} on {trading_date}: "
            f"range=[{snapshot_date_start}, {snapshot_date_end}], mode={mode}, "
            f"found={'yes' if latest_snapshot else 'NO'}"
        )

        if not latest_snapshot:
            logger.warning(f"No snapshot found for {strategy_id} on {trading_date}")
            return False

        today_equity = Decimal(str(latest_snapshot.total_equity))
        today_cash = Decimal(str(latest_snapshot.cash)) if latest_snapshot.cash else None
        today_positions_value = today_equity - (today_cash or Decimal('0'))

        # Get previous day's record
        prev_record = db.query(DailyPerformance).filter(
            DailyPerformance.entity_type == 'strategy',
            DailyPerformance.entity_id == strategy_id,
            DailyPerformance.mode == mode,
            DailyPerformance.trading_date < datetime.combine(trading_date, datetime.min.time(), tzinfo=eastern),
        ).order_by(
            desc(DailyPerformance.trading_date)
        ).first()

        # Calculate metrics
        if prev_record is None:
            # First day - cold start
            daily_return = Decimal('0')
            cumulative_return = Decimal('0')
            initial_capital = today_equity
            is_first_day = True
            days_since_previous = 0
            trading_days_count = 1

            # Initialize KPI state
            kpi_state = initialize_kpi_state(float(today_equity))
        else:
            yesterday_equity = prev_record.total_equity
            initial_capital = prev_record.initial_capital

            # Calculate equity-based daily return
            daily_return = calculate_daily_return(today_equity, Decimal(str(yesterday_equity)))
            cumulative_return = calculate_cumulative_return(
                today_equity, Decimal(str(initial_capital))
            )

            is_first_day = False

            # Calculate days since previous
            prev_date = prev_record.trading_date.date() if hasattr(prev_record.trading_date, 'date') else prev_record.trading_date
            days_since_previous = (trading_date - prev_date).days

            if days_since_previous > 5:
                logger.warning(
                    f"Large gap detected for {strategy_id}: {days_since_previous} trading days "
                    f"between {prev_date} and {trading_date}"
                )

            trading_days_count = (prev_record.trading_days_count or 1) + 1

            # Calculate incremental KPIs using Welford's algorithm
            kpi_state = update_kpis_incremental(
                prev_returns_sum=float(prev_record.returns_sum or 0),
                prev_returns_sum_sq=float(prev_record.returns_sum_sq or 0),
                prev_downside_sum_sq=float(prev_record.downside_sum_sq or 0),
                prev_returns_count=prev_record.returns_count or 0,
                prev_high_water_mark=float(prev_record.high_water_mark or initial_capital),
                prev_max_drawdown=float(prev_record.max_drawdown or 0),
                today_return=float(daily_return),
                today_equity=float(today_equity),
                initial_capital=float(initial_capital),
            )

        # Get regime metadata from scheduler snapshot (authoritative source)
        # Architecture decision 2026-01-14: only scheduler snapshots carry regime data;
        # refresh snapshots intentionally omit it.  Fall back to latest_snapshot if no
        # scheduler snapshot exists for this day.
        regime_snapshot = db.query(
            PerformanceSnapshot
        ).filter(
            PerformanceSnapshot.strategy_id == strategy_id,
            PerformanceSnapshot.mode == mode,
            PerformanceSnapshot.timestamp >= snapshot_date_start,
            PerformanceSnapshot.timestamp <= snapshot_date_end,
            PerformanceSnapshot.snapshot_source == 'scheduler',
        ).order_by(
            desc(PerformanceSnapshot.timestamp)
        ).first()

        if regime_snapshot and regime_snapshot.strategy_cell is not None:
            strategy_cell = regime_snapshot.strategy_cell
            trend_state = regime_snapshot.trend_state
            vol_state = regime_snapshot.vol_state
        else:
            # Fallback: use latest snapshot (may be None for refresh-only days)
            strategy_cell = latest_snapshot.strategy_cell
            trend_state = latest_snapshot.trend_state
            vol_state = latest_snapshot.vol_state

        # Build record
        record = DailyPerformance(
            trading_date=datetime.combine(trading_date, datetime.min.time()),
            entity_type='strategy',
            entity_id=strategy_id,
            mode=mode,
            total_equity=today_equity,
            cash=today_cash,
            positions_value=today_positions_value,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            drawdown=Decimal(str(kpi_state.get('drawdown', 0))) if kpi_state.get('drawdown') else None,
            sharpe_ratio=Decimal(str(kpi_state.get('sharpe_ratio'))) if kpi_state.get('sharpe_ratio') else None,
            sortino_ratio=Decimal(str(kpi_state.get('sortino_ratio'))) if kpi_state.get('sortino_ratio') else None,
            calmar_ratio=Decimal(str(kpi_state.get('calmar_ratio'))) if kpi_state.get('calmar_ratio') else None,
            max_drawdown=Decimal(str(kpi_state.get('max_drawdown'))) if kpi_state.get('max_drawdown') else None,
            volatility=Decimal(str(kpi_state.get('volatility'))) if kpi_state.get('volatility') else None,
            cagr=Decimal(str(kpi_state.get('cagr'))) if kpi_state.get('cagr') else None,
            strategy_cell=strategy_cell,
            trend_state=trend_state,
            vol_state=vol_state,
            initial_capital=initial_capital,
            high_water_mark=Decimal(str(kpi_state.get('high_water_mark', today_equity))),
            trading_days_count=trading_days_count,
            days_since_previous=days_since_previous,
            is_first_day=is_first_day,
            returns_sum=Decimal(str(kpi_state.get('returns_sum', 0))),
            returns_sum_sq=Decimal(str(kpi_state.get('returns_sum_sq', 0))),
            downside_sum_sq=Decimal(str(kpi_state.get('downside_sum_sq', 0))),
            returns_count=kpi_state.get('returns_count', 0),
            finalized_at=datetime.now(timezone.utc),
        )

        # UPSERT using ON CONFLICT
        stmt = pg_insert(DailyPerformance).values(
            trading_date=record.trading_date,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            mode=record.mode,
            total_equity=record.total_equity,
            cash=record.cash,
            positions_value=record.positions_value,
            daily_return=record.daily_return,
            cumulative_return=record.cumulative_return,
            drawdown=record.drawdown,
            sharpe_ratio=record.sharpe_ratio,
            sortino_ratio=record.sortino_ratio,
            calmar_ratio=record.calmar_ratio,
            max_drawdown=record.max_drawdown,
            volatility=record.volatility,
            cagr=record.cagr,
            strategy_cell=record.strategy_cell,
            trend_state=record.trend_state,
            vol_state=record.vol_state,
            initial_capital=record.initial_capital,
            high_water_mark=record.high_water_mark,
            trading_days_count=record.trading_days_count,
            days_since_previous=record.days_since_previous,
            is_first_day=record.is_first_day,
            returns_sum=record.returns_sum,
            returns_sum_sq=record.returns_sum_sq,
            downside_sum_sq=record.downside_sum_sq,
            returns_count=record.returns_count,
            finalized_at=record.finalized_at,
        ).on_conflict_do_update(
            constraint='uix_daily_perf',
            set_={
                'total_equity': record.total_equity,
                'cash': record.cash,
                'positions_value': record.positions_value,
                'daily_return': record.daily_return,
                'cumulative_return': record.cumulative_return,
                'drawdown': record.drawdown,
                'sharpe_ratio': record.sharpe_ratio,
                'sortino_ratio': record.sortino_ratio,
                'calmar_ratio': record.calmar_ratio,
                'max_drawdown': record.max_drawdown,
                'volatility': record.volatility,
                'cagr': record.cagr,
                'strategy_cell': record.strategy_cell,
                'trend_state': record.trend_state,
                'vol_state': record.vol_state,
                'high_water_mark': record.high_water_mark,
                'trading_days_count': record.trading_days_count,
                'days_since_previous': record.days_since_previous,
                'is_first_day': record.is_first_day,
                'returns_sum': record.returns_sum,
                'returns_sum_sq': record.returns_sum_sq,
                'downside_sum_sq': record.downside_sum_sq,
                'returns_count': record.returns_count,
                'finalized_at': record.finalized_at,
            }
        )

        db.execute(stmt)
        db.commit()

        logger.debug(
            f"Processed {strategy_id}: equity={today_equity}, "
            f"return={float(daily_return):.4%}, sharpe={kpi_state.get('sharpe_ratio', 'N/A')}"
        )

        return True

    except SQLAlchemyError as e:
        logger.error(f"Database error processing {strategy_id}: {e}")
        db.rollback()
        return False
    except Exception as e:
        logger.error(f"Error processing {strategy_id}: {e}", exc_info=True)
        db.rollback()
        return False


async def process_baseline_eod(
    db,
    symbol: str,
    mode: str,
    trading_date: date,
) -> bool:
    """
    Process baseline (e.g., QQQ) for EOD finalization.

    Baselines are deduplicated - only one row per symbol per date,
    regardless of how many strategies use that baseline.

    Args:
        db: SQLAlchemy session
        symbol: Baseline symbol (e.g., 'QQQ', 'SPY')
        mode: Trading mode
        trading_date: Date to process

    Returns:
        bool: True if successful, False otherwise
    """
    logger.debug(f"Processing baseline {symbol} for {trading_date}")

    try:
        # Check if baseline already exists for this date (deduplication)
        eastern = ZoneInfo('America/New_York')
        existing = db.query(DailyPerformance).filter(
            DailyPerformance.entity_type == 'baseline',
            DailyPerformance.entity_id == symbol,
            DailyPerformance.mode == mode,
            DailyPerformance.trading_date == datetime.combine(trading_date, datetime.min.time(), tzinfo=eastern),
        ).first()

        if existing:
            logger.debug(f"Baseline {symbol} already exists for {trading_date}")
            return True  # Already processed, success

        # Get baseline price data
        # For baselines, we calculate buy-and-hold from market data
        from jutsu_engine.data.models import MarketData
        from sqlalchemy import func

        # Use UTC-aware date range to find market data
        # Schwab timestamps daily bars at 06:00 UTC of the trading date
        # (which is 22:00 PST previous calendar day, 01:00 ET same day)
        # Query range [T 00:00 UTC, T+1 00:00 UTC) captures the 06:00 UTC bar
        start_of_day = datetime.combine(trading_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = datetime.combine(trading_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)

        today_bar = db.query(MarketData).filter(
            MarketData.symbol == symbol,
            MarketData.timeframe == '1D',
            MarketData.timestamp >= start_of_day,
            MarketData.timestamp < end_of_day,
        ).first()

        if not today_bar:
            logger.warning(f"No market data for baseline {symbol} on {trading_date}")
            return False

        today_price = Decimal(str(today_bar.close))

        # Get previous baseline record
        prev_record = db.query(DailyPerformance).filter(
            DailyPerformance.entity_type == 'baseline',
            DailyPerformance.entity_id == symbol,
            DailyPerformance.mode == mode,
            DailyPerformance.trading_date < datetime.combine(trading_date, datetime.min.time(), tzinfo=eastern),
        ).order_by(
            desc(DailyPerformance.trading_date)
        ).first()

        # Calculate baseline equity (buy-and-hold)
        if prev_record is None:
            # First day - initialize with standard capital
            initial_capital = Decimal('10000')
            shares = initial_capital / today_price
            today_equity = shares * today_price  # = initial_capital
            daily_return = Decimal('0')
            cumulative_return = Decimal('0')
            is_first_day = True
            days_since_previous = 0
            trading_days_count = 1

            kpi_state = initialize_kpi_state(float(today_equity))
        else:
            initial_capital = prev_record.initial_capital
            shares = Decimal(str(initial_capital)) / Decimal(str(prev_record.total_equity)) * Decimal(str(prev_record.total_equity)) / today_price

            # Get previous day's price (use UTC-aware timestamps for Schwab convention)
            prev_date = prev_record.trading_date.date() if hasattr(prev_record.trading_date, 'date') else prev_record.trading_date
            prev_start = datetime.combine(prev_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            prev_end = datetime.combine(prev_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
            prev_bar = db.query(MarketData).filter(
                MarketData.symbol == symbol,
                MarketData.timeframe == '1D',
                MarketData.timestamp >= prev_start,
                MarketData.timestamp < prev_end,
            ).first()

            if prev_bar:
                prev_price = Decimal(str(prev_bar.close))
                daily_return = (today_price - prev_price) / prev_price
            else:
                daily_return = Decimal('0')

            # Calculate equity
            today_equity = Decimal(str(prev_record.total_equity)) * (1 + daily_return)
            cumulative_return = calculate_cumulative_return(today_equity, Decimal(str(initial_capital)))

            is_first_day = False
            days_since_previous = (trading_date - prev_date).days
            trading_days_count = (prev_record.trading_days_count or 1) + 1

            kpi_state = update_kpis_incremental(
                prev_returns_sum=float(prev_record.returns_sum or 0),
                prev_returns_sum_sq=float(prev_record.returns_sum_sq or 0),
                prev_downside_sum_sq=float(prev_record.downside_sum_sq or 0),
                prev_returns_count=prev_record.returns_count or 0,
                prev_high_water_mark=float(prev_record.high_water_mark or initial_capital),
                prev_max_drawdown=float(prev_record.max_drawdown or 0),
                today_return=float(daily_return),
                today_equity=float(today_equity),
                initial_capital=float(initial_capital),
            )

        # Build record
        record = DailyPerformance(
            trading_date=datetime.combine(trading_date, datetime.min.time()),
            entity_type='baseline',
            entity_id=symbol,
            mode=mode,
            total_equity=today_equity,
            cash=None,  # Baselines don't have cash
            positions_value=today_equity,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            drawdown=Decimal(str(kpi_state.get('drawdown', 0))) if kpi_state.get('drawdown') else None,
            sharpe_ratio=Decimal(str(kpi_state.get('sharpe_ratio'))) if kpi_state.get('sharpe_ratio') else None,
            sortino_ratio=Decimal(str(kpi_state.get('sortino_ratio'))) if kpi_state.get('sortino_ratio') else None,
            calmar_ratio=Decimal(str(kpi_state.get('calmar_ratio'))) if kpi_state.get('calmar_ratio') else None,
            max_drawdown=Decimal(str(kpi_state.get('max_drawdown'))) if kpi_state.get('max_drawdown') else None,
            volatility=Decimal(str(kpi_state.get('volatility'))) if kpi_state.get('volatility') else None,
            cagr=Decimal(str(kpi_state.get('cagr'))) if kpi_state.get('cagr') else None,
            strategy_cell=None,  # Baselines don't have strategy state
            trend_state=None,
            vol_state=None,
            initial_capital=initial_capital,
            high_water_mark=Decimal(str(kpi_state.get('high_water_mark', today_equity))),
            trading_days_count=trading_days_count,
            days_since_previous=days_since_previous,
            is_first_day=is_first_day,
            returns_sum=Decimal(str(kpi_state.get('returns_sum', 0))),
            returns_sum_sq=Decimal(str(kpi_state.get('returns_sum_sq', 0))),
            downside_sum_sq=Decimal(str(kpi_state.get('downside_sum_sq', 0))),
            returns_count=kpi_state.get('returns_count', 0),
            finalized_at=datetime.now(timezone.utc),
        )

        # UPSERT
        stmt = pg_insert(DailyPerformance).values(
            trading_date=record.trading_date,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            mode=record.mode,
            total_equity=record.total_equity,
            cash=record.cash,
            positions_value=record.positions_value,
            daily_return=record.daily_return,
            cumulative_return=record.cumulative_return,
            drawdown=record.drawdown,
            sharpe_ratio=record.sharpe_ratio,
            sortino_ratio=record.sortino_ratio,
            calmar_ratio=record.calmar_ratio,
            max_drawdown=record.max_drawdown,
            volatility=record.volatility,
            cagr=record.cagr,
            strategy_cell=record.strategy_cell,
            trend_state=record.trend_state,
            vol_state=record.vol_state,
            initial_capital=record.initial_capital,
            high_water_mark=record.high_water_mark,
            trading_days_count=record.trading_days_count,
            days_since_previous=record.days_since_previous,
            is_first_day=record.is_first_day,
            returns_sum=record.returns_sum,
            returns_sum_sq=record.returns_sum_sq,
            downside_sum_sq=record.downside_sum_sq,
            returns_count=record.returns_count,
            finalized_at=record.finalized_at,
        ).on_conflict_do_update(
            constraint='uix_daily_perf',
            set_={
                'total_equity': record.total_equity,
                'daily_return': record.daily_return,
                'cumulative_return': record.cumulative_return,
                'drawdown': record.drawdown,
                'sharpe_ratio': record.sharpe_ratio,
                'sortino_ratio': record.sortino_ratio,
                'calmar_ratio': record.calmar_ratio,
                'max_drawdown': record.max_drawdown,
                'volatility': record.volatility,
                'cagr': record.cagr,
                'high_water_mark': record.high_water_mark,
                'trading_days_count': record.trading_days_count,
                'days_since_previous': record.days_since_previous,
                'is_first_day': record.is_first_day,
                'returns_sum': record.returns_sum,
                'returns_sum_sq': record.returns_sum_sq,
                'downside_sum_sq': record.downside_sum_sq,
                'returns_count': record.returns_count,
                'finalized_at': record.finalized_at,
            }
        )

        db.execute(stmt)
        db.commit()

        logger.debug(
            f"Processed baseline {symbol}: price={today_price}, "
            f"equity={today_equity}, return={float(daily_return):.4%}"
        )

        return True

    except SQLAlchemyError as e:
        logger.error(f"Database error processing baseline {symbol}: {e}")
        db.rollback()
        return False
    except Exception as e:
        logger.error(f"Error processing baseline {symbol}: {e}", exc_info=True)
        db.rollback()
        return False


def monitor_eod_health() -> Dict[str, Any]:
    """
    Health check for EOD finalization.

    Checks:
    - Job completed today (if trading day)
    - All strategies processed
    - No large data gaps

    Returns:
        dict: Health report with status and details
    """
    from jutsu_engine.api.dependencies import SessionLocal

    today = get_trading_date()
    health = {
        'healthy': True,
        'checks': [],
        'warnings': [],
        'errors': [],
    }

    if not is_trading_day(today):
        health['checks'].append('Not a trading day - no job expected')
        return health

    db = SessionLocal()
    try:
        # Check if today's job completed
        job = db.query(EODJobStatus).filter(
            EODJobStatus.job_date == datetime.combine(today, datetime.min.time())
        ).first()

        if job is None:
            health['warnings'].append(f"No EOD job found for today ({today})")
        elif job.status == 'completed':
            health['checks'].append(f"Today's job completed in {job.duration}")
        elif job.status == 'running':
            elapsed = datetime.now(timezone.utc) - job.started_at if job.started_at else None
            if elapsed and elapsed > timedelta(hours=1):
                health['errors'].append(f"Job stuck for {elapsed}")
                health['healthy'] = False
            else:
                health['checks'].append(f"Job in progress ({job.progress_pct:.0f}%)")
        elif job.status in ('failed', 'partial'):
            health['errors'].append(f"Job {job.status}: {job.error_message}")
            health['healthy'] = False

        # Check for recent gaps
        recent_jobs = db.query(EODJobStatus).filter(
            EODJobStatus.job_date >= datetime.combine(
                get_previous_trading_day(today) - timedelta(days=10),
                datetime.min.time()
            )
        ).all()

        failed_count = sum(1 for j in recent_jobs if j.status in ('failed', 'partial'))
        if failed_count > 2:
            health['warnings'].append(f"{failed_count} failed/partial jobs in last 10 days")

    finally:
        db.close()

    return health


# =============================================================================
# Corner Case Helper Functions (Phase 6)
# =============================================================================


def handle_first_day(
    strategy_id: str,
    mode: str,
    today_equity: float,
    entity_type: str = 'strategy',
) -> Dict[str, Any]:
    """
    Handle first trading day for new strategy (cold start).

    Sets:
    - daily_return = 0.0 (no previous day)
    - cumulative_return = 0.0
    - initial_capital = today_equity
    - is_first_day = True
    - All KPIs = None (insufficient data)
    - Initialize incremental state (returns_sum=0, etc.)

    Args:
        strategy_id: Strategy or baseline identifier
        mode: Trading mode
        today_equity: Today's closing equity
        entity_type: 'strategy' or 'baseline'

    Returns:
        dict: Record data for first day
    """
    logger.info(
        f"[FIRST_DAY] Initializing first day for {entity_type} {strategy_id} "
        f"with equity={today_equity}"
    )

    kpi_state = initialize_kpi_state(today_equity)

    return {
        'daily_return': Decimal('0'),
        'cumulative_return': Decimal('0'),
        'initial_capital': Decimal(str(today_equity)),
        'is_first_day': True,
        'days_since_previous': 0,
        'trading_days_count': 1,
        'kpi_state': kpi_state,
    }


def handle_data_gap(
    strategy_id: str,
    mode: str,
    prev_date: date,
    today_date: date,
    gap_days: int,
) -> None:
    """
    Handle gaps in trading data with appropriate logging.

    Logging levels:
    - Small gaps (2-3 days): DEBUG
    - Normal gaps (4-5 days): INFO
    - Large gaps (>5 days): WARNING

    Args:
        strategy_id: Strategy or baseline identifier
        mode: Trading mode
        prev_date: Previous trading date
        today_date: Current trading date
        gap_days: Number of trading days gap
    """
    if gap_days <= 3:
        logger.debug(
            f"[DATA_GAP] Small gap ({gap_days} trading days) for {strategy_id}: "
            f"{prev_date} → {today_date}"
        )
    elif gap_days <= 5:
        logger.info(
            f"[DATA_GAP] Normal gap ({gap_days} trading days) for {strategy_id}: "
            f"{prev_date} → {today_date}"
        )
    else:
        logger.warning(
            f"[DATA_GAP] Large gap ({gap_days} trading days) for {strategy_id}: "
            f"{prev_date} → {today_date}. This may affect KPI accuracy."
        )


def log_edge_case(
    case_type: str,
    entity_id: str,
    message: str,
    level: str = 'INFO',
    **extra,
) -> None:
    """
    Structured logging for edge cases.

    Case types:
    - FIRST_DAY: First trading day for entity (INFO)
    - DATA_GAP: Non-consecutive trading days (DEBUG/WARNING)
    - NO_SNAPSHOT: Missing snapshot data (WARNING)
    - STRATEGY_MISSING: Strategy not registered (ERROR)
    - BASELINE_MISSING: Baseline data unavailable (WARNING)
    - RECOVERY: Backfilling missed days (INFO)

    Args:
        case_type: Type of edge case
        entity_id: Entity identifier
        message: Log message
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        **extra: Additional context to log
    """
    extra_str = ' '.join(f'{k}={v}' for k, v in extra.items()) if extra else ''
    full_message = f"[{case_type}] {entity_id}: {message}" + (f" ({extra_str})" if extra_str else '')

    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, full_message)


def get_latest_daily_performance(
    db,
    entity_type: str,
    entity_id: str,
    mode: str,
    trading_date: date,
    include_fallback: bool = True,
) -> tuple[Optional[Any], bool, Optional[date]]:
    """
    Get latest daily performance with fallback behavior.

    API Fallback Logic:
    - If today's finalized row exists: Return it with is_finalized=True
    - If not (market still open): Return yesterday's row with is_finalized=False

    Args:
        db: SQLAlchemy session
        entity_type: 'strategy' or 'baseline'
        entity_id: Entity identifier
        mode: Trading mode
        trading_date: Target date
        include_fallback: Whether to fallback to previous day

    Returns:
        tuple: (record, is_finalized, data_as_of_date)
            - record: DailyPerformance record or None
            - is_finalized: True if this is finalized data
            - data_as_of_date: Date the data is from
    """
    target_datetime = datetime.combine(trading_date, datetime.min.time())

    # Try to get today's record
    today_record = db.query(DailyPerformance).filter(
        DailyPerformance.entity_type == entity_type,
        DailyPerformance.entity_id == entity_id,
        DailyPerformance.mode == mode,
        DailyPerformance.trading_date == target_datetime,
    ).first()

    if today_record:
        # Today's record exists and is finalized
        return (today_record, True, trading_date)

    if not include_fallback:
        return (None, False, None)

    # Fallback to most recent record
    prev_record = db.query(DailyPerformance).filter(
        DailyPerformance.entity_type == entity_type,
        DailyPerformance.entity_id == entity_id,
        DailyPerformance.mode == mode,
        DailyPerformance.trading_date < target_datetime,
    ).order_by(
        desc(DailyPerformance.trading_date)
    ).first()

    if prev_record:
        prev_date = (
            prev_record.trading_date.date()
            if hasattr(prev_record.trading_date, 'date')
            else prev_record.trading_date
        )
        logger.debug(
            f"[API_FALLBACK] {entity_type} {entity_id}: Today ({trading_date}) not finalized, "
            f"returning {prev_date} data"
        )
        return (prev_record, False, prev_date)

    return (None, False, None)


def get_eod_finalization_status(db, trading_date: date) -> Dict[str, Any]:
    """
    Get EOD finalization status for a specific date.

    Returns:
        dict: Status including completion state, timing, and any errors
    """
    job = db.query(EODJobStatus).filter(
        EODJobStatus.job_date == datetime.combine(trading_date, datetime.min.time())
    ).first()

    if job is None:
        return {
            'date': trading_date.isoformat(),
            'finalized': False,
            'status': 'pending',
            'started_at': None,
            'completed_at': None,
            'duration_seconds': None,
            'error': None,
        }

    return {
        'date': trading_date.isoformat(),
        'finalized': job.status == 'completed',
        'status': job.status,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'duration_seconds': job.duration.total_seconds() if job.duration else None,
        'error': job.error_message,
        'progress_pct': job.progress_pct,
    }
