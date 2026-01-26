# Security & Encryption Audit Report

**Date:** 2026-01-17
**Auditor:** Claude Code Security Analysis
**Database:** PostgreSQL (jutsu_labs)
**Scope:** All 16 tables analyzed for encryption compliance and data protection

---

## Executive Summary

This audit examined all PostgreSQL database tables for sensitive data handling, encryption compliance, and adherence to security standards (NIST 800-63B, OWASP ASVS, GDPR, SOC 2).

### Risk Summary

| Severity | Count | Status |
|----------|-------|--------|
| **CRITICAL** | 2 | 🚨 Requires Immediate Action |
| **HIGH** | 1 | ⚠️ Should Fix Soon |
| **MEDIUM** | 0 | - |
| **LOW** | 0 | - |
| **COMPLIANT** | 13 | ✅ No Action Needed |

---

## Critical Findings

### 1. TOTP Secrets Stored in Plain Text 🚨

**Table:** `users`
**Column:** `totp_secret`
**Current State:** Plain text BASE32 strings
**Example:** `YSALE3CQKWFBPTPX5SJJTRXXHSF3FP2Z`

#### Why This Is Critical

TOTP secrets are the seed used to generate time-based one-time passwords. If an attacker gains database access through:
- SQL injection
- Database backup theft
- Insider threat
- Server compromise

They can **generate valid TOTP codes for ANY user**, completely bypassing 2FA protection.

#### Compliance Violations

| Standard | Requirement | Status |
|----------|-------------|--------|
| **NIST 800-63B** | Section 5.1.4.2: "Authenticator secrets SHALL be stored in a form resistant to offline attacks" | ❌ VIOLATED |
| **OWASP ASVS 4.0** | 2.9.2: "Verify authenticator secrets are stored using approved algorithms such as encryption" | ❌ VIOLATED |
| **SOC 2** | CC6.1: Logical access security controls | ❌ WOULD FAIL AUDIT |
| **PCI-DSS** | Req 8.2.1: MFA secrets must be encrypted at rest | ❌ VIOLATED (if applicable) |

#### Business Impact

- **Complete 2FA bypass** for all users with TOTP enabled
- **Unauthorized trading access** - attackers could execute trades
- **Financial liability** - potential for unauthorized transactions
- **Regulatory penalties** - non-compliance fines

#### Required Remediation

**Solution:** Encrypt TOTP secrets at rest using AES-256-GCM

```python
# Implementation approach
from cryptography.fernet import Fernet
import os

# Key stored in environment variable or secrets manager
TOTP_ENCRYPTION_KEY = os.environ.get('TOTP_ENCRYPTION_KEY')
cipher = Fernet(TOTP_ENCRYPTION_KEY)

# Encrypt before storage
encrypted_secret = cipher.encrypt(totp_secret.encode())

# Decrypt only when generating/validating TOTP
decrypted_secret = cipher.decrypt(encrypted_secret).decode()
```

---

### 2. Backup Codes Stored in Plain Text 🚨

**Table:** `users`
**Column:** `backup_codes`
**Current State:** Plain text JSON array
**Example:** `["MDKS-6RS7", "GCQB-2L48", "8STY-6GAW", ...]`

#### Why This Is Critical

Backup codes are single-use recovery tokens. Unlike TOTP:
- They don't rotate automatically
- They're permanent until used
- User won't know codes were stolen until they try to use one

#### Compliance Violations

| Standard | Requirement | Status |
|----------|-------------|--------|
| **NIST 800-63B** | Section 5.1.2: Recovery secrets have same protection requirements as primary authenticators | ❌ VIOLATED |
| **OWASP ASVS 4.0** | 2.5.4, 2.9.2: Backup codes should be hashed | ❌ VIOLATED |

#### Required Remediation

**Solution:** Hash backup codes like passwords (not encrypt)

Backup codes are single-use, so they should be **hashed** (irreversible), not encrypted:

