"""
Daily Performance API v2 Routes

GET /api/v2/performance/{strategy_id}/daily - Get daily performance metrics
GET /api/v2/performance/{strategy_id}/daily/history - Get historical daily metrics

These endpoints use the pre-computed daily_performance table for fast, consistent
KPI retrieval. Implements fallback behavior to return previous day's data if
today's finalization has not yet occurred.

Reference: claudedocs/eod_daily_performance_architecture.md Section 10
Workflow: claudedocs/eod_daily_performance_workflow.md Phase 6 & 7
"""

import json
import logging
from datetime import datetime, timezone, timedelta, date as date_type
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, aliased
from sqlalchemy import desc, and_, func
from zoneinfo import ZoneInfo

from jutsu_engine.api.dependencies import (
    get_db,
    get_engine_state,
    verify_credentials,
    EngineState,
)
from jutsu_engine.data.models import DailyPerformance, PerformanceSnapshot
from jutsu_engine.jobs.eod_finalization import (
    get_latest_daily_performance,
    get_eod_finalization_status,
)
from jutsu_engine.utils.trading_calendar import (
    get_trading_date,
    is_trading_day,
    get_previous_trading_day,
)

logger = logging.getLogger('API.DAILY_PERFORMANCE_V2')

router = APIRouter(prefix="/api/v2/performance", tags=["performance-v2"])


# =============================================================================
# Response Models
# =============================================================================


class BaselineData(BaseModel):
    """Baseline performance data for comparison."""
    symbol: str
    total_equity: float
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None


class HoldingInfo(BaseModel):
    """Individual position holding information."""
    symbol: str
    quantity: float
    value: float
    weight_pct: float  # Position as % of total portfolio


class DailyPerformanceData(BaseModel):
    """Daily performance metrics from daily_performance table."""
    trading_date: str
    total_equity: float
    cash: Optional[float] = None
    positions_value: Optional[float] = None
    daily_return: float
    cumulative_return: float
    
    # KPI metrics
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    volatility: Optional[float] = None
    cagr: Optional[float] = None
    
    # Strategy state
    strategy_cell: Optional[str] = None
    trend_state: Optional[str] = None
    vol_state: Optional[str] = None
    
    # Metadata
    trading_days_count: int
    is_first_day: bool = False
    days_since_previous: int = 0
    
    # === NEW FIELDS (Phase 1: Missing from database model) ===
    
    # Per-day drawdown (different from max_drawdown which is all-time)
    drawdown: Optional[float] = None  # (equity - HWM) / HWM for this day
    
    # Position breakdown
    positions_json: Optional[str] = None  # JSON: [{symbol, quantity, value, weight}]
    holdings: Optional[List[HoldingInfo]] = None  # Parsed positions for frontend
    cash_weight_pct: Optional[float] = None  # Cash as % of total portfolio

    # Trade statistics
    total_trades: Optional[int] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None
    win_rate: Optional[float] = None  # winning_trades / total_trades * 100
    
    # Reference tracking
    high_water_mark: Optional[float] = None  # Peak equity for drawdown calc
    initial_capital: Optional[float] = None  # Starting capital for return calcs
    
    # Indicator values (strategies only)
    t_norm: Optional[float] = None
    z_score: Optional[float] = None
    sma_fast: Optional[float] = None
    sma_slow: Optional[float] = None
    
    # === BASELINE FIELDS (Phase 2: Joined from baseline rows) ===
    baseline_value: Optional[float] = None        # Baseline total_equity for same date
    baseline_return: Optional[float] = None       # Baseline cumulative_return (as %)
    baseline_daily_return: Optional[float] = None # Baseline daily_return (as %)

    # === FINALIZATION STATUS ===
    is_finalized: Optional[bool] = None           # True if EOD finalized, False for intraday preview


class DailyPerformanceResponse(BaseModel):
    """Response for GET /api/v2/performance/{strategy_id}/daily."""
    strategy_id: str
    mode: str
    data: DailyPerformanceData
    baseline: Optional[BaselineData] = None
    
    # Fallback indicators
    is_finalized: bool
    data_as_of: str
    finalized_at: Optional[str] = None


class DailyPerformanceHistoryResponse(BaseModel):
    """Response for GET /api/v2/performance/{strategy_id}/daily/history."""
    strategy_id: str
    mode: str
    count: int
    history: List[DailyPerformanceData]
    baseline_symbol: Optional[str] = None


class EODStatusResponse(BaseModel):
    """Response for EOD finalization status."""
    date: str
    finalized: bool
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    progress_pct: Optional[float] = None


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_holdings(positions_json: Optional[str], total_equity: float) -> Optional[List[HoldingInfo]]:
    """Parse positions_json string into HoldingInfo list with weight percentages.

    Args:
        positions_json: JSON string like '[{"symbol": "QQQ", "quantity": 10, "value": 6200.0}]'
        total_equity: Total portfolio value for calculating weight percentages

    Returns:
        List of HoldingInfo objects, or None if no positions
    """
    if not positions_json:
        return None

    try:
        positions = json.loads(positions_json)
        if not positions:
            return None

        holdings = []
        for pos in positions:
            value = float(pos.get('value', 0))
            weight_pct = (value / total_equity * 100) if total_equity > 0 else 0
            holdings.append(HoldingInfo(
                symbol=pos.get('symbol', ''),
                quantity=float(pos.get('quantity', 0)),
                value=value,
                weight_pct=round(weight_pct, 2),
            ))
        return holdings if holdings else None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse positions_json: {e}")
        return None


def _compute_cash_weight(cash: Optional[float], total_equity: Optional[float]) -> Optional[float]:
    """Compute cash as percentage of total portfolio."""
    if cash is None or total_equity is None or total_equity <= 0:
        return None
    return round((float(cash) / float(total_equity)) * 100, 2)


def _record_to_data(record: DailyPerformance) -> DailyPerformanceData:
    """Convert DailyPerformance record to API response data.
    
    Maps all fields from the database model to the API response schema.
    Phase 1 adds: drawdown, positions_json, trade stats, indicators, reference fields.
    Baseline fields (baseline_value, baseline_return) are populated separately via JOIN.
    """
    trading_date = (
        record.trading_date.strftime('%Y-%m-%d')
        if hasattr(record.trading_date, 'strftime')
        else str(record.trading_date)
    )
    
    return DailyPerformanceData(
        # Core fields
        trading_date=trading_date,
        total_equity=float(record.total_equity),
        cash=float(record.cash) if record.cash else None,
        positions_value=float(record.positions_value) if record.positions_value else None,
        daily_return=float(record.daily_return) if record.daily_return else 0.0,
        cumulative_return=float(record.cumulative_return) if record.cumulative_return else 0.0,
        
        # KPI metrics
        sharpe_ratio=float(record.sharpe_ratio) if record.sharpe_ratio else None,
        sortino_ratio=float(record.sortino_ratio) if record.sortino_ratio else None,
        calmar_ratio=float(record.calmar_ratio) if record.calmar_ratio else None,
        max_drawdown=float(record.max_drawdown) if record.max_drawdown else None,
        volatility=float(record.volatility) if record.volatility else None,
        cagr=float(record.cagr) if record.cagr else None,
        
        # Strategy state
        strategy_cell=str(record.strategy_cell) if record.strategy_cell else None,
        trend_state=str(record.trend_state) if record.trend_state else None,
        vol_state=str(record.vol_state) if record.vol_state else None,
        
        # Metadata
        trading_days_count=int(record.trading_days_count) if record.trading_days_count else 1,
        is_first_day=bool(record.is_first_day) if record.is_first_day else False,
        days_since_previous=int(record.days_since_previous) if record.days_since_previous else 0,
        
        # === NEW FIELDS (Phase 1) ===

        # Per-day drawdown
        drawdown=float(record.drawdown) if record.drawdown else None,

        # Position breakdown - parse JSON to holdings array
        positions_json=record.positions_json if record.positions_json else None,
        holdings=_parse_holdings(record.positions_json, float(record.total_equity) if record.total_equity else 10000.0),
        cash_weight_pct=_compute_cash_weight(record.cash, record.total_equity),

        # Trade statistics
        total_trades=int(record.total_trades) if record.total_trades else None,
        winning_trades=int(record.winning_trades) if record.winning_trades else None,
        losing_trades=int(record.losing_trades) if record.losing_trades else None,
        win_rate=float(record.win_rate) if record.win_rate else None,
        
        # Reference tracking
        high_water_mark=float(record.high_water_mark) if record.high_water_mark else None,
        initial_capital=float(record.initial_capital) if record.initial_capital else None,
        
        # Indicator values
        t_norm=float(record.t_norm) if record.t_norm else None,
        z_score=float(record.z_score) if record.z_score else None,
        sma_fast=float(record.sma_fast) if record.sma_fast else None,
        sma_slow=float(record.sma_slow) if record.sma_slow else None,
        
        # Baseline fields (populated via JOIN in Phase 2, None here)
        baseline_value=None,
        baseline_return=None,
        baseline_daily_return=None,

        # Finalization status - records from daily_performance table are finalized
        is_finalized=True,
    )


