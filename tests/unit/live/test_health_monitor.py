"""
Unit tests for HealthMonitor module.

Tests system health checks with mocked dependencies.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from jutsu_engine.live.health_monitor import HealthMonitor


@pytest.fixture
def config():
    """Standard test configuration."""
    return {
        'health': {
            'check_interval_hours': 6,
            'checks': [
                'api_connectivity',
                'state_file_integrity',
                'disk_space',
                'cron_schedule'
            ],
            'thresholds': {
                'min_disk_space_gb': 1.0
            }
        },
        'schwab': {
            'account_number': 'test_account_hash'
        }
    }


@pytest.fixture
def mock_client():
    """Create mock Schwab client."""
    client = Mock()
    return client


@pytest.fixture
def mock_alert_manager():
    """Create mock AlertManager."""
    return Mock()


@pytest.fixture
def valid_state_file():
    """Create temporary valid state file."""
    state = {
        'last_run': '2025-01-01T12:00:00Z',
        'vol_state': 0,
        'current_positions': {'TQQQ': 100, 'TMF': 50}
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(state, f)
        return Path(f.name)


@pytest.fixture
def health_monitor(mock_client, config, mock_alert_manager, valid_state_file):
    """Create HealthMonitor instance."""
    return HealthMonitor(
        client=mock_client,
        config=config,
        alert_manager=mock_alert_manager,
        state_file=valid_state_file
    )


class TestAPIConnectivity:
    """Test API connectivity check."""

    def test_check_api_connectivity_success(self, health_monitor, mock_client):
        """Test successful API connectivity check."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client.get_account.return_value = mock_response

        result = health_monitor.check_api_connectivity()

        assert result is True
        mock_client.get_account.assert_called_once()

    def test_check_api_connectivity_failure(self, health_monitor, mock_client):
        """Test API connectivity check failure."""
        mock_response = Mock()
        mock_response.status_code = 401  # Unauthorized
        mock_client.get_account.return_value = mock_response

        result = health_monitor.check_api_connectivity()

        assert result is False

    def test_check_api_connectivity_exception(self, health_monitor, mock_client):
        """Test API connectivity check with exception."""
        mock_client.get_account.side_effect = Exception("Network error")

        result = health_monitor.check_api_connectivity()

        assert result is False


