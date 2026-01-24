"""
SQLAlchemy database models for market data storage.

Defines the schema for storing OHLCV data and metadata for incremental updates.
"""
from datetime import datetime, timezone
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
    ForeignKey,
    LargeBinary,
    JSON,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    """
    User roles for role-based access control.
    
    Roles:
        ADMIN: Full access to all features including user management,
               engine control, scheduler, and trade execution
        VIEWER: Read-only access to dashboard data, can manage own
                password, 2FA, and passkeys
    
    Future:
        INVESTOR: Viewer + portfolio management (when needed)
    """
    ADMIN = "admin"
    VIEWER = "viewer"
    # INVESTOR = "investor"  # Future: for real money tracking


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
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
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

    # Multi-strategy support (added 2026-01-20)
    # Identifies which strategy generated this trade
    strategy_id = Column(String(50), default='v3_5b')  # e.g., 'v3_5b', 'v3_5d'

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index('idx_live_trades_mode_ts', 'mode', 'timestamp'),
        Index('idx_live_trades_symbol_mode', 'symbol', 'mode'),
        Index('idx_live_trades_strategy', 'strategy_id', 'timestamp'),
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
    each trade execution. Separate records for each trading mode and strategy.

    Indexes:
        - (symbol, mode, strategy_id) for unique position lookup
        - (strategy_id, timestamp) for strategy filtering
    """

    __tablename__ = 'positions'

    id = Column(Integer, primary_key=True, autoincrement=True)

    symbol = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    avg_cost = Column(Numeric(18, 6))  # Average cost basis
    market_value = Column(Numeric(18, 6))  # Current market value
    unrealized_pnl = Column(Numeric(18, 6))  # Unrealized profit/loss

    mode = Column(String(20), nullable=False)  # 'offline_mock' or 'online_live'

    # Multi-strategy support (added 2026-01-22 Phase 2)
    # Identifies which strategy this position belongs to
    strategy_id = Column(String(50), default='v3_5b')  # e.g., 'v3_5b', 'v3_5d'

    last_updated = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # Updated unique constraint to include strategy_id for multi-strategy support
        UniqueConstraint('symbol', 'mode', 'strategy_id', name='uix_position_symbol_mode_strategy'),
        Index('idx_positions_mode', 'mode'),
        Index('idx_positions_strategy', 'strategy_id'),
    )

    def __repr__(self):
        return (
            f"<Position(symbol={self.symbol}, qty={self.quantity}, "
            f"strategy={self.strategy_id}, mode={self.mode})>"
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

    # Source of this snapshot for regime authority tracking
    # "scheduler" = authoritative for regime, "refresh" = P/L only, "manual" = user-triggered
    snapshot_source = Column(String(20))  # "scheduler" | "refresh" | "manual"

    # Indicator values at snapshot time (scheduler snapshots only)
    # These are the values used by scheduler to determine regime
    t_norm = Column(Numeric(10, 6))  # Normalized trend indicator (-1 to 1)
    z_score = Column(Numeric(10, 6))  # Volatility z-score
    sma_fast = Column(Numeric(18, 6))  # QQQ fast SMA value
    sma_slow = Column(Numeric(18, 6))  # QQQ slow SMA value

    # Position breakdown at snapshot time (JSON: [{symbol, quantity, value}])
    positions_json = Column(Text)  # JSON string of position breakdown

    # QQQ Baseline comparison (buy-and-hold benchmark)
    baseline_value = Column(Numeric(18, 6))  # QQQ buy-and-hold portfolio value
    baseline_return = Column(Numeric(10, 6))  # QQQ buy-and-hold cumulative return %

    mode = Column(String(20), nullable=False)  # 'offline_mock' or 'online_live'

    # Multi-strategy support (added 2026-01-20)
    # Identifies which strategy this snapshot belongs to
    strategy_id = Column(String(50), default='v3_5b')  # e.g., 'v3_5b', 'v3_5d'

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index('idx_perf_snapshot_mode_ts', 'mode', 'timestamp'),
        Index('idx_perf_snapshots_strategy', 'strategy_id', 'timestamp'),
        # Updated unique constraint to include strategy_id for multi-strategy support
        UniqueConstraint('mode', 'strategy_id', 'timestamp', name='uix_perf_snapshot_mode_strategy_ts'),
    )

    def __repr__(self):
        return (
            f"<PerformanceSnapshot(equity={self.total_equity}, strategy={self.strategy_id}, "
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

    # Multi-strategy support (added 2026-01-22)
    # Identifies which strategy this override applies to
    strategy_id = Column(String(50), default='v3_5b')  # e.g., 'v3_5b', 'v3_5d'

    is_active = Column(Boolean, default=True)  # Currently applied
    reason = Column(String(200))  # Why override was created

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deactivated_at = Column(DateTime(timezone=True))  # When override was removed

    __table_args__ = (
        Index('idx_config_override_active', 'parameter_name', 'strategy_id', 'is_active'),
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

    # Renamed from 'last_updated' to 'updated_at' for consistency
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

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
    - Account lockout after 10 failed login attempts (30 minute lockout)
    - Failed login counter reset on successful authentication

    Security features:
    - failed_login_count: Tracks consecutive failed login attempts
    - locked_until: Timestamp when account lockout expires (None if not locked)
    - Account automatically unlocks after 30 minutes
    - Counter resets to 0 on successful login

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
    
    # Role-based access control (replaces is_admin boolean)
    # Default to "viewer" for new users - admin sets initial admin via migration
    role = Column(String(20), default="viewer", nullable=False, index=True)
    
    @property
    def is_admin(self) -> bool:
        """Backward compatibility property. Check if user has admin role."""
        return self.role == "admin"

    # Account lockout (brute force protection) - OWASP ASVS V2.2.1, V2.2.2, CWE-307
    failed_login_count = Column(Integer, default=0)  # Consecutive failed login attempts
    locked_until = Column(DateTime(timezone=True), nullable=True)  # Lockout expiration timestamp

    # Session tracking
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Two-Factor Authentication (2FA/TOTP)
    # Security: totp_secret is encrypted at rest using Fernet (AES-256-GCM) when TOTP_ENCRYPTION_KEY is set
    # Compliance: NIST 800-63B Section 5.1.4.2, OWASP ASVS 2.9.2
    totp_secret = Column(String(255), nullable=True)  # Encrypted TOTP secret (Fernet token or legacy plaintext)
    totp_enabled = Column(Boolean, default=False)     # Whether 2FA is active
    # Security: backup_codes are stored as bcrypt hashes (like passwords)
    # Compliance: NIST 800-63B Section 5.1.2 - recovery secrets must be hashed
    backup_codes = Column(JSON, nullable=True)  # List of bcrypt-hashed backup codes

    # Passkey/WebAuthn relationship
    passkeys = relationship("Passkey", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(username={self.username}, active={self.is_active})>"


class Passkey(Base):
    """
    WebAuthn passkey credential for passwordless 2FA bypass.

    Each user can have multiple passkeys (one per device).
    Passkeys are valid forever until manually revoked.

    Security features:
    - sign_count: Protects against cloned authenticators (replay attacks)
    - credential_id: Unique identifier from the authenticator
    - public_key: COSE-format public key for signature verification

    Design decisions:
    - Multiple passkeys per user (multi-device support)
    - Replaces 2FA only (password still required)
    - Falls back to TOTP if no passkey for device
    - Never expires until manually revoked

    Indexes:
        - credential_id for fast lookup during authentication
        - user_id for listing user's passkeys
    """

    __tablename__ = 'passkeys'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # WebAuthn credential data (from registration)
    credential_id = Column(LargeBinary, nullable=False, unique=True, index=True)
    public_key = Column(LargeBinary, nullable=False)  # COSE format
    sign_count = Column(Integer, default=0, nullable=False)  # Replay attack protection

    # User-friendly metadata
    device_name = Column(String(100), nullable=True)  # "MacBook Pro", "iPhone 15"

    # AAGUID for authenticator identification (optional)
    aaguid = Column(String(36), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    user = relationship("User", back_populates="passkeys")

    def __repr__(self):
        return f"<Passkey(id={self.id}, user_id={self.user_id}, device={self.device_name})>"


class BlacklistedToken(Base):
    """
    Blacklisted JWT tokens for logout/revocation.

    Tokens added here are rejected even if cryptographically valid.
    A background job should clean up expired entries periodically.

    Design decisions:
    - jti (JWT ID) is the unique identifier for each token
    - Store token type to differentiate access vs refresh tokens
    - Store expiration time to enable automatic cleanup of old entries
    - Optional user_id link for auditing and user-specific token revocation

    Security:
    - OWASP ASVS V3.5.3: Server-side token revocation
    - Stolen tokens invalidated on logout
    - Backward compatible with legacy tokens (no JTI)

    Indexes:
        - jti for fast blacklist lookups during token validation
    """
    __tablename__ = 'blacklisted_tokens'

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(36), unique=True, nullable=False, index=True)  # JWT ID
    token_type = Column(String(10), nullable=False)  # 'access' or 'refresh'
    blacklisted_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Original token expiry for cleanup
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # Optional link to user

    def __repr__(self):
        return f"<BlacklistedToken(jti={self.jti}, type={self.token_type})>"


class UserInvitation(Base):
    """
    Invitation for new user registration.
    
    Allows admin to generate secure invitation links for new users.
    New users set their own password and username via the invitation link.
    
    Design decisions:
    - Single-use tokens (marked as accepted after use)
    - 48-hour expiry for security
    - Role assigned at invitation creation
    - Email optional (just a hint for the invitation)
    - Token is cryptographically random (32 bytes urlsafe)
    
    Security features:
    - Tokens expire after 48 hours (configurable)
    - Single-use only (accepted_at tracking)
    - Audit trail (created_by, accepted_by)
    - Secure random token generation
    
    Indexes:
        - token for fast invitation lookup during acceptance
    """
    __tablename__ = 'user_invitations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Invitation details
    email = Column(String(255), nullable=True)  # Optional email hint
    # Security: Token is stored as SHA-256 hash (64 hex chars) for security
    # Compliance: Protects invitation tokens from database exposure
    token = Column(String(64), unique=True, nullable=False, index=True)
    role = Column(String(20), default="viewer", nullable=False)
    
    # Tracking
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    
    # Usage
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by], backref="created_invitations")

    def __repr__(self):
        status = "used" if self.accepted_at else "pending"
        return f"<UserInvitation(role={self.role}, status={status}, expires={self.expires_at})>"


# ==============================================================================
# EOD DAILY PERFORMANCE MODELS (Phase 1 - Foundation)
# ==============================================================================


class EntityTypeEnum(str, enum.Enum):
    """Entity type enumeration for daily_performance table."""
    STRATEGY = "strategy"
    BASELINE = "baseline"


class EODJobStatusEnum(str, enum.Enum):
    """EOD job status enumeration."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class DailyPerformance(Base):
    """
    Authoritative end-of-day performance metrics.

    Single source of truth for daily strategy and baseline performance.
    One row per entity (strategy/baseline) per trading day per mode.
    Pre-computed KPIs calculated at 4:15 PM ET via EOD finalization job.

    This table fixes the Sharpe ratio bug (showing -4 instead of ~0.82) by:
    - Calculating daily returns from equity changes (not stored daily_return values)
    - Having exactly one row per day (not 5-13 snapshots)
    - Pre-computing all KPIs at EOD instead of on-the-fly

    Entity Types:
        - 'strategy': Trading strategies (v3_5b, v3_5d, etc.)
        - 'baseline': Buy-and-hold benchmarks (QQQ, SPY, etc.)

    Corner Cases Handled:
        - First day (cold start): is_first_day=True, daily_return=0
        - Data gaps: days_since_previous > 1, warning logged
        - Half-days: Triggered at 1:15 PM ET instead of 4:15 PM ET

    Scalability:
        - Incremental KPI state (returns_sum, etc.) enables O(1) daily updates
        - Uses Welford's algorithm for numerically stable variance calculation

    Reference: claudedocs/eod_daily_performance_architecture.md v1.1
    """

    __tablename__ = 'daily_performance'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Composite Natural Key
    trading_date = Column(DateTime(timezone=False), nullable=False)  # DATE type - no time component
    entity_type = Column(String(10), nullable=False)  # 'strategy' or 'baseline'
    entity_id = Column(String(50), nullable=False)    # 'v3_5b', 'v3_5d', 'QQQ', etc.
    mode = Column(String(20), nullable=False)         # 'offline_mock' or 'online_live'

    # Portfolio State (End of Day)
    total_equity = Column(Numeric(18, 6), nullable=False)
    cash = Column(Numeric(18, 6), nullable=True)
    positions_value = Column(Numeric(18, 6), nullable=True)
    positions_json = Column(Text, nullable=True)  # JSON: [{symbol, quantity, value, weight}]

    # Daily Metrics (Equity-Based) - CRITICAL: These are decimals, not percentages
    # 0.01 = 1%, NOT 1.0 = 1%
    daily_return = Column(Numeric(10, 6), nullable=False)     # (today - yesterday) / yesterday
    cumulative_return = Column(Numeric(10, 6), nullable=False) # (today - initial) / initial
    drawdown = Column(Numeric(10, 6), nullable=True)          # (equity - HWM) / HWM

    # Pre-Computed KPIs (All-Time from Inception)
    sharpe_ratio = Column(Numeric(10, 6), nullable=True)      # Annualized, risk-free rate = 0
    sortino_ratio = Column(Numeric(10, 6), nullable=True)     # Downside deviation based
    calmar_ratio = Column(Numeric(10, 6), nullable=True)      # CAGR / Max Drawdown
    max_drawdown = Column(Numeric(10, 6), nullable=True)      # Maximum peak-to-trough decline
    volatility = Column(Numeric(10, 6), nullable=True)        # Annualized standard deviation
    cagr = Column(Numeric(10, 6), nullable=True)              # Compound Annual Growth Rate

    # Strategy State (Strategies Only - NULL for baselines)
    strategy_cell = Column(Integer, nullable=True)            # Current regime cell (1-6)
    trend_state = Column(String(20), nullable=True)           # BullStrong, Sideways, BearStrong
    vol_state = Column(String(10), nullable=True)             # Low, High

    # Indicator Values (Strategies Only - NULL for baselines)
    t_norm = Column(Numeric(10, 6), nullable=True)
    z_score = Column(Numeric(10, 6), nullable=True)
    sma_fast = Column(Numeric(18, 6), nullable=True)
    sma_slow = Column(Numeric(18, 6), nullable=True)

    # Trade Statistics (Strategies Only - NULL for baselines)
    total_trades = Column(Integer, default=0, nullable=True)
    winning_trades = Column(Integer, default=0, nullable=True)
    losing_trades = Column(Integer, default=0, nullable=True)
    win_rate = Column(Numeric(5, 2), nullable=True)           # winning_trades / total_trades * 100

    # Baseline Reference (Strategies Only - which baseline to compare against)
    baseline_symbol = Column(String(20), nullable=True)       # 'QQQ', 'SPY', etc.

    # Metadata
    initial_capital = Column(Numeric(18, 6), nullable=True)   # Starting capital for return calcs
    high_water_mark = Column(Numeric(18, 6), nullable=True)   # Peak equity for drawdown calc
    trading_days_count = Column(Integer, nullable=True)       # Number of trading days since inception

    # Corner Case Handling (v1.1)
    days_since_previous = Column(Integer, default=1, nullable=True)  # 1 = consecutive, >1 = gap
    is_first_day = Column(Boolean, default=False, nullable=True)     # True for first trading day

    # Incremental KPI State for O(1) updates (v1.1 - Welford's algorithm)
    returns_sum = Column(Numeric(18, 8), nullable=True)       # Running sum of daily_returns
    returns_sum_sq = Column(Numeric(18, 8), nullable=True)    # Running sum of daily_returns squared
    downside_sum_sq = Column(Numeric(18, 8), nullable=True)   # Running sum of min(return, 0) squared
    returns_count = Column(Integer, nullable=True)            # Count of returns (excludes first day)

    finalized_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('trading_date', 'entity_type', 'entity_id', 'mode', name='uix_daily_perf'),
        Index('idx_daily_perf_date', 'trading_date'),
        Index('idx_daily_perf_entity', 'entity_type', 'entity_id'),
        Index('idx_daily_perf_mode_entity', 'mode', 'entity_type', 'entity_id', 'trading_date'),
    )

    def to_dict(self) -> dict:
        """
        Convert to JSON-serializable dictionary for API responses.

        Returns:
            dict: All columns as JSON-serializable values
        """
        return {
            'trading_date': self.trading_date.isoformat() if self.trading_date else None,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'mode': self.mode,
            'total_equity': float(self.total_equity) if self.total_equity else None,
            'cash': float(self.cash) if self.cash else None,
            'positions_value': float(self.positions_value) if self.positions_value else None,
            'daily_return': float(self.daily_return) if self.daily_return is not None else None,
            'cumulative_return': float(self.cumulative_return) if self.cumulative_return is not None else None,
            'drawdown': float(self.drawdown) if self.drawdown else None,
            'sharpe_ratio': float(self.sharpe_ratio) if self.sharpe_ratio else None,
            'sortino_ratio': float(self.sortino_ratio) if self.sortino_ratio else None,
            'calmar_ratio': float(self.calmar_ratio) if self.calmar_ratio else None,
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown else None,
            'volatility': float(self.volatility) if self.volatility else None,
            'cagr': float(self.cagr) if self.cagr else None,
            'strategy_cell': self.strategy_cell,
            'trend_state': self.trend_state,
            'vol_state': self.vol_state,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': float(self.win_rate) if self.win_rate else None,
            'baseline_symbol': self.baseline_symbol,
            'trading_days_count': self.trading_days_count,
            'days_since_previous': self.days_since_previous,
            'is_first_day': self.is_first_day,
            'finalized_at': self.finalized_at.isoformat() if self.finalized_at else None,
        }

    @classmethod
    def get_latest(cls, session, entity_id: str, mode: str = 'offline_mock') -> 'DailyPerformance':
        """
        Get the latest daily performance record for an entity.

        Args:
            session: SQLAlchemy session
            entity_id: Strategy ID or baseline symbol
            mode: Trading mode (offline_mock or online_live)

        Returns:
            DailyPerformance: Latest record or None
        """
        from sqlalchemy import desc
        return session.query(cls).filter(
            cls.entity_id == entity_id,
            cls.mode == mode
        ).order_by(desc(cls.trading_date)).first()

    @classmethod
    def get_history(
        cls,
        session,
        entity_id: str,
        mode: str = 'offline_mock',
        days: int = 30
    ) -> list:
        """
        Get historical daily performance records.

        Args:
            session: SQLAlchemy session
            entity_id: Strategy ID or baseline symbol
            mode: Trading mode
            days: Number of days of history (max 365)

        Returns:
            list[DailyPerformance]: Records in descending date order
        """
        from sqlalchemy import desc
        days = min(days, 365)
        return session.query(cls).filter(
            cls.entity_id == entity_id,
            cls.mode == mode
        ).order_by(desc(cls.trading_date)).limit(days).all()

    def __repr__(self):
        return (
            f"<DailyPerformance(date={self.trading_date}, entity={self.entity_id}, "
            f"equity={self.total_equity}, sharpe={self.sharpe_ratio}, mode={self.mode})>"
        )


