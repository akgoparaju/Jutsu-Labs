"""Pydantic schemas for API request/response validation.

Defines all data transfer objects (DTOs) used by API endpoints.
"""
from pydantic import BaseModel, Field, validator
from typing import Dict, Any, Optional, List
from datetime import datetime
from decimal import Decimal


class BacktestRequest(BaseModel):
    """Request schema for running a backtest.

    Attributes:
        strategy_name: Name of strategy to backtest
        symbol: Stock ticker symbol
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital amount
        parameters: Strategy-specific parameters
        timeframe: Data timeframe (default: "1D")
        commission_per_share: Commission cost per share
        slippage_percent: Slippage percentage
    """
    strategy_name: str = Field(..., description="Strategy name (e.g., 'SMA_Crossover')")
    symbol: str = Field(..., description="Stock ticker symbol")
    start_date: datetime = Field(..., description="Backtest start date")
    end_date: datetime = Field(..., description="Backtest end date")
    initial_capital: Decimal = Field(..., description="Initial capital amount")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")
    timeframe: str = Field(default="1D", description="Data timeframe")
    commission_per_share: Optional[Decimal] = Field(
        default=Decimal("0.01"),
        description="Commission per share"
    )
    slippage_percent: Optional[Decimal] = Field(
        default=Decimal("0.001"),
        description="Slippage percentage"
    )

    @validator("end_date")
    def validate_date_range(cls, end_date, values):
        """Ensure end_date is after start_date."""
        if "start_date" in values and end_date <= values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return end_date

    @validator("initial_capital")
    def validate_capital(cls, capital):
        """Ensure initial capital is positive."""
        if capital <= 0:
            raise ValueError("initial_capital must be positive")
        return capital

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_name": "SMA_Crossover",
                "symbol": "AAPL",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-12-31T00:00:00",
                "initial_capital": "100000.00",
                "parameters": {
                    "short_period": 20,
                    "long_period": 50
                },
                "timeframe": "1D"
            }
        }


class BacktestResponse(BaseModel):
    """Response schema for backtest results.

    Attributes:
        backtest_id: Unique identifier for backtest run
        status: Status of backtest (success, error)
        metrics: Performance metrics
        error: Error message if failed
        config: Backtest configuration used
    """
    backtest_id: str = Field(..., description="Unique backtest identifier")
    status: str = Field(..., description="Backtest status")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Performance metrics")
    error: Optional[str] = Field(None, description="Error message if failed")
    config: Optional[Dict[str, Any]] = Field(None, description="Backtest configuration")

    class Config:
        json_schema_extra = {
            "example": {
                "backtest_id": "bt_20240101_AAPL_SMA",
                "status": "success",
                "metrics": {
                    "total_return": 0.15,
                    "sharpe_ratio": 1.5,
                    "max_drawdown": -0.08,
                    "total_trades": 42
                }
            }
        }


class DataSyncRequest(BaseModel):
    """Request schema for data synchronization.

    Attributes:
        symbol: Stock ticker symbol
        source: Data source identifier
        timeframe: Data timeframe
        start_date: Start date for sync
        end_date: End date for sync
        force_refresh: Force re-download of all data
    """
    symbol: str = Field(..., description="Stock ticker symbol")
    source: str = Field(default="schwab", description="Data source")
    timeframe: str = Field(default="1D", description="Data timeframe")
    start_date: datetime = Field(..., description="Sync start date")
    end_date: Optional[datetime] = Field(None, description="Sync end date")
    force_refresh: bool = Field(default=False, description="Force refresh all data")

    @validator("end_date")
    def validate_date_range(cls, end_date, values):
        """Ensure end_date is after start_date if provided."""
        if end_date and "start_date" in values and end_date <= values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return end_date

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "AAPL",
                "source": "schwab",
                "timeframe": "1D",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-12-31T00:00:00"
            }
        }


