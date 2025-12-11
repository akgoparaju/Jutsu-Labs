"""
Two-Factor Authentication (2FA/TOTP) API routes.

Provides endpoints for TOTP-based 2FA:
- GET /2fa/status: Check if 2FA is enabled for current user
- POST /2fa/setup: Generate TOTP secret and QR code for setup
- POST /2fa/verify: Verify TOTP code and enable 2FA
- POST /2fa/disable: Disable 2FA with password confirmation
- POST /2fa/validate: Validate 2FA code (for login flow)
- POST /2fa/backup-codes: Generate new backup codes

Security Features:
- TOTP secrets generated with 32-character base32 encoding
- 10 one-time backup codes for account recovery
- Password required to disable 2FA
- Security event logging for all 2FA operations
"""

import json
import logging
import secrets
import io
import base64
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from jutsu_engine.api.dependencies import (
    get_db,
    get_current_user,
    verify_password,
)
from jutsu_engine.utils.security_logger import security_logger, get_client_ip

logger = logging.getLogger('API.2FA')

# Rate limiting (optional - falls back to no limiting if slowapi not available)
try:
    from jutsu_engine.api.main import limiter, RATE_LIMITING_AVAILABLE
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

# Rate limit for 2FA validation (prevent brute force attacks on 6-digit codes)
TWO_FA_RATE_LIMIT = "5/minute"


def _rate_limit_2fa(func):
    """Apply rate limiting to 2FA validation endpoint if available."""
    if RATE_LIMITING_AVAILABLE and limiter is not None:
        return limiter.limit(TWO_FA_RATE_LIMIT)(func)
    return func

router = APIRouter(prefix="/api/2fa", tags=["two-factor-auth"])

# Check if pyotp is available
try:
    import pyotp
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    logger.warning("pyotp not installed. 2FA will not be available.")

# Check if qrcode is available
try:
    import qrcode
    from qrcode.image.pil import PilImage
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    logger.warning("qrcode[pil] not installed. QR codes will not be available.")


# ==============================================================================
# SCHEMAS
# ==============================================================================

class TwoFactorStatus(BaseModel):
    """2FA status for current user."""
    enabled: bool
    available: bool  # Whether 2FA is available on the server
    message: str


class TwoFactorSetupResponse(BaseModel):
    """Response when setting up 2FA."""
    secret: str  # Base32 secret for manual entry
    qr_code: Optional[str] = None  # Base64 encoded QR code image
    provisioning_uri: str  # otpauth:// URI
    message: str


class TwoFactorVerifyRequest(BaseModel):
    """Request to verify and enable 2FA."""
    code: str  # 6-digit TOTP code


class TwoFactorVerifyResponse(BaseModel):
    """Response after enabling 2FA."""
    success: bool
    backup_codes: Optional[List[str]] = None  # One-time backup codes
    message: str


class TwoFactorValidateRequest(BaseModel):
    """Request to validate 2FA code (during login)."""
    username: str
    code: str  # 6-digit TOTP code or backup code


class TwoFactorValidateResponse(BaseModel):
    """Response from 2FA validation."""
    valid: bool
    message: str


class TwoFactorDisableRequest(BaseModel):
    """Request to disable 2FA."""
    password: str  # Current password for confirmation
    code: Optional[str] = None  # Optional TOTP code for extra security


class BackupCodesResponse(BaseModel):
    """Response with new backup codes."""
    backup_codes: List[str]
    message: str


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def generate_backup_codes(count: int = 10) -> List[str]:
    """
    Generate secure one-time backup codes.

    Format: XXXX-XXXX (8 alphanumeric characters with hyphen)
    """
    codes = []
    for _ in range(count):
        # Generate 8 random alphanumeric characters
        code_chars = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        # Format as XXXX-XXXX
        code = f"{code_chars[:4]}-{code_chars[4:]}"
        codes.append(code)
    return codes


