# Security Hardening Guide for Jutsu-Labs

**Document Version**: 1.2
**Audit Date**: 2025-12-07
**Target Environment**: Production deployment via Cloudflare Tunnel

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Completed Security Items](#completed-security-items)
3. [Pending Critical Items](#pending-critical-items)
4. [Pending High Priority Items](#pending-high-priority-items)
5. [Recommended Enhancements](#recommended-enhancements)
6. [Cloudflare Tunnel Configuration](#cloudflare-tunnel-configuration)
7. [Security Checklist](#security-checklist)
8. [Positive Security Features](#positive-security-features)

---

## Executive Summary

This document outlines security hardening requirements for deploying Jutsu-Labs via Cloudflare tunnel to a public domain. The audit identified several critical vulnerabilities that must be addressed before public exposure.

**Current Status**: Partially hardened - critical configuration items completed, code-level fixes pending.

---

## Completed Security Items

The following security configurations have been applied:

### 1. Authentication Enabled
```bash
# .env
AUTH_REQUIRED=true
```
**Status**: ✅ COMPLETED
**Impact**: All dashboard endpoints now require JWT authentication.

### 2. Debug Mode Disabled
```bash
# .env
DEBUG=false
```
**Status**: ✅ COMPLETED
**Impact**: Detailed error messages and stack traces no longer exposed to users.

### 3. Strong SECRET_KEY Configured
```bash
# .env
SECRET_KEY=<64-character-random-hex>
```
**Status**: ✅ COMPLETED
**Impact**: JWT tokens are cryptographically secure and cannot be forged.

### 4. Strong Admin Password Set
```bash
# .env
ADMIN_PASSWORD=<strong-password>
```
**Status**: ✅ COMPLETED
**Impact**: Default admin account protected with strong credentials.

---

## Pending Critical Items

### 4. Database Password Exposed in Logs

**Severity**: 🔴 CRITICAL
**Status**: ⏳ PENDING CODE FIX
**Files Affected**:
- `jutsu_api/main.py:138`
- `jutsu_engine/api/dependencies.py:124`

**Problem**:
```python
# jutsu_api/main.py:138 - CURRENT (INSECURE)
logger.info(f"Database: {settings.database_url}")

# jutsu_engine/api/dependencies.py:124 - CURRENT (INSECURE)
logger.info(f"Database URL: {DATABASE_URL[:50]}...")  # 50 chars includes password!
```

**Recommended Fix**:

Create a utility function in `jutsu_engine/utils/config.py`:

```python
def get_safe_database_url_for_logging(db_url: str) -> str:
    """
    Return database URL with password masked for safe logging.

    Args:
        db_url: Full database connection URL

    Returns:
        URL with password replaced by asterisks

    Example:
        postgresql://user:secret@host:5432/db
        → postgresql://user:****@host:5432/db
    """
    if 'postgresql' in db_url and '@' in db_url:
        # Split at @ to separate credentials from host
        parts = db_url.split('@')
        if len(parts) == 2:
            # Split credentials part to mask password
            cred_part = parts[0]  # postgresql://user:password
            host_part = parts[1]  # host:port/database

            if ':' in cred_part.split('//')[1]:
                # Has password
                proto_user = cred_part.rsplit(':', 1)[0]  # postgresql://user
                return f"{proto_user}:****@{host_part}"

    return db_url  # Return as-is for SQLite or if parsing fails
```

Then update the logging calls:

```python
# jutsu_api/main.py:138
from jutsu_engine.utils.config import get_safe_database_url_for_logging
logger.info(f"Database: {get_safe_database_url_for_logging(settings.database_url)}")

# jutsu_engine/api/dependencies.py:124
from jutsu_engine.utils.config import get_safe_database_url_for_logging
logger.info(f"Database URL: {get_safe_database_url_for_logging(DATABASE_URL)}")
```

**Verification**:
```bash
# After fix, logs should show:
# "Database URL: postgresql://jutsudB:****@tower.local:5423/jutsu_labs"
```

---

### 5. Two-Factor Authentication (2FA) Required

**Severity**: 🔴 CRITICAL
**Status**: ⏳ PENDING IMPLEMENTATION
**Impact**: Account takeover prevention, defense against credential theft

**Why 2FA is Critical (Not Optional) for This Deployment:**

| Risk Factor | Your Situation | Without 2FA |
|-------------|----------------|-------------|
| Public Internet | Yes (Cloudflare tunnel) | Single password = full access |
| Financial App | Yes (Schwab API) | Compromised = trading access |
| Single User | Yes (no backup admin) | No recovery path |
| Rate Limiting | Not yet implemented | Brute force viable |

**Attack Scenarios Blocked by 2FA:**
- Password leaked in data breach → ✅ Still need device
- Phishing captures password → ✅ Still need device
- Keylogger/shoulder surfing → ✅ Still need device
- Successful brute force → ✅ Still need device

**Implementation Options (Choose One or Both):**

---

#### Option A: Cloudflare Access (Quickest - No Code Changes)

**Best for**: Immediate protection without modifying your application code

**Setup Steps**:
1. Go to Cloudflare Zero Trust Dashboard → Access → Applications
2. Create new "Self-hosted" application
3. Set application domain to your tunnel hostname
4. Configure policy:
   - **Policy name**: "Admin Access"
   - **Action**: Allow
   - **Include rule**: Emails ending in `@yourdomain.com` (or specific email)
5. Choose authentication method:
   - **One-time PIN** (email OTP) - Simplest
   - **Authenticator App** (TOTP) - More secure
   - **Hardware Key** (WebAuthn) - Most secure

**Advantages**:
- Zero code changes required
- Protects ALL endpoints including API
- Built-in brute force protection
- Audit logs included
- Free for up to 50 users

**Configuration Example**:
```yaml
# In Cloudflare Access Policy
access_policy:
  name: "Jutsu Dashboard Access"
  decision: allow
  include:
    - email:
        email: "your-email@domain.com"
  require:
    - authentication_method:
        auth_method: "totp"  # or "otp", "webauthn"
```

---

#### Option B: Application-Level TOTP (Auth App)

**Best for**: Defense-in-depth when combined with Cloudflare Access

**Required Changes**:

1. **Add dependencies** to `requirements.txt`:
```
pyotp>=2.9.0
qrcode[pil]>=7.4
```

2. **Add user model field** in `jutsu_engine/data/models.py`:
```python
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    totp_secret = Column(String(32), nullable=True)  # ADD THIS
    totp_enabled = Column(Boolean, default=False)    # ADD THIS
    backup_codes = Column(Text, nullable=True)       # ADD THIS (JSON array)
    created_at = Column(DateTime, default=datetime.utcnow)
```

3. **Create TOTP setup endpoint** in `jutsu_engine/api/routes/auth.py`:
```python
import pyotp
import qrcode
import io
import base64
import secrets
import json

@router.post("/2fa/setup")
async def setup_2fa(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate TOTP secret and QR code for authenticator app."""
    if current_user.totp_enabled:
        raise HTTPException(400, "2FA already enabled")

    # Generate new secret
    secret = pyotp.random_base32()

    # Create provisioning URI for QR code
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=current_user.username,
        issuer_name="Jutsu Labs"
    )

    # Generate QR code as base64
    qr = qrcode.make(uri)
    buffer = io.BytesIO()
    qr.save(buffer, format='PNG')
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    # Store secret temporarily (not enabled until verified)
    current_user.totp_secret = secret
    db.commit()

    return {
        "secret": secret,  # For manual entry
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "message": "Scan QR code with authenticator app, then verify"
    }

@router.post("/2fa/verify")
async def verify_2fa(
    code: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verify TOTP code and enable 2FA."""
    if not current_user.totp_secret:
        raise HTTPException(400, "Run /2fa/setup first")

    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(400, "Invalid code")

    # Generate backup codes
    backup_codes = [secrets.token_hex(4) for _ in range(10)]
    current_user.backup_codes = json.dumps(backup_codes)
    current_user.totp_enabled = True
    db.commit()

    return {
        "message": "2FA enabled successfully",
        "backup_codes": backup_codes,
        "warning": "Save these backup codes securely. They cannot be shown again."
    }
```

4. **Modify login flow** in `jutsu_engine/api/routes/auth.py`:
```python
@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: Optional[str] = None,  # ADD THIS
    db: Session = Depends(get_db)
):
    # ... existing password verification ...

    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")

    # ADD: Check if 2FA is enabled
    if user.totp_enabled:
        if not totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="2FA code required",
                headers={"X-2FA-Required": "true"}
            )

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code, valid_window=1):
            # Check backup codes
            backup_codes = json.loads(user.backup_codes or '[]')
            if totp_code in backup_codes:
                # Remove used backup code
                backup_codes.remove(totp_code)
                user.backup_codes = json.dumps(backup_codes)
                db.commit()
            else:
                raise HTTPException(401, "Invalid 2FA code")

    # ... rest of login (generate JWT) ...
```

---

#### Option C: Passkeys/WebAuthn (Future Enhancement)

**Best for**: Maximum security with phishing-resistant authentication

**Complexity**: High - requires WebAuthn library and frontend changes
**Recommendation**: Implement after TOTP is working, as an additional option

---

**Recommended Implementation Order:**

1. **Immediate**: Cloudflare Access with email OTP (10 minutes, no code)
2. **This week**: Upgrade to Cloudflare Access with TOTP requirement
3. **Optional**: Add application-level TOTP for defense-in-depth

**Recovery Considerations (Single User):**
- With Cloudflare Access: Use email recovery
- With TOTP: Generate and **securely store** 10 backup codes offline
- Consider: Secondary trusted email for account recovery

**Verification After Setup:**
```bash
# Test login without 2FA - should fail (after implementation)
curl -X POST https://yourdomain.com/auth/login \
  -d "username=admin&password=yourpassword"
# Expected: 401 with X-2FA-Required header

# Test with invalid 2FA - should fail
curl -X POST https://yourdomain.com/auth/login \
  -d "username=admin&password=yourpassword&totp_code=000000"
# Expected: 401 Invalid 2FA code

# Test with valid 2FA - should succeed
curl -X POST https://yourdomain.com/auth/login \
  -d "username=admin&password=yourpassword&totp_code=123456"
# Expected: 200 with JWT token
```

---

### 6. Schwab OAuth Endpoints Unprotected

**Severity**: 🔴 CRITICAL
**Status**: ⏳ PENDING CODE FIX
**File**: `jutsu_engine/api/routes/schwab_auth.py`

**Problem**:
The Schwab OAuth endpoints intentionally bypass authentication:
```python
# Lines 159-163
# NOTE: These routes do NOT use get_current_user dependency
# to allow Schwab OAuth management even when AUTH_REQUIRED=true.
```

This means anyone on the internet can:
- `GET /api/schwab/status` - View token status
- `POST /api/schwab/initiate` - Start OAuth flow
- `POST /api/schwab/callback` - Complete OAuth
- `DELETE /api/schwab/token` - **Delete your Schwab token!**

**Recommended Fix**:

Option A: Protect DELETE endpoint only (minimum fix):

```python
# jutsu_engine/api/routes/schwab_auth.py

from jutsu_engine.api.dependencies import get_current_user

@router.delete("/token")
async def delete_schwab_token(
    current_user = Depends(get_current_user)  # ADD THIS
):
    """
    Delete the current Schwab token.

    REQUIRES AUTHENTICATION when AUTH_REQUIRED=true.
    """
    # Check if auth is required and user is authenticated
    auth_required = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'
    if auth_required and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to delete Schwab token"
        )

    # ... rest of existing code
```

Option B: Protect all Schwab endpoints (more secure):

```python
# Add to all Schwab route functions:
async def get_schwab_auth_status(
    current_user = Depends(get_current_user)  # ADD THIS
):
```

---

### 7. JWT Token Security Configuration

**Severity**: 🔴 CRITICAL
**Status**: ⏳ PENDING CODE FIX
**Files Affected**:
- `jutsu_engine/api/dependencies.py`
- `jutsu_engine/api/routes/auth.py`

**Problem**:
JWT tokens without proper expiration and rotation can lead to prolonged unauthorized access if stolen.

**Security Requirements**:

| Setting | Current | Recommended | Risk if Wrong |
|---------|---------|-------------|---------------|
| Access Token Expiry | Unknown | 15-30 minutes | Token theft = long access |
| Refresh Token Expiry | Unknown | 7 days | Permanent access if stolen |
| Token Rotation | None | On refresh | Replay attacks possible |

**Recommended Fix**:

1. **Set short access token expiration** in `.env`:
```bash
# .env
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

2. **Update token generation** in `jutsu_engine/api/routes/auth.py`:
```python
import os
from datetime import datetime, timedelta

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '15'))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', '7'))

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.utcnow()
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.utcnow()
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
```

3. **Add refresh endpoint with token rotation**:
```python
@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    """Exchange refresh token for new access + refresh tokens."""
    payload = decode_token(refresh_token)

    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")

    # Check if token is blacklisted (optional but recommended)
    if is_token_blacklisted(refresh_token):
        raise HTTPException(401, "Token has been revoked")

    # Blacklist the old refresh token (rotation)
    blacklist_token(refresh_token)

    # Issue new tokens
    username = payload.get("sub")
    return {
        "access_token": create_access_token({"sub": username}),
        "refresh_token": create_refresh_token({"sub": username}),
        "token_type": "bearer"
    }
```

4. **Optional: Add token blacklist for revocation**:
```python
# Simple in-memory blacklist (use Redis in production)
_token_blacklist = set()

def blacklist_token(token: str):
    _token_blacklist.add(token)

def is_token_blacklisted(token: str) -> bool:
    return token in _token_blacklist
```

**Frontend Integration**:
```javascript
// Auto-refresh before expiry
const TOKEN_REFRESH_THRESHOLD = 60; // seconds before expiry

function scheduleTokenRefresh(accessToken) {
    const payload = JSON.parse(atob(accessToken.split('.')[1]));
    const expiresIn = payload.exp - Math.floor(Date.now() / 1000);
    const refreshIn = Math.max(0, expiresIn - TOKEN_REFRESH_THRESHOLD) * 1000;

    setTimeout(() => refreshAccessToken(), refreshIn);
}
```

---

### 8. Secure Cookie Configuration

**Severity**: 🔴 CRITICAL
**Status**: ⏳ PENDING CODE FIX
**File**: `jutsu_engine/api/routes/auth.py`

**Problem**:
Without proper cookie flags, JWT tokens stored in cookies are vulnerable to:
- **XSS attacks** (JavaScript can steal tokens)
- **CSRF attacks** (cross-site requests can use cookies)
- **Man-in-the-middle** (cookies sent over HTTP)

**Current State**: Unknown - need to verify cookie configuration

**Recommended Fix**:

```python
# jutsu_engine/api/routes/auth.py

from fastapi.responses import JSONResponse

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # ... authentication logic ...

    access_token = create_access_token({"sub": user.username})
    refresh_token = create_refresh_token({"sub": user.username})

    response = JSONResponse(content={
        "access_token": access_token,
        "token_type": "bearer"
    })

    # Set secure cookie for refresh token
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,      # 🔒 Prevents JavaScript access (XSS protection)
        secure=True,        # 🔒 Only sent over HTTPS
        samesite="strict",  # 🔒 Prevents CSRF attacks
        max_age=7 * 24 * 60 * 60,  # 7 days in seconds
        path="/api/auth"    # Only sent to auth endpoints
    )

    return response


@router.post("/logout")
async def logout(response: Response):
    """Clear authentication cookies."""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/auth"
    )
    return {"message": "Logged out successfully"}
```

**Cookie Security Flags Explained**:

| Flag | Purpose | Risk Without It |
|------|---------|-----------------|
| `httponly=True` | Blocks JavaScript access | XSS can steal tokens |
| `secure=True` | HTTPS only transmission | MitM can intercept |
| `samesite="strict"` | Blocks cross-site requests | CSRF attacks |
| `path="/api/auth"` | Limits cookie scope | Broader exposure |

**Verification**:
```bash
# Check cookie headers in response
curl -v -X POST https://yourdomain.com/api/auth/login \
  -d "username=admin&password=yourpassword"

# Should see:
# Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Strict; Path=/api/auth
```

---

### 9. Secrets Management

**Severity**: 🔴 CRITICAL
**Status**: ⏳ PENDING REVIEW
**Files Affected**: `.env`, Docker configuration

**Problem**:
Storing secrets in `.env` files is acceptable for development but risky for production:
- File can be accidentally committed
- Readable by anyone with container access
- No secret rotation capability
- No audit trail for secret access

**Current Secrets in `.env**:
```bash
# HIGH RISK if exposed:
SCHWAB_API_KEY=...
SCHWAB_API_SECRET=...
POSTGRES_PASSWORD=...
SECRET_KEY=...
ADMIN_PASSWORD=...
```

**Risk Assessment**:

| Secret | Impact if Leaked |
|--------|------------------|
| SCHWAB_API_KEY/SECRET | Trading access, financial loss |
| POSTGRES_PASSWORD | Full database access |
| SECRET_KEY | JWT forgery, session hijacking |
| ADMIN_PASSWORD | Complete system access |

**Recommended Solutions (Choose One)**:

---

#### Option A: Docker Secrets (Simplest for Docker Swarm)

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    image: jutsu-api
    secrets:
      - schwab_api_key
      - schwab_api_secret
      - postgres_password
      - jwt_secret_key
    environment:
      - SCHWAB_API_KEY_FILE=/run/secrets/schwab_api_key
      - SCHWAB_API_SECRET_FILE=/run/secrets/schwab_api_secret

secrets:
  schwab_api_key:
    file: ./secrets/schwab_api_key.txt
  schwab_api_secret:
    file: ./secrets/schwab_api_secret.txt
  postgres_password:
    file: ./secrets/postgres_password.txt
  jwt_secret_key:
    file: ./secrets/jwt_secret_key.txt
```

Update code to read from file:
```python
# jutsu_engine/utils/config.py

def get_secret(env_var: str) -> str:
    """Get secret from file (Docker secrets) or environment variable."""
    file_path = os.getenv(f"{env_var}_FILE")
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return f.read().strip()
    return os.getenv(env_var, '')

# Usage:
SCHWAB_API_KEY = get_secret('SCHWAB_API_KEY')
```

---

#### Option B: Environment-Based with Restricted Permissions

If staying with `.env`, implement these safeguards:

```bash
# 1. Restrict file permissions
chmod 600 .env
chown root:root .env

# 2. Use .env.example for documentation (no real values)
cp .env .env.example
# Edit .env.example to remove actual secrets

# 3. Add to .gitignore (verify!)
echo ".env" >> .gitignore
echo "*.env" >> .gitignore
echo "secrets/" >> .gitignore

# 4. Add to .dockerignore
echo ".env" >> .dockerignore
```

---

#### Option C: External Secrets Manager (Most Secure)

For maximum security, use an external secrets manager:

**HashiCorp Vault** (self-hosted):
```python
import hvac

client = hvac.Client(url='http://vault:8200')
client.token = os.getenv('VAULT_TOKEN')

secrets = client.secrets.kv.read_secret_version(path='jutsu/production')
SCHWAB_API_KEY = secrets['data']['data']['schwab_api_key']
```

**AWS Secrets Manager** (cloud):
```python
import boto3

client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId='jutsu/production')
secrets = json.loads(response['SecretString'])
SCHWAB_API_KEY = secrets['schwab_api_key']
```

---

**Immediate Actions Required**:

1. **Verify `.gitignore`** includes `.env`:
   ```bash
   grep -r "\.env" .gitignore
   ```

2. **Check git history** for accidentally committed secrets:
   ```bash
   git log --all --full-history -- .env
   # If found, secrets are compromised - rotate them immediately!
   ```

3. **Restrict `.env` file permissions**:
   ```bash
   chmod 600 .env
   ```

4. **Never log secrets** - verify no `logger.info(f"API Key: {key}")` exists

---

## Pending High Priority Items

### 10. Dependency Security Scanning

**Severity**: 🟡 HIGH
**Status**: ⏳ PENDING IMPLEMENTATION
**Impact**: Known vulnerabilities in third-party packages

**Problem**:
Python dependencies may contain known security vulnerabilities (CVEs). Without regular scanning, you may be running vulnerable code.

**Risk Example**:
```
# A vulnerable package could allow:
- Remote code execution
- SQL injection
- Authentication bypass
- Denial of service
```

**Recommended Fix**:

1. **Pre-deployment scan** - Add to deployment checklist:
```bash
# Option A: pip-audit (recommended)
pip install pip-audit
pip-audit

# Option B: safety (alternative)
pip install safety
safety check

# Option C: Using requirements file
pip-audit -r requirements.txt
```

2. **Add to CI/CD pipeline** (GitHub Actions example):
```yaml
# .github/workflows/security.yml
name: Security Scan

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '0 6 * * 1'  # Weekly on Monday

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install pip-audit
      - run: pip-audit --strict --desc
```

3. **Enable GitHub Dependabot** - Create `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    labels:
      - "dependencies"
      - "security"
```

4. **Document update policy**:
```markdown
## Dependency Update Policy
- Security patches: Apply within 24 hours
- Minor updates: Review and apply weekly
- Major updates: Test thoroughly before applying
```

**Verification**:
```bash
# Run scan and ensure no HIGH or CRITICAL vulnerabilities
pip-audit --strict
# Exit code 0 = safe to deploy
```

---

### 11. Request Size and Rate Limits

**Severity**: 🟡 HIGH
**Status**: ⏳ PENDING IMPLEMENTATION
**Files Affected**:
- `docker/nginx.conf`
- `jutsu_engine/api/main.py`

**Problem**:
Without request limits, attackers can:
- Send massive payloads (DoS via memory exhaustion)
- Flood API endpoints (resource exhaustion)
- Perform slowloris attacks (connection exhaustion)

**Recommended Fixes**:

---

#### A. Nginx Request Limits (First Line of Defense)

Add to `docker/nginx.conf`:

```nginx
http {
    # === REQUEST SIZE LIMITS ===
    client_max_body_size 10M;           # Max upload size
    client_body_buffer_size 128k;       # Buffer for request body
    client_header_buffer_size 1k;       # Buffer for headers
    large_client_header_buffers 4 16k;  # Large header handling

    # === CONNECTION LIMITS ===
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;
    limit_conn conn_limit 20;           # Max 20 connections per IP

    # === RATE LIMITING ===
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;

    # === TIMEOUTS ===
    client_body_timeout 10s;            # Time to receive body
    client_header_timeout 10s;          # Time to receive headers
    keepalive_timeout 30s;              # Keep connection alive
    send_timeout 10s;                   # Time to send response

    server {
        # Apply rate limits to locations
        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;
            # ... proxy settings
        }

        location /api/auth/login {
            limit_req zone=login_limit burst=5 nodelay;
            # ... proxy settings
        }
    }
}
```

---

#### B. FastAPI Application Limits

Add global rate limiting in `jutsu_engine/api/main.py`:

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

def create_app(...) -> FastAPI:
    app = FastAPI(...)

    # Add rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Add request size limit middleware
    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB
        content_length = request.headers.get('content-length')

        if content_length and int(content_length) > MAX_REQUEST_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request too large"}
            )

        return await call_next(request)

    return app

# Apply to specific endpoints
@router.post("/upload")
@limiter.limit("5/minute")
async def upload_file(request: Request, ...):
    ...
```

---

#### C. Add to `.env` for Configurability

```bash
# .env - Request Limits
MAX_REQUEST_SIZE_MB=10
API_RATE_LIMIT=100/minute
LOGIN_RATE_LIMIT=5/minute
MAX_CONNECTIONS_PER_IP=20
```

**Verification**:
```bash
# Test request size limit
dd if=/dev/zero bs=1M count=20 | curl -X POST \
  -H "Content-Type: application/octet-stream" \
  --data-binary @- https://yourdomain.com/api/upload
# Expected: 413 Request Entity Too Large

# Test rate limit
for i in {1..20}; do curl -s -o /dev/null -w "%{http_code}\n" \
  https://yourdomain.com/api/status; done
# Expected: 429 Too Many Requests after limit reached
```

---

### 12. Disable OpenAPI Documentation in Production

**Severity**: 🟡 HIGH
**Status**: ⏳ PENDING
**File**: `jutsu_engine/api/main.py`

**Problem**:
API documentation (`/docs`, `/redoc`, `/openapi.json`) is publicly accessible, revealing your entire API structure to potential attackers.

**Recommended Fix**:

```python
# jutsu_engine/api/main.py - in create_app()

import os

def create_app(
    title: str = "Jutsu Trading API",
    version: str = "1.0.0",
    debug: bool = False,
) -> FastAPI:
    # Disable docs in production
    is_production = os.getenv('ENV', 'development') == 'production'

    app = FastAPI(
        title=title,
        version=version,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
        # ... rest of config
    )
```

Then set in `.env`:
```bash
ENV=production
```

---

### 13. WebSocket Authentication

**Severity**: 🟡 HIGH
**Status**: ⏳ PENDING
**File**: `jutsu_engine/api/main.py:238-241`

**Problem**:
```python
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket_endpoint(websocket)  # No auth check!
```

**Recommended Fix**:

```python
# jutsu_engine/api/websocket.py or main.py

from jutsu_engine.api.dependencies import decode_access_token

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates with optional auth."""
    auth_required = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'

    if auth_required:
        # Get token from query parameter or header
        token = websocket.query_params.get('token')

        if not token:
            await websocket.close(code=4001, reason="Authentication required")
            return

        payload = decode_access_token(token)
        if payload is None:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await websocket_endpoint(websocket)
```

**Frontend Update Required**:
```javascript
// Connect with token
const ws = new WebSocket(`wss://yourdomain.com/ws?token=${accessToken}`);
```

---

### 14. Rate Limiting on Login Endpoint

**Severity**: 🟡 HIGH
**Status**: ⏳ PENDING
**File**: `jutsu_engine/api/routes/auth.py`

**Problem**:
No rate limiting on `/auth/login` allows brute force password attacks.

**Recommended Fix**:

Option A: Use existing rate limit middleware with stricter limits:

```python
# jutsu_engine/api/main.py

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# In auth.py
from slowapi import limiter

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")  # Max 5 login attempts per minute
async def login(request: Request, ...):
```

Option B: Simple in-memory rate limiter:

```python
# jutsu_engine/api/routes/auth.py

from collections import defaultdict
from datetime import datetime, timedelta
import threading

_login_attempts = defaultdict(list)
_lock = threading.Lock()

def check_rate_limit(ip: str, max_attempts: int = 5, window_minutes: int = 15) -> bool:
    """Return True if rate limit exceeded."""
    now = datetime.now()
    cutoff = now - timedelta(minutes=window_minutes)

    with _lock:
        # Clean old entries
        _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]

        if len(_login_attempts[ip]) >= max_attempts:
            return True

        _login_attempts[ip].append(now)
        return False

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host

    if check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later."
        )

    # ... rest of login logic
