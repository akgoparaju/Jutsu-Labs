# Product Requirements Document: Jutsu Labs Live Trader v3.0

**Version:** 3.0.0
**Status:** Production
**Strategy:** Hierarchical Adaptive v3.5b-v5.1 (Multi-Version Support)
**Platform:** Docker + PostgreSQL + Cloudflare Tunnel + React Dashboard
**Last Updated:** January 5, 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Strategy Configuration](#3-strategy-configuration)
4. [Authentication & Security](#4-authentication--security)
5. [Trading Modes](#5-trading-modes)
6. [Dashboard](#6-dashboard)
7. [Infrastructure](#7-infrastructure)
8. [Monitoring & Notifications](#8-monitoring--notifications)
9. [Data Architecture](#9-data-architecture)
10. [API Reference](#10-api-reference)
11. [Implementation Status](#11-implementation-status)
12. [Success Criteria](#12-success-criteria)

---

## 1. Executive Summary

### 1.1 Objective

Production-grade live trading system for the **Hierarchical Adaptive** strategy family with:

- **Multi-strategy support**: v3.5b through v5.1 with progressive enhancements
- **Dual-mode operation**: Offline mock trading + Online live trading (all phases complete)
- **Enterprise authentication**: JWT tokens + TOTP 2FA + WebAuthn Passkeys
- **Docker deployment**: Production-ready with Cloudflare tunnel and PostgreSQL
- **Real-time dashboard**: React-based monitoring with WebSocket updates
- **Proactive monitoring**: Token expiration alerts via Slack/Discord webhooks

### 1.2 Key Changes from v2.0

| Feature | v2.0 PRD | v3.0 PRD |
|---------|----------|----------|
| Strategy | v3.5b Golden Config | v3.5b → v5.1 (5 versions supported) |
| Symbol Set | 6 symbols | 9 symbols (added GLD, SLV, UUP) |
| Cell Matrix | 6-cell | 6-cell (v3.5b) → 9-cell (v5.x) |
| Database | SQLite (planned PostgreSQL) | PostgreSQL production |
| Authentication | Basic admin password | JWT + TOTP 2FA + WebAuthn Passkeys |
| Sessions | Not specified | 15 min (password) / 7 hours (passkey) |
| Deployment | Manual | Docker + Cloudflare Tunnel |
| Dashboard | Wireframes | Fully implemented React 18 |
| Phases | Planned (0-5) | All 5 phases complete |
| Monitoring | Log files | Webhooks + Dashboard banners |
| Staging | Not defined | Full staging environment architecture |

### 1.3 Strategy Version Summary

| Version | Key Feature | Cell Matrix | New Symbols |
|---------|-------------|-------------|-------------|
| v3.5b | Treasury Overlay (TMF/TMV) | 6-cell | TMF, TMV |
| v3.5c | Shock Brake Protection | 6-cell | - |
| v4.0 | Correlation-Based Routing | 6-cell | - |
| v5.0 | Precious Metals Overlay (GLD/SLV) | 9-cell | GLD, SLV |
| v5.1 | DXY Filter for Hedge Preference | 9-cell | UUP |

### 1.4 Production Deployment Status

| Component | Status | Notes |
|-----------|--------|-------|
| Core Trading Engine | ✅ Production | All phases complete |
| Mock Trading | ✅ Production | Validated 20+ days |
| Live Trading | ✅ Production | Schwab integration complete |
| Dashboard | ✅ Production | React 18 with WebSocket |
| Authentication | ✅ Production | JWT + 2FA + Passkeys |
| PostgreSQL | ✅ Production | Running on Unraid |
| Docker Deployment | ✅ Production | Cloudflare tunnel |
| Monitoring | ✅ Production | Webhook notifications |

---

## 2. System Overview

### 2.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     JUTSU LABS LIVE TRADER v3.0                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │      CLOUDFLARE TUNNEL        │
                    │  • SSL/TLS termination        │
                    │  • DDoS protection            │
                    │  • Zero-trust access          │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │      NGINX REVERSE PROXY      │
                    │  • HSTS headers               │
                    │  • Rate limiting              │
                    │  • Request routing            │
                    └───────────────┬───────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼───────┐           ┌───────▼───────┐           ┌───────▼───────┐
│  DASHBOARD    │           │  FASTAPI      │           │  WEBSOCKET    │
│  (React 18)   │◄─────────►│  BACKEND      │◄─────────►│  SERVER       │
│  • Vite build │   REST    │  • Auth       │   Push    │  • Real-time  │
│  • TailwindCSS│   API     │  • Routes     │   Events  │  • Status     │
│  • TanStack   │           │  • Scheduler  │           │  • Trades     │
└───────────────┘           └───────┬───────┘           └───────────────┘
                                    │
┌───────────────────────────────────┴───────────────────────────────────┐
│                          CORE TRADING ENGINE                          │
├───────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌──────────────────────────────────────┐ │
│  │  SCHEDULER          │    │  STRATEGY RUNNER                      │ │
│  │  ─────────────────  │    │  ──────────────────────────────────  │ │
│  │  • Trading Job      │───▶│  • v3.5b / v3.5c / v4.0 / v5.0 / v5.1│ │
│  │  • Hourly Refresh   │    │  • Runtime parameter injection       │ │
│  │  • Market Close     │    │  • Signal generation                 │ │
│  │  • Token Monitor    │    │  • 6-cell / 9-cell allocation        │ │
│  └─────────────────────┘    └──────────────┬───────────────────────┘ │
│                                             │                         │
│  ┌──────────────────────────────────────────▼────────────────────┐   │
│  │                     EXECUTION ROUTER                           │   │
│  │          MODE: [OFFLINE_MOCK] / [ONLINE_LIVE]                  │   │
│  └─────────┬───────────────────────────────────────┬─────────────┘   │
│            │                                       │                 │
│  ┌─────────▼─────────┐                  ┌──────────▼──────────┐     │
│  │  MOCK EXECUTOR    │                  │  SCHWAB EXECUTOR    │     │
│  │  • Simulates fills│                  │  • Real API orders  │     │
│  │  • Uses mid price │                  │  • Fill verification│     │
│  │  • CSV + DB log   │                  │  • Slippage tracking│     │
│  └─────────┬─────────┘                  └──────────┬──────────┘     │
│            │                                       │                 │
│            └────────────────────┬──────────────────┘                 │
│                    ┌────────────▼────────────┐                       │
│                    │    POSTGRESQL           │                       │
│                    │  • live_trades          │                       │
│                    │  • positions            │                       │
│                    │  • performance_snapshots│                       │
│                    │  • passkeys             │                       │
│                    │  • users                │                       │
│                    └─────────────────────────┘                       │
└───────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼───────┐           ┌───────▼───────┐           ┌───────▼───────┐
│  SCHWAB API   │           │  NOTIFICATION │           │  MARKET DATA  │
│  • Orders     │           │  • Slack      │           │  • Quotes     │
│  • Account    │           │  • Discord    │           │  • Historical │
│  • OAuth      │           │  • Generic    │           │  • Real-time  │
└───────────────┘           └───────────────┘           └───────────────┘
```

### 2.2 Component Summary

| Component | Technology | Purpose | Status |
|-----------|------------|---------|--------|
| Dashboard Frontend | React 18 + Vite + TypeScript | User interface | ✅ Production |
| Dashboard Backend | FastAPI + Uvicorn | REST API + WebSocket | ✅ Production |
| Authentication | JWT + TOTP + WebAuthn | Multi-factor auth | ✅ Production |
| Trading Engine | Python 3.11+ | Strategy execution | ✅ Production |
| Scheduler | APScheduler | Time-based triggers | ✅ Production |
| Database | PostgreSQL 15+ | Persistent storage | ✅ Production |
| Reverse Proxy | NGINX | Load balancing, headers | ✅ Production |
| Tunnel | Cloudflare Tunnel | Secure external access | ✅ Production |
| Broker | Schwab API (schwab-py) | Market data + orders | ✅ Production |
| Notifications | Webhooks | Slack/Discord alerts | ✅ Production |

---

## 3. Strategy Configuration

### 3.1 Strategy Version Matrix

#### Hierarchical Adaptive v3.5b (Base - Golden Config)

**Key Features**:
- 6-cell regime matrix (Trend × Volatility)
- Treasury Overlay: Dynamic bond selection (TMF/TMV) based on TLT trend
- Kalman filter trend detection
- Vol-crush override for compression breakouts

**Symbol Requirements**: QQQ, TQQQ, PSQ, TLT, TMF, TMV

#### Hierarchical Adaptive v5.0 (Commodity-Augmented)

**Key Features**:
- 9-cell regime matrix (extended from 6-cell)
- Hedge Preference Signal: QQQ/TLT correlation routes between Paper (bonds) and Hard (commodities)
- Precious Metals Overlay: GLD/SLV as alternative safe haven
- Gold Momentum (G-Trend): SMA on GLD for commodity trend
- Silver Relative Strength (S-Beta): ROC comparison for silver kicker

**Symbol Requirements**: QQQ, TQQQ, PSQ, TLT, TMF, TMV, GLD, SLV

#### Hierarchical Adaptive v5.1 (DXY-Filtered)

**Key Features**:
- All v5.0 features plus DXY Filter
- Dual-filter hedge preference: Correlation AND DXY momentum
- PAPER preference: Low correlation AND DXY > SMA (dollar strong)
- HARD preference: High correlation OR DXY < SMA (dollar weak)

**Symbol Requirements**: QQQ, TQQQ, PSQ, TLT, TMF, TMV, GLD, SLV, UUP

### 3.2 v3.5b Golden Config Parameters (32 parameters)

```yaml
strategy:
  name: Hierarchical_Adaptive_v3_5b
  parameters:
    # KALMAN TREND (6)
    measurement_noise: 3000.0
    process_noise_1: 0.01
    process_noise_2: 0.01
    osc_smoothness: 15
    strength_smoothness: 15
    T_max: 50.0

    # STRUCTURAL TREND (4)
    sma_fast: 40
    sma_slow: 140
    t_norm_bull_thresh: 0.05
    t_norm_bear_thresh: -0.30

    # VOLATILITY Z-SCORE (4)
    realized_vol_window: 21
    vol_baseline_window: 200
    upper_thresh_z: 1.0
    lower_thresh_z: 0.2

    # VOL-CRUSH OVERRIDE (2)
    vol_crush_threshold: -0.15
    vol_crush_lookback: 5

    # TREASURY OVERLAY (5)
    allow_treasury: true
    bond_sma_fast: 20
    bond_sma_slow: 60
    max_bond_weight: 0.4
    treasury_trend_symbol: TLT

    # ALLOCATION (3)
    leverage_scalar: 1.0
    use_inverse_hedge: false
    w_PSQ_max: 0.5

    # REBALANCING (1)
    rebalance_threshold: 0.025

    # SYMBOLS (7)
    signal_symbol: QQQ
    core_long_symbol: QQQ
    leveraged_long_symbol: TQQQ
    inverse_hedge_symbol: PSQ
    bull_bond_symbol: TMF
    bear_bond_symbol: TMV
```

### 3.3 v5.1 Additional Parameters (8 new)

```yaml
    # HEDGE PREFERENCE (2)
    hedge_corr_threshold: 0.20
    hedge_corr_lookback: 60

    # COMMODITY OVERLAY (4)
    commodity_ma_period: 150
    gold_weight_max: 0.60
    silver_vol_multiplier: 0.5
    silver_momentum_lookback: 20
    silver_momentum_gate: true

    # DXY FILTER (2) - v5.1 only
    dxy_symbol: UUP
    dxy_sma_period: 50

    # ADDITIONAL SYMBOLS (3)
    gold_symbol: GLD
    silver_symbol: SLV
```

---

## 4. Authentication & Security

### 4.1 Authentication Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION FLOW                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐                                           │
│  │  LOGIN REQUEST   │                                           │
│  │  username/pass   │                                           │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐     ┌──────────────────┐                  │
│  │  RATE LIMITER    │────▶│  5 req/min/IP    │                  │
│  │  (slowapi)       │     │  Blocks brute    │                  │
│  └────────┬─────────┘     └──────────────────┘                  │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │  PASSWORD CHECK  │                                           │
│  │  (bcrypt hash)   │                                           │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              2FA CHECK (if enabled)                       │   │
│  │  ┌─────────────────┐         ┌─────────────────────────┐ │   │
│  │  │  HAS PASSKEYS?  │──YES───▶│  PASSKEY CHALLENGE      │ │   │
│  │  │                 │         │  (WebAuthn)             │ │   │
│  │  └────────┬────────┘         └───────────┬─────────────┘ │   │
│  │           │ NO                           │               │   │
│  │           ▼                              │               │   │
│  │  ┌─────────────────┐                     │               │   │
│  │  │  TOTP REQUIRED  │                     │               │   │
│  │  │  (6-digit code) │                     │               │   │
│  │  └────────┬────────┘                     │               │   │
│  │           │                              │               │   │
│  │           └──────────────┬───────────────┘               │   │
│  └──────────────────────────┼───────────────────────────────┘   │
│                             │                                    │
│                             ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    TOKEN ISSUANCE                         │   │
│  │  ┌─────────────────────┐    ┌─────────────────────────┐  │   │
│  │  │  PASSWORD LOGIN     │    │  PASSKEY LOGIN          │  │   │
│  │  │  Access: 15 min     │    │  Access: 7 hours        │  │   │
│  │  │  Refresh: 7 days    │    │  Refresh: 7 days        │  │   │
│  │  └─────────────────────┘    └─────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 JWT Token Configuration

| Token Type | Default Duration | Environment Variable |
|------------|-----------------|---------------------|
| Access Token (password) | 15 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Access Token (passkey) | 7 hours (420 min) | `PASSKEY_TOKEN_EXPIRE_MINUTES` |
| Refresh Token | 7 days | `REFRESH_TOKEN_EXPIRE_DAYS` |

### 4.3 WebAuthn Passkey Features

- **Purpose**: Passwordless 2FA bypass for trusted devices
- **Security**: Hardware-bound credentials (biometric/security key)
- **Multi-device**: Multiple passkeys per user supported
- **Sign Count**: Replay attack protection via counter validation

### 4.4 Security Controls

| Control | Implementation | Configuration |
|---------|---------------|---------------|
| Rate Limiting | slowapi | `LOGIN_RATE_LIMIT=5/minute` |
| Account Lockout | 10 failed attempts | `failed_login_count` in DB |
| CORS | Configurable origins | `CORS_ORIGINS` env var |
| Security Headers | NGINX | HSTS, X-Frame-Options |
| API Docs | Disabled in prod | `DISABLE_DOCS=true` |
| Security Logging | JSON format | ELK/Splunk compatible |

### 4.5 Security Event Types

```python
SECURITY_EVENTS = [
    "LOGIN_SUCCESS",
    "LOGIN_FAILURE",
    "TOKEN_CREATED",
    "TOKEN_REFRESHED",
    "TOKEN_INVALID",
    "PASSKEY_REGISTERED",
    "PASSKEY_AUTHENTICATED",
    "PASSKEY_REVOKED",
    "PASSKEY_AUTH_FAILED",
    "OAUTH_TOKEN_DELETED",
    "2FA_ENABLED",
    "2FA_DISABLED",
]
```

---

## 5. Trading Modes

### 5.1 Mode Architecture (Implemented)

| Mode | Description | API Calls | Database |
|------|-------------|-----------|----------|
| `OFFLINE_MOCK` | Simulated trading with real market data | Data only | Local tracking |
| `ONLINE_LIVE` | Real order execution via Schwab | Data + Orders | Local + Schwab |

### 5.2 Offline Mode Features

- Real Schwab market data (quotes, historical bars)
- Simulated fills at mid-point price
- Full strategy context logging (cell, trend, vol state)
- Performance tracking and daily snapshots
- Trade history in PostgreSQL + CSV backup

**CLI Command**:
```bash
jutsu live --mode mock --execution-time 5min_before_close
```

### 5.3 Online Mode Features

- Real Schwab order execution (MARKET orders)
- Fill verification and slippage tracking
- SELL-first, BUY-second order sequence
- Slippage abort mechanism (>1% threshold)
- Daily 17:00 ET reconciliation
- Schwab order ID tracking

**CLI Command**:
```bash
jutsu live --mode online --execution-time 5min_before_close --confirm
```

### 5.4 Safety Controls (Implemented)

| Control | Status | Description |
|---------|--------|-------------|
| `--confirm` flag | ✅ | Required for online mode |
| Interactive confirmation | ✅ | Type 'YES' in caps |
| Slippage abort | ✅ | >1% cancels order |
| Kill switch | ✅ | Dashboard stop button |
| Daily reconciliation | ✅ | 17:00 ET auto-check |

---

## 6. Dashboard

### 6.1 Technology Stack (Implemented)

| Layer | Technology | Version |
|-------|------------|---------|
| Framework | React | 18.x |
| Build Tool | Vite | 5.x |
| Language | TypeScript | 5.x |
| Styling | Tailwind CSS | 3.x |
| State Management | TanStack Query | 5.x |
| Charts | lightweight-charts | 4.x |
| Icons | lucide-react | 0.300+ |
| WebSocket | Native WebSocket | - |

### 6.2 Implemented Features

| Feature | Priority | Status | Description |
|---------|----------|--------|-------------|
| Mode Toggle | P0 | ✅ | Switch offline/online |
| Regime Display | P0 | ✅ | Cell, trend, vol state |
| Portfolio View | P0 | ✅ | Positions and values |
| Trade History | P0 | ✅ | Paginated with filters |
| Indicator Panel | P1 | ✅ | Live indicator values |
| Execution Time | P1 | ✅ | Selectable windows |
| Performance Metrics | P1 | ✅ | Returns, Sharpe, DD |
| Parameter Editor | P2 | ✅ | Runtime overrides |
| WebSocket Updates | P2 | ✅ | Real-time refresh |
| Equity Chart | P3 | ✅ | TradingView-style |
| Scheduler Controls | P3 | ✅ | Start/stop jobs |
| Schwab Token Banner | P3 | ✅ | Expiration warnings |
| Passkey Management | P3 | ✅ | Register/revoke |
| 2FA Settings | P3 | ✅ | Enable/disable TOTP |

### 6.3 Dashboard Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Main control panel, regime, portfolio |
| Trades | `/trades` | History with pagination, CSV export |
| Performance | `/performance` | Metrics, equity chart, regime breakdown |
| Config | `/config` | Parameter editor with validation |
| Settings | `/settings` | 2FA, passkeys, account |
| Login | `/login` | Authentication flow |

### 6.4 Schwab Token Banner

Real-time token status monitoring with color-coded banners:

| Remaining | Banner Color | Action |
|-----------|--------------|--------|
| > 5 days | Hidden | None needed |
| 2-5 days | Info (blue) | Plan re-auth |
| 1-2 days | Warning (yellow) | Re-auth soon |
| < 12 hours | Critical (red) | Re-auth now |
| Expired | Critical (red) | Re-auth required |

**One-Click Re-Auth Flow**:
1. Click "Re-authenticate" → Modal opens
2. Click "Open Schwab" → New tab to Schwab login
3. Login and authorize → Redirected to callback
4. Copy redirect URL → Paste into modal
5. Click "Complete Authentication" → Done

---

## 7. Infrastructure

### 7.1 Docker Deployment

**Container Architecture**:
```
┌─────────────────────────────────────────────────────┐
│                    DOCKER HOST (Unraid)             │
├─────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────┐  │
│  │  jutsu-labs:latest                            │  │
│  │  • FastAPI backend (port 8000)                │  │
│  │  • React dashboard (port 3000)                │  │
│  │  • NGINX reverse proxy                        │  │
│  │  • APScheduler                                │  │
│  └───────────────────────────────────────────────┘  │
│                         │                           │
│  ┌──────────────────────▼────────────────────────┐  │
│  │  PostgreSQL 15 (port 5432)                    │  │
│  │  • jutsu_labs database                        │  │
│  │  • Persistent volume                          │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 7.2 Environment Variables

```bash
# Database
DATABASE_TYPE=postgresql
POSTGRES_HOST=tower.local
POSTGRES_PORT=5432
POSTGRES_USER=jutsu
POSTGRES_PASSWORD=<secure_password>
POSTGRES_DATABASE=jutsu_labs

# Authentication
AUTH_REQUIRED=true
SECRET_KEY=<openssl rand -hex 32>
ADMIN_PASSWORD=<secure_password>
ACCESS_TOKEN_EXPIRE_MINUTES=15
PASSKEY_TOKEN_EXPIRE_MINUTES=420

# WebAuthn
WEBAUTHN_RP_ID=your-domain.com
WEBAUTHN_RP_NAME=Jutsu Trading
WEBAUTHN_ORIGIN=https://your-domain.com

# Schwab
SCHWAB_API_KEY=<api_key>
SCHWAB_APP_SECRET=<app_secret>
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182/

# Notifications
NOTIFICATION_WEBHOOK_URL=https://hooks.slack.com/...
NOTIFICATION_WEBHOOK_TYPE=slack

# Security
CORS_ORIGINS=https://your-domain.com
DISABLE_DOCS=true
LOGIN_RATE_LIMIT=5/minute
```

### 7.3 Staging Environment

Separate staging environment for testing:

| Aspect | Production | Staging |
|--------|------------|---------|
| Branch | `main` | `staging` |
| Docker Tag | `latest` | `staging` |
| API Port | 8000 | 8002 |
| Dashboard Port | 3000 | 3002 |
| Database | `jutsu_labs` | `jutsu_labs_staging` |
| Schwab | Enabled | `SCHWAB_ENABLED=false` |
| Trading | All modes | `PAPER_TRADING_ONLY=true` |

**Database Sync**: Nightly pg_dump/pg_restore of `market_data` and `performance_snapshots` (not positions/trades).

### 7.4 CI/CD Pipeline

```yaml
# GitHub Actions workflow
on:
  push:
    branches: [main, staging]

jobs:
  build:
    - Build Docker image
    - Run unit tests
    - Push to Docker Hub (ankugo/jutsu-labs:tag)
  
  deploy:
    - Watchtower auto-updates containers
```

---

## 8. Monitoring & Notifications

### 8.1 Schwab Token Monitoring

**Scheduled Job**: `token_expiration_check_job`
- Runs every 12 hours via APScheduler
- Checks token expiration from `get_token_status()`
- Sends notifications at thresholds

**Notification Thresholds**:
| Remaining | Level | Action |
|-----------|-------|--------|
| 5 days | NOTICE | Plan re-auth |
| 2 days | WARNING | Re-auth soon |
| 1 day | CRITICAL | Re-auth today |
| 12 hours | URGENT | Re-auth immediately |
| Expired | EXPIRED | Cannot trade |

### 8.2 Webhook Configuration

**Supported Platforms**:
- Slack (`hooks.slack.com`)
- Discord (`discord.com/api/webhooks`)
- Generic HTTP POST

**Example Slack Message**:
```json
{
  "text": "⚠️ Schwab Token Expires in 2 Days",
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Token Expiration Warning*\nYour Schwab OAuth token expires in 2 days.\n<https://dashboard.example.com|Re-authenticate now>"
      }
    }
  ]
}
```

### 8.3 Scheduler Jobs

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `trading_job` | Cron (15:55 ET M-F) | Execute strategy |
| `hourly_refresh_job` | Every hour | Update market data |
| `market_close_job` | Cron (16:05 ET M-F) | EOD snapshot |
| `token_expiration_check_job` | Every 12 hours | Check Schwab token |

---

## 9. Data Architecture

### 9.1 PostgreSQL Schema

```sql
-- Core trading tables
CREATE TABLE live_trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    target_price NUMERIC(18,6),
    fill_price NUMERIC(18,6),
    slippage_pct NUMERIC(8,4),
    mode VARCHAR(20) NOT NULL,
    schwab_order_id VARCHAR(50),
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    t_norm NUMERIC(8,4),
    z_score NUMERIC(8,4),
    execution_time_setting VARCHAR(30),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    avg_cost NUMERIC(18,6),
    current_value NUMERIC(18,6),
    mode VARCHAR(20) NOT NULL,
    last_updated TIMESTAMPTZ,
    UNIQUE(symbol, mode)
);

CREATE TABLE performance_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    mode VARCHAR(20) NOT NULL,
    total_equity NUMERIC(18,6),
    daily_return NUMERIC(8,4),
    cumulative_return NUMERIC(8,4),
    drawdown NUMERIC(8,4),
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    positions_json JSONB,
    baseline_value NUMERIC(18,6),
    baseline_return NUMERIC(8,4),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Authentication tables
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE,
    totp_secret VARCHAR(32),
    totp_enabled BOOLEAN DEFAULT FALSE,
    backup_codes TEXT[],
    failed_login_count INTEGER DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE passkeys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    credential_id BYTEA UNIQUE NOT NULL,
    public_key BYTEA NOT NULL,
    sign_count INTEGER DEFAULT 0,
    device_name VARCHAR(100),
    aaguid VARCHAR(36),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_passkeys_user_id ON passkeys(user_id);
CREATE INDEX idx_passkeys_credential_id ON passkeys(credential_id);
```

---

## 10. API Reference

### 10.1 Authentication Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/auth/login` | Login with password | No |
| POST | `/api/auth/login/2fa` | Complete 2FA | No |
| POST | `/api/auth/refresh` | Refresh tokens | Refresh |
| POST | `/api/auth/logout` | Logout | Access |
| GET | `/api/auth/me` | Current user | Access |

### 10.2 Passkey Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/passkey/register/options` | Get registration options | Access |
| POST | `/api/passkey/register` | Complete registration | Access |
| POST | `/api/passkey/authenticate/options` | Get auth options | No |
| POST | `/api/passkey/authenticate` | Authenticate | No |
| GET | `/api/passkey/list` | List passkeys | Access |
| DELETE | `/api/passkey/{id}` | Revoke passkey | Access |

### 10.3 Trading Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/status` | System status | Access |
| GET | `/api/status/health` | Health check | No |
| GET | `/api/status/regime` | Current regime | Access |
| GET | `/api/trades` | Trade history | Access |
| GET | `/api/trades/export` | CSV export | Access |
| GET | `/api/performance` | Metrics | Access |
| GET | `/api/performance/equity-curve` | Chart data | Access |
| GET | `/api/indicators` | Current values | Access |

### 10.4 Control Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/control/start` | Start engine | Access |
| POST | `/api/control/stop` | Stop engine | Access |
| POST | `/api/control/restart` | Restart engine | Access |
| GET | `/api/control/state` | Engine state | Access |
| GET | `/api/scheduler/jobs` | List jobs | Access |
| POST | `/api/scheduler/jobs/{id}/pause` | Pause job | Access |
| POST | `/api/scheduler/jobs/{id}/resume` | Resume job | Access |

### 10.5 Schwab Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/schwab/status` | Token status | Access |
| POST | `/api/schwab/initiate` | Start OAuth | Access |
| POST | `/api/schwab/callback` | Complete OAuth | Access |
| DELETE | `/api/schwab/token` | Revoke token | Access |

### 10.6 WebSocket

| Endpoint | Events |
|----------|--------|
| `/ws?token=<jwt>` | `status_update`, `trade_executed`, `regime_change`, `error` |

---

## 11. Implementation Status

### 11.1 Phase Completion

| Phase | Description | Status | Completion |
|-------|-------------|--------|------------|
| Phase 0 | Foundation (models, flat config) | ✅ Complete | Dec 2025 |
| Phase 1 | Offline Mock Trading | ✅ Complete | Dec 2025 |
| Phase 2 | Online Live Trading | ✅ Complete | Dec 2025 |
| Phase 3 | Dashboard MVP | ✅ Complete | Dec 2025 |
| Phase 4 | Dashboard Advanced | ✅ Complete | Dec 2025 |
| Phase 5 | Production Hardening | ✅ Complete | Jan 2026 |

### 11.2 Feature Completion

| Category | Feature | Status |
|----------|---------|--------|
| **Core** | Strategy v3.5b-v5.1 | ✅ |
| **Core** | Offline mock trading | ✅ |
| **Core** | Online live trading | ✅ |
| **Core** | Schwab integration | ✅ |
| **Auth** | JWT authentication | ✅ |
| **Auth** | TOTP 2FA | ✅ |
| **Auth** | WebAuthn Passkeys | ✅ |
| **Auth** | Rate limiting | ✅ |
| **Dashboard** | React frontend | ✅ |
| **Dashboard** | WebSocket updates | ✅ |
| **Dashboard** | Token banner | ✅ |
| **Dashboard** | Passkey management | ✅ |
| **Infra** | PostgreSQL | ✅ |
| **Infra** | Docker deployment | ✅ |
| **Infra** | Cloudflare tunnel | ✅ |
| **Monitor** | Webhook notifications | ✅ |
| **Monitor** | Token monitoring | ✅ |

---

## 12. Success Criteria

### 12.1 Offline Mode Validation ✅

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| Uptime | 20 days | 30+ days | ✅ |
| Logic Match | 100% | 100% | ✅ |
| Database Integrity | 100% | 100% | ✅ |
| Performance Tracking | Accurate | Accurate | ✅ |

### 12.2 Online Mode Validation ✅

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| Fill Rate | 100% | 100% | ✅ |
| Slippage | <0.5% avg | <0.3% avg | ✅ |
| Reconciliation | Match | Match | ✅ |
| Safety | No incidents | No incidents | ✅ |

### 12.3 Dashboard Validation ✅

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| Availability | 99.9% | 99.9%+ | ✅ |
| Latency | <1s | <500ms | ✅ |
| Accuracy | 100% | 100% | ✅ |
| Usability | Positive | Positive | ✅ |

### 12.4 Security Validation ✅

| Criterion | Target | Status |
|-----------|--------|--------|
| Auth bypass | None | ✅ Fixed |
| SQL injection | None | ✅ Verified |
| XSS prevention | 100% | ✅ Verified |
| Rate limiting | Active | ✅ Active |
| Security logging | Complete | ✅ Complete |

---

## Appendix A: CLI Reference

```bash
# Live trading
jutsu live --mode mock --execution-time 5min_before_close
jutsu live --mode online --execution-time 5min_before_close --confirm
jutsu live status

# Data sync
jutsu sync --symbol QQQ --start 2020-01-01
jutsu sync --all

# Grid search
jutsu grid-search --config grid-configs/examples/grid_search_hierarchical_adaptive_v5_1.yaml

# Walk-forward optimization
jutsu wfo --config grid-configs/examples/wfo_hierarchical_adaptive_v5_1.yaml

# Dashboard
jutsu dashboard --port 8000 --host 0.0.0.0

# Backtest
jutsu backtest --strategy Hierarchical_Adaptive_v5_1 --start 2010-01-01 --end 2025-12-31
```

---

## Appendix B: Migration from v2.0

### Database Migration

```sql
-- Add authentication columns to users
ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN totp_secret VARCHAR(32);
ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN backup_codes TEXT[];

-- Create passkeys table
CREATE TABLE passkeys (...);

-- Add v5.x columns to performance_snapshots
ALTER TABLE performance_snapshots ADD COLUMN baseline_value NUMERIC(18,6);
ALTER TABLE performance_snapshots ADD COLUMN baseline_return NUMERIC(8,4);
```

### Environment Variable Changes

| v2.0 | v3.0 | Notes |
|------|------|-------|
| `JUTSU_API_USERNAME` | Deprecated | Use `ADMIN_PASSWORD` |
| `JUTSU_API_PASSWORD` | Deprecated | Use `ADMIN_PASSWORD` |
| - | `AUTH_REQUIRED=true` | New required |
| - | `SECRET_KEY` | New required |
| - | `PASSKEY_TOKEN_EXPIRE_MINUTES` | New optional |
| - | `NOTIFICATION_WEBHOOK_URL` | New optional |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Nov 2025 | Team | Original PRD |
| 2.0 | Dec 2025 | Team | Dual-mode, dashboard, multi-time |
| 2.0.1 | Dec 2025 | Claude | Audit corrections |
| 3.0.0 | Jan 2026 | Claude | Production release - all phases complete, v5.1 strategy, passkeys, PostgreSQL, Docker, monitoring |

---

**End of Document**
