"""
Security event logging for audit trails and monitoring.

Provides structured logging for security-relevant events:
- Authentication events (login, logout, failures)
- Token operations (create, refresh, revoke)
- OAuth events (Schwab auth flows)
- Access control events (unauthorized access attempts)

Usage:
    from jutsu_engine.utils.security_logger import security_logger, SecurityEvent

    security_logger.log_login_success(username, ip_address)
    security_logger.log_login_failure(username, ip_address, reason)
    security_logger.log_token_created(username, token_type)
"""

import logging
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict


class SecurityEventType(str, Enum):
    """Types of security events for categorization and filtering."""
    # Authentication events
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"

    # Token events
    TOKEN_CREATED = "TOKEN_CREATED"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    TOKEN_INVALID = "TOKEN_INVALID"

    # OAuth events (Schwab)
    OAUTH_INITIATED = "OAUTH_INITIATED"
    OAUTH_COMPLETED = "OAUTH_COMPLETED"
    OAUTH_FAILED = "OAUTH_FAILED"
    OAUTH_TOKEN_DELETED = "OAUTH_TOKEN_DELETED"

    # Access control events
    ACCESS_DENIED = "ACCESS_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"

    # 2FA events
    TWO_FA_ENABLED = "2FA_ENABLED"
    TWO_FA_DISABLED = "2FA_DISABLED"
    TWO_FA_SUCCESS = "2FA_SUCCESS"
    TWO_FA_FAILURE = "2FA_FAILURE"

    # Passkey/WebAuthn events
    PASSKEY_REGISTERED = "PASSKEY_REGISTERED"
    PASSKEY_AUTHENTICATED = "PASSKEY_AUTHENTICATED"
    PASSKEY_REVOKED = "PASSKEY_REVOKED"
    PASSKEY_AUTH_FAILED = "PASSKEY_AUTH_FAILED"


