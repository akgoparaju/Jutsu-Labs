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
    days: int = Query(90, ge=0, description="Days of history (0 for all data)"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format) for custom range"),
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
        filter_start_date = None
        
        if start_date:
            # Custom start date provided (for YTD or custom range)
            try:
                filter_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                if filter_start_date.tzinfo is None:
                    filter_start_date = filter_start_date.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format.")
        elif days > 0:
            # Days-based filtering
            filter_start_date = end_date - timedelta(days=days)
        # If days=0 and no start_date, filter_start_date remains None (ALL data)

        # Get historical snapshots
        history_filters = [PerformanceSnapshot.mode == effective_mode]
        if filter_start_date:
            history_filters.append(PerformanceSnapshot.timestamp >= filter_start_date)
        
        history_query = db.query(PerformanceSnapshot).filter(
            and_(*history_filters)
        ).order_by(PerformanceSnapshot.timestamp)

        history = history_query.all()

        # Calculate trade statistics
        trade_stats = db.query(
            func.count(LiveTrade.id).label('total'),
        ).filter(
            LiveTrade.mode == effective_mode
        ).first()

        total_trades = trade_stats.total if trade_stats else 0

        # Calculate win rate, winning_trades, losing_trades from round-trip trades
        # Using FIFO matching: BUYs are matched with subsequent SELLs
        from collections import defaultdict

        win_rate_value = None
        winning_trades = 0
        losing_trades = 0
        total_round_trips = 0

        # Get all trades ordered by timestamp for P&L matching
        all_trades = db.query(LiveTrade).filter(
            LiveTrade.mode == effective_mode
        ).order_by(LiveTrade.timestamp).all()

        # Track open positions by symbol (FIFO queue of BUY trades)
        open_positions = defaultdict(list)

        for trade in all_trades:
            if not trade.fill_price or not trade.quantity:
                continue

            fill_price = float(trade.fill_price)
            quantity = trade.quantity

            if trade.action == 'BUY':
                open_positions[trade.symbol].append({
                    'quantity': quantity,
                    'fill_price': fill_price,
                })
            elif trade.action == 'SELL':
                remaining_to_sell = quantity

                while remaining_to_sell > 0 and open_positions[trade.symbol]:
                    buy_trade = open_positions[trade.symbol][0]
                    buy_qty = buy_trade['quantity']
                    buy_price = buy_trade['fill_price']

                    close_qty = min(remaining_to_sell, buy_qty)
                    pnl = (fill_price - buy_price) * close_qty
                    total_round_trips += 1

                    if pnl > 0:
                        winning_trades += 1
                    else:
                        losing_trades += 1

                    remaining_to_sell -= close_qty
                    buy_trade['quantity'] -= close_qty

                    if buy_trade['quantity'] <= 0:
                        open_positions[trade.symbol].pop(0)

        # Calculate win rate as decimal (0-1 range for frontend compatibility)
        if total_round_trips > 0:
            win_rate_value = winning_trades / total_round_trips

        # Get high water mark for accurate drawdown
        hwm_result = db.query(
            func.max(PerformanceSnapshot.total_equity)
        ).filter(
            PerformanceSnapshot.mode == effective_mode
        ).first()

        high_water_mark = float(hwm_result[0]) if hwm_result and hwm_result[0] else None

        # Get max drawdown from all snapshots (historical maximum)
        max_dd_result = db.query(
            func.max(PerformanceSnapshot.drawdown)
        ).filter(
            PerformanceSnapshot.mode == effective_mode
        ).first()

        max_drawdown = float(max_dd_result[0]) if max_dd_result and max_dd_result[0] else None

        # Calculate Sharpe Ratio from daily returns
        # Sharpe = (Mean Return - Risk Free Rate) / Std Dev of Returns
        # Using annualized Sharpe with risk-free rate ≈ 0
        # IMPORTANT: Deduplicate to one snapshot per day (latest) to avoid skewing metrics
        sharpe_ratio = None
        if history:
            import math
            # Deduplicate: take latest snapshot per day for accurate daily returns
            daily_snapshots = {}
            for snap in history:
                if snap.daily_return is not None and snap.timestamp:
                    day_key = snap.timestamp.date()
                    # Keep the latest snapshot for each day
                    if day_key not in daily_snapshots or snap.timestamp > daily_snapshots[day_key].timestamp:
                        daily_snapshots[day_key] = snap
            
            daily_returns = [
                float(snap.daily_return)
                for snap in daily_snapshots.values()
            ]
            if len(daily_returns) >= 2:
                mean_return = sum(daily_returns) / len(daily_returns)
                variance = sum((r - mean_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
                std_dev = math.sqrt(variance) if variance > 0 else 0
                if std_dev > 0:
                    # Annualize: multiply by sqrt(252 trading days)
                    sharpe_ratio = (mean_return / std_dev) * math.sqrt(252)

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
            max_drawdown=max_drawdown,
            high_water_mark=high_water_mark,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate_value,
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
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/equity-curve",
    summary="Get equity curve data",
    description="Returns equity curve data for charting."
)
async def get_equity_curve(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    days: int = Query(90, ge=0, description="Days of history (0 for all data)"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format) for custom range"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get equity curve data optimized for charting.

    Returns arrays of dates and values for lightweight-charts.
    """
    try:
        effective_mode = mode or engine_state.mode

        end_date = datetime.now(timezone.utc)
        filter_start_date = None
        
        if start_date:
            # Custom start date provided (for YTD or custom range)
            try:
                filter_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                if filter_start_date.tzinfo is None:
                    filter_start_date = filter_start_date.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format.")
        elif days > 0:
            # Days-based filtering
            filter_start_date = end_date - timedelta(days=days)
        # If days=0 and no start_date, filter_start_date remains None (ALL data)

        # Build query filters
        query_filters = [PerformanceSnapshot.mode == effective_mode]
        if filter_start_date:
            query_filters.append(PerformanceSnapshot.timestamp >= filter_start_date)

        # Query all snapshots for P/L data (value, return, baseline)
        # Latest per day wins for financial data (refresh snapshots update P/L)
        snapshots = db.query(
            PerformanceSnapshot.timestamp,
            PerformanceSnapshot.total_equity,
            PerformanceSnapshot.cumulative_return,
            PerformanceSnapshot.baseline_value,
            PerformanceSnapshot.baseline_return,
        ).filter(
            and_(*query_filters)
        ).order_by(PerformanceSnapshot.timestamp).all()

        # Query ONLY scheduler snapshots for regime data (authoritative source)
        # Architecture Decision (2026-01-15): Regime is ONLY written by scheduler
        # Refresh snapshots have NULL regime (correct behavior)
        scheduler_filters = query_filters + [PerformanceSnapshot.snapshot_source == 'scheduler']
        scheduler_snapshots = db.query(
            PerformanceSnapshot.timestamp,
            PerformanceSnapshot.strategy_cell,
        ).filter(
            and_(*scheduler_filters)
        ).order_by(PerformanceSnapshot.timestamp).all()

        # Build regime lookup by date (latest scheduler snapshot per day)
        regime_by_date = {}
        for snapshot in scheduler_snapshots:
            date_key = snapshot.timestamp.strftime('%Y-%m-%d')
            regime_by_date[date_key] = snapshot.strategy_cell

        # Format for charting - deduplicate by date (keep latest per day)
        # lightweight-charts requires unique ascending timestamps
        data_by_date = {}
        for snapshot in snapshots:
            date_key = snapshot.timestamp.strftime('%Y-%m-%d')
            # Later entries overwrite earlier ones (keeping latest per day for P/L)
            data_by_date[date_key] = {
                "time": date_key,
                "value": float(snapshot.total_equity),
                "return": float(snapshot.cumulative_return) if snapshot.cumulative_return else 0.0,
                "regime": regime_by_date.get(date_key),  # Only from scheduler snapshots
                "baseline_value": float(snapshot.baseline_value) if snapshot.baseline_value is not None else None,
                "baseline_return": float(snapshot.baseline_return) if snapshot.baseline_return is not None else None,
            }

        # Convert to sorted list (ascending by date)
        data = [data_by_date[k] for k in sorted(data_by_date.keys())]

        return {
            "mode": effective_mode,
            "start_date": filter_start_date.isoformat() if filter_start_date else None,
            "end_date": end_date.isoformat(),
            "data_points": len(data),
            "data": data,
        }

    except Exception as e:
        logger.error(f"Equity curve error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/regime-breakdown",
    summary="Get performance by regime",
    description="Returns performance broken down by strategy regime."
)
async def get_regime_breakdown(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    days: int = Query(0, ge=0, description="Days of history (0 for all data)"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format) for custom range"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get performance broken down by strategy regime (cell).

    Returns average return, total return, trade count, and win rate for each cell.
    Supports time range filtering via days or start_date parameters.
    """
    try:
        logger.info(f"Regime breakdown request: mode={mode}, days={days}, start_date={start_date}")
        effective_mode = mode or engine_state.mode

        # Calculate date range (same logic as get_performance)
        end_date = datetime.now(timezone.utc)
        filter_start_date = None

        if start_date:
            # Custom start date provided (for YTD or custom range)
            try:
                filter_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                if filter_start_date.tzinfo is None:
                    filter_start_date = filter_start_date.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format.")
        elif days > 0:
            # Days-based filtering
            filter_start_date = end_date - timedelta(days=days)
        # If days=0 and no start_date, filter_start_date remains None (ALL data)

        logger.info(f"Regime breakdown: filter_start_date={filter_start_date}, end_date={end_date}")

        # Build base filter conditions
        base_filters = [
            PerformanceSnapshot.mode == effective_mode,
            PerformanceSnapshot.strategy_cell.isnot(None)
        ]
        if filter_start_date:
            base_filters.append(PerformanceSnapshot.timestamp >= filter_start_date)

        # Get return stats by cell with trend_state and vol_state
        # Use a subquery to get the most common trend/vol state per cell
        # IMPORTANT: Count unique dates, not rows (there can be multiple snapshots per day)
        cell_stats = db.query(
            PerformanceSnapshot.strategy_cell,
            func.count(func.distinct(func.date(PerformanceSnapshot.timestamp))).label('days'),
            func.avg(PerformanceSnapshot.daily_return).label('avg_return'),
            func.sum(PerformanceSnapshot.daily_return).label('total_return'),
        ).filter(
            and_(*base_filters)
        ).group_by(
            PerformanceSnapshot.strategy_cell
        ).all()

        logger.info(f"Regime breakdown: found {len(cell_stats)} cells, total_days={sum(s.days or 0 for s in cell_stats)}")

        # Get trend_state and vol_state for each cell (most common value)
        cell_regime_info = {}
        for cell in set(s.strategy_cell for s in cell_stats):
            # Get the most common trend/vol state for this cell (with date filter)
            cell_filter = [
                PerformanceSnapshot.mode == effective_mode,
                PerformanceSnapshot.strategy_cell == cell,
                PerformanceSnapshot.trend_state.isnot(None),
                PerformanceSnapshot.vol_state.isnot(None)
            ]
            if filter_start_date:
                cell_filter.append(PerformanceSnapshot.timestamp >= filter_start_date)

            regime_sample = db.query(
                PerformanceSnapshot.trend_state,
                PerformanceSnapshot.vol_state
            ).filter(
                and_(*cell_filter)
            ).first()
            if regime_sample:
                cell_regime_info[cell] = {
                    'trend_state': regime_sample.trend_state,
                    'vol_state': regime_sample.vol_state
                }

        # Get trade stats by cell including win/loss calculation
        # A "winning" trade needs to be calculated from matched BUY/SELL pairs
        # For now, we'll calculate based on profitable SELL trades
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

        # Calculate win rate per cell based on daily returns
        # A day is "winning" if daily_return > 0
        win_filters = [
            PerformanceSnapshot.mode == effective_mode,
            PerformanceSnapshot.strategy_cell.isnot(None),
            PerformanceSnapshot.daily_return > 0
        ]
        if filter_start_date:
            win_filters.append(PerformanceSnapshot.timestamp >= filter_start_date)

        # Count unique winning dates (not rows) for accurate win rate
        win_stats = db.query(
            PerformanceSnapshot.strategy_cell,
            func.count(func.distinct(func.date(PerformanceSnapshot.timestamp))).label('winning_days'),
        ).filter(
            and_(*win_filters)
        ).group_by(
            PerformanceSnapshot.strategy_cell
        ).all()

        win_map = {w.strategy_cell: w.winning_days for w in win_stats}

        # Build regime breakdown
        regimes = []
        for stat in cell_stats:
            cell = stat.strategy_cell
            days = stat.days or 1  # Avoid division by zero
            winning_days = win_map.get(cell, 0)
            win_rate = winning_days / days if days > 0 else 0.0

            regime_info = cell_regime_info.get(cell, {})

            regimes.append({
                "cell": cell,
                "trend_state": regime_info.get('trend_state', ''),
                "vol_state": regime_info.get('vol_state', ''),
                "trade_count": trade_map.get(cell, 0),
                "win_rate": win_rate,
                "avg_return": float(stat.avg_return) if stat.avg_return else 0.0,
                "total_return": float(stat.total_return) if stat.total_return else 0.0,
                # Keep legacy fields for backwards compatibility
                "days": days,
                "trades": trade_map.get(cell, 0),
                "avg_daily_return": float(stat.avg_return) if stat.avg_return else 0.0,
            })

        return {
            "mode": effective_mode,
            "regimes": sorted(regimes, key=lambda x: x['cell']),
        }

    except Exception as e:
        logger.error(f"Regime breakdown error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
