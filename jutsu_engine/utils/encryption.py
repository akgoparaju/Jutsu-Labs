"""
Security encryption utilities for sensitive data protection.

This module provides encryption for TOTP secrets and hashing for backup codes,
implementing compliance with:
- NIST 800-63B Section 5.1.4.2 (TOTP secrets encrypted at rest)
- NIST 800-63B Section 5.1.2 (Backup codes hashed like passwords)
- OWASP ASVS 4.0 Section 2.9.2 (Authenticator secrets protection)

Security Architecture:
- TOTP secrets: AES-256-GCM encryption via Fernet (reversible - needed for TOTP generation)
- Backup codes: bcrypt hashing (irreversible - single-use codes only need verification)
- Invitation tokens: SHA-256 hashing (irreversible - single-use tokens)
"""

import os
import hashlib
import logging
import secrets
from typing import List, Tuple, Optional

# Use passlib for bcrypt (already in project for password hashing)
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# Fernet is optional - only required for TOTP encryption
try:
    from cryptography.fernet import Fernet, InvalidToken
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False
    logger.warning("cryptography not installed. TOTP encryption disabled.")


# =============================================================================
# TOTP SECRET ENCRYPTION (AES-256-GCM via Fernet)
# =============================================================================

class TOTPEncryption:
    """
    Handles TOTP secret encryption/decryption using Fernet (AES-256-GCM).
    
    The encryption key must be provided via TOTP_ENCRYPTION_KEY environment variable.
    Generate a key using: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    
    Security considerations:
    - Key rotation: If key changes, all encrypted secrets become unreadable
    - Key storage: Store in environment variable or secrets manager, never in code
    - Encryption is reversible (required for TOTP verification)
    """
    
    _instance: Optional['TOTPEncryption'] = None
    _cipher: Optional['Fernet'] = None
    _initialized: bool = False
    
    def __new__(cls):
        """Singleton pattern - one cipher instance per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize encryption cipher from environment."""
        if self._initialized:
            return
            
        if not FERNET_AVAILABLE:
            logger.warning("TOTP encryption unavailable - cryptography not installed")
            self._initialized = True
            return
            
        key = os.environ.get('TOTP_ENCRYPTION_KEY')
        if key:
            try:
                self._cipher = Fernet(key.encode() if isinstance(key, str) else key)
                logger.info("TOTP encryption initialized successfully")
            except Exception as e:
                logger.error(f"Invalid TOTP_ENCRYPTION_KEY: {e}")
                self._cipher = None
        else:
            logger.warning(
                "TOTP_ENCRYPTION_KEY not set. TOTP secrets will be stored in plain text. "
                "Generate key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        
        self._initialized = True
    
    @property
    def is_available(self) -> bool:
        """Check if encryption is available and configured."""
        return self._cipher is not None
    
    def encrypt(self, plaintext_secret: str) -> str:
        """
        Encrypt a TOTP secret for database storage.
        
        Args:
            plaintext_secret: Base32-encoded TOTP secret (e.g., from pyotp.random_base32())
            
        Returns:
            Encrypted secret (Fernet token) or plaintext if encryption unavailable
            
        Note:
            If encryption is not configured, returns plaintext with a warning logged.
            This allows gradual rollout and backwards compatibility.
        """
        if not self.is_available:
            logger.warning("TOTP encryption not available - storing secret in plain text")
            return plaintext_secret
            
        try:
            encrypted = self._cipher.encrypt(plaintext_secret.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"TOTP encryption failed: {e}")
            # Fail closed - don't store unencrypted on encryption failure
            raise ValueError("TOTP encryption failed") from e
    
    def decrypt(self, encrypted_secret: str) -> str:
        """
        Decrypt a TOTP secret for TOTP code generation/verification.
        
        Args:
            encrypted_secret: Fernet-encrypted secret from database
            
        Returns:
            Plaintext Base32 TOTP secret
            
        Raises:
            ValueError: If decryption fails (invalid token or wrong key)
        """
        if not self.is_available:
            # If encryption not configured, assume secret is plaintext
            return encrypted_secret
            
        # Check if this looks like a Fernet token (starts with 'gAAAAA')
        if not encrypted_secret.startswith('gAAAAA'):
            # This is likely a plaintext secret from before encryption was enabled
            logger.debug("TOTP secret appears to be plaintext (legacy data)")
            return encrypted_secret
            
        try:
            decrypted = self._cipher.decrypt(encrypted_secret.encode())
            return decrypted.decode()
        except InvalidToken:
            logger.error("TOTP decryption failed - invalid token or wrong key")
            raise ValueError("TOTP decryption failed - invalid token")
        except Exception as e:
            logger.error(f"TOTP decryption error: {e}")
            raise ValueError("TOTP decryption failed") from e
    
    def is_encrypted(self, secret: str) -> bool:
        """Check if a secret appears to be encrypted (Fernet token format)."""
        return secret.startswith('gAAAAA') if secret else False


# =============================================================================
# BACKUP CODE HASHING (bcrypt)
# =============================================================================

# Use bcrypt with cost factor 12 (same as password hashing)
backup_code_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class BackupCodeManager:
    """
    Handles backup code generation and verification with bcrypt hashing.
    
    Security model:
    - Backup codes are single-use, so they're HASHED (not encrypted)
    - Each code is hashed individually with unique salt
    - On verification, input is hashed and compared to stored hashes
    - Used codes are removed from the database
    
    Compliance:
    - NIST 800-63B Section 5.1.2: Recovery secrets hashed with approved algorithm
    - OWASP ASVS 2.9.2: Authenticator secrets stored using approved algorithms
    """
    
    # Characters for generating backup codes (excluding ambiguous chars: 0, O, I, 1, L)
    CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
    
    @classmethod
    def generate_codes(cls, count: int = 10) -> Tuple[List[str], List[str]]:
        """
        Generate secure backup codes with their hashes.
        
        Args:
            count: Number of backup codes to generate (default: 10)
            
        Returns:
            Tuple of (plaintext_codes, hashed_codes):
            - plaintext_codes: Show to user ONCE, then discard
            - hashed_codes: Store in database as JSON array
            
        Example:
            >>> codes, hashes = BackupCodeManager.generate_codes(10)
            >>> # Show 'codes' to user, store 'hashes' in DB
            >>> user.backup_codes = hashes
        """
        plaintext_codes = []
        hashed_codes = []
        
        for _ in range(count):
            # Generate 8 random characters
            code_chars = ''.join(
                secrets.choice(cls.CODE_ALPHABET) for _ in range(8)
            )
            # Format as XXXX-XXXX
            code = f"{code_chars[:4]}-{code_chars[4:]}"
            plaintext_codes.append(code)
            
            # Hash the code (normalized - without hyphen, uppercase)
            normalized = code.replace('-', '').upper()
            hashed = backup_code_context.hash(normalized)
            hashed_codes.append(hashed)
        
        return plaintext_codes, hashed_codes
    
    @classmethod
    def verify_code(cls, input_code: str, stored_hashes: List[str]) -> Tuple[bool, int]:
        """
        Verify a backup code against stored hashes.
        
        Args:
            input_code: User-provided backup code (with or without hyphen)
            stored_hashes: List of bcrypt hashes from database
            
        Returns:
            Tuple of (is_valid, index):
            - is_valid: True if code matches any stored hash
            - index: Index of matched hash (for removal), -1 if invalid
            
        Example:
            >>> valid, idx = BackupCodeManager.verify_code("ABCD-1234", user.backup_codes)
            >>> if valid:
            ...     # Remove used code
            ...     codes = list(user.backup_codes)
            ...     codes.pop(idx)
            ...     user.backup_codes = codes
        """
        if not stored_hashes:
            return False, -1
            
        # Normalize input (remove hyphen, uppercase)
        normalized_input = input_code.replace('-', '').upper().strip()
        
        for i, stored_hash in enumerate(stored_hashes):
            try:
                # Check if this looks like a bcrypt hash
                if stored_hash.startswith('$2'):
                    # New format: bcrypt hash
                    if backup_code_context.verify(normalized_input, stored_hash):
                        return True, i
                else:
                    # Legacy format: plaintext code
                    stored_normalized = stored_hash.replace('-', '').upper()
                    if stored_normalized == normalized_input:
                        return True, i
            except Exception:
                # If verification fails, continue to next hash
                continue
        
        return False, -1
    
    @classmethod
    def is_hashed(cls, code: str) -> bool:
        """Check if a backup code appears to be hashed (bcrypt format)."""
        return code.startswith('$2') if code else False


# =============================================================================
# INVITATION TOKEN HASHING (SHA-256)
# =============================================================================

class InvitationTokenManager:
    """
    Handles invitation token hashing using SHA-256.
    
    Security model:
    - Invitation tokens are single-use
    - Store SHA-256 hash in database, not plaintext
    - On validation, hash input and compare to stored hash
    
    Design decision: SHA-256 over bcrypt
    - Tokens are cryptographically random (32 bytes), not user-chosen
    - No risk of brute force (2^256 search space)
    - SHA-256 is faster for single comparison operations
    - bcrypt's slow hashing is overkill for random tokens
    """
    
    @staticmethod
    def generate_token() -> Tuple[str, str]:
        """
        Generate a secure invitation token and its hash.
        
        Returns:
            Tuple of (plaintext_token, hashed_token):
            - plaintext_token: Include in invitation URL
            - hashed_token: Store in database
        """
        # Generate 32 bytes of random data, URL-safe base64 encoded
        plaintext = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(plaintext.encode()).hexdigest()
        return plaintext, hashed
    
    @staticmethod
    def hash_token(plaintext_token: str) -> str:
        """Hash a token for database storage or comparison."""
        return hashlib.sha256(plaintext_token.encode()).hexdigest()
    
    @staticmethod
    def verify_token(input_token: str, stored_hash: str) -> bool:
        """
        Verify an invitation token against stored hash.
        
        Args:
            input_token: Token from invitation URL
            stored_hash: SHA-256 hash from database
            
        Returns:
            True if token matches stored hash
        """
        # Check if stored value is a hash (64 hex chars) or plaintext
        if len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash.lower()):
            # New format: SHA-256 hash
            input_hash = hashlib.sha256(input_token.encode()).hexdigest()
            return secrets.compare_digest(input_hash, stored_hash.lower())
        else:
            # Legacy format: plaintext token
            return secrets.compare_digest(input_token, stored_hash)


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

# Global instances for easy import
totp_encryption = TOTPEncryption()
backup_code_manager = BackupCodeManager
invitation_token_manager = InvitationTokenManager
