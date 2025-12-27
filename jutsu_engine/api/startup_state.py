"""
Startup State Module for Application Readiness Tracking.

This module implements the Kubernetes-style readiness pattern for the Jutsu API.
It tracks whether the application has completed its initialization and is ready
to serve traffic.

Key concepts:
- Liveness: The application process is running (handled by supervisord)
- Readiness: The application has completed startup and can serve traffic

The readiness check ensures that:
1. Load balancers don't route traffic before the app is ready
2. Startup errors are properly detected and reported
3. The application can signal when critical services (DB, etc.) are available

Usage:
    from jutsu_engine.api.startup_state import startup_state

    # In lifespan handler:
    startup_state.mark_db_ready()
    startup_state.mark_ready()

    # In health check:
    if startup_state.is_ready:
        return {"status": "ok"}
    else:
        raise HTTPException(503, "Service not ready")
"""

import threading
from datetime import datetime, timezone
from typing import Optional


class StartupState:
    """
    Singleton to track application startup state for health/readiness checks.

    This class is thread-safe and maintains the following state:
    - _initialized: Whether the lifespan startup has completed
    - _db_ready: Whether the database connection is verified
    - _started_at: When the application process started
    - _ready_at: When the application became ready (None if not ready)
    - _error: Any error that occurred during startup

    The is_ready property returns True only when all components are ready
    and no errors have occurred.
    """

    _instance: Optional["StartupState"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "StartupState":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
                cls._instance._db_ready = False
                cls._instance._started_at = datetime.now(timezone.utc)
                cls._instance._ready_at: Optional[datetime] = None
                cls._instance._error: Optional[str] = None
        return cls._instance

    def mark_db_ready(self) -> None:
        """Mark database connection as verified and ready."""
        with self._lock:
            self._db_ready = True

    def mark_ready(self) -> None:
        """Mark application as fully initialized and ready to serve traffic."""
        with self._lock:
            self._initialized = True
            self._ready_at = datetime.now(timezone.utc)

    def mark_error(self, error: str) -> None:
        """Record a startup error that prevents readiness."""
        with self._lock:
            self._error = error

    def reset(self) -> None:
        """Reset state (primarily for testing purposes)."""
        with self._lock:
            self._initialized = False
            self._db_ready = False
            self._ready_at = None
            self._error = None

    @property
    def is_ready(self) -> bool:
        """
        Check if the application is ready to serve traffic.

        Returns True only when:
        - Lifespan initialization is complete
        - Database connection is verified
        - No startup errors have occurred
        """
        with self._lock:
            return self._initialized and self._db_ready and self._error is None

    @property
    def status(self) -> dict:
        """
        Get detailed startup status for health check responses.

        Returns a dictionary with:
        - ready: Overall readiness boolean
        - initialized: Whether lifespan completed
        - db_ready: Whether database is connected
        - started_at: Process start time
        - ready_at: When app became ready (None if not ready)
        - error: Any startup error message
        - uptime_seconds: Time since process started
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            uptime = (now - self._started_at).total_seconds()

            return {
                "ready": self._initialized and self._db_ready and self._error is None,
                "initialized": self._initialized,
                "db_ready": self._db_ready,
                "started_at": self._started_at.isoformat(),
                "ready_at": self._ready_at.isoformat() if self._ready_at else None,
                "error": self._error,
                "uptime_seconds": round(uptime, 2),
            }


# Global singleton instance
startup_state = StartupState()
