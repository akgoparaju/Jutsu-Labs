"""
Indicators API Routes

GET /api/indicators - Get current indicator values
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from jutsu_engine.api.schemas import (
    IndicatorsResponse,
    IndicatorValue,
    ErrorResponse,
)
from jutsu_engine.api.dependencies import (
    get_strategy_runner,
    verify_credentials,
    get_db,
    get_engine_state,
    EngineState,
)
from jutsu_engine.data.models import PerformanceSnapshot

logger = logging.getLogger('API.INDICATORS')

router = APIRouter(prefix="/api/indicators", tags=["indicators"])


# Indicator descriptions
INDICATOR_DESCRIPTIONS = {
    'sma_fast': 'QQQ 40-day Simple Moving Average',
    'sma_slow': 'QQQ 140-day Simple Moving Average',
    'sma_trend': 'Trend Simple Moving Average',
    'vol_crush_triggered': 'Vol-Crush Override Status',
    'bond_sma_fast': 'TLT 20-day Simple Moving Average',
    'bond_sma_slow': 'TLT 60-day Simple Moving Average',
    'bond_trend': 'Bond Trend (TLT SMA crossover)',
    't_norm': 'Normalized Trend Indicator (-1 to 1)',
    'z_score': 'Volatility Z-Score',
    'vol_state': 'Volatility State (Low/High)',
    'trend_state': 'Trend State (BullStrong/Sideways/BearStrong)',
    'current_cell': 'Strategy Regime Cell (1-6)',
    'treasury_score': 'Treasury Overlay Score',
    'hysteresis_state': 'Hysteresis State Machine Value',
}


def get_target_allocation_for_cell(cell_id: int, bond_trend: Optional[str] = None) -> dict:
    """
    Return theoretical target allocation based on 6-Cell matrix.

    Cell allocations (from strategy docs):
    - Cell 1 (Bull/Low): 60% TQQQ, 40% QQQ
    - Cell 2 (Bull/High): 100% QQQ
    - Cell 3 (Sideways/Low): 20% TQQQ, 80% QQQ
    - Cell 4 (Sideways/High): 100% Defensive (Treasury Overlay)
    - Cell 5 (Bear/Low): 50% QQQ, 50% Defensive
    - Cell 6 (Bear/High): 100% Defensive

    Args:
        cell_id: Current strategy cell (1-6)
        bond_trend: Bond trend ("Bull" or "Bear") for treasury overlay

    Returns:
        Target allocation dict with percentages for each symbol
    """
    allocations = {
        1: {'TQQQ': 60.0, 'QQQ': 40.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 0.0},
        2: {'TQQQ': 0.0, 'QQQ': 100.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 0.0},
        3: {'TQQQ': 20.0, 'QQQ': 80.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 0.0},
        4: {'TQQQ': 0.0, 'QQQ': 0.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 100.0},  # Treasury Overlay applies
        5: {'TQQQ': 0.0, 'QQQ': 50.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 50.0},  # Treasury Overlay applies
        6: {'TQQQ': 0.0, 'QQQ': 0.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 100.0},  # Treasury Overlay applies
    }

    base = allocations.get(cell_id, {'TQQQ': 0.0, 'QQQ': 0.0, 'PSQ': 0.0, 'TMF': 0.0, 'TMV': 0.0, 'CASH': 100.0})

    # Apply Treasury Overlay for defensive cells (4, 5, 6)
    if cell_id in [4, 5, 6] and bond_trend:
        cash_portion = base['CASH']
        if cash_portion > 0:
            # 40% of defensive goes to bonds, 60% stays cash (max 40% bond allocation)
            bond_allocation = min(cash_portion * 0.4, 40.0)
            remaining_cash = cash_portion - bond_allocation

            if bond_trend == 'Bull':
                base['TMF'] = bond_allocation
            else:
                base['TMV'] = bond_allocation
            base['CASH'] = remaining_cash

    return base


def get_signal_for_indicator(name: str, value: float) -> Optional[str]:
    """Get signal description for indicator value."""
    if name == 't_norm':
        if value > 0.5:
            return 'Strong Bull'
        elif value > 0:
            return 'Weak Bull'
        elif value > -0.5:
            return 'Weak Bear'
        else:
            return 'Strong Bear'
    elif name == 'z_score':
        if value > 2:
            return 'Extreme High Vol'
        elif value > 1:
            return 'High Vol'
        elif value > -1:
            return 'Normal Vol'
        else:
            return 'Low Vol'
    return None


@router.get(
    "",
    response_model=IndicatorsResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Strategy not available"}
    },
    summary="Get current indicator values",
    description="Returns all current indicator values from the strategy."
)
async def get_indicators(
    db: Session = Depends(get_db),
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> IndicatorsResponse:
    """
    Get current indicator values.

    Returns:
    - All strategy indicators with current values
    - Signal descriptions where applicable
    - Indicator descriptions

    Note: Core regime indicators (current_cell, trend_state, vol_state) are
    sourced from the database snapshot (source of truth) rather than the
    live strategy context, which may have stale values if the engine hasn't
    processed bars recently.
    """
    try:
        runner = get_strategy_runner()
        state = runner.get_strategy_state()
        context = runner.get_strategy_context()

        if not context:
            raise HTTPException(
                status_code=503,
                detail="Strategy context not available"
            )

        indicators = []

        # Get regime indicators from SCHEDULER snapshot (authoritative source)
        # Architecture decision 2026-01-14: Scheduler is authoritative for regime,
        # P/L refresh snapshots intentionally do NOT contain regime fields.
        # Priority: scheduler snapshot > any snapshot with regime > live context
        db_cell = None
        db_trend = None
        db_vol = None
        regime_source = None

        try:
            # First: Try to get regime from scheduler snapshot (authoritative)
            scheduler_snapshot = db.query(PerformanceSnapshot).filter(
                PerformanceSnapshot.mode == engine_state.mode,
                PerformanceSnapshot.snapshot_source == "scheduler"
            ).order_by(desc(PerformanceSnapshot.timestamp)).first()

            if scheduler_snapshot and scheduler_snapshot.strategy_cell is not None:
                db_cell = scheduler_snapshot.strategy_cell
                db_trend = scheduler_snapshot.trend_state
                db_vol = scheduler_snapshot.vol_state
                regime_source = "scheduler"
                logger.debug(f"Regime from scheduler snapshot: Cell {db_cell}, Trend {db_trend}, Vol {db_vol}")
            else:
                # Fallback: Try any snapshot with regime data (backward compatibility)
                any_regime_snapshot = db.query(PerformanceSnapshot).filter(
                    PerformanceSnapshot.mode == engine_state.mode,
                    PerformanceSnapshot.strategy_cell.isnot(None)
                ).order_by(desc(PerformanceSnapshot.timestamp)).first()

                if any_regime_snapshot:
                    db_cell = any_regime_snapshot.strategy_cell
                    db_trend = any_regime_snapshot.trend_state
                    db_vol = any_regime_snapshot.vol_state
                    regime_source = any_regime_snapshot.snapshot_source or "legacy"
                    logger.debug(f"Regime from {regime_source} snapshot: Cell {db_cell}, Trend {db_trend}, Vol {db_vol}")
        except Exception as e:
            logger.warning(f"Could not get regime from DB snapshot: {e}")

        # Core regime indicators - prefer DB snapshot, fall back to live context
        # current_cell
        cell_value = db_cell if db_cell is not None else context.get('current_cell')
        if cell_value is not None:
            indicators.append(IndicatorValue(
                name='current_cell',
                value=float(cell_value),
                signal=f"Cell {cell_value}",
                description=INDICATOR_DESCRIPTIONS.get('current_cell'),
            ))

        # t_norm and z_score always from live context (not stored in snapshot)
        if 't_norm' in context and context['t_norm'] is not None:
            t_norm = context['t_norm']
            indicators.append(IndicatorValue(
                name='t_norm',
                value=float(t_norm),
                signal=get_signal_for_indicator('t_norm', t_norm),
                description=INDICATOR_DESCRIPTIONS.get('t_norm'),
            ))

        if 'z_score' in context and context['z_score'] is not None:
            z_score = context['z_score']
            indicators.append(IndicatorValue(
                name='z_score',
                value=float(z_score),
                signal=get_signal_for_indicator('z_score', z_score),
                description=INDICATOR_DESCRIPTIONS.get('z_score'),
            ))

        # State indicators - prefer DB snapshot, fall back to live context
        trend_state = db_trend if db_trend is not None else context.get('trend_state')
        if trend_state is not None:
            trend_map = {'BullStrong': 2, 'BullWeak': 1, 'Sideways': 0, 'BearWeak': -1, 'BearStrong': -2}
            trend_value = trend_map.get(trend_state, 0)
            indicators.append(IndicatorValue(
                name='trend_state',
                value=float(trend_value),
                signal=trend_state,
                description=INDICATOR_DESCRIPTIONS.get('trend_state'),
            ))

        vol_state = db_vol if db_vol is not None else context.get('vol_state')
        if vol_state is not None:
            vol_value = 1.0 if vol_state == 'High' else 0.0
            indicators.append(IndicatorValue(
                name='vol_state',
                value=vol_value,
                signal=vol_state,
                description=INDICATOR_DESCRIPTIONS.get('vol_state'),
            ))

        # Decision tree indicators - SMA indicators
        if 'sma_fast' in context and context['sma_fast'] is not None:
            indicators.append(IndicatorValue(
                name='sma_fast',
                value=float(context['sma_fast']),
                description=INDICATOR_DESCRIPTIONS.get('sma_fast'),
            ))

        if 'sma_slow' in context and context['sma_slow'] is not None:
            indicators.append(IndicatorValue(
                name='sma_slow',
                value=float(context['sma_slow']),
                description=INDICATOR_DESCRIPTIONS.get('sma_slow'),
            ))

        # Vol-crush override indicator
        indicators.append(IndicatorValue(
            name='vol_crush_triggered',
            value=1.0 if context.get('vol_crush_triggered', False) else 0.0,
            signal='ACTIVE' if context.get('vol_crush_triggered', False) else 'Inactive',
            description=INDICATOR_DESCRIPTIONS.get('vol_crush_triggered'),
        ))

        # Bond indicators (only present in defensive cells)
        if context.get('bond_sma_fast') is not None:
            indicators.append(IndicatorValue(
                name='bond_sma_fast',
                value=float(context['bond_sma_fast']),
                description=INDICATOR_DESCRIPTIONS.get('bond_sma_fast'),
            ))

        if context.get('bond_sma_slow') is not None:
            indicators.append(IndicatorValue(
                name='bond_sma_slow',
                value=float(context['bond_sma_slow']),
                description=INDICATOR_DESCRIPTIONS.get('bond_sma_slow'),
            ))

        if context.get('bond_trend') is not None:
            indicators.append(IndicatorValue(
                name='bond_trend',
                value=1.0 if context['bond_trend'] == 'Bull' else 0.0,
                signal=context['bond_trend'],
                description=INDICATOR_DESCRIPTIONS.get('bond_trend'),
            ))

        # SMA indicators from state
        if state:
            for key in ['sma_fast', 'sma_slow', 'sma_trend']:
                if key in state and state[key] is not None:
                    indicators.append(IndicatorValue(
                        name=key,
                        value=float(state[key]),
                        description=INDICATOR_DESCRIPTIONS.get(key),
                    ))

        # Weight indicators
        weight_keys = [
            'current_tqqq_weight', 'current_qqq_weight', 'current_psq_weight',
            'current_tmf_weight', 'current_tmv_weight'
        ]
        for key in weight_keys:
            if state and key in state and state[key] is not None:
                indicators.append(IndicatorValue(
                    name=key,
                    value=float(state[key]) * 100,  # Convert to percentage
                    signal=f"{float(state[key])*100:.1f}%",
                    description=f"Current {key.replace('current_', '').replace('_weight', '').upper()} allocation",
                ))

        # Get target allocation based on current cell (use cell_value which prefers DB snapshot)
        bond_trend = context.get('bond_trend')
        target_allocation = get_target_allocation_for_cell(int(cell_value), bond_trend) if cell_value else None

        return IndicatorsResponse(
            timestamp=datetime.now(timezone.utc),
            indicators=indicators,
            symbol=runner.get_all_symbols()[0] if runner.get_all_symbols() else 'QQQ',
            target_allocation=target_allocation,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Indicators endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/history",
    summary="Get indicator history",
    description="Returns historical indicator values for charting."
)
async def get_indicator_history(
    indicator: str = Query(..., description="Indicator name"),
    days: int = Query(30, ge=1, le=365, description="Days of history"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get historical values for a specific indicator.

    Note: This is a placeholder - would need to store indicator
    history separately or derive from performance snapshots.
    """
    try:
        # For now, return empty - would need indicator history storage
        return {
            "indicator": indicator,
            "days": days,
            "message": "Indicator history not yet implemented",
            "data": [],
        }

    except Exception as e:
        logger.error(f"Indicator history error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/descriptions",
    summary="Get indicator descriptions",
    description="Returns descriptions for all available indicators."
)
async def get_indicator_descriptions(
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get descriptions for all indicators.
    """
    return {
        "indicators": INDICATOR_DESCRIPTIONS,
    }
