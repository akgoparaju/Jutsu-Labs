"""
Unit tests for AlertManager module.

Tests SMS and email alert functionality with mocked Twilio/SendGrid.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os

from jutsu_engine.live.alert_manager import AlertManager


@pytest.fixture
def config():
    """Standard test configuration."""
    return {
        'alerts': {
            'sms_enabled': True,
            'email_enabled': True,
            'critical_conditions': ['auth_failure', 'slippage_exceeded'],
            'sms_number': '+1234567890',
            'email_address': 'test@example.com'
        }
    }


@pytest.fixture
def alert_manager_no_init(config):
    """Create AlertManager without initializing clients (for mocking)."""
    with patch.object(AlertManager, '_init_twilio', return_value=None):
        with patch.object(AlertManager, '_init_sendgrid', return_value=None):
            manager = AlertManager(config)
            # Manually set clients for testing
            manager.twilio_client = Mock()
            manager.sendgrid_client = Mock()
            manager.twilio_from_number = '+0987654321'
            manager.sendgrid_from_email = 'noreply@jutsu-labs.com'
            return manager


class TestSMSAlerts:
    """Test SMS alert functionality."""

    def test_send_sms_success(self, alert_manager_no_init):
        """Test successful SMS sending."""
        mock_message = Mock()
        mock_message.sid = 'SM123456'
        alert_manager_no_init.twilio_client.messages.create.return_value = mock_message

        result = alert_manager_no_init.send_sms("Test alert message")

        assert result is True
        alert_manager_no_init.twilio_client.messages.create.assert_called_once()

    def test_send_sms_disabled(self, config):
        """Test SMS sending when disabled."""
        config['alerts']['sms_enabled'] = False

        with patch.object(AlertManager, '_init_twilio', return_value=None):
            with patch.object(AlertManager, '_init_sendgrid', return_value=None):
                manager = AlertManager(config)
                result = manager.send_sms("Test message")

                assert result is False

    def test_send_sms_truncates_long_message(self, alert_manager_no_init):
        """Test SMS message truncation for long messages."""
        long_message = "A" * 200  # Exceeds 160 character limit

        mock_message = Mock()
        mock_message.sid = 'SM123456'
        alert_manager_no_init.twilio_client.messages.create.return_value = mock_message

        result = alert_manager_no_init.send_sms(long_message)

        # Verify message was truncated
        call_args = alert_manager_no_init.twilio_client.messages.create.call_args
        sent_message = call_args[1]['body']
        assert len(sent_message) <= 160
        assert result is True

    def test_send_sms_failure(self, alert_manager_no_init):
        """Test SMS sending failure."""
        alert_manager_no_init.twilio_client.messages.create.side_effect = Exception("API error")

        result = alert_manager_no_init.send_sms("Test message")

        assert result is False


class TestEmailAlerts:
    """Test email alert functionality."""

    def test_send_email_success(self, alert_manager_no_init):
        """Test successful email sending."""
        mock_response = Mock()
        mock_response.status_code = 202
        alert_manager_no_init.sendgrid_client.send.return_value = mock_response

        result = alert_manager_no_init.send_email(
            "Test Subject",
            "Test email body"
        )

        assert result is True
        alert_manager_no_init.sendgrid_client.send.assert_called_once()

    def test_send_email_disabled(self, config):
        """Test email sending when disabled."""
        config['alerts']['email_enabled'] = False

        with patch.object(AlertManager, '_init_twilio', return_value=None):
            with patch.object(AlertManager, '_init_sendgrid', return_value=None):
                manager = AlertManager(config)
                result = manager.send_email("Subject", "Body")

                assert result is False

    def test_send_email_failure(self, alert_manager_no_init):
        """Test email sending failure."""
        mock_response = Mock()
        mock_response.status_code = 500  # Server error
        alert_manager_no_init.sendgrid_client.send.return_value = mock_response

        result = alert_manager_no_init.send_email("Subject", "Body")

        assert result is False


class TestCriticalAlerts:
    """Test critical alert functionality."""

    def test_send_critical_alert_both_channels(self, alert_manager_no_init):
        """Test critical alert sends via both SMS and Email."""
        # Mock successful SMS
        mock_sms = Mock()
        mock_sms.sid = 'SM123456'
        alert_manager_no_init.twilio_client.messages.create.return_value = mock_sms

        # Mock successful email
        mock_email_response = Mock()
        mock_email_response.status_code = 202
        alert_manager_no_init.sendgrid_client.send.return_value = mock_email_response

        alert_manager_no_init.send_critical_alert(
            "Authentication failure",
            "OAuth token expired"
        )

        # Verify both channels were called
        alert_manager_no_init.twilio_client.messages.create.assert_called_once()
        alert_manager_no_init.sendgrid_client.send.assert_called_once()

    def test_send_critical_alert_without_context(self, alert_manager_no_init):
        """Test critical alert without context."""
        mock_sms = Mock()
        mock_sms.sid = 'SM123456'
        alert_manager_no_init.twilio_client.messages.create.return_value = mock_sms

        mock_email_response = Mock()
        mock_email_response.status_code = 202
        alert_manager_no_init.sendgrid_client.send.return_value = mock_email_response

        alert_manager_no_init.send_critical_alert("Critical error")

        # Should still send alerts
        alert_manager_no_init.twilio_client.messages.create.assert_called_once()
        alert_manager_no_init.sendgrid_client.send.assert_called_once()


class TestWarningAlerts:
    """Test warning alert functionality."""

    def test_send_warning_email_only(self, alert_manager_no_init):
        """Test warning sends via email only (not SMS)."""
        mock_email_response = Mock()
        mock_email_response.status_code = 202
        alert_manager_no_init.sendgrid_client.send.return_value = mock_email_response

        alert_manager_no_init.send_warning(
            "Moderate slippage detected",
            "TQQQ: 0.4% slippage"
        )

        # Email should be sent
        alert_manager_no_init.sendgrid_client.send.assert_called_once()

        # SMS should NOT be sent
        alert_manager_no_init.twilio_client.messages.create.assert_not_called()


class TestInfoLogging:
    """Test info logging functionality."""

    def test_send_info_logs_only(self, alert_manager_no_init):
        """Test info message logs but doesn't send alerts."""
        alert_manager_no_init.send_info("Execution completed successfully")

        # No alerts should be sent
        alert_manager_no_init.twilio_client.messages.create.assert_not_called()
        alert_manager_no_init.sendgrid_client.send.assert_not_called()


