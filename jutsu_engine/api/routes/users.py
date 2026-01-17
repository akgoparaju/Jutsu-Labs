"""
User Management API Routes.

Provides endpoints for admin to manage users:
- GET /api/users - List all users
- POST /api/users/invite - Create invitation link
- GET /api/users/{id} - Get user details
- PUT /api/users/{id} - Update user (role, active status)
- DELETE /api/users/{id} - Delete user

Self-service endpoints (any authenticated user):
- PUT /api/users/me/password - Change own password

Security Features:
- Admin-only access for user management
- Password hashing with bcrypt
- Security event logging
- 20 user maximum limit
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from jutsu_engine.api.dependencies import (
    get_db,
    get_current_user,
    require_admin,
    verify_password,
    get_password_hash,
)
from jutsu_engine.data.models import User, UserInvitation
from jutsu_engine.utils.security_logger import security_logger, get_client_ip
from jutsu_engine.utils.encryption import InvitationTokenManager

logger = logging.getLogger('API.USERS')

router = APIRouter(prefix="/api/users", tags=["users"])

# Configuration
MAX_USERS = 20
INVITATION_EXPIRY_HOURS = 48


# ==============================================================================
# SCHEMAS
# ==============================================================================

class UserResponse(BaseModel):
    """User information returned from API."""
    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    last_login: Optional[str] = None
    created_at: Optional[str] = None
    totp_enabled: bool = False


class UserListResponse(BaseModel):
    """Response for list users endpoint."""
    users: List[UserResponse]
    total: int
    limit: int


class CreateInvitationRequest(BaseModel):
    """Request to create a new user invitation."""
    email: Optional[str] = Field(None, description="Optional email hint for the invitation")
    role: str = Field("viewer", description="Role for the new user")
    
    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v not in ["admin", "viewer"]:
            raise ValueError("Role must be 'admin' or 'viewer'")
        return v


class InvitationResponse(BaseModel):
    """Response after creating an invitation."""
    token: str
    invite_url: str
    expires_at: str
    role: str


class ChangePasswordRequest(BaseModel):
    """Request to change own password."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class UpdateUserRequest(BaseModel):
    """Request to update user details (admin only)."""
    role: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v is not None and v not in ["admin", "viewer"]:
            raise ValueError("Role must be 'admin' or 'viewer'")
        return v


class InvitationInfo(BaseModel):
    """Invitation information for admin listing."""
    id: int
    email: Optional[str] = None
    role: str
    token: str
    expires_at: str
    created_at: str
    accepted: bool
    accepted_at: Optional[str] = None
    invited_by_username: str


class InvitationsListResponse(BaseModel):
    """Response for list invitations endpoint."""
    invitations: List[InvitationInfo]
    total: int


# ==============================================================================
# ADMIN ENDPOINTS
# ==============================================================================

@router.get("", response_model=UserListResponse)
async def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all users (admin only).
    
    Returns all users with their role, status, and last login info.
    """
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    return UserListResponse(
        users=[
            UserResponse(
                id=u.id,
                username=u.username,
                email=u.email,
                role=u.role,
                is_active=u.is_active,
                last_login=u.last_login.isoformat() if u.last_login else None,
                created_at=u.created_at.isoformat() if u.created_at else None,
                totp_enabled=u.totp_enabled or False,
            )
            for u in users
        ],
        total=len(users),
        limit=MAX_USERS
    )


@router.post("/invite", response_model=InvitationResponse)
async def create_invitation(
    invite_request: CreateInvitationRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Create invitation link for new user (admin only).
    
    Generates a secure single-use invitation link that expires in 48 hours.
    The new user sets their own username and password via the link.
    
    Security:
        - Token is SHA-256 hashed before storage (plaintext never stored)
        - Plaintext token returned to admin for sharing, hash stored in DB
    """
    # Check user limit
    user_count = db.query(User).count()
    if user_count >= MAX_USERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum user limit ({MAX_USERS}) reached"
        )
    
    # Generate secure token and its hash
    plaintext_token, hashed_token = InvitationTokenManager.generate_token()
    
    # Create invitation with hashed token
    invitation = UserInvitation(
        email=invite_request.email,
        token=hashed_token,  # Store hash, not plaintext
        role=invite_request.role,
        created_by=current_user.id if current_user else None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITATION_EXPIRY_HOURS)
    )
    db.add(invitation)
    db.commit()
    
    # Generate invite URL (frontend will handle this route)
    # Get the origin from request headers or use a default
    origin = request.headers.get('Origin', '')
    if not origin:
        # Fallback to constructing from host
        scheme = request.headers.get('X-Forwarded-Proto', 'http')
        host = request.headers.get('Host', 'localhost')
        origin = f"{scheme}://{host}"
    
    invite_url = f"{origin}/accept-invitation?token={plaintext_token}"
    
    # Log security event
    logger.info(
        f"Invitation created by {current_user.username if current_user else 'system'} "
        f"for role '{invite_request.role}'"
    )
    
    return InvitationResponse(
        token=plaintext_token,  # Return plaintext for sharing
        invite_url=invite_url,
        expires_at=invitation.expires_at.isoformat(),
        role=invitation.role
    )


