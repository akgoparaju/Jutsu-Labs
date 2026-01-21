"""
Live Trading Strategies API Routes

Provides REST API for listing active strategies, retrieving strategy details,
and accessing strategy state. Part of the Multi-Strategy Engine implementation.

GET /api/strategies - List all registered strategies
GET /api/strategies/{id} - Get strategy details
GET /api/strategies/{id}/state - Get strategy state
GET /api/strategies/status - Get status for all active strategies
"""

import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from jutsu_engine.api.schemas import ErrorResponse
from jutsu_engine.api.dependencies import verify_credentials
from jutsu_engine.live.strategy_registry import StrategyRegistry, StrategyConfig
from jutsu_engine.live.multi_state_manager import MultiStrategyStateManager

logger = logging.getLogger('API.STRATEGIES')

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# Singleton instances (lazy loaded)
_registry: Optional[StrategyRegistry] = None
_state_manager: Optional[MultiStrategyStateManager] = None


def get_registry() -> StrategyRegistry:
    """Get or create the strategy registry singleton."""
    global _registry
    if _registry is None:
        try:
            _registry = StrategyRegistry(Path("config/strategies_registry.yaml"))
        except FileNotFoundError:
            logger.warning("Strategy registry not found, using empty registry")
            raise HTTPException(
                status_code=503,
                detail="Strategy registry not configured. Create config/strategies_registry.yaml"
            )
    return _registry


def get_state_manager() -> MultiStrategyStateManager:
    """Get or create the multi-strategy state manager singleton."""
    global _state_manager
    if _state_manager is None:
        registry = get_registry()
        _state_manager = MultiStrategyStateManager(registry)
    return _state_manager


