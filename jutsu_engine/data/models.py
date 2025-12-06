"""
SQLAlchemy database models for market data storage.

Defines the schema for storing OHLCV data and metadata for incremental updates.
"""
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Numeric,
    BigInteger,
    Boolean,
    Text,
    Enum,
    UniqueConstraint,
    Index,
)
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class MarketData(Base):
    """
    Historical OHLCV market data.

    Stores individual bars (candles) with source tracking and timestamps.
    Unique constraint prevents duplicate bars.

    Indexes:
        - (symbol, timeframe, timestamp) for fast queries
        - timestamp for date range queries
    """

    __tablename__ = 'market_data'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)  # '1D', '1H', '5m', etc.
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # OHLCV data - use Numeric for financial precision
    open = Column(Numeric(18, 6), nullable=False)
    high = Column(Numeric(18, 6), nullable=False)
    low = Column(Numeric(18, 6), nullable=False)
    close = Column(Numeric(18, 6), nullable=False)
    volume = Column(BigInteger, nullable=False)

    # Metadata
    data_source = Column(String(20), nullable=False)  # 'schwab', 'csv', 'yahoo', etc.
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    is_valid = Column(Boolean, default=True)  # For marking bad data without deleting

    # Unique constraint: one bar per symbol/timeframe/timestamp
    __table_args__ = (
        UniqueConstraint('symbol', 'timeframe', 'timestamp', name='uix_symbol_tf_ts'),
        Index('idx_market_data_lookup', 'symbol', 'timeframe', 'timestamp'),
    )

    def __repr__(self):
        return (
            f"<MarketData(symbol={self.symbol}, timeframe={self.timeframe}, "
            f"timestamp={self.timestamp}, close={self.close})>"
        )


class DataMetadata(Base):
    """
    Metadata for tracking available data and enabling incremental updates.

    Stores information about what data we have for each symbol/timeframe
    combination. Used to determine what new data to fetch from APIs.

    Example:
        If last_bar_timestamp is 2024-10-30, next sync will fetch from 2024-10-31.
    """

    __tablename__ = 'data_metadata'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False)
    timeframe = Column(String(10), nullable=False)

    # Data range tracking
    last_bar_timestamp = Column(DateTime(timezone=True))  # Latest bar we have
    total_bars = Column(Integer, default=0)  # Count for validation
    last_updated = Column(DateTime(timezone=True))  # When we last synced

    # Unique constraint: one metadata entry per symbol/timeframe
    __table_args__ = (
        UniqueConstraint('symbol', 'timeframe', name='uix_metadata'),
        Index('idx_metadata_lookup', 'symbol', 'timeframe'),
    )

    def __repr__(self):
        return (
            f"<DataMetadata(symbol={self.symbol}, timeframe={self.timeframe}, "
            f"bars={self.total_bars}, last_bar={self.last_bar_timestamp})>"
        )


class DataAuditLog(Base):
    """
    Audit log for tracking all data modifications.

    Required for financial data compliance - tracks who changed what and when.
    Provides complete audit trail for data lineage.

    Example uses:
        - Track when data was corrected
        - Investigate data quality issues
        - Regulatory compliance
    """

    __tablename__ = 'data_audit_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10))  # Stock symbol
    timeframe = Column(String(10))  # Timeframe (1D, 1H, etc.)
    operation = Column(String(20), nullable=False)  # 'sync', 'fetch', 'update', 'delete'
    status = Column(String(20), nullable=False)  # 'success', 'error', 'warning'
    message = Column(String(500))  # Operation details
    bars_affected = Column(Integer, default=0)  # Number of bars changed
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (Index('idx_audit_log_timestamp', 'timestamp'),)

    def __repr__(self):
        return (
            f"<DataAuditLog(operation={self.operation}, status={self.status}, "
            f"symbol={self.symbol}, timestamp={self.timestamp})>"
        )


# ==============================================================================
# LIVE TRADING MODELS (Phase 0 - Foundation Enhancement)
# ==============================================================================


class TradingModeEnum(enum.Enum):
    """Trading mode enumeration for distinguishing offline mock vs online live trades."""
    OFFLINE_MOCK = "offline_mock"
    ONLINE_LIVE = "online_live"


