"""
Authentication API routes for JWT-based login.

Provides:
- POST /auth/login: Login and get JWT tokens (access + refresh)
- POST /auth/refresh: Refresh JWT access token
- GET /auth/me: Get current user info
- POST /auth/logout: Logout (client-side token removal)

Security Features:
- Short-lived access tokens (configurable, default 15 min)
- Long-lived refresh tokens (configurable, default 7 days)
- Secure HTTP-only cookies for refresh tokens (optional, USE_SECURE_COOKIES=true)
- Security event logging for audit trails
- Account lockout after 10 failed login attempts (30 minute lockout)
- Automatic unlock after lockout period expires
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from jutsu_engine.api.dependencies import (
    get_db,
    create_access_token,
    create_refresh_token,
    verify_password,
    get_current_user,
    decode_access_token,
    JWT_AVAILABLE,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from jutsu_engine.utils.security_logger import security_logger, get_client_ip

# Rate limiting (optional)
try:
    from jutsu_engine.api.main import limiter, LOGIN_RATE_LIMIT, RATE_LIMITING_AVAILABLE
except ImportError:
    limiter = None
    LOGIN_RATE_LIMIT = "5/minute"
    RATE_LIMITING_AVAILABLE = False

logger = logging.getLogger('API.AUTH')

# ==============================================================================
# SECURE COOKIE CONFIGURATION
# ==============================================================================
# Set USE_SECURE_COOKIES=true to store refresh tokens in HTTP-only cookies
# This provides additional XSS protection for the refresh token

USE_SECURE_COOKIES = os.getenv('USE_SECURE_COOKIES', 'false').lower() == 'true'
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'  # Require HTTPS
COOKIE_SAMESITE = os.getenv('COOKIE_SAMESITE', 'lax')  # lax, strict, or none
COOKIE_DOMAIN = os.getenv('COOKIE_DOMAIN')  # None = current domain only
REFRESH_TOKEN_COOKIE_NAME = 'refresh_token'

# ==============================================================================
# ACCOUNT LOCKOUT CONFIGURATION
# ==============================================================================
LOCKOUT_THRESHOLD = 10  # Failed login attempts before lockout
LOCKOUT_DURATION_MINUTES = 30  # Account lockout duration

router = APIRouter(prefix="/api/auth", tags=["authentication"])


# ==============================================================================
# SCHEMAS
# ==============================================================================

class Token(BaseModel):
    """JWT token response with access and refresh tokens."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int  # access token expiry in seconds
    refresh_expires_in: Optional[int] = None  # refresh token expiry in seconds