class TestStateFileIntegrity:
    """Test state file integrity check."""

    def test_check_state_file_valid(self, health_monitor):
        """Test valid state file passes check."""
        result = health_monitor.check_state_file_integrity()

        assert result is True

    def test_check_state_file_missing(self, health_monitor):
        """Test missing state file fails check."""
        # Point to non-existent file
        health_monitor.state_file = Path('/tmp/nonexistent_state.json')

        result = health_monitor.check_state_file_integrity()

        assert result is False

    def test_check_state_file_corrupted_json(self, health_monitor):
        """Test corrupted JSON fails check."""
        # Create corrupted JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{invalid json")
            corrupted_file = Path(f.name)

        health_monitor.state_file = corrupted_file

        result = health_monitor.check_state_file_integrity()

        assert result is False

        # Cleanup
        corrupted_file.unlink()

    def test_check_state_file_missing_keys(self, health_monitor):
        """Test state file with missing required keys fails."""
        # Create state with missing keys
        incomplete_state = {'last_run': '2025-01-01T12:00:00Z'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(incomplete_state, f)
            incomplete_file = Path(f.name)

        health_monitor.state_file = incomplete_file

        result = health_monitor.check_state_file_integrity()

        assert result is False

        # Cleanup
        incomplete_file.unlink()

    def test_check_state_file_invalid_types(self, health_monitor):
        """Test state file with invalid data types fails."""
        # Position quantity must be int, not string
        invalid_state = {
            'last_run': '2025-01-01T12:00:00Z',
            'vol_state': 0,
            'current_positions': {'TQQQ': '100'}  # String instead of int
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(invalid_state, f)
            invalid_file = Path(f.name)

        health_monitor.state_file = invalid_file

        result = health_monitor.check_state_file_integrity()

        assert result is False

        # Cleanup
        invalid_file.unlink()


class TestDiskSpace:
    """Test disk space check."""

    def test_check_disk_space_sufficient(self, health_monitor):
        """Test disk space check passes with sufficient space."""
        with patch('shutil.disk_usage') as mock_usage:
            # Mock 10GB free
            mock_usage.return_value = Mock(free=10 * 1024**3)

            result = health_monitor.check_disk_space()

            assert result is True

    def test_check_disk_space_insufficient(self, health_monitor):
        """Test disk space check fails with insufficient space."""
        with patch('shutil.disk_usage') as mock_usage:
            # Mock 0.5GB free (below 1GB threshold)
            mock_usage.return_value = Mock(free=0.5 * 1024**3)

            result = health_monitor.check_disk_space()

            assert result is False

    def test_check_disk_space_exception(self, health_monitor):
        """Test disk space check handles exceptions."""
        with patch('shutil.disk_usage') as mock_usage:
            mock_usage.side_effect = Exception("Disk error")

            result = health_monitor.check_disk_space()

            assert result is False


class TestCronSchedule:
    """Test cron schedule check."""

    def test_check_cron_schedule_exists(self, health_monitor):
        """Test cron schedule check passes when job exists."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "0 15 * * * python scripts/live_trader.py"

        with patch('subprocess.run', return_value=mock_result):
            result = health_monitor.check_cron_schedule()

            assert result is True

    def test_check_cron_schedule_missing(self, health_monitor):
        """Test cron schedule check fails when job missing."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "0 0 * * * some_other_job"  # No live_trader

        with patch('subprocess.run', return_value=mock_result):
            result = health_monitor.check_cron_schedule()

            assert result is False

    def test_check_cron_schedule_no_crontab(self, health_monitor):
        """Test cron schedule check handles no crontab."""
        mock_result = Mock()
        mock_result.returncode = 1  # Error code

        with patch('subprocess.run', return_value=mock_result):
            result = health_monitor.check_cron_schedule()

            assert result is False

    def test_check_cron_schedule_non_unix(self, health_monitor):
        """Test cron schedule check on non-Unix systems."""
        with patch('subprocess.run', side_effect=FileNotFoundError):
            result = health_monitor.check_cron_schedule()

            # Should pass on non-Unix systems
            assert result is True


class TestRunHealthChecks:
    """Test running all health checks."""

    def test_run_health_checks_all_pass(self, health_monitor, mock_client, mock_alert_manager):
        """Test all health checks passing."""
        # Mock all checks to pass
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client.get_account.return_value = mock_response

        with patch('shutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(free=10 * 1024**3)

            with patch('subprocess.run') as mock_subprocess:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "0 15 * * * python scripts/live_trader.py"
                mock_subprocess.return_value = mock_result

                checks = health_monitor.run_health_checks()

                # All checks should pass
                assert all(checks.values())

                # No alert should be sent
                mock_alert_manager.send_critical_alert.assert_not_called()

    def test_run_health_checks_some_fail(self, health_monitor, mock_client, mock_alert_manager):
        """Test some health checks failing."""
        # API check fails
        mock_client.get_account.side_effect = Exception("API error")

        # Disk space passes
        with patch('shutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(free=10 * 1024**3)

            with patch('subprocess.run') as mock_subprocess:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "0 15 * * * python scripts/live_trader.py"
                mock_subprocess.return_value = mock_result

                checks = health_monitor.run_health_checks()

                # API check should fail
                assert checks['api_connectivity'] is False

                # Others should pass
                assert checks['state_file_integrity'] is True
                assert checks['disk_space'] is True
                assert checks['cron_schedule'] is True

                # Critical alert should be sent
                mock_alert_manager.send_critical_alert.assert_called_once()


class TestGenerateHealthReport:
    """Test health report generation."""

    def test_generate_health_report_healthy(self, health_monitor, mock_client):
        """Test generating health report when all checks pass."""
        # Mock all checks to pass
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client.get_account.return_value = mock_response

        with patch('shutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(free=10 * 1024**3)

            with patch('subprocess.run') as mock_subprocess:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "0 15 * * * python scripts/live_trader.py"
                mock_subprocess.return_value = mock_result

                report = health_monitor.generate_health_report()

                assert report['overall_status'] == 'HEALTHY'
                assert len(report['failed_checks']) == 0
                assert 'timestamp' in report
                assert 'checks' in report
                assert 'config' in report

    def test_generate_health_report_unhealthy(self, health_monitor, mock_client):
        """Test generating health report when checks fail."""
        # API check fails
        mock_client.get_account.side_effect = Exception("API error")

        with patch('shutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(free=10 * 1024**3)

            with patch('subprocess.run') as mock_subprocess:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = ""  # No cron job
                mock_subprocess.return_value = mock_result

                report = health_monitor.generate_health_report()

                assert report['overall_status'] == 'UNHEALTHY'
                assert 'api_connectivity' in report['failed_checks']
                assert 'cron_schedule' in report['failed_checks']
