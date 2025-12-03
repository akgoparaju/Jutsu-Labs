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
    - order_executor: Real order execution (Phase 2)
    - slippage_validator: Fill quality validation (Phase 2)
    - alert_manager: SMS/Email alerts (Phase 3)
    - health_monitor: System health checks (Phase 3)

Usage:
    from jutsu_engine.live import LiveDataFetcher, StateManager

    # Fetch live data
    fetcher = LiveDataFetcher(client)
    data = fetcher.fetch_historical_bars('QQQ', lookback=250)

    # Manage state
    manager = StateManager()
    state = manager.load_state()
"""

__version__ = '1.0.0'
__author__ = 'Anil Goparaju, Padma Priya Garnepudi'

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

# Phase 2 imports (future)
try:
    from jutsu_engine.live.order_executor import OrderExecutor
except ImportError:
    OrderExecutor = None

try:
    from jutsu_engine.live.slippage_validator import SlippageValidator
except ImportError:
    SlippageValidator = None

# Phase 3 imports (future)
try:
    from jutsu_engine.live.alert_manager import AlertManager
except ImportError:
    AlertManager = None

try:
    from jutsu_engine.live.health_monitor import HealthMonitor
except ImportError:
    HealthMonitor = None

__all__ = [
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
    # Phase 2
    'OrderExecutor',
    'SlippageValidator',
    # Phase 3
    'AlertManager',
    'HealthMonitor',
]
