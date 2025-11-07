"""API configuration management.

Centralizes all configuration settings for the REST API.
Uses pydantic-settings for environment variable management.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os


class Settings(BaseSettings):
    """API configuration settings.

    All settings can be overridden via environment variables.
    See .env.example for available options.
    """

    # App settings
    environment: str = Field(default="development", env="ENV")
    debug: bool = Field(default=True, env="DEBUG")

    # Security
    secret_key: str = Field(default="dev-secret-key-change-in-production", env="SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        env="CORS_ORIGINS"
    )

    # Rate limiting
    rate_limit_rpm: int = Field(default=60, env="RATE_LIMIT_RPM")

    # Database
    database_url: str = Field(
        default="sqlite:///data/market_data.db",
        env="DATABASE_URL"
    )

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env (for project-wide config)


# Singleton settings instance
_settings: Settings = None


def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance (singleton)

    Example:
        settings = get_settings()
        print(settings.database_url)
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