class LiveTrade(Base):
    """
    Live trading transaction record.

    Stores all live trades (both mock and real) with execution details,
    strategy context, and slippage analysis. Required for audit trail
    and post-trade analysis.

    Indexes:
        - timestamp for chronological queries
        - (symbol, mode) for filtering by symbol and trading mode
        - (mode, timestamp) for querying trades by mode
    """

    __tablename__ = 'live_trades'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Trade identification
    symbol = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Execution details
    action = Column(String(10), nullable=False)  # 'BUY' or 'SELL'
    quantity = Column(Integer, nullable=False)
    target_price = Column(Numeric(18, 6), nullable=False)  # Price at signal time
    fill_price = Column(Numeric(18, 6))  # Actual execution price (null for mock)
    fill_value = Column(Numeric(18, 6))  # Total trade value (qty * price)

    # Slippage analysis
    slippage_pct = Column(Numeric(10, 6))  # (fill - target) / target * 100

    # External references
    schwab_order_id = Column(String(50))  # Schwab API order ID (online only)

    # Strategy context (for trade analysis)
    strategy_cell = Column(Integer)  # Regime cell (1-6)
    trend_state = Column(String(20))  # BullStrong, Sideways, BearStrong
    vol_state = Column(String(10))  # Low, High
    t_norm = Column(Numeric(10, 6))  # Normalized trend indicator
    z_score = Column(Numeric(10, 6))  # Volatility z-score

    # Trade classification
    reason = Column(String(50))  # 'Rebalance', 'Signal Change', etc.
    mode = Column(String(20), nullable=False)  # 'offline_mock' or 'online_live'

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_live_trades_mode_ts', 'mode', 'timestamp'),
        Index('idx_live_trades_symbol_mode', 'symbol', 'mode'),
    )

    def __repr__(self):
        return (
            f"<LiveTrade(symbol={self.symbol}, action={self.action}, "
            f"qty={self.quantity}, mode={self.mode}, ts={self.timestamp})>"
        )


class Position(Base):
    """
    Current position holdings for live trading.

    Tracks real-time position state for each symbol. Updated after
    each trade execution. Separate records for each trading mode.

    Indexes:
        - (symbol, mode) for unique position lookup
    """

    __tablename__ = 'positions'

    id = Column(Integer, primary_key=True, autoincrement=True)

    symbol = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    avg_cost = Column(Numeric(18, 6))  # Average cost basis
    market_value = Column(Numeric(18, 6))  # Current market value
    unrealized_pnl = Column(Numeric(18, 6))  # Unrealized profit/loss

    mode = Column(String(20), nullable=False)  # 'offline_mock' or 'online_live'

    last_updated = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('symbol', 'mode', name='uix_position_symbol_mode'),
        Index('idx_positions_mode', 'mode'),
    )

    def __repr__(self):
        return (
            f"<Position(symbol={self.symbol}, qty={self.quantity}, "
            f"mode={self.mode})>"
        )


class PerformanceSnapshot(Base):
    """
    Daily performance snapshot for tracking strategy performance.

    Captures end-of-day portfolio state including equity, returns,
    drawdown, and current regime. Used for dashboard visualization
    and performance analysis.

    Indexes:
        - (mode, timestamp) for time-series queries by mode
    """

    __tablename__ = 'performance_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)

    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Portfolio metrics - Decimal precision (18,6) for financial accuracy
    total_equity = Column(Numeric(18, 6), nullable=False)
    cash = Column(Numeric(18, 6))
    positions_value = Column(Numeric(18, 6))

    # Return metrics
    daily_return = Column(Numeric(10, 6))  # Day-over-day return %
    cumulative_return = Column(Numeric(10, 6))  # Total return since inception %
    drawdown = Column(Numeric(10, 6))  # Current drawdown from high water mark %

    # Strategy state at snapshot time
    strategy_cell = Column(Integer)  # Current regime cell (1-6)
    trend_state = Column(String(20))  # BullStrong, Sideways, BearStrong
    vol_state = Column(String(10))  # Low, High

    # Position breakdown at snapshot time (JSON: [{symbol, quantity, value}])
    positions_json = Column(Text)  # JSON string of position breakdown

    # QQQ Baseline comparison (buy-and-hold benchmark)
    baseline_value = Column(Numeric(18, 6))  # QQQ buy-and-hold portfolio value
    baseline_return = Column(Numeric(10, 6))  # QQQ buy-and-hold cumulative return %

    mode = Column(String(20), nullable=False)  # 'offline_mock' or 'online_live'

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_perf_snapshot_mode_ts', 'mode', 'timestamp'),
        UniqueConstraint('mode', 'timestamp', name='uix_perf_snapshot_mode_ts'),
    )

    def __repr__(self):
        return (
            f"<PerformanceSnapshot(equity={self.total_equity}, "
            f"return={self.daily_return}%, mode={self.mode}, ts={self.timestamp})>"
        )