```python
import bcrypt

# When generating backup codes
def generate_backup_codes(count=10):
    codes = []
    hashed_codes = []
    for _ in range(count):
        code = generate_random_code()  # e.g., "XXXX-XXXX"
        codes.append(code)  # Show to user ONCE
        hashed = bcrypt.hashpw(code.encode(), bcrypt.gensalt())
        hashed_codes.append(hashed.decode())
    return codes, hashed_codes  # Return plaintext to user, store hashes

# When validating
def validate_backup_code(input_code, stored_hashes):
    for i, stored_hash in enumerate(stored_hashes):
        if bcrypt.checkpw(input_code.encode(), stored_hash.encode()):
            # Mark this hash as used (delete from array)
            return True, i
    return False, -1
```

---

## High Priority Findings

### 3. Invitation Tokens Stored in Plain Text ⚠️

**Table:** `user_invitations`
**Column:** `token`
**Current State:** Plain text URL-safe tokens
**Example:** `h-qRVEF_UA8Vc5_EUmHR9SBhqpIDzJ5Mfw2HRwdz3zw`

#### Risk Assessment

| Factor | Assessment |
|--------|------------|
| **Exposure Window** | Limited (tokens expire in 48 hours) |
| **Impact** | Unauthorized account creation with specific role |
| **Likelihood** | Medium (requires database access) |

#### Mitigating Factors
- Tokens have expiration dates
- Tokens are single-use (marked as accepted)
- 4 of 5 invitations already accepted

#### Recommended Remediation

**Option A (Preferred):** Hash invitation tokens
```python
# Store hash, compare hash on redemption
stored_token = hashlib.sha256(token.encode()).hexdigest()
```

**Option B:** Accept current risk with monitoring
- Tokens are short-lived and single-use
- Lower priority than TOTP/backup code fixes

---

## Compliant Areas ✅

### 4. Password Storage - COMPLIANT ✅

**Table:** `users`
**Column:** `password_hash`
**Implementation:** bcrypt with cost factor 12

```
$2b$12$xGoCPfllVRtBSw0f7Hh7WOtzh5zMVHGqGtb1aD3zlUWjZsRiODDcS
```

**Assessment:**
- ✅ bcrypt algorithm (recommended)
- ✅ Cost factor 12 (adequate for 2026)
- ✅ Unique salt per password
- ✅ Resistant to rainbow table attacks

---

### 5. Email Storage - ACCEPTABLE ✅

**Table:** `users`
**Column:** `email`
**Current State:** Plain text

**Assessment:**
Plain text email storage is **industry standard practice** and acceptable because:

| Consideration | Status |
|---------------|--------|
| GDPR Compliance | ✅ Doesn't mandate encryption for all PII |
| Functional Necessity | ✅ Required for login, notifications, recovery |
| Risk Level | LOW - emails alone don't grant account access |
| Industry Practice | ✅ Standard at GitHub, AWS, Google, etc. |

**Verdict:** No change required

---

### 6. WebAuthn Passkeys - COMPLIANT ✅

**Table:** `passkeys`
**Columns:** `credential_id`, `public_key`
**Current State:** Binary (bytea)

**Assessment:**
- ✅ `credential_id` - Device-generated identifier (not secret)
- ✅ `public_key` - By design, public keys are meant to be public
- ✅ Private key never leaves the user's device
- ✅ WebAuthn security model is preserved

**Verdict:** No change required

---

### 7. JWT Blacklist - COMPLIANT ✅

**Table:** `blacklisted_tokens`
**Column:** `jti`
**Current State:** Plain text JWT IDs

**Assessment:**
- ✅ JTI is just an identifier, not a secret
- ✅ Cannot be used to forge tokens
- ✅ Proper implementation of token revocation

**Verdict:** No change required

---

### 8. Trading & Market Data - NOT PII ✅

**Tables:** `live_trades`, `positions`, `performance_snapshots`, `market_data`

**Assessment:**
- ✅ No personally identifiable information
- ✅ Financial data is system-internal
- ✅ Market data is publicly available
- ✅ No encryption requirement

**Verdict:** No change required

---

### 9. System Configuration - COMPLIANT ✅

**Tables:** `system_state`, `config_overrides`, `config_history`

