"""
Configuration API Routes

GET /api/config - Get current configuration
PUT /api/config - Update configuration parameter
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from jutsu_engine.api.schemas import (
    ConfigResponse,
    ConfigParameter,
    ConfigUpdate,
    ConfigUpdateResponse,
    ParameterConstraint,
    ErrorResponse,
)
from jutsu_engine.api.dependencies import (
    get_db,
    get_config,
    load_config,
    reset_strategy_runner,
    verify_credentials,
    require_permission,
)
from jutsu_engine.data.models import ConfigOverride, ConfigHistory

logger = logging.getLogger('API.CONFIG')

router = APIRouter(prefix="/api/config", tags=["config"])

# Parameter constraints (validated on update)
PARAMETER_CONSTRAINTS = {
    # SMA parameters
    'sma_fast': {'min': 5, 'max': 100, 'type': 'int'},
    'sma_slow': {'min': 50, 'max': 300, 'type': 'int'},
    'sma_trend': {'min': 100, 'max': 500, 'type': 'int'},

    # Regime parameters
    'regime_bull_strong': {'min': 0.1, 'max': 1.0, 'type': 'float'},
    'regime_bear_strong': {'min': -1.0, 'max': -0.1, 'type': 'float'},
    'regime_vol_high': {'min': 0.5, 'max': 3.0, 'type': 'float'},

    # Weight parameters
    'weight_equity_max': {'min': 0.0, 'max': 1.0, 'type': 'float'},
    'weight_bond_max': {'min': 0.0, 'max': 1.0, 'type': 'float'},

    # Execution parameters
    'execution_time': {
        'allowed': ['open', '15min_after_open', '15min_before_close', '5min_before_close', 'close'],
        'type': 'str'
    },

    # Slippage thresholds
    'slippage_abort_pct': {'min': 0.1, 'max': 5.0, 'type': 'float'},
    'rebalance_threshold_pct': {'min': 1.0, 'max': 20.0, 'type': 'float'},
}


def get_value_type(value) -> str:
    """Determine the value type for storage."""
    if isinstance(value, bool):
        return 'bool'
    elif isinstance(value, int):
        return 'int'
    elif isinstance(value, float):
        return 'float'
    elif isinstance(value, str):
        return 'str'
    else:
        return 'str'


@router.get(
    "",
    response_model=ConfigResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get current configuration",
    description="Returns all strategy parameters with their current values and constraints."
)
async def get_configuration(
    db: Session = Depends(get_db),
    config: dict = Depends(get_config),
    _auth: bool = Depends(verify_credentials),
) -> ConfigResponse:
    """
    Get full configuration with overrides applied.

    Returns all 32+ strategy parameters with:
    - Current value (with any active overrides)
    - Original value (from config file)
    - Override status
    - Parameter constraints
    """
    try:
        strategy_config = config.get('strategy', {})
        strategy_name = strategy_config.get('name', 'Unknown')
        parameters_config = strategy_config.get('parameters', {})

        # Get active overrides from database
        active_overrides = db.query(ConfigOverride).filter(
            ConfigOverride.is_active == True
        ).all()

        override_map = {o.parameter_name: o for o in active_overrides}

        # Build parameter list
        parameters = []

        for name, value in parameters_config.items():
            override = override_map.get(name)

            # Get constraints if defined
            constraint = None
            if name in PARAMETER_CONSTRAINTS:
                pc = PARAMETER_CONSTRAINTS[name]
                constraint = ParameterConstraint(
                    min_value=pc.get('min'),
                    max_value=pc.get('max'),
                    allowed_values=pc.get('allowed'),
                    value_type=pc.get('type', 'str'),
                )

            # Apply override if active
            current_value = value
            original_value = value
            is_overridden = False

            if override:
                original_value = value
                current_value = _convert_value(override.override_value, override.value_type)
                is_overridden = True

            parameters.append(ConfigParameter(
                name=name,
                value=current_value,
                original_value=original_value if is_overridden else None,
                is_overridden=is_overridden,
                constraints=constraint,
            ))

        # Get last modification time
        last_override = db.query(ConfigOverride).filter(
            ConfigOverride.is_active == True
        ).order_by(ConfigOverride.created_at.desc()).first()

        last_modified = last_override.created_at if last_override else None

        return ConfigResponse(
            strategy_name=strategy_name,
            parameters=parameters,
            active_overrides=len(active_overrides),
            last_modified=last_modified,
        )

    except Exception as e:
        logger.error(f"Config get error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "",
    response_model=ConfigUpdateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Update configuration parameter",
    description="Update a single configuration parameter with validation."
)
async def update_configuration(
    update: ConfigUpdate,
    db: Session = Depends(get_db),
    config: dict = Depends(get_config),
    _auth = Depends(require_permission("config:write")),
) -> ConfigUpdateResponse:
    """
    Update a configuration parameter.

    Creates a ConfigOverride record and logs to ConfigHistory.
    Validates against parameter constraints before applying.
    """
    try:
        param_name = update.parameter_name
        new_value = update.new_value

        # Get current config
        strategy_config = config.get('strategy', {})
        parameters = strategy_config.get('parameters', {})

        # Validate parameter exists
        if param_name not in parameters:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown parameter: {param_name}"
            )

        original_value = parameters[param_name]

        # Validate against constraints
        if param_name in PARAMETER_CONSTRAINTS:
            constraints = PARAMETER_CONSTRAINTS[param_name]

            # Check type
            expected_type = constraints.get('type', 'str')
            if expected_type == 'int' and not isinstance(new_value, int):
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter {param_name} must be an integer"
                )
            elif expected_type == 'float' and not isinstance(new_value, (int, float)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter {param_name} must be a number"
                )

            # Check range
            min_val = constraints.get('min')
            max_val = constraints.get('max')

            if min_val is not None and new_value < min_val:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter {param_name} must be >= {min_val}"
                )

            if max_val is not None and new_value > max_val:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter {param_name} must be <= {max_val}"
                )

            # Check allowed values
            allowed = constraints.get('allowed')
            if allowed and new_value not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter {param_name} must be one of: {allowed}"
                )

        # Get strategy_id from update or default to primary strategy
        strategy_id = update.strategy_id or config.get('strategy', {}).get('strategy_id', 'v3_5b')

        # Deactivate existing override if present for this strategy
        existing = db.query(ConfigOverride).filter(
            ConfigOverride.parameter_name == param_name,
            ConfigOverride.strategy_id == strategy_id,
            ConfigOverride.is_active == True
        ).first()

        if existing:
            existing.is_active = False
            existing.deactivated_at = datetime.now(timezone.utc)

        # Create new override for this strategy
        value_type = get_value_type(new_value)
        new_override = ConfigOverride(
            parameter_name=param_name,
            original_value=str(original_value),
            override_value=str(new_value),
            value_type=value_type,
            strategy_id=strategy_id,
            is_active=True,
            reason=update.reason,
            created_at=datetime.now(timezone.utc),
        )
        db.add(new_override)

        # Log to history
        history_entry = ConfigHistory(
            parameter_name=param_name,
            old_value=str(original_value),
            new_value=str(new_value),
            change_type='override',
            reason=update.reason or 'API update',
            changed_by='api',
            timestamp=datetime.now(timezone.utc),
        )
        db.add(history_entry)

        db.commit()

        # Reset strategy runner to pick up changes
        reset_strategy_runner()

        logger.info(f"Config updated: {param_name} = {new_value}")

        return ConfigUpdateResponse(
            success=True,
            parameter_name=param_name,
            old_value=original_value,
            new_value=new_value,
            message=f"Parameter {param_name} updated successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Config update error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{parameter_name}",
    response_model=ConfigUpdateResponse,
    summary="Reset parameter to default",
    description="Remove override and reset parameter to config file value."
)
async def reset_parameter(
    parameter_name: str,
    strategy_id: Optional[str] = None,
    db: Session = Depends(get_db),
    config: dict = Depends(get_config),
    _auth = Depends(require_permission("config:write")),
) -> ConfigUpdateResponse:
    """
    Reset a parameter to its default value from config file.

    Deactivates any active override for the parameter.
    Optionally specify strategy_id to reset for a specific strategy.
    """
    try:
        # Get strategy_id from query param or default to primary strategy
        target_strategy_id = strategy_id or config.get('strategy', {}).get('strategy_id', 'v3_5b')

        # Get current config
        strategy_config = config.get('strategy', {})
        parameters = strategy_config.get('parameters', {})

        if parameter_name not in parameters:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown parameter: {parameter_name}"
            )

        original_value = parameters[parameter_name]

        # Deactivate override for this strategy
        existing = db.query(ConfigOverride).filter(
            ConfigOverride.parameter_name == parameter_name,
            ConfigOverride.strategy_id == target_strategy_id,
            ConfigOverride.is_active == True
        ).first()

        if not existing:
            return ConfigUpdateResponse(
                success=True,
                parameter_name=parameter_name,
                old_value=original_value,
                new_value=original_value,
                message="Parameter was not overridden",
            )

        overridden_value = _convert_value(existing.override_value, existing.value_type)

        existing.is_active = False
        existing.deactivated_at = datetime.now(timezone.utc)

        # Log to history
        history_entry = ConfigHistory(
            parameter_name=parameter_name,
            old_value=str(overridden_value),
            new_value=str(original_value),
            change_type='reset',
            reason='Reset to default via API',
            changed_by='api',
            timestamp=datetime.now(timezone.utc),
        )
        db.add(history_entry)

        db.commit()

        # Reset strategy runner
        reset_strategy_runner()

        return ConfigUpdateResponse(
            success=True,
            parameter_name=parameter_name,
            old_value=overridden_value,
            new_value=original_value,
            message=f"Parameter {parameter_name} reset to default",
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Config reset error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


def _convert_value(value_str: str, value_type: str):
    """Convert string value to appropriate type."""
    if value_type == 'int':
        return int(value_str)
    elif value_type == 'float':
        return float(value_str)
    elif value_type == 'bool':
        return value_str.lower() in ('true', '1', 'yes')
    elif value_type == 'decimal':
        from decimal import Decimal
        return Decimal(value_str)
    else:
        return value_str