```

---

### 15. Restrict CORS Origins

**Severity**: 🟡 HIGH
**Status**: ⏳ PENDING
**File**: `jutsu_engine/api/main.py:212-225`

**Current Configuration**:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        # ...localhost only
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Recommended Fix for Production**:

```python
# jutsu_engine/api/main.py

import os

# Get allowed origins from environment
cors_origins = os.getenv('CORS_ORIGINS', '').split(',')
if not cors_origins or cors_origins == ['']:
    # Default for development
    cors_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Explicit methods
    allow_headers=["Authorization", "Content-Type"],  # Explicit headers
)
```

Then set in `.env`:
```bash
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

---

### 16. Security Event Monitoring and Alerting

**Severity**: 🟡 HIGH (upgraded from optional)
**Status**: ⏳ PENDING IMPLEMENTATION
**Impact**: Breach detection, incident response, compliance

**Problem**:
Without proper security monitoring, breaches can go undetected for extended periods. Average breach detection time without monitoring: **197 days** (IBM Security Report).

**Why HIGH Priority for Internet-Exposed Apps**:
- Public exposure = higher attack frequency
- Single user = no one else notices anomalies
- Financial app = high-value target
- Regulatory implications if Schwab data compromised

**Required Security Events to Log**:

```python
# jutsu_engine/utils/security_logger.py

import logging
from datetime import datetime
from typing import Optional

# Dedicated security logger
security_logger = logging.getLogger('SECURITY')
security_logger.setLevel(logging.INFO)

# Add file handler for security events
security_handler = logging.FileHandler('logs/security.log')
security_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s'
))
security_logger.addHandler(security_handler)


def log_auth_event(
    event_type: str,
    username: str,
    ip_address: str,
    success: bool,
    details: Optional[str] = None
):
    """Log authentication-related security events."""
    status = "SUCCESS" if success else "FAILED"
    msg = f"AUTH | {event_type} | {status} | user={username} | ip={ip_address}"
    if details:
        msg += f" | {details}"

    if success:
        security_logger.info(msg)
    else:
        security_logger.warning(msg)


def log_security_event(
    event_type: str,
    severity: str,
    details: str,
    ip_address: Optional[str] = None
):
    """Log general security events."""
    msg = f"SECURITY | {event_type} | {severity} | {details}"
    if ip_address:
        msg += f" | ip={ip_address}"

    if severity == "CRITICAL":
        security_logger.critical(msg)
    elif severity == "HIGH":
        security_logger.error(msg)
    elif severity == "MEDIUM":
        security_logger.warning(msg)
    else:
        security_logger.info(msg)
```