class EODJobStatus(Base):
    """
    EOD finalization job execution tracking.

    Tracks the status of daily EOD finalization jobs for:
    - Failure recovery (auto-backfill missed days)
    - Progress monitoring (strategies_processed checkpoints)
    - Alerting and health checks

    Job Lifecycle:
        1. Job starts: status='running', started_at set
        2. Progress: strategies_processed incremented after each strategy
        3. Success: status='completed', completed_at set
        4. Failure: status='failed' or 'partial', error_message set

    Recovery Logic:
        - If 'running' for >1 hour: Consider as failed, retry
        - If 'partial': Some strategies succeeded, retry failed ones
        - If 'failed': Retry all with exponential backoff

    Reference: claudedocs/eod_daily_performance_architecture.md Section 8.3
    """

    __tablename__ = 'eod_job_status'

    job_date = Column(DateTime(timezone=False), primary_key=True)  # DATE type - trading day
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False)  # 'running', 'completed', 'failed', 'partial'

    strategies_total = Column(Integer, nullable=True)
    strategies_processed = Column(Integer, default=0, nullable=True)
    baselines_total = Column(Integer, nullable=True)
    baselines_processed = Column(Integer, default=0, nullable=True)

    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=True)

    __table_args__ = (
        Index('idx_eod_job_status', 'status', 'job_date'),
    )

    @property
    def is_complete(self) -> bool:
        """Check if job completed successfully."""
        return self.status == 'completed'

    @property
    def duration(self):
        """Calculate job duration."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    @property
    def progress_pct(self) -> float:
        """Calculate completion percentage."""
        total = (self.strategies_total or 0) + (self.baselines_total or 0)
        processed = (self.strategies_processed or 0) + (self.baselines_processed or 0)
        if total == 0:
            return 0.0
        return (processed / total) * 100

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            'job_date': self.job_date.isoformat() if self.job_date else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status,
            'strategies_total': self.strategies_total,
            'strategies_processed': self.strategies_processed,
            'baselines_total': self.baselines_total,
            'baselines_processed': self.baselines_processed,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'progress_pct': self.progress_pct,
            'duration_seconds': self.duration.total_seconds() if self.duration else None,
        }

    def __repr__(self):
        return (
            f"<EODJobStatus(date={self.job_date}, status={self.status}, "
            f"progress={self.strategies_processed}/{self.strategies_total})>"
        )