class ConfigOverride(Base):
    """
    Runtime parameter overrides for live trading.

    Allows modifying strategy parameters without restarting.
    Changes are validated and logged. Only active overrides
    are applied; inactive ones are kept for audit trail.

    Indexes:
        - (parameter_name, is_active) for fast active override lookup
    """

    __tablename__ = 'config_overrides'

    id = Column(Integer, primary_key=True, autoincrement=True)

    parameter_name = Column(String(50), nullable=False)  # Flat parameter name
    original_value = Column(String(100))  # Value before override
    override_value = Column(String(100), nullable=False)  # New value
    value_type = Column(String(20), nullable=False)  # 'int', 'float', 'decimal', 'bool', 'str'

    is_active = Column(Boolean, default=True)  # Currently applied
    reason = Column(String(200))  # Why override was created

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    deactivated_at = Column(DateTime(timezone=True))  # When override was removed

    __table_args__ = (
        Index('idx_config_override_active', 'parameter_name', 'is_active'),
    )

    def __repr__(self):
        return (
            f"<ConfigOverride({self.parameter_name}: {self.override_value}, "
            f"active={self.is_active})>"
        )


class ConfigHistory(Base):
    """
    Audit log for configuration changes.

    Tracks all parameter modifications for regulatory compliance
    and debugging. Immutable - never modified after creation.

    Indexes:
        - timestamp for chronological queries
        - parameter_name for filtering by parameter
    """

    __tablename__ = 'config_history'

    id = Column(Integer, primary_key=True, autoincrement=True)

    parameter_name = Column(String(50), nullable=False, index=True)
    old_value = Column(String(100))
    new_value = Column(String(100), nullable=False)
    change_type = Column(String(20), nullable=False)  # 'override', 'restore', 'update'

    changed_by = Column(String(50))  # 'user', 'system', 'dashboard'
    reason = Column(String(200))

    timestamp = Column(DateTime(timezone=True), nullable=False, index=True, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"<ConfigHistory({self.parameter_name}: {self.old_value} → {self.new_value}, "
            f"ts={self.timestamp})>"
        )


class SystemState(Base):
    """
    Key-value store for system state persistence.

    Stores critical system state like last run timestamp, current
    regime, and recovery information. Used for crash recovery
    and cross-session state management.

    Indexes:
        - key for fast lookups
    """

    __tablename__ = 'system_state'

    id = Column(Integer, primary_key=True, autoincrement=True)

    key = Column(String(50), nullable=False, unique=True, index=True)
    value = Column(Text)  # JSON-serialized value
    value_type = Column(String(20))  # 'string', 'int', 'float', 'json', 'datetime'

    last_updated = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<SystemState({self.key}={self.value[:50] if self.value else None}...)>"


# ==============================================================================
# USER AUTHENTICATION MODELS
# ==============================================================================


class User(Base):
    """
    User account for dashboard authentication.

    Stores user credentials and session information for JWT-based
    authentication. Passwords are stored as bcrypt hashes.

    Design decisions:
    - Single user mode by default (admin user)
    - JWT tokens with 7-day expiry for persistent sessions
    - Email optional (not required for single user mode)

    Indexes:
        - username for fast login lookups
    """

    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Authentication
    username = Column(String(50), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash

    # Optional profile info
    email = Column(String(255), unique=True, nullable=True)

    # Account state
    is_active = Column(Boolean, default=True)  # Can disable without deleting
    is_admin = Column(Boolean, default=True)  # Admin flag (all users admin for now)

    # Session tracking
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<User(username={self.username}, active={self.is_active})>"
