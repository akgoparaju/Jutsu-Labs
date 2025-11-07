"""Backtest endpoints for running and managing backtests.

Provides REST API for executing backtests, retrieving results,
and managing backtest history.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
import logging
import uuid

from jutsu_api.models.schemas import BacktestRequest, BacktestResponse
from jutsu_api.dependencies import get_db
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

logger = logging.getLogger("API.BACKTEST")

router = APIRouter()

# In-memory storage for backtest results (replace with database in production)
_backtest_results: Dict[str, Dict[str, Any]] = {}


def get_strategy_class(strategy_name: str):
    """
    Get strategy class by name.

    Args:
        strategy_name: Name of strategy

    Returns:
        Strategy class

    Raises:
        ValueError: If strategy not found
    """
    strategies = {
        "SMA_Crossover": SMA_Crossover,
        # Add more strategies as they're implemented
    }

    if strategy_name not in strategies:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available: {', '.join(strategies.keys())}"
        )

    return strategies[strategy_name]


@router.post("/run", response_model=BacktestResponse, status_code=status.HTTP_201_CREATED)
async def run_backtest(
    request: BacktestRequest,
    db: Session = Depends(get_db)
):
    """
    Run a backtest with specified strategy and parameters.

    Args:
        request: Backtest configuration
        db: Database session

    Returns:
        Backtest results with metrics

    Raises:
        HTTPException: 400 if validation fails, 500 if backtest fails

    Example:
        POST /api/v1/backtest/run
        {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "parameters": {
                "short_period": 20,
                "long_period": 50
            }
        }
    """
    try:
        logger.info(
            f"Starting backtest: {request.strategy_name} on {request.symbol} "
            f"from {request.start_date.date()} to {request.end_date.date()}"
        )

        # Get strategy class
        strategy_class = get_strategy_class(request.strategy_name)

        # Create strategy instance with parameters
        strategy = strategy_class(**request.parameters)

        # Prepare backtest configuration
        config = {
            'symbol': request.symbol,
            'timeframe': request.timeframe,
            'start_date': request.start_date,
            'end_date': request.end_date,
            'initial_capital': request.initial_capital,
            'commission_per_share': request.commission_per_share,
            'slippage_percent': request.slippage_percent,
        }

        # Run backtest
        runner = BacktestRunner(config)
        results = runner.run(strategy)

        # Generate backtest ID
        backtest_id = f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{request.symbol}_{request.strategy_name}"

        # Store results
        _backtest_results[backtest_id] = results

        logger.info(
            f"Backtest completed: {backtest_id} - "
            f"Return: {results.get('total_return', 0):.2%}, "
            f"Sharpe: {results.get('sharpe_ratio', 0):.2f}"
        )

        return BacktestResponse(
            backtest_id=backtest_id,
            status="success",
            metrics=results,
            config=config
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backtest execution failed: {str(e)}"
        )


@router.get("/{backtest_id}", response_model=BacktestResponse)
async def get_backtest_results(backtest_id: str):
    """
    Retrieve results for a specific backtest.

    Args:
        backtest_id: Unique backtest identifier

    Returns:
        Backtest results

    Raises:
        HTTPException: 404 if backtest not found

    Example:
        GET /api/v1/backtest/bt_20240101_120000_AAPL_SMA_Crossover
    """
    try:
        if backtest_id not in _backtest_results:
            logger.warning(f"Backtest not found: {backtest_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Backtest not found: {backtest_id}"
            )

        results = _backtest_results[backtest_id]

        logger.info(f"Retrieved results for: {backtest_id}")

        return BacktestResponse(
            backtest_id=backtest_id,
            status="success",
            metrics=results,
            config=results.get('config')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve backtest: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve backtest: {str(e)}"
        )


@router.get("/history", response_model=List[Dict[str, Any]])
async def list_backtest_history(
    limit: int = 100,
    offset: int = 0
):
    """
    List backtest history.

    Args:
        limit: Maximum number of results (default: 100)
        offset: Number of results to skip (default: 0)

    Returns:
        List of backtest summaries

    Example:
        GET /api/v1/backtest/history?limit=10&offset=0
    """
    try:
        # Get all backtest IDs, sorted by timestamp (most recent first)
        sorted_ids = sorted(
            _backtest_results.keys(),
            reverse=True
        )

        # Apply pagination
        paginated_ids = sorted_ids[offset:offset + limit]

        # Build summary for each backtest
        history = []
        for backtest_id in paginated_ids:
            results = _backtest_results[backtest_id]
            history.append({
                'backtest_id': backtest_id,
                'strategy_name': results.get('strategy_name'),
                'symbol': results.get('config', {}).get('symbol'),
                'start_date': results.get('config', {}).get('start_date'),
                'end_date': results.get('config', {}).get('end_date'),
                'total_return': results.get('total_return'),
                'sharpe_ratio': results.get('sharpe_ratio'),
                'total_trades': results.get('total_trades'),
            })

        logger.info(f"Retrieved {len(history)} backtest records")

        return history

    except Exception as e:
        logger.error(f"Failed to list history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve history: {str(e)}"
        )


@router.delete("/{backtest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backtest(backtest_id: str):
    """
    Delete a backtest and its results.

    Args:
        backtest_id: Unique backtest identifier

    Raises:
        HTTPException: 404 if backtest not found

    Example:
        DELETE /api/v1/backtest/bt_20240101_120000_AAPL_SMA_Crossover
    """
    try:
        if backtest_id not in _backtest_results:
            logger.warning(f"Backtest not found for deletion: {backtest_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Backtest not found: {backtest_id}"
            )

        del _backtest_results[backtest_id]
        logger.info(f"Deleted backtest: {backtest_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete backtest: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete backtest: {str(e)}"
        )
