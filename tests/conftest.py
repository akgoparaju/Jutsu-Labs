"""
Global pytest fixtures for Jutsu Labs test suite.

Provides PostgreSQL session fixtures using the STAGING database.
All tests should use these fixtures instead of creating SQLite in-memory databases.
"""
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from urllib.parse import quote_plus
from dotenv import load_dotenv

from jutsu_engine.data.models import Base

# Load environment variables
load_dotenv()


def get_staging_database_url() -> str:
    """
    Build PostgreSQL connection URL for STAGING database.

    Uses the same credentials as production but connects to jutsu_labs_staging.
    """
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    user = os.getenv('POSTGRES_USER', 'jutsu')
    password = os.getenv('POSTGRES_PASSWORD')
    # Use staging database for tests
    database = os.getenv('POSTGRES_DATABASE_STAGING', 'jutsu_labs_staging')

    if not password:
        raise ValueError("POSTGRES_PASSWORD environment variable is required for tests")

    encoded_user = quote_plus(user)
    encoded_password = quote_plus(password)

    return f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"


@pytest.fixture(scope="session")
def db_engine():
    """
    Create database engine using STAGING database.

    Uses PostgreSQL staging database from .env configuration.
    Session-scoped for performance (engine reused across all tests).
    """
    db_url = get_staging_database_url()
    engine = create_engine(db_url, pool_pre_ping=True)

    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Session:
    """
    Create a database session for testing.

    Each test gets a fresh session that's rolled back after the test.
    This ensures test isolation without modifying the actual database.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def postgres_session(db_engine) -> Session:
    """
    Alias for db_session - PostgreSQL session for testing.

    Use this fixture in tests that specifically need PostgreSQL features
    like timezone() function.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="session")
def ensure_tables(db_engine):
    """
    Ensure all tables exist in the test database.

    This is session-scoped and only runs once.
    Tables are created if they don't exist.
    """
    Base.metadata.create_all(db_engine)
    yield
    # Don't drop tables - they're needed for the production database


@pytest.fixture(scope="function")
def clean_db_session(db_engine, ensure_tables) -> Session:
    """
    Database session with tables guaranteed to exist.

    Use this when tests need to insert data into existing tables.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
