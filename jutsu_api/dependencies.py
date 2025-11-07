"""Dependency injection for API endpoints.

Provides reusable dependencies for database sessions,
authentication, and other shared resources.
"""
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from jutsu_api.config import get_settings
import logging

logger = logging.getLogger("API.DEPENDENCIES")

# Database setup
settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Get database session for request.

    Yields:
        SQLAlchemy session

    Usage:
        @router.get("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            # Use db session
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
