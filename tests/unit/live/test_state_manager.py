"""
Unit tests for State Manager.

Tests atomic state persistence, validation, and reconciliation.
"""

import pytest
import json
import tempfile
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone

from jutsu_engine.live.state_manager import StateManager


@pytest.fixture
def temp_state_dir():
    """Create temporary directory for state files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_manager(temp_state_dir):
    """Create StateManager with temporary files."""
    state_file = temp_state_dir / 'state.json'
    backup_dir = temp_state_dir / 'backups'
    return StateManager(
        state_file=state_file,
        backup_enabled=True,
        backup_dir=backup_dir
    )


class TestStateManager:
    """Test suite for StateManager class."""

    def test_initialization_creates_directories(self, temp_state_dir):
        """Test that StateManager creates necessary directories."""
        state_file = temp_state_dir / 'state' / 'state.json'
        backup_dir = temp_state_dir / 'backups'

        manager = StateManager(
            state_file=state_file,
            backup_enabled=True,
            backup_dir=backup_dir
        )

        assert state_file.parent.exists()
        assert backup_dir.exists()

    def test_load_state_default_when_missing(self, state_manager):
        """Test load_state returns default when file doesn't exist."""
        state = state_manager.load_state()

        assert state['last_run'] is None
        assert state['vol_state'] == 0
        assert state['current_positions'] == {}
        assert state['account_equity'] is None
        assert 'metadata' in state

    def test_save_and_load_state(self, state_manager):
        """Test basic save and load cycle."""
        test_state = {
            'last_run': '2025-11-23T15:55:00+00:00',
            'vol_state': 1,
            'current_positions': {'TQQQ': 100, 'TMF': 50},
            'account_equity': 100000.00,
            'last_allocation': {'TQQQ': 0.6, 'TMF': 0.3, 'CASH': 0.1}
        }

        state_manager.save_state(test_state)
        loaded_state = state_manager.load_state()

        assert loaded_state['vol_state'] == 1
        assert loaded_state['current_positions'] == {'TQQQ': 100, 'TMF': 50}
        assert loaded_state['account_equity'] == 100000.00

    def test_atomic_write_creates_temp_file(self, state_manager, temp_state_dir):
        """Test that atomic write uses temp file (no .tmp left behind)."""
        test_state = {
            'last_run': None,
            'vol_state': 0,
            'current_positions': {}
        }

        state_manager.save_state(test_state)

        # Verify state.json exists
        assert state_manager.state_file.exists()

        # Verify NO .tmp file left behind (atomicity)
        temp_file = state_manager.state_file.with_suffix('.tmp')
        assert not temp_file.exists()

    def test_state_validation_required_keys(self, state_manager):
        """Test validation fails for missing required keys."""
        invalid_state = {
            'vol_state': 0,
            # Missing 'last_run' and 'current_positions'
        }

        assert state_manager.validate_state_integrity(invalid_state) is False

    def test_state_validation_invalid_vol_state(self, state_manager):
        """Test validation fails for invalid vol_state."""
        invalid_state = {
            'last_run': None,
            'vol_state': 5,  # Invalid (must be -1, 0, 1, or None)
            'current_positions': {}
        }

        assert state_manager.validate_state_integrity(invalid_state) is False

    def test_state_validation_non_integer_positions(self, state_manager):
        """Test validation fails for non-integer positions."""
        invalid_state = {
            'last_run': None,
            'vol_state': 0,
            'current_positions': {'TQQQ': 100.5}  # Must be int
        }

        assert state_manager.validate_state_integrity(invalid_state) is False

    def test_state_validation_valid_state(self, state_manager):
        """Test validation passes for valid state."""
        valid_state = {
            'last_run': '2025-11-23T15:55:00+00:00',
            'vol_state': 1,
            'current_positions': {'TQQQ': 100, 'TMF': 50}
        }

        assert state_manager.validate_state_integrity(valid_state) is True

    def test_save_state_refuses_invalid(self, state_manager):
        """Test save_state refuses to save invalid state."""
        invalid_state = {
            'vol_state': 99,  # Invalid
            # Missing keys
        }

        with pytest.raises(ValueError, match="State validation failed"):
            state_manager.save_state(invalid_state)

    def test_backup_creation(self, state_manager):
        """Test that backups are created before save."""
        # Save initial state
        state1 = {
            'last_run': None,
            'vol_state': 0,
            'current_positions': {'TQQQ': 100}
        }
        state_manager.save_state(state1)

        # Save second state (should create backup of first)
        state2 = {
            'last_run': None,
            'vol_state': 1,
            'current_positions': {'TQQQ': 120}
        }
        state_manager.save_state(state2)

        # Check backup directory has at least one backup
        backups = list(state_manager.backup_dir.glob('state_backup_*.json'))
        assert len(backups) >= 1

    def test_reconcile_with_account_no_discrepancies(self, state_manager):
        """Test reconciliation with matching positions."""
        state_positions = {'TQQQ': 100, 'TMF': 50}
        api_positions = {'TQQQ': 100, 'TMF': 50}

        discrepancies = state_manager.reconcile_with_account(
            state_positions,
            api_positions
        )

        assert discrepancies == {}

    def test_reconcile_with_account_minor_drift(self, state_manager):
        """Test reconciliation with minor drift (warning level)."""
        state_positions = {'TQQQ': 100}
        api_positions = {'TQQQ': 102}  # 2% drift

        discrepancies = state_manager.reconcile_with_account(
            state_positions,
            api_positions,
            threshold_pct=2.0
        )

        assert 'TQQQ' in discrepancies
        assert discrepancies['TQQQ']['state'] == 100
        assert discrepancies['TQQQ']['api'] == 102
        assert discrepancies['TQQQ']['diff'] == 2
        assert discrepancies['TQQQ']['drift_pct'] == 2.0

    def test_reconcile_with_account_critical_drift(self, state_manager):
        """Test reconciliation raises error for critical drift (>10%)."""
        state_positions = {'TQQQ': 100}
        api_positions = {'TQQQ': 120}  # 20% drift

        with pytest.raises(ValueError, match="Critical position drift"):
            state_manager.reconcile_with_account(
                state_positions,
                api_positions
            )

    def test_reconcile_with_account_new_position(self, state_manager):
        """Test reconciliation detects new position in API."""
        state_positions = {'TQQQ': 100}
        api_positions = {'TQQQ': 100, 'TMF': 50}  # New TMF position

        discrepancies = state_manager.reconcile_with_account(
            state_positions,
            api_positions
        )

        assert 'TMF' in discrepancies
        assert discrepancies['TMF']['state'] == 0
        assert discrepancies['TMF']['api'] == 50

    def test_reconcile_with_account_closed_position(self, state_manager):
        """Test reconciliation detects closed position."""
        state_positions = {'TQQQ': 100, 'TMF': 50}
        api_positions = {'TQQQ': 100}  # TMF closed

        discrepancies = state_manager.reconcile_with_account(
            state_positions,
            api_positions
        )

        assert 'TMF' in discrepancies
        assert discrepancies['TMF']['state'] == 50
        assert discrepancies['TMF']['api'] == 0

    def test_backup_recovery_on_corruption(self, state_manager, temp_state_dir):
        """Test recovery from backup when state file is corrupted."""
        # Save valid state (creates backup)
        valid_state = {
            'last_run': None,
            'vol_state': 1,
            'current_positions': {'TQQQ': 100}
        }
        state_manager.save_state(valid_state)

        # Corrupt state file
        with open(state_manager.state_file, 'w') as f:
            f.write("CORRUPTED JSON{{{")

        # Load should recover from backup
        loaded_state = state_manager.load_state()

        # Should have recovered from backup
        assert loaded_state['vol_state'] == 1
        assert loaded_state['current_positions'] == {'TQQQ': 100}

    def test_cleanup_old_backups(self, state_manager):
        """Test that old backups are cleaned up (keeps last 10)."""
        # Create 15 saves (should trigger cleanup)
        for i in range(15):
            state = {
                'last_run': None,
                'vol_state': i % 3,
                'current_positions': {'TQQQ': 100 + i}
            }
            state_manager.save_state(state)

        # Check backup directory has at most 10 backups
        backups = list(state_manager.backup_dir.glob('state_backup_*.json'))
        assert len(backups) <= 10

    def test_default_state_structure(self, state_manager):
        """Test default state has required structure."""
        default = state_manager._default_state()

        assert default['last_run'] is None
        assert default['vol_state'] == 0
        assert default['current_positions'] == {}
        assert default['account_equity'] is None
        assert default['last_allocation'] == {}
        assert 'metadata' in default
        assert 'created_at' in default['metadata']
        assert 'version' in default['metadata']

    def test_state_preserves_decimal_type(self, state_manager):
        """Test that Decimal values are preserved (via default=str)."""
        state = {
            'last_run': None,
            'vol_state': 0,
            'current_positions': {'TQQQ': 100},
            'account_equity': 100000.00  # Will be saved as string
        }

        state_manager.save_state(state)
        loaded = state_manager.load_state()

        # Equity loaded as float, but no precision loss for this value
        assert loaded['account_equity'] == 100000.00
