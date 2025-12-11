# Token Blacklist Implementation Summary

## Overview
Implemented server-side token revocation using JWT blacklist table for secure logout functionality.

## Changes Made

### 1. Database Model (jutsu_engine/data/models.py)
Added `BlacklistedToken` model:
- `id`: Primary key
- `jti`: Unique JWT ID (indexed for fast lookups)
- `token_type`: 'access' or 'refresh'
- `blacklisted_at`: Timestamp when token was blacklisted
- `expires_at`: Original token expiry (for cleanup jobs)
- `user_id`: Optional foreign key to users table

### 2. Token Functions (jutsu_engine/api/dependencies.py)
- **Added uuid import**: For generating unique JWT IDs
- **Modified `create_access_token()`**: Adds `jti` (JWT ID) to token payload
- **Modified `create_refresh_token()`**: Adds `jti` (JWT ID) to token payload
- **Added `is_token_blacklisted()`**: Function to check if JTI is blacklisted
- **Modified `get_user_from_token()`**: Checks blacklist before returning user
  - Maintains backward compatibility (tokens without JTI skip blacklist check)
  - Logs warning when blacklisted token is attempted

### 3. Logout Endpoint (jutsu_engine/api/routes/auth.py)
Modified `/api/auth/logout` endpoint:
- Extracts token from Authorization header
- Decodes token to get JTI and expiration
- Adds JTI to blacklist table
- Clears refresh token cookie (if secure cookies enabled)
- Returns success message

## Security Features

### Token Revocation Flow
1. User logs out → Frontend sends POST to /api/auth/logout with token
2. Server extracts JTI from token
3. Server adds JTI to blacklist table
4. Future requests with same token are rejected

### Blacklist Check Flow
1. Request comes in with Authorization: Bearer token
2. `get_user_from_token()` decodes token
3. Checks if JTI exists in blacklist table
4. If blacklisted → returns None (unauthorized)
5. If not blacklisted → returns user (authorized)

### Backward Compatibility
- Tokens without JTI (issued before this update) skip blacklist check
- No breaking changes for existing deployments
- Graceful degradation for legacy tokens

## Database Migration

Run this to add the table to existing databases:

```bash
python3 << 'MIGRATION'
from jutsu_engine.api.dependencies import engine
from jutsu_engine.data.models import BlacklistedToken

BlacklistedToken.__table__.create(engine, checkfirst=True)
print("✅ blacklisted_tokens table created")
MIGRATION
```

Or use SQLAlchemy migrations:
```bash
# If using Alembic
alembic revision --autogenerate -m "Add blacklisted_tokens table"
alembic upgrade head
```

## Testing

### Manual Testing
1. Login to get access token:
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin"
```

2. Use token to access protected endpoint:
```bash
curl http://localhost:8000/api/data/metadata \
  -H "Authorization: Bearer <token>"
```

3. Logout (blacklist token):
```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -H "Authorization: Bearer <token>"
```

4. Try to use same token again (should fail):
```bash
curl http://localhost:8000/api/data/metadata \
  -H "Authorization: Bearer <token>"
# Should return 401 Unauthorized
```

### Verify Blacklist
```python
from jutsu_engine.api.dependencies import get_db_context
from jutsu_engine.data.models import BlacklistedToken

with get_db_context() as db:
    tokens = db.query(BlacklistedToken).all()
    for token in tokens:
        print(f"JTI: {token.jti}, Type: {token.token_type}, Blacklisted: {token.blacklisted_at}")
```

## Cleanup Job (Recommended)

Add periodic cleanup of expired blacklist entries:

```python
from datetime import datetime, timezone
from jutsu_engine.api.dependencies import get_db_context
from jutsu_engine.data.models import BlacklistedToken

def cleanup_expired_tokens():
    """Remove blacklisted tokens that have expired."""
    with get_db_context() as db:
        now = datetime.now(timezone.utc)
        deleted = db.query(BlacklistedToken).filter(
            BlacklistedToken.expires_at < now
        ).delete()
        db.commit()
        print(f"Cleaned up {deleted} expired blacklisted tokens")

# Run daily via cron or scheduler
```

## Files Modified
1. `/Users/anil.goparaju/Documents/Python/Projects/Jutsu-Labs/jutsu_engine/data/models.py`
2. `/Users/anil.goparaju/Documents/Python/Projects/Jutsu-Labs/jutsu_engine/api/dependencies.py`
3. `/Users/anil.goparaju/Documents/Python/Projects/Jutsu-Labs/jutsu_engine/api/routes/auth.py`

## Security Considerations

### Advantages
- True server-side token revocation
- Prevents reuse of stolen tokens after logout
- Audit trail of revoked tokens
- Fast lookup via indexed JTI column

### Limitations
- Requires database query for every token validation
- Blacklist table grows over time (requires periodic cleanup)
- Doesn't prevent token theft before logout

### Best Practices
1. Run cleanup job daily to remove expired tokens
2. Monitor blacklist table size
3. Consider adding user_id to enable "logout all devices"
4. Use short token expiration times (current: 15 minutes for access tokens)
5. Implement refresh token rotation for additional security

## Performance Impact
- Adds 1 database query per authenticated request (blacklist check)
- Index on JTI makes lookup O(log n)
- Minimal overhead for production workloads

## Next Steps
1. Create database migration for existing deployments
2. Add cleanup job to cron/scheduler
3. Test logout flow end-to-end
4. Update API documentation
5. Consider adding "logout all devices" feature (blacklist all user's tokens)