@router.get(
    "",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
        503: {"model": ErrorResponse, "description": "Strategy registry not configured"}
    },
    summary="List all strategies",
    description="Returns all registered trading strategies with their configuration."
)
async def list_strategies(
    active_only: bool = Query(True, description="Only return active strategies"),
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    List all registered trading strategies.

    Returns:
    - strategies: List of strategy info objects
    - primary_id: ID of the primary strategy
    - execution_order: Order in which strategies are executed
    """
    try:
        registry = get_registry()

        if active_only:
            strategies = registry.get_active_strategies()
        else:
            strategies = [
                registry.get_strategy(sid)
                for sid in registry.get_all_strategy_ids()
            ]
            strategies = [s for s in strategies if s is not None]

        primary = registry.get_primary_strategy()

        strategy_list = []
        for strategy in strategies:
            strategy_list.append({
                "id": strategy.id,
                "display_name": strategy.display_name,
                "strategy_class": strategy.strategy_class,
                "is_primary": strategy.is_primary,
                "is_active": strategy.is_active,
                "paper_trading": strategy.paper_trading,
                "description": strategy.description,
                "config_file": strategy.config_file,
            })

        settings = registry.get_settings()

        return {
            "strategies": strategy_list,
            "primary_id": primary.id if primary else None,
            "execution_order": [s.id for s in registry.get_active_strategies()],
            "settings": {
                "isolate_failures": settings.isolate_failures,
                "execution_timeout": settings.execution_timeout,
                "shared_data_fetch": settings.shared_data_fetch,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List strategies error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/status",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
        503: {"model": ErrorResponse, "description": "Strategy registry not configured"}
    },
    summary="Get all strategies status",
    description="Returns current status for all active strategies including state info."
)
async def get_strategies_status(
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    Get status for all active strategies.

    Returns status including last run time, positions, and equity for each strategy.
    """
    try:
        registry = get_registry()
        state_manager = get_state_manager()

        # Load all states
        states = state_manager.load_all_states()

        status_map = {}
        for strategy in registry.get_active_strategies():
            state = states.get(strategy.id, {})

            status_map[strategy.id] = {
                "display_name": strategy.display_name,
                "is_primary": strategy.is_primary,
                "paper_trading": strategy.paper_trading,
                "last_run": state.get("last_run"),
                "vol_state": state.get("vol_state"),
                "trend_state": state.get("trend_state"),
                "account_equity": state.get("account_equity"),
                "position_count": len(state.get("current_positions", {})),
            }

        return {
            "strategies": status_map,
            "primary_id": registry.get_primary_strategy().id if registry.get_primary_strategy() else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get strategies status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{strategy_id}",
    responses={
        404: {"model": ErrorResponse, "description": "Strategy not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
        503: {"model": ErrorResponse, "description": "Strategy registry not configured"}
    },
    summary="Get strategy details",
    description="Returns detailed information about a specific strategy."
)
async def get_strategy(
    strategy_id: str,
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    Get detailed information about a specific strategy.

    Args:
        strategy_id: Strategy identifier (e.g., 'v3_5b')

    Returns:
        Strategy configuration and details
    """
    try:
        registry = get_registry()

        strategy = registry.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy not found: {strategy_id}. Available: {', '.join(registry.get_all_strategy_ids())}"
            )

        # Load full config if available
        config = None
        try:
            config = registry.load_strategy_config(strategy_id)
        except ValueError as e:
            logger.warning(f"Could not load config for {strategy_id}: {e}")

        return {
            "id": strategy.id,
            "display_name": strategy.display_name,
            "strategy_class": strategy.strategy_class,
            "is_primary": strategy.is_primary,
            "is_active": strategy.is_active,
            "paper_trading": strategy.paper_trading,
            "description": strategy.description,
            "config_file": strategy.config_file,
            "state_file_path": strategy.state_file_path,
            "backup_path": strategy.backup_path,
            "config": config,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get strategy error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{strategy_id}/state",
    responses={
        404: {"model": ErrorResponse, "description": "Strategy not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
        503: {"model": ErrorResponse, "description": "Strategy registry not configured"}
    },
    summary="Get strategy state",
    description="Returns current state for a specific strategy including positions and regime."
)
async def get_strategy_state(
    strategy_id: str,
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    Get current state for a specific strategy.

    Args:
        strategy_id: Strategy identifier

    Returns:
        Strategy state including positions, regime, and last run time
    """
    try:
        registry = get_registry()
        state_manager = get_state_manager()

        strategy = registry.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy not found: {strategy_id}"
            )

        state = state_manager.load_state(strategy_id)

        return {
            "strategy_id": strategy_id,
            "display_name": strategy.display_name,
            "is_primary": strategy.is_primary,
            "state": {
                "last_run": state.get("last_run"),
                "vol_state": state.get("vol_state"),
                "trend_state": state.get("trend_state"),
                "current_positions": state.get("current_positions", {}),
                "account_equity": state.get("account_equity"),
                "last_allocation": state.get("last_allocation", {}),
                "initial_qqq_price": state.get("initial_qqq_price"),
                "metadata": state.get("metadata", {}),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get strategy state error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/primary/state",
    responses={
        404: {"model": ErrorResponse, "description": "No primary strategy configured"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
        503: {"model": ErrorResponse, "description": "Strategy registry not configured"}
    },
    summary="Get primary strategy state",
    description="Returns current state for the primary strategy."
)
async def get_primary_strategy_state(
    _auth: bool = Depends(verify_credentials),
) -> Dict[str, Any]:
    """
    Get current state for the primary strategy.

    Convenience endpoint that returns state for whichever strategy is marked as primary.
    """
    try:
        registry = get_registry()
        state_manager = get_state_manager()

        primary = registry.get_primary_strategy()
        if not primary:
            raise HTTPException(
                status_code=404,
                detail="No primary strategy configured"
            )

        state = state_manager.load_state(primary.id)

        return {
            "strategy_id": primary.id,
            "display_name": primary.display_name,
            "is_primary": True,
            "state": {
                "last_run": state.get("last_run"),
                "vol_state": state.get("vol_state"),
                "trend_state": state.get("trend_state"),
                "current_positions": state.get("current_positions", {}),
                "account_equity": state.get("account_equity"),
                "last_allocation": state.get("last_allocation", {}),
                "initial_qqq_price": state.get("initial_qqq_price"),
                "metadata": state.get("metadata", {}),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get primary strategy state error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
