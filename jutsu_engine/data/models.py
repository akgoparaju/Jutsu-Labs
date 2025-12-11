"""
Database models for Jutsu Backtesting Engine.

Defines SQLAlchemy ORM models for:
- Market Data (OHLCV bars)
- Data Metadata (tracking and synchronization)
- User Authentication (JWT-based auth)
- Two-Factor Authentication (TOTP)

Models use:
- Decimal type for precise financial calculations (avoid float errors)
- Timezone-aware datetime for consistent time handling
- Proper indexing for performance (symbol, timestamp lookups)

Design decisions:
- Immutable history: Never delete/update existing market data
- UTC timestamps: All datetimes stored in UTC for consistency
- Decimal precision: Use DECIMAL(20,8) for prices/volumes to avoid float errors
"""

from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, DECIMAL, DateTime, Enum, Index, ForeignKey, Boolean, ARRAY
)
from sqlalchemy.orm import DeclarativeBase
import enum


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# ==============================================================================
# MARKET DATA MODELS
# ==============================================================================

class Timeframe(str, enum.Enum):
    """
    Supported timeframes for market data.

    Each bar represents data aggregated over the timeframe period.
    For example, timeframe '1m' means each bar represents 1 minute of trading.

    Values:
        1m: 1 minute
        5m: 5 minutes
        15m: 15 minutes
        30m: 30 minutes
        1h: 1 hour
        1d: 1 day
    """
    ONE_MINUTE = '1m'
    FIVE_MINUTES = '5m'
    FIFTEEN_MINUTES = '15m'
    THIRTY_MINUTES = '30m'
    ONE_HOUR = '1h'
    ONE_DAY = '1d'


class MarketData(Base):
    """
    OHLCV bar data for a specific symbol and timeframe.

    Stores individual price bars (candlesticks) retrieved from data sources.
    Each bar represents trading activity over a specific timeframe period.

    Design decisions:
    - DECIMAL(20,8) for prices (8 decimals = sub-cent precision, 12 integer digits)
    - DECIMAL(20,4) for volume (4 decimals for fractional shares, 16 integer digits)
    - UTC timestamps with timezone awareness
    - Composite primary key (symbol, timeframe, timestamp) for uniqueness
    - Individual indexes on symbol, timestamp for common query patterns

    Example:
        bar = MarketData(
            symbol='AAPL',
            timeframe=Timeframe.ONE_DAY,
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            open=Decimal('150.50'),
            high=Decimal('152.00'),
            low=Decimal('149.75'),
            close=Decimal('151.25'),
            volume=Decimal('75000000.0')
        )

    Indexes:
        - Primary: (symbol, timeframe, timestamp)
        - symbol for filtering by ticker
        - timestamp for time-based queries
        - Combined (symbol, timestamp) for typical range queries
    """

    __tablename__ = 'market_data'

    # Primary key components
    symbol = Column(String(10), primary_key=True)
    timeframe = Column(Enum(Timeframe), primary_key=True)
    timestamp = Column(DateTime(timezone=True), primary_key=True)

    # OHLCV data
    open = Column(DECIMAL(20, 8), nullable=False)
    high = Column(DECIMAL(20, 8), nullable=False)
    low = Column(DECIMAL(20, 8), nullable=False)
    close = Column(DECIMAL(20, 8), nullable=False)
    volume = Column(DECIMAL(20, 4), nullable=False)

    # Data quality tracking
    is_valid = Column(Boolean, default=True)  # Flag for invalid/suspect data

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    source = Column(String(50))  # Data source identifier (e.g., 'schwab', 'yahoo')

    # Indexes for common query patterns
    __table_args__ = (
        Index('idx_symbol', 'symbol'),
        Index('idx_timestamp', 'timestamp'),
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
    )

    def __repr__(self):
        return f"<MarketData(symbol={self.symbol}, timeframe={self.timeframe}, timestamp={self.timestamp}, close={self.close})>"


class DataSourceType(str, enum.Enum):
    """
    Supported data source types.

    Each source may have different data formats, rate limits, and availability.

    Values:
        schwab: Schwab API data
        yahoo: Yahoo Finance data
        csv: CSV file import
        polygon: Polygon.io API (future)
        alpaca: Alpaca API (future)
    """
    SCHWAB = 'schwab'
    YAHOO = 'yahoo'
    CSV = 'csv'
    POLYGON = 'polygon'
    ALPACA = 'alpaca'


class DataSyncStatus(str, enum.Enum):
    """
    Data synchronization status for tracking progress.

    Tracks whether data for a symbol/timeframe is up-to-date or needs refresh.

    Values:
        pending: Not yet synced
        syncing: Currently in progress
        complete: Successfully synced
        error: Failed to sync
    """
    PENDING = 'pending'
    SYNCING = 'syncing'
    COMPLETE = 'complete'
    ERROR = 'error'


