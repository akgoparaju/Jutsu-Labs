"""
Pydantic schemas for API request/response models.

Provides type-safe data validation for all API endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ==============================================================================
# STATUS SCHEMAS
# ==============================================================================

class RegimeInfo(BaseModel):
    """Current strategy regime information."""
    cell: Optional[int] = Field(None, ge=1, le=6, description="Strategy cell (1-6)")
    trend_state: Optional[str] = Field(None, description="Trend state (BullStrong, Sideways, BearStrong)")
    vol_state: Optional[str] = Field(None, description="Volatility state (Low, High)")
    t_norm: Optional[float] = Field(None, description="Normalized trend indicator")
    z_score: Optional[float] = Field(None, description="Volatility z-score")


class PositionInfo(BaseModel):
    """Position information for a single symbol."""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    quantity: int
    avg_cost: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    weight_pct: Optional[float] = Field(None, description="Position weight as % of portfolio")


class PortfolioInfo(BaseModel):
    """Portfolio summary information."""
    total_equity: float
    cash: Optional[float] = None
    positions_value: Optional[float] = None
    positions: List[PositionInfo] = []


class SystemStatus(BaseModel):
    """Complete system status response."""
    mode: str = Field(..., description="Current trading mode (offline_mock, online_live)")
    is_running: bool = Field(..., description="Whether trading engine is active")
    last_execution: Optional[datetime] = Field(None, description="Last trade execution time")
    next_execution: Optional[datetime] = Field(None, description="Next scheduled execution time")
    regime: Optional[RegimeInfo] = None
    portfolio: Optional[PortfolioInfo] = None
    uptime_seconds: Optional[float] = None
    error: Optional[str] = None


# ==============================================================================
# CONFIG SCHEMAS
# ==============================================================================

class ParameterConstraint(BaseModel):
    """Constraints for a single parameter."""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[List[Any]] = None
    value_type: str = Field(..., description="Type: int, float, decimal, bool, str")


class ConfigParameter(BaseModel):
    """Single configuration parameter."""
    name: str
    value: Any
    original_value: Optional[Any] = None
    is_overridden: bool = False
    constraints: Optional[ParameterConstraint] = None
    description: Optional[str] = None


class ConfigResponse(BaseModel):
    """Full configuration response."""
    strategy_name: str
    parameters: List[ConfigParameter]
    active_overrides: int = 0
    last_modified: Optional[datetime] = None


class ConfigUpdate(BaseModel):
    """Configuration update request."""
    parameter_name: str = Field(..., description="Name of parameter to update")
    new_value: Any = Field(..., description="New value for parameter")
    reason: Optional[str] = Field(None, description="Reason for change")


class ConfigUpdateResponse(BaseModel):
    """Configuration update response."""
    success: bool
    parameter_name: str
    old_value: Any
    new_value: Any
    message: str


# ==============================================================================
# TRADE SCHEMAS
# ==============================================================================

class TradeRecord(BaseModel):
    """Single trade record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    timestamp: datetime
    action: str = Field(..., description="BUY or SELL")
    quantity: int
    target_price: float
    fill_price: Optional[float] = None
    fill_value: Optional[float] = None
    slippage_pct: Optional[float] = None
    schwab_order_id: Optional[str] = None
    strategy_cell: Optional[int] = None
    trend_state: Optional[str] = None
    vol_state: Optional[str] = None
    t_norm: Optional[float] = None
    z_score: Optional[float] = None
    reason: Optional[str] = None
    mode: str


class TradeListResponse(BaseModel):
    """Paginated trade list response."""
    trades: List[TradeRecord]
    total: int
    page: int
    page_size: int
    total_pages: int


class TradeFilter(BaseModel):
    """Trade filtering options."""
    symbol: Optional[str] = None
    mode: Optional[str] = None
    action: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class ExecuteTradeRequest(BaseModel):
    """Trade execution request for Jutsu Trader."""
    symbol: str = Field(..., description="Symbol to trade (QQQ, TQQQ, PSQ, TMF, TMV)")
    action: str = Field(..., description="Trade action: BUY or SELL")
    quantity: int = Field(..., gt=0, description="Number of shares to trade")
    reason: Optional[str] = Field(None, description="Optional reason for the trade")


class ExecuteTradeResponse(BaseModel):
    """Trade execution response for Jutsu Trader."""
    success: bool = Field(..., description="Whether trade executed successfully")
    trade_id: Optional[int] = Field(None, description="Database ID of executed trade")
    symbol: str = Field(..., description="Symbol traded")
    action: str = Field(..., description="Trade action (BUY/SELL)")
    quantity: int = Field(..., description="Shares traded")
    target_price: float = Field(..., description="Target/expected price")
    fill_price: Optional[float] = Field(None, description="Actual fill price")
    fill_value: Optional[float] = Field(None, description="Total value of trade")
    slippage_pct: Optional[float] = Field(None, description="Slippage percentage")
    message: str = Field(..., description="Execution result message")
    timestamp: datetime = Field(..., description="Execution timestamp")


# ==============================================================================
# PERFORMANCE SCHEMAS
# ==============================================================================

class HoldingInfo(BaseModel):
    """Individual position holding information."""
    symbol: str
    quantity: int
    value: float
    weight_pct: float = Field(..., description="Position weight as % of total equity")


