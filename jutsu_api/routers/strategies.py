"""Strategy information endpoints.

Provides REST API for listing available strategies,
retrieving strategy details, and validating parameters.
"""
from fastapi import APIRouter, HTTPException, status
from typing import List, Dict, Any
import logging
import inspect

from jutsu_api.models.schemas import StrategyInfo
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

logger = logging.getLogger("API.STRATEGIES")

router = APIRouter()

# Registry of available strategies
STRATEGY_REGISTRY = {
    "SMA_Crossover": {
        "class": SMA_Crossover,
        "description": "Simple Moving Average crossover strategy",
        "parameters": {
            "short_period": "Short-term SMA period (bars)",
            "long_period": "Long-term SMA period (bars)",
            "position_percent": "Position size as percent of capital (0.0-1.0)"
        },
        "defaults": {
            "short_period": 20,
            "long_period": 50,
            "position_percent": "1.0"
        }
    },
    # Add more strategies as they're implemented
}


@router.get("", response_model=List[StrategyInfo])
async def list_strategies():
    """
    List all available trading strategies.

    Returns:
        List of strategy information objects

    Example:
        GET /api/v1/strategies
        Response: [
            {
                "name": "SMA_Crossover",
                "description": "Simple Moving Average crossover strategy",
                "parameters": {...},
                "default_values": {...}
            }
        ]
    """
    try:
        strategies = []

        for name, info in STRATEGY_REGISTRY.items():
            strategies.append(
                StrategyInfo(
                    name=name,
                    description=info["description"],
                    parameters=info["parameters"],
                    default_values=info["defaults"]
                )
            )

        logger.info(f"Retrieved {len(strategies)} strategies")

        return strategies

    except Exception as e:
        logger.error(f"Failed to list strategies: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve strategies: {str(e)}"
        )


@router.get("/{name}", response_model=StrategyInfo)
async def get_strategy_details(name: str):
    """
    Get detailed information about a specific strategy.

    Args:
        name: Strategy name

    Returns:
        Strategy information

    Raises:
        HTTPException: 404 if strategy not found

    Example:
        GET /api/v1/strategies/SMA_Crossover
    """
    try:
        if name not in STRATEGY_REGISTRY:
            logger.warning(f"Strategy not found: {name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy not found: {name}. Available: {', '.join(STRATEGY_REGISTRY.keys())}"
            )

        info = STRATEGY_REGISTRY[name]

        logger.info(f"Retrieved details for strategy: {name}")

        return StrategyInfo(
            name=name,
            description=info["description"],
            parameters=info["parameters"],
            default_values=info["defaults"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get strategy details: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve strategy details: {str(e)}"
        )


@router.post("/validate", response_model=Dict[str, Any])
async def validate_strategy_parameters(
    strategy_name: str,
    parameters: Dict[str, Any]
):
    """
    Validate strategy parameters.

    Checks if provided parameters are valid for the strategy
    and returns any validation errors.

    Args:
        strategy_name: Name of strategy
        parameters: Parameter values to validate

    Returns:
        Validation result with errors if any

    Raises:
        HTTPException: 400 if validation fails, 404 if strategy not found

    Example:
        POST /api/v1/strategies/validate
        {
            "strategy_name": "SMA_Crossover",
            "parameters": {
                "short_period": 20,
                "long_period": 50,
                "position_percent": "1.0"
            }
        }
    """
    try:
        # Check if strategy exists
        if strategy_name not in STRATEGY_REGISTRY:
            logger.warning(f"Strategy not found for validation: {strategy_name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy not found: {strategy_name}"
            )

        info = STRATEGY_REGISTRY[strategy_name]
        strategy_class = info["class"]
        expected_params = info["parameters"].keys()

        # Validate parameters
        errors = []

        # Check for unknown parameters
        for param in parameters:
            if param not in expected_params:
                errors.append(f"Unknown parameter: {param}")

        # Try to instantiate strategy with parameters
        try:
            strategy_instance = strategy_class(**parameters)
            logger.info(f"Strategy validation successful: {strategy_name}")
        except TypeError as e:
            errors.append(f"Invalid parameter types: {str(e)}")
        except ValueError as e:
            errors.append(f"Invalid parameter values: {str(e)}")

        # Return validation result
        if errors:
            logger.warning(f"Validation errors for {strategy_name}: {errors}")
            return {
                'valid': False,
                'errors': errors,
                'strategy_name': strategy_name,
                'parameters': parameters
            }
        else:
            return {
                'valid': True,
                'errors': [],
                'strategy_name': strategy_name,
                'parameters': parameters
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Parameter validation failed: {str(e)}"
        )


@router.get("/{name}/schema", response_model=Dict[str, Any])
async def get_strategy_schema(name: str):
    """
    Get JSON schema for strategy parameters.

    Returns JSON schema that can be used for form generation
    or validation in frontends.

    Args:
        name: Strategy name

    Returns:
        JSON schema for parameters

    Raises:
        HTTPException: 404 if strategy not found

    Example:
        GET /api/v1/strategies/SMA_Crossover/schema
    """
    try:
        if name not in STRATEGY_REGISTRY:
            logger.warning(f"Strategy not found: {name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy not found: {name}"
            )

        info = STRATEGY_REGISTRY[name]

        # Build JSON schema
        schema = {
            "type": "object",
            "properties": {},
            "required": list(info["parameters"].keys())
        }

        # Add property definitions based on defaults
        for param, description in info["parameters"].items():
            default_value = info["defaults"].get(param)
            param_type = type(default_value).__name__

            schema["properties"][param] = {
                "type": "integer" if param_type == "int" else "number",
                "description": description,
                "default": default_value
            }

        logger.info(f"Retrieved schema for strategy: {name}")

        return {
            "strategy_name": name,
            "schema": schema
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get schema: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve schema: {str(e)}"
        )