class DataMetadata(Base):
    """
    Metadata about market data availability and synchronization.

    Tracks the date range and quality of data for each symbol/timeframe combination.
    Used to determine what data is available and what needs to be fetched.

    Design decisions:
    - Separate table for metadata vs actual data (denormalized for performance)
    - Track first/last available date for each symbol/timeframe
    - Store error information for debugging sync failures
    - Use updated_at to know when data was last refreshed

    Example:
        metadata = DataMetadata(
            symbol='AAPL',
            timeframe=Timeframe.ONE_DAY,
            source=DataSourceType.SCHWAB,
            first_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            last_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            bar_count=1000,
            sync_status=DataSyncStatus.COMPLETE
        )

    Indexes:
        - Primary: (symbol, timeframe, source)
        - symbol for filtering
        - sync_status for finding data needing refresh
    """

    __tablename__ = 'data_metadata'

    # Composite primary key: one row per symbol/timeframe/source
    symbol = Column(String(10), primary_key=True)
    timeframe = Column(Enum(Timeframe), primary_key=True)
    source = Column(Enum(DataSourceType), primary_key=True)

    # Data availability window
    first_date = Column(DateTime(timezone=True))  # Earliest available bar
    last_date = Column(DateTime(timezone=True))   # Most recent available bar
    bar_count = Column(Integer, default=0)        # Total bars available

    # Synchronization tracking
    sync_status = Column(Enum(DataSyncStatus), default=DataSyncStatus.PENDING)
    last_sync_attempt = Column(DateTime(timezone=True))  # When we last tried to sync
    last_sync_success = Column(DateTime(timezone=True))  # When we last succeeded
    sync_error = Column(String(500))  # Error message if sync failed

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index('idx_metadata_symbol', 'symbol'),
        Index('idx_metadata_sync_status', 'sync_status'),
    )

    def __repr__(self):
        return (f"<DataMetadata(symbol={self.symbol}, timeframe={self.timeframe}, "
                f"source={self.source}, bars={self.bar_count}, status={self.sync_status})>")


class BacktestRun(Base):
    """
    Record of a completed backtest run.

    Stores the configuration and results of each backtest execution.
    Allows viewing historical backtests and comparing strategy performance.

    Design decisions:
    - Store strategy parameters as JSON for flexibility
    - Link to strategy class name for reproducibility
    - Track both execution time and data range tested
    - Store summary metrics for quick comparison

    Example:
        run = BacktestRun(
            strategy_name='SimpleSMA',
            symbol='AAPL',
            timeframe=Timeframe.ONE_DAY,
            start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            initial_capital=Decimal('10000.00'),
            final_value=Decimal('12500.00'),
            total_return=Decimal('0.25'),
            sharpe_ratio=Decimal('1.85')
        )

    Indexes:
        - Primary: id (auto-incrementing)
        - strategy_name for filtering by strategy
        - created_at for chronological sorting
    """

    __tablename__ = 'backtest_runs'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Strategy identification
    strategy_name = Column(String(100), nullable=False, index=True)
    strategy_params = Column(String(1000))  # JSON string of strategy parameters

    # Backtest configuration
    symbol = Column(String(10), nullable=False)
    timeframe = Column(Enum(Timeframe), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)

    # Portfolio configuration
    initial_capital = Column(DECIMAL(20, 2), nullable=False)
    position_size = Column(DECIMAL(5, 4))  # Position sizing (e.g., 0.1 = 10% per trade)

    # Results summary
    final_value = Column(DECIMAL(20, 2))
    total_return = Column(DECIMAL(10, 4))  # e.g., 0.25 = 25% return
    sharpe_ratio = Column(DECIMAL(10, 4))
    max_drawdown = Column(DECIMAL(10, 4))  # e.g., -0.15 = -15% max drawdown
    total_trades = Column(Integer)
    winning_trades = Column(Integer)

    # Execution metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    duration_seconds = Column(Integer)  # How long the backtest took to run

    def __repr__(self):
        return f"<BacktestRun(id={self.id}, strategy={self.strategy_name}, symbol={self.symbol}, return={self.total_return})>"


# ==============================================================================
# AUTHENTICATION MODELS
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
    is_admin = Column(Boolean, default=True)  # Admin flag (all users admin for now)

    # Account lockout (brute force protection)
    failed_login_count = Column(Integer, default=0)  # Consecutive failed login attempts
    locked_until = Column(DateTime(timezone=True), nullable=True)  # Lockout expiration timestamp

    # Session tracking
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Two-Factor Authentication (2FA/TOTP)
    totp_secret = Column(String(32), nullable=True)  # Base32 secret for TOTP
    totp_enabled = Column(Boolean, default=False)    # Whether 2FA is active
    backup_codes = Column(ARRAY(String), nullable=True)  # Array of one-time backup codes

    def __repr__(self):
        return f"<User(username={self.username}, active={self.is_active})>"


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
