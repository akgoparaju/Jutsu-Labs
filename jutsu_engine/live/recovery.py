"""
Recovery Manager - Crash recovery and missed execution detection.

This module provides automatic recovery mechanisms including:
- Missed execution detection (cron failures)
- Automatic restart coordination
- Recovery notifications via AlertManager
- Heartbeat tracking for process health
"""

import logging
import subprocess
import json
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone, timedelta
from enum import Enum

logger = logging.getLogger('LIVE.RECOVERY')


class RecoveryAction(Enum):
    """Enum for recovery actions taken."""
    NONE = "none"
    MISSED_EXECUTION_DETECTED = "missed_execution_detected"
    STATE_RECOVERED = "state_recovered"
    PROCESS_RESTARTED = "process_restarted"
    MANUAL_INTERVENTION_REQUIRED = "manual_intervention_required"


class RecoveryManager:
    """
    Manage crash recovery and missed execution detection.

    Tracks execution heartbeats to detect missed runs and coordinates
    recovery actions with alerts.
    """

    def __init__(
        self,
        config: Dict,
        alert_manager,
        state_manager,
        heartbeat_file: Path = Path('state/heartbeat.json')
    ):
        """
        Initialize recovery manager.

        Args:
            config: Configuration dictionary
            alert_manager: AlertManager instance for notifications
            state_manager: StateManager instance for state operations
            heartbeat_file: Path to heartbeat tracking file
        """
        self.config = config
        self.alert_manager = alert_manager
        self.state_manager = state_manager
        self.heartbeat_file = heartbeat_file

        # Recovery configuration
        recovery_config = config.get('recovery', {})
        self.max_missed_hours = recovery_config.get('max_missed_hours', 26)
        self.heartbeat_interval_minutes = recovery_config.get(
            'heartbeat_interval_minutes', 60
        )
        self.auto_restart_enabled = recovery_config.get(
            'auto_restart_enabled', False
        )

        # Ensure heartbeat directory exists
        self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"RecoveryManager initialized: max_missed={self.max_missed_hours}h, "
            f"auto_restart={self.auto_restart_enabled}"
        )

    def record_heartbeat(self, execution_type: str = 'scheduled') -> None:
        """
        Record execution heartbeat.

        Called after each successful execution to track that the
        system is running normally.

        Args:
            execution_type: Type of execution ('scheduled', 'manual', 'recovery')
        """
        heartbeat = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'execution_type': execution_type,
            'pid': self._get_current_pid()
        }

        try:
            # Load existing heartbeats (keep last 24)
            history = self._load_heartbeat_history()
            history.append(heartbeat)
            history = history[-24:]  # Keep last 24 heartbeats

            with open(self.heartbeat_file, 'w') as f:
                json.dump({
                    'last_heartbeat': heartbeat,
                    'history': history
                }, f, indent=2)

            logger.debug(f"Heartbeat recorded: {execution_type}")

        except Exception as e:
            logger.error(f"Failed to record heartbeat: {e}")

    def check_missed_executions(self) -> Optional[Dict[str, Any]]:
        """
        Check for missed scheduled executions.

        Compares last heartbeat timestamp against expected execution times
        to detect if cron jobs failed to run.

        Returns:
            Dict with missed execution details if detected, None otherwise:
                {
                    'missed': True,
                    'last_heartbeat': ISO timestamp,
                    'hours_since': float,
                    'expected_executions': int,
                    'action': RecoveryAction
                }
        """
        try:
            heartbeat_data = self._load_heartbeat_data()

            if not heartbeat_data or 'last_heartbeat' not in heartbeat_data:
                logger.warning("No heartbeat data found - first run or data lost")
                return None

            last_heartbeat = datetime.fromisoformat(
                heartbeat_data['last_heartbeat']['timestamp']
            )
            now = datetime.now(timezone.utc)
            hours_since = (now - last_heartbeat).total_seconds() / 3600

            # Check if we've exceeded max missed hours
            if hours_since > self.max_missed_hours:
                missed_info = {
                    'missed': True,
                    'last_heartbeat': heartbeat_data['last_heartbeat']['timestamp'],
                    'hours_since': round(hours_since, 2),
                    'expected_executions': self._estimate_missed_executions(hours_since),
                    'action': RecoveryAction.MANUAL_INTERVENTION_REQUIRED
                }

                logger.critical(
                    f"CRITICAL: Missed executions detected! "
                    f"Hours since last heartbeat: {hours_since:.1f}h"
                )

                return missed_info

            # Check for reasonable gap (more than 2 execution windows)
            # Assuming daily execution at market close
            if hours_since > 26:  # More than 1 day + buffer
                missed_info = {
                    'missed': True,
                    'last_heartbeat': heartbeat_data['last_heartbeat']['timestamp'],
                    'hours_since': round(hours_since, 2),
                    'expected_executions': self._estimate_missed_executions(hours_since),
                    'action': RecoveryAction.MISSED_EXECUTION_DETECTED
                }

                logger.warning(
                    f"Possible missed execution: {hours_since:.1f}h since last heartbeat"
                )

                return missed_info

            logger.debug(f"Heartbeat OK: {hours_since:.1f}h since last execution")
            return None

        except Exception as e:
            logger.error(f"Failed to check missed executions: {e}")
            return None

    def perform_recovery(self, missed_info: Dict[str, Any]) -> RecoveryAction:
        """
        Perform recovery actions for missed executions.

        Args:
            missed_info: Dictionary from check_missed_executions()

        Returns:
            RecoveryAction taken
        """
        action = missed_info.get('action', RecoveryAction.NONE)
        hours_since = missed_info.get('hours_since', 0)

        logger.info(f"Performing recovery: action={action.value}, hours_since={hours_since}")

        # Send recovery notification
        self._send_recovery_notification(missed_info)

        if action == RecoveryAction.MANUAL_INTERVENTION_REQUIRED:
            logger.critical(
                "Manual intervention required - too many missed executions"
            )
            # Don't auto-restart for extended outages
            return action

        if action == RecoveryAction.MISSED_EXECUTION_DETECTED:
            # Attempt state recovery
            state = self._recover_state()

            if state:
                logger.info("State recovered from backup")

                # Optionally trigger restart
                if self.auto_restart_enabled:
                    self._trigger_restart()
                    return RecoveryAction.PROCESS_RESTARTED

                return RecoveryAction.STATE_RECOVERED

        return RecoveryAction.NONE

    def _recover_state(self) -> Optional[Dict[str, Any]]:
        """
        Attempt to recover state from backup.

        Returns:
            Recovered state dict if successful, None otherwise
        """
        try:
            # Use StateManager's built-in recovery
            state = self.state_manager.load_state()

            if state:
                logger.info("State loaded (may be from backup)")
                return state

            logger.error("Failed to recover state")
            return None

        except Exception as e:
            logger.error(f"State recovery failed: {e}")
            return None

    def _trigger_restart(self) -> bool:
        """
        Trigger system restart via systemd or supervisor.

        Returns:
            True if restart triggered, False otherwise
        """
        if not self.auto_restart_enabled:
            logger.info("Auto-restart disabled, skipping")
            return False

        try:
            # Check if running under systemd
            if self._is_systemd_service():
                subprocess.run(
                    ['systemctl', 'restart', 'jutsu-live-trader'],
                    check=True,
                    capture_output=True
                )
                logger.info("Triggered systemd restart")
                return True

            # Check if running under supervisor
            elif self._is_supervisor_service():
                subprocess.run(
                    ['supervisorctl', 'restart', 'jutsu-live-trader'],
                    check=True,
                    capture_output=True
                )
                logger.info("Triggered supervisor restart")
                return True

            else:
                logger.warning(
                    "No service manager detected - manual restart required"
                )
                return False

        except subprocess.CalledProcessError as e:
            logger.error(f"Restart command failed: {e}")
            return False
        except FileNotFoundError:
            logger.warning("Service manager not available")
            return False

    def _send_recovery_notification(self, missed_info: Dict[str, Any]) -> None:
        """
        Send notification about recovery action.

        Args:
            missed_info: Dictionary with missed execution details
        """
        action = missed_info.get('action', RecoveryAction.NONE)
        hours_since = missed_info.get('hours_since', 0)
        expected_missed = missed_info.get('expected_executions', 0)

        if action == RecoveryAction.MANUAL_INTERVENTION_REQUIRED:
            self.alert_manager.send_critical_alert(
                error=f"CRITICAL: {expected_missed} missed executions ({hours_since:.1f}h)",
                context=(
                    f"Last heartbeat: {missed_info.get('last_heartbeat')}\n"
                    f"Manual intervention required - check cron and system logs"
                )
            )
        elif action == RecoveryAction.MISSED_EXECUTION_DETECTED:
            self.alert_manager.send_warning(
                warning=f"Missed execution detected ({hours_since:.1f}h gap)",
                details=(
                    f"Last heartbeat: {missed_info.get('last_heartbeat')}\n"
                    f"Estimated missed: {expected_missed} execution(s)\n"
                    f"Recovery action: Auto-recovery initiated"
                )
            )

    def _estimate_missed_executions(self, hours_since: float) -> int:
        """
        Estimate number of missed executions based on time gap.

        Assumes daily execution at market close.

        Args:
            hours_since: Hours since last heartbeat

        Returns:
            Estimated number of missed executions
        """
        # Assuming once-daily execution
        return max(0, int(hours_since / 24))

    def _load_heartbeat_data(self) -> Optional[Dict[str, Any]]:
        """
        Load heartbeat data from file.

        Returns:
            Heartbeat data dict or None if not found
        """
        if not self.heartbeat_file.exists():
            return None

        try:
            with open(self.heartbeat_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load heartbeat data: {e}")
            return None

    def _load_heartbeat_history(self) -> List[Dict[str, Any]]:
        """
        Load heartbeat history.

        Returns:
            List of heartbeat records
        """
        data = self._load_heartbeat_data()
        if data:
            return data.get('history', [])
        return []

    def _get_current_pid(self) -> int:
        """Get current process ID."""
        import os
        return os.getpid()

    def _is_systemd_service(self) -> bool:
        """Check if running under systemd."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'jutsu-live-trader'],
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _is_supervisor_service(self) -> bool:
        """Check if running under supervisor."""
        try:
            result = subprocess.run(
                ['supervisorctl', 'status', 'jutsu-live-trader'],
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def generate_recovery_report(self) -> Dict[str, Any]:
        """
        Generate recovery status report.

        Returns:
            Report dictionary with recovery status and history
        """
        heartbeat_data = self._load_heartbeat_data()
        missed_check = self.check_missed_executions()

        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': 'HEALTHY' if not missed_check else 'NEEDS_ATTENTION',
            'last_heartbeat': heartbeat_data.get('last_heartbeat') if heartbeat_data else None,
            'heartbeat_history_count': len(heartbeat_data.get('history', [])) if heartbeat_data else 0,
            'missed_execution_check': missed_check,
            'config': {
                'max_missed_hours': self.max_missed_hours,
                'auto_restart_enabled': self.auto_restart_enabled
            }
        }

        logger.info(f"Recovery report: {report['status']}")
        return report


def main():
    """Test recovery manager functionality."""
    logging.basicConfig(level=logging.INFO)

    print("\n⚠️  Recovery Manager Test")
    print("This module requires:")
    print("  - AlertManager instance")
    print("  - StateManager instance")

    print("\nCore functionality:")
    print("  ✅ Record execution heartbeats")
    print("  ✅ Detect missed executions (cron failures)")
    print("  ✅ Coordinate recovery actions")
    print("  ✅ Send recovery notifications")
    print("  ✅ Trigger auto-restart (if enabled)")

    print("\nUsage in daily_dry_run.py:")
    print("  1. Call recovery_manager.record_heartbeat() after execution")
    print("  2. Call recovery_manager.check_missed_executions() at startup")
    print("  3. Handle recovery actions if needed")

    # Demo heartbeat recording
    print("\nDemo: Creating heartbeat file...")
    heartbeat_path = Path('state/heartbeat.json')
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)

    demo_heartbeat = {
        'last_heartbeat': {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'execution_type': 'demo',
            'pid': 12345
        },
        'history': []
    }

    with open(heartbeat_path, 'w') as f:
        json.dump(demo_heartbeat, f, indent=2)

    print(f"  ✅ Heartbeat file created: {heartbeat_path}")


if __name__ == "__main__":
    main()
