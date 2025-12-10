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
"""

import os
import logging
from datetime import datetime, timezone
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
    """Login response - either tokens or 2FA required indicator."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    refresh_expires_in: Optional[int] = None
    requires_2fa: bool = False
    username: Optional[str] = None  # Included when 2FA is required


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
        HTTPException 401: Invalid credentials
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

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        security_logger.log_login_failure(
            username=form_data.username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="invalid_password"
        )
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

    # Check if 2FA is enabled - if so, don't issue tokens yet
    if user.totp_enabled:
        logger.info(f"User '{user.username}' requires 2FA verification")
        return LoginResponse(
            requires_2fa=True,
            username=user.username,
            token_type="bearer"
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

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

    Args:
        request: FastAPI request (for client IP logging)
        login_request: Login credentials with TOTP code

    Returns:
        JWT access and refresh tokens

    Raises:
        HTTPException 401: Invalid credentials or TOTP code
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

    # Verify password
    if not verify_password(login_request.password, user.password_hash):
        security_logger.log_login_failure(
            username=login_request.username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="invalid_password"
        )
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
        security_logger.log_login_failure(
            username=login_request.username,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="invalid_2fa_code"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or 2FA code",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

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
async def logout(response: Response):
    """
    Logout endpoint.

    JWT tokens are stateless, so this is mainly for client-side cleanup.
    If secure cookies are enabled, this clears the refresh token cookie.
    Returns success message - client should discard the access token.
    """
    if USE_SECURE_COOKIES:
        response.delete_cookie(
            key=REFRESH_TOKEN_COOKIE_NAME,
            path="/api/auth",
            domain=COOKIE_DOMAIN,
            secure=COOKIE_SECURE,
            httponly=True,
            samesite=COOKIE_SAMESITE,
        )

    return {"message": "Logged out successfully. Please discard your access token."}


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