**Events to Monitor**:

| Event | Log Level | Action |
|-------|-----------|--------|
| Failed login (1-2 attempts) | WARNING | Log only |
| Failed login (3+ attempts) | ERROR | Log + consider lockout |
| Failed login (5+ attempts) | CRITICAL | Log + temporary IP block |
| Successful login | INFO | Log for audit trail |
| Token refresh | INFO | Log for audit trail |
| 2FA bypass attempt | CRITICAL | Log + alert |
| Schwab token deleted | WARNING | Log + alert owner |
| Rate limit triggered | WARNING | Log source IP |
| Invalid JWT detected | WARNING | Log + track pattern |
| Admin config change | INFO | Log who/what/when |

**Integration Points**:

```python
# In jutsu_engine/api/routes/auth.py

from jutsu_engine.utils.security_logger import log_auth_event, log_security_event

@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    client_ip = request.client.host

    user = authenticate_user(db, form_data.username, form_data.password)

    if not user:
        log_auth_event(
            event_type="LOGIN",
            username=form_data.username,
            ip_address=client_ip,
            success=False,
            details="Invalid credentials"
        )
        raise HTTPException(401, "Invalid credentials")

    # Log successful login
    log_auth_event(
        event_type="LOGIN",
        username=user.username,
        ip_address=client_ip,
        success=True
    )

    return create_tokens(user)


# In schwab_auth.py
@router.delete("/token")
async def delete_schwab_token(current_user = Depends(get_current_user)):
    log_security_event(
        event_type="SCHWAB_TOKEN_DELETE",
        severity="MEDIUM",
        details=f"Token deleted by user={current_user.username}"
    )
    # ... delete token
```

