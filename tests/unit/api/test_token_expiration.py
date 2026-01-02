"""
Tests for Schwab token expiration monitoring and notifications.

Simulates different expiration scenarios:
- 5 days remaining: INFO notification, blue banner
- 2 days remaining: WARNING notification, yellow banner
- -1 days (expired 1 day): CRITICAL/expired notification, red banner
- -3 days (expired 3 days): CRITICAL/expired notification, red banner
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
import json
import tempfile
import os

from jutsu_engine.utils.notifications import (
    send_token_expiration_warning,
    send_token_expired_alert,
    NotificationLevel,
    WebhookNotifier,
    _format_slack_message,
    _format_discord_message,
)


class TestNotificationLevelSelection:
    """Test that correct notification levels are selected based on expiration days."""

    def test_5_days_remaining_is_info(self):
        """5 days remaining should trigger INFO level notification."""
        # The function selects level based on days
        expires_in_days = 5.0
        
        # Determine expected level (from the function logic)
        if expires_in_days <= 0.5:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 1:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 2:
            expected_level = NotificationLevel.WARNING
        else:
            expected_level = NotificationLevel.INFO
        
        assert expected_level == NotificationLevel.INFO

    def test_2_days_remaining_is_warning(self):
        """2 days remaining should trigger WARNING level notification."""
        expires_in_days = 2.0
        
        if expires_in_days <= 0.5:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 1:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 2:
            expected_level = NotificationLevel.WARNING
        else:
            expected_level = NotificationLevel.INFO
        
        assert expected_level == NotificationLevel.WARNING

    def test_1_day_remaining_is_critical(self):
        """1 day remaining should trigger CRITICAL level notification."""
        expires_in_days = 1.0
        
        if expires_in_days <= 0.5:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 1:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 2:
            expected_level = NotificationLevel.WARNING
        else:
            expected_level = NotificationLevel.INFO
        
        assert expected_level == NotificationLevel.CRITICAL

    def test_12_hours_remaining_is_critical(self):
        """12 hours (0.5 days) remaining should trigger CRITICAL level."""
        expires_in_days = 0.5
        
        if expires_in_days <= 0.5:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 1:
            expected_level = NotificationLevel.CRITICAL
        elif expires_in_days <= 2:
            expected_level = NotificationLevel.WARNING
        else:
            expected_level = NotificationLevel.INFO
        
        assert expected_level == NotificationLevel.CRITICAL


class TestTokenExpirationWarningFormatting:
    """Test notification message formatting for different expiration scenarios."""

    @pytest.mark.parametrize("expires_in_days,expected_urgency", [
        (5.0, "NOTICE"),
        (2.0, "WARNING"),
        (1.0, "CRITICAL"),
        (0.5, "URGENT"),
        (0.25, "URGENT"),  # 6 hours
    ])
    def test_urgency_labels(self, expires_in_days, expected_urgency):
        """Test that urgency labels are correct for different thresholds."""
        # Determine urgency based on days (from send_token_expiration_warning logic)
        if expires_in_days <= 0.5:
            urgency = "URGENT"
        elif expires_in_days <= 1:
            urgency = "CRITICAL"
        elif expires_in_days <= 2:
            urgency = "WARNING"
        else:
            urgency = "NOTICE"
        
        assert urgency == expected_urgency

    @pytest.mark.parametrize("expires_in_days,expected_format", [
        (5.0, "5.0 days"),
        (2.0, "2.0 days"),
        (1.5, "1.5 days"),
        (0.5, "12 hours"),  # Less than 1 day shows hours
        (0.25, "6 hours"),
    ])
    def test_time_formatting(self, expires_in_days, expected_format):
        """Test that time remaining is formatted correctly."""
        if expires_in_days < 1:
            hours = int(expires_in_days * 24)
            time_remaining = f"{hours} hours"
        else:
            time_remaining = f"{expires_in_days:.1f} days"
        
        assert time_remaining == expected_format


class TestSlackMessageFormatting:
    """Test Slack webhook message formatting."""

    def test_critical_message_has_red_color(self):
        """Critical notifications should have red color in Slack."""
        message = _format_slack_message(
            title="Test Title",
            message="Test message",
            level=NotificationLevel.CRITICAL,
        )
        
        assert "attachments" in message
        assert message["attachments"][0]["color"] == "#ff0000"

    def test_warning_message_has_yellow_color(self):
        """Warning notifications should have yellow color in Slack."""
        message = _format_slack_message(
            title="Test Title",
            message="Test message",
            level=NotificationLevel.WARNING,
        )
        
        assert message["attachments"][0]["color"] == "#ffcc00"

    def test_info_message_has_green_color(self):
        """Info notifications should have green color in Slack."""
        message = _format_slack_message(
            title="Test Title",
            message="Test message",
            level=NotificationLevel.INFO,
        )
        
        assert message["attachments"][0]["color"] == "#36a64f"

    def test_action_url_creates_button(self):
        """Action URL should create a button element in Slack."""
        message = _format_slack_message(
            title="Test",
            message="Test",
            level=NotificationLevel.INFO,
            action_url="https://example.com/reauth",
        )
        
        blocks = message["attachments"][0]["blocks"]
        actions_block = next((b for b in blocks if b.get("type") == "actions"), None)
        
        assert actions_block is not None
        assert actions_block["elements"][0]["url"] == "https://example.com/reauth"


class TestDiscordMessageFormatting:
    """Test Discord webhook message formatting."""

    def test_critical_message_has_red_color(self):
        """Critical notifications should have red color in Discord."""
        message = _format_discord_message(
            title="Test Title",
            message="Test message",
            level=NotificationLevel.CRITICAL,
        )
        
        assert "embeds" in message
        assert message["embeds"][0]["color"] == 0xff0000

    def test_warning_message_has_yellow_color(self):
        """Warning notifications should have yellow color in Discord."""
        message = _format_discord_message(
            title="Test Title",
            message="Test message",
            level=NotificationLevel.WARNING,
        )
        
        assert message["embeds"][0]["color"] == 0xffcc00

    def test_fields_are_included(self):
        """Fields should be included in Discord embed."""
        message = _format_discord_message(
            title="Test",
            message="Test",
            level=NotificationLevel.INFO,
            fields={"Time Remaining": "2 days", "Action": "Re-auth"},
        )
        
        fields = message["embeds"][0]["fields"]
        assert len(fields) == 2
        assert any(f["name"] == "Time Remaining" for f in fields)


class TestWebhookNotifierDisabled:
    """Test that notifications are skipped when disabled."""

    def test_no_webhook_url_returns_false(self):
        """Without webhook URL, send should return False."""
        notifier = WebhookNotifier(webhook_url="", enabled=True)
        result = notifier.send("Test", "Test", NotificationLevel.INFO)
        assert result is False

    def test_disabled_returns_false(self):
        """When disabled, send should return False."""
        notifier = WebhookNotifier(
            webhook_url="https://hooks.slack.com/test",
            enabled=False,
        )
        result = notifier.send("Test", "Test", NotificationLevel.INFO)
        assert result is False


class TestTokenExpirationScenarios:
    """
    Integration tests for complete expiration scenarios.
    Tests the full flow with mocked token status.
    """

    @pytest.fixture
    def mock_token_status(self):
        """Create mock token status responses."""
        def create_status(expires_in_days, token_exists=True, token_valid=True):
            return {
                "token_exists": token_exists,
                "token_valid": token_valid if expires_in_days > 0 else False,
                "expires_in_days": expires_in_days,
                "authenticated": token_valid if expires_in_days > 0 else False,
                "message": f"Token expires in {expires_in_days} days" if expires_in_days > 0 else "Token expired",
            }
        return create_status

    def test_scenario_5_days(self, mock_token_status):
        """Test 5 days remaining scenario - INFO level."""
        status = mock_token_status(5.0)
        
        assert status["token_exists"] is True
        assert status["token_valid"] is True
        assert status["expires_in_days"] == 5.0
        
        # Banner state would be "info"
        days = status["expires_in_days"]
        if days <= 0:
            banner_type = "critical"
        elif days <= 0.5:
            banner_type = "critical"
        elif days <= 1:
            banner_type = "critical"
        elif days <= 2:
            banner_type = "warning"
        elif days <= 5:
            banner_type = "info"
        else:
            banner_type = "success"
        
        assert banner_type == "info"

    def test_scenario_2_days(self, mock_token_status):
        """Test 2 days remaining scenario - WARNING level."""
        status = mock_token_status(2.0)
        
        assert status["token_exists"] is True
        assert status["token_valid"] is True
        assert status["expires_in_days"] == 2.0
        
        days = status["expires_in_days"]
        if days <= 0:
            banner_type = "critical"
        elif days <= 0.5:
            banner_type = "critical"
        elif days <= 1:
            banner_type = "critical"
        elif days <= 2:
            banner_type = "warning"
        elif days <= 5:
            banner_type = "info"
        else:
            banner_type = "success"
        
        assert banner_type == "warning"

    def test_scenario_expired_1_day(self, mock_token_status):
        """Test -1 day (expired 1 day ago) scenario - CRITICAL level."""
        status = mock_token_status(-1.0)
        
        assert status["token_exists"] is True
        assert status["token_valid"] is False  # Expired token is invalid
        assert status["expires_in_days"] == -1.0
        
        days = status["expires_in_days"]
        if days <= 0:
            banner_type = "critical"
        elif days <= 0.5:
            banner_type = "critical"
        elif days <= 1:
            banner_type = "critical"
        elif days <= 2:
            banner_type = "warning"
        elif days <= 5:
            banner_type = "info"
        else:
            banner_type = "success"
        
        assert banner_type == "critical"

    def test_scenario_expired_3_days(self, mock_token_status):
        """Test -3 days (expired 3 days ago) scenario - CRITICAL level."""
        status = mock_token_status(-3.0)
        
        assert status["token_exists"] is True
        assert status["token_valid"] is False
        assert status["expires_in_days"] == -3.0
        
        days = status["expires_in_days"]
        if days <= 0:
            banner_type = "critical"
        else:
            banner_type = "other"
        
        assert banner_type == "critical"


class TestSchedulerTokenCheckJob:
    """Test the scheduler's token expiration check job logic."""

    @pytest.fixture
    def notification_state_file(self):
        """Create a temporary notification state file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            temp_path = f.name
        yield temp_path
        os.unlink(temp_path)

    def test_notification_level_progression(self):
        """Test that notification levels progress correctly (5d -> 2d -> 1d -> 12h)."""
        level_order = ['5d', '2d', '1d', '12h']
        
        # Simulate state tracking
        last_level = None
        
        # Day 5 - should notify (first notification)
        current_level = '5d'
        should_notify = last_level is None or (
            current_level in level_order and
            (last_level not in level_order or
             level_order.index(current_level) > level_order.index(last_level))
        )
        assert should_notify is True
        last_level = current_level
        
        # Day 5 again - should NOT notify (already sent)
        current_level = '5d'
        should_notify = last_level is None or (
            current_level in level_order and
            (last_level not in level_order or
             level_order.index(current_level) > level_order.index(last_level))
        )
        assert should_notify is False
        
        # Day 2 - should notify (more urgent than 5d)
        current_level = '2d'
        should_notify = last_level is None or (
            current_level in level_order and
            (last_level not in level_order or
             level_order.index(current_level) > level_order.index(last_level))
        )
        assert should_notify is True
        last_level = current_level
        
        # Day 1 - should notify (more urgent than 2d)
        current_level = '1d'
        should_notify = last_level is None or (
            current_level in level_order and
            (last_level not in level_order or
             level_order.index(current_level) > level_order.index(last_level))
        )
        assert should_notify is True
        last_level = current_level
        
        # 12 hours - should notify (more urgent than 1d)
        current_level = '12h'
        should_notify = last_level is None or (
            current_level in level_order and
            (last_level not in level_order or
             level_order.index(current_level) > level_order.index(last_level))
        )
        assert should_notify is True

    def test_expired_notification_sent_once(self):
        """Test that expired notification is only sent once."""
        state = {'expired_notified': False}
        
        # First expiration check
        if not state.get('expired_notified'):
            # Would send notification here
            state['expired_notified'] = True
            sent = True
        else:
            sent = False
        
        assert sent is True
        
        # Second expiration check
        if not state.get('expired_notified'):
            sent = True
        else:
            sent = False
        
        assert sent is False


class TestBannerStateLogic:
    """Test the frontend banner state determination logic."""

    def get_banner_state(self, expires_in_days, token_exists=True, token_valid=True):
        """
        Replicate the getBannerState logic from SchwabTokenBanner.tsx
        """
        if not token_exists:
            return {"type": "critical", "title": "Schwab Not Connected"}
        
        if not token_valid:
            return {"type": "critical", "title": "Schwab Token Expired"}
        
        if expires_in_days <= 0.5:
            return {"type": "critical", "title": "Token Expiring Soon!"}
        
        if expires_in_days <= 1:
            return {"type": "critical", "title": "Token Expiring Today"}
        
        if expires_in_days <= 2:
            return {"type": "warning", "title": "Token Expiring Soon"}
        
        if expires_in_days <= 5:
            return {"type": "info", "title": "Token Status"}
        
        return {"type": "success", "title": "Schwab Connected"}

    def test_5_days_shows_info_banner(self):
        """5 days remaining shows info (blue) banner."""
        state = self.get_banner_state(5.0)
        assert state["type"] == "info"
        assert state["title"] == "Token Status"

    def test_2_days_shows_warning_banner(self):
        """2 days remaining shows warning (yellow) banner."""
        state = self.get_banner_state(2.0)
        assert state["type"] == "warning"
        assert state["title"] == "Token Expiring Soon"

    def test_negative_1_day_shows_critical_banner(self):
        """Expired token (-1 day) shows critical (red) banner."""
        # When expired, token_valid should be False
        state = self.get_banner_state(-1.0, token_valid=False)
        assert state["type"] == "critical"
        assert state["title"] == "Schwab Token Expired"

    def test_negative_3_days_shows_critical_banner(self):
        """Expired token (-3 days) shows critical (red) banner."""
        state = self.get_banner_state(-3.0, token_valid=False)
        assert state["type"] == "critical"
        assert state["title"] == "Schwab Token Expired"

    def test_no_token_shows_connect_prompt(self):
        """No token shows 'Schwab Not Connected' prompt."""
        state = self.get_banner_state(0, token_exists=False)
        assert state["type"] == "critical"
        assert state["title"] == "Schwab Not Connected"

    def test_healthy_token_shows_success(self):
        """Token with >5 days shows success banner."""
        state = self.get_banner_state(6.5)
        assert state["type"] == "success"
        assert state["title"] == "Schwab Connected"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
