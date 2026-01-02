"""
Passkey/WebAuthn API routes.

Provides endpoints for FIDO2 passkey authentication:
- POST /passkey/register-options: Generate registration challenge
- POST /passkey/register: Complete passkey registration
- GET /passkey/list: List user's registered passkeys
- DELETE /passkey/{id}: Revoke a passkey
- POST /passkey/authenticate-options: Generate auth challenge (after password)
- POST /passkey/authenticate: Verify passkey assertion and issue tokens

Security Features:
- Passkeys replace TOTP 2FA (password still required)
- Multiple passkeys per user (multi-device support)
- Falls back to TOTP if no passkey for device
- sign_count validation prevents replay attacks
- Security event logging for all passkey operations

WebAuthn Library: py_webauthn (FIDO2 compliant)
"""

import os
import json
import logging
import base64
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from jutsu_engine.api.dependencies import (
    get_db,
    get_current_user,
    create_access_token,
    create_refresh_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    PASSKEY_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from jutsu_engine.utils.security_logger import security_logger, get_client_ip

logger = logging.getLogger('API.Passkey')

# Rate limiting (optional - falls back to no limiting if slowapi not available)
try:
    from jutsu_engine.api.main import limiter, RATE_LIMITING_AVAILABLE
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

PASSKEY_RATE_LIMIT = "5/minute"


def _rate_limit_passkey(func):
    """Apply rate limiting to passkey endpoints if available."""
    if RATE_LIMITING_AVAILABLE and limiter is not None:
        return limiter.limit(PASSKEY_RATE_LIMIT)(func)
    return func


router = APIRouter(prefix="/api/passkey", tags=["passkey"])

# Check if webauthn is available
try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
    )
    from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor,
        AuthenticatorSelectionCriteria,
        ResidentKeyRequirement,
        UserVerificationRequirement,
        AuthenticatorAttachment,
    )
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False
    logger.warning("webauthn not installed. Passkey authentication will not be available.")

# WebAuthn configuration from environment
WEBAUTHN_RP_ID = os.getenv("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Jutsu Trading")
WEBAUTHN_ORIGIN = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")

# Session storage for challenges (in production, use Redis or database)
# This is a simple in-memory store - valid for single-instance deployments
_registration_challenges: dict = {}  # user_id -> challenge bytes
_authentication_challenges: dict = {}  # username -> challenge bytes


# ==============================================================================
# SCHEMAS
# ==============================================================================

class PasskeyStatus(BaseModel):
    """Passkey status for current user."""
    available: bool  # Whether passkey is available on the server
    count: int  # Number of registered passkeys
    message: str


class PasskeyInfo(BaseModel):
    """Information about a registered passkey."""
    id: int
    device_name: Optional[str]
    created_at: str  # ISO format
    last_used_at: Optional[str]  # ISO format


class PasskeyListResponse(BaseModel):
    """Response listing user's passkeys."""
    passkeys: List[PasskeyInfo]
    count: int


class RegisterOptionsRequest(BaseModel):
    """Request to generate registration options."""
    device_name: Optional[str] = None  # User-friendly name for the device


class RegisterOptionsResponse(BaseModel):
    """WebAuthn registration options."""
    options: str  # JSON string of PublicKeyCredentialCreationOptions
    message: str


class RegisterRequest(BaseModel):
    """Request to complete passkey registration."""
    credential: str  # JSON string of registration response from browser
    device_name: Optional[str] = None


class RegisterResponse(BaseModel):
    """Response after successful registration."""
    success: bool
    passkey_id: int
    message: str


class AuthenticateOptionsRequest(BaseModel):
    """Request to generate authentication options (after password verification)."""
    username: str


class AuthenticateOptionsResponse(BaseModel):
    """WebAuthn authentication options."""
    options: str  # JSON string of PublicKeyCredentialRequestOptions
    has_passkeys: bool
    message: str


class AuthenticateRequest(BaseModel):
    """Request to verify passkey assertion."""
    username: str
    credential: str  # JSON string of authentication response from browser


class AuthenticateResponse(BaseModel):
    """Response after successful passkey authentication."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _bytes_to_base64(data: bytes) -> str:
    """Convert bytes to base64 string for database storage."""
    return base64.b64encode(data).decode('utf-8')


def _base64_to_bytes(data: str) -> bytes:
    """Convert base64 string from database to bytes."""
    return base64.b64decode(data.encode('utf-8'))


# ==============================================================================
# ENDPOINTS
# ==============================================================================

@router.get("/status", response_model=PasskeyStatus)
async def get_passkey_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get passkey status for current user.

    Returns:
        Whether passkeys are available and how many are registered.
    """
    if not WEBAUTHN_AVAILABLE:
        return PasskeyStatus(
            available=False,
            count=0,
            message="Passkey authentication not available (webauthn not installed)"
        )

    from jutsu_engine.data.models import Passkey

    passkey_count = db.query(Passkey).filter(Passkey.user_id == current_user.id).count()

    return PasskeyStatus(
        available=True,
        count=passkey_count,
        message=f"You have {passkey_count} passkey(s) registered"
    )


