"""
Live Trading Module

Purpose:
    Live trading system for automated execution of trading strategies.
    Supports dry-run, paper trading, and live trading modes.

Modules:
    - market_calendar: Trading day validation
    - data_fetcher: Live market data retrieval
    - strategy_runner: Strategy execution on live data
    - state_manager: State persistence and reconciliation
    - position_rounder: Whole share calculations
    - dry_run_executor: Dry-run mode (no real orders)
    - mock_order_executor: Mock order executor for testing (Phase 1)
    - live_order_executor: Live order executor base (Phase 1)
    - performance_tracker: Trade performance metrics (Phase 1)
    - schwab_executor: Real Schwab API executor (Phase 2)
    - reconciliation: Fill reconciliation with Schwab (Phase 2)
    - order_executor: Legacy order execution
    - slippage_validator: Fill quality validation (Phase 2)
    - alert_manager: SMS/Email alerts (Phase 3)
    - health_monitor: System health checks (Phase 3)
    - recovery: Crash recovery and missed execution detection (Phase 5)

Usage:
    from jutsu_engine.live import LiveDataFetcher, StateManager

    # Fetch live data
    fetcher = LiveDataFetcher(client)
    data = fetcher.fetch_historical_bars('QQQ', lookback=250)

    # Manage state
    manager = StateManager()
    state = manager.load_state()
"""

__version__ = '2.0.0'
__author__ = 'Anil Goparaju, Padma Priya Garnepudi'

# Core imports
from jutsu_engine.live.mode import TradingMode
from jutsu_engine.live.executor_router import ExecutorInterface, ExecutorRouter

# Phase 0 imports
from jutsu_engine.live.market_calendar import (
    is_trading_day,
    get_next_trading_day,
    get_previous_trading_day,
    is_market_open_now
)

# Phase 1 imports (will be available after implementation)
try:
    from jutsu_engine.live.data_fetcher import LiveDataFetcher
except ImportError:
    LiveDataFetcher = None

try:
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner
except ImportError:
    LiveStrategyRunner = None

try:
    from jutsu_engine.live.state_manager import StateManager
except ImportError:
    StateManager = None

try:
    from jutsu_engine.live.position_rounder import PositionRounder
except ImportError:
    PositionRounder = None

try:
    from jutsu_engine.live.dry_run_executor import DryRunExecutor
except ImportError:
    DryRunExecutor = None

try:
    from jutsu_engine.live.mock_order_executor import MockOrderExecutor
except ImportError:
    MockOrderExecutor = None

try:
    from jutsu_engine.live.live_order_executor import LiveOrderExecutor
except ImportError:
    LiveOrderExecutor = None

try:
    from jutsu_engine.live.performance_tracker import PerformanceTracker
except ImportError:
    PerformanceTracker = None

# Phase 2 imports
try:
    from jutsu_engine.live.order_executor import OrderExecutor
except ImportError:
    OrderExecutor = None

try:
    from jutsu_engine.live.slippage_validator import SlippageValidator
except ImportError:
    SlippageValidator = None

try:
    from jutsu_engine.live.schwab_executor import SchwabOrderExecutor
except ImportError:
    SchwabOrderExecutor = None

try:
    from jutsu_engine.live.reconciliation import FillReconciler, ReconciliationResult
except ImportError:
    FillReconciler = None
    ReconciliationResult = None

# Phase 3 imports (future)
try:
    from jutsu_engine.live.alert_manager import AlertManager
except ImportError:
    AlertManager = None

try:
    from jutsu_engine.live.health_monitor import HealthMonitor
except ImportError:
    HealthMonitor = None

# Phase 5 imports (Production Hardening)
try:
    from jutsu_engine.live.recovery import RecoveryManager, RecoveryAction
except ImportError:
    RecoveryManager = None
    RecoveryAction = None

# Multi-Strategy Engine imports
try:
    from jutsu_engine.live.strategy_registry import StrategyRegistry, StrategyConfig
except ImportError:
    StrategyRegistry = None
    StrategyConfig = None

try:
    from jutsu_engine.live.multi_state_manager import MultiStrategyStateManager
except ImportError:
    MultiStrategyStateManager = None

try:
    from jutsu_engine.live.multi_strategy_runner import (
        MultiStrategyRunner,
        StrategyExecutionResult,
        MultiExecutionResult
    )
except ImportError:
    MultiStrategyRunner = None
    StrategyExecutionResult = None
    MultiExecutionResult = None

__all__ = [
    # Core (v2.0)
    'TradingMode',
    'ExecutorInterface',
    'ExecutorRouter',
    'MockOrderExecutor',
    'LiveOrderExecutor',
    # Phase 0
    'is_trading_day',
    'get_next_trading_day',
    'get_previous_trading_day',
    'is_market_open_now',
    # Phase 1
    'LiveDataFetcher',
    'LiveStrategyRunner',
    'StateManager',
    'PositionRounder',
    'DryRunExecutor',
    'PerformanceTracker',
    # Phase 2
    'OrderExecutor',
    'SlippageValidator',
    'SchwabOrderExecutor',
    'FillReconciler',
    'ReconciliationResult',
    # Phase 3
    'AlertManager',
    'HealthMonitor',
    # Phase 5
    'RecoveryManager',
    'RecoveryAction',
    # Multi-Strategy Engine
    'StrategyRegistry',
    'StrategyConfig',
    'MultiStrategyStateManager',
    'MultiStrategyRunner',
    'StrategyExecutionResult',
    'MultiExecutionResult',
]
