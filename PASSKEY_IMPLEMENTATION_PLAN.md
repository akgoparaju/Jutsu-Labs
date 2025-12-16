# Passkey Implementation Plan

**Date:** 2025-12-15
**Branch:** security
**Status:** AWAITING APPROVAL

---

## Executive Summary

Implement WebAuthn Passkeys as an alternative to TOTP 2FA. Once a user registers a passkey on a device, they can skip the 2FA step on that device while still requiring password authentication.

### Requirements (Confirmed)
| Requirement | Decision |
|-------------|----------|
| Auth Model | Passkey replaces 2FA only (password still required) |
| Multi-device | Yes, multiple passkeys per user |
| Fallback | Fall back to TOTP 2FA if no passkey |
| Trust Duration | Forever until manually revoked |

---

## Architecture Overview

### Current Login Flow
```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Password │ --> │   2FA    │ --> │  Tokens  │
│ Verify   │     │  (TOTP)  │     │  Issued  │
└──────────┘     └──────────┘     └──────────┘
```

### New Login Flow with Passkeys
```
┌──────────┐     ┌─────────────────────────────┐     ┌──────────┐
│ Password │ --> │ Has Passkey for device?     │ --> │  Tokens  │
│ Verify   │     │ ├─ YES: Verify Passkey     │     │  Issued  │
│          │     │ └─ NO:  Fall back to TOTP  │     │          │
└──────────┘     └─────────────────────────────┘     └──────────┘
```

---

## Phase 1: Backend Implementation

### 1.1 Database Model

**New Table: `passkeys`**

```python
# jutsu_engine/data/models.py

class Passkey(Base):
    """
    WebAuthn passkey credential for passwordless 2FA bypass.

    Each user can have multiple passkeys (one per device).
    Passkeys are valid forever until manually revoked.

    Security features:
    - sign_count: Protects against cloned authenticators (replay attacks)
    - credential_id: Unique identifier from the authenticator
    - public_key: COSE-format public key for signature verification
    """

    __tablename__ = 'passkeys'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # WebAuthn credential data (from registration)
    credential_id = Column(LargeBinary, nullable=False, unique=True, index=True)
    public_key = Column(LargeBinary, nullable=False)  # COSE format
    sign_count = Column(Integer, default=0, nullable=False)

    # User-friendly metadata
    device_name = Column(String(100), nullable=True)  # "MacBook Pro", "iPhone 15"

    # AAGUID for authenticator identification (optional)
    aaguid = Column(String(36), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    user = relationship("User", back_populates="passkeys")

    def __repr__(self):
        return f"<Passkey(id={self.id}, user_id={self.user_id}, device={self.device_name})>"
```

**Update User Model:**
```python
# Add to User class
passkeys = relationship("Passkey", back_populates="user", cascade="all, delete-orphan")
```

### 1.2 API Endpoints

**New File: `jutsu_engine/api/routes/passkey.py`**

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| `/api/passkey/register-options` | POST | Yes (JWT) | Generate WebAuthn registration challenge |
| `/api/passkey/register` | POST | Yes (JWT) | Complete passkey registration |
| `/api/passkey/list` | GET | Yes (JWT) | List user's registered passkeys |
| `/api/passkey/{id}` | DELETE | Yes (JWT) | Revoke a specific passkey |
| `/api/passkey/authenticate-options` | POST | No* | Generate auth challenge after password |
| `/api/passkey/authenticate` | POST | No* | Verify passkey and issue tokens |

*These endpoints are called during login flow after password verification.

### 1.3 Registration Flow

```
Frontend                    Backend                         Authenticator
   │                           │                                │
   │ 1. POST /register-options │                                │
   │ (device_name)             │                                │
   │ ─────────────────────────>│                                │
   │                           │                                │
   │ 2. { challenge, rp, user }│                                │
   │ <─────────────────────────│                                │
   │                           │                                │
   │ 3. navigator.credentials.create(options)                   │
   │ ──────────────────────────────────────────────────────────>│
   │                           │                                │
   │ 4. { credential_id, public_key, attestation }              │
   │ <──────────────────────────────────────────────────────────│
   │                           │                                │
   │ 5. POST /register         │                                │
   │ { credential, device_name}│                                │
   │ ─────────────────────────>│                                │
   │                           │ 6. Verify & Store              │
   │ 7. { success: true }      │                                │
   │ <─────────────────────────│                                │
```