class PerformanceMetrics(BaseModel):
    """Performance metrics summary."""
    total_equity: float
    holdings: List[HoldingInfo] = Field(default_factory=list, description="Current position holdings")
    cash: Optional[float] = None
    cash_weight_pct: Optional[float] = Field(None, description="Cash weight as % of total equity")
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    drawdown: Optional[float] = None
    high_water_mark: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0


class SnapshotPositionInfo(BaseModel):
    """Position info within a performance snapshot."""
    symbol: str
    quantity: int
    value: float


class PerformanceSnapshot(BaseModel):
    """Daily performance snapshot."""
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    total_equity: float
    cash: Optional[float] = None
    positions_value: Optional[float] = None
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    drawdown: Optional[float] = None
    strategy_cell: Optional[int] = None
    trend_state: Optional[str] = None
    vol_state: Optional[str] = None
    positions: Optional[List[SnapshotPositionInfo]] = None  # Position breakdown
    baseline_value: Optional[float] = Field(None, description="QQQ buy-and-hold portfolio value")
    baseline_return: Optional[float] = Field(None, description="QQQ buy-and-hold cumulative return %")
    mode: str


class PerformanceResponse(BaseModel):
    """Performance endpoint response."""
    current: PerformanceMetrics
    history: List[PerformanceSnapshot] = []
    mode: str


# ==============================================================================
# CONTROL SCHEMAS
# ==============================================================================

class ControlAction(BaseModel):
    """Control action request."""
    action: str = Field(..., description="start, stop, restart")
    mode: Optional[str] = Field(None, description="Trading mode for start action")
    confirm: bool = Field(False, description="Confirmation for destructive actions")


class ControlResponse(BaseModel):
    """Control action response."""
    success: bool
    action: str
    previous_state: str
    new_state: str
    message: str
    timestamp: datetime


# ==============================================================================
# INDICATOR SCHEMAS
# ==============================================================================

class IndicatorValue(BaseModel):
    """Single indicator value."""
    name: str
    value: float
    signal: Optional[str] = None
    description: Optional[str] = None


class IndicatorsResponse(BaseModel):
    """Current indicator values."""
    timestamp: datetime
    indicators: List[IndicatorValue]
    symbol: str = "QQQ"  # Signal symbol
    target_allocation: Optional[Dict[str, float]] = None  # Target allocation percentages by symbol


# ==============================================================================
# WEBSOCKET SCHEMAS (Phase 4)
# ==============================================================================

class WSMessage(BaseModel):
    """WebSocket message format."""
    type: str = Field(..., description="Message type: status, trade, indicator, error")
    data: Dict[str, Any]
    timestamp: datetime


# ==============================================================================
# SCHEDULER SCHEMAS
# ==============================================================================

class SchedulerStatus(BaseModel):
    """Scheduler status response."""
    enabled: bool = Field(..., description="Whether scheduled execution is enabled")
    execution_time: str = Field(..., description="Execution time key (e.g., '15min_after_open')")
    execution_time_est: str = Field(..., description="Human-readable EST time (e.g., '09:45 AM EST')")
    next_run: Optional[str] = Field(None, description="Next scheduled run (ISO format)")
    next_refresh: Optional[str] = Field(None, description="Next market close refresh (ISO format)")
    last_run: Optional[str] = Field(None, description="Last execution time (ISO format)")
    last_run_status: Optional[str] = Field(None, description="Last run status: success, failed, skipped")
    last_error: Optional[str] = Field(None, description="Error message if last run failed")
    run_count: int = Field(0, description="Total number of scheduled runs")
    is_running: bool = Field(False, description="Whether a job is currently executing")
    is_running_refresh: bool = Field(False, description="Whether data refresh is running")
    valid_execution_times: List[str] = Field(
        default_factory=list,
        description="List of valid execution time keys"
    )


class SchedulerEnableRequest(BaseModel):
    """Request to enable scheduler."""
    execution_time: Optional[str] = Field(
        None,
        description="Optional execution time to set when enabling"
    )


class SchedulerTriggerResponse(BaseModel):
    """Response from manual trigger."""
    success: bool = Field(..., description="Whether trigger was successful")
    message: str = Field(..., description="Result message")
    timestamp: str = Field(..., description="Trigger timestamp (ISO format)")
    status: Optional[str] = Field(None, description="Execution status")
    error: Optional[str] = Field(None, description="Error if execution failed")


class SchedulerUpdateRequest(BaseModel):
    """Request to update scheduler settings."""
    execution_time: str = Field(
        ...,
        description="Execution time key: open, 15min_after_open, 15min_before_close, 5min_before_close, close"
    )


class DataRefreshResponse(BaseModel):
    """Response from data refresh operation."""
    success: bool = Field(..., description="Whether refresh was successful")
    message: str = Field(..., description="Result message")
    timestamp: str = Field(..., description="Refresh timestamp (ISO format)")
    details: Optional[Dict[str, Any]] = Field(None, description="Detailed refresh results")


class DataStalenessInfo(BaseModel):
    """Information about data staleness."""
    is_stale: bool = Field(..., description="Whether data is stale")
    last_snapshot: Optional[str] = Field(None, description="Last snapshot timestamp (ISO format)")
    age_hours: Optional[float] = Field(None, description="Age of last snapshot in hours")
    threshold_hours: float = Field(1.0, description="Staleness threshold in hours")


# ==============================================================================
# ERROR SCHEMAS
# ==============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ValidationError(BaseModel):
    """Validation error detail."""
    field: str
    message: str
    value: Optional[Any] = None
