"""
Control API Routes

POST /api/control/start - Start trading engine
POST /api/control/stop - Stop trading engine
POST /api/control/restart - Restart trading engine
GET /api/control/scheduler - Get scheduler status
POST /api/control/scheduler/enable - Enable scheduled execution
POST /api/control/scheduler/disable - Disable scheduled execution
POST /api/control/scheduler/trigger - Manually trigger execution
PUT /api/control/scheduler - Update scheduler settings
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from jutsu_engine.api.schemas import (
    ControlAction,
    ControlResponse,
    ErrorResponse,
    SchedulerStatus,
    SchedulerEnableRequest,
    SchedulerTriggerResponse,
    SchedulerUpdateRequest,
    DataRefreshResponse,
    DataStalenessInfo,
)
from jutsu_engine.api.dependencies import (
    get_engine_state,
    verify_credentials,
    EngineState,
)
from jutsu_engine.api.scheduler import get_scheduler_service, EXECUTION_TIME_MAP

logger = logging.getLogger('API.CONTROL')

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post(
    "/start",
    response_model=ControlResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        409: {"model": ErrorResponse, "description": "Engine already running"},
    },
    summary="Start trading engine",
    description="Start the trading engine in the specified mode."
)
async def start_engine(
    action: ControlAction,
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> ControlResponse:
    """
    Start the trading engine.

    Args:
        action: Control action with mode specification

    Returns:
        Control response with new state
    """
    try:
        if engine_state.is_running:
            raise HTTPException(
                status_code=409,
                detail="Engine is already running"
            )

        mode = action.mode or 'offline_mock'

        # Validate mode
        if mode not in ('offline_mock', 'online_live'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode: {mode}. Must be 'offline_mock' or 'online_live'"
            )

        # Require confirmation for online mode
        if mode == 'online_live' and not action.confirm:
            raise HTTPException(
                status_code=400,
                detail="Online mode requires confirm=true"
            )

        previous_state = "stopped"

        success = engine_state.start(mode=mode)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to start engine"
            )

        logger.info(f"Engine started via API in {mode} mode")

        return ControlResponse(
            success=True,
            action="start",
            previous_state=previous_state,
            new_state=f"running ({mode})",
            message=f"Trading engine started in {mode} mode",
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Start engine error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/stop",
    response_model=ControlResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Engine not running"},
    },
    summary="Stop trading engine",
    description="Stop the currently running trading engine."
)
async def stop_engine(
    action: ControlAction,
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> ControlResponse:
    """
    Stop the trading engine.

    Returns:
        Control response with new state
    """
    try:
        if not engine_state.is_running:
            raise HTTPException(
                status_code=409,
                detail="Engine is not running"
            )

        previous_state = f"running ({engine_state.mode})"

        success = engine_state.stop()

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to stop engine"
            )

        logger.info("Engine stopped via API")

        return ControlResponse(
            success=True,
            action="stop",
            previous_state=previous_state,
            new_state="stopped",
            message="Trading engine stopped",
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stop engine error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/restart",
    response_model=ControlResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
    },
    summary="Restart trading engine",
    description="Stop and restart the trading engine."
)
async def restart_engine(
    action: ControlAction,
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> ControlResponse:
    """
    Restart the trading engine.

    If engine is running, stops it first. Then starts in the specified mode
    (or the previous mode if not specified).

    Returns:
        Control response with new state
    """
    try:
        mode = action.mode or engine_state.mode

        # Validate mode
        if mode not in ('offline_mock', 'online_live'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode: {mode}. Must be 'offline_mock' or 'online_live'"
            )

        # Require confirmation for online mode
        if mode == 'online_live' and not action.confirm:
            raise HTTPException(
                status_code=400,
                detail="Online mode requires confirm=true"
            )

        was_running = engine_state.is_running
        previous_state = f"running ({engine_state.mode})" if was_running else "stopped"

        # Stop if running
        if was_running:
            engine_state.stop()

        # Start in specified mode
        success = engine_state.start(mode=mode)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to restart engine"
            )

        logger.info(f"Engine restarted via API in {mode} mode")

        return ControlResponse(
            success=True,
            action="restart",
            previous_state=previous_state,
            new_state=f"running ({mode})",
            message=f"Trading engine restarted in {mode} mode",
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restart engine error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/state",
    summary="Get engine state",
    description="Get current engine state without full status."
)
async def get_state(
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get simplified engine state.

    Returns just the running state and mode.
    """
    return {
        "is_running": engine_state.is_running,
        "mode": engine_state.mode,
        "uptime_seconds": engine_state.get_uptime_seconds(),
        "error": engine_state.error,
    }


