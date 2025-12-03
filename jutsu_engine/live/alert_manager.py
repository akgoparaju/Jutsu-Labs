"""
Alert Manager - Send SMS and email alerts for critical events.

This module handles alert delivery via Twilio (SMS) and SendGrid (Email)
for critical trading failures and warnings.
"""

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger('LIVE.ALERTS')


class AlertManager:
    """
    Send SMS and email alerts for critical trading events.

    Supports:
    - SMS via Twilio (critical alerts only)
    - Email via SendGrid (critical + warnings)
    - Configurable enable/disable per channel
    """

    def __init__(self, config: Dict):
        """
        Initialize alert manager with configuration.

        Args:
            config: Configuration dictionary with alerts settings
                    Expected keys:
                        alerts.sms_enabled: Enable SMS alerts (bool)
                        alerts.email_enabled: Enable email alerts (bool)
                        alerts.sms_number: Phone number for SMS
                        alerts.email_address: Email for alerts
                        alerts.critical_conditions: List of critical event types
        """
        alert_config = config.get('alerts', {})

        self.sms_enabled = alert_config.get('sms_enabled', False)
        self.email_enabled = alert_config.get('email_enabled', True)
        self.sms_number = os.getenv('ALERT_SMS_NUMBER', alert_config.get('sms_number', ''))
        self.email_address = os.getenv('ALERT_EMAIL', alert_config.get('email_address', ''))
        self.critical_conditions = alert_config.get('critical_conditions', [])

        # Initialize Twilio client if SMS enabled
        self.twilio_client = None
        if self.sms_enabled:
            self.twilio_client = self._init_twilio()

        # Initialize SendGrid client if email enabled
        self.sendgrid_client = None
        if self.email_enabled:
            self.sendgrid_client = self._init_sendgrid()

        logger.info(
            f"AlertManager initialized: SMS={self.sms_enabled}, "
            f"Email={self.email_enabled}"
        )

    def _init_twilio(self) -> Optional[object]:
        """
        Initialize Twilio client for SMS.

        Returns:
            Twilio Client object or None if initialization fails
        """
        try:
            from twilio.rest import Client

            account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            from_number = os.getenv('TWILIO_FROM_NUMBER')

            if not all([account_sid, auth_token, from_number]):
                logger.warning(
                    "Twilio credentials missing in environment variables, "
                    "SMS alerts disabled"
                )
                self.sms_enabled = False
                return None

            client = Client(account_sid, auth_token)
            self.twilio_from_number = from_number

            logger.info("Twilio client initialized successfully")
            return client

        except ImportError:
            logger.warning("twilio library not installed, SMS alerts disabled")
            self.sms_enabled = False
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Twilio: {e}")
            self.sms_enabled = False
            return None

    def _init_sendgrid(self) -> Optional[object]:
        """
        Initialize SendGrid client for email.

        Returns:
            SendGrid API Client or None if initialization fails
        """
        try:
            from sendgrid import SendGridAPIClient

            api_key = os.getenv('SENDGRID_API_KEY')

            if not api_key:
                logger.warning(
                    "SendGrid API key missing in environment variables, "
                    "email alerts disabled"
                )
                self.email_enabled = False
                return None

            client = SendGridAPIClient(api_key)
            self.sendgrid_from_email = os.getenv(
                'SENDGRID_FROM_EMAIL',
                'noreply@jutsu-labs.com'
            )

            logger.info("SendGrid client initialized successfully")
            return client

        except ImportError:
            logger.warning("sendgrid library not installed, email alerts disabled")
            self.email_enabled = False
            return None
        except Exception as e:
            logger.error(f"Failed to initialize SendGrid: {e}")
            self.email_enabled = False
            return None

    def send_sms(self, message: str) -> bool:
        """
        Send SMS alert via Twilio.

        Args:
            message: Alert message (max 160 characters for single SMS)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.sms_enabled or not self.twilio_client:
            logger.debug("SMS not enabled or client not initialized")
            return False

        if not self.sms_number:
            logger.warning("SMS number not configured, cannot send SMS")
            return False

        try:
            # Truncate message if too long
            if len(message) > 160:
                message = message[:157] + "..."

            message_obj = self.twilio_client.messages.create(
                body=message,
                from_=self.twilio_from_number,
                to=self.sms_number
            )

            logger.info(f"SMS sent successfully: sid={message_obj.sid}")
            return True

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            return False

    def send_email(self, subject: str, body: str) -> bool:
        """
        Send email alert via SendGrid.

        Args:
            subject: Email subject line
            body: Email body (plain text)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.email_enabled or not self.sendgrid_client:
            logger.debug("Email not enabled or client not initialized")
            return False

        if not self.email_address:
            logger.warning("Email address not configured, cannot send email")
            return False

        try:
            from sendgrid.helpers.mail import Mail

            message = Mail(
                from_email=self.sendgrid_from_email,
                to_emails=self.email_address,
                subject=subject,
                plain_text_content=body
            )

            response = self.sendgrid_client.send(message)

            if response.status_code in [200, 201, 202]:
                logger.info(f"Email sent successfully: status={response.status_code}")
                return True
            else:
                logger.error(f"Email send failed: status={response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_critical_alert(self, error: str, context: Optional[str] = None) -> None:
        """
        Send critical alert via BOTH SMS and Email.

        Used for conditions that require immediate attention:
        - Authentication failures
        - Extreme slippage
        - Corporate actions
        - State corruption

        Args:
            error: Critical error description
            context: Additional context (optional)
        """
        timestamp = logger.handlers[0].formatter.formatTime(
            logging.LogRecord('', 0, '', 0, '', (), None)
        ) if logger.handlers else ''

        # SMS message (short)
        sms_msg = f"JUTSU CRITICAL: {error[:100]}"

        # Email message (detailed)
        email_subject = f"[JUTSU CRITICAL] {error[:50]}"
        email_body = f"""
CRITICAL ALERT - Jutsu Labs Live Trading

Timestamp: {timestamp}
Error: {error}

{f'Context: {context}' if context else ''}

Action Required: Investigate immediately and verify trading status.

---
This is an automated alert from Jutsu Labs live trading system.
        """

        logger.critical(f"CRITICAL ALERT: {error}")

        # Send SMS
        sms_sent = self.send_sms(sms_msg)

        # Send Email
        email_sent = self.send_email(email_subject, email_body.strip())

        if sms_sent or email_sent:
            logger.info(
                f"Critical alert sent: SMS={sms_sent}, Email={email_sent}"
            )
        else:
            logger.error("Failed to send critical alert via any channel")

    def send_warning(self, warning: str, details: Optional[str] = None) -> None:
        """
        Send warning alert via Email only.

        Used for non-critical issues:
        - Moderate slippage
        - Position drift
        - Data fetch delays

        Args:
            warning: Warning description
            details: Additional details (optional)
        """
        timestamp = logger.handlers[0].formatter.formatTime(
            logging.LogRecord('', 0, '', 0, '', (), None)
        ) if logger.handlers else ''

        email_subject = f"[JUTSU WARNING] {warning[:50]}"
        email_body = f"""
WARNING - Jutsu Labs Live Trading

Timestamp: {timestamp}
Warning: {warning}

{f'Details: {details}' if details else ''}

Action: Review at your convenience.

---
This is an automated alert from Jutsu Labs live trading system.
        """

        logger.warning(f"WARNING ALERT: {warning}")

        email_sent = self.send_email(email_subject, email_body.strip())

        if email_sent:
            logger.info("Warning alert sent via email")
        else:
            logger.warning("Failed to send warning alert")

    def send_info(self, message: str) -> None:
        """
        Log info message (no external alerts).

        Used for informational events:
        - Successful execution
        - Daily summary
        - Performance updates

        Args:
            message: Info message
        """
        logger.info(message)


def main():
    """Test alert manager functionality."""
    logging.basicConfig(level=logging.INFO)

    # Test configuration
    config = {
        'alerts': {
            'sms_enabled': False,  # Requires Twilio credentials
            'email_enabled': False,  # Requires SendGrid API key
            'critical_conditions': [
                'auth_failure',
                'slippage_exceeded'
            ],
            'sms_number': '+1234567890',
            'email_address': 'test@example.com'
        }
    }

    alert_manager = AlertManager(config)

    # Test 1: Info message (log only)
    print("\nTest 1: Info message (log only)")
    alert_manager.send_info("Daily execution completed successfully")
    print("  ✅ Logged")

    # Test 2: Warning (email if enabled)
    print("\nTest 2: Warning alert")
    alert_manager.send_warning(
        "Moderate slippage detected",
        "TQQQ: 0.4% slippage"
    )
    print("  ✅ Warning logged (email if configured)")

    # Test 3: Critical alert (SMS + Email if enabled)
    print("\nTest 3: Critical alert")
    alert_manager.send_critical_alert(
        "Authentication failure detected",
        "OAuth token expired at 15:50"
    )
    print("  ✅ Critical alert logged (SMS + Email if configured)")

    print("\n✅ Alert manager tests completed")
    print("\nNOTE: To test actual delivery:")
    print("  1. Set environment variables:")
    print("     - TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER")
    print("     - SENDGRID_API_KEY, SENDGRID_FROM_EMAIL")
    print("     - ALERT_SMS_NUMBER, ALERT_EMAIL")
    print("  2. Set sms_enabled=True and email_enabled=True in config")
    print("  3. Run test again")


if __name__ == "__main__":
    main()
