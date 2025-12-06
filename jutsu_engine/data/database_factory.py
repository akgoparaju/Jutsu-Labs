"""
Database factory for creating SQLAlchemy engines.

Supports multiple database backends:
- SQLite: Development and testing
- PostgreSQL: Production deployment

Handles connection pooling, configuration, and optimization
for each database type.

Example:
    from jutsu_engine.data.database_factory import DatabaseFactory

    # SQLite (development)
    engine = DatabaseFactory.create_engine(
        'sqlite',
        {'database': 'data/market_data.db'}
    )

    # PostgreSQL (production)
    engine = DatabaseFactory.create_engine(
        'postgresql',
        {
            'host': 'localhost',
            'port': 5432,
            'user': 'jutsu',
            'password': 'password',
            'database': 'jutsu_labs'
        }
    )
"""
from typing import Literal, Dict, Any
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool, StaticPool
from jutsu_engine.utils.logging_config import get_data_logger

logger = get_data_logger('DATABASE.FACTORY')


class DatabaseFactory:
    """
    Factory for creating database engines with proper configuration.

    Abstracts database-specific setup to support multiple backends
    while maintaining a consistent interface.
    """

    @staticmethod
    def create_engine(
        db_type: Literal['sqlite', 'postgresql'],
        config: Dict[str, Any]
    ) -> Engine:
        """
        Create SQLAlchemy engine based on database type and configuration.

        Args:
            db_type: Database backend type ('sqlite' or 'postgresql')
            config: Database-specific configuration dictionary

        Returns:
            Configured SQLAlchemy Engine

        Raises:
            ValueError: If db_type is unsupported or config is invalid

        Example:
            # SQLite
            engine = DatabaseFactory.create_engine(
                'sqlite',
                {'database': 'data/market_data.db', 'echo': False}
            )

            # PostgreSQL
            engine = DatabaseFactory.create_engine(
                'postgresql',
                {
                    'host': 'localhost',
                    'port': 5432,
                    'user': 'jutsu',
                    'password': 'secret',
                    'database': 'jutsu_labs',
                    'pool_size': 10,
                    'max_overflow': 20
                }
            )
        """
        if db_type == 'sqlite':
            return DatabaseFactory._create_sqlite_engine(config)
        elif db_type == 'postgresql':
            return DatabaseFactory._create_postgresql_engine(config)
        else:
            raise ValueError(
                f"Unsupported database type: {db_type}. "
                f"Supported types: 'sqlite', 'postgresql'"
            )

    @staticmethod
    def _create_sqlite_engine(config: Dict[str, Any]) -> Engine:
        """
        Create SQLite engine for development and testing.

        Args:
            config: SQLite configuration
                - database: Path to database file (required)
                - echo: Enable SQL logging (optional, default: False)

        Returns:
            SQLite engine with appropriate settings

        Example:
            engine = DatabaseFactory._create_sqlite_engine({
                'database': 'data/market_data.db',
                'echo': False
            })
        """
        database_path = config.get('database')
        if not database_path:
            raise ValueError("SQLite config must include 'database' path")

        echo = config.get('echo', False)

        # Use file-based database
        if database_path == ':memory:':
            # In-memory database for testing
            connection_string = 'sqlite:///:memory:'
            poolclass = StaticPool  # StaticPool for in-memory
            logger.info("Creating in-memory SQLite engine")
        else:
            connection_string = f'sqlite:///{database_path}'
            poolclass = None  # Default pool for file-based
            logger.info(f"Creating SQLite engine: {database_path}")

        engine = create_engine(
            connection_string,
            echo=echo,
            poolclass=poolclass,
            connect_args={'check_same_thread': False} if database_path != ':memory:' else {}
        )

        logger.info(f"SQLite engine created successfully")
        return engine

    @staticmethod
    def _create_postgresql_engine(config: Dict[str, Any]) -> Engine:
        """
        Create PostgreSQL engine with connection pooling for production.

        Args:
            config: PostgreSQL configuration
                - host: Database host (required)
                - port: Database port (required)
                - user: Database user (required)
                - password: Database password (required)
                - database: Database name (required)
                - pool_size: Connection pool size (optional, default: 10)
                - max_overflow: Max overflow connections (optional, default: 20)
                - pool_timeout: Pool timeout in seconds (optional, default: 30)
                - pool_recycle: Connection recycle time (optional, default: 3600)
                - echo: Enable SQL logging (optional, default: False)

        Returns:
            PostgreSQL engine with connection pooling

        Example:
            engine = DatabaseFactory._create_postgresql_engine({
                'host': 'localhost',
                'port': 5432,
                'user': 'jutsu',
                'password': 'secret',
                'database': 'jutsu_labs',
                'pool_size': 10,
                'max_overflow': 20
            })
        """
        # Validate required fields
        required_fields = ['host', 'port', 'user', 'password', 'database']
        missing_fields = [f for f in required_fields if f not in config]
        if missing_fields:
            raise ValueError(
                f"PostgreSQL config missing required fields: {missing_fields}"
            )

        # Extract configuration
        host = config['host']
        port = config['port']
        user = config['user']
        password = config['password']
        database = config['database']
        pool_size = config.get('pool_size', 10)
        max_overflow = config.get('max_overflow', 20)
        pool_timeout = config.get('pool_timeout', 30)
        pool_recycle = config.get('pool_recycle', 3600)
        echo = config.get('echo', False)

        # Build connection string
        connection_string = (
            f'postgresql://{user}:{password}@{host}:{port}/{database}'
        )

        logger.info(
            f"Creating PostgreSQL engine: {user}@{host}:{port}/{database}"
        )
        logger.info(
            f"Connection pool: size={pool_size}, max_overflow={max_overflow}"
        )

        engine = create_engine(
            connection_string,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,  # Verify connections before use
            echo=echo
        )

        logger.info("PostgreSQL engine created successfully")
        return engine

    @staticmethod
    def create_session_maker(engine: Engine):
        """
        Create session maker from engine.

        Args:
            engine: SQLAlchemy engine

        Returns:
            Configured sessionmaker

        Example:
            engine = DatabaseFactory.create_engine('sqlite', {...})
            SessionMaker = DatabaseFactory.create_session_maker(engine)
            session = SessionMaker()
        """
        from sqlalchemy.orm import sessionmaker
        return sessionmaker(bind=engine)
