# Multi-User Access System Implementation Plan

**Version:** 1.0  
**Created:** 2026-01-13  
**Status:** Approved for Implementation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Requirements](#requirements)
3. [Security Architecture](#security-architecture)
4. [System Design](#system-design)
5. [Implementation Phases](#implementation-phases)
6. [Database Schema Changes](#database-schema-changes)
7. [API Endpoints](#api-endpoints)
8. [Frontend Components](#frontend-components)
9. [Testing Strategy](#testing-strategy)
10. [Rollback Plan](#rollback-plan)

---

## Executive Summary

### Objective
Implement a multi-user access system for the Jutsu Trading Dashboard that allows:
- Admin to invite viewer users via secure invitation links
- Viewers to see all dashboard tabs (read-only)
- Viewers restricted from executing trades, controlling engine, or managing scheduler
- Users to self-manage password and 2FA settings
- Future extensibility for investor tier

### Key Decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Role System | Role Enum with Permissions | Future-proof for investor tier without migration |
| Onboarding | Invite Links | Professional UX, self-service password setup |
| Admin Count | Single Admin | Simpler security model |
| Viewer Data | Paper Trading Only | Clear separation of concerns |
| User Limit | 20 users max | Resource management |

### Effort Estimate
**Total: 6-8 days**
- Phase 1 (Backend): 2-3 days
- Phase 2 (Frontend): 2 days
- Phase 3 (Invitation System): 2 days
- Testing & Polish: 1 day

---

## Requirements

### Functional Requirements

#### FR-1: User Roles
- **FR-1.1**: System supports two roles: `admin` and `viewer`
- **FR-1.2**: Admin has full access to all features
- **FR-1.3**: Viewer has read-only access to dashboard data

#### FR-2: Viewer Restrictions
| Feature | Admin | Viewer |
|---------|-------|--------|
| View Dashboard | ✅ | ✅ |
| View Performance | ✅ | ✅ |
| View Trades | ✅ | ✅ |
| View Decision Tree | ✅ | ✅ |
| View Config | ✅ | ✅ |
| View Settings | ✅ | ✅ |
| **Execute Trade** | ✅ | ❌ |
| **Engine Control** | ✅ | ❌ |
| **Scheduler Control** | ✅ | ❌ |
| **User Management** | ✅ | ❌ |
| **Config Modification** | ✅ | ❌ |
| Change Own Password | ✅ | ✅ |
| Manage Own 2FA | ✅ | ✅ |
| Manage Own Passkeys | ✅ | ✅ |

#### FR-3: User Onboarding
- **FR-3.1**: Admin generates invitation link with role assignment
- **FR-3.2**: Link contains secure, single-use token (48-hour expiry)
- **FR-3.3**: New user sets username and password via invitation link
- **FR-3.4**: 2FA setup is optional but encouraged

#### FR-4: User Management
- **FR-4.1**: Admin can list all users
- **FR-4.2**: Admin can create invitation links
- **FR-4.3**: Admin can deactivate/delete users
- **FR-4.4**: Admin cannot delete self (last admin protection)
- **FR-4.5**: Maximum 20 user accounts

#### FR-5: Data Visibility
- **FR-5.1**: Viewers always see paper trading data
- **FR-5.2**: Viewers cannot see live trading mode (even if engine running)

### Non-Functional Requirements

#### NFR-1: Security
- Passwords hashed with bcrypt (cost factor 12)
- JWT tokens with HMAC-SHA256 (HS256)
- Invitation tokens cryptographically random (32 bytes)
- All authorization enforced server-side

#### NFR-2: Performance
- Role check adds <5ms to request latency
- User list pagination for future scalability

#### NFR-3: Audit
- All admin actions logged to security audit trail
- Invitation creation/acceptance logged

---

## Security Architecture

### Current Implementation (Industry Standard)

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                          │
├─────────────────────────────────────────────────────────────────┤
│  Access Token (JWT)          │  Refresh Token                   │
│  - Stored: localStorage      │  - Stored: httpOnly cookie*      │
│  - Expiry: 15min (password)  │  - Expiry: 7 days               │
│           7hr (passkey)      │  - Secure, SameSite=Lax         │
│  - Contains: sub, exp, jti   │                                  │
│                              │  * OR localStorage if cookies    │
│                              │    disabled                      │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                        SERVER (FastAPI)                          │
├─────────────────────────────────────────────────────────────────┤
│  Password Storage:           │  Token Validation:               │
│  - Algorithm: bcrypt         │  - Verify signature (HS256)      │
│  - Cost factor: default      │  - Check expiry                  │
│  - Salt: per-password        │  - Check blacklist (JTI)         │
│                              │  - Fetch user role from DB       │
├─────────────────────────────────────────────────────────────────┤
│  Security Features:                                              │
│  - Rate limiting: 5 req/min on login                            │
│  - Account lockout: 10 failures → 30 min lock                   │
│  - Token blacklisting: JTI-based revocation on logout           │
│  - Security logging: All auth events to JSON audit trail        │
│  - CORS: Configurable origins                                   │
│  - HTTPS: Enforced via Cloudflare tunnel                        │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATABASE (PostgreSQL)                       │
├─────────────────────────────────────────────────────────────────┤
│  users table:                                                    │
│  - password_hash (bcrypt)    - Role (NEW)                       │
│  - totp_secret (encrypted)   - Lockout fields                   │
│  - passkeys (FK)             - Audit timestamps                 │
│                                                                  │
│  invitations table (NEW):                                        │
│  - Secure token (32 bytes)   - Expiry timestamp                 │
│  - Role assignment           - Usage tracking                   │
└─────────────────────────────────────────────────────────────────┘
```

### Role-Based Authorization Flow

```
Request with JWT
       │
       ▼
┌──────────────────┐
│ Verify JWT       │ ──────► 401 Unauthorized
│ (signature, exp) │   fail
└────────┬─────────┘
         │ pass
         ▼
┌──────────────────┐
│ Check Blacklist  │ ──────► 401 Token Revoked
│ (JTI lookup)     │   found
└────────┬─────────┘
         │ not found
         ▼
┌──────────────────┐
│ Load User from   │ ──────► 401 User Not Found
│ Database         │   fail
└────────┬─────────┘
         │ found
         ▼
┌──────────────────┐
│ Check Permission │ ──────► 403 Forbidden
│ (role → perms)   │   denied
└────────┬─────────┘
         │ granted
         ▼
    Process Request
```

### Permission Mapping (Code-Based)

```python
ROLE_PERMISSIONS = {
    "admin": {"*"},  # Wildcard = all permissions
    
    "viewer": {
        # Read operations
        "dashboard:read",
        "performance:read",
        "trades:read",
        "config:read",
        "indicators:read",
        "regime:read",
        "status:read",
        
        # Self-management
        "self:password",
        "self:2fa",
        "self:passkey",
    },
    
    # Future: Investor role
    # "investor": {
    #     ...viewer permissions,
    #     "portfolio:read",
    #     "portfolio:execute",
    # }
}
```

### Protected Permissions Matrix

| Permission | Endpoints | Description |
|------------|-----------|-------------|
| `engine:control` | `POST /control/start`, `/stop`, `/mode` | Start/stop engine, switch modes |
| `scheduler:control` | `POST /control/scheduler/*` | Enable/disable/trigger scheduler |
| `trades:execute` | `POST /trades/execute` | Manual trade execution |
| `users:manage` | `GET/POST/PUT/DELETE /users/*` | User CRUD operations |
| `config:write` | `PUT /config`, `DELETE /config/*` | Modify strategy config |
| `invitations:manage` | `POST /invitations`, `DELETE /invitations/*` | Create/revoke invitations |

---

## System Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           FRONTEND                                   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    AuthContext                               │   │
│  │  - user: { username, role }                                  │   │
│  │  - isAdmin: boolean                                          │   │
│  │  - hasPermission(perm): boolean                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│        ┌─────────────────────┼─────────────────────┐               │
│        ▼                     ▼                     ▼               │
│  ┌───────────┐        ┌───────────┐        ┌───────────┐          │
│  │ Dashboard │        │ Settings  │        │ Invite    │          │
│  │ (cond UI) │        │ (Users)   │        │ Accept    │          │
│  └───────────┘        └───────────┘        └───────────┘          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            BACKEND                                   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Authorization Layer                       │   │
│  │  @require_permission("engine:control")                       │   │
│  │  @require_admin                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│        │                     │                     │               │
│        ▼                     ▼                     ▼               │
│  ┌───────────┐        ┌───────────┐        ┌───────────┐          │
│  │ /control  │        │ /users    │        │/invitations│         │
│  │ /trades   │        │ /auth     │        │           │          │
│  └───────────┘        └───────────┘        └───────────┘          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           DATABASE                                   │
│  ┌───────────┐        ┌───────────┐        ┌───────────┐          │
│  │   users   │        │ passkeys  │        │invitations│          │
│  │  (+ role) │        │           │        │   (NEW)   │          │
│  └───────────┘        └───────────┘        └───────────┘          │
└─────────────────────────────────────────────────────────────────────┘
```

### Invitation Flow

```
Admin                    Backend                   New User
  │                         │                         │
  ├─── POST /invitations ──►│                         │
  │    {email, role}        │                         │
  │                         │                         │
  │◄── {invite_url, token} ─┤                         │
  │                         │                         │
  │                         │                         │
  │    (share link)         │                         │
  ├─────────────────────────┼────────────────────────►│
  │                         │                         │
  │                         │◄─ GET /invitations/{token}
  │                         │   (validate token)      │
  │                         │                         │
  │                         │─► {valid, email, role} ─┤
  │                         │                         │
  │                         │◄─ POST /invitations/{token}/accept
  │                         │   {username, password}  │
  │                         │                         │
  │                         │   (create user)         │
  │                         │   (mark invite used)    │
  │                         │                         │
  │                         │─► {success, user} ─────►│
  │                         │                         │
  │                         │◄─ POST /auth/login ─────┤
  │                         │   (normal login)        │
```

---

## Implementation Phases

### Phase 1: Backend Role System (2-3 days)

#### 1.1 Database Schema Updates

**File: `jutsu_engine/data/models.py`**

```python
# Add after imports
from enum import Enum as PyEnum

class UserRole(str, PyEnum):
    """User roles for access control."""
    ADMIN = "admin"
    VIEWER = "viewer"
    # INVESTOR = "investor"  # Future


class User(Base):
    # ... existing fields ...
    
    # NEW: Role field (replaces is_admin logic)
    role = Column(String(20), default="viewer", nullable=False, index=True)
    
    # Keep is_admin as computed property for backward compatibility
    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class UserInvitation(Base):
    """Invitation for new user registration."""
    __tablename__ = 'user_invitations'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Invitation details
    email = Column(String(255), nullable=True)  # Optional email hint
    token = Column(String(64), unique=True, nullable=False, index=True)
    role = Column(String(20), default="viewer", nullable=False)
    
    # Tracking
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    
    # Usage
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    acceptor = relationship("User", foreign_keys=[accepted_by])
```

#### 1.2 Permission System

**File: `jutsu_engine/api/dependencies.py`**

```python
# Add permission constants and helpers

ROLE_PERMISSIONS = {
    "admin": {"*"},
    "viewer": {
        "dashboard:read", "performance:read", "trades:read",
        "config:read", "indicators:read", "regime:read",
        "status:read", "self:password", "self:2fa", "self:passkey"
    },
}

def has_permission(user, permission: str) -> bool:
    """Check if user has a specific permission."""
    if user is None:
        return False
    role_perms = ROLE_PERMISSIONS.get(user.role, set())
    return "*" in role_perms or permission in role_perms


def require_permission(permission: str):
    """Dependency that requires a specific permission."""
    async def check_permission(
        current_user = Depends(get_current_user),
        db: Session = Depends(get_db)
    ):
        if current_user is None:
            # Auth disabled - allow all
            return current_user
        
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {permission}"
            )
        return current_user
    return check_permission


def require_admin(current_user = Depends(get_current_user)):
    """Dependency that requires admin role."""
    if current_user is None:
        return current_user  # Auth disabled
    
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
```

#### 1.3 Protected Endpoints

**Files to modify:**
- `jutsu_engine/api/routes/trades.py` - Protect execute endpoint
- `jutsu_engine/api/routes/control.py` - Protect all control endpoints
- `jutsu_engine/api/routes/config.py` - Protect write endpoints

Example for trades.py:
```python
from jutsu_engine.api.dependencies import require_permission

@router.post("/execute")
async def execute_trade(
    request: ExecuteTradeRequest,
    current_user = Depends(require_permission("trades:execute")),
    db: Session = Depends(get_db)
):
    # ... existing implementation
```

#### 1.4 User Management API

**New File: `jutsu_engine/api/routes/users.py`**

```python
"""
User Management API

Endpoints for admin to manage users:
- GET /api/users - List all users
- POST /api/users/invite - Create invitation link
- GET /api/users/{id} - Get user details
- PUT /api/users/{id} - Update user
- DELETE /api/users/{id} - Delete user

Self-service endpoints (any authenticated user):
- PUT /api/users/me/password - Change own password
"""

router = APIRouter(prefix="/api/users", tags=["users"])

MAX_USERS = 20

@router.get("")
async def list_users(
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all users (admin only)."""
    users = db.query(User).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "totp_enabled": u.totp_enabled,
            }
            for u in users
        ],
        "total": len(users),
        "limit": MAX_USERS
    }


@router.post("/invite")
async def create_invitation(
    invite_request: CreateInvitationRequest,
    request: Request,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create invitation link for new user (admin only)."""
    # Check user limit
    user_count = db.query(User).count()
    if user_count >= MAX_USERS:
        raise HTTPException(400, f"Maximum user limit ({MAX_USERS}) reached")
    
    # Generate secure token
    token = secrets.token_urlsafe(32)
    
    # Create invitation
    invitation = UserInvitation(
        email=invite_request.email,
        token=token,
        role=invite_request.role or "viewer",
        created_by=current_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48)
    )
    db.add(invitation)
    db.commit()
    
    # Generate invite URL
    base_url = str(request.base_url).rstrip('/')
    invite_url = f"{base_url}/accept-invite/{token}"
    
    # Log security event
    security_logger.log_security_event(
        event_type="invitation_created",
        username=current_user.username,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get('User-Agent'),
        details=f"Invitation created for role '{invite_request.role}'"
    )
    
    return {
        "token": token,
        "invite_url": invite_url,
        "expires_at": invitation.expires_at.isoformat(),
        "role": invitation.role
    }


@router.put("/me/password")
async def change_own_password(
    password_request: ChangePasswordRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change own password (any authenticated user)."""
    # Verify current password
    if not verify_password(password_request.current_password, current_user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    
    # Update password
    current_user.password_hash = get_password_hash(password_request.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}
```

#### 1.5 Invitation Acceptance API

**New File: `jutsu_engine/api/routes/invitations.py`**

```python
"""
Invitation Management API

Public endpoints for invitation acceptance:
- GET /api/invitations/{token} - Validate invitation
- POST /api/invitations/{token}/accept - Accept and create account
"""

router = APIRouter(prefix="/api/invitations", tags=["invitations"])


@router.get("/{token}")
async def validate_invitation(token: str, db: Session = Depends(get_db)):
    """Validate an invitation token (public endpoint)."""
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token
    ).first()
    
    if not invitation:
        raise HTTPException(404, "Invalid invitation link")
    
    if invitation.accepted_at:
        raise HTTPException(400, "Invitation has already been used")
    
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invitation has expired")
    
    return {
        "valid": True,
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": invitation.expires_at.isoformat()
    }


@router.post("/{token}/accept")
async def accept_invitation(
    token: str,
    accept_request: AcceptInvitationRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Accept invitation and create account (public endpoint)."""
    # Validate invitation
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token
    ).first()
    
    if not invitation:
        raise HTTPException(404, "Invalid invitation link")
    
    if invitation.accepted_at:
        raise HTTPException(400, "Invitation has already been used")
    
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invitation has expired")
    
    # Check username uniqueness
    existing = db.query(User).filter(User.username == accept_request.username).first()
    if existing:
        raise HTTPException(400, "Username already taken")
    
    # Create user
    new_user = User(
        username=accept_request.username,
        password_hash=get_password_hash(accept_request.password),
        email=invitation.email or accept_request.email,
        role=invitation.role,
        is_active=True
    )
    db.add(new_user)
    
    # Mark invitation as used
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.accepted_by = new_user.id
    
    db.commit()
    
    # Log security event
    security_logger.log_security_event(
        event_type="invitation_accepted",
        username=new_user.username,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get('User-Agent'),
        details=f"New user created with role '{new_user.role}'"
    )
    
    return {
        "success": True,
        "username": new_user.username,
        "role": new_user.role,
        "message": "Account created successfully. You can now log in."
    }
```

#### 1.6 Database Migration

**File: `alembic/versions/YYYYMMDD_add_user_roles.py`**

```python
"""Add user roles and invitations

Revision ID: xxx
Create Date: 2026-01-13
"""

from alembic import op
import sqlalchemy as sa


def upgrade():
    # Add role column to users
    op.add_column('users', sa.Column('role', sa.String(20), nullable=True))
    
    # Set default role for existing users
    op.execute("UPDATE users SET role = 'admin' WHERE role IS NULL")
    
    # Make role non-nullable
    op.alter_column('users', 'role', nullable=False)
    
    # Add index
    op.create_index('ix_users_role', 'users', ['role'])
    
    # Create invitations table
    op.create_table(
        'user_invitations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('token', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('role', sa.String(20), nullable=False, default='viewer'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
    )


def downgrade():
    op.drop_table('user_invitations')
    op.drop_index('ix_users_role', 'users')
    op.drop_column('users', 'role')
```

---

### Phase 2: Frontend Access Control (2 days)

#### 2.1 Auth Context Enhancement

**File: `dashboard/src/contexts/AuthContext.tsx`**

```typescript
// Add to AuthState interface
interface AuthState {
  user: UserInfo | null
  isAuthenticated: boolean
  isAdmin: boolean  // Computed from user.role
  hasPermission: (permission: string) => boolean
  // ... existing fields
}

// Add permission check function
const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  admin: new Set(['*']),
  viewer: new Set([
    'dashboard:read', 'performance:read', 'trades:read',
    'config:read', 'indicators:read', 'regime:read',
    'self:password', 'self:2fa', 'self:passkey'
  ])
}

const hasPermission = useCallback((permission: string): boolean => {
  if (!user) return false
  const perms = ROLE_PERMISSIONS[user.role] || new Set()
  return perms.has('*') || perms.has(permission)
}, [user])

// Update UserInfo interface
interface UserInfo {
  username: string
  email?: string
  role: 'admin' | 'viewer'
  last_login?: string
}

// Compute isAdmin
const isAdmin = useMemo(() => user?.role === 'admin', [user])
```

#### 2.2 Dashboard Conditional Rendering

**File: `dashboard/src/pages/Dashboard.tsx`**

```tsx
function Dashboard() {
  const { hasPermission, isAdmin } = useAuth()
  
  // ... existing code ...
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Jutsu Trader</h2>
        
        {/* Only show Execute Trade button for admin */}
        {hasPermission('trades:execute') && (
          <button
            onClick={() => setShowTradeModal(true)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg"
          >
            Execute Trade
          </button>
        )}
      </div>
      
      {/* Only show Engine Control for admin */}
      {hasPermission('engine:control') && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Engine Control</h3>
          {/* ... engine control UI ... */}
        </div>
      )}
      
      {/* Show read-only status for viewers */}
      {!isAdmin && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Engine Status</h3>
          <div className="flex items-center gap-2">
            <span className={`w-3 h-3 rounded-full ${
              status?.is_running ? 'bg-green-500' : 'bg-gray-500'
            }`} />
            <span>
              {status?.is_running ? 'Running' : 'Stopped'} - 
              {status?.mode === 'offline_mock' ? ' Paper Trading' : ' Live'}
            </span>
          </div>
        </div>
      )}
      
      {/* ... rest of dashboard (visible to all) ... */}
      
      {/* Only show Scheduler Control for admin */}
      {hasPermission('scheduler:control') && <SchedulerControl />}
    </div>
  )
}
```

#### 2.3 Settings Page Enhancement

**File: `dashboard/src/pages/Settings.tsx`**

```tsx
function Settings() {
  const { user, isAdmin } = useAuth()
  
  return (
    <div className="space-y-8">
      {/* Account Information (all users) */}
      <section className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <h3 className="text-lg font-semibold mb-4">Account Information</h3>
        {/* ... existing account info ... */}
        <div className="mt-2">
          <span className="text-gray-400">Role: </span>
          <span className={`px-2 py-1 rounded text-sm ${
            user?.role === 'admin' 
              ? 'bg-purple-600 text-white' 
              : 'bg-slate-600 text-gray-200'
          }`}>
            {user?.role === 'admin' ? 'Administrator' : 'Viewer'}
          </span>
        </div>
      </section>
      
      {/* Security Settings (all users) */}
      <section className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <h3 className="text-lg font-semibold mb-4">Security</h3>
        <TwoFactorSettings />
        <PasskeySettings />
        <ChangePassword />  {/* New component */}
      </section>
      
      {/* User Management (admin only) */}
      {isAdmin && (
        <section className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">User Management</h3>
          <UserManagement />
        </section>
      )}
    </div>
  )
}
```

#### 2.4 New Components

**File: `dashboard/src/components/UserManagement.tsx`**

```tsx
function UserManagement() {
  const [users, setUsers] = useState<User[]>([])
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  
  // ... fetch users, handle invite, etc.
  
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="text-gray-400">
          {users.length} / 20 users
        </span>
        <button
          onClick={() => setShowInviteModal(true)}
          disabled={users.length >= 20}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50"
        >
          Invite User
        </button>
      </div>
      
      {/* User list table */}
      <table className="w-full">
        <thead>
          <tr className="text-left text-gray-400 border-b border-slate-700">
            <th className="pb-2">Username</th>
            <th className="pb-2">Role</th>
            <th className="pb-2">2FA</th>
            <th className="pb-2">Last Login</th>
            <th className="pb-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map(user => (
            <tr key={user.id} className="border-b border-slate-700/50">
              <td className="py-3">{user.username}</td>
              <td className="py-3">
                <span className={`px-2 py-1 rounded text-xs ${
                  user.role === 'admin' ? 'bg-purple-600' : 'bg-slate-600'
                }`}>
                  {user.role}
                </span>
              </td>
              <td className="py-3">
                {user.totp_enabled ? '✓' : '—'}
              </td>
              <td className="py-3 text-gray-400">
                {user.last_login 
                  ? new Date(user.last_login).toLocaleDateString() 
                  : 'Never'}
              </td>
              <td className="py-3">
                {user.role !== 'admin' && (
                  <button
                    onClick={() => handleDeleteUser(user.id)}
                    className="text-red-400 hover:text-red-300"
                  >
                    Remove
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      
      {/* Invite Modal */}
      <InviteUserModal
        isOpen={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        onSuccess={(link) => setInviteLink(link)}
      />
      
      {/* Invite Link Display */}
      {inviteLink && (
        <div className="p-4 bg-green-900/30 border border-green-600 rounded-lg">
          <p className="text-green-400 font-medium mb-2">Invitation Link Created</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-slate-900 px-3 py-2 rounded text-sm">
              {inviteLink}
            </code>
            <button
              onClick={() => navigator.clipboard.writeText(inviteLink)}
              className="px-3 py-2 bg-slate-700 rounded hover:bg-slate-600"
            >
              Copy
            </button>
          </div>
          <p className="text-sm text-gray-400 mt-2">
            Share this link with the new user. Expires in 48 hours.
          </p>
        </div>
      )}
    </div>
  )
}
```

**File: `dashboard/src/pages/AcceptInvite.tsx`**

```tsx
function AcceptInvite() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  
  const [invitation, setInvitation] = useState<Invitation | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  
  // Validate invitation on load
  useEffect(() => {
    validateInvitation()
  }, [token])
  
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    
    try {
      await api.post(`/invitations/${token}/accept`, {
        username,
        password
      })
      navigate('/login?registered=true')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create account')
    }
  }
  
  // ... render form
}
```

---

### Phase 3: Invitation System (2 days)

Covered in Phase 1 backend and Phase 2 frontend implementations above.

---

## Database Schema Changes

### Final Schema

```
┌─────────────────────────────────────────────────────────────────┐
│                          users                                   │
├─────────────────────────────────────────────────────────────────┤
│  id              │ INTEGER PRIMARY KEY                          │
│  username        │ VARCHAR(50) NOT NULL UNIQUE                  │
│  password_hash   │ VARCHAR(255) NOT NULL                        │
│  email           │ VARCHAR(255) UNIQUE                          │
│  role            │ VARCHAR(20) NOT NULL DEFAULT 'viewer' [NEW]  │
│  is_active       │ BOOLEAN DEFAULT TRUE                         │
│  failed_login_count │ INTEGER DEFAULT 0                         │
│  locked_until    │ DATETIME                                     │
│  last_login      │ DATETIME                                     │
│  created_at      │ DATETIME                                     │
│  totp_secret     │ VARCHAR(32)                                  │
│  totp_enabled    │ BOOLEAN DEFAULT FALSE                        │
│  backup_codes    │ JSON                                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     user_invitations [NEW]                       │
├─────────────────────────────────────────────────────────────────┤
│  id              │ INTEGER PRIMARY KEY                          │
│  email           │ VARCHAR(255)                                 │
│  token           │ VARCHAR(64) NOT NULL UNIQUE                  │
│  role            │ VARCHAR(20) NOT NULL DEFAULT 'viewer'        │
│  created_by      │ INTEGER FK → users.id                        │
│  created_at      │ DATETIME                                     │
│  expires_at      │ DATETIME NOT NULL                            │
│  accepted_at     │ DATETIME                                     │
│  accepted_by     │ INTEGER FK → users.id                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## API Endpoints

### New Endpoints Summary

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/users` | Admin | List all users |
| POST | `/api/users/invite` | Admin | Create invitation |
| GET | `/api/users/{id}` | Admin | Get user details |
| PUT | `/api/users/{id}` | Admin | Update user |
| DELETE | `/api/users/{id}` | Admin | Delete user |
| PUT | `/api/users/me/password` | Any | Change own password |
| GET | `/api/invitations/{token}` | None | Validate invitation |
| POST | `/api/invitations/{token}/accept` | None | Accept invitation |

### Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/trades/execute` | Add `require_permission("trades:execute")` |
| `POST /api/control/start` | Add `require_permission("engine:control")` |
| `POST /api/control/stop` | Add `require_permission("engine:control")` |
| `POST /api/control/mode` | Add `require_permission("engine:control")` |
| `POST /api/control/scheduler/*` | Add `require_permission("scheduler:control")` |
| `PUT /api/config` | Add `require_permission("config:write")` |
| `DELETE /api/config/*` | Add `require_permission("config:write")` |
| `GET /api/auth/me` | Include `role` in response |

---

## Frontend Components

### New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `UserManagement` | `components/UserManagement.tsx` | User list and management |
| `InviteUserModal` | `components/InviteUserModal.tsx` | Create invitation |
| `ChangePassword` | `components/ChangePassword.tsx` | Self-service password change |
| `AcceptInvite` | `pages/AcceptInvite.tsx` | Invitation acceptance flow |

### Modified Components

| Component | Changes |
|-----------|---------|
| `AuthContext.tsx` | Add `role`, `isAdmin`, `hasPermission()` |
| `Dashboard.tsx` | Conditional rendering of controls |
| `Settings.tsx` | Add User Management section |
| `App.tsx` | Add `/accept-invite/:token` route |
| `Layout.tsx` | Optional: Show role badge |

---

## Testing Strategy

### Unit Tests

- Permission helper functions
- Role validation logic
- Token generation/validation

### Integration Tests

```python
# test_user_management.py

def test_admin_can_create_invitation():
    # Login as admin
    # POST /users/invite
    # Verify token returned

def test_viewer_cannot_create_invitation():
    # Login as viewer
    # POST /users/invite
    # Expect 403 Forbidden

def test_viewer_cannot_execute_trade():
    # Login as viewer
    # POST /trades/execute
    # Expect 403 Forbidden

def test_invitation_acceptance():
    # Create invitation as admin
    # GET /invitations/{token} - validate
    # POST /invitations/{token}/accept
    # Verify user created with correct role

def test_invitation_expiry():
    # Create invitation
    # Wait for expiry (or mock time)
    # POST /invitations/{token}/accept
    # Expect 400 Bad Request
```

### E2E Tests (Playwright)

```typescript
// test_multi_user.spec.ts

test('admin can invite viewer', async ({ page }) => {
  // Login as admin
  // Navigate to Settings
  // Click Invite User
  // Copy link
  // Logout
  // Navigate to invite link
  // Complete registration
  // Login as new user
  // Verify restricted access
})

test('viewer cannot see engine controls', async ({ page }) => {
  // Login as viewer
  // Navigate to Dashboard
  // Verify Engine Control section hidden
  // Verify Execute Trade button hidden
})
```

---

## Rollback Plan

### Phase 1 Rollback (Backend)
```bash
# Revert migration
alembic downgrade -1

# Restore original routes (git checkout)
git checkout HEAD~1 -- jutsu_engine/api/routes/
```

### Phase 2 Rollback (Frontend)
```bash
# Revert frontend changes
git checkout HEAD~1 -- dashboard/src/
```

### Emergency Rollback
If critical issues discovered post-deployment:
1. Disable AUTH_REQUIRED temporarily
2. Revert to single-admin mode
3. Investigate and fix issues
4. Re-enable with fix

---

## Appendix: File Changes Summary

### New Files
- `jutsu_engine/api/routes/users.py`
- `jutsu_engine/api/routes/invitations.py`
- `alembic/versions/YYYYMMDD_add_user_roles.py`
- `dashboard/src/components/UserManagement.tsx`
- `dashboard/src/components/InviteUserModal.tsx`
- `dashboard/src/components/ChangePassword.tsx`
- `dashboard/src/pages/AcceptInvite.tsx`

### Modified Files
- `jutsu_engine/data/models.py` - Add role, UserInvitation
- `jutsu_engine/api/dependencies.py` - Add permission helpers
- `jutsu_engine/api/routes/trades.py` - Protect execute
- `jutsu_engine/api/routes/control.py` - Protect all endpoints
- `jutsu_engine/api/routes/config.py` - Protect write endpoints
- `jutsu_engine/api/routes/auth.py` - Include role in /me response
- `jutsu_engine/api/main.py` - Register new routers
- `dashboard/src/contexts/AuthContext.tsx` - Add role/permissions
- `dashboard/src/pages/Dashboard.tsx` - Conditional UI
- `dashboard/src/pages/Settings.tsx` - Add User Management
- `dashboard/src/App.tsx` - Add routes
- `dashboard/src/api/client.ts` - Add user/invitation API functions
