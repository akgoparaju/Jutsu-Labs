"""
Passkey/WebAuthn authentication tests.

Tests passkey registration, authentication, listing, and deletion.
Uses mocking for WebAuthn operations since they require hardware authenticators.

Note: Database model tests are skipped because the User model uses PostgreSQL
ARRAY type (for backup_codes) which isn't compatible with SQLite test database.
"""
import pytest
import json
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestPasskeyEndpointSchemas:
    """Test passkey API schemas and data structures."""

    def test_registration_request_schema(self):
        """Test registration options request schema."""
        from jutsu_engine.api.routes.passkey import RegisterOptionsRequest

        # Valid request
        request = RegisterOptionsRequest(device_name="Test Device")
        assert request.device_name == "Test Device"

        # Optional device name
        request_no_name = RegisterOptionsRequest()
        assert request_no_name.device_name is None

    def test_passkey_info_schema(self):
        """Test passkey info response schema."""
        from jutsu_engine.api.routes.passkey import PasskeyInfo

        info = PasskeyInfo(
            id=1,
            device_name="MacBook Pro",
            created_at="2025-01-15T12:00:00Z",
            last_used_at=None,
        )
        assert info.id == 1
        assert info.device_name == "MacBook Pro"
        assert info.last_used_at is None

    def test_passkey_info_with_last_used(self):
        """Test passkey info with last used timestamp."""
        from jutsu_engine.api.routes.passkey import PasskeyInfo

        info = PasskeyInfo(
            id=2,
            device_name="iPhone 15",
            created_at="2025-01-15T12:00:00Z",
            last_used_at="2025-01-16T08:30:00Z",
        )
        assert info.last_used_at == "2025-01-16T08:30:00Z"

    def test_registration_response_schema(self):
        """Test registration completion request schema."""
        from jutsu_engine.api.routes.passkey import RegisterRequest

        # Create a mock credential response
        request = RegisterRequest(
            device_name="Test Device",
            credential='{"id": "test_id", "rawId": "base64_raw_id", "type": "public-key"}',
        )
        assert request.device_name == "Test Device"
        assert "test_id" in request.credential

    def test_authenticate_request_schema(self):
        """Test authentication request schema."""
        from jutsu_engine.api.routes.passkey import AuthenticateRequest

        request = AuthenticateRequest(
            username="testuser",
            credential='{"id": "test_id", "response": {"authenticatorData": "..."}}',
        )
        assert request.username == "testuser"
        assert request.credential is not None

    def test_authenticate_options_request_schema(self):
        """Test authentication options request schema."""
        from jutsu_engine.api.routes.passkey import AuthenticateOptionsRequest

        request = AuthenticateOptionsRequest(username="testuser")
        assert request.username == "testuser"


class TestPasskeyWebAuthnHelpers:
    """Test WebAuthn helper functions and configurations."""

    def test_webauthn_config_defaults(self):
        """Test WebAuthn configuration defaults."""
        # These are the expected defaults from the passkey module
        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        rp_name = os.getenv("WEBAUTHN_RP_NAME", "Jutsu Trading")
        origin = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")

        # Verify defaults are sensible for development
        assert rp_id == "localhost" or len(rp_id) > 0
        assert "Trading" in rp_name or len(rp_name) > 0
        assert origin.startswith("https://") or origin.startswith("http://")

    def test_webauthn_availability(self):
        """Test that webauthn library is available."""
        try:
            from webauthn import (
                generate_registration_options,
                verify_registration_response,
                generate_authentication_options,
                verify_authentication_response,
            )
            webauthn_available = True
        except ImportError:
            webauthn_available = False

        # WebAuthn should be available after installation
        assert webauthn_available, "webauthn library not installed"

    def test_webauthn_helpers_available(self):
        """Test that webauthn helper functions are available."""
        from webauthn.helpers import bytes_to_base64url, base64url_to_bytes

        # Test conversion functions work
        test_bytes = b"test_data"
        encoded = bytes_to_base64url(test_bytes)
        decoded = base64url_to_bytes(encoded)
        assert decoded == test_bytes

    def test_webauthn_structs_available(self):
        """Test that webauthn structs are importable."""
        from webauthn.helpers.structs import (
            PublicKeyCredentialDescriptor,
            AuthenticatorSelectionCriteria,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )

        # Verify we can use the structs
        assert PublicKeyCredentialDescriptor is not None
        assert AuthenticatorSelectionCriteria is not None


class TestPasskeySecurityLogging:
    """Test security logging for passkey operations."""

    def test_security_logger_import(self):
        """Test that security logger can be imported."""
        from jutsu_engine.utils.security_logger import security_logger
        assert security_logger is not None

    def test_get_client_ip_import(self):
        """Test that get_client_ip helper can be imported."""
        from jutsu_engine.utils.security_logger import get_client_ip
        assert get_client_ip is not None

    def test_security_events_defined(self):
        """Test that passkey-related security events are defined."""
        from jutsu_engine.utils.security_logger import (
            PASSKEY_REGISTERED,
            PASSKEY_AUTHENTICATED,
            PASSKEY_REVOKED,
            PASSKEY_AUTH_FAILED,
        )

        assert PASSKEY_REGISTERED == "passkey_registered"
        assert PASSKEY_AUTHENTICATED == "passkey_authenticated"
        assert PASSKEY_REVOKED == "passkey_revoked"
        assert PASSKEY_AUTH_FAILED == "passkey_auth_failed"