class LoginResponse(BaseModel):
    """Login response - either tokens, passkey challenge, or 2FA required indicator."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    refresh_expires_in: Optional[int] = None
    requires_2fa: bool = False
    requires_passkey: bool = False  # Passkey authentication available
    passkey_options: Optional[str] = None  # WebAuthn authentication options JSON
    username: Optional[str] = None  # Included when 2FA or passkey is required


class UserInfo(BaseModel):
    """Current user information."""
    username: str
    email: Optional[str] = None
    is_admin: bool = False
    last_login: Optional[str] = None


class AuthStatus(BaseModel):
    """Authentication system status."""
    auth_required: bool
    jwt_available: bool
    message: str


class RefreshTokenRequest(BaseModel):
    """Request body for token refresh."""
    refresh_token: str


class Login2FARequest(BaseModel):
    """Request body for login with 2FA code."""
    username: str
    password: str
    totp_code: str  # 6-digit TOTP code or backup code


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def check_account_lockout(user, username: str, client_ip: str, user_agent: str):
    """
    Check if account is locked due to failed login attempts.

    Args:
        user: User object from database
        username: Username for logging
        client_ip: Client IP for logging
        user_agent: User agent for logging

    Raises:
        HTTPException: If account is currently locked
    """
    if user.locked_until:
        now = datetime.now(timezone.utc)
        if user.locked_until > now:
            # Account is locked
            remaining_minutes = int((user.locked_until - now).total_seconds() / 60)
            security_logger.log_login_failure(
                username=username,
                ip_address=client_ip,
                user_agent=user_agent,
                reason="account_locked"
            )
            logger.warning(f"Login attempt for locked account '{username}' - {remaining_minutes} min remaining")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Account is locked due to too many failed login attempts. Try again in {remaining_minutes} minutes.",
                headers={"WWW-Authenticate": "Bearer"},
            )


def handle_failed_login(user, db: Session, username: str, client_ip: str, user_agent: str, reason: str):
    """
    Handle failed login attempt - increment counter and potentially lock account.

    Args:
        user: User object from database
        db: Database session
        username: Username for logging
        client_ip: Client IP for logging
        user_agent: User agent for logging
        reason: Reason for failure (for logging)
    """
    user.failed_login_count += 1

    if user.failed_login_count >= LOCKOUT_THRESHOLD:
        # Lock the account
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
        db.commit()

        security_logger.log_security_event(
            event_type="account_locked",
            username=username,
            ip_address=client_ip,
            user_agent=user_agent,
            details=f"Account locked after {user.failed_login_count} failed login attempts"
        )
        logger.warning(f"Account '{username}' locked after {user.failed_login_count} failed login attempts")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Account locked due to too many failed login attempts. Try again in {LOCKOUT_DURATION_MINUTES} minutes.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    else:
        # Just increment counter
        db.commit()
        security_logger.log_login_failure(
            username=username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason=reason
        )
        logger.warning(f"Failed login attempt for '{username}' - attempt {user.failed_login_count}/{LOCKOUT_THRESHOLD}")


def handle_successful_login(user, db: Session):
    """
    Handle successful login - reset failed login counter and unlock account.

    Args:
        user: User object from database
        db: Database session
    """
    # Reset lockout fields on successful login
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)
    db.commit()


# ==============================================================================
# ROUTES
# ==============================================================================

@router.get("/status", response_model=AuthStatus)
async def get_auth_status():
    """
    Get authentication system status.

    Returns whether authentication is enabled and available.
    Useful for frontend to determine if login screen should be shown.
    """
    auth_required = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'

    if not auth_required:
        return AuthStatus(
            auth_required=False,
            jwt_available=JWT_AVAILABLE,
            message="Authentication disabled. Direct access allowed."
        )

    if not JWT_AVAILABLE:
        return AuthStatus(
            auth_required=True,
            jwt_available=False,
            message="Authentication required but JWT libraries not installed."
        )

    return AuthStatus(
        auth_required=True,
        jwt_available=True,
        message="Authentication enabled. Login required."
    )


def _rate_limit_login(func):
    """Apply rate limiting to login endpoint if available."""
    if RATE_LIMITING_AVAILABLE and limiter is not None:
        return limiter.limit(LOGIN_RATE_LIMIT)(func)
    return func


@router.post("/login", response_model=LoginResponse)
@_rate_limit_login
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login and get JWT access and refresh tokens.

    Rate limited to prevent brute force attacks (default: 5 attempts/minute per IP).

    Account lockout: After 10 failed login attempts, account is locked for 30 minutes.
    Counter resets on successful login.

    If user has 2FA enabled, returns requires_2fa=True instead of tokens.
    User must then call /login-2fa with username and TOTP code to complete login.

    Returns both a short-lived access token and a long-lived refresh token.
    - Access token: Used for API requests, expires quickly (default 15 min)
    - Refresh token: Used to get new access tokens without re-login (default 7 days)

    Args:
        request: FastAPI request (for client IP logging)
        form_data: OAuth2 form with username and password

    Returns:
        JWT access and refresh tokens, or requires_2fa indicator

    Raises:
        HTTPException 401: Invalid credentials or account locked
        HTTPException 503: JWT not available
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get('User-Agent')

    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not available. Install: pip install python-jose[cryptography] bcrypt"
        )

    from jutsu_engine.data.models import User

    # Find user
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user:
        security_logger.log_login_failure(
            username=form_data.username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="user_not_found"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if account is locked
    check_account_lockout(user, form_data.username, client_ip, user_agent)

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        handle_failed_login(user, db, form_data.username, client_ip, user_agent, "invalid_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        security_logger.log_login_failure(
            username=form_data.username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="account_disabled"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )

    # Check if user has passkeys registered - if so, offer passkey authentication
    # Passkey authentication bypasses 2FA (it IS the second factor)
    from jutsu_engine.data.models import Passkey
    passkey_count = db.query(Passkey).filter(Passkey.user_id == user.id).count()

    if passkey_count > 0:
        # Generate passkey authentication options
        try:
            from jutsu_engine.api.routes.passkey import (
                WEBAUTHN_AVAILABLE,
                WEBAUTHN_RP_ID,
                _authentication_challenges,
            )
            if WEBAUTHN_AVAILABLE:
                from webauthn import generate_authentication_options, options_to_json
                from webauthn.helpers.structs import (
                    PublicKeyCredentialDescriptor,
                    UserVerificationRequirement,
                )

                # Get user's passkey credentials
                passkeys = db.query(Passkey).filter(Passkey.user_id == user.id).all()
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
                _authentication_challenges[user.username] = options.challenge

                logger.info(f"User '{user.username}' has passkeys, offering passkey authentication")
                return LoginResponse(
                    requires_passkey=True,
                    passkey_options=options_to_json(options),
                    username=user.username,
                    token_type="bearer"
                )
        except Exception as e:
            logger.warning(f"Failed to generate passkey options: {e}, falling back to 2FA")

    # Check if 2FA is enabled - if so, don't issue tokens yet
    if user.totp_enabled:
        logger.info(f"User '{user.username}' requires 2FA verification")
        return LoginResponse(
            requires_2fa=True,
            username=user.username,
            token_type="bearer"
        )

    # Successful login - reset failed login counter and update last login
    handle_successful_login(user, db)

    # Create tokens
    token_data = {"sub": user.username}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)

    # Calculate expiration times in seconds
    access_expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_expires_in = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    # Log successful login
    security_logger.log_login_success(
        username=user.username,
        ip_address=client_ip,
        user_agent=user_agent
    )
    security_logger.log_token_created(
        username=user.username,
        token_type="access",
        ip_address=client_ip
    )
    security_logger.log_token_created(
        username=user.username,
        token_type="refresh",
        ip_address=client_ip
    )

    logger.info(f"User '{user.username}' logged in successfully")

    # Set refresh token in secure HTTP-only cookie if enabled
    if USE_SECURE_COOKIES:
        response.set_cookie(
            key=REFRESH_TOKEN_COOKIE_NAME,
            value=refresh_token,
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # Convert days to seconds
            httponly=True,  # Not accessible via JavaScript
            secure=COOKIE_SECURE,  # Require HTTPS
            samesite=COOKIE_SAMESITE,  # CSRF protection
            domain=COOKIE_DOMAIN,  # None = current domain only
            path="/api/auth",  # Only sent to auth endpoints
        )
        logger.info("Refresh token set in secure HTTP-only cookie")
        # Don't include refresh token in response body when using cookies
        return LoginResponse(
            access_token=access_token,
            refresh_token=None,  # Not in body when using secure cookies
            token_type="bearer",
            expires_in=access_expires_in,
            refresh_expires_in=refresh_expires_in
        )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=access_expires_in,
        refresh_expires_in=refresh_expires_in
    )


@router.post("/login-2fa", response_model=LoginResponse)
@_rate_limit_login
async def login_with_2fa(
    request: Request,
    response: Response,
    login_request: Login2FARequest,
    db: Session = Depends(get_db)
):
    """
    Complete login with 2FA verification.

    Called after initial login returns requires_2fa=True.
    Validates username, password, and TOTP code, then issues tokens.

    Account lockout: After 10 failed login attempts, account is locked for 30 minutes.
    Counter resets on successful login.

    Args:
        request: FastAPI request (for client IP logging)
        login_request: Login credentials with TOTP code

    Returns:
        JWT access and refresh tokens

    Raises:
        HTTPException 401: Invalid credentials, TOTP code, or account locked
        HTTPException 503: JWT not available
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get('User-Agent')

    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not available"
        )

    from jutsu_engine.data.models import User

    # Find and verify user (same as login endpoint)
    user = db.query(User).filter(User.username == login_request.username).first()

    if not user:
        security_logger.log_login_failure(
            username=login_request.username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="user_not_found"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or 2FA code",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if account is locked
    check_account_lockout(user, login_request.username, client_ip, user_agent)

    # Verify password
    if not verify_password(login_request.password, user.password_hash):
        handle_failed_login(user, db, login_request.username, client_ip, user_agent, "invalid_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or 2FA code",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )

    # Verify 2FA is actually enabled for this user
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled for this user. Use /login instead.",
        )

    # Verify TOTP code
    try:
        import pyotp
        totp = pyotp.TOTP(user.totp_secret)
        totp_valid = totp.verify(login_request.totp_code, valid_window=1)
    except Exception:
        totp_valid = False

    # If TOTP fails, try backup code
    backup_code_used = False
    if not totp_valid and user.backup_codes:
        # Normalize code format (remove hyphens for comparison)
        normalized_code = login_request.totp_code.replace('-', '').upper()
        codes = list(user.backup_codes)

        for i, stored_code in enumerate(codes):
            if stored_code.replace('-', '').upper() == normalized_code:
                # Remove used backup code
                codes.pop(i)
                user.backup_codes = codes
                backup_code_used = True
                totp_valid = True
                logger.warning(f"Backup code used for user '{user.username}'")
                break

    if not totp_valid:
        handle_failed_login(user, db, login_request.username, client_ip, user_agent, "invalid_2fa_code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or 2FA code",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Successful login - reset failed login counter and update last login
    handle_successful_login(user, db)

    # Create tokens
    token_data = {"sub": user.username}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)

    # Calculate expiration times in seconds
    access_expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_expires_in = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    # Log successful login with 2FA
    security_logger.log_login_success(
        username=user.username,
        ip_address=client_ip,
        user_agent=user_agent
    )
    security_logger.log_token_created(
        username=user.username,
        token_type="access",
        ip_address=client_ip
    )
    security_logger.log_token_created(
        username=user.username,
        token_type="refresh",
        ip_address=client_ip
    )

    logger.info(f"User '{user.username}' logged in successfully with 2FA")

    # Set refresh token in secure HTTP-only cookie if enabled
    if USE_SECURE_COOKIES:
        response.set_cookie(
            key=REFRESH_TOKEN_COOKIE_NAME,
            value=refresh_token,
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
            domain=COOKIE_DOMAIN,
            path="/api/auth",
        )
        return LoginResponse(
            access_token=access_token,
            refresh_token=None,
            token_type="bearer",
            expires_in=access_expires_in,
            refresh_expires_in=refresh_expires_in
        )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=access_expires_in,
        refresh_expires_in=refresh_expires_in
    )


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get current authenticated user information.

    Returns user info if authenticated, or anonymous info if auth disabled.
    """
    if current_user is None:
        # Auth disabled
        return UserInfo(
            username="anonymous",
            is_admin=True,
            email=None,
            last_login=None
        )

    return UserInfo(
        username=current_user.username,
        email=current_user.email,
        is_admin=current_user.is_admin,
        last_login=current_user.last_login.isoformat() if current_user.last_login else None
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Logout endpoint.

    Blacklists the current access token to prevent further use.
    Also clears refresh token cookie if secure cookies are enabled.

    Requires valid access token in Authorization header.
    """
    from jutsu_engine.data.models import BlacklistedToken

    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix

        # Decode token to get JTI and expiration
        payload = decode_access_token(token)
        if payload:
            jti = payload.get("jti")
            exp = payload.get("exp")

            # Only blacklist if token has JTI (new tokens)
            if jti and exp:
                # Convert expiration timestamp to datetime
                expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)

                # Get user for logging
                username = payload.get("sub")

                # Add to blacklist
                blacklisted = BlacklistedToken(
                    jti=jti,
                    token_type="access",
                    expires_at=expires_at,
                    user_id=None  # Could lookup user_id if needed
                )
                db.add(blacklisted)
                db.commit()

                logger.info(f"Token blacklisted for user '{username}': {jti}")

    # Clear refresh token cookie if enabled
    if USE_SECURE_COOKIES:
        response.delete_cookie(
            key=REFRESH_TOKEN_COOKIE_NAME,
            path="/api/auth",
            domain=COOKIE_DOMAIN,
            secure=COOKIE_SECURE,
            httponly=True,
            samesite=COOKIE_SAMESITE,
        )

    return {"message": "Logged out successfully. Your token has been revoked."}


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    token_request: Optional[RefreshTokenRequest] = None,
    refresh_token_cookie: Optional[str] = Cookie(None, alias=REFRESH_TOKEN_COOKIE_NAME),
    db: Session = Depends(get_db)
):
    """
    Refresh JWT access token using a valid refresh token.

    Submit a valid refresh token to receive a new access token.
    The refresh token itself is NOT rotated (same refresh token can be reused
    until it expires).

    Token sources (in priority order):
    1. Request body (token_request.refresh_token)
    2. HTTP-only cookie (if USE_SECURE_COOKIES is enabled)

    Args:
        request: FastAPI request (for client IP logging)
        token_request: Request body containing the refresh token (optional if using cookies)
        refresh_token_cookie: Refresh token from HTTP-only cookie (automatic)

    Returns:
        New JWT access token (refresh token not included)

    Raises:
        HTTPException 401: Invalid or expired refresh token
        HTTPException 503: JWT not available
    """
    client_ip = get_client_ip(request)

    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not available"
        )

    # Get refresh token from body or cookie
    refresh_token_value = None
    if token_request and token_request.refresh_token:
        refresh_token_value = token_request.refresh_token
    elif USE_SECURE_COOKIES and refresh_token_cookie:
        refresh_token_value = refresh_token_cookie

    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode and validate the refresh token
    payload = decode_access_token(refresh_token_value)

    if payload is None:
        security_logger.log_token_invalid(
            ip_address=client_ip,
            reason="invalid_or_expired_refresh_token"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify this is actually a refresh token
    token_type = payload.get("type")
    if token_type != "refresh":
        security_logger.log_token_invalid(
            ip_address=client_ip,
            reason="not_a_refresh_token"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Please use a refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    if not username:
        security_logger.log_token_invalid(
            ip_address=client_ip,
            reason="missing_subject_claim"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user still exists and is active
    from jutsu_engine.data.models import User
    user = db.query(User).filter(User.username == username).first()

    if not user or not user.is_active:
        security_logger.log_token_invalid(
            ip_address=client_ip,
            reason="user_not_found_or_inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create new access token only (don't rotate refresh token)
    new_access_token = create_access_token(data={"sub": username})
    access_expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # Log token refresh
    security_logger.log_token_refreshed(
        username=username,
        ip_address=client_ip
    )

    logger.info(f"Token refreshed for user '{username}'")

    return Token(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=access_expires_in
    )