**Assessment:**
- ✅ No secrets stored (baseline prices, dates, parameters)
- ✅ Configuration values are not sensitive
- ✅ Audit trail maintained in `config_history`

**Verdict:** No change required

---

### 10. Scheduler Jobs - ACCEPTABLE ✅

**Table:** `apscheduler_jobs`
**Column:** `job_state`
**Current State:** Pickled binary

**Assessment:**
- ✅ Internal scheduler state
- ✅ No sensitive data in job definitions
- ✅ Standard APScheduler implementation

**Verdict:** No change required

---

### 11. Audit Logs - COMPLIANT ✅

**Table:** `data_audit_log`

**Assessment:**
- ✅ Operational logging only
- ✅ No sensitive data captured
- ✅ Good practice for compliance audits

**Verdict:** No change required

---

## Complete Table Assessment

| Table | Sensitive Data | Encryption Status | Compliance |
|-------|---------------|-------------------|------------|
| `users` | totp_secret | ❌ Plain text | 🚨 CRITICAL |
| `users` | backup_codes | ❌ Plain text | 🚨 CRITICAL |
| `users` | password_hash | ✅ bcrypt | ✅ Compliant |
| `users` | email | Plain text | ✅ Acceptable |
| `passkeys` | credential_id, public_key | Binary (by design) | ✅ Compliant |
| `user_invitations` | token | ❌ Plain text | ⚠️ HIGH |
| `blacklisted_tokens` | jti | Plain text (not secret) | ✅ Compliant |
| `live_trades` | None | N/A | ✅ Compliant |
| `positions` | None | N/A | ✅ Compliant |
| `performance_snapshots` | None | N/A | ✅ Compliant |
| `market_data` | None | N/A | ✅ Compliant |
| `data_metadata` | None | N/A | ✅ Compliant |
| `system_state` | None | N/A | ✅ Compliant |
| `config_overrides` | None | N/A | ✅ Compliant |
| `config_history` | None | N/A | ✅ Compliant |
| `apscheduler_jobs` | None | Pickled | ✅ Acceptable |
| `data_audit_log` | None | N/A | ✅ Compliant |
| `backtest_runs` | None | N/A | ✅ Compliant |
| `alembic_version` | None | N/A | ✅ Compliant |

---

## Implementation Roadmap

### Phase 1: Critical Fixes (Immediate - Week 1)

#### 1.1 TOTP Secret Encryption

**Files to modify:**
- `jutsu_engine/api/models.py` - Add encryption/decryption methods
- `jutsu_engine/api/routes/two_factor.py` - Use encryption when storing/retrieving
- `jutsu_engine/utils/encryption.py` - New file for encryption utilities

**Environment variables to add:**
```bash
TOTP_ENCRYPTION_KEY=<generate-32-byte-base64-key>
```

**Migration script needed:**
```python
# Encrypt all existing TOTP secrets
def migrate_totp_secrets():
    users_with_totp = session.query(User).filter(User.totp_secret.isnot(None)).all()
    for user in users_with_totp:
        user.totp_secret = encrypt_totp(user.totp_secret)
    session.commit()
```

#### 1.2 Backup Code Hashing

**Files to modify:**
- `jutsu_engine/api/routes/two_factor.py` - Hash codes on generation, compare hashes on validation

**Migration approach:**
```python
# IMPORTANT: Cannot migrate existing codes (one-way hash)
# Must regenerate codes for all users and notify them
def migrate_backup_codes():
    users_with_codes = session.query(User).filter(User.backup_codes.isnot(None)).all()
    for user in users_with_codes:
        # Invalidate old codes by setting to empty
        # User must generate new codes
        user.backup_codes = None
    session.commit()
    # Send notification emails
```

### Phase 2: High Priority (Week 2)

#### 2.1 Invitation Token Hashing

**Files to modify:**
- `jutsu_engine/api/routes/admin.py` - Hash tokens on creation
- `jutsu_engine/api/routes/auth.py` - Hash input and compare

### Phase 3: Verification (Week 3)

- [ ] Run security scan (bandit, pip-audit)
- [ ] Penetration testing on 2FA flows
- [ ] Verify encryption keys not in code/logs
- [ ] Update security documentation