**Simple Alerting (Email on Critical Events)**:

```python
# jutsu_engine/utils/security_alerts.py

import smtplib
from email.mime.text import MIMEText
import os

ALERT_EMAIL = os.getenv('SECURITY_ALERT_EMAIL')
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')

def send_security_alert(subject: str, body: str):
    """Send email alert for critical security events."""
    if not ALERT_EMAIL:
        return  # Alerting not configured

    msg = MIMEText(body)
    msg['Subject'] = f"[SECURITY ALERT] {subject}"
    msg['From'] = 'security@jutsu-labs.local'
    msg['To'] = ALERT_EMAIL

    try:
        with smtplib.SMTP(SMTP_SERVER, 587) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
            server.send_message(msg)
    except Exception as e:
        security_logger.error(f"Failed to send security alert: {e}")
```

**Add to `.env`**:
```bash
# Security Monitoring
SECURITY_ALERT_EMAIL=your-email@domain.com
SMTP_SERVER=smtp.gmail.com
SMTP_USER=your-smtp-user
SMTP_PASS=your-smtp-password
```

**Log Retention**:
```bash
# Add to crontab for log rotation
0 0 * * * /usr/sbin/logrotate /etc/logrotate.d/jutsu-security
```

```
# /etc/logrotate.d/jutsu-security
/var/log/jutsu/security.log {
    daily
    rotate 90
    compress
    delaycompress
    missingok
    notifempty
}
```