@router.get("/list", response_model=PasskeyListResponse)
async def list_passkeys(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all passkeys registered for the current user.

    Returns:
        List of passkeys with device names and timestamps.
    """
    from jutsu_engine.data.models import Passkey

    passkeys = db.query(Passkey).filter(Passkey.user_id == current_user.id).all()

    passkey_list = [
        PasskeyInfo(
            id=p.id,
            device_name=p.device_name,
            created_at=p.created_at.isoformat() if p.created_at else None,
            last_used_at=p.last_used_at.isoformat() if p.last_used_at else None
        )
        for p in passkeys
    ]

    return PasskeyListResponse(
        passkeys=passkey_list,
        count=len(passkey_list)
    )


@router.post("/register-options", response_model=RegisterOptionsResponse)
@_rate_limit_passkey
async def get_registration_options(
    request: Request,
    options_request: RegisterOptionsRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate WebAuthn registration options.

    This is the first step in passkey registration. Returns a challenge
    that must be signed by the authenticator.

    Args:
        options_request: Optional device name for the new passkey.

    Returns:
        WebAuthn PublicKeyCredentialCreationOptions as JSON.
    """
    client_ip = get_client_ip(request)

    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Passkey authentication not available"
        )

    from jutsu_engine.data.models import Passkey

    # Get existing credentials to exclude (prevent re-registration of same device)
    existing_passkeys = db.query(Passkey).filter(Passkey.user_id == current_user.id).all()
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=p.credential_id)
        for p in existing_passkeys
    ]

    # Generate registration options
    options = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=str(current_user.id).encode(),
        user_name=current_user.username,
        user_display_name=current_user.username,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    # Store challenge for verification
    _registration_challenges[current_user.id] = options.challenge

    logger.info(f"Generated passkey registration options for user '{current_user.username}'")

    return RegisterOptionsResponse(
        options=options_to_json(options),
        message="Registration options generated. Complete registration with your authenticator."
    )


@router.post("/register", response_model=RegisterResponse)
@_rate_limit_passkey
async def register_passkey(
    request: Request,
    register_request: RegisterRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Complete passkey registration.

    This is the second step in passkey registration. Verifies the
    authenticator response and stores the credential.

    Args:
        register_request: The credential response from the browser.

    Returns:
        Success status and the new passkey ID.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get('User-Agent')

    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Passkey authentication not available"
        )

    # Get stored challenge
    expected_challenge = _registration_challenges.get(current_user.id)
    if not expected_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No registration in progress. Call /register-options first."
        )

    try:
        # Parse credential from JSON
        credential_data = json.loads(register_request.credential)

        # Verify registration response
        verification = verify_registration_response(
            credential=credential_data,
            expected_challenge=expected_challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_ORIGIN,
        )

        # Clean up challenge
        del _registration_challenges[current_user.id]

        # Store the credential
        from jutsu_engine.data.models import Passkey

        new_passkey = Passkey(
            user_id=current_user.id,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            device_name=register_request.device_name,
            aaguid=str(verification.aaguid) if verification.aaguid else None,
            created_at=datetime.now(timezone.utc),
        )

        db.add(new_passkey)
        db.commit()
        db.refresh(new_passkey)

        # Log security event
        security_logger.log_passkey_registered(
            username=current_user.username,
            device_name=register_request.device_name,
            ip_address=client_ip
        )

        logger.info(f"Passkey registered for user '{current_user.username}' (device: {register_request.device_name})")

        return RegisterResponse(
            success=True,
            passkey_id=new_passkey.id,
            message=f"Passkey registered successfully for {register_request.device_name or 'this device'}"
        )

    except Exception as e:
        # Clean up challenge on failure
        _registration_challenges.pop(current_user.id, None)

        logger.error(f"Passkey registration failed for user '{current_user.username}': {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passkey registration failed. Please try again."
        )


@router.delete("/{passkey_id}")
@_rate_limit_passkey
async def delete_passkey(
    request: Request,
    passkey_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete/revoke a passkey.

    Args:
        passkey_id: ID of the passkey to delete.

    Returns:
        Success confirmation.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get('User-Agent')

    from jutsu_engine.data.models import Passkey

    passkey = db.query(Passkey).filter(
        Passkey.id == passkey_id,
        Passkey.user_id == current_user.id
    ).first()

    if not passkey:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passkey not found"
        )

    device_name = passkey.device_name
    db.delete(passkey)
    db.commit()

    # Log security event
    security_logger.log_passkey_revoked(
        username=current_user.username,
        device_name=device_name,
        ip_address=client_ip
    )

    logger.info(f"Passkey {passkey_id} revoked for user '{current_user.username}'")

    return {"success": True, "message": f"Passkey '{device_name or 'unnamed'}' has been revoked"}


