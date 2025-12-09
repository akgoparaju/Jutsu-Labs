"""
Performance API Routes

GET /api/performance - Get performance metrics and history
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func

from jutsu_engine.api.schemas import (
    PerformanceResponse,
    PerformanceMetrics,
    PerformanceSnapshot as PerformanceSnapshotSchema,
    SnapshotPositionInfo,
    HoldingInfo,
    ErrorResponse,
)
from jutsu_engine.api.dependencies import (
    get_db,
    get_engine_state,
    verify_credentials,
    EngineState,
)
from jutsu_engine.data.models import PerformanceSnapshot, LiveTrade, Position

logger = logging.getLogger('API.PERFORMANCE')

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get(
    "",
    response_model=PerformanceResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get performance metrics",
    description="Returns current performance metrics and historical snapshots."
)
async def get_performance(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    days: int = Query(30, ge=1, le=365, description="Days of history"),
    _auth: bool = Depends(verify_credentials),
) -> PerformanceResponse:
    """
    Get performance metrics and history.

    Returns:
    - Current performance metrics (equity, returns, drawdown)
    - Historical snapshots for charting
    - Trade statistics (win rate, total trades)
    """
    try:
        effective_mode = mode or engine_state.mode

        # Get latest snapshot for current metrics
        latest = db.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == effective_mode
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

        # Calculate date range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # Get historical snapshots
        history_query = db.query(PerformanceSnapshot).filter(
            and_(
                PerformanceSnapshot.mode == effective_mode,
                PerformanceSnapshot.timestamp >= start_date,
            )
        ).order_by(PerformanceSnapshot.timestamp)

        history = history_query.all()

        # Calculate trade statistics
        trade_stats = db.query(
            func.count(LiveTrade.id).label('total'),
        ).filter(
            LiveTrade.mode == effective_mode
        ).first()

        total_trades = trade_stats.total if trade_stats else 0

        # Calculate win rate (trades where we had a profit)
        # For a simple approach, count trades where fill_value > 0 for BUY
        # This is simplified - real P&L calculation would be more complex
        winning_trades = 0
        losing_trades = 0

        # Get high water mark for accurate drawdown
        hwm_result = db.query(
            func.max(PerformanceSnapshot.total_equity)
        ).filter(
            PerformanceSnapshot.mode == effective_mode
        ).first()

        high_water_mark = float(hwm_result[0]) if hwm_result and hwm_result[0] else None

        # Query current positions for holdings breakdown
        positions = db.query(Position).filter(
            Position.mode == effective_mode,
            Position.quantity != 0  # Only show non-zero positions
        ).all()

        # Calculate holdings breakdown
        holdings = []
        total_equity = float(latest.total_equity) if latest else 0.0

        for pos in positions:
            market_value = float(pos.market_value) if pos.market_value else 0.0
            weight_pct = (market_value / total_equity * 100) if total_equity > 0 else 0.0

            holdings.append(HoldingInfo(
                symbol=pos.symbol,
                quantity=pos.quantity,
                value=market_value,
                weight_pct=round(weight_pct, 2)
            ))

        # Sort holdings by value descending
        holdings.sort(key=lambda x: x.value, reverse=True)

        # Calculate cash and cash weight
        cash = float(latest.cash) if latest and latest.cash else None
        cash_weight_pct = None
        if cash is not None and total_equity > 0:
            cash_weight_pct = round(cash / total_equity * 100, 2)

        # Build current metrics
        current = PerformanceMetrics(
            total_equity=total_equity,
            holdings=holdings,
            cash=cash,
            cash_weight_pct=cash_weight_pct,
            daily_return=float(latest.daily_return) if latest and latest.daily_return else None,
            cumulative_return=float(latest.cumulative_return) if latest and latest.cumulative_return else None,
            drawdown=float(latest.drawdown) if latest and latest.drawdown else None,
            high_water_mark=high_water_mark,
            sharpe_ratio=None,  # Would need to calculate from returns
            win_rate=None,  # Would need proper P&L tracking
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
        )

        # Convert history to schema
        history_schemas = []
        for snapshot in history:
            # Parse positions from JSON if available
            positions = None
            if snapshot.positions_json:
                try:
                    positions_data = json.loads(snapshot.positions_json)
                    positions = [
                        SnapshotPositionInfo(
                            symbol=p['symbol'],
                            quantity=p['quantity'],
                            value=p['value']
                        )
                        for p in positions_data
                    ]
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse positions_json: {e}")

            history_schemas.append(PerformanceSnapshotSchema(
                timestamp=snapshot.timestamp,
                total_equity=float(snapshot.total_equity),
                cash=float(snapshot.cash) if snapshot.cash else None,
                positions_value=float(snapshot.positions_value) if snapshot.positions_value else None,
                daily_return=float(snapshot.daily_return) if snapshot.daily_return else None,
                cumulative_return=float(snapshot.cumulative_return) if snapshot.cumulative_return else None,
                drawdown=float(snapshot.drawdown) if snapshot.drawdown else None,
                strategy_cell=snapshot.strategy_cell,
                trend_state=snapshot.trend_state,
                vol_state=snapshot.vol_state,
                positions=positions,
                baseline_value=float(snapshot.baseline_value) if snapshot.baseline_value is not None else None,
                baseline_return=float(snapshot.baseline_return) if snapshot.baseline_return is not None else None,
                mode=snapshot.mode,
            ))

        return PerformanceResponse(
            current=current,
            history=history_schemas,
            mode=effective_mode,
        )

    except Exception as e:
        logger.error(f"Performance get error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/equity-curve",
    summary="Get equity curve data",
    description="Returns equity curve data for charting."
)
async def get_equity_curve(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    days: int = Query(90, ge=1, le=365, description="Days of history"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get equity curve data optimized for charting.

    Returns arrays of dates and values for lightweight-charts.
    """
    try:
        effective_mode = mode or engine_state.mode

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        snapshots = db.query(
            PerformanceSnapshot.timestamp,
            PerformanceSnapshot.total_equity,
            PerformanceSnapshot.cumulative_return,
            PerformanceSnapshot.strategy_cell,
            PerformanceSnapshot.baseline_value,
            PerformanceSnapshot.baseline_return,
        ).filter(
            and_(
                PerformanceSnapshot.mode == effective_mode,
                PerformanceSnapshot.timestamp >= start_date,
            )
        ).order_by(PerformanceSnapshot.timestamp).all()

        # Format for charting - deduplicate by date (keep latest per day)
        # lightweight-charts requires unique ascending timestamps
        data_by_date = {}
        for snapshot in snapshots:
            date_key = snapshot.timestamp.strftime('%Y-%m-%d')
            # Later entries overwrite earlier ones (keeping latest per day)
            data_by_date[date_key] = {
                "time": date_key,
                "value": float(snapshot.total_equity),
                "return": float(snapshot.cumulative_return) if snapshot.cumulative_return else 0.0,
                "regime": snapshot.strategy_cell,
                "baseline_value": float(snapshot.baseline_value) if snapshot.baseline_value is not None else None,
                "baseline_return": float(snapshot.baseline_return) if snapshot.baseline_return is not None else None,
            }

        # Convert to sorted list (ascending by date)
        data = [data_by_date[k] for k in sorted(data_by_date.keys())]

        return {
            "mode": effective_mode,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "data_points": len(data),
            "data": data,
        }

    except Exception as e:
        logger.error(f"Equity curve error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/drawdown",
    summary="Get drawdown analysis",
    description="Returns drawdown periods and recovery information."
)
async def get_drawdown_analysis(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get detailed drawdown analysis.

    Returns:
    - Current drawdown
    - Max drawdown
    - Drawdown periods
    """
    try:
        effective_mode = mode or engine_state.mode

        # Get all snapshots ordered by time
        snapshots = db.query(
            PerformanceSnapshot.timestamp,
            PerformanceSnapshot.total_equity,
            PerformanceSnapshot.drawdown,
        ).filter(
            PerformanceSnapshot.mode == effective_mode
        ).order_by(PerformanceSnapshot.timestamp).all()

        if not snapshots:
            return {
                "mode": effective_mode,
                "current_drawdown": None,
                "max_drawdown": None,
                "drawdown_periods": [],
            }

        # Calculate drawdown periods
        high_water_mark = 0.0
        max_drawdown = 0.0
        current_drawdown = 0.0
        drawdown_periods = []
        current_period_start = None

        for snapshot in snapshots:
            equity = float(snapshot.total_equity)

            if equity > high_water_mark:
                high_water_mark = equity

                # End any current drawdown period
                if current_period_start:
                    drawdown_periods.append({
                        "start": current_period_start,
                        "end": snapshot.timestamp.isoformat(),
                        "max_drawdown": current_drawdown,
                    })
                    current_period_start = None

            if high_water_mark > 0:
                dd = (high_water_mark - equity) / high_water_mark * 100

                if dd > max_drawdown:
                    max_drawdown = dd

                if dd > 0 and current_period_start is None:
                    current_period_start = snapshot.timestamp.isoformat()
                    current_drawdown = dd
                elif dd > current_drawdown:
                    current_drawdown = dd

        # Get latest drawdown
        latest = snapshots[-1]
        current = float(latest.drawdown) if latest.drawdown else 0.0

        return {
            "mode": effective_mode,
            "current_drawdown": current,
            "max_drawdown": max_drawdown,
            "high_water_mark": high_water_mark,
            "drawdown_periods": drawdown_periods[-10:],  # Last 10 periods
        }

    except Exception as e:
        logger.error(f"Drawdown analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/regime-breakdown",
    summary="Get performance by regime",
    description="Returns performance broken down by strategy regime."
)
async def get_regime_breakdown(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get performance broken down by strategy regime (cell).

    Returns average return and trade count for each cell.
    """
    try:
        effective_mode = mode or engine_state.mode

        # Get return stats by cell
        cell_stats = db.query(
            PerformanceSnapshot.strategy_cell,
            func.count(PerformanceSnapshot.id).label('days'),
            func.avg(PerformanceSnapshot.daily_return).label('avg_return'),
        ).filter(
            and_(
                PerformanceSnapshot.mode == effective_mode,
                PerformanceSnapshot.strategy_cell.isnot(None)
            )
        ).group_by(
            PerformanceSnapshot.strategy_cell
        ).all()

        # Get trade stats by cell
        trade_stats = db.query(
            LiveTrade.strategy_cell,
            func.count(LiveTrade.id).label('trades'),
        ).filter(
            and_(
                LiveTrade.mode == effective_mode,
                LiveTrade.strategy_cell.isnot(None)
            )
        ).group_by(
            LiveTrade.strategy_cell
        ).all()

        trade_map = {t.strategy_cell: t.trades for t in trade_stats}

        # Build regime breakdown
        regimes = []
        for stat in cell_stats:
            regimes.append({
                "cell": stat.strategy_cell,
                "days": stat.days,
                "avg_daily_return": float(stat.avg_return) if stat.avg_return else 0.0,
                "trades": trade_map.get(stat.strategy_cell, 0),
            })

        return {
            "mode": effective_mode,
            "regimes": sorted(regimes, key=lambda x: x['cell']),
        }

    except Exception as e:
        logger.error(f"Regime breakdown error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
