"""
Alembic environment configuration for Jutsu Labs.

Handles database connections and migration execution for both
SQLite (development) and PostgreSQL (production).
"""
from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Import database models for autogenerate support
from jutsu_engine.data.models import Base
from jutsu_engine.data.database_factory import DatabaseFactory

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for autogenerate support
target_metadata = Base.metadata


def get_url_from_env():
    """
    Get database URL from environment variables.

    Supports both SQLite and PostgreSQL based on DATABASE_TYPE env var.

    Returns:
        Database connection string
    """
    db_type = os.getenv('DATABASE_TYPE', 'sqlite')

    if db_type == 'sqlite':
        # SQLite for development
        db_path = os.getenv('SQLITE_DATABASE', 'data/market_data.db')
        return f'sqlite:///{db_path}'

    elif db_type == 'postgresql':
        # PostgreSQL for production
        user = os.getenv('POSTGRES_USER', 'jutsu')
        password = os.getenv('POSTGRES_PASSWORD', '')
        host = os.getenv('POSTGRES_HOST', 'localhost')
        port = os.getenv('POSTGRES_PORT', '5432')
        database = os.getenv('POSTGRES_DATABASE', 'jutsu_labs')

        return f'postgresql://{user}:{password}@{host}:{port}/{database}'

    else:
        raise ValueError(f"Unsupported DATABASE_TYPE: {db_type}")


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url_from_env()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a
    connection with the context.
    """
    # Get configuration from environment
    url = get_url_from_env()

    # Override sqlalchemy.url in alembic config
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