@router.post("/authenticate-options", response_model=AuthenticateOptionsResponse)
@_rate_limit_passkey
async def get_authentication_options(
    request: Request,
    options_request: AuthenticateOptionsRequest,
    db: Session = Depends(get_db)
):
    """
    Generate WebAuthn authentication options.

    Called after password verification to check if user has passkeys.
    Returns authentication challenge if passkeys exist.

    Args:
        options_request: Username to authenticate.

    Returns:
        WebAuthn PublicKeyCredentialRequestOptions as JSON.
    """
    client_ip = get_client_ip(request)

    if not WEBAUTHN_AVAILABLE:
        return AuthenticateOptionsResponse(
            options="{}",
            has_passkeys=False,
            message="Passkey authentication not available"
        )

    from jutsu_engine.data.models import User, Passkey

    # Find user
    user = db.query(User).filter(User.username == options_request.username).first()
    if not user:
        # Don't reveal user existence
        return AuthenticateOptionsResponse(
            options="{}",
            has_passkeys=False,
            message="No passkeys available"
        )

    # Get user's passkeys
    passkeys = db.query(Passkey).filter(Passkey.user_id == user.id).all()
    if not passkeys:
        return AuthenticateOptionsResponse(
            options="{}",
            has_passkeys=False,
            message="No passkeys registered for this user"
        )

    # Build allowed credentials list
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=p.credential_id)
        for p in passkeys
    ]

    # Generate authentication options
    options = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    # Store challenge for verification
    _authentication_challenges[options_request.username] = options.challenge

    logger.info(f"Generated passkey authentication options for user '{options_request.username}'")

    return AuthenticateOptionsResponse(
        options=options_to_json(options),
        has_passkeys=True,
        message="Authentication options generated. Verify with your passkey."
    )


@router.post("/authenticate", response_model=AuthenticateResponse)
@_rate_limit_passkey
async def authenticate_passkey(
    request: Request,
    auth_request: AuthenticateRequest,
    db: Session = Depends(get_db)
):
    """
    Verify passkey assertion and issue JWT tokens.

    This completes the passkey authentication flow after password verification.
    On success, issues access and refresh tokens.

    Args:
        auth_request: Username and credential assertion from browser.

    Returns:
        JWT access and refresh tokens.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get('User-Agent')

    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Passkey authentication not available"
        )

    # Get stored challenge
    expected_challenge = _authentication_challenges.get(auth_request.username)
    if not expected_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No authentication in progress. Call /authenticate-options first."
        )

    from jutsu_engine.data.models import User, Passkey

    # Find user
    user = db.query(User).filter(User.username == auth_request.username).first()
    if not user:
        _authentication_challenges.pop(auth_request.username, None)
        security_logger.log_passkey_auth_failed(
            username=auth_request.username,
            ip_address=client_ip,
            reason="user_not_found"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )

    try:
        # Parse credential from JSON
        credential_data = json.loads(auth_request.credential)

        # Find the passkey by credential ID
        raw_id = credential_data.get('rawId') or credential_data.get('id')
        if not raw_id:
            raise ValueError("Missing credential ID")

        # Decode the credential ID from base64url
        credential_id_bytes = base64url_to_bytes(raw_id)

        passkey = db.query(Passkey).filter(
            Passkey.user_id == user.id,
            Passkey.credential_id == credential_id_bytes
        ).first()

        if not passkey:
            raise ValueError("Passkey not found")

        # Verify authentication response
        verification = verify_authentication_response(
            credential=credential_data,
            expected_challenge=expected_challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_ORIGIN,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
        )

        # Clean up challenge
        del _authentication_challenges[auth_request.username]

        # Update sign_count and last_used_at
        passkey.sign_count = verification.new_sign_count
        passkey.last_used_at = datetime.now(timezone.utc)
        db.commit()

        # Create tokens with extended session for passkey authentication
        # Passkey auth gets 7-hour tokens (hardware-bound security allows this safely)
        token_data = {"sub": user.username}
        access_token = create_access_token(data=token_data, auth_method="passkey")
        refresh_token = create_refresh_token(data=token_data, auth_method="passkey")

        # Calculate expiration times (passkey sessions get extended duration)
        access_expires_in = PASSKEY_TOKEN_EXPIRE_MINUTES * 60
        refresh_expires_in = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

        # Log successful authentication
        security_logger.log_passkey_authenticated(
            username=user.username,
            device_name=passkey.device_name,
            ip_address=client_ip
        )

        logger.info(f"User '{user.username}' authenticated with passkey (device: {passkey.device_name})")

        return AuthenticateResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=access_expires_in,
            refresh_expires_in=refresh_expires_in
        )

    except Exception as e:
        # Clean up challenge on failure
        _authentication_challenges.pop(auth_request.username, None)

        security_logger.log_passkey_auth_failed(
            username=auth_request.username,
            ip_address=client_ip,
            reason=str(e)
        )

        logger.error(f"Passkey authentication failed for user '{auth_request.username}': {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )
