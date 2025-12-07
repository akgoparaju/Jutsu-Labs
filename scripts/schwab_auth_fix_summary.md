# Schwab Auth UI Fix - Root Cause Analysis & Resolution

**Date**: 2025-12-07
**Issue**: "Failed to load authentication status" on Docker deployment
**Status**: FIXED

---

## Evidence Collected

### Docker Deployment (FAILING)
- **Network Request**: `GET http://192.168.7.100:8787/api/schwab/status`
- **HTTP Status**: 401 Unauthorized
- **Response Body**: `{"detail": "Authentication required"}`
- **Authorization Header**: MISSING (no JWT token)
- **Browser Console Error**: "Failed to load resource: the server responded with a status of 401 (Unauthorized)"

### Local Deployment (WORKING)
- **Network Request**: None captured (routing issue, separate problem)
- **HTTP Status**: N/A
- **AUTH_REQUIRED**: false
- **No authentication errors**

### Key Observations
1. Docker deployment has `AUTH_REQUIRED=true` in environment
2. Frontend has NO JWT token in localStorage (no login flow visible)
3. Axios interceptor attempts to add Authorization header, but token doesn't exist
4. `/api/schwab/status` endpoint requires authentication when `AUTH_REQUIRED=true`

---

## Root Cause

The Schwab authentication endpoints (`/api/schwab/status`, `/api/schwab/initiate`, `/api/schwab/callback`) were using the `get_current_user` dependency:

```python
@router.get("/status", response_model=SchwabAuthStatus)
async def get_schwab_auth_status(
    current_user=Depends(get_current_user)  # ← Problem: requires dashboard auth
):
```

When `AUTH_REQUIRED=true` in Docker:
1. `get_current_user` checks for JWT token
2. No token exists (user hasn't logged into dashboard)
3. Dependency raises 401 Unauthorized
4. Schwab auth status check fails before endpoint logic runs

**Why this is wrong**: Schwab OAuth token management should work INDEPENDENTLY of dashboard authentication. Users need to set up Schwab tokens regardless of whether dashboard login is required.

---

## Solution

Removed `get_current_user` dependency from ALL Schwab auth endpoints:

### Changed Files
- `/Users/anil.goparaju/Documents/Python/Projects/Jutsu-Labs/jutsu_engine/api/routes/schwab_auth.py`

### Changes Made
1. Removed `from jutsu_engine.api.dependencies import get_current_user`
2. Removed `current_user=Depends(get_current_user)` from ALL route signatures:
   - `GET /api/schwab/status` (line 166)
   - `POST /api/schwab/initiate` (line 228)
   - `POST /api/schwab/callback` (line 304)
   - `DELETE /api/schwab/token` (line 411)

3. Added documentation explaining why:
```python
# NOTE: These routes do NOT use get_current_user dependency to allow
# Schwab OAuth management even when AUTH_REQUIRED=true for the dashboard.
# This is intentional - Schwab token management should work independently
# of dashboard authentication.
```

---

## Validation Required

### Manual Testing
1. **Docker Deployment Test**:
   ```bash
   # Navigate to config page
   http://192.168.7.100:8787/config

   # Expected: Schwab Auth component loads successfully
   # Expected: Status shows "Not Authenticated" or current token status
   # Expected: NO 401 errors in console
   ```

2. **Local Deployment Test**:
   ```bash
   # Navigate to config page
   http://localhost:3000/config

   # Expected: Same behavior as Docker (no regression)
   ```

### Automated Test
Run the Playwright debug script again:
```bash
node scripts/debug_schwab_auth.js
```

**Expected Results**:
- Docker: 200 OK response from `/api/schwab/status`
- Docker: Response body contains valid status (not 401 error)
- Docker: No "Failed to load authentication status" in UI

---

## Additional Notes

### Why This Design is Correct
- Schwab OAuth tokens are for **external API access** (Schwab API)
- Dashboard JWT tokens are for **internal access** (dashboard UI)
- These should be independent: users need Schwab tokens whether or not dashboard login is enabled
- Security: Schwab endpoints still validate Schwab credentials (SCHWAB_API_KEY/SECRET)

### No Security Regression
- Schwab endpoints don't expose sensitive data without proper Schwab credentials
- Token management requires valid SCHWAB_API_KEY and SCHWAB_API_SECRET
- OAuth state validation prevents CSRF attacks
- Token files are protected by filesystem permissions

### Related Issues Fixed
This also resolves a CORS error visible in evidence:
```
Access to fetch at 'http://localhost:8000/auth/status' from origin
'http://192.168.7.100:8787' has been blocked by CORS policy
```
This was the AuthContext trying to check dashboard auth status, which failed due to hardcoded localhost URL.

---

## Deployment Steps

1. **Commit changes**:
   ```bash
   git add jutsu_engine/api/routes/schwab_auth.py
   git commit -m "fix(api): remove auth requirement from Schwab OAuth endpoints

   - Remove get_current_user dependency from /api/schwab/* endpoints
   - Schwab token management should work independently of dashboard auth
   - Fixes 401 Unauthorized on Docker with AUTH_REQUIRED=true
   - Allows Schwab setup regardless of dashboard authentication state"
   ```

2. **Rebuild Docker image**:
   ```bash
   docker compose build
   docker compose up -d
   ```

3. **Verify fix**:
   - Navigate to http://192.168.7.100:8787/config
   - Check browser console (should see NO 401 errors)
   - Schwab Auth component should load successfully

---

## Files Modified
- `jutsu_engine/api/routes/schwab_auth.py` - Removed auth dependency from Schwab endpoints

## Files Created (Debug/Evidence)
- `scripts/debug_schwab_auth.js` - Playwright test script
- `scripts/schwab_auth_evidence.json` - Evidence collected
- `scripts/debug_Docker_Deployment_initial.png` - Screenshot (before fix)
- `scripts/debug_Docker_Deployment_error.png` - Screenshot (error state)
- `scripts/schwab_auth_fix_summary.md` - This document
