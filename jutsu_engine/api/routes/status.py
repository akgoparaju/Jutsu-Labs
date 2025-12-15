"""
Status API Routes

GET /api/status - System status, regime, and portfolio information
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from jutsu_engine.api.schemas import (
    SystemStatus,
    RegimeInfo,
    PortfolioInfo,
    PositionInfo,
    ErrorResponse,
)
from jutsu_engine.api.dependencies import (
    get_db,
    get_engine_state,
    get_strategy_runner,
    verify_credentials,
    EngineState,
)
from jutsu_engine.data.models import Position, PerformanceSnapshot

logger = logging.getLogger('API.STATUS')

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get(
    "",
    response_model=SystemStatus,
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get system status",
    description="Returns current system status including mode, regime, and portfolio."
)
async def get_status(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> SystemStatus:
    """
    Get complete system status.

    Returns:
        - Trading mode (offline_mock or online_live)
        - Engine running state
        - Last/next execution times
        - Current strategy regime
        - Portfolio summary with positions
    """
    try:
        # Build regime info - prefer database snapshot over live strategy context
        # The live strategy context may have stale/default values if the engine
        # hasn't processed bars recently. The database snapshot is the source of truth.
        regime_info = None
        try:
            # First try to get from latest performance snapshot (source of truth)
            latest_snapshot = db.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == engine_state.mode
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()

            if latest_snapshot and latest_snapshot.strategy_cell is not None:
                # Use database snapshot values (most accurate for cell/trend/vol)
                # But supplement with live strategy context for t_norm/z_score
                t_norm_val = None
                z_score_val = None
                try:
                    runner = get_strategy_runner()
                    context = runner.get_strategy_context()
                    if context:
                        t_norm_val = context.get('t_norm')
                        z_score_val = context.get('z_score')
                except Exception as e:
                    logger.debug(f"Could not get live indicators: {e}")

                regime_info = RegimeInfo(
                    cell=latest_snapshot.strategy_cell,
                    trend_state=latest_snapshot.trend_state,
                    vol_state=latest_snapshot.vol_state,
                    t_norm=t_norm_val,
                    z_score=z_score_val,
                )
                logger.debug(f"Regime from snapshot: Cell {latest_snapshot.strategy_cell}")
            else:
                # Fall back to live strategy context if no snapshot
                runner = get_strategy_runner()
                context = runner.get_strategy_context()

                if context:
                    cell = context.get('current_cell')
                    trend = context.get('trend_state')
                    vol = context.get('vol_state')

                    regime_info = RegimeInfo(
                        cell=cell if cell is not None else None,
                        trend_state=trend if trend else None,
                        vol_state=vol if vol else None,
                        t_norm=context.get('t_norm'),
                        z_score=context.get('z_score'),
                    )
        except Exception as e:
            logger.warning(f"Could not get regime info: {e}")

        # Build portfolio info
        portfolio_info = None
        try:
            # Get positions from database
            positions = db.query(Position).filter(
                Position.mode == engine_state.mode
            ).all()

            position_list = []
            total_value = 0.0

            for pos in positions:
                mv = float(pos.market_value) if pos.market_value else 0.0
                total_value += mv

                position_list.append(PositionInfo(
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    avg_cost=float(pos.avg_cost) if pos.avg_cost else None,
                    market_value=mv if mv else None,
                    unrealized_pnl=float(pos.unrealized_pnl) if pos.unrealized_pnl else None,
                ))

            # Get latest performance snapshot for equity
            latest_snapshot = db.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == engine_state.mode
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()

            total_equity = float(latest_snapshot.total_equity) if latest_snapshot else total_value
            cash = float(latest_snapshot.cash) if latest_snapshot and latest_snapshot.cash else None

            # Calculate position weights
            if total_equity > 0:
                for pos_info in position_list:
                    if pos_info.market_value:
                        pos_info.weight_pct = (pos_info.market_value / total_equity) * 100

            portfolio_info = PortfolioInfo(
                total_equity=total_equity,
                cash=cash,
                positions_value=total_value if total_value > 0 else None,
                positions=position_list,
            )

        except Exception as e:
            logger.warning(f"Could not build portfolio info: {e}")

        # Parse timestamps
        last_exec = None
        next_exec = None

        if engine_state.last_execution:
            try:
                last_exec = datetime.fromisoformat(
                    engine_state.last_execution.replace('Z', '+00:00')
                )
            except ValueError:
                pass

        # Fallback: use latest performance snapshot timestamp if no execution recorded
        if last_exec is None:
            try:
                latest_snapshot = db.query(PerformanceSnapshot.timestamp).filter(
                    PerformanceSnapshot.mode == engine_state.mode
                ).order_by(desc(PerformanceSnapshot.timestamp)).first()

                if latest_snapshot:
                    last_exec = latest_snapshot.timestamp
            except Exception as e:
                logger.warning(f"Could not get latest snapshot timestamp: {e}")

        if engine_state.next_execution:
            try:
                next_exec = datetime.fromisoformat(
                    engine_state.next_execution.replace('Z', '+00:00')
                )
            except ValueError:
                pass

        return SystemStatus(
            mode=engine_state.mode,
            is_running=engine_state.is_running,
            last_execution=last_exec,
            next_execution=next_exec,
            regime=regime_info,
            portfolio=portfolio_info,
            uptime_seconds=engine_state.get_uptime_seconds(),
            error=engine_state.error,
        )

    except Exception as e:
        logger.error(f"Status endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/health",
    summary="Health check",
    description="Simple health check endpoint for monitoring."
)
async def health_check() -> dict:
    """
    Health check endpoint.

    Returns:
        Simple OK status with timestamp.
    """
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "jutsu-api",
    }


@router.get(
    "/regime",
    response_model=RegimeInfo,
    responses={
        503: {"model": ErrorResponse, "description": "Strategy not available"}
    },
    summary="Get current regime",
    description="Returns just the current strategy regime information."
)
async def get_regime(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> RegimeInfo:
    """
    Get current strategy regime.

    Returns cell, trend state, volatility state, and indicator values.
    Prefers database snapshot (source of truth) over live strategy context.
    """
    try:
        # First try to get from latest performance snapshot (source of truth)
        latest_snapshot = db.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.mode == engine_state.mode
        ).order_by(desc(PerformanceSnapshot.timestamp)).first()

        if latest_snapshot and latest_snapshot.strategy_cell is not None:
            # Use database snapshot values (most accurate for cell/trend/vol)
            # But supplement with live strategy context for t_norm/z_score
            t_norm_val = None
            z_score_val = None
            try:
                runner = get_strategy_runner()
                context = runner.get_strategy_context()
                if context:
                    t_norm_val = context.get('t_norm')
                    z_score_val = context.get('z_score')
            except Exception as e:
                logger.debug(f"Could not get live indicators: {e}")

            return RegimeInfo(
                cell=latest_snapshot.strategy_cell,
                trend_state=latest_snapshot.trend_state,
                vol_state=latest_snapshot.vol_state,
                t_norm=t_norm_val,
                z_score=z_score_val,
            )

        # Fall back to live strategy context if no snapshot
        runner = get_strategy_runner()
        context = runner.get_strategy_context()

        if not context:
            raise HTTPException(
                status_code=503,
                detail="Strategy context not available"
            )

        cell = context.get('current_cell')
        trend = context.get('trend_state')
        vol = context.get('vol_state')

        return RegimeInfo(
            cell=cell if cell is not None else None,
            trend_state=trend if trend else None,
            vol_state=vol if vol else None,
            t_norm=context.get('t_norm'),
            z_score=context.get('z_score'),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Regime endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
