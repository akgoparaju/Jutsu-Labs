"""
Authentication tests for JWT token handling.

Tests token creation, validation, and expiration.
"""
import pytest
from datetime import datetime, timedelta
from jose import jwt

from jutsu_api.auth.jwt import create_access_token, get_current_user
from jutsu_api.config import get_settings
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


settings = get_settings()


class TestJWTAuthentication:
    """Test JWT token creation and validation."""

    def test_create_access_token(self):
        """Test creating a valid JWT token."""
        test_data = {"sub": "testuser@example.com"}
        token = create_access_token(test_data)

        assert token is not None
        assert isinstance(token, str)

        # Decode token to verify contents
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        assert payload["sub"] == "testuser@example.com"
        assert "exp" in payload

    def test_create_token_with_custom_expiration(self):
        """Test creating token with custom expiration time."""
        test_data = {"sub": "testuser@example.com"}
        expires_delta = timedelta(minutes=15)
        token = create_access_token(test_data, expires_delta)

        # Decode and check expiration
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        exp_timestamp = payload["exp"]
        exp_datetime = datetime.utcfromtimestamp(exp_timestamp)
        now = datetime.utcnow()

        # Should expire in approximately 15 minutes (with some tolerance for test execution time)
        time_diff = (exp_datetime - now).total_seconds()
        assert 13 * 60 < time_diff < 16 * 60, f"Expected ~15 min, got {time_diff/60:.1f} min"

    @pytest.mark.asyncio
    async def test_validate_valid_token(self):
        """Test validating a valid JWT token."""
        test_data = {"sub": "testuser@example.com"}
        token = create_access_token(test_data)

        # Create credentials object
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token
        )

        # Validate token
        username = await get_current_user(credentials)
        assert username == "testuser@example.com"

    @pytest.mark.asyncio
    async def test_validate_invalid_token(self):
        """Test validating an invalid JWT token."""
        # Create credentials with invalid token
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid.token.here"
        )

        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_validate_expired_token(self):
        """Test validating an expired JWT token."""
        test_data = {"sub": "testuser@example.com"}

        # Create token that expired 1 minute ago
        expires_delta = timedelta(minutes=-1)
        token = create_access_token(test_data, expires_delta)

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token
        )

        # Should raise HTTPException for expired token
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_validate_token_missing_subject(self):
        """Test validating token without 'sub' claim."""
        # Create token without 'sub' claim
        test_data = {"user": "testuser"}  # Wrong key
        token = jwt.encode(
            test_data,
            settings.secret_key,
            algorithm=settings.algorithm
        )

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token
        )

        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_validate_token_wrong_secret(self):
        """Test validating token signed with wrong secret."""
        test_data = {"sub": "testuser@example.com"}

        # Sign with different secret
        wrong_token = jwt.encode(
            test_data,
            "wrong_secret_key",
            algorithm=settings.algorithm
        )

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=wrong_token
        )

        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)

        assert exc_info.value.status_code == 401


class TestAPIKeyAuthentication:
    """Test API key generation and validation (future implementation)."""

    def test_api_key_placeholder(self):
        """Placeholder test for future API key implementation."""
        # API key authentication not yet implemented
        # This test serves as a placeholder
        assert True