@router.get("/invitations", response_model=InvitationsListResponse)
async def list_invitations(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all invitations (admin only).

    Returns all invitations with their status, including:
    - Pending (not yet accepted, not expired)
    - Accepted (used to create account)
    - Expired (not accepted within 48 hours)
    """
    invitations = db.query(UserInvitation).order_by(
        UserInvitation.created_at.desc()
    ).all()

    invitation_list = []
    for inv in invitations:
        # Get the username of who created this invitation
        invited_by = "system"
        if inv.created_by:
            creator = db.query(User).filter(User.id == inv.created_by).first()
            if creator:
                invited_by = creator.username

        invitation_list.append(InvitationInfo(
            id=inv.id,
            email=inv.email,
            role=inv.role,
            token=inv.token,
            expires_at=inv.expires_at.isoformat(),
            created_at=inv.created_at.isoformat() if inv.created_at else "",
            accepted=inv.accepted_at is not None,
            accepted_at=inv.accepted_at.isoformat() if inv.accepted_at else None,
            invited_by_username=invited_by,
        ))

    return InvitationsListResponse(
        invitations=invitation_list,
        total=len(invitation_list)
    )


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Revoke (delete) an invitation (admin only).

    Can only revoke invitations that haven't been accepted yet.
    """
    invitation = db.query(UserInvitation).filter(
        UserInvitation.id == invitation_id
    ).first()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )

    if invitation.accepted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke an invitation that has already been accepted"
        )

    db.delete(invitation)
    db.commit()

    logger.info(
        f"Invitation {invitation_id} revoked by "
        f"{current_user.username if current_user else 'system'}"
    )

    return {"message": "Invitation revoked successfully"}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get user details by ID (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        last_login=user.last_login.isoformat() if user.last_login else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
        totp_enabled=user.totp_enabled or False,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    update_request: UpdateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Update user details (admin only).
    
    Can update role and active status.
    Admin cannot demote themselves.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admin from demoting themselves
    if current_user and user.id == current_user.id:
        if update_request.role and update_request.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change your own role"
            )
        if update_request.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account"
            )
    
    # Apply updates
    if update_request.role is not None:
        user.role = update_request.role
        logger.info(f"User {user.username} role changed to {update_request.role}")
    
    if update_request.is_active is not None:
        user.is_active = update_request.is_active
        logger.info(f"User {user.username} active status changed to {update_request.is_active}")
    
    db.commit()
    db.refresh(user)
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        last_login=user.last_login.isoformat() if user.last_login else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
        totp_enabled=user.totp_enabled or False,
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Delete a user (admin only).
    
    Admin cannot delete themselves.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admin from deleting themselves
    if current_user and user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    username = user.username
    db.delete(user)
    db.commit()
    
    logger.warning(f"User {username} deleted by {current_user.username if current_user else 'system'}")
    
    return {"message": f"User {username} deleted successfully"}


# ==============================================================================
# SELF-SERVICE ENDPOINTS
# ==============================================================================

@router.put("/me/password")
async def change_own_password(
    password_request: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Change own password (any authenticated user).
    
    Requires current password for verification.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    # Verify current password
    if not verify_password(password_request.current_password, current_user.password_hash):
        security_logger.log_access_denied(
            resource="password_change",
            username=current_user.username,
            ip_address=get_client_ip(request),
            reason="incorrect_current_password"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )
    
    # Update password
    current_user.password_hash = get_password_hash(password_request.new_password)
    db.commit()
    
    logger.info(f"User {current_user.username} changed their password")
    
    return {"message": "Password changed successfully"}