class TestInitialization:
    """Test client initialization."""

    @patch.dict(os.environ, {
        'TWILIO_ACCOUNT_SID': 'AC123',
        'TWILIO_AUTH_TOKEN': 'token123',
        'TWILIO_FROM_NUMBER': '+1111111111'
    })
    @patch('jutsu_engine.live.alert_manager.Client')
    def test_init_twilio_success(self, mock_twilio_class, config):
        """Test successful Twilio initialization."""
        mock_twilio_client = Mock()
        mock_twilio_class.return_value = mock_twilio_client

        with patch.object(AlertManager, '_init_sendgrid', return_value=None):
            manager = AlertManager(config)

            # Verify Twilio client was created
            mock_twilio_class.assert_called_once_with('AC123', 'token123')
            assert manager.twilio_client is not None

    @patch.dict(os.environ, {'SENDGRID_API_KEY': 'SG.test_key'})
    @patch('jutsu_engine.live.alert_manager.SendGridAPIClient')
    def test_init_sendgrid_success(self, mock_sendgrid_class, config):
        """Test successful SendGrid initialization."""
        mock_sendgrid_client = Mock()
        mock_sendgrid_class.return_value = mock_sendgrid_client

        with patch.object(AlertManager, '_init_twilio', return_value=None):
            manager = AlertManager(config)

            # Verify SendGrid client was created
            mock_sendgrid_class.assert_called_once_with('SG.test_key')
            assert manager.sendgrid_client is not None

    def test_init_missing_credentials(self, config):
        """Test initialization with missing credentials disables alerts."""
        # No environment variables set
        with patch.dict(os.environ, {}, clear=True):
            manager = AlertManager(config)

            # Both should be disabled due to missing credentials
            assert manager.sms_enabled is False
            assert manager.email_enabled is False