---

## Recommended Enhancements

### 17. Security Headers Enhancement

**Severity**: 🟢 RECOMMENDED
**Status**: ⏳ OPTIONAL

Current nginx headers in `docker/nginx.conf` are good but can be enhanced:

```nginx
# docker/nginx.conf - Add these headers

# Prevent clickjacking
add_header X-Frame-Options "DENY" always;  # Changed from SAMEORIGIN

# Content Security Policy
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' wss: https:;" always;

# Strict Transport Security (after confirming HTTPS works)
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

# Permissions Policy
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
```

---

## Cloudflare Tunnel Configuration

### What Cloudflare Tunnel Provides

| Feature | Status |
|---------|--------|
| TLS/SSL Termination | ✅ Automatic |
| DDoS Protection | ✅ Automatic |
| WAF (Web Application Firewall) | ⚠️ Requires Pro plan |
| Bot Protection | ⚠️ Requires configuration |

### What You Must Configure

| Feature | Status |
|---------|--------|
| Application Authentication | ✅ Configured (AUTH_REQUIRED=true) |
| API Endpoint Protection | ⏳ Pending fixes |
| Rate Limiting | ⏳ Pending implementation |
| Credential Masking in Logs | ⏳ Pending fixes |

### Recommended Tunnel Settings

```yaml
# cloudflared config
tunnel: your-tunnel-id
credentials-file: /path/to/credentials.json

ingress:
  - hostname: yourdomain.com
    service: http://localhost:8080
    originRequest:
      noTLSVerify: false  # Keep TLS verification
      connectTimeout: 30s
      tcpKeepAlive: 30s
  - service: http_status:404
```

