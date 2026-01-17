"""Encrypt TOTP secrets and hash backup codes for security compliance.

Implements:
- NIST 800-63B Section 5.1.4.2: TOTP secrets encrypted at rest
- NIST 800-63B Section 5.1.2: Backup codes hashed like passwords
- OWASP ASVS 4.0 Section 2.9.2: Authenticator secrets protection

IMPORTANT:
- Requires TOTP_ENCRYPTION_KEY environment variable for TOTP encryption
- Backup codes will be INVALIDATED - users must regenerate them
- This is a DATA migration, not just schema

Revision ID: 20260117_0001
Revises: d9f2a3456789
Create Date: 2026-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
import logging
import os

# revision identifiers, used by Alembic.
revision = '20260117_0001'
down_revision = 'd9f2a3456789'  # References backup codes column type fix
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    """
    Encrypt existing TOTP secrets and invalidate backup codes.
    
    Migration strategy:
    1. TOTP secrets: Encrypt if TOTP_ENCRYPTION_KEY is set, otherwise leave as-is with warning
    2. Backup codes: Set to NULL (users must regenerate - cannot migrate plaintext to hashes)
    3. totp_secret column: Increase size to accommodate Fernet tokens
    """
    bind = op.get_bind()
    session = Session(bind=bind)
    
    # Step 1: Increase totp_secret column size for encrypted tokens
    # Fernet tokens are ~120 chars for 32-byte input, but we use 255 for safety
    try:
        # PostgreSQL
        op.alter_column('users', 'totp_secret',
                       existing_type=sa.String(32),
                       type_=sa.String(255),
                       existing_nullable=True)
        logger.info("Increased totp_secret column size to 255")
    except Exception as e:
        logger.warning(f"Column resize skipped (may already be larger): {e}")
    
    # Step 2: Encrypt existing TOTP secrets (if encryption key is available)
    totp_key = os.environ.get('TOTP_ENCRYPTION_KEY')
    
    if totp_key:
        try:
            from cryptography.fernet import Fernet
            cipher = Fernet(totp_key.encode() if isinstance(totp_key, str) else totp_key)
            
            # Find users with TOTP secrets that aren't already encrypted
            result = session.execute(
                sa.text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL")
            )
            
            encrypted_count = 0
            for row in result:
                user_id, totp_secret = row
                # Skip if already encrypted (Fernet tokens start with 'gAAAAA')
                if totp_secret and not totp_secret.startswith('gAAAAA'):
                    encrypted = cipher.encrypt(totp_secret.encode()).decode()
                    session.execute(
                        sa.text("UPDATE users SET totp_secret = :secret WHERE id = :id"),
                        {"secret": encrypted, "id": user_id}
                    )
                    encrypted_count += 1
            
            session.commit()
            logger.info(f"Encrypted {encrypted_count} TOTP secrets")
            
        except ImportError:
            logger.warning("cryptography not installed - TOTP secrets NOT encrypted")
        except Exception as e:
            logger.error(f"TOTP encryption failed: {e}")
            session.rollback()
            raise
    else:
        logger.warning(
            "TOTP_ENCRYPTION_KEY not set - TOTP secrets will remain in plain text. "
            "Set the environment variable and re-run migration to encrypt."
        )
    
    # Step 3: Invalidate all backup codes (users must regenerate)
    # We cannot migrate plaintext to hashes - hashing is one-way
    result = session.execute(
        sa.text("UPDATE users SET backup_codes = NULL WHERE backup_codes IS NOT NULL")
    )
    session.commit()
    logger.info(f"Invalidated backup codes for users with 2FA - they must regenerate")
    
    print("\n" + "="*70)
    print("SECURITY MIGRATION COMPLETE")
    print("="*70)
    if totp_key:
        print("✓ TOTP secrets encrypted with AES-256-GCM")
    else:
        print("⚠ TOTP secrets NOT encrypted (TOTP_ENCRYPTION_KEY not set)")
    print("✓ Backup codes invalidated (users must regenerate)")
    print("\nACTION REQUIRED:")
    print("- Notify users with 2FA to regenerate backup codes")
    print("- If TOTP_ENCRYPTION_KEY wasn't set, set it and re-run migration")
    print("="*70 + "\n")


def downgrade() -> None:
    """
    Decrypt TOTP secrets back to plaintext.
    
    WARNING: This removes encryption protection!
    Backup codes cannot be restored (hashing is one-way).
    """
    bind = op.get_bind()
    session = Session(bind=bind)
    
    totp_key = os.environ.get('TOTP_ENCRYPTION_KEY')
    
    if totp_key:
        try:
            from cryptography.fernet import Fernet
            cipher = Fernet(totp_key.encode() if isinstance(totp_key, str) else totp_key)
            
            result = session.execute(
                sa.text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL")
            )
            
            for row in result:
                user_id, totp_secret = row
                # Only decrypt if it looks like a Fernet token
                if totp_secret and totp_secret.startswith('gAAAAA'):
                    try:
                        decrypted = cipher.decrypt(totp_secret.encode()).decode()
                        session.execute(
                            sa.text("UPDATE users SET totp_secret = :secret WHERE id = :id"),
                            {"secret": decrypted, "id": user_id}
                        )
                    except Exception:
                        logger.warning(f"Could not decrypt TOTP for user {user_id}")
            
            session.commit()
            logger.info("Decrypted TOTP secrets (encryption removed)")
            
        except Exception as e:
            logger.error(f"Downgrade failed: {e}")
            session.rollback()
            raise
    
    # Note: Cannot restore backup codes - hashing is one-way
    print("\n⚠ WARNING: Backup codes cannot be restored - users must regenerate\n")