def generate_qr_code(provisioning_uri: str) -> Optional[str]:
    """
    Generate QR code as base64 encoded PNG.

    Returns None if qrcode library not available.
    """
    if not QR_AVAILABLE:
        return None

    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return f"data:image/png;base64,{img_base64}"
    except Exception as e:
        logger.warning(f"Failed to generate QR code: {e}")
        return None


def verify_backup_code(user, code: str, db: Session) -> bool:
    """
    Verify and consume a backup code.

    Returns True if code is valid and was consumed.
    """
    if not user.backup_codes:
        return False

    try:
        # backup_codes is now a PostgreSQL ARRAY, convert to list for manipulation
        codes = list(user.backup_codes)
        # Normalize code format (remove hyphens for comparison)
        normalized_code = code.replace('-', '').upper()

        for i, stored_code in enumerate(codes):
            if stored_code.replace('-', '').upper() == normalized_code:
                # Remove used code
                codes.pop(i)
                user.backup_codes = codes  # Assign list directly to ARRAY column
                db.commit()
                return True

        return False
    except Exception:
        return False


# ==============================================================================
# ROUTES
# ==============================================================================

@router.get("/status", response_model=TwoFactorStatus)
async def get_2fa_status(
    current_user=Depends(get_current_user)
):
    """
    Get 2FA status for current user.

    Returns whether 2FA is enabled and available.
    """
    if current_user is None:
        # Auth disabled
        return TwoFactorStatus(
            enabled=False,
            available=TOTP_AVAILABLE,
            message="Authentication disabled. 2FA not applicable."
        )

    return TwoFactorStatus(
        enabled=current_user.totp_enabled or False,
        available=TOTP_AVAILABLE,
        message="2FA is enabled" if current_user.totp_enabled else "2FA is not enabled"
    )


@router.post("/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Generate TOTP secret and QR code for 2FA setup.

    Returns the secret key (for manual entry) and a QR code (for authenticator apps).
    User must then call /verify with a valid TOTP code to complete setup.

    Raises:
        HTTPException 401: If not authenticated
        HTTPException 400: If 2FA already enabled
        HTTPException 503: If pyotp not installed
    """
    client_ip = get_client_ip(request)

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to setup 2FA"
        )

    if not TOTP_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="2FA not available. Install: pip install pyotp qrcode[pil]"
        )

    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled. Disable it first to reconfigure."
        )

    # Generate new secret
    secret = pyotp.random_base32()

    # Store secret (not enabled until verified)
    current_user.totp_secret = secret
    db.commit()

    # Generate provisioning URI
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.username,
        issuer_name="Jutsu Labs"
    )

    # Generate QR code
    qr_code = generate_qr_code(provisioning_uri)

    logger.info(f"2FA setup initiated for user '{current_user.username}'")

    return TwoFactorSetupResponse(
        secret=secret,
        qr_code=qr_code,
        provisioning_uri=provisioning_uri,
        message="Scan the QR code with your authenticator app, then verify with a code."
    )


@router.post("/verify", response_model=TwoFactorVerifyResponse)
async def verify_2fa(
    request: Request,
    verify_request: TwoFactorVerifyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Verify TOTP code and enable 2FA.

    After calling /setup, use this endpoint with a valid TOTP code
    to confirm the user has correctly configured their authenticator app.

    Returns backup codes that should be stored securely.

    Raises:
        HTTPException 401: If not authenticated
        HTTPException 400: If no pending 2FA setup or invalid code
    """
    client_ip = get_client_ip(request)

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    if not TOTP_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="2FA not available"
        )

    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No 2FA setup in progress. Call /setup first."
        )

    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled."
        )

    # Verify the code
    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(verify_request.code, valid_window=1):
        security_logger.log_2fa_failure(
            username=current_user.username,
            ip_address=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please try again."
        )

    # Generate backup codes
    backup_codes = generate_backup_codes(10)

    # Enable 2FA
    current_user.totp_enabled = True
    current_user.backup_codes = backup_codes  # Assign list directly to ARRAY column
    db.commit()

    # Log security event
    security_logger.log_2fa_enabled(
        username=current_user.username,
        ip_address=client_ip
    )

    logger.info(f"2FA enabled for user '{current_user.username}'")

    return TwoFactorVerifyResponse(
        success=True,
        backup_codes=backup_codes,
        message="2FA enabled successfully. Save your backup codes securely!"
    )