def _get_baseline_data(
    db: Session,
    baseline_symbol: str,
    mode: str,
    trading_date: date_type,
) -> Optional[BaselineData]:
    """Get baseline performance data for comparison."""
    baseline_record = db.query(DailyPerformance).filter(
        DailyPerformance.entity_type == 'baseline',
        DailyPerformance.entity_id == baseline_symbol,
        DailyPerformance.mode == mode,
        DailyPerformance.trading_date == datetime.combine(trading_date, datetime.min.time()),
    ).first()
    
    if not baseline_record:
        # Try previous trading day
        prev_date = get_previous_trading_day(trading_date)
        baseline_record = db.query(DailyPerformance).filter(
            DailyPerformance.entity_type == 'baseline',
            DailyPerformance.entity_id == baseline_symbol,
            DailyPerformance.mode == mode,
            DailyPerformance.trading_date == datetime.combine(prev_date, datetime.min.time()),
        ).first()
    
    if not baseline_record:
        return None
    
    return BaselineData(
        symbol=baseline_symbol,
        total_equity=float(baseline_record.total_equity),
        daily_return=float(baseline_record.daily_return) if baseline_record.daily_return else None,
        cumulative_return=float(baseline_record.cumulative_return) if baseline_record.cumulative_return else None,
        sharpe_ratio=float(baseline_record.sharpe_ratio) if baseline_record.sharpe_ratio else None,
        max_drawdown=float(baseline_record.max_drawdown) if baseline_record.max_drawdown else None,
    )


# =============================================================================
# API Endpoints
# =============================================================================


