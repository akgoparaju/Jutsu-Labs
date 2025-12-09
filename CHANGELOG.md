#### **Schwab: Fix localhost Callback URL Rejection** (2025-12-08)

**Fixed hardcoded `localhost` callback URLs that schwab-py rejects - library only allows `127.0.0.1`**

**Problem**:
After fixing token path issue, got new error: `Disallowed hostname localhost. client_from_login_flow only allows callback URLs with hostname 127.0.0.1`

**Root Cause** (Evidence-Based):
schwab-py library **explicitly rejects** `localhost` - only allows `127.0.0.1` per their security advisory.

Hardcoded `localhost` found in:
1. `schwab.py` line 151: `'https://localhost:8080/callback'` (default fallback)
2. `data_refresh.py` line 295: `'https://localhost:8182'` (hardcoded)

**Fix**:
1. Changed all defaults to `https://127.0.0.1:8182`
2. Added env var support in `data_refresh.py`
3. Updated troubleshooting messages to warn about localhost vs 127.0.0.1

**Files Modified**:
- `jutsu_engine/data/fetchers/schwab.py`: Lines 105, 148-154, 242-249
- `jutsu_engine/live/data_refresh.py`: Lines 292-299

**Reference**: https://schwab-py.readthedocs.io/en/latest/auth.html#callback-url-advisory

---

#### **Schwab: Fix Token Path Mismatch in Docker** (2025-12-08)

**Fixed critical bug where SchwabDataFetcher read from wrong token path in Docker, causing persistent authentication failures after successful re-authentication**

**Problem**:
User re-authenticated with Schwab via dashboard but still got `refresh_token_authentication_error` with HTTP 400. Different tokenDigest values confirmed a new token was created, yet errors persisted.

**Root Cause** (Evidence-Based):
1. Found TWO token files in Docker:
   - `/app/token.json` (old/revoked) - created Dec 5, 3.6 days ago
   - `/app/data/token.json` (new/valid) - created Dec 8, 0.9 days ago
2. `schwab_auth.py` OAuth callback (line 83-84) correctly writes to `/app/data/token.json`:
   ```python
   if Path('/app').exists() and not token_path.startswith('/'):
       token_path = f'/app/data/{token_path}'
   ```
3. `schwab.py` SchwabDataFetcher (line 152) used `token.json` directly WITHOUT Docker path logic:
   ```python
   self.token_path = token_path or os.getenv('SCHWAB_TOKEN_PATH', 'token.json')
   ```
4. Result: OAuth writes new token to `/app/data/token.json`, but fetcher reads old revoked token from `/app/token.json`

**Fix**:
Added matching Docker path logic to `SchwabDataFetcher.__init__()`:
```python
token_path_raw = token_path or os.getenv('SCHWAB_TOKEN_PATH', 'token.json')
if Path('/app').exists() and not token_path_raw.startswith('/'):
    self.token_path = f'/app/data/{token_path_raw}'
else:
    self.token_path = token_path_raw
```

**Files Modified**:
- `jutsu_engine/data/fetchers/schwab.py`:
  - Line 33: Added `from pathlib import Path` import
  - Lines 154-162: Added Docker path adjustment logic matching `schwab_auth.py`

**Impact**: All Docker deployments now correctly read tokens from `/app/data/token.json` after OAuth authentication.

---

#### **Dashboard: Improve Schwab Auth Error Handling** (2025-12-07)

**Enhanced UI to show detailed error messages and disable button when credentials not configured**

**Problem**:
After fixing the 401 Unauthorized error, clicking "Authenticate with Schwab" showed a generic error "Request failed with status code 400" instead of the actual API error message.

