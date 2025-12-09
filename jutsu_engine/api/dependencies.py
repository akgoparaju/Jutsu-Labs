"""
FastAPI dependencies for database sessions, authentication, and shared resources.

Supports:
- SQLite (local) and PostgreSQL (server) databases via DATABASE_TYPE
- JWT authentication for dashboard access
- HTTP Basic authentication (legacy, optional)
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Generator, Optional
from pathlib import Path
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials, OAuth2PasswordBearer
import secrets

# JWT and password hashing imports
try:
    from jose import JWTError, jwt
    import bcrypt  # Using bcrypt directly instead of passlib (bcrypt 5.0+ compatibility)
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

from jutsu_engine.utils.config import (
    get_database_url,
    get_database_type,
    get_safe_database_url_for_logging,
    is_sqlite,
    is_postgresql,
    DATABASE_TYPE_SQLITE,
    DATABASE_TYPE_POSTGRES,
)

logger = logging.getLogger('API.DEPS')

# ==============================================================================
# DATABASE CONFIGURATION
# ==============================================================================

def _ensure_database_exists(db_url: str) -> None:
    """
    Ensure the database file and directory exist (SQLite only).
    Creates empty database with schema if it doesn't exist.
    PostgreSQL databases should be created externally.
    """
    if not db_url.startswith('sqlite'):
        # PostgreSQL: Log connection info but don't try to create
        logger.info(f"Using PostgreSQL database")
        return

    # Parse SQLite path (sqlite:/// or sqlite:////)
    if db_url.startswith('sqlite:////'):
        # Absolute path
        db_path = Path(db_url.replace('sqlite:////', '/'))
    else:
        # Relative path
        db_path = Path(db_url.replace('sqlite:///', ''))

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # If database doesn't exist, create it with schema
    if not db_path.exists():
        logger.info(f"Database not found at {db_path}, creating...")
        try:
            # Import models to ensure they're registered with Base
            from jutsu_engine.data.models import Base, MarketData, DataMetadata

            # Create temporary engine just for schema creation
            temp_engine = create_engine(
                db_url,
                connect_args={'check_same_thread': False},
                echo=False
            )
            Base.metadata.create_all(temp_engine)
            temp_engine.dispose()
            logger.info(f"Database created successfully at {db_path}")
        except Exception as e:
            logger.warning(f"Could not create database: {e}")


def _create_engine(db_url: str):
    """
    Create SQLAlchemy engine with appropriate settings for database type.

    Args:
        db_url: Database connection URL

    Returns:
        SQLAlchemy engine instance
    """
    if db_url.startswith('sqlite'):
        # SQLite: Need check_same_thread=False for FastAPI async
        return create_engine(
            db_url,
            connect_args={'check_same_thread': False},
            echo=False,
            pool_pre_ping=True,
        )
    else:
        # PostgreSQL: Connection pooling settings
        return create_engine(
            db_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,  # Recycle connections after 1 hour
        )


# Get database URL from centralized config (handles SQLite/PostgreSQL, Docker/local)
DATABASE_URL = get_database_url()
DATABASE_TYPE = get_database_type()

logger.info(f"Database type: {DATABASE_TYPE}")
logger.info(f"Database URL: {get_safe_database_url_for_logging(DATABASE_URL)}")

# Ensure database exists before creating engine (SQLite only)
_ensure_database_exists(DATABASE_URL)

# Create engine with appropriate settings for database type
engine = _create_engine(DATABASE_URL)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency.

    Yields a database session and ensures it's closed after use.
    Usage:
        @app.get("/endpoint")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database sessions (non-FastAPI use).

    Usage:
        with get_db_context() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# AUTHENTICATION
# ==============================================================================

# HTTP Basic auth (legacy, for backward compatibility)
security = HTTPBasic(auto_error=False)

# OAuth2 bearer token for JWT
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# API credentials from environment (HTTP Basic - legacy)
API_USERNAME = os.getenv('JUTSU_API_USERNAME', '')
API_PASSWORD = os.getenv('JUTSU_API_PASSWORD', '')

# JWT configuration
SECRET_KEY = os.getenv('SECRET_KEY', 'default-dev-secret-change-in-production')
ALGORITHM = "HS256"

# Token expiration - configurable via environment variables
# Access tokens: short-lived (15 minutes default) for security
# Refresh tokens: longer-lived (7 days default) for session persistence
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '15'))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', '7'))

# Legacy compatibility - used when refresh tokens not enabled
ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv('ACCESS_TOKEN_EXPIRE_DAYS', '7'))

# Password hashing using bcrypt directly (bcrypt 5.0+ compatible)
# Note: passlib 1.7.4 is incompatible with bcrypt 5.0+ due to __about__ attribute removal


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash using bcrypt directly."""
    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not available. Install: pip install python-jose[cryptography] bcrypt"
        )
    try:
        # Handle both bytes and string hash formats
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Hash a password for storage using bcrypt directly."""
    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not available. Install: pip install python-jose[cryptography] bcrypt"
        )
    # Generate salt and hash the password
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')  # Return as string for database storage


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    use_short_expiry: bool = True
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Token payload (e.g., {"sub": username})
        expires_delta: Custom token expiry time
        use_short_expiry: If True (default), use short ACCESS_TOKEN_EXPIRE_MINUTES.
                         If False, use legacy ACCESS_TOKEN_EXPIRE_DAYS.

    Returns:
        Encoded JWT token string
    """
    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT not available. Install: pip install python-jose[cryptography]"
        )

    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    elif use_short_expiry:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT refresh token with longer expiration.

    Refresh tokens are used to obtain new access tokens without re-authentication.
    They have longer expiration (default: REFRESH_TOKEN_EXPIRE_DAYS).

    Args:
        data: Token payload (e.g., {"sub": username})
        expires_delta: Custom expiry (default: REFRESH_TOKEN_EXPIRE_DAYS)

    Returns:
        Encoded JWT refresh token string
    """
    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT not available. Install: pip install python-jose[cryptography]"
        )

    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT access token.

    Args:
        token: JWT token string

    Returns:
        Token payload if valid, None if invalid/expired
    """
    if not JWT_AVAILABLE:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_user_from_token(db: Session, token: str) -> Optional["User"]:
    """
    Get user from JWT token.

    Args:
        db: Database session
        token: JWT token string

    Returns:
        User object if token valid and user exists, None otherwise
    """
    from jutsu_engine.data.models import User

    payload = decode_access_token(token)
    if payload is None:
        return None

    username: str = payload.get("sub")
    if username is None:
        return None

    user = db.query(User).filter(User.username == username).first()
    return user


