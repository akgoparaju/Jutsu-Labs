"""
FastAPI dependencies for database sessions, authentication, and shared resources.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Generator, Optional
from pathlib import Path
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

logger = logging.getLogger('API.DEPS')

# ==============================================================================
# DATABASE CONFIGURATION
# ==============================================================================

def _normalize_sqlite_url(db_url: str) -> str:
    """
    Normalize SQLite URL to use correct slash format.

    sqlite:///app/... should be sqlite:////app/... (4 slashes for absolute)
    """
    import re
    if re.match(r'^sqlite:///app/', db_url):
        normalized = db_url.replace('sqlite:///app/', 'sqlite:////app/', 1)
        logger.info(f"Normalized database URL: {db_url} -> {normalized}")
        return normalized
    return db_url


def _get_database_url() -> str:
    """
    Get database URL with proper absolute path handling.

    SQLite URL format: sqlite:///relative/path OR sqlite:////absolute/path
    (Note: 4 slashes for absolute paths on Unix)
    """
    db_url = os.getenv('DATABASE_URL')

    if db_url:
        # Normalize 3-slash paths to 4-slash for absolute /app paths
        return _normalize_sqlite_url(db_url)

    # Default: Check if running in Docker (/app exists) or local
    if Path('/app/data').exists():
        # Docker environment - use absolute path
        return 'sqlite:////app/data/market_data.db'
    else:
        # Local development - use relative path from project root
        return 'sqlite:///data/market_data.db'


def _ensure_database_exists(db_url: str) -> None:
    """
    Ensure the database file and directory exist.
    Creates empty database with schema if it doesn't exist.
    """
    if not db_url.startswith('sqlite'):
        return  # Only handle SQLite

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


# Get database URL (handles Docker vs local automatically)
DATABASE_URL = _get_database_url()

# Ensure database exists before creating engine
_ensure_database_exists(DATABASE_URL)

# Create engine with appropriate settings
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(
        DATABASE_URL,
        connect_args={'check_same_thread': False},  # SQLite specific
        echo=False
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)

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
# AUTHENTICATION (Optional - for production)
# ==============================================================================

security = HTTPBasic(auto_error=False)

# API credentials from environment
API_USERNAME = os.getenv('JUTSU_API_USERNAME', '')
API_PASSWORD = os.getenv('JUTSU_API_PASSWORD', '')


def verify_credentials(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
    """
    Verify HTTP Basic credentials.

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
    """
    global _config_cache

    if _config_cache is not None and not force_reload:
        return _config_cache

    import yaml
    config_path = get_config_path()

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}")
        return {}

    with open(config_path, 'r') as f:
        _config_cache = yaml.safe_load(f)

    logger.info(f"Config loaded from {config_path}")
    return _config_cache


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
