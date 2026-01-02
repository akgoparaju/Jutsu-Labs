"""
Notification utilities for Jutsu Labs.

Provides webhook-based notifications for:
- Schwab token expiration warnings
- System alerts and recovery notifications
- Trading activity summaries

Supports:
- Slack webhooks
- Discord webhooks
- Generic webhook endpoints

Configuration via environment variables:
- NOTIFICATION_WEBHOOK_URL: Primary webhook URL
- NOTIFICATION_WEBHOOK_TYPE: 'slack', 'discord', or 'generic' (default: auto-detect)
- NOTIFICATION_ENABLED: 'true' to enable (default: 'true' if webhook URL set)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum

import httpx

logger = logging.getLogger('NOTIFICATIONS')


class WebhookType(Enum):
    """Supported webhook types."""
    SLACK = 'slack'
    DISCORD = 'discord'
    GENERIC = 'generic'


class NotificationLevel(Enum):
    """Notification severity levels."""
    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'


def _detect_webhook_type(url: str) -> WebhookType:
    """Auto-detect webhook type from URL."""
    if 'hooks.slack.com' in url:
        return WebhookType.SLACK
    elif 'discord.com/api/webhooks' in url or 'discordapp.com/api/webhooks' in url:
        return WebhookType.DISCORD
    else:
        return WebhookType.GENERIC


def _format_slack_message(
    title: str,
    message: str,
    level: NotificationLevel,
    fields: Optional[Dict[str, str]] = None,
    action_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Format message for Slack webhook."""
    color_map = {
        NotificationLevel.INFO: '#36a64f',      # Green
        NotificationLevel.WARNING: '#ffcc00',   # Yellow
        NotificationLevel.CRITICAL: '#ff0000',  # Red
    }
    
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": title,
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message
            }
        }
    ]
    
    if fields:
        field_blocks = []
        for key, value in fields.items():
            field_blocks.append({
                "type": "mrkdwn",
                "text": f"*{key}:*\n{value}"
            })
        blocks.append({
            "type": "section",
            "fields": field_blocks[:10]  # Slack limit
        })
    
    if action_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Re-authenticate Now",
                        "emoji": True
                    },
                    "url": action_url,
                    "style": "primary"
                }
            ]
        })
    
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Sent by Jutsu Labs at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            }
        ]
    })
    
    return {
        "attachments": [
            {
                "color": color_map.get(level, '#808080'),
                "blocks": blocks
            }
        ]
    }


