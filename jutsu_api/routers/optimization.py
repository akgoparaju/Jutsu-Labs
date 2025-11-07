"""Parameter optimization endpoints.

Provides REST API for running parameter optimization jobs,
retrieving results, and monitoring job status.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
import logging
import uuid
import asyncio

from jutsu_api.models.schemas import OptimizationRequest, OptimizationResponse
from jutsu_api.dependencies import get_db
from jutsu_engine.optimization.grid_search import GridSearchOptimizer
from jutsu_engine.optimization.genetic import GeneticOptimizer
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

logger = logging.getLogger("API.OPTIMIZATION")

router = APIRouter()

# In-memory storage for optimization jobs (replace with database + Celery in production)
_optimization_jobs: Dict[str, Dict[str, Any]] = {}


def get_strategy_class(strategy_name: str):
    """Get strategy class by name."""
    strategies = {
        "SMA_Crossover": SMA_Crossover,
    }
    if strategy_name not in strategies:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available: {', '.join(strategies.keys())}"
        )
    return strategies[strategy_name]


def get_optimizer_class(optimizer_type: str):
    """Get optimizer class by type."""
    optimizers = {
        "grid_search": GridSearchOptimizer,
        "genetic": GeneticOptimizer,
    }
    if optimizer_type not in optimizers:
        raise ValueError(
            f"Unknown optimizer: {optimizer_type}. "
            f"Available: {', '.join(optimizers.keys())}"
        )
    return optimizers[optimizer_type]


@router.post("/grid-search", response_model=OptimizationResponse, status_code=status.HTTP_201_CREATED)
async def run_grid_search_optimization(
    request: OptimizationRequest,
    db: Session = Depends(get_db)
):
    """
    Run grid search parameter optimization.

    Exhaustively tests all parameter combinations to find the best.
    Use for small parameter spaces (<1000 combinations).

    Args:
        request: Optimization configuration
        db: Database session

    Returns:
        Optimization job information

    Raises:
        HTTPException: 400 if validation fails, 500 if optimization fails

    Example:
        POST /api/v1/optimization/grid-search
        {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "parameter_space": {
                "short_period": [10, 20, 30],
                "long_period": [40, 50, 60]
            },
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "metric": "sharpe_ratio"
        }
    """
    try:
        # Force grid search optimizer
        request.optimizer_type = "grid_search"

        return await _run_optimization(request, db)

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Grid search failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Grid search optimization failed: {str(e)}"
        )


@router.post("/genetic", response_model=OptimizationResponse, status_code=status.HTTP_201_CREATED)
async def run_genetic_optimization(
    request: OptimizationRequest,
    db: Session = Depends(get_db)
):
    """
    Run genetic algorithm parameter optimization.

    Uses evolutionary algorithm to efficiently search large parameter spaces.
    Use for large parameter spaces (>1000 combinations).

    Args:
        request: Optimization configuration
        db: Database session

    Returns:
        Optimization job information

    Raises:
        HTTPException: 400 if validation fails, 500 if optimization fails

    Example:
        POST /api/v1/optimization/genetic
        {
            "strategy_name": "SMA_Crossover",
            "symbol": "AAPL",
            "parameter_space": {
                "short_period": [5, 10, 15, 20, 25, 30],
                "long_period": [30, 40, 50, 60, 70, 80]
            },
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00",
            "initial_capital": "100000.00",
            "metric": "sharpe_ratio"
        }
    """
    try:
        # Force genetic optimizer
        request.optimizer_type = "genetic"

        return await _run_optimization(request, db)

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Genetic optimization failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Genetic optimization failed: {str(e)}"
        )


async def _run_optimization(
    request: OptimizationRequest,
    db: Session
) -> OptimizationResponse:
    """
    Internal function to run optimization (shared by grid search and genetic).

    Args:
        request: Optimization configuration
        db: Database session

    Returns:
        Optimization response with job ID
    """
    logger.info(
        f"Starting {request.optimizer_type} optimization: "
        f"{request.strategy_name} on {request.symbol}"
    )

    # Generate job ID
    job_id = f"opt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{request.symbol}_{request.strategy_name}"

    # Get strategy and optimizer classes
    strategy_class = get_strategy_class(request.strategy_name)
    optimizer_class = get_optimizer_class(request.optimizer_type)

    # Create optimizer instance
    optimizer = optimizer_class(
        strategy_class=strategy_class,
        parameter_space=request.parameter_space,
        objective=request.metric
    )

    # Store job as running
    _optimization_jobs[job_id] = {
        'status': 'running',
        'started_at': datetime.now(),
        'request': request.dict(),
        'results': None,
        'error': None
    }

    try:
        # Run optimization (this is synchronous and may take time)
        # In production, this should be async with Celery or similar
        results = optimizer.optimize(
            symbol=request.symbol,
            timeframe="1D",
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            parallel=True
        )

        # Update job status
        _optimization_jobs[job_id]['status'] = 'completed'
        _optimization_jobs[job_id]['completed_at'] = datetime.now()
        _optimization_jobs[job_id]['results'] = results

        logger.info(
            f"Optimization completed: {job_id} - "
            f"Best {request.metric}: {results['objective_value']:.4f}"
        )

        return OptimizationResponse(
            job_id=job_id,
            status='completed',
            best_parameters=results['parameters'],
            results={
                'best_value': results['objective_value'],
                'n_evaluated': results['n_evaluated'],
                'execution_mode': results.get('execution_mode', 'sequential')
            }
        )

    except Exception as e:
        # Update job status with error
        _optimization_jobs[job_id]['status'] = 'failed'
        _optimization_jobs[job_id]['error'] = str(e)
        _optimization_jobs[job_id]['failed_at'] = datetime.now()

        logger.error(f"Optimization failed: {job_id} - {e}", exc_info=True)

        return OptimizationResponse(
            job_id=job_id,
            status='failed',
            error=str(e)
        )


@router.get("/{job_id}", response_model=OptimizationResponse)
async def get_optimization_status(job_id: str):
    """
    Get status of an optimization job.

    Args:
        job_id: Optimization job identifier

    Returns:
        Optimization job status and results

    Raises:
        HTTPException: 404 if job not found

    Example:
        GET /api/v1/optimization/opt_20240101_120000_AAPL_SMA_Crossover
    """
    try:
        if job_id not in _optimization_jobs:
            logger.warning(f"Optimization job not found: {job_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Optimization job not found: {job_id}"
            )

        job = _optimization_jobs[job_id]

        logger.info(f"Retrieved status for optimization: {job_id}")

        # Build response based on status
        if job['status'] == 'completed':
            results = job['results']
            return OptimizationResponse(
                job_id=job_id,
                status='completed',
                best_parameters=results['parameters'],
                results={
                    'best_value': results['objective_value'],
                    'n_evaluated': results['n_evaluated'],
                    'execution_mode': results.get('execution_mode', 'sequential')
                }
            )
        elif job['status'] == 'failed':
            return OptimizationResponse(
                job_id=job_id,
                status='failed',
                error=job['error']
            )
        else:  # running
            return OptimizationResponse(
                job_id=job_id,
                status='running'
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve optimization status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve job status: {str(e)}"
        )


@router.get("/{job_id}/results", response_model=Dict[str, Any])
async def get_optimization_results(job_id: str):
    """
    Get detailed results of a completed optimization job.

    Args:
        job_id: Optimization job identifier

    Returns:
        Complete optimization results

    Raises:
        HTTPException: 404 if job not found, 400 if not completed

    Example:
        GET /api/v1/optimization/opt_20240101_120000_AAPL_SMA_Crossover/results
    """
    try:
        if job_id not in _optimization_jobs:
            logger.warning(f"Optimization job not found: {job_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Optimization job not found: {job_id}"
            )

        job = _optimization_jobs[job_id]

        if job['status'] != 'completed':
            logger.warning(f"Optimization not completed: {job_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Optimization not completed yet. Status: {job['status']}"
            )

        results = job['results']

        logger.info(f"Retrieved results for optimization: {job_id}")

        return {
            'job_id': job_id,
            'status': 'completed',
            'best_parameters': results['parameters'],
            'best_value': results['objective_value'],
            'n_evaluated': results['n_evaluated'],
            'execution_mode': results.get('execution_mode', 'sequential'),
            'all_results': results.get('all_results', [])[:100],  # Limit to 100 results
            'started_at': job['started_at'],
            'completed_at': job['completed_at'],
            'request': job['request']
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve results: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve results: {str(e)}"
        )


@router.get("/jobs/list", response_model=List[Dict[str, Any]])
async def list_optimization_jobs(
    status: str = None,
    limit: int = 100
):
    """
    List all optimization jobs.

    Args:
        status: Optional status filter (running, completed, failed)
        limit: Maximum number of jobs to return (default: 100)

    Returns:
        List of optimization job summaries

    Example:
        GET /api/v1/optimization/jobs/list?status=completed&limit=10
    """
    try:
        # Filter jobs by status if provided
        jobs = []
        for job_id, job in _optimization_jobs.items():
            if status and job['status'] != status:
                continue

            job_summary = {
                'job_id': job_id,
                'status': job['status'],
                'strategy_name': job['request']['strategy_name'],
                'symbol': job['request']['symbol'],
                'optimizer_type': job['request']['optimizer_type'],
                'started_at': job['started_at']
            }

            if job['status'] == 'completed':
                job_summary['completed_at'] = job['completed_at']
                job_summary['best_value'] = job['results']['objective_value']
            elif job['status'] == 'failed':
                job_summary['failed_at'] = job['failed_at']
                job_summary['error'] = job['error']

            jobs.append(job_summary)

        # Sort by started_at (most recent first) and limit
        jobs.sort(key=lambda x: x['started_at'], reverse=True)
        jobs = jobs[:limit]

        logger.info(f"Retrieved {len(jobs)} optimization jobs")

        return jobs

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list jobs: {str(e)}"
        )