---

## Key Generation Commands

```bash
# Generate TOTP encryption key (Fernet requires 32-byte base64)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Example output: Wq3kZ8xY2mN5pR7sT9vB1cD4fG6hJ8kL0nM2oP4qR6s=
```

---

## Deployment Instructions

### Prerequisites

1. **Generate the encryption key ONCE** and save it securely:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. **IMPORTANT**: Use the SAME key across all environments (local, staging, production)
   - If you regenerate the key, all existing encrypted TOTP secrets become unreadable
   - Users would need to re-setup 2FA from scratch

---

### Local Development (.env file)

1. **Add to your `.env` file**:
   ```bash
   # 2FA Security - NEVER regenerate after users have 2FA enabled!
   TOTP_ENCRYPTION_KEY=your-generated-key-here
   ```

2. **Run the migration**:
   ```bash
   source venv/bin/activate
   alembic upgrade head
   ```

3. **Verify** in logs:
   ```
   Encrypted X TOTP secrets
   Invalidated backup codes for users with 2FA - they must regenerate
   ```

---

### Docker Deployment (docker-compose)

1. **Add to `.env` file** (same directory as docker-compose.yml):
   ```bash
   TOTP_ENCRYPTION_KEY=your-generated-key-here
   ```

2. **Rebuild and restart**:
   ```bash
   docker-compose down
   docker-compose build
   docker-compose up -d
   ```

3. The migration runs automatically on container startup via `docker-entrypoint.sh`

---

### Unraid Server Deployment

Unraid uses its Docker UI, not docker-compose directly.

1. **In Unraid Docker UI**:
   - Go to Docker → Click on your Jutsu container → Edit
   - Scroll to "Add another Path, Port, Variable, Label or Device"
   - Click "Add another Variable"

2. **Add the environment variable**:
   | Field | Value |
   |-------|-------|
   | Config Type | Variable |
   | Name | TOTP_ENCRYPTION_KEY |
   | Key | TOTP_ENCRYPTION_KEY |
   | Value | `your-generated-key-here` |

3. **Apply and restart** the container

4. **Check logs** to verify migration ran:
   ```bash
   docker logs jutsu-trading-dashboard | grep -i "totp\|encrypt\|migration"
   ```

---

### Post-Deployment Actions

After running the migration:

1. **Notify users with 2FA enabled**:
   - Their backup codes have been invalidated
   - They must regenerate backup codes in Settings → Security → 2FA

2. **Verify encryption is working**:
   ```sql
   -- TOTP secrets should now start with 'gAAAAA' (Fernet token prefix)
   SELECT id, LEFT(totp_secret, 10) FROM users WHERE totp_secret IS NOT NULL;

   -- Backup codes should be NULL (invalidated)
   SELECT id, backup_codes FROM users WHERE totp_enabled = true;
   ```

3. **Test 2FA login** with an existing user to ensure decryption works

---

### Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `TOTP_ENCRYPTION_KEY not set` warning | Key not in environment | Add to .env or Unraid Docker variable |
| TOTP codes not working after migration | Wrong key or key changed | Restore from backup, use correct key |
| Migration fails | Database connection issue | Check DATABASE_TYPE and credentials |
| `InvalidToken` error on 2FA login | Key mismatch between encrypt/decrypt | Ensure same key in all environments |

---

### Security Checklist

- [ ] TOTP_ENCRYPTION_KEY generated and saved securely
- [ ] Key added to all deployment environments (local, staging, production)
- [ ] Migration run successfully (`alembic upgrade head`)
- [ ] Existing TOTP secrets encrypted (check database)
- [ ] Backup codes invalidated (users notified)
- [ ] 2FA login tested and working
- [ ] Key NOT committed to git (check .gitignore includes .env)

---

## Compliance Checklist Post-Implementation

### NIST 800-63B
- [ ] TOTP secrets encrypted at rest (5.1.4.2)
- [ ] Backup codes hashed (5.1.2)
- [ ] Passwords hashed with approved algorithm (✅ already compliant)