@router.post("/disable")
async def disable_2fa(
    request: Request,
    disable_request: TwoFactorDisableRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Disable 2FA for current user.

    Requires password confirmation for security.
    Optionally accepts a TOTP code for extra verification.

    Raises:
        HTTPException 401: If not authenticated or wrong password
        HTTPException 400: If 2FA not enabled
    """
    client_ip = get_client_ip(request)

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled"
        )

    # Verify password
    if not verify_password(disable_request.password, current_user.password_hash):
        security_logger.log_login_failure(
            username=current_user.username,
            ip_address=client_ip,
            reason="wrong_password_2fa_disable"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password"
        )

    # Optional: verify TOTP code if provided
    if disable_request.code and TOTP_AVAILABLE:
        totp = pyotp.TOTP(current_user.totp_secret)
        if not totp.verify(disable_request.code, valid_window=1):
            security_logger.log_2fa_failure(
                username=current_user.username,
                ip_address=client_ip
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid TOTP code"
            )

    # Disable 2FA
    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.backup_codes = None
    db.commit()

    # Log security event
    security_logger.log_2fa_disabled(
        username=current_user.username,
        ip_address=client_ip
    )

    logger.info(f"2FA disabled for user '{current_user.username}'")

    return {"success": True, "message": "2FA has been disabled"}


@router.post("/validate", response_model=TwoFactorValidateResponse)
@_rate_limit_2fa
async def validate_2fa(
    request: Request,
    validate_request: TwoFactorValidateRequest,
    db: Session = Depends(get_db)
):
    """
    Validate 2FA code (for use in login flow).

    This endpoint is called after successful password authentication
    when 2FA is enabled. It accepts either a TOTP code or a backup code.

    Note: This endpoint does not require authentication as it's part of
    the login flow (user has already provided valid credentials).

    Returns:
        Whether the code is valid
    """
    client_ip = get_client_ip(request)

    if not TOTP_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="2FA not available"
        )

    from jutsu_engine.data.models import User
    user = db.query(User).filter(User.username == validate_request.username).first()

    if not user or not user.totp_enabled:
        # Don't reveal if user exists
        return TwoFactorValidateResponse(
            valid=False,
            message="Invalid code"
        )

    # Try TOTP code first
    totp = pyotp.TOTP(user.totp_secret)
    if totp.verify(validate_request.code, valid_window=1):
        security_logger.log_2fa_success(
            username=user.username,
            ip_address=client_ip
        )
        return TwoFactorValidateResponse(
            valid=True,
            message="2FA verification successful"
        )

    # Try backup code
    if verify_backup_code(user, validate_request.code, db):
        security_logger.log_2fa_success(
            username=user.username,
            ip_address=client_ip
        )
        logger.warning(f"Backup code used for user '{user.username}'")
        return TwoFactorValidateResponse(
            valid=True,
            message="Backup code accepted. Consider generating new backup codes."
        )

    # Invalid code
    security_logger.log_2fa_failure(
        username=user.username,
        ip_address=client_ip
    )

    return TwoFactorValidateResponse(
        valid=False,
        message="Invalid code"
    )


@router.post("/backup-codes", response_model=BackupCodesResponse)
async def regenerate_backup_codes(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Generate new backup codes.

    This invalidates all previous backup codes. Requires 2FA to be enabled.

    Raises:
        HTTPException 401: If not authenticated
        HTTPException 400: If 2FA not enabled
    """
    client_ip = get_client_ip(request)

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA must be enabled to generate backup codes"
        )

    # Generate new backup codes
    backup_codes = generate_backup_codes(10)
    current_user.backup_codes = backup_codes  # Assign list directly to ARRAY column
    db.commit()

    logger.info(f"New backup codes generated for user '{current_user.username}'")

    return BackupCodesResponse(
        backup_codes=backup_codes,
        message="New backup codes generated. Previous codes are now invalid."
    )
