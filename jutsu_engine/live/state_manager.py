"""
State Manager - Persist and reconcile live trading state.

This module manages the state.json file that tracks trading state across sessions,
including position tracking, volatility state, and account reconciliation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timezone
from decimal import Decimal
import shutil

logger = logging.getLogger('LIVE.STATE')


class StateManager:
    """
    Manage live trading state persistence and reconciliation.

    Uses atomic file writes (temp + rename) to prevent corruption and
    maintains backups for recovery. Reconciles state with broker API
    to detect position drift.
    """

    def __init__(
        self,
        state_file: Path = Path('state/state.json'),
        backup_enabled: bool = True,
        backup_dir: Path = Path('state/backups')
    ):
        """
        Initialize state manager.

        Args:
            state_file: Path to state.json file
            backup_enabled: Enable automatic backups before save
            backup_dir: Directory for state backups
        """
        self.state_file = state_file
        self.backup_enabled = backup_enabled
        self.backup_dir = backup_dir

        # Create directories if they don't exist
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"StateManager initialized: {self.state_file}")

    def load_state(self) -> Dict[str, Any]:
        """
        Load state from file.

        Returns default state if file doesn't exist. Validates state
        integrity and logs warnings for any issues.

        Returns:
            State dictionary with keys:
                - last_run: ISO timestamp of last execution
                - vol_state: Volatility regime (-1, 0, 1)
                - current_positions: {symbol: quantity}
                - account_equity: Last known account value
                - last_allocation: Last target allocation weights

        Raises:
            ValueError: If state file is corrupted and cannot be recovered
        """
        if not self.state_file.exists():
            logger.warning(f"State file not found: {self.state_file}")
            logger.info("Returning default state")
            return self._default_state()

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

            logger.info(f"Loaded state: last_run={state.get('last_run')}")

            # Validate state integrity
            if not self.validate_state_integrity(state):
                logger.error("State integrity validation failed")
                # Try to recover from backup
                backup_state = self._load_latest_backup()
                if backup_state:
                    logger.warning("Recovered state from backup")
                    return backup_state
                else:
                    logger.error("No valid backup found, using default state")
                    return self._default_state()

            return state

        except json.JSONDecodeError as e:
            logger.error(f"State file corrupted (JSON decode error): {e}")
            # Try backup recovery
            backup_state = self._load_latest_backup()
            if backup_state:
                logger.warning("Recovered state from backup")
                return backup_state
            else:
                raise ValueError(f"State file corrupted and no backup available: {e}")

        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            raise

    def save_state(self, state: Dict[str, Any]) -> None:
        """
        Save state to file using atomic write pattern.

        Uses temp file + rename for atomicity on POSIX systems.
        Creates backup before overwriting if backup_enabled=True.

        Args:
            state: State dictionary to persist

        Raises:
            ValueError: If state validation fails
            IOError: If file write fails
        """
        # Validate state before saving
        if not self.validate_state_integrity(state):
            raise ValueError("State validation failed, refusing to save corrupted state")

        # Update last_run timestamp
        state['last_run'] = datetime.now(timezone.utc).isoformat()

        # Backup existing state if enabled
        if self.backup_enabled and self.state_file.exists():
            self._backup_current_state()

        # Atomic write: temp file + rename
        temp_file = self.state_file.with_suffix('.tmp')

        try:
            # Write to temporary file
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)

            # Atomic rename (POSIX systems)
            temp_file.rename(self.state_file)

            logger.info(f"State saved: {state.get('last_run')}")
            logger.debug(f"Positions: {state.get('current_positions', {})}")

        except Exception as e:
            # Clean up temp file on failure
            if temp_file.exists():
                temp_file.unlink()
            logger.error(f"Failed to save state: {e}")
            raise IOError(f"State save failed: {e}")

    def validate_state_integrity(self, state: Dict[str, Any]) -> bool:
        """
        Validate state file structure and data types.

        Args:
            state: State dictionary to validate

        Returns:
            True if state is valid, False otherwise
        """
        # Required keys
        required_keys = ['last_run', 'vol_state', 'current_positions']

        for key in required_keys:
            if key not in state:
                logger.error(f"State missing required key: {key}")
                return False

        # Validate data types
        if not isinstance(state['current_positions'], dict):
            logger.error("current_positions must be a dictionary")
            return False

        if state['vol_state'] not in [-1, 0, 1, None]:
            logger.error(f"Invalid vol_state: {state['vol_state']}")
            return False

        # Validate position quantities are integers
        for symbol, qty in state['current_positions'].items():
            if not isinstance(qty, int):
                logger.error(f"Position quantity for {symbol} must be integer, got {type(qty)}")
                return False

        logger.debug("State integrity validation: PASSED")
        return True

    def reconcile_with_account(
        self,
        state_positions: Dict[str, int],
        api_positions: Dict[str, int],
        threshold_pct: float = 2.0
    ) -> Dict[str, Dict[str, int]]:
        """
        Reconcile state.json positions with API account positions.

        Detects position drift between local state and broker account,
        which can occur due to manual trades, corporate actions, or
        state file corruption.

        Args:
            state_positions: Positions from state.json {symbol: qty}
            api_positions: Positions from Schwab API {symbol: qty}
            threshold_pct: Warning threshold for position drift (default 2%)

        Returns:
            Discrepancies dictionary:
                {symbol: {'state': qty, 'api': qty, 'diff': qty, 'drift_pct': %}}
                Empty dict if no discrepancies

        Raises:
            ValueError: If drift exceeds critical threshold (>10%)
        """
        discrepancies = {}

        # Get all symbols from both sources
        all_symbols = set(state_positions.keys()) | set(api_positions.keys())

        for symbol in all_symbols:
            state_qty = state_positions.get(symbol, 0)
            api_qty = api_positions.get(symbol, 0)

            if state_qty != api_qty:
                diff = api_qty - state_qty

                # Calculate drift percentage
                if state_qty != 0:
                    drift_pct = abs(diff / state_qty) * 100
                else:
                    drift_pct = 100.0 if api_qty != 0 else 0.0

                discrepancies[symbol] = {
                    'state': state_qty,
                    'api': api_qty,
                    'diff': diff,
                    'drift_pct': drift_pct
                }

                # Log based on severity
                if drift_pct > 10.0:
                    logger.error(
                        f"CRITICAL position drift {symbol}: state={state_qty}, "
                        f"api={api_qty}, drift={drift_pct:.1f}%"
                    )
                    raise ValueError(
                        f"Critical position drift detected: {symbol} drift={drift_pct:.1f}%"
                    )
                elif drift_pct > threshold_pct:
                    logger.warning(
                        f"Position drift {symbol}: state={state_qty}, "
                        f"api={api_qty}, drift={drift_pct:.1f}%"
                    )
                else:
                    logger.info(
                        f"Minor position drift {symbol}: state={state_qty}, "
                        f"api={api_qty}, drift={drift_pct:.1f}%"
                    )

        if not discrepancies:
            logger.info("State reconciliation: PASSED (no discrepancies)")
        else:
            logger.warning(f"State reconciliation: {len(discrepancies)} discrepancies found")

        return discrepancies

    def _default_state(self) -> Dict[str, Any]:
        """
        Return default state structure.

        Returns:
            Default state with empty positions and null values
        """
        return {
            'last_run': None,
            'vol_state': 0,
            'current_positions': {},
            'account_equity': None,
            'last_allocation': {},
            'metadata': {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'version': '1.0'
            }
        }

    def _backup_current_state(self) -> None:
        """
        Create timestamped backup of current state file.

        Backups are stored in backup_dir with timestamp in filename.
        Only backs up if state file exists.
        """
        if not self.state_file.exists():
            return

        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        backup_file = self.backup_dir / f"state_backup_{timestamp}.json"

        try:
            shutil.copy2(self.state_file, backup_file)
            logger.debug(f"State backed up to: {backup_file}")

            # Clean up old backups (keep last 10)
            self._cleanup_old_backups(keep_count=10)

        except Exception as e:
            logger.warning(f"Failed to backup state: {e}")
            # Don't fail if backup fails

    def _load_latest_backup(self) -> Optional[Dict[str, Any]]:
        """
        Load the most recent valid backup file.

        Returns:
            Backup state dict if found and valid, None otherwise
        """
        if not self.backup_dir.exists():
            return None

        # Get all backup files sorted by modification time (newest first)
        backups = sorted(
            self.backup_dir.glob('state_backup_*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for backup_file in backups:
            try:
                with open(backup_file, 'r') as f:
                    state = json.load(f)

                if self.validate_state_integrity(state):
                    logger.info(f"Loaded valid backup: {backup_file}")
                    return state

            except Exception as e:
                logger.warning(f"Backup {backup_file} invalid: {e}")
                continue

        logger.error("No valid backups found")
        return None

    def _cleanup_old_backups(self, keep_count: int = 10) -> None:
        """
        Remove old backup files, keeping only the most recent N.

        Args:
            keep_count: Number of backups to keep (default 10)
        """
        backups = sorted(
            self.backup_dir.glob('state_backup_*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        # Delete backups beyond keep_count
        for backup in backups[keep_count:]:
            try:
                backup.unlink()
                logger.debug(f"Deleted old backup: {backup}")
            except Exception as e:
                logger.warning(f"Failed to delete backup {backup}: {e}")


def main():
    """Test state manager functionality."""
    logging.basicConfig(level=logging.INFO)

    manager = StateManager()

    # Test default state
    state = manager.load_state()
    print(f"Default state: {state}")

    # Test save
    state['vol_state'] = 1
    state['current_positions'] = {'TQQQ': 100, 'TMF': 50}
    manager.save_state(state)

    # Test load
    loaded = manager.load_state()
    print(f"Loaded state: {loaded}")

    # Test reconciliation
    api_positions = {'TQQQ': 102, 'TMF': 50}  # 2 share drift in TQQQ
    discrepancies = manager.reconcile_with_account(
        state['current_positions'],
        api_positions
    )
    print(f"Discrepancies: {discrepancies}")


if __name__ == "__main__":
    main()