---

## Security Checklist

### Pre-Deployment Checklist

#### Configuration (All Completed ✅)
- [x] `AUTH_REQUIRED=true`
- [x] `DEBUG=false`
- [x] Strong `SECRET_KEY` (64+ hex chars)
- [x] Strong `ADMIN_PASSWORD`

#### Critical Items (🔴 Must Fix Before Public Exposure)
- [ ] Fix database URL logging to mask password
- [ ] **Implement 2FA** (Cloudflare Access or TOTP)
- [ ] Protect Schwab OAuth DELETE endpoint
- [ ] Configure JWT token expiration (15-30 min)
- [ ] Set secure cookie flags (HttpOnly, Secure, SameSite)
- [ ] Review secrets management (restrict .env permissions)

#### High Priority Items (🟡 Should Fix)
- [ ] Run dependency security scan (`pip-audit`)
- [ ] Configure request size and rate limits
- [ ] Disable `/docs` and `/redoc` in production
- [ ] Add WebSocket authentication
- [ ] Add rate limiting to login endpoint
- [ ] Restrict CORS origins to production domain
- [ ] Implement security event monitoring and alerting

#### Enhancements (Optional 🟢)
- [ ] Enhance security headers (CSP, HSTS)
- [ ] Add IP-based access restrictions
- [ ] Implement token blacklist for revocation

---

## Positive Security Features

The following security measures are already properly implemented:

| Feature | Implementation | Location |
|---------|----------------|----------|
| `.env` not in repo | `.gitignore` includes `.env` | `.gitignore:45` |
| SQL Injection Protection | SQLAlchemy ORM used | All database queries |
| Password Hashing | bcrypt with salt | `dependencies.py:192-219` |
| Non-root Docker User | User `jutsu` (UID 1000) | `Dockerfile:51` |
| X-Frame-Options | SAMEORIGIN | `nginx.conf:64` |
| X-XSS-Protection | 1; mode=block | `nginx.conf:66` |
| X-Content-Type-Options | nosniff | `nginx.conf:65` |
| Constant-time Comparison | For HTTP Basic auth | `dependencies.py:378-379` |
| Input Validation | Config parameters | `config.py:36-61` |
| CSRF State Validation | OAuth flow | `schwab_auth.py:345-350` |

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-07 | Security Audit | Initial security hardening guide |
| 1.1 | 2025-12-07 | Security Audit | Added 2FA as CRITICAL item with implementation options |
| 1.2 | 2025-12-07 | Security Audit | Comprehensive update: JWT security, cookie flags, secrets management, dependency scanning, request limits, security monitoring |

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