@router.get(
    "/{strategy_id}/daily",
    response_model=DailyPerformanceResponse,
    summary="Get daily performance metrics",
    description="""
    Get pre-computed daily performance metrics from the daily_performance table.
    
    Fallback Behavior:
    - If today's finalized row exists: Returns it with is_finalized=True
    - If not (market still open): Returns yesterday's data with is_finalized=False
    
    The response includes:
    - Pre-computed KPIs (Sharpe, Sortino, Calmar, etc.)
    - Strategy state (regime cell, trend, volatility)
    - Baseline comparison data
    - Finalization status and timing
    """
)
async def get_daily_performance(
    strategy_id: str,
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Trading mode (defaults to engine state)"),
    baseline_symbol: str = Query("QQQ", description="Baseline symbol for comparison"),
    _auth: bool = Depends(verify_credentials),
) -> DailyPerformanceResponse:
    """
    Get daily performance metrics for a strategy.
    
    Returns pre-computed KPIs from the daily_performance table.
    Implements fallback to previous day if today's data is not yet finalized.
    """
    try:
        effective_mode = mode or engine_state.mode
        today = get_trading_date()
        
        # Get latest performance with fallback
        record, is_finalized, data_as_of = get_latest_daily_performance(
            db=db,
            entity_type='strategy',
            entity_id=strategy_id,
            mode=effective_mode,
            trading_date=today,
            include_fallback=True,
        )
        
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"No daily performance data found for strategy '{strategy_id}'"
            )
        
        # Convert record to response data
        data = _record_to_data(record)
        
        # Get baseline comparison
        effective_date = data_as_of if data_as_of else today
        baseline = _get_baseline_data(db, baseline_symbol, effective_mode, effective_date)
        
        # Get finalization timestamp
        finalized_at = None
        if record.finalized_at:
            finalized_at = record.finalized_at.isoformat()
        
        return DailyPerformanceResponse(
            strategy_id=strategy_id,
            mode=effective_mode,
            data=data,
            baseline=baseline,
            is_finalized=is_finalized,
            data_as_of=data_as_of.isoformat() if data_as_of else today.isoformat(),
            finalized_at=finalized_at,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting daily performance for {strategy_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{strategy_id}/daily/history",
    response_model=DailyPerformanceHistoryResponse,
    summary="Get historical daily performance",
    description="""
    Get historical daily performance metrics for a strategy.
    
    Returns a list of daily performance records in descending date order.
    Supports pagination via the `days` parameter.
    
    Phase 2: Includes LEFT JOIN to baseline rows for baseline_value, 
    baseline_return, and baseline_daily_return per-row comparison.
    """
)
async def get_daily_history(
    strategy_id: str,
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Trading mode"),
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    baseline_symbol: str = Query("QQQ", description="Baseline symbol"),
    _auth: bool = Depends(verify_credentials),
) -> DailyPerformanceHistoryResponse:
    """
    Get historical daily performance metrics.
    
    Returns records in descending date order (most recent first).
    Phase 2: Includes baseline data via LEFT JOIN for per-row comparison.
    """
    try:
        effective_mode = mode or engine_state.mode
        today = get_trading_date()
        start_date = today - timedelta(days=days)
        
        # Create alias for baseline self-join (Phase 2)
        BaselinePerf = aliased(DailyPerformance, name='baseline_perf')
        
        # Query with LEFT JOIN to baseline rows
        # Strategy rows joined to baseline rows by trading_date and mode
        query_results = db.query(
            DailyPerformance,
            BaselinePerf.total_equity.label('baseline_value'),
            BaselinePerf.cumulative_return.label('baseline_cumulative_return'),
            BaselinePerf.daily_return.label('baseline_daily_return'),
        ).outerjoin(
            BaselinePerf,
            and_(
                BaselinePerf.trading_date == DailyPerformance.trading_date,
                BaselinePerf.entity_type == 'baseline',
                BaselinePerf.entity_id == baseline_symbol,
                BaselinePerf.mode == DailyPerformance.mode,
            )
        ).filter(
            DailyPerformance.entity_type == 'strategy',
            DailyPerformance.entity_id == strategy_id,
            DailyPerformance.mode == effective_mode,
            DailyPerformance.trading_date >= datetime.combine(start_date, datetime.min.time()),
        ).order_by(
            desc(DailyPerformance.trading_date)
        ).all()
        
        # Convert to response data with baseline fields populated
        history = []
        for row in query_results:
            # row is a tuple: (DailyPerformance, baseline_value, baseline_cumulative_return, baseline_daily_return)
            strategy_record = row[0]
            baseline_value = row[1]
            baseline_cumulative_return = row[2]
            baseline_daily_return = row[3]

            # Convert strategy record to response data
            data = _record_to_data(strategy_record)

            # Populate baseline fields from JOIN results (Phase 2)
            # Return as decimal (e.g., 0.0125 for 1.25%) for consistency with cumulative_return/daily_return
            # Frontend will multiply by 100 for display
            data.baseline_value = float(baseline_value) if baseline_value is not None else None
            data.baseline_return = float(baseline_cumulative_return) if baseline_cumulative_return is not None else None
            data.baseline_daily_return = float(baseline_daily_return) if baseline_daily_return is not None else None

            # BACKFILL: If baseline data is missing from JOIN, try to get from performance_snapshots
            # This handles the case where the strategy row exists but the baseline EOD row hasn't been created yet
            if data.baseline_value is None:
                trading_date_obj = (
                    strategy_record.trading_date.date()
                    if hasattr(strategy_record.trading_date, 'date')
                    else strategy_record.trading_date
                )
                eastern = ZoneInfo('America/New_York')
                snapshot_start = datetime.combine(trading_date_obj, datetime.min.time(), tzinfo=eastern)
                snapshot_end = datetime.combine(trading_date_obj, datetime.max.time(), tzinfo=eastern)

                snapshot_with_baseline = db.query(PerformanceSnapshot).filter(
                    PerformanceSnapshot.strategy_id == strategy_id,
                    PerformanceSnapshot.mode == effective_mode,
                    PerformanceSnapshot.timestamp >= snapshot_start,
                    PerformanceSnapshot.timestamp <= snapshot_end,
                    PerformanceSnapshot.baseline_value.isnot(None),
                ).order_by(desc(PerformanceSnapshot.timestamp)).first()

                if snapshot_with_baseline:
                    data.baseline_value = float(snapshot_with_baseline.baseline_value)
                    # Snapshots store baseline_return as percentage (e.g., -0.52 = -0.52%)
                    # But API expects decimals (e.g., 0.004628 = 0.46%), so divide by 100
                    data.baseline_return = float(snapshot_with_baseline.baseline_return) / 100 if snapshot_with_baseline.baseline_return else None
                    logger.debug(f"Backfilled baseline data for {strategy_id} on {trading_date_obj} from snapshot")

            history.append(data)

        # Check if today is in the results (intraday preview logic)
        has_today = any(
            (r[0].trading_date.date() if hasattr(r[0].trading_date, 'date') else r[0].trading_date) == today
            for r in query_results
        ) if query_results else False

        # If today is missing and we have snapshot data, add intraday preview row
        if not has_today and is_trading_day(today):
            eastern = ZoneInfo('America/New_York')
            snapshot_date_start = datetime.combine(today, datetime.min.time(), tzinfo=eastern)
            snapshot_date_end = datetime.combine(today, datetime.max.time(), tzinfo=eastern)

            latest_snapshot = db.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.strategy_id == strategy_id,
                PerformanceSnapshot.mode == effective_mode,
                PerformanceSnapshot.timestamp >= snapshot_date_start,
                PerformanceSnapshot.timestamp <= snapshot_date_end,
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()

            if latest_snapshot:
                # Get previous day's record for calculating daily return
                prev_record = None
                if history:
                    # History is already sorted DESC, so first item is most recent finalized
                    prev_record = history[0]

                # Create intraday preview data
                prev_equity = float(prev_record.total_equity) if prev_record else float(latest_snapshot.total_equity)
                current_equity = float(latest_snapshot.total_equity) if latest_snapshot.total_equity else 0
                daily_return = ((current_equity - prev_equity) / prev_equity) if prev_equity > 0 else 0

                # Calculate cumulative return from initial capital
                prev_initial = float(prev_record.initial_capital) if prev_record and prev_record.initial_capital else current_equity
                cumulative_return = ((current_equity - prev_initial) / prev_initial) if prev_initial > 0 else 0

                preview_data = DailyPerformanceData(
                    trading_date=today.isoformat(),
                    total_equity=current_equity,
                    cash=float(latest_snapshot.cash) if latest_snapshot.cash else None,
                    positions_value=current_equity - (float(latest_snapshot.cash) if latest_snapshot.cash else 0),
                    daily_return=daily_return,
                    cumulative_return=cumulative_return,
                    sharpe_ratio=float(prev_record.sharpe_ratio) if prev_record and prev_record.sharpe_ratio else None,
                    sortino_ratio=float(prev_record.sortino_ratio) if prev_record and prev_record.sortino_ratio else None,
                    calmar_ratio=float(prev_record.calmar_ratio) if prev_record and prev_record.calmar_ratio else None,
                    max_drawdown=float(prev_record.max_drawdown) if prev_record and prev_record.max_drawdown else None,
                    volatility=float(prev_record.volatility) if prev_record and prev_record.volatility else None,
                    cagr=float(prev_record.cagr) if prev_record and prev_record.cagr else None,
                    strategy_cell=str(latest_snapshot.strategy_cell) if latest_snapshot.strategy_cell else None,
                    trend_state=str(latest_snapshot.trend_state) if latest_snapshot.trend_state else None,
                    vol_state=str(latest_snapshot.vol_state) if latest_snapshot.vol_state else None,
                    trading_days_count=(prev_record.trading_days_count + 1) if prev_record and prev_record.trading_days_count else 1,
                    is_first_day=False,
                    days_since_previous=1,
                    high_water_mark=max(current_equity, float(prev_record.high_water_mark)) if prev_record and prev_record.high_water_mark else current_equity,
                    initial_capital=float(prev_record.initial_capital) if prev_record and prev_record.initial_capital else current_equity,
                    # Baseline fields from snapshot
                    # Snapshots store baseline_return as percentage (e.g., -0.52 = -0.52%)
                    # But API expects decimals (e.g., 0.004628 = 0.46%), so divide by 100
                    baseline_value=float(latest_snapshot.baseline_value) if latest_snapshot.baseline_value else None,
                    baseline_return=float(latest_snapshot.baseline_return) / 100 if latest_snapshot.baseline_return else None,
                    baseline_daily_return=None,  # Not available in snapshot
                    # Mark as NOT finalized (intraday preview)
                    is_finalized=False,
                )

                # Insert at beginning (most recent first)
                history.insert(0, preview_data)
                logger.info(f"Added intraday preview row for {strategy_id} on {today}")

        return DailyPerformanceHistoryResponse(
            strategy_id=strategy_id,
            mode=effective_mode,
            count=len(history),
            history=history,
            baseline_symbol=baseline_symbol,
        )
        
    except Exception as e:
        logger.error(f"Error getting history for {strategy_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/comparison",
    summary="Compare multiple strategies",
    description="""
    Compare daily performance across multiple strategies.
    
    Returns performance data for multiple strategies on the same trading date,
    plus their shared baseline for comparison.
    """
)
async def get_performance_comparison(
    strategies: str = Query(..., description="Comma-separated strategy IDs"),
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Trading mode"),
    baseline_symbol: str = Query("QQQ", description="Baseline symbol"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Compare performance across multiple strategies.
    
    All strategies are compared using data from the same trading date.
    """
    try:
        effective_mode = mode or engine_state.mode
        today = get_trading_date()
        
        strategy_ids = [s.strip() for s in strategies.split(',')]
        
        results = []
        data_as_of = None
        
        for strategy_id in strategy_ids:
            record, is_finalized, record_date = get_latest_daily_performance(
                db=db,
                entity_type='strategy',
                entity_id=strategy_id,
                mode=effective_mode,
                trading_date=today,
                include_fallback=True,
            )
            
            if record:
                results.append({
                    'strategy_id': strategy_id,
                    'data': _record_to_data(record).model_dump(),
                    'is_finalized': is_finalized,
                })
                
                # Use the oldest data_as_of for baseline matching
                if data_as_of is None or (record_date and record_date < data_as_of):
                    data_as_of = record_date
            else:
                results.append({
                    'strategy_id': strategy_id,
                    'data': None,
                    'error': 'No data found',
                })
        
        # Get baseline for comparison
        baseline = None
        if data_as_of:
            baseline = _get_baseline_data(db, baseline_symbol, effective_mode, data_as_of)
        
        return {
            'mode': effective_mode,
            'data_as_of': data_as_of.isoformat() if data_as_of else None,
            'strategies': results,
            'baseline': baseline.model_dump() if baseline else None,
        }
        
    except Exception as e:
        logger.error(f"Error comparing strategies: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/eod-status/{date}",
    response_model=EODStatusResponse,
    summary="Get EOD finalization status",
    description="Get the status of EOD finalization for a specific date."
)
async def get_eod_status(
    date: str,
    db: Session = Depends(get_db),
    _auth: bool = Depends(verify_credentials),
) -> EODStatusResponse:
    """
    Get EOD finalization status for a specific date.
    
    Returns whether finalization has completed, timing, and any errors.
    """
    try:
        target_date = datetime.fromisoformat(date).date()
        status = get_eod_finalization_status(db, target_date)
        return EODStatusResponse(**status)
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format (YYYY-MM-DD).")
    except Exception as e:
        logger.error(f"Error getting EOD status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/eod-status/today",
    response_model=EODStatusResponse,
    summary="Get today's EOD finalization status",
    description="Get the status of EOD finalization for today."
)
async def get_today_eod_status(
    db: Session = Depends(get_db),
    _auth: bool = Depends(verify_credentials),
) -> EODStatusResponse:
    """
    Get today's EOD finalization status.
    """
    try:
        today = get_trading_date()
        status = get_eod_finalization_status(db, today)
        return EODStatusResponse(**status)
        
    except Exception as e:
        logger.error(f"Error getting today's EOD status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