### 1.4 Authentication Flow

```
Frontend                    Backend                         Authenticator
   │                           │                                │
   │ 1. POST /login            │                                │
   │ (username, password)      │                                │
   │ ─────────────────────────>│                                │
   │                           │ 2. Verify password             │
   │                           │    Check if has passkey        │
   │ 3. { requires_passkey,    │                                │
   │      challenge,           │                                │
   │      credential_ids }     │                                │
   │ <─────────────────────────│                                │
   │                           │                                │
   │ 4. navigator.credentials.get(options)                      │
   │ ──────────────────────────────────────────────────────────>│
   │                           │                                │
   │ 5. { credential_id, signature, authenticatorData }         │
   │ <──────────────────────────────────────────────────────────│
   │                           │                                │
   │ 6. POST /passkey/authenticate                              │
   │ { username, credential, signature, ... }                   │
   │ ─────────────────────────>│                                │
   │                           │ 7. Verify signature            │
   │                           │    Update sign_count           │
   │ 8. { access_token,        │                                │
   │      refresh_token }      │                                │
   │ <─────────────────────────│                                │
```

### 1.5 Dependencies

**Add to requirements.txt:**
```
webauthn>=2.0.0  # py_webauthn - FIDO2/WebAuthn library
```

**Why py_webauthn:**
- Production-ready, actively maintained
- FIDO Alliance compliant
- Handles all cryptographic verification
- Used by major companies (GitHub, Google)
- Clear API for registration and authentication

---

## Phase 2: Frontend Implementation

### 2.1 Components

**New File: `dashboard/src/components/PasskeySettings.tsx`**

Features:
- List registered passkeys with device names and last used date
- Register new passkey button
- Delete/revoke passkey functionality
- Browser compatibility check (WebAuthn API availability)

**Modify: `dashboard/src/pages/Settings.tsx`**

Add PasskeySettings component alongside TwoFactorSettings:
```tsx
<Section title="Passkeys">
  <PasskeySettings />
</Section>

<Section title="Two-Factor Authentication">
  <TwoFactorSettings />
</Section>
```

### 2.2 Login Page Changes

**Modify: `dashboard/src/pages/Login.tsx`**

Handle new `requires_passkey` response:
```tsx
// After password submit
if (response.requires_passkey) {
  // Show passkey prompt
  await performPasskeyAuthentication(response.challenge, response.credential_ids);
} else if (response.requires_2fa) {
  // Existing TOTP flow
  setShow2FAInput(true);
}
```

### 2.3 Browser Compatibility

Check for WebAuthn support:
```tsx
const isWebAuthnSupported = () => {
  return window.PublicKeyCredential !== undefined;
};
```

Graceful degradation: If browser doesn't support WebAuthn, hide passkey options and use TOTP only.

---

## Phase 3: Security Considerations

### 3.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| Replay attack | sign_count validation - reject if lower than stored |
| Credential cloning | sign_count + AAGUID tracking |
| Phishing | Origin binding in WebAuthn (RP ID = domain) |
| CSRF | Challenge nonces + JWT validation |
| Credential theft | Private key never leaves authenticator |

### 3.2 Rate Limiting

Apply same rate limits as 2FA:
- Registration: 5 attempts/minute per IP
- Authentication: 5 attempts/minute per IP

### 3.3 Security Logging

Add to `security_logger.py`:
```python
PASSKEY_REGISTERED = "passkey_registered"
PASSKEY_AUTHENTICATED = "passkey_authenticated"
PASSKEY_REVOKED = "passkey_revoked"
PASSKEY_AUTH_FAILED = "passkey_auth_failed"
```

### 3.4 Relying Party Configuration

```python
# Environment variables
WEBAUTHN_RP_ID = os.getenv("WEBAUTHN_RP_ID", "localhost")  # Domain name
WEBAUTHN_RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Jutsu Trading")
WEBAUTHN_ORIGIN = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")
```

**Production Example:**
```env
WEBAUTHN_RP_ID=trading.example.com
WEBAUTHN_RP_NAME=Jutsu Trading
WEBAUTHN_ORIGIN=https://trading.example.com
```