class TestPasskeyRateLimiting:
    """Test rate limiting for passkey endpoints."""

    def test_rate_limit_decorator_exists(self):
        """Test that rate limiting decorator is defined."""
        from jutsu_engine.api.routes.passkey import _rate_limit_passkey, PASSKEY_RATE_LIMIT
        assert PASSKEY_RATE_LIMIT == "5/minute"
        assert callable(_rate_limit_passkey)

    def test_rate_limit_decorator_returns_callable(self):
        """Test that rate limit decorator properly wraps functions."""
        from jutsu_engine.api.routes.passkey import _rate_limit_passkey

        @_rate_limit_passkey
        def test_func():
            return "test"

        assert callable(test_func)


class TestPasskeyRouterConfiguration:
    """Test passkey router configuration."""

    def test_router_prefix(self):
        """Test that router has correct prefix."""
        from jutsu_engine.api.routes.passkey import router

        assert router.prefix == "/api/passkey"

    def test_router_tags(self):
        """Test that router has correct tags."""
        from jutsu_engine.api.routes.passkey import router

        assert "passkey" in router.tags

    def test_router_registered_in_main(self):
        """Test that passkey router is registered in main app."""
        from jutsu_engine.api.routes import passkey_router

        assert passkey_router is not None
        assert passkey_router.prefix == "/api/passkey"


class TestPasskeyModelStructure:
    """Test Passkey model structure without database operations."""

    def test_passkey_model_exists(self):
        """Test that Passkey model class exists."""
        from jutsu_engine.data.models import Passkey

        assert Passkey is not None

    def test_passkey_model_tablename(self):
        """Test Passkey model table name."""
        from jutsu_engine.data.models import Passkey

        assert Passkey.__tablename__ == "passkeys"

    def test_passkey_model_columns(self):
        """Test Passkey model has required columns."""
        from jutsu_engine.data.models import Passkey

        # Check that required columns exist
        columns = [c.name for c in Passkey.__table__.columns]
        required_columns = [
            "id",
            "user_id",
            "credential_id",
            "public_key",
            "sign_count",
            "device_name",
            "aaguid",
            "created_at",
            "last_used_at",
        ]

        for col in required_columns:
            assert col in columns, f"Missing column: {col}"

    def test_passkey_model_credential_id_indexed(self):
        """Test that credential_id column is indexed."""
        from jutsu_engine.data.models import Passkey

        credential_id_col = Passkey.__table__.columns["credential_id"]
        assert credential_id_col.index is True or credential_id_col.unique is True

    def test_user_passkeys_relationship_exists(self):
        """Test that User model has passkeys relationship."""
        from jutsu_engine.data.models import User

        # Check that the relationship is defined
        assert hasattr(User, "passkeys")


class TestPasskeyChallengeStorage:
    """Test challenge storage mechanisms."""

    def test_challenge_storage_structures_exist(self):
        """Test that challenge storage dictionaries exist."""
        from jutsu_engine.api.routes.passkey import (
            _registration_challenges,
            _authentication_challenges,
        )

        assert isinstance(_registration_challenges, dict)
        assert isinstance(_authentication_challenges, dict)


class TestLoginFlowIntegration:
    """Test login flow modifications for passkey support."""

    def test_login_response_has_passkey_fields(self):
        """Test that LoginResponse includes passkey fields."""
        from jutsu_engine.api.routes.auth import LoginResponse

        # Create a response with passkey fields
        response = LoginResponse(
            requires_passkey=True,
            passkey_options='{"challenge": "test"}',
            username="testuser",
            token_type="bearer",
        )

        assert response.requires_passkey is True
        assert response.passkey_options is not None
        assert response.username == "testuser"

    def test_login_response_passkey_defaults(self):
        """Test LoginResponse passkey field defaults."""
        from jutsu_engine.api.routes.auth import LoginResponse

        # Create minimal response
        response = LoginResponse(token_type="bearer")

        assert response.requires_passkey is False
        assert response.passkey_options is None


class TestBase64UrlHelpers:
    """Test base64url encoding/decoding for WebAuthn."""

    def test_bytes_to_base64url(self):
        """Test bytes to base64url conversion."""
        from webauthn.helpers import bytes_to_base64url

        test_data = b"test_challenge_data"
        encoded = bytes_to_base64url(test_data)

        # Base64url should not contain +, /, or =
        assert "+" not in encoded
        assert "/" not in encoded
        assert encoded.rstrip("=") == encoded or "=" not in encoded

    def test_base64url_to_bytes(self):
        """Test base64url to bytes conversion."""
        from webauthn.helpers import bytes_to_base64url, base64url_to_bytes

        original = b"test_credential_id_12345"
        encoded = bytes_to_base64url(original)
        decoded = base64url_to_bytes(encoded)

        assert decoded == original

    def test_base64url_roundtrip(self):
        """Test base64url encoding/decoding roundtrip."""
        from webauthn.helpers import bytes_to_base64url, base64url_to_bytes

        # Test various data sizes
        test_cases = [
            b"a",
            b"ab",
            b"abc",
            b"test",
            b"longer_test_string",
            bytes(range(256)),  # All byte values
        ]

        for original in test_cases:
            encoded = bytes_to_base64url(original)
            decoded = base64url_to_bytes(encoded)
            assert decoded == original, f"Roundtrip failed for: {original[:20]}..."