class DataResponse(BaseModel):
    """Response schema for data operations.

    Attributes:
        symbol: Stock ticker symbol
        bars_count: Number of bars available
        date_range: Date range of available data
        timeframe: Data timeframe
        last_updated: Last update timestamp
    """
    symbol: str = Field(..., description="Stock ticker symbol")
    bars_count: int = Field(..., description="Number of bars")
    date_range: Optional[Dict[str, datetime]] = Field(None, description="Date range")
    timeframe: str = Field(..., description="Data timeframe")
    last_updated: Optional[datetime] = Field(None, description="Last update time")

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "AAPL",
                "bars_count": 252,
                "date_range": {
                    "start": "2024-01-01T00:00:00",
                    "end": "2024-12-31T00:00:00"
                },
                "timeframe": "1D"
            }
        }


class StrategyInfo(BaseModel):
    """Strategy information schema.

    Attributes:
        name: Strategy name
        description: Strategy description
        parameters: Strategy parameters with descriptions
        default_values: Default parameter values
    """
    name: str = Field(..., description="Strategy name")
    description: str = Field(..., description="Strategy description")
    parameters: Dict[str, str] = Field(..., description="Parameter descriptions")
    default_values: Dict[str, Any] = Field(..., description="Default parameter values")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "SMA_Crossover",
                "description": "Simple Moving Average crossover strategy",
                "parameters": {
                    "short_period": "Short SMA period",
                    "long_period": "Long SMA period"
                },
                "default_values": {
                    "short_period": 20,
                    "long_period": 50
                }
            }
        }


class OptimizationRequest(BaseModel):
    """Request schema for parameter optimization.

    Attributes:
        strategy_name: Name of strategy to optimize
        symbol: Stock ticker symbol
        parameter_space: Parameter ranges to test
        optimizer_type: Type of optimizer (grid_search, genetic)
        start_date: Optimization start date
        end_date: Optimization end date
        initial_capital: Starting capital
        metric: Optimization metric (sharpe_ratio, total_return)
    """
    strategy_name: str = Field(..., description="Strategy name")
    symbol: str = Field(..., description="Stock ticker symbol")
    parameter_space: Dict[str, List[Any]] = Field(..., description="Parameter ranges")
    optimizer_type: str = Field(default="grid_search", description="Optimizer type")
    start_date: datetime = Field(..., description="Start date")
    end_date: datetime = Field(..., description="End date")
    initial_capital: Decimal = Field(..., description="Initial capital")
    metric: str = Field(default="sharpe_ratio", description="Optimization metric")

    @validator("optimizer_type")
    def validate_optimizer(cls, optimizer_type):
        """Validate optimizer type."""
        valid_types = ["grid_search", "genetic"]
        if optimizer_type not in valid_types:
            raise ValueError(f"optimizer_type must be one of {valid_types}")
        return optimizer_type

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_name": "SMA_Crossover",
                "symbol": "AAPL",
                "parameter_space": {
                    "short_period": [10, 20, 30],
                    "long_period": [40, 50, 60]
                },
                "optimizer_type": "grid_search",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-12-31T00:00:00",
                "initial_capital": "100000.00",
                "metric": "sharpe_ratio"
            }
        }


class OptimizationResponse(BaseModel):
    """Response schema for optimization results.

    Attributes:
        job_id: Unique optimization job identifier
        status: Job status (running, completed, failed)
        results: Optimization results if completed
        best_parameters: Best parameter set found
        error: Error message if failed
    """
    job_id: str = Field(..., description="Optimization job ID")
    status: str = Field(..., description="Job status")
    results: Optional[Dict[str, Any]] = Field(None, description="Optimization results")
    best_parameters: Optional[Dict[str, Any]] = Field(None, description="Best parameters")
    error: Optional[str] = Field(None, description="Error message")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "opt_20240101_AAPL",
                "status": "completed",
                "best_parameters": {
                    "short_period": 20,
                    "long_period": 50
                },
                "results": {
                    "best_sharpe": 1.8,
                    "total_combinations": 9
                }
            }
        }


class HealthResponse(BaseModel):
    """Health check response schema.

    Attributes:
        status: Service health status
        version: API version
        timestamp: Current timestamp
    """
    status: str = Field(..., description="Health status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Current time")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "version": "0.2.0",
                "timestamp": "2024-01-01T00:00:00"
            }
        }