async def get_current_user(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme)
) -> Optional["User"]:
    """
    FastAPI dependency to get current authenticated user.

    If AUTH_REQUIRED=false (default for local), returns None without error.
    If AUTH_REQUIRED=true, requires valid JWT token.

    Args:
        db: Database session
        token: JWT token from Authorization header

    Returns:
        User object if authenticated, None if auth disabled

    Raises:
        HTTPException: If auth required but token invalid
    """
    auth_required = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'

    if not auth_required:
        return None  # Auth disabled, allow access

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_from_token(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account disabled",
        )

    return user


async def require_auth(
    user: Optional["User"] = Depends(get_current_user)
) -> Optional["User"]:
    """
    Dependency that requires authentication when AUTH_REQUIRED=true.

    Use this for protected endpoints that should only be accessible
    when authentication is enabled and user is logged in.

    For local development (AUTH_REQUIRED=false), allows access without login.
    """
    return user


def verify_credentials(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
    """
    Verify HTTP Basic credentials (legacy - for backward compatibility).

    If JUTSU_API_USERNAME and JUTSU_API_PASSWORD are not set,
    authentication is disabled (returns True).
    """
    # If no credentials configured, allow access
    if not API_USERNAME or not API_PASSWORD:
        return True

    # If credentials configured but not provided, deny
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify credentials (constant-time comparison)
    username_ok = secrets.compare_digest(credentials.username, API_USERNAME)
    password_ok = secrets.compare_digest(credentials.password, API_PASSWORD)

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return True


def create_default_user(db: Session, username: str = "admin", password: str = None) -> "User":
    """
    Create the default admin user if it doesn't exist.

    Args:
        db: Database session
        username: Admin username (default: "admin")
        password: Admin password (default: from ADMIN_PASSWORD env or "admin")

    Returns:
        User object (existing or newly created)
    """
    from jutsu_engine.data.models import User

    # Check if user exists
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return existing

    # Get password from environment or use default
    if password is None:
        password = os.getenv('ADMIN_PASSWORD', 'admin')

    # Create user
    user = User(
        username=username,
        password_hash=get_password_hash(password),
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Created default admin user: {username}")
    return user


def ensure_admin_user_exists():
    """
    Ensure the admin user exists in the database.
    Called during application startup when AUTH_REQUIRED=true.
    """
    auth_required = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'
    if not auth_required:
        return

    if not JWT_AVAILABLE:
        logger.warning("JWT authentication not available. Install: pip install python-jose[cryptography] bcrypt")
        return

    try:
        with get_db_context() as db:
            create_default_user(db)
    except Exception as e:
        logger.error(f"Failed to create admin user: {e}")


# ==============================================================================
# SHARED STATE (Trading Engine State)
# ==============================================================================

class EngineState:
    """
    Shared state for the trading engine.

    Singleton that tracks engine status, mode, and timing.
    Used by control endpoints to manage engine lifecycle.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.is_running: bool = False
        self.mode: str = 'offline_mock'
        self.last_execution: Optional[str] = None
        self.next_execution: Optional[str] = None
        self.start_time: Optional[str] = None
        self.error: Optional[str] = None
        self._initialized = True

    def start(self, mode: str = 'offline_mock') -> bool:
        """Start the trading engine."""
        if self.is_running:
            return False

        from datetime import datetime, timezone
        self.is_running = True
        self.mode = mode
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.error = None
        logger.info(f"Engine started in {mode} mode")
        return True

    def stop(self) -> bool:
        """Stop the trading engine."""
        if not self.is_running:
            return False

        self.is_running = False
        self.start_time = None
        self.next_execution = None
        logger.info("Engine stopped")
        return True

    def record_execution(self, timestamp: str):
        """Record an execution timestamp."""
        self.last_execution = timestamp

    def schedule_next(self, timestamp: str):
        """Set next scheduled execution."""
        self.next_execution = timestamp

    def set_error(self, error: str):
        """Record an error."""
        self.error = error
        logger.error(f"Engine error: {error}")

    def get_uptime_seconds(self) -> Optional[float]:
        """Get engine uptime in seconds."""
        if not self.start_time:
            return None

        from datetime import datetime, timezone
        start = datetime.fromisoformat(self.start_time.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (now - start).total_seconds()


def get_engine_state() -> EngineState:
    """Get the singleton engine state."""
    return EngineState()


# ==============================================================================
# CONFIG LOADER
# ==============================================================================

_config_cache: Optional[dict] = None
_config_path: Optional[Path] = None


def get_config_path() -> Path:
    """Get the path to the live trading config."""
    global _config_path
    if _config_path is None:
        _config_path = Path(os.getenv(
            'JUTSU_CONFIG_PATH',
            'config/live_trading_config.yaml'
        ))
    return _config_path


def load_config(force_reload: bool = False) -> dict:
    """
    Load the live trading configuration.

    Caches the config and only reloads when force_reload=True.

    Checks primary config path first, then falls back to Docker default config
    location (/app/config.default/) for cases where mounted volume is empty.
    """
    global _config_cache

    if _config_cache is not None and not force_reload:
        return _config_cache

    import yaml
    config_path = get_config_path()

    # Fallback path for Docker deployments where mounted config dir may be empty
    # The Dockerfile copies default config to /app/config.default/
    default_config_path = Path('/app/config.default/live_trading_config.yaml')

    logger.info(f"Loading config - primary path: {config_path}, exists: {config_path.exists()}")
    logger.info(f"Fallback path: {default_config_path}, exists: {default_config_path.exists()}")

    if not config_path.exists():
        # Check fallback path (Docker default config)
        if default_config_path.exists():
            logger.info(f"Primary config not found at {config_path}, using default: {default_config_path}")
            config_path = default_config_path
        else:
            logger.warning(f"Config file not found: {config_path} (no fallback available)")
            return {}

    try:
        with open(config_path, 'r') as f:
            _config_cache = yaml.safe_load(f)

        # Log strategy name for diagnostic purposes
        strategy_config = _config_cache.get('strategy', {}) if _config_cache else {}
        strategy_name = strategy_config.get('name', 'NOT_FOUND')
        logger.info(f"Config loaded from {config_path}, strategy.name: {strategy_name}")

        return _config_cache
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        return {}


def get_config() -> dict:
    """FastAPI dependency for configuration."""
    return load_config()


# ==============================================================================
# STRATEGY RUNNER (Lazy Loading with Warmup)
# ==============================================================================

_strategy_runner = None
_strategy_warmed_up = False

# Number of trading days of historical data to use for warmup
WARMUP_DAYS = 300


def _warmup_strategy(runner) -> bool:
    """
    Warmup strategy with historical market data.

    Loads historical bars from the database and feeds them through
    the strategy's on_bar() method to initialize all indicators
    (t_norm, z_score, cell_id, trend_state, etc.).

    Args:
        runner: LiveStrategyRunner instance to warmup

    Returns:
        True if warmup successful, False otherwise
    """
    from jutsu_engine.data.models import MarketData

    try:
        # Get symbols from config
        signal_symbol = runner.get_signal_symbol()
        treasury_symbol = runner.get_treasury_symbol()

        logger.info(f"Warming up strategy with {WARMUP_DAYS} days of data")
        logger.info(f"  Signal symbol: {signal_symbol}")
        logger.info(f"  Treasury symbol: {treasury_symbol}")

        # Calculate date range for warmup
        end_date = datetime.now()
        # Use 1.5x calendar days to account for weekends/holidays
        start_date = end_date - timedelta(days=int(WARMUP_DAYS * 1.5))

        # Load data from database
        with get_db_context() as db:
            market_data = {}

            for symbol in [signal_symbol, treasury_symbol]:
                query = db.query(MarketData).filter(
                    and_(
                        MarketData.symbol == symbol,
                        MarketData.timeframe == '1D',
                        MarketData.timestamp >= start_date,
                        MarketData.timestamp <= end_date,
                        MarketData.is_valid == True,  # noqa: E712
                    )
                ).order_by(MarketData.timestamp.asc())

                rows = query.all()

                if not rows:
                    logger.warning(f"No data found for {symbol}")
                    continue

                # Convert to DataFrame
                data = []
                for row in rows:
                    data.append({
                        'date': row.timestamp,
                        'open': float(row.open),
                        'high': float(row.high),
                        'low': float(row.low),
                        'close': float(row.close),
                        'volume': row.volume,
                    })

                df = pd.DataFrame(data)
                market_data[symbol] = df
                logger.info(f"  Loaded {len(df)} bars for {symbol}")

            if signal_symbol not in market_data:
                logger.error(f"Cannot warmup: missing {signal_symbol} data")
                return False

            if treasury_symbol not in market_data:
                logger.warning(f"Missing {treasury_symbol} data, warmup may be incomplete")
                # Create empty dataframe to avoid calculate_signals error
                market_data[treasury_symbol] = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])

            # Feed data through strategy
            signals = runner.calculate_signals(market_data)

            logger.info("Strategy warmup complete:")
            logger.info(f"  Cell ID: {signals.get('current_cell')}")
            logger.info(f"  Trend State: {signals.get('trend_state')}")
            logger.info(f"  Vol State: {signals.get('vol_state')}")
            logger.info(f"  T-Norm: {signals.get('t_norm')}")
            logger.info(f"  Z-Score: {signals.get('z_score')}")

            return True

    except Exception as e:
        logger.error(f"Strategy warmup failed: {e}", exc_info=True)
        return False


def get_strategy_runner():
    """
    Get the LiveStrategyRunner instance.

    Lazy-loads and caches the strategy runner.
    Automatically warms up the strategy with historical data on first call.
    """
    global _strategy_runner, _strategy_warmed_up

    if _strategy_runner is None:
        try:
            from jutsu_engine.live.strategy_runner import LiveStrategyRunner
            config_path = get_config_path()
            _strategy_runner = LiveStrategyRunner(config_path=config_path)
            logger.info(f"Strategy runner initialized: {_strategy_runner.strategy.name}")
            _strategy_warmed_up = False
        except Exception as e:
            logger.error(f"Failed to initialize strategy runner: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Strategy runner not available: {str(e)}"
            )

    # Warmup strategy with historical data on first access
    if not _strategy_warmed_up:
        if _warmup_strategy(_strategy_runner):
            _strategy_warmed_up = True
            logger.info("Strategy runner warmed up successfully")
        else:
            logger.warning("Strategy warmup incomplete - indicators may show N/A")

    return _strategy_runner


def reset_strategy_runner():
    """Reset the strategy runner (for config reloads)."""
    global _strategy_runner, _config_cache, _strategy_warmed_up
    _strategy_runner = None
    _config_cache = None
    _strategy_warmed_up = False
    logger.info("Strategy runner reset")