def _format_discord_message(
    title: str,
    message: str,
    level: NotificationLevel,
    fields: Optional[Dict[str, str]] = None,
    action_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Format message for Discord webhook."""
    color_map = {
        NotificationLevel.INFO: 0x36a64f,      # Green
        NotificationLevel.WARNING: 0xffcc00,   # Yellow
        NotificationLevel.CRITICAL: 0xff0000,  # Red
    }
    
    embed = {
        "title": title,
        "description": message,
        "color": color_map.get(level, 0x808080),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": "Jutsu Labs"
        }
    }
    
    if fields:
        embed["fields"] = [
            {"name": key, "value": value, "inline": True}
            for key, value in list(fields.items())[:25]  # Discord limit
        ]
    
    if action_url:
        embed["url"] = action_url
    
    return {
        "embeds": [embed]
    }


def _format_generic_message(
    title: str,
    message: str,
    level: NotificationLevel,
    fields: Optional[Dict[str, str]] = None,
    action_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Format message for generic webhook."""
    return {
        "title": title,
        "message": message,
        "level": level.value,
        "fields": fields or {},
        "action_url": action_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "jutsu-labs"
    }


class WebhookNotifier:
    """
    Webhook-based notification sender.
    
    Usage:
        notifier = WebhookNotifier()
        notifier.send(
            title="Token Expiration Warning",
            message="Your Schwab token expires in 2 days",
            level=NotificationLevel.WARNING
        )
    """
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        webhook_type: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        """
        Initialize webhook notifier.
        
        Args:
            webhook_url: Webhook URL (or use NOTIFICATION_WEBHOOK_URL env var)
            webhook_type: 'slack', 'discord', or 'generic' (auto-detected if not set)
            enabled: Enable/disable notifications (default: True if URL set)
        """
        self.webhook_url = webhook_url or os.getenv('NOTIFICATION_WEBHOOK_URL', '')
        
        if webhook_type:
            self.webhook_type = WebhookType(webhook_type)
        elif os.getenv('NOTIFICATION_WEBHOOK_TYPE'):
            self.webhook_type = WebhookType(os.getenv('NOTIFICATION_WEBHOOK_TYPE'))
        elif self.webhook_url:
            self.webhook_type = _detect_webhook_type(self.webhook_url)
        else:
            self.webhook_type = WebhookType.GENERIC
        
        if enabled is not None:
            self.enabled = enabled
        else:
            env_enabled = os.getenv('NOTIFICATION_ENABLED', '').lower()
            if env_enabled in ('true', '1', 'yes'):
                self.enabled = True
            elif env_enabled in ('false', '0', 'no'):
                self.enabled = False
            else:
                # Default: enabled if webhook URL is set
                self.enabled = bool(self.webhook_url)
        
        if self.enabled and self.webhook_url:
            logger.info(f"Webhook notifications enabled ({self.webhook_type.value})")
        elif self.enabled:
            logger.warning("Notifications enabled but no webhook URL configured")
    
    def send(
        self,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        fields: Optional[Dict[str, str]] = None,
        action_url: Optional[str] = None,
    ) -> bool:
        """
        Send a notification via webhook.
        
        Args:
            title: Notification title
            message: Main message body
            level: Severity level (INFO, WARNING, CRITICAL)
            fields: Optional key-value pairs for additional info
            action_url: Optional URL for action button
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled or not self.webhook_url:
            logger.debug(f"Notification skipped (disabled): {title}")
            return False
        
        # Format message based on webhook type
        if self.webhook_type == WebhookType.SLACK:
            payload = _format_slack_message(title, message, level, fields, action_url)
        elif self.webhook_type == WebhookType.DISCORD:
            payload = _format_discord_message(title, message, level, fields, action_url)
        else:
            payload = _format_generic_message(title, message, level, fields, action_url)
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    self.webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                )
                response.raise_for_status()
            
            logger.info(f"Notification sent: {title}")
            return True
            
        except httpx.HTTPError as e:
            logger.error(f"Failed to send notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Notification error: {e}")
            return False


# Singleton instance
_notifier: Optional[WebhookNotifier] = None


def get_notifier() -> WebhookNotifier:
    """Get the singleton notifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = WebhookNotifier()
    return _notifier


def send_token_expiration_warning(
    expires_in_days: float,
    dashboard_url: Optional[str] = None,
) -> bool:
    """
    Send a Schwab token expiration warning notification.
    
    Args:
        expires_in_days: Days until token expires
        dashboard_url: URL to dashboard config page for re-auth
        
    Returns:
        True if notification sent successfully
    """
    notifier = get_notifier()
    
    # Determine severity and message
    if expires_in_days <= 0.5:  # 12 hours
        level = NotificationLevel.CRITICAL
        emoji = "🚨"
        urgency = "URGENT"
    elif expires_in_days <= 1:
        level = NotificationLevel.CRITICAL
        emoji = "⚠️"
        urgency = "CRITICAL"
    elif expires_in_days <= 2:
        level = NotificationLevel.WARNING
        emoji = "⏰"
        urgency = "WARNING"
    else:
        level = NotificationLevel.INFO
        emoji = "ℹ️"
        urgency = "NOTICE"
    
    # Format time remaining
    if expires_in_days < 1:
        hours = int(expires_in_days * 24)
        time_remaining = f"{hours} hours"
    else:
        time_remaining = f"{expires_in_days:.1f} days"
    
    title = f"{emoji} Schwab Token Expiration {urgency}"
    message = (
        f"Your Schwab API token will expire in *{time_remaining}*.\n\n"
        "After expiration, trading and data sync will fail. "
        "Please re-authenticate via the dashboard before the token expires."
    )
    
    fields = {
        "Time Remaining": time_remaining,
        "Action Required": "Re-authenticate via Dashboard",
    }
    
    # Construct action URL
    action_url = dashboard_url
    if not action_url:
        # Try to construct from environment
        api_base = os.getenv('DASHBOARD_URL', os.getenv('API_BASE_URL', ''))
        if api_base:
            action_url = f"{api_base.rstrip('/')}/config"
    
    return notifier.send(
        title=title,
        message=message,
        level=level,
        fields=fields,
        action_url=action_url,
    )


def send_token_expired_alert() -> bool:
    """Send alert that token has already expired."""
    notifier = get_notifier()
    
    dashboard_url = os.getenv('DASHBOARD_URL', os.getenv('API_BASE_URL', ''))
    if dashboard_url:
        dashboard_url = f"{dashboard_url.rstrip('/')}/config"
    
    return notifier.send(
        title="🔴 Schwab Token EXPIRED",
        message=(
            "Your Schwab API token has *expired*.\n\n"
            "Trading and data sync are currently *disabled*. "
            "Please re-authenticate immediately to restore functionality."
        ),
        level=NotificationLevel.CRITICAL,
        fields={
            "Status": "EXPIRED",
            "Impact": "Trading & Data Sync Disabled",
            "Action": "Re-authenticate NOW",
        },
        action_url=dashboard_url,
    )
