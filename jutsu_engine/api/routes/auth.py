"""
Authentication API routes for JWT-based login.

Provides:
- POST /auth/login: Login and get JWT token
- POST /auth/refresh: Refresh JWT token
- GET /auth/me: Get current user info
- POST /auth/logout: Logout (client-side token removal)
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from jutsu_engine.api.dependencies import (
    get_db,
    create_access_token,
    verify_password,
    get_current_user,
    JWT_AVAILABLE,
)

logger = logging.getLogger('API.AUTH')

router = APIRouter(prefix="/api/auth", tags=["authentication"])


# ==============================================================================
# SCHEMAS
# ==============================================================================

class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until expiry


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


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login and get JWT access token.

    Args:
        form_data: OAuth2 form with username and password

    Returns:
        JWT access token

    Raises:
        HTTPException 401: Invalid credentials
        HTTPException 503: JWT not available
    """
    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not available. Install: pip install python-jose[cryptography] bcrypt"
        )

    from jutsu_engine.data.models import User

    # Find user
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user:
        logger.warning(f"Login failed: user '{form_data.username}' not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        logger.warning(f"Login failed: invalid password for user '{form_data.username}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login failed: user '{form_data.username}' is disabled")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    # Create token
    access_token = create_access_token(data={"sub": user.username})

    # 7 days in seconds
    expires_in = 7 * 24 * 60 * 60

    logger.info(f"User '{user.username}' logged in successfully")

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in
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
async def logout():
    """
    Logout endpoint.

    JWT tokens are stateless, so this is mainly for client-side cleanup.
    Returns success message - client should discard the token.
    """
    return {"message": "Logged out successfully. Please discard your access token."}


@router.post("/refresh", response_model=Token)
async def refresh_token(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Refresh JWT access token.

    Requires valid (not expired) current token.
    Returns new token with fresh expiry time.
    """
    if current_user is None:
        # Auth disabled, nothing to refresh
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is disabled"
        )

    # Create new token
    access_token = create_access_token(data={"sub": current_user.username})

    # 7 days in seconds
    expires_in = 7 * 24 * 60 * 60

    logger.info(f"Token refreshed for user '{current_user.username}'")

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in
    )