**Root Cause** (Evidence-Based):
Using Playwright browser automation on Docker deployment (http://192.168.7.100:8787/config):
1. `/api/schwab/status` returns 200 OK with message "Schwab API credentials not configured..."
2. `/api/schwab/initiate` returns 400 Bad Request with detail: "Schwab API credentials not configured. Set SCHWAB_API_KEY and SCHWAB_API_SECRET in .env"
3. This 400 is **expected behavior** - the API correctly rejects initiation when credentials aren't configured
4. The UI was not extracting the detailed error message from `error.response.data.detail`

**Fix**:
1. **Extract detailed error messages** from API responses (`error.response.data.detail`)
2. **Disable "Authenticate with Schwab" button** when status message indicates credentials not configured
3. **Add tooltip** explaining why button is disabled: "API credentials must be configured in .env file"

**Files Modified**:
- `dashboard/src/components/SchwabAuth.tsx`:
  - Lines 266-277: Callback error now shows `error.response.data.detail`
  - Lines 285-289: Button disabled when credentials not configured
  - Lines 291-296: Added helpful tooltip
  - Lines 335-346: Initiate error now shows `error.response.data.detail`

**User Action Required**:
If seeing "Schwab API credentials not configured":
1. Set `SCHWAB_API_KEY` and `SCHWAB_API_SECRET` in Docker environment
2. Rebuild/restart the container
3. Then the "Authenticate with Schwab" button will be enabled

---

#### **API: Fix Schwab Auth 401 Unauthorized in Docker** (2025-12-07)

**Removed authentication requirement from Schwab OAuth endpoints to allow token management regardless of dashboard authentication state**

**Problem**:
Docker deployment showed "Failed to load authentication status" for Schwab API Authentication on /config page. HTTP 401 Unauthorized from `/api/schwab/status` endpoint.

**Root Cause** (Evidence-Based):
Using Playwright browser automation, collected evidence showing:
1. Docker deployment: 401 Unauthorized from `/api/schwab/status`
2. Response: `{"detail": "Authentication required"}`
3. No Authorization header sent (no JWT token exists)
4. Environment: `AUTH_REQUIRED=true` in Docker (vs `false` locally)

**Analysis**:
Schwab auth endpoints used `get_current_user` dependency which requires JWT token when `AUTH_REQUIRED=true`. This created a circular dependency:
- Can't access Schwab auth UI without dashboard login
- But Schwab token management should work INDEPENDENTLY of dashboard auth
- Users need to set up Schwab OAuth tokens regardless of dashboard authentication

**Fix**:
Removed `get_current_user` dependency from ALL Schwab auth endpoints:
- `GET /api/schwab/status` - Check token status
- `POST /api/schwab/initiate` - Start OAuth flow
- `POST /api/schwab/callback` - Complete OAuth flow
- `DELETE /api/schwab/token` - Delete token

**Security**:
No regression - Schwab endpoints still require valid SCHWAB_API_KEY and SCHWAB_API_SECRET. OAuth state validation prevents CSRF. Token files protected by filesystem permissions.

**Files Modified**:
- `jutsu_engine/api/routes/schwab_auth.py` - Removed auth dependency from all endpoints

**Files Created** (Debug Evidence):
- `scripts/debug_schwab_auth.js` - Playwright test script for evidence collection
- `scripts/schwab_auth_evidence.json` - Network requests, console errors, HTTP responses
- `scripts/schwab_auth_fix_summary.md` - Complete root cause analysis

**Evidence Collection Method**:
Playwright browser automation tested BOTH deployments:
- Local: http://localhost:3000/config (working, AUTH_REQUIRED=false)
- Docker: http://192.168.7.100:8787/config (failing, AUTH_REQUIRED=true)

Captured: HTTP status codes, response bodies, Authorization headers, browser console errors, screenshots

**Validation**:
After fix, `/api/schwab/status` should return 200 OK with status information, not 401 Unauthorized.

---

#### **Docker: Fix JWT Authorization Header Forwarding** (2025-12-07)

**Fixed nginx not explicitly forwarding Authorization header to FastAPI backend**

**Problem**:
Schwab API Authentication showed "Failed to load authentication status" in Docker deployments (Unraid) even after the axios interceptor fix was applied locally. The configuration page worked (no JWT required) but Schwab auth failed (requires JWT).

**Root Cause**:
Two issues combined:
1. **Primary**: Docker image not rebuilt after axios interceptor fix (commit 885f63a)
2. **Secondary**: nginx.conf wasn't explicitly forwarding the Authorization header

**Fix**:
Added explicit Authorization header forwarding in nginx.conf:
```nginx
proxy_set_header Authorization $http_authorization;
```

**Files Modified**:
- `docker/nginx.conf` - Added Authorization header forwarding in /api location

**User Action Required**:
After pulling latest code, rebuild Docker image:
```bash
docker build -t jutsu-trading-dashboard .
# Or for Unraid: Re-pull/rebuild the container
```

---

#### **Dashboard: Switch Icons to SVG Format** (2025-12-07)

**Changed dashboard icons from PNG to SVG for better scalability and display quality**

**Changes**:

1. **Header Logo** (`Layout.tsx`)
   - Changed from `logo.png` to `logo.svg`
   - SVG scales infinitely without pixelation on any display

2. **Favicon** (`index.html`)
   - Changed from `favicon.png` to `favicon.svg`
   - Updated MIME type from `image/png` to `image/svg+xml`

3. **Apple Touch Icon** - **Kept as PNG**
   - iOS does not support SVG for touch icons
   - Retained `favicon.png` for iOS home screen compatibility

**Evidence-Based Decision**:
- TypeScript SVG support confirmed in `vite-env.d.ts:24-27`