---

## Phase 4: Database Migration

### 4.1 Alembic Migration

```python
"""Add passkeys table

Revision ID: xxxx
"""

def upgrade():
    op.create_table(
        'passkeys',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('credential_id', sa.LargeBinary(), nullable=False, unique=True),
        sa.Column('public_key', sa.LargeBinary(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False, default=0),
        sa.Column('device_name', sa.String(100), nullable=True),
        sa.Column('aaguid', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_passkeys_credential_id', 'passkeys', ['credential_id'])
    op.create_index('ix_passkeys_user_id', 'passkeys', ['user_id'])

def downgrade():
    op.drop_table('passkeys')
```

---

## Phase 5: Testing

### 5.1 Unit Tests

**File: `tests/unit/api/test_passkey.py`**

Test cases:
- Registration options generation
- Registration completion
- List passkeys
- Delete passkey
- Authentication options generation
- Authentication verification
- Sign count validation
- Invalid credential rejection
- Rate limiting

### 5.2 Integration Tests

- Full registration flow
- Full authentication flow
- Fallback to TOTP when no passkey
- Multi-passkey per user
- Passkey revocation

### 5.3 Manual Testing

Use browser DevTools or a hardware security key (YubiKey) for real-world testing.

---

## Implementation Order

### Step 1: Backend Foundation (Est. 2 hours)
1. [ ] Add `webauthn` to requirements.txt
2. [ ] Create `Passkey` model in models.py
3. [ ] Add relationship to `User` model
4. [ ] Create database migration
5. [ ] Run migration

### Step 2: API Endpoints (Est. 3 hours)
1. [ ] Create `passkey.py` router
2. [ ] Implement `/register-options` endpoint
3. [ ] Implement `/register` endpoint
4. [ ] Implement `/list` endpoint
5. [ ] Implement `/delete/{id}` endpoint
6. [ ] Implement `/authenticate-options` endpoint
7. [ ] Implement `/authenticate` endpoint
8. [ ] Add security logging
9. [ ] Add rate limiting

### Step 3: Modify Login Flow (Est. 1 hour)
1. [ ] Update `/login` to check for passkeys
2. [ ] Add `requires_passkey` response handling
3. [ ] Integrate passkey auth into login pipeline

### Step 4: Frontend - Settings (Est. 2 hours)
1. [ ] Create `PasskeySettings.tsx` component
2. [ ] Add to Settings page
3. [ ] Implement registration UI
4. [ ] Implement list/delete UI

### Step 5: Frontend - Login (Est. 1 hour)
1. [ ] Add passkey handling to Login page
2. [ ] WebAuthn API integration
3. [ ] Fallback to TOTP flow

### Step 6: Testing & Documentation (Est. 2 hours)
1. [ ] Write unit tests
2. [ ] Write integration tests
3. [ ] Update CHANGELOG.md
4. [ ] Update README security section

**Total Estimated Time: ~11 hours**

---

## Environment Variables (New)

```env
# WebAuthn Configuration
WEBAUTHN_RP_ID=localhost                    # Domain (no protocol, no port)
WEBAUTHN_RP_NAME=Jutsu Trading              # Display name
WEBAUTHN_ORIGIN=https://localhost           # Full origin with protocol
```

**Docker Compose Addition:**
```yaml
environment:
  WEBAUTHN_RP_ID=${WEBAUTHN_RP_ID:-localhost}
  WEBAUTHN_RP_NAME=${WEBAUTHN_RP_NAME:-Jutsu Trading}
  WEBAUTHN_ORIGIN=${WEBAUTHN_ORIGIN:-https://localhost}
```

---

## Rollback Plan

If issues occur:
1. Disable passkey endpoints (comment out router in main.py)
2. Users fall back to existing TOTP 2FA
3. No data migration required for rollback
4. Passkey table can remain (unused)

---

## Approval Checklist

Please confirm:
- [ ] Architecture approach is acceptable
- [ ] Security model meets requirements
- [ ] Implementation order is correct
- [ ] Environment variable naming is appropriate
- [ ] Ready to proceed with implementation

---

**Next Step:** Upon approval, I will begin implementation following the plan above.
