"""
Configuration management for the Jutsu Labs backtesting engine.

Loads configuration from environment variables and YAML files.
Supports both SQLite (local) and PostgreSQL (server) databases.
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from decimal import Decimal
from urllib.parse import quote_plus
import yaml
from dotenv import load_dotenv


# Load .env file at module level so all functions have access to environment variables
# This ensures get_database_type(), is_postgresql(), etc. work correctly when imported
load_dotenv()


# Database type constants
DATABASE_TYPE_SQLITE = "sqlite"
DATABASE_TYPE_POSTGRES = "postgresql"


class Config:
    """
    Application configuration manager.

    Loads settings from:
    1. .env file (environment variables)
    2. config/config.yaml (application config)
    3. Environment variables (override everything)

    Example:
        config = Config()
        api_key = config.get('SCHWAB_API_KEY')
        db_url = config.database_url
        initial_capital = config.get_decimal('INITIAL_CAPITAL', default=Decimal('100000'))
    """

    def __init__(self, env_file: str = '.env', config_file: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            env_file: Path to .env file
            config_file: Path to config YAML file (defaults to config/config.yaml)
        """
        # Load .env file
        load_dotenv(env_file)

        # Load YAML config
        if config_file is None:
            config_file = 'config/config.yaml'

        self._config = self._load_yaml(config_file)

    def _load_yaml(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        config_path = Path(config_file)

        if not config_path.exists():
            # Try .example version
            example_path = Path(f"{config_file}.example")
            if example_path.exists():
                print(
                    f"Warning: {config_file} not found, using {config_file}.example. "
                    f"Please copy to {config_file} and customize."
                )
                config_path = example_path
            else:
                print(f"Warning: No config file found at {config_file}, using defaults")
                return {}

        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Checks in order:
        1. Environment variable
        2. YAML config
        3. Default value

        Args:
            key: Configuration key
            default: Default value if not found

        Returns:
            Configuration value

        Example:
            api_key = config.get('SCHWAB_API_KEY')
            log_level = config.get('LOG_LEVEL', 'INFO')
        """
        # Check environment variable first (takes precedence)
        env_value = os.getenv(key)
        if env_value is not None:
            return env_value

        # Check YAML config (nested keys with dot notation)
        value = self._config
        for part in key.split('.'):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default

        return value if value is not self._config else default

    def get_decimal(self, key: str, default: Decimal = Decimal('0')) -> Decimal:
        """
        Get configuration value as Decimal.

        Args:
            key: Configuration key
            default: Default Decimal value

        Returns:
            Configuration value as Decimal

        Example:
            commission = config.get_decimal('DEFAULT_COMMISSION', Decimal('0.01'))
        """
        value = self.get(key)
        if value is None:
            return default
        return Decimal(str(value))

    def get_int(self, key: str, default: int = 0) -> int:
        """Get configuration value as integer."""
        value = self.get(key)
        if value is None:
            return default
        return int(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get configuration value as boolean."""
        value = self.get(key)
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        # Handle string values
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')

        return bool(value)

    # Convenience properties for common config values

    @property
    def database_url(self) -> str:
        """
        Get database URL with Docker/local auto-detection.

        Handles SQLite URL formats:
        - sqlite:///relative/path (3 slashes = relative path)
        - sqlite:////absolute/path (4 slashes = absolute path)

        In Docker, paths like /app/data/ require 4 slashes.
        """
        return get_database_url()

    @property
    def schwab_api_key(self) -> Optional[str]:
        """Get Schwab API key."""
        return self.get('SCHWAB_API_KEY')

    @property
    def schwab_api_secret(self) -> Optional[str]:
        """Get Schwab API secret."""
        return self.get('SCHWAB_API_SECRET')

    @property
    def log_level(self) -> str:
        """Get log level."""
        return self.get('LOG_LEVEL', 'INFO')

    @property
    def initial_capital(self) -> Decimal:
        """Get initial capital for backtesting."""
        return self.get_decimal(
            'INITIAL_CAPITAL', default=self.get_decimal('backtesting.defaults.initial_capital', Decimal('100000'))
        )

    @property
    def commission_per_share(self) -> Decimal:
        """Get commission per share."""
        return self.get_decimal(
            'DEFAULT_COMMISSION',
            default=self.get_decimal('backtesting.defaults.commission_per_share', Decimal('0.01')),
        )

    @property
    def environment(self) -> str:
        """Get environment (development, staging, production)."""
        return self.get('ENV', 'development')

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == 'development'

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == 'production'


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get global configuration instance.

    Creates singleton Config instance on first call.

    Returns:
        Config instance

    Example:
        from jutsu_engine.utils.config import get_config

        config = get_config()
        api_key = config.schwab_api_key
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def get_database_type() -> str:
    """
    Get the configured database type.

    Returns:
        Database type: 'sqlite' or 'postgresql'

    Example:
        from jutsu_engine.utils.config import get_database_type

        db_type = get_database_type()
        # 'sqlite' (default) or 'postgresql'
    """
    return os.getenv('DATABASE_TYPE', DATABASE_TYPE_SQLITE).lower()


def get_postgresql_url() -> str:
    """
    Build PostgreSQL connection URL from environment variables.

    Required environment variables:
    - POSTGRES_HOST: Database host (default: localhost)
    - POSTGRES_PORT: Database port (default: 5432)
    - POSTGRES_USER: Database user (default: jutsu)
    - POSTGRES_PASSWORD: Database password (required)
    - POSTGRES_DATABASE: Database name (default: jutsu_labs)

    Note: Password and username are URL-encoded to handle special characters
    like @, #, %, etc. safely in the connection URL.

    Returns:
        PostgreSQL connection URL string

    Raises:
        ValueError: If POSTGRES_PASSWORD is not set

    Example:
        from jutsu_engine.utils.config import get_postgresql_url

        db_url = get_postgresql_url()
        # 'postgresql://jutsu:password@localhost:5432/jutsu_labs'
    """
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    user = os.getenv('POSTGRES_USER', 'jutsu')
    password = os.getenv('POSTGRES_PASSWORD')
    database = os.getenv('POSTGRES_DATABASE', 'jutsu_labs')

    if not password:
        raise ValueError(
            "POSTGRES_PASSWORD environment variable is required when DATABASE_TYPE=postgresql. "
            "Please set it in your .env file or environment."
        )

    # URL-encode user and password to handle special characters (@, #, %, etc.)
    encoded_user = quote_plus(user)
    encoded_password = quote_plus(password)

    return f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"


def get_sqlite_url() -> str:
    """
    Get SQLite database URL with proper Docker/local path detection.

    SQLite URL format:
    - sqlite:///relative/path (3 slashes = relative path from cwd)
    - sqlite:////absolute/path (4 slashes = absolute path, e.g., /app/data/)

    Logic:
    1. Read DATABASE_URL environment variable (if set and is SQLite)
    2. Normalize 3-slash to 4-slash for /app/ paths (Docker)
    3. If no env var, auto-detect Docker (/app/data exists) vs local

    Returns:
        SQLite database URL string

    Example:
        from jutsu_engine.utils.config import get_sqlite_url

        db_url = get_sqlite_url()
        # Docker: 'sqlite:////app/data/market_data.db'
        # Local:  'sqlite:///data/market_data.db'
    """
    db_url = os.getenv('DATABASE_URL')

    if db_url and db_url.startswith('sqlite'):
        # Normalize 3-slash paths to 4-slash for absolute /app paths
        # sqlite:///app/... should be sqlite:////app/... (4 slashes for absolute)
        if re.match(r'^sqlite:///app/', db_url):
            return db_url.replace('sqlite:///app/', 'sqlite:////app/', 1)
        return db_url

    # Default: Check if running in Docker (/app exists) or local
    if Path('/app/data').exists():
        # Docker environment - use absolute path (4 slashes)
        return 'sqlite:////app/data/market_data.db'
    else:
        # Local development - use relative path (3 slashes)
        return 'sqlite:///data/market_data.db'


def get_database_url() -> str:
    """
    Get database URL based on DATABASE_TYPE configuration.

    This is the centralized utility for database URL resolution.
    All modules should use this function instead of hardcoding paths.

    Supports:
    - SQLite (DATABASE_TYPE=sqlite, default): Local file-based database
    - PostgreSQL (DATABASE_TYPE=postgresql): Server-based database

    Returns:
        Database connection URL string

    Example:
        from jutsu_engine.utils.config import get_database_url

        db_url = get_database_url()
        # SQLite:     'sqlite:///data/market_data.db'
        # PostgreSQL: 'postgresql://jutsu:password@localhost:5432/jutsu_labs'
    """
    db_type = get_database_type()

    if db_type == DATABASE_TYPE_POSTGRES:
        return get_postgresql_url()
    else:
        return get_sqlite_url()


def get_database_path() -> Optional[str]:
    """
    Get database file path (without sqlite:// prefix).

    Note: Only applicable for SQLite databases. Returns None for PostgreSQL.

    Returns:
        Database file path string for SQLite, None for PostgreSQL

    Example:
        path = get_database_path()
        # SQLite Docker: '/app/data/market_data.db'
        # SQLite Local:  'data/market_data.db'
        # PostgreSQL:    None
    """
    db_type = get_database_type()

    if db_type == DATABASE_TYPE_POSTGRES:
        return None

    db_url = get_sqlite_url()

    if db_url.startswith('sqlite:////'):
        # Absolute path (4 slashes)
        return db_url.replace('sqlite:////', '/')
    elif db_url.startswith('sqlite:///'):
        # Relative path (3 slashes)
        return db_url.replace('sqlite:///', '')
    else:
        # Unexpected format
        return db_url


def is_postgresql() -> bool:
    """
    Check if using PostgreSQL database.

    Returns:
        True if DATABASE_TYPE is postgresql, False otherwise

    Example:
        from jutsu_engine.utils.config import is_postgresql

        if is_postgresql():
            # PostgreSQL-specific logic
            pass
    """
    return get_database_type() == DATABASE_TYPE_POSTGRES


def is_sqlite() -> bool:
    """
    Check if using SQLite database.

    Returns:
        True if DATABASE_TYPE is sqlite (or unset), False otherwise

    Example:
        from jutsu_engine.utils.config import is_sqlite

        if is_sqlite():
            # SQLite-specific logic
            pass
    """
    return get_database_type() == DATABASE_TYPE_SQLITE


def reload_config():
    """Reload configuration (useful for testing)."""
    global _config
    _config = Config()