class SecuritySeverity(str, Enum):
    """Severity levels for security events."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class SecurityEvent:
    """Structured security event for logging and analysis."""
    event_type: SecurityEventType
    severity: SecuritySeverity
    timestamp: str
    username: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        d = asdict(self)
        d['event_type'] = self.event_type.value
        d['severity'] = self.severity.value
        return d

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict())


class SecurityLogger:
    """
    Security event logger for audit trails.

    Logs security events in structured JSON format for easy parsing
    and integration with log aggregation systems (ELK, Splunk, etc.).
    """

    def __init__(self, logger_name: str = 'SECURITY'):
        """Initialize security logger with dedicated logger instance."""
        self.logger = logging.getLogger(logger_name)

    def _get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _log_event(self, event: SecurityEvent) -> None:
        """Log a security event at appropriate level."""
        log_message = f"[{event.event_type.value}] {event.to_json()}"

        if event.severity == SecuritySeverity.CRITICAL:
            self.logger.critical(log_message)
        elif event.severity == SecuritySeverity.WARNING:
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)

    # Authentication events
    def log_login_success(
        self,
        username: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> None:
        """Log successful login event."""
        event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            user_agent=user_agent
        )
        self._log_event(event)

    def log_login_failure(
        self,
        username: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Log failed login attempt."""
        event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILURE,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"reason": reason} if reason else None
        )
        self._log_event(event)

    def log_logout(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> None:
        """Log logout event."""
        event = SecurityEvent(
            event_type=SecurityEventType.LOGOUT,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address
        )
        self._log_event(event)

    # Token events
    def log_token_created(
        self,
        username: str,
        token_type: str = "access",
        ip_address: Optional[str] = None
    ) -> None:
        """Log token creation event."""
        event = SecurityEvent(
            event_type=SecurityEventType.TOKEN_CREATED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"token_type": token_type}
        )
        self._log_event(event)

    def log_token_refreshed(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> None:
        """Log token refresh event."""
        event = SecurityEvent(
            event_type=SecurityEventType.TOKEN_REFRESHED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address
        )
        self._log_event(event)

    def log_token_invalid(
        self,
        ip_address: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Log invalid token attempt."""
        event = SecurityEvent(
            event_type=SecurityEventType.TOKEN_INVALID,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            ip_address=ip_address,
            details={"reason": reason} if reason else None
        )
        self._log_event(event)

    # OAuth events
    def log_oauth_initiated(
        self,
        provider: str = "schwab",
        ip_address: Optional[str] = None
    ) -> None:
        """Log OAuth flow initiation."""
        event = SecurityEvent(
            event_type=SecurityEventType.OAUTH_INITIATED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            ip_address=ip_address,
            details={"provider": provider}
        )
        self._log_event(event)

    def log_oauth_completed(
        self,
        provider: str = "schwab",
        ip_address: Optional[str] = None
    ) -> None:
        """Log successful OAuth completion."""
        event = SecurityEvent(
            event_type=SecurityEventType.OAUTH_COMPLETED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            ip_address=ip_address,
            details={"provider": provider}
        )
        self._log_event(event)

    def log_oauth_failed(
        self,
        provider: str = "schwab",
        ip_address: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Log OAuth failure."""
        event = SecurityEvent(
            event_type=SecurityEventType.OAUTH_FAILED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            ip_address=ip_address,
            details={"provider": provider, "reason": reason}
        )
        self._log_event(event)

    def log_oauth_token_deleted(
        self,
        provider: str = "schwab",
        username: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """Log OAuth token deletion."""
        event = SecurityEvent(
            event_type=SecurityEventType.OAUTH_TOKEN_DELETED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"provider": provider}
        )
        self._log_event(event)

    # Access control events
    def log_access_denied(
        self,
        resource: str,
        username: Optional[str] = None,
        ip_address: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Log access denied event."""
        event = SecurityEvent(
            event_type=SecurityEventType.ACCESS_DENIED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"resource": resource, "reason": reason}
        )
        self._log_event(event)

    def log_rate_limited(
        self,
        endpoint: str,
        ip_address: Optional[str] = None,
        username: Optional[str] = None
    ) -> None:
        """Log rate limiting event."""
        event = SecurityEvent(
            event_type=SecurityEventType.RATE_LIMITED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"endpoint": endpoint}
        )
        self._log_event(event)

    def log_suspicious_activity(
        self,
        activity_type: str,
        ip_address: Optional[str] = None,
        username: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log suspicious activity for review."""
        event = SecurityEvent(
            event_type=SecurityEventType.SUSPICIOUS_ACTIVITY,
            severity=SecuritySeverity.CRITICAL,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"activity_type": activity_type, **(details or {})}
        )
        self._log_event(event)

    # 2FA events
    def log_2fa_enabled(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> None:
        """Log 2FA enablement."""
        event = SecurityEvent(
            event_type=SecurityEventType.TWO_FA_ENABLED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address
        )
        self._log_event(event)

    def log_2fa_disabled(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> None:
        """Log 2FA disablement."""
        event = SecurityEvent(
            event_type=SecurityEventType.TWO_FA_DISABLED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address
        )
        self._log_event(event)

    def log_2fa_success(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> None:
        """Log successful 2FA verification."""
        event = SecurityEvent(
            event_type=SecurityEventType.TWO_FA_SUCCESS,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address
        )
        self._log_event(event)

    def log_2fa_failure(
        self,
        username: str,
        ip_address: Optional[str] = None,
        attempt_count: Optional[int] = None
    ) -> None:
        """Log failed 2FA attempt."""
        event = SecurityEvent(
            event_type=SecurityEventType.TWO_FA_FAILURE,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"attempt_count": attempt_count} if attempt_count else None
        )
        self._log_event(event)

    # Passkey/WebAuthn events
    def log_passkey_registered(
        self,
        username: str,
        device_name: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """Log passkey registration."""
        event = SecurityEvent(
            event_type=SecurityEventType.PASSKEY_REGISTERED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"device_name": device_name} if device_name else None
        )
        self._log_event(event)

    def log_passkey_authenticated(
        self,
        username: str,
        device_name: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """Log successful passkey authentication."""
        event = SecurityEvent(
            event_type=SecurityEventType.PASSKEY_AUTHENTICATED,
            severity=SecuritySeverity.INFO,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"device_name": device_name} if device_name else None
        )
        self._log_event(event)

    def log_passkey_revoked(
        self,
        username: str,
        device_name: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """Log passkey revocation."""
        event = SecurityEvent(
            event_type=SecurityEventType.PASSKEY_REVOKED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"device_name": device_name} if device_name else None
        )
        self._log_event(event)

    def log_passkey_auth_failed(
        self,
        username: str,
        ip_address: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Log failed passkey authentication attempt."""
        event = SecurityEvent(
            event_type=SecurityEventType.PASSKEY_AUTH_FAILED,
            severity=SecuritySeverity.WARNING,
            timestamp=self._get_timestamp(),
            username=username,
            ip_address=ip_address,
            details={"reason": reason} if reason else None
        )
        self._log_event(event)


# Global security logger instance
security_logger = SecurityLogger()

# Module-level constants for passkey security events (for easy imports)
PASSKEY_REGISTERED = "passkey_registered"
PASSKEY_AUTHENTICATED = "passkey_authenticated"
PASSKEY_REVOKED = "passkey_revoked"
PASSKEY_AUTH_FAILED = "passkey_auth_failed"


def get_client_ip(request) -> Optional[str]:
    """
    Extract client IP address from request, handling proxies.

    Checks X-Forwarded-For header for proxied requests (Cloudflare, nginx).
    Falls back to client.host for direct connections.

    Args:
        request: FastAPI Request object

    Returns:
        Client IP address or None
    """
    # Check for Cloudflare's real IP header
    cf_connecting_ip = request.headers.get('CF-Connecting-IP')
    if cf_connecting_ip:
        return cf_connecting_ip

    # Check X-Forwarded-For (may contain multiple IPs)
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        # First IP is the original client
        return x_forwarded_for.split(',')[0].strip()

    # Check X-Real-IP (nginx)
    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip:
        return x_real_ip

    # Fall back to direct connection IP
    if hasattr(request, 'client') and request.client:
        return request.client.host

    return None