@router.post(
    "/mode",
    response_model=ControlResponse,
    summary="Switch trading mode",
    description="Switch between offline and online trading modes."
)
async def switch_mode(
    action: ControlAction,
    engine_state: EngineState = Depends(get_engine_state),
    _auth: bool = Depends(verify_credentials),
) -> ControlResponse:
    """
    Switch trading mode.

    If engine is running, restarts in new mode.
    If not running, just updates the mode setting.
    """
    try:
        new_mode = action.mode

        if not new_mode:
            raise HTTPException(
                status_code=400,
                detail="Mode must be specified"
            )

        if new_mode not in ('offline_mock', 'online_live'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode: {new_mode}"
            )

        # Require confirmation for online mode
        if new_mode == 'online_live' and not action.confirm:
            raise HTTPException(
                status_code=400,
                detail="Online mode requires confirm=true"
            )

        previous_mode = engine_state.mode

        if engine_state.is_running:
            # Restart in new mode
            engine_state.stop()
            engine_state.start(mode=new_mode)
            new_state = f"running ({new_mode})"
        else:
            # Just update mode
            engine_state.mode = new_mode
            new_state = f"stopped ({new_mode})"

        logger.info(f"Mode switched: {previous_mode} -> {new_mode}")

        return ControlResponse(
            success=True,
            action="mode_switch",
            previous_state=previous_mode,
            new_state=new_state,
            message=f"Mode switched from {previous_mode} to {new_mode}",
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Mode switch error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ==============================================================================
# SCHEDULER ENDPOINTS
# ==============================================================================


@router.get(
    "/scheduler",
    response_model=SchedulerStatus,
    summary="Get scheduler status",
    description="Get current scheduler status including enabled state, next run time, and last execution details."
)
async def get_scheduler_status(
    _auth: bool = Depends(verify_credentials),
) -> SchedulerStatus:
    """
    Get scheduler status.

    Returns:
        Scheduler status with enabled state, next run, last run details.
    """
    try:
        scheduler = get_scheduler_service()
        status = scheduler.get_status()
        return SchedulerStatus(**status)
    except Exception as e:
        logger.error(f"Scheduler status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/scheduler/enable",
    response_model=SchedulerStatus,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid execution time"},
    },
    summary="Enable scheduled execution",
    description="Enable automatic scheduled trading execution. Optionally set execution time."
)
async def enable_scheduler(
    request: Optional[SchedulerEnableRequest] = None,
    _auth: bool = Depends(verify_credentials),
) -> SchedulerStatus:
    """
    Enable scheduled execution.

    Optionally set the execution time when enabling.

    Args:
        request: Optional request with execution_time

    Returns:
        Updated scheduler status
    """
    try:
        scheduler = get_scheduler_service()

        # Update execution time if provided
        if request and request.execution_time:
            if request.execution_time not in EXECUTION_TIME_MAP:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid execution_time: {request.execution_time}. "
                           f"Must be one of {list(EXECUTION_TIME_MAP.keys())}"
                )
            scheduler.update_execution_time(request.execution_time)

        status = scheduler.enable()
        logger.info("Scheduler enabled via API")
        return SchedulerStatus(**status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enable scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/scheduler/disable",
    response_model=SchedulerStatus,
    summary="Disable scheduled execution",
    description="Disable automatic scheduled trading execution."
)
async def disable_scheduler(
    _auth: bool = Depends(verify_credentials),
) -> SchedulerStatus:
    """
    Disable scheduled execution.

    Returns:
        Updated scheduler status
    """
    try:
        scheduler = get_scheduler_service()
        status = scheduler.disable()
        logger.info("Scheduler disabled via API")
        return SchedulerStatus(**status)

    except Exception as e:
        logger.error(f"Disable scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/scheduler/trigger",
    response_model=SchedulerTriggerResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Job already running"},
    },
    summary="Manually trigger execution",
    description="Manually trigger trading execution immediately, bypassing the schedule."
)
async def trigger_scheduler(
    _auth: bool = Depends(verify_credentials),
) -> SchedulerTriggerResponse:
    """
    Manually trigger execution NOW.

    Runs the daily trading workflow immediately, regardless of schedule.
    Only one execution can run at a time.

    Returns:
        Trigger response with execution result
    """
    try:
        scheduler = get_scheduler_service()

        if scheduler._is_running_job:
            raise HTTPException(
                status_code=409,
                detail="A job is already running. Please wait for it to complete."
            )

        result = await scheduler.trigger_now()
        logger.info(f"Manual trigger completed: {result.get('status')}")

        return SchedulerTriggerResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trigger scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/scheduler",
    response_model=SchedulerStatus,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid execution time"},
    },
    summary="Update scheduler settings",
    description="Update scheduler settings including execution time."
)
async def update_scheduler(
    request: SchedulerUpdateRequest,
    _auth: bool = Depends(verify_credentials),
) -> SchedulerStatus:
    """
    Update scheduler settings.

    Args:
        request: Update request with execution_time

    Returns:
        Updated scheduler status
    """
    try:
        scheduler = get_scheduler_service()

        if request.execution_time not in EXECUTION_TIME_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid execution_time: {request.execution_time}. "
                       f"Must be one of {list(EXECUTION_TIME_MAP.keys())}"
            )

        status = scheduler.update_execution_time(request.execution_time)
        logger.info(f"Scheduler updated: execution_time={request.execution_time}")

        return SchedulerStatus(**status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ==============================================================================
# DATA REFRESH ENDPOINTS
# ==============================================================================


@router.get(
    "/refresh/status",
    response_model=DataStalenessInfo,
    summary="Check data staleness",
    description="Check if dashboard data is stale and needs refresh."
)
async def check_data_staleness(
    threshold_hours: float = 1.0,
    _auth: bool = Depends(verify_credentials),
) -> DataStalenessInfo:
    """
    Check if dashboard data is stale.
    
    Args:
        threshold_hours: Maximum age in hours before data is considered stale
        
    Returns:
        Staleness information including last snapshot time and age
    """
    try:
        from jutsu_engine.live.data_refresh import get_data_refresher
        
        refresher = get_data_refresher()
        is_stale, last_time = refresher.check_if_stale(threshold_hours)
        
        # Calculate age if we have a last time
        age_hours = None
        if last_time:
            from datetime import timezone
            now = datetime.now(timezone.utc)
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            age_hours = (now - last_time).total_seconds() / 3600
        
        return DataStalenessInfo(
            is_stale=is_stale,
            last_snapshot=last_time.isoformat() if last_time else None,
            age_hours=round(age_hours, 2) if age_hours else None,
            threshold_hours=threshold_hours,
        )
        
    except Exception as e:
        logger.error(f"Check staleness error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/refresh",
    response_model=DataRefreshResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Refresh already running"},
    },
    summary="Refresh dashboard data",
    description="Manually trigger a dashboard data refresh. Updates prices, P&L, and performance snapshot without running the trading strategy."
)
async def trigger_data_refresh(
    sync_data: bool = True,
    _auth: bool = Depends(verify_credentials),
) -> DataRefreshResponse:
    """
    Manually trigger a data refresh.
    
    Updates:
    - Market data sync (if enabled)
    - Position prices from Schwab API
    - Position market values
    - Performance snapshot with P&L calculations
    
    Does NOT:
    - Run the trading strategy
    - Execute any trades
    - Change allocations
    
    Args:
        sync_data: Whether to sync market data first (slower but more complete)
        
    Returns:
        Refresh result with details
    """
    try:
        scheduler = get_scheduler_service()
        
        if scheduler._is_running_refresh:
            raise HTTPException(
                status_code=409,
                detail="A data refresh is already running. Please wait for it to complete."
            )
        
        result = await scheduler.trigger_data_refresh()
        logger.info(f"Manual data refresh completed: {result.get('success')}")
        
        return DataRefreshResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Data refresh error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
