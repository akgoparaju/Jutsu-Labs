"""
Configuration management for the Jutsu Labs backtesting engine.

Loads configuration from environment variables and YAML files.
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional
from decimal import Decimal
import yaml
from dotenv import load_dotenv


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
        """Get database URL."""
        return self.get('DATABASE_URL', 'sqlite:///data/market_data.db')

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


def reload_config():
    """Reload configuration (useful for testing)."""
    global _config
    _config = Config()
