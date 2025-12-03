#!/usr/bin/env python3
"""
Health Check Script

Runs system health checks and sends alerts if any fail.
Designed to run as cron job every 6 hours.

Usage:
    python scripts/health_check.py

Cron Entry:
    0 */6 * * * cd /path/to/jutsu-labs && python3 scripts/health_check.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
import yaml
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from schwab import auth

from jutsu_engine.live.health_monitor import HealthMonitor
from jutsu_engine.live.alert_manager import AlertManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/health_check_{datetime.now().strftime("%Y-%m-%d")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('LIVE.HEALTH_CHECK')


def load_config() -> dict:
    """Load configuration from YAML file."""
    config_path = project_root / 'config' / 'live_trading_config.yaml'

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    return config


def authenticate_schwab(config: dict):
    """Authenticate with Schwab API."""
    logger.info("Authenticating with Schwab API...")

    api_key = config['schwab']['api_key']
    api_secret = config['schwab']['api_secret']
    token_path = config['schwab']['token_path']

    schwab_client = auth.client_from_token_file(
        token_path=token_path,
        api_key=api_key,
        app_secret=api_secret
    )

    logger.info("Authentication successful")
    return schwab_client


def main():
    """Run health checks."""
    logger.info("=" * 80)
    logger.info("SYSTEM HEALTH CHECK")
    logger.info("=" * 80)

    try:
        # Load configuration
        logger.info("\nLoading configuration...")
        config = load_config()

        # Initialize alert manager
        alert_manager = AlertManager(config)

        # Authenticate
        logger.info("\nAuthenticating...")
        schwab_client = authenticate_schwab(config)

        # Initialize health monitor
        logger.info("\nInitializing health monitor...")
        health_monitor = HealthMonitor(
            client=schwab_client,
            config=config,
            alert_manager=alert_manager
        )

        # Run health checks
        logger.info("\nRunning health checks...")
        report = health_monitor.generate_health_report()

        # Log report
        logger.info("\n" + "=" * 80)
        logger.info("HEALTH REPORT")
        logger.info("=" * 80)
        logger.info(f"Timestamp: {report['timestamp']}")
        logger.info(f"Overall Status: {report['overall_status']}")
        logger.info("\nCheck Results:")

        for check_name, passed in report['checks'].items():
            status = "✅ PASSED" if passed else "❌ FAILED"
            logger.info(f"  {check_name}: {status}")

        if report['failed_checks']:
            logger.warning(f"\nFailed Checks: {', '.join(report['failed_checks'])}")

        logger.info("=" * 80)

        # Save report to file
        report_path = project_root / 'logs' / f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"\nHealth report saved to: {report_path}")

        # Return exit code based on status
        if report['overall_status'] == 'HEALTHY':
            logger.info("\n✅ All health checks PASSED")
            return 0
        else:
            logger.error("\n❌ Some health checks FAILED")
            return 1

    except Exception as e:
        logger.error(f"Health check failed with error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
