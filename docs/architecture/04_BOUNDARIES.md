# 04 - System Boundaries

> APIs, authentication, authorization, external integrations, and security perimeter

**Last Updated**: 2026-01-25
**Status**: Complete
**Related Documents**: [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | [02_DATA_LAYER](./02_DATA_LAYER.md) | [03_FUNCTIONAL_CORE](./03_FUNCTIONAL_CORE.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [REST API Architecture](#2-rest-api-architecture)
3. [WebSocket Events](#3-websocket-events)
4. [Authentication and Authorization](#4-authentication-and-authorization)
5. [External Integrations](#5-external-integrations)
6. [CORS and Security Headers](#6-cors-and-security-headers)
7. [Error Handling Conventions](#7-error-handling-conventions)
8. [Cross-References](#8-cross-references)

---

## 1. Overview

Jutsu Labs exposes its functionality through a **FastAPI REST API** and a **WebSocket** endpoint for real-time updates. The system integrates with external services (Schwab brokerage, Yahoo Finance) and enforces a multi-layer security model covering authentication, authorization, rate limiting, and request validation.

### Boundary Summary

```
┌─────────────────────────────────────────────────────────┐
│                     EXTERNAL CLIENTS                     │
│   React Dashboard  │  CLI Tools  │  WebSocket Clients    │
└─────────┬──────────┴──────┬──────┴──────────┬───────────┘
          │ HTTPS           │ HTTPS           │ WSS
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│               CLOUDFLARE TUNNEL + NGINX                  │
│   DDoS Protection  │  SSL Termination  │  Rate Limiting  │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    FASTAPI APPLICATION                    │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │   Auth   │  │   CORS   │  │  Rate    │  Middleware   │
│  │  Guard   │  │  Policy  │  │  Limiter │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       └──────────────┼─────────────┘                     │
│                      ▼                                   │
│  ┌────────────────────────────────────────┐              │
│  │           ROUTE HANDLERS               │              │
│  │  auth │ status │ trades │ performance  │              │
│  │  config │ control │ indicators         │              │
│  │  users │ strategies │ backtest         │              │
│  │  daily_performance_v2                  │              │
│  └────────────────────┬───────────────────┘              │
│                       ▼                                  │
│  ┌────────────────────────────────────────┐              │
│  │       EXTERNAL INTEGRATIONS            │              │
│  │  Schwab API │ Yahoo Finance │ Webhooks │              │
│  └────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **FastAPI over Flask/Django** | Async support, automatic OpenAPI docs, Pydantic validation |
| **JWT over sessions** | Stateless auth, works with SPA frontend, token refresh pattern |
| **WebSocket for live updates** | Real-time regime changes and trade notifications |
| **Rate limiting (slowapi)** | Brute-force protection without external infrastructure |
| **Invitation-based onboarding** | Controlled access, no public registration |

---

## 2. REST API Architecture

### 2.1 Route Organization

All API routes are registered in `jutsu_engine/api/main.py` via `create_app()`. Routes are organized by functional domain:

| Router | Prefix | Tag | Source File |
|--------|--------|-----|-------------|
| `auth_router` | `/api/auth` | Authentication | `routes/auth.py` |
| `two_factor_router` | `/api/2fa` | Two-Factor Auth | `routes/two_factor.py` |
| `passkey_router` | `/api/passkey` | WebAuthn Passkeys | `routes/passkey.py` |
| `schwab_auth_router` | `/api/schwab` | Schwab OAuth | `routes/schwab_auth.py` |
| `status_router` | `/api/status` | System Status | `routes/status.py` |
| `config_router` | `/api/config` | Configuration | `routes/config.py` |
| `trades_router` | `/api/trades` | Trade History | `routes/trades.py` |
| `performance_router` | `/api/performance` | Performance (V1) | `routes/performance.py` |
| `daily_performance_v2_router` | `/api/v2` | Performance (V2) | `routes/daily_performance_v2.py` |
| `control_router` | `/api/control` | Engine Control | `routes/control.py` |
| `indicators_router` | `/api/indicators` | Indicator Values | `routes/indicators.py` |
| `users_router` | `/api/users` | User Management | `routes/users.py` |
| `invitations_router` | `/api/invitations` | Invitation Accept | `routes/invitations.py` |
| `backtest_router` | `/api/backtest` | Backtest Results | `routes/backtest.py` |
| `strategies_router` | `/api/strategies` | Strategy Registry | `routes/strategies.py` |

### 2.2 Endpoint Catalog

#### Authentication (`/api/auth/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/auth/status` | None | Check if auth is enabled |
| `POST` | `/api/auth/login` | None | Login with username/password |
| `POST` | `/api/auth/login/2fa` | Partial | Complete login with TOTP code |
| `GET` | `/api/auth/me` | JWT | Get current user info (includes role) |
| `POST` | `/api/auth/logout` | JWT | Logout (blacklist token) |
| `POST` | `/api/auth/refresh` | Refresh Token | Refresh access token |

#### Two-Factor Authentication (`/api/2fa/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/2fa/status` | JWT | Check 2FA enrollment status |
| `POST` | `/api/2fa/setup` | JWT | Generate TOTP secret + QR code |
| `POST` | `/api/2fa/verify` | JWT | Verify TOTP code to enable 2FA |
| `POST` | `/api/2fa/disable` | JWT | Disable 2FA (requires TOTP code) |
| `POST` | `/api/2fa/validate` | JWT | Validate a TOTP code |
| `POST` | `/api/2fa/backup-codes/regenerate` | JWT | Generate new backup codes |

#### WebAuthn Passkeys (`/api/passkey/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/passkey/status` | JWT | Check passkey support status |
| `GET` | `/api/passkey/list` | JWT | List registered passkeys |
| `POST` | `/api/passkey/register/options` | JWT | Generate registration challenge |
| `POST` | `/api/passkey/register` | JWT | Complete passkey registration |
| `DELETE` | `/api/passkey/{id}` | JWT | Revoke a passkey |
| `POST` | `/api/passkey/authenticate/options` | None | Generate auth challenge |
| `POST` | `/api/passkey/authenticate` | None | Verify passkey (completes login) |

#### Schwab OAuth (`/api/schwab/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/schwab/status` | JWT | Token validity and expiration status |
| `GET` | `/api/schwab/auth/status` | JWT | Detailed Schwab auth status |
| `POST` | `/api/schwab/auth/initiate` | JWT | Start OAuth flow (returns auth URL) |
| `POST` | `/api/schwab/auth/callback` | JWT | Complete OAuth with callback URL |
| `DELETE` | `/api/schwab/token` | JWT | Revoke stored Schwab token |

#### System Status (`/api/status/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/status` | JWT | Full system status (engine, scheduler, positions) |
| `GET` | `/api/status/health` | None | Health check (for load balancers) |
| `GET` | `/api/status/ready` | None | Readiness probe (database + data freshness) |
| `GET` | `/api/status/regime` | JWT | Current regime state (trend, volatility, cell) |

#### Configuration (`/api/config/*`)

| Method | Endpoint | Auth | Permission |
|--------|----------|------|------------|
| `GET` | `/api/config` | JWT | `config:read` |
| `PUT` | `/api/config` | JWT | `config:write` (admin) |
| `POST` | `/api/config/reset/{param}` | JWT | `config:write` (admin) |

#### Trade History (`/api/trades/*`)

| Method | Endpoint | Auth | Permission |
|--------|----------|------|------------|
| `GET` | `/api/trades` | JWT | `trades:read` |
| `GET` | `/api/trades/export` | JWT | `trades:read` |
| `GET` | `/api/trades/{id}` | JWT | `trades:read` |
| `GET` | `/api/trades/stats` | JWT | `trades:read` |
| `POST` | `/api/trades/execute` | JWT | `trades:execute` (admin) |

#### Performance V1 (`/api/performance/*`) — Deprecated

| Method | Endpoint | Auth | Notes |
|--------|----------|------|-------|
| `GET` | `/api/performance` | JWT | Returns deprecation headers |
| `GET` | `/api/performance/equity-curve` | JWT | Sunset date in response |
| `GET` | `/api/performance/drawdown` | JWT | Use V2 API instead |
| `GET` | `/api/performance/regime-breakdown` | JWT | Legacy endpoint |

#### Performance V2 (`/api/v2/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v2/daily-performance` | JWT | Latest EOD-finalized metrics |
| `GET` | `/api/v2/daily-performance/history` | JWT | Historical daily performance |
| `GET` | `/api/v2/daily-performance/comparison` | JWT | Multi-strategy comparison |
| `GET` | `/api/v2/daily-performance/eod-status` | JWT | EOD job status and schedule |
| `GET` | `/api/v2/daily-performance/eod-status/today` | JWT | Today's EOD finalization status |

#### Engine Control (`/api/control/*`)

| Method | Endpoint | Auth | Permission |
|--------|----------|------|------------|
| `POST` | `/api/control/start` | JWT | `engine:control` (admin) |
| `POST` | `/api/control/stop` | JWT | `engine:control` (admin) |
| `POST` | `/api/control/restart` | JWT | `engine:control` (admin) |
| `GET` | `/api/control/state` | JWT | `engine:control` |
| `POST` | `/api/control/mode` | JWT | `engine:control` (admin) |
| `GET` | `/api/control/scheduler` | JWT | `scheduler:control` |
| `POST` | `/api/control/scheduler/enable` | JWT | `scheduler:control` (admin) |
| `POST` | `/api/control/scheduler/disable` | JWT | `scheduler:control` (admin) |
| `POST` | `/api/control/scheduler/trigger` | JWT | `scheduler:control` (admin) |
| `PUT` | `/api/control/scheduler` | JWT | `scheduler:control` (admin) |
| `GET` | `/api/control/data-staleness` | JWT | Check data freshness |
| `POST` | `/api/control/data-refresh` | JWT | `scheduler:control` (admin) |

#### Indicators (`/api/indicators/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/indicators` | JWT | Current indicator values |
| `GET` | `/api/indicators/history` | JWT | Historical indicator data |
| `GET` | `/api/indicators/descriptions` | JWT | Indicator metadata and descriptions |

#### User Management (`/api/users/*`)

| Method | Endpoint | Auth | Permission |
|--------|----------|------|------------|
| `GET` | `/api/users` | JWT | `users:manage` (admin) |
| `POST` | `/api/users/invite` | JWT | `users:manage` (admin) |
| `GET` | `/api/users/invitations` | JWT | `users:manage` (admin) |
| `DELETE` | `/api/users/invitations/{id}` | JWT | `users:manage` (admin) |
| `GET` | `/api/users/{id}` | JWT | `users:manage` (admin) |
| `PUT` | `/api/users/{id}` | JWT | `users:manage` (admin) |
| `DELETE` | `/api/users/{id}` | JWT | `users:manage` (admin) |
| `PUT` | `/api/users/me/password` | JWT | `self:password` |

#### Invitations (`/api/invitations/*`) — Public

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/invitations/{token}` | None | Validate invitation token |
| `POST` | `/api/invitations/{token}/accept` | None | Register new user via invitation |

#### Strategies (`/api/strategies/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/strategies` | JWT | List registered strategies |
| `GET` | `/api/strategies/status` | JWT | Strategy execution state |
| `GET` | `/api/strategies/{id}` | JWT | Strategy details |
| `GET` | `/api/strategies/{id}/state` | JWT | Strategy runtime state |
| `GET` | `/api/strategies/primary/state` | JWT | Primary strategy state |

#### Backtest (`/api/backtest/*`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/backtest/strategies` | JWT | List available backtest results |
| `GET` | `/api/backtest/{strategy}` | JWT | Get backtest data (equity, trades) |
| `GET` | `/api/backtest/{strategy}/config` | JWT | Get strategy configuration YAML |
| `GET` | `/api/backtest/{strategy}/regime` | JWT | Get regime breakdown for backtest |

### 2.3 Request/Response Patterns

All API responses follow consistent patterns defined with **Pydantic** schemas:

```python
# Success response
{
    "strategy_id": "v3_5b",
    "date": "2026-01-24",
    "total_value": 125430.50,
    "daily_return_pct": 0.45,
    ...
}

# Error response (standard FastAPI)
{
    "error": "Not Found",
    "detail": "Strategy 'invalid' not found"
}

# Validation error (422)
{
    "detail": [
        {
            "loc": ["query", "strategy_id"],
            "msg": "field required",
            "type": "value_error.missing"
        }
    ]
}
```

**Query Parameter Conventions:**

| Pattern | Example | Description |
|---------|---------|-------------|
| `strategy_id` | `?strategy_id=v3_5b` | Filter by strategy (most endpoints) |
| `days` | `?days=30` | Time window for historical data |
| `start_date` / `end_date` | `?start_date=2025-01-01` | Date range filter |
| `limit` / `offset` | `?limit=50&offset=0` | Pagination |
| `format` | `?format=csv` | Response format |

---

## 3. WebSocket Events

### 3.1 Connection

The WebSocket endpoint is at `/ws`. When `AUTH_REQUIRED=true`, connection requires a JWT token:

```
ws://host/ws?token=<jwt_access_token>
```

**Connection Manager** (`jutsu_engine/api/websocket.py`):
- Manages active connections via `ConnectionManager` class
- Broadcasts to all connected clients simultaneously
- Rejects invalid tokens with close code `4001`
- Runs a background broadcast loop for periodic updates

### 3.2 Event Types

| Event Type | Direction | Payload | Description |
|------------|-----------|---------|-------------|
| `trade_executed` | Server → Client | Trade details, strategy context | Real-time trade notification |
| `regime_change` | Server → Client | New cell, trend/vol state | Regime transition alert |
| `data_refresh` | Server → Client | Refresh status, timestamp | Data refresh completion |
| `error` | Server → Client | Error message, severity | System error notification |

### 3.3 Broadcast Functions

```python
# jutsu_engine/api/websocket.py
async def broadcast_trade_executed(trade_data: dict)
async def broadcast_regime_change(regime_data: dict)
async def broadcast_error(error_data: dict)
async def broadcast_data_refresh(refresh_data: dict)
```

---

## 4. Authentication and Authorization

### 4.1 Authentication Modes

The system supports three auth modes, selected via environment variables:

| Mode | Config | Use Case |
|------|--------|----------|
| **JWT (Recommended)** | `AUTH_REQUIRED=true` | Production deployment |
| **HTTP Basic (Legacy)** | `JUTSU_API_USERNAME` / `JUTSU_API_PASSWORD` | Simple setups |
| **No Auth** | Neither configured | Local development only |

### 4.2 JWT Token Flow

```
┌──────────┐     POST /api/auth/login        ┌──────────┐
│  Client   │ ─────────────────────────────► │  Server   │
│           │    {username, password}         │           │
│           │                                 │           │
│           │ ◄───────────────────────────── │           │
│           │   {requires_2fa: true} OR       │           │
│           │   {access_token, refresh_token} │           │
│           │                                 │           │
│  [If 2FA] │     POST /api/auth/login/2fa    │           │
│           │ ─────────────────────────────► │           │
│           │    {username, password, code}    │           │
│           │                                 │           │
│           │ ◄───────────────────────────── │           │
│           │   {access_token, refresh_token} │           │
│           │                                 │           │
│  [If      │     POST /api/passkey/          │           │
│  Passkey] │     authenticate                │           │
│           │ ─────────────────────────────► │           │
│           │    {credential}                 │           │
│           │                                 │           │
│           │ ◄───────────────────────────── │           │
│           │   {access_token, refresh_token} │           │
└──────────┘                                 └──────────┘
```

**Token Configuration** (from `dependencies.py`):

| Token Type | Default Lifetime | Env Variable |
|------------|-----------------|--------------|
| Access Token | 15 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Refresh Token | 7 days | `REFRESH_TOKEN_EXPIRE_DAYS` |
| Passkey Token | 5 minutes | `PASSKEY_TOKEN_EXPIRE_MINUTES` |

**Token Structure:**
```python
{
    "sub": "admin",          # Username
    "type": "access",        # "access" or "refresh"
    "exp": 1737849600,       # Expiration timestamp
    "iat": 1737848700        # Issued-at timestamp
}
```

### 4.3 Two-Factor Authentication (TOTP)

| Feature | Implementation |
|---------|---------------|
| **Algorithm** | TOTP (RFC 6238) via `pyotp` library |
| **QR Code** | Generated with `qrcode` library, base64-encoded PNG |
| **Backup Codes** | 10 single-use codes, stored in database |
| **Rate Limiting** | 5 attempts/minute on 2FA endpoints |
| **Enrollment** | Setup → Verify → Enable (3-step flow) |

### 4.4 WebAuthn Passkeys (FIDO2)

Passkeys provide **passwordless 2FA bypass** on trusted devices:

| Feature | Implementation |
|---------|---------------|
| **Library** | `py-webauthn` |
| **Replaces** | 2FA only (password still required initially) |
| **Multiple per user** | Each device gets its own passkey |
| **Never expires** | Valid until manually revoked |
| **Fallback** | If no passkey for device → standard TOTP flow |
| **sign_count** | Replay attack protection via counter validation |

**Configuration** (environment variables):
```
WEBAUTHN_RP_ID=your-domain.com
WEBAUTHN_RP_NAME=Jutsu Trading
WEBAUTHN_ORIGIN=https://your-domain.com
```

### 4.5 Account Security

| Feature | Details |
|---------|---------|
| **Password Hashing** | bcrypt via `passlib` |
| **Account Lockout** | 5 failed attempts → locked for configurable duration |
| **Security Logging** | JSON-formatted events (ELK/Splunk compatible) |
| **Cookie Security** | Configurable Secure, SameSite, Domain attributes |

**Security Events** logged to `security_logger.py`:

| Event | Trigger |
|-------|---------|
| `LOGIN_SUCCESS` | Successful authentication |
| `LOGIN_FAILURE` | Invalid credentials |
| `TOKEN_CREATED` | JWT issued |
| `TOKEN_REFRESHED` | Token refresh |
| `TOKEN_INVALID` | Invalid/expired token used |
| `PASSKEY_REGISTERED` | New passkey enrolled |
| `PASSKEY_AUTHENTICATED` | Passkey login success |
| `PASSKEY_AUTH_FAILED` | Passkey verification failure |
| `PASSKEY_REVOKED` | Passkey deleted |
| `OAUTH_TOKEN_DELETED` | Schwab token revoked |

### 4.6 Role-Based Access Control (RBAC)

#### Roles

| Role | Scope | Description |
|------|-------|-------------|
| **admin** | `*` (wildcard) | Full system access |
| **viewer** | Read-only + self-management | Dashboard viewing, own password/2FA |

#### Permission Map

```python
# jutsu_engine/api/dependencies.py
ROLE_PERMISSIONS = {
    "admin": {"*"},
    "viewer": {
        "dashboard:read", "performance:read", "trades:read",
        "config:read", "indicators:read", "regime:read",
        "status:read", "self:password", "self:2fa", "self:passkey",
    },
}
```

#### Protected Permissions (Admin-Only)

| Permission | Protects |
|------------|----------|
| `trades:execute` | Trade execution endpoint |
| `engine:control` | Start/stop/restart engine, switch modes |
| `scheduler:control` | Enable/disable scheduler, trigger jobs |
| `config:write` | Update configuration parameters |
| `users:manage` | User CRUD and invitation management |

#### Enforcement Pattern

```python
# FastAPI dependency injection pattern
@router.post("/control/start")
async def start_engine(
    user=Depends(require_permission("engine:control"))
):
    ...
```

### 4.7 Invitation System

New users are onboarded exclusively through admin-generated invitations:

| Property | Value |
|----------|-------|
| **Token Format** | `secrets.token_urlsafe(48)` → 64 characters |
| **Expiration** | 48 hours from creation |
| **One-Time Use** | Marked as accepted after registration |
| **User Limit** | Maximum 20 users per instance |
| **Role Assignment** | Admin specifies role at invitation time |

---

## 5. External Integrations

### 5.1 Schwab API (Brokerage)

The primary external integration for live trading:

| Feature | Details |
|---------|---------|
| **Library** | `schwab-py` (official Python SDK) |
| **Authentication** | OAuth 2.0 with PKCE |
| **Token Storage** | Encrypted file at configurable path |
| **Token Refresh** | Automatic via library; monitoring via scheduler job |
| **Data Endpoints** | Quotes, historical bars, account positions, orders |

**OAuth Flow** (managed via `/api/schwab/auth/*`):

```
1. Admin initiates OAuth  →  Server generates auth URL
2. Admin opens URL        →  Schwab login page
3. Admin authorizes       →  Schwab redirects with callback URL
4. Admin pastes callback  →  Server exchanges code for tokens
5. Tokens stored          →  Encrypted file persisted
```

**API Operations** (`jutsu_engine/live/data_fetcher.py` → `LiveDataFetcher`):

| Operation | Method | Purpose |
|-----------|--------|---------|
| `fetch_historical_bars()` | GET price history | Strategy warmup and daily bars |
| `fetch_current_quote()` | GET quote | Real-time price for single symbol |
| `fetch_all_quotes()` | GET quotes | Batch price fetch for all symbols |
| `create_synthetic_daily_bar()` | Computed | Build daily bar from intraday quote |
| `validate_corporate_actions()` | Analysis | Detect stock splits/dividends |
| `fetch_account_equity()` | GET account | Current account value |
| `fetch_account_positions()` | GET positions | Current holdings |

**Order Execution** (`jutsu_engine/live/schwab_executor.py` → `SchwabOrderExecutor`):

| Feature | Details |
|---------|---------|
| **Order Sequence** | SELL-first, BUY-second (reduces margin risk) |
| **Slippage Abort** | 1% threshold; warning at 0.5% |
| **Fill Timeout** | 30 seconds default |
| **Audit Trail** | Every order logged with strategy context |
| **Reconciliation** | Daily at 5:00 PM ET via `FillReconciler` |

### 5.2 Yahoo Finance (Market Data)

| Feature | Details |
|---------|---------|
| **Library** | `yfinance` |
| **Purpose** | Historical daily bars, dividend/split data |
| **Usage** | Data sync for backfill and daily refresh |
| **Fallback** | Used when Schwab data unavailable (weekends, pre-market) |

Data flows through `jutsu_engine/live/data_refresh.py` → `DashboardDataRefresher`:

| Method | Purpose |
|--------|---------|
| `sync_market_data()` | Sync from Yahoo Finance to database |
| `_fallback_sync()` | Retry with alternative date ranges |
| `fetch_current_prices()` | Get latest prices for dashboard display |
| `update_position_values()` | Mark-to-market position valuation |
| `calculate_indicators()` | Recompute indicators with fresh data |
| `save_performance_snapshot()` | Persist computed metrics |
| `full_refresh()` | Orchestrate complete refresh cycle |

### 5.3 Webhook Notifications

| Feature | Details |
|---------|---------|
| **Channels** | Slack, Discord (via webhook URLs) |
| **Alerts** | Trade execution, regime changes, errors |
| **Manager** | `jutsu_engine/live/alert_manager.py` |
| **Format** | Rich formatted messages with trade context |

---

## 6. CORS and Security Headers

### 6.1 CORS Configuration

```python
# Production: environment-configured origins
CORS_ORIGINS = "https://your-domain.com"  # comma-separated

# Development: localhost variants (automatic fallback)
cors_origins = [
    "http://localhost:3000",   # React dev server
    "http://localhost:5173",   # Vite dev server
    "http://localhost:8080",   # Alternative dev port
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
]
```

### 6.2 Rate Limiting

| Endpoint | Limit | Purpose |
|----------|-------|---------|
| Login | 5/minute per IP | Brute-force protection |
| 2FA | 5/minute per IP | OTP guessing prevention |
| Passkey | 5/minute per IP | Credential stuffing prevention |
| General API | Configurable | DoS mitigation |

**IP Detection Priority:**
1. `CF-Connecting-IP` (Cloudflare)
2. `X-Real-IP` (NGINX)
3. `X-Forwarded-For` (proxies)
4. Direct connection IP

### 6.3 Request Size Limiting

```python
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB default
# Configurable via MAX_REQUEST_SIZE env variable
# Returns 413 if Content-Length exceeds limit
```

### 6.4 OpenAPI Documentation Toggle

```
# Production: hide API documentation
DISABLE_DOCS=true  →  /docs, /redoc, /openapi.json return 404
```

### 6.5 Global Exception Handler

All unhandled exceptions return a **generic 500 response** — internal details are **never** leaked to the client:

```python
{
    "error": "Internal server error",
    "detail": "An unexpected error occurred. Please try again later."
}
```

Full stack traces are logged server-side only.

---

## 7. Error Handling Conventions

### 7.1 HTTP Status Codes

| Code | Usage |
|------|-------|
| `200` | Success |
| `201` | Created (new resource) |
| `400` | Bad request (invalid parameters) |
| `401` | Unauthorized (missing/invalid token) |
| `403` | Forbidden (insufficient permissions) |
| `404` | Resource not found |
| `413` | Request entity too large |
| `422` | Validation error (Pydantic) |
| `429` | Rate limit exceeded |
| `500` | Internal server error (generic message) |

### 7.2 Deprecation Headers

V1 Performance API endpoints include deprecation headers:

```http
Deprecation: true
Sunset: <date>
Link: </api/v2/daily-performance>; rel="successor-version"
```

---

## 8. Cross-References

| Document | Relevant Sections |
|----------|-------------------|
| [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | Security architecture layers, deployment overview |
| [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | Strategy types referenced in `/api/strategies` |
| [02_DATA_LAYER](./02_DATA_LAYER.md) | Database models underlying API responses |
| [03_FUNCTIONAL_CORE](./03_FUNCTIONAL_CORE.md) | Performance metrics returned by API |
| [05_LIFECYCLE](./05_LIFECYCLE.md) | Authentication flow sequence, trading day flow |
| [06_WORKERS](./06_WORKERS.md) | Scheduler control API, EOD job status |
| [07_INTEGRATION_PATTERNS](./07_INTEGRATION_PATTERNS.md) | Error handling patterns, DI for auth |

---

*This document is part of the [Jutsu Labs Architecture Documentation](./00_SYSTEM_OVERVIEW.md) series.*
