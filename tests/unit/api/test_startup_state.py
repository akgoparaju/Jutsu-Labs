"""
Tests for the startup_state module.

Tests the application readiness tracking system.
"""

import pytest
from datetime import datetime, timezone

from jutsu_engine.api.startup_state import StartupState


class TestStartupState:
    """Test the StartupState singleton for tracking application readiness."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before each test."""
        # Get the singleton instance and reset it
        state = StartupState()
        state.reset()
        yield
        # Clean up after test
        state.reset()

    def test_initial_state_not_ready(self):
        """Test that a fresh StartupState is not ready."""
        state = StartupState()
        assert state.is_ready is False
        status = state.status
        assert status["ready"] is False
        assert status["initialized"] is False
        assert status["db_ready"] is False
        assert status["error"] is None

    def test_mark_db_ready(self):
        """Test marking database as ready."""
        state = StartupState()
        assert state.status["db_ready"] is False

        state.mark_db_ready()

        assert state.status["db_ready"] is True
        # Still not fully ready without initialization
        assert state.is_ready is False

    def test_mark_ready(self):
        """Test marking application as ready."""
        state = StartupState()
        state.mark_db_ready()
        assert state.status["initialized"] is False
        assert state.status["ready_at"] is None

        state.mark_ready()

        assert state.status["initialized"] is True
        assert state.status["ready_at"] is not None
        # Now fully ready
        assert state.is_ready is True

    def test_full_startup_sequence(self):
        """Test the complete startup sequence."""
        state = StartupState()

        # Initial state
        assert state.is_ready is False

        # DB becomes ready
        state.mark_db_ready()
        assert state.is_ready is False

        # Lifespan completes
        state.mark_ready()
        assert state.is_ready is True

        # Verify status details
        status = state.status
        assert status["ready"] is True
        assert status["initialized"] is True
        assert status["db_ready"] is True
        assert status["error"] is None
        assert status["uptime_seconds"] >= 0

    def test_mark_error_prevents_ready(self):
        """Test that an error prevents readiness."""
        state = StartupState()
        state.mark_db_ready()
        state.mark_ready()
        assert state.is_ready is True

        # Error occurs
        state.mark_error("Database connection lost")

        assert state.is_ready is False
        assert state.status["error"] == "Database connection lost"

    def test_status_includes_timestamps(self):
        """Test that status includes proper timestamps."""
        state = StartupState()

        status = state.status
        assert "started_at" in status
        assert "uptime_seconds" in status

        # Verify started_at is a valid ISO format timestamp
        started_at = datetime.fromisoformat(status["started_at"].replace("Z", "+00:00"))
        assert started_at is not None

        # Uptime should be a positive number
        assert status["uptime_seconds"] >= 0

    def test_singleton_pattern(self):
        """Test that StartupState is a singleton."""
        state1 = StartupState()
        state2 = StartupState()

        assert state1 is state2

        # Changes in one instance affect the other
        state1.mark_db_ready()
        assert state2.status["db_ready"] is True

    def test_reset_clears_state(self):
        """Test that reset clears all state."""
        state = StartupState()
        state.mark_db_ready()
        state.mark_ready()
        state.mark_error("Some error")

        state.reset()

        assert state.is_ready is False
        assert state.status["initialized"] is False
        assert state.status["db_ready"] is False
        assert state.status["error"] is None
        assert state.status["ready_at"] is None