### OWASP ASVS 4.0
- [ ] 2.9.2: Authenticator secrets stored using encryption/hashing
- [ ] 2.5.4: Backup codes properly protected

### SOC 2 Type II
- [ ] CC6.1: Logical access controls for MFA secrets
- [ ] CC6.7: Data encryption controls

---

## Appendix A: Sample Encryption Implementation

```python
# jutsu_engine/utils/encryption.py

import os
from cryptography.fernet import Fernet
import bcrypt
from typing import List, Tuple, Optional

class TOTPEncryption:
    """Handles TOTP secret encryption/decryption."""

    def __init__(self):
        key = os.environ.get('TOTP_ENCRYPTION_KEY')
        if not key:
            raise ValueError("TOTP_ENCRYPTION_KEY environment variable not set")
        self._cipher = Fernet(key.encode())

    def encrypt(self, secret: str) -> str:
        """Encrypt a TOTP secret for storage."""
        return self._cipher.encrypt(secret.encode()).decode()

    def decrypt(self, encrypted_secret: str) -> str:
        """Decrypt a TOTP secret for use."""
        return self._cipher.decrypt(encrypted_secret.encode()).decode()


class BackupCodeManager:
    """Handles backup code generation and validation with hashing."""

    @staticmethod
    def generate_codes(count: int = 10) -> Tuple[List[str], List[str]]:
        """
        Generate backup codes.

        Returns:
            Tuple of (plaintext_codes, hashed_codes)
            - plaintext_codes: Show to user ONCE, then discard
            - hashed_codes: Store in database
        """
        import secrets
        import string

        plaintext_codes = []
        hashed_codes = []

        alphabet = string.ascii_uppercase + string.digits
        for _ in range(count):
            # Generate code like "XXXX-XXXX"
            part1 = ''.join(secrets.choice(alphabet) for _ in range(4))
            part2 = ''.join(secrets.choice(alphabet) for _ in range(4))
            code = f"{part1}-{part2}"

            plaintext_codes.append(code)
            hashed = bcrypt.hashpw(code.encode(), bcrypt.gensalt())
            hashed_codes.append(hashed.decode())

        return plaintext_codes, hashed_codes

    @staticmethod
    def validate_code(input_code: str, stored_hashes: List[str]) -> Tuple[bool, int]:
        """
        Validate a backup code against stored hashes.

        Returns:
            Tuple of (is_valid, index_of_used_code)
            - If valid, the code at the returned index should be removed
        """
        input_code = input_code.upper().strip()

        for i, stored_hash in enumerate(stored_hashes):
            if bcrypt.checkpw(input_code.encode(), stored_hash.encode()):
                return True, i

        return False, -1
```

---

## Appendix B: Database Migration Script

```python
# migrations/versions/xxxx_encrypt_2fa_secrets.py

"""Encrypt TOTP secrets and hash backup codes

Revision ID: xxxx
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from jutsu_engine.utils.encryption import TOTPEncryption

def upgrade():
    # Get database session
    bind = op.get_bind()
    session = Session(bind=bind)

    # Initialize encryption
    totp_crypto = TOTPEncryption()

    # Migrate TOTP secrets
    result = session.execute(
        sa.text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL")
    )

    for row in result:
        user_id, totp_secret = row
        # Check if already encrypted (Fernet tokens start with 'gAAAAA')
        if not totp_secret.startswith('gAAAAA'):
            encrypted = totp_crypto.encrypt(totp_secret)
            session.execute(
                sa.text("UPDATE users SET totp_secret = :secret WHERE id = :id"),
                {"secret": encrypted, "id": user_id}
            )

    # Invalidate all backup codes (users must regenerate)
    session.execute(
        sa.text("UPDATE users SET backup_codes = NULL WHERE backup_codes IS NOT NULL")
    )

    session.commit()

def downgrade():
    # WARNING: Downgrade loses encryption
    # Not recommended for production
    pass
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-17 | Claude Code | Initial audit and recommendations |

---

## Contact

For questions about this security audit or implementation assistance, refer to the Jutsu Labs security team or the original audit context.
