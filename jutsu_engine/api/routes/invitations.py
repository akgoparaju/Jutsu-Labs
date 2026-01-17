"""
Invitation Management API Routes.

Public endpoints for invitation acceptance:
- GET /api/invitations/{token} - Validate invitation token
- POST /api/invitations/{token}/accept - Accept invitation and create account

These endpoints are PUBLIC (no authentication required) because
new users need to access them before they have an account.

Security Features:
- Tokens expire after 48 hours
- Single-use (marked as used after acceptance)
- Cryptographically random tokens
- Rate limiting (via main.py limiter)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from jutsu_engine.api.dependencies import (
    get_db,
    get_password_hash,
)
from jutsu_engine.data.models import User, UserInvitation
from jutsu_engine.utils.security_logger import security_logger, get_client_ip
from jutsu_engine.utils.encryption import InvitationTokenManager

logger = logging.getLogger('API.INVITATIONS')

router = APIRouter(prefix="/api/invitations", tags=["invitations"])


# ==============================================================================
# SCHEMAS
# ==============================================================================

class InvitationValidateResponse(BaseModel):
    """Response for invitation validation."""
    valid: bool
    email: Optional[str] = None
    role: str
    expires_at: str


class AcceptInvitationRequest(BaseModel):
    """Request to accept an invitation and create account."""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    email: Optional[str] = Field(None, max_length=255)
    
    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        # Username should be alphanumeric with underscores
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        return v


class AcceptInvitationResponse(BaseModel):
    """Response after accepting an invitation."""
    success: bool
    username: str
    role: str
    message: str


# ==============================================================================
# PUBLIC ENDPOINTS (No authentication required)
# ==============================================================================

@router.get("/{token}", response_model=InvitationValidateResponse)
async def validate_invitation(
    token: str,
    db: Session = Depends(get_db)
):
    """
    Validate an invitation token (public endpoint).
    
    Use this to check if an invitation is valid before showing
    the registration form.
    
    Security:
        - Supports both hashed tokens (new) and plaintext (legacy)
        - Token is hashed and compared against stored hash
    """
    # Hash the input token for comparison
    token_hash = InvitationTokenManager.hash_token(token)
    
    # Try to find by hash first (new format)
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token_hash
    ).first()
    
    # Fallback to plaintext comparison (legacy tokens)
    if not invitation:
        invitation = db.query(UserInvitation).filter(
            UserInvitation.token == token
        ).first()
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invitation link"
        )
    
    if invitation.accepted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has already been used"
        )
    
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired"
        )
    
    return InvitationValidateResponse(
        valid=True,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at.isoformat()
    )


@router.post("/{token}/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    token: str,
    accept_request: AcceptInvitationRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Accept invitation and create account (public endpoint).
    
    Creates a new user account with the role assigned in the invitation.
    The invitation is marked as used and cannot be reused.
    
    Security:
        - Supports both hashed tokens (new) and plaintext (legacy)
        - Token is hashed and compared against stored hash
    """
    # Hash the input token for comparison
    token_hash = InvitationTokenManager.hash_token(token)
    
    # Try to find by hash first (new format)
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token_hash
    ).first()
    
    # Fallback to plaintext comparison (legacy tokens)
    if not invitation:
        invitation = db.query(UserInvitation).filter(
            UserInvitation.token == token
        ).first()
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invitation link"
        )
    
    if invitation.accepted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has already been used"
        )
    
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired"
        )
    
    # Check username uniqueness
    existing = db.query(User).filter(User.username == accept_request.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
    
    # Check email uniqueness if provided
    email = accept_request.email or invitation.email
    if email:
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Create user
    new_user = User(
        username=accept_request.username,
        password_hash=get_password_hash(accept_request.password),
        email=email,
        role=invitation.role,
        is_active=True,
        created_at=datetime.now(timezone.utc),  # Explicit for PostgreSQL compatibility
    )
    db.add(new_user)
    db.flush()  # Get the user ID
    
    # Mark invitation as used
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.accepted_by = new_user.id
    
    db.commit()
    
    # Log security event
    logger.info(
        f"New user '{accept_request.username}' created with role '{invitation.role}' "
        f"via invitation from IP {get_client_ip(request)}"
    )
    
    return AcceptInvitationResponse(
        success=True,
        username=new_user.username,
        role=new_user.role,
        message="Account created successfully. You can now log in."
    )
