"""
Health Monitor - System health checks and monitoring.

This module performs periodic health checks on critical system components
and sends alerts if any checks fail. Designed to run as a cron job.
"""

import logging
import json
import shutil
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger('LIVE.HEALTH')


class HealthMonitor:
    """
    Monitor system health with configurable checks.

    Checks:
    1. API connectivity (Schwab authentication)
    2. State file integrity (JSON validation)
    3. Disk space (minimum threshold)
    4. Cron schedule (job exists in crontab)
    """

    def __init__(
        self,
        client,
        config: Dict,
        alert_manager,
        state_file: Path = Path('state/state.json')
    ):
        """
        Initialize health monitor.

        Args:
            client: Authenticated schwab-py client
            config: Configuration dictionary
            alert_manager: AlertManager instance for notifications
            state_file: Path to state.json file
        """
        self.client = client
        self.config = config
        self.alert_manager = alert_manager
        self.state_file = state_file

        health_config = config.get('health', {})
        self.min_disk_space_gb = health_config.get(
            'thresholds', {}
        ).get('min_disk_space_gb', 1.0)

        logger.info("HealthMonitor initialized")

    def check_api_connectivity(self) -> bool:
        """
        Test Schwab API connectivity with a lightweight API call.

        Attempts to fetch account info to verify authentication
        and network connectivity.

        Returns:
            True if API is reachable and authenticated, False otherwise
        """
        logger.info("Checking API connectivity...")

        try:
            # Test API call - get account info
            account_hash = self.config.get('schwab', {}).get('account_number')

            if not account_hash:
                logger.error("Account hash not configured")
                return False

            # Lightweight API call
            response = self.client.get_account(account_hash)

            if response.status_code == 200:
                logger.info("API connectivity check: PASSED ✅")
                return True
            else:
                logger.error(f"API returned status {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"API connectivity check FAILED: {e}")
            return False

    def check_state_file_integrity(self) -> bool:
        """
        Validate state.json file structure and data types.

        Checks:
        - File exists and is readable
        - Valid JSON format
        - Required keys present
        - Data types correct

        Returns:
            True if state file is valid, False otherwise
        """
        logger.info("Checking state file integrity...")

        if not self.state_file.exists():
            logger.error(f"State file not found: {self.state_file}")
            return False

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

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
                    logger.error(
                        f"Position quantity for {symbol} must be integer, "
                        f"got {type(qty)}"
                    )
                    return False

            logger.info("State file integrity check: PASSED ✅")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"State file JSON decode error: {e}")
            return False
        except Exception as e:
            logger.error(f"State file integrity check FAILED: {e}")
            return False

    def check_disk_space(self) -> bool:
        """
        Check available disk space.

        Verifies that at least min_disk_space_gb (default: 1GB) is available
        on the filesystem where the project is located.

        Returns:
            True if sufficient space available, False otherwise
        """
        logger.info("Checking disk space...")

        try:
            # Get disk usage for current directory
            usage = shutil.disk_usage('.')

            # Convert to GB
            free_gb = usage.free / (1024 ** 3)

            logger.info(f"Free disk space: {free_gb:.2f} GB")

            if free_gb < self.min_disk_space_gb:
                logger.error(
                    f"Low disk space: {free_gb:.2f} GB "
                    f"< {self.min_disk_space_gb} GB threshold"
                )
                return False

            logger.info(f"Disk space check: PASSED ✅ ({free_gb:.2f} GB free)")
            return True

        except Exception as e:
            logger.error(f"Disk space check FAILED: {e}")
            return False

    def check_cron_schedule(self) -> bool:
        """
        Verify cron job exists for live trading script.

        Checks if crontab contains entry for live trading execution.

        Returns:
            True if cron job exists, False otherwise
        """
        logger.info("Checking cron schedule...")

        try:
            import subprocess

            # Get current crontab
            result = subprocess.run(
                ['crontab', '-l'],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                logger.warning("No crontab found or crontab access failed")
                return False

            crontab_content = result.stdout

            # Check for live trading script
            if 'live_trader' in crontab_content or 'jutsu' in crontab_content:
                logger.info("Cron schedule check: PASSED ✅")
                return True
            else:
                logger.error("Live trading cron job not found in crontab")
                return False

        except FileNotFoundError:
            logger.warning("crontab command not found (not on Unix system?)")
            return True  # Pass on non-Unix systems
        except Exception as e:
            logger.error(f"Cron schedule check FAILED: {e}")
            return False

    def run_health_checks(self) -> Dict[str, bool]:
        """
        Run all health checks and send alerts if any fail.

        Returns:
            Dictionary of check results: {check_name: passed}
        """
        logger.info("Running health checks...")

        checks = {
            'api_connectivity': self.check_api_connectivity(),
            'state_file_integrity': self.check_state_file_integrity(),
            'disk_space': self.check_disk_space(),
            'cron_schedule': self.check_cron_schedule()
        }

        # Identify failures
        failed_checks = [name for name, passed in checks.items() if not passed]

        # Send alerts if any checks failed
        if failed_checks:
            error_msg = f"Health checks failed: {', '.join(failed_checks)}"
            logger.critical(error_msg)

            # Send critical alert
            self.alert_manager.send_critical_alert(
                error=error_msg,
                context=f"Failed checks: {failed_checks}"
            )
        else:
            logger.info("All health checks PASSED ✅")

        return checks

    def generate_health_report(self) -> Dict:
        """
        Generate comprehensive health report.

        Returns:
            Health report dictionary with check results and metadata
        """
        logger.info("Generating health report...")

        checks = self.run_health_checks()

        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_status': 'HEALTHY' if all(checks.values()) else 'UNHEALTHY',
            'checks': checks,
            'failed_checks': [name for name, passed in checks.items() if not passed],
            'config': {
                'min_disk_space_gb': self.min_disk_space_gb
            }
        }

        logger.info(f"Health report: {report['overall_status']}")
        return report


def main():
    """Test health monitor functionality."""
    logging.basicConfig(level=logging.INFO)

    print("\n⚠️  Health Monitor Test")
    print("This module requires:")
    print("  - Authenticated Schwab API client")
    print("  - AlertManager instance")
    print("  - state.json file")

    print("\nCore functionality:")
    print("  ✅ Check API connectivity (Schwab authentication)")
    print("  ✅ Validate state.json integrity")
    print("  ✅ Check disk space (>1GB required)")
    print("  ✅ Verify cron schedule exists")
    print("  ✅ Send alerts if any check fails")

    print("\nTo test:")
    print("  1. See scripts/health_check.py for full example")
    print("  2. Run as cron job: */6 * * * * python scripts/health_check.py")


if __name__ == "__main__":
    main()
