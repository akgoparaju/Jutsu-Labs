# 02 - Data Layer

> Database schema, data models, persistence patterns, and data lifecycle for Jutsu Labs

**Last Updated**: January 25, 2026
**Version**: 1.0
**Status**: Active

---

## Table of Contents

1. [Overview](#overview)
2. [Database Architecture](#database-architecture)
3. [Entity Relationship Diagram](#entity-relationship-diagram)
4. [Core Tables Schema](#core-tables-schema)
5. [SQLAlchemy Models](#sqlalchemy-models)
6. [Data Migration Strategy](#data-migration-strategy)
7. [Data Integrity Constraints](#data-integrity-constraints)
8. [Data Flow Patterns](#data-flow-patterns)
9. [Backup and Recovery](#backup-and-recovery)
10. [Related Documents](#related-documents)

---

## Overview

The Jutsu Labs data layer provides persistent storage for market data, trading activity, performance metrics, and user management. The architecture supports both development (SQLite) and production (PostgreSQL) environments with identical schemas.

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Financial Precision** | `Numeric(18,6)` for all monetary values (no floating-point errors) |
| **UTC Timestamps** | All timestamps stored with timezone (`DateTime(timezone=True)`) |
| **Immutable History** | Market data and trades are append-only after creation |
| **Multi-Strategy Support** | `strategy_id` column enables strategy-specific data isolation |
| **Audit Trail** | `created_at` timestamps on all tables with `server_default` |

### Data Categories

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA LAYER CATEGORIES                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  MARKET DATA     │  │  TRADING DATA    │  │  USER DATA       │  │
│  │                  │  │                  │  │                  │  │
│  │  • market_data   │  │  • live_trades   │  │  • users         │  │
│  │  • data_metadata │  │  • positions     │  │  • passkeys      │  │
│  │                  │  │  • performance_  │  │  • user_         │  │
│  │                  │  │    snapshots     │  │    invitations   │  │
│  │                  │  │  • daily_        │  │  • blacklisted_  │  │
│  │                  │  │    performance   │  │    tokens        │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐                        │
│  │  SYSTEM STATE    │  │  CONFIGURATION   │                        │
│  │                  │  │                  │                        │
│  │  • system_state  │  │  • config_       │                        │
│  │                  │  │    override      │                        │
│  │                  │  │  • config_       │                        │
│  │                  │  │    history       │                        │
│  └──────────────────┘  └──────────────────┘                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Database Architecture

### Supported Backends

| Backend | Use Case | Configuration | Connection String |
|---------|----------|---------------|-------------------|
| **SQLite** | Development, Testing | `DATABASE_TYPE=sqlite` | `sqlite:///data/market_data.db` |
| **PostgreSQL** | Production | `DATABASE_TYPE=postgresql` | `postgresql://user:pass@host:port/db` |

### PostgreSQL Production Configuration

```yaml
# Environment Variables
POSTGRES_HOST: tower.local
POSTGRES_PORT: 5423
POSTGRES_USER: jutsudB
POSTGRES_DATABASE: jutsu_labs
DATABASE_TYPE: postgresql
```

### Database Factory Pattern

The system uses a factory pattern to abstract database backend selection:

```python
# jutsu_engine/data/database_factory.py
class DatabaseFactory:
    @staticmethod
    def create_session() -> Session:
        """Create database session based on DATABASE_TYPE env var."""
        db_type = os.getenv("DATABASE_TYPE", "sqlite")
        if db_type == "postgresql":
            return PostgreSQLSession()
        return SQLiteSession()
```

---

## Entity Relationship Diagram

```mermaid
erDiagram
    MARKET_DATA ||--o{ DATA_METADATA : tracks

    USER ||--o{ PASSKEY : owns
    USER ||--o{ USER_INVITATION : creates

    STRATEGY ||--o{ LIVE_TRADE : generates
    STRATEGY ||--o{ POSITION : manages
    STRATEGY ||--o{ PERFORMANCE_SNAPSHOT : captures
    STRATEGY ||--o{ DAILY_PERFORMANCE : aggregates

    MARKET_DATA {
        int id PK
        string symbol
        string timeframe
        timestamp timestamp
        decimal open
        decimal high
        decimal low
        decimal close
        bigint volume
        string data_source
    }

    DAILY_PERFORMANCE {
        int id PK
        date trading_date
        string entity_type
        string entity_id
        string mode
        decimal total_equity
        decimal daily_return
        decimal sharpe_ratio
        int strategy_cell
    }

    LIVE_TRADE {
        int id PK
        timestamp timestamp
        string strategy_id
        string symbol
        string action
        int quantity
        decimal fill_price
        string mode
    }

    POSITION {
        int id PK
        string symbol
        int quantity
        decimal avg_cost
        string strategy_id
        string mode
    }

    USER {
        int id PK
        string username UK
        string password_hash
        string role
        boolean totp_enabled
    }

    PASSKEY {
        int id PK
        int user_id FK
        bytes credential_id UK
        bytes public_key
        int sign_count
    }
```

---

## Core Tables Schema

### market_data

Primary storage for OHLCV price data with source tracking.

```sql
CREATE TABLE market_data (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,           -- '1D', '1H', '5m'
    timestamp TIMESTAMPTZ NOT NULL,

    -- OHLCV data (Numeric for financial precision)
    open NUMERIC(18,6) NOT NULL,
    high NUMERIC(18,6) NOT NULL,
    low NUMERIC(18,6) NOT NULL,
    close NUMERIC(18,6) NOT NULL,
    volume BIGINT NOT NULL,

    -- Metadata
    data_source VARCHAR(20) NOT NULL,         -- 'schwab', 'yahoo', 'csv'
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,

    -- Constraints
    CONSTRAINT uix_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp)
);

-- Indexes for query performance
CREATE INDEX idx_market_data_lookup ON market_data(symbol, timeframe, timestamp);
CREATE INDEX idx_market_data_symbol ON market_data(symbol);
CREATE INDEX idx_market_data_ts ON market_data(timestamp);
```

**Key Design Decisions**:
- `Numeric(18,6)` provides 12 integer + 6 decimal digits (handles all price ranges)
- `is_valid` flag allows marking bad data without deletion
- Unique constraint prevents duplicate bars during sync operations

---

### daily_performance (V2 API)

Authoritative end-of-day performance metrics - **single source of truth** for strategy performance.

```sql
CREATE TABLE daily_performance (
    id SERIAL PRIMARY KEY,

    -- Composite Natural Key
    trading_date DATE NOT NULL,               -- No time component
    entity_type VARCHAR(10) NOT NULL,         -- 'strategy' or 'baseline'
    entity_id VARCHAR(50) NOT NULL,           -- 'v3_5b', 'QQQ', etc.
    mode VARCHAR(20) NOT NULL,                -- 'offline_mock' or 'online_live'

    -- Portfolio State (End of Day)
    total_equity NUMERIC(18,6) NOT NULL,
    cash NUMERIC(18,6),
    positions_value NUMERIC(18,6),
    positions_json TEXT,                      -- JSON: [{symbol, quantity, value}]

    -- Daily Metrics (as decimals: 0.01 = 1%)
    daily_return NUMERIC(10,6) NOT NULL,
    cumulative_return NUMERIC(10,6) NOT NULL,
    drawdown NUMERIC(10,6),

    -- Pre-Computed KPIs (All-Time)
    sharpe_ratio NUMERIC(10,6),
    sortino_ratio NUMERIC(10,6),
    calmar_ratio NUMERIC(10,6),
    max_drawdown NUMERIC(10,6),
    volatility NUMERIC(10,6),
    cagr NUMERIC(10,6),

    -- Strategy State (NULL for baselines)
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),

    -- Indicator Values (NULL for baselines)
    t_norm NUMERIC(10,6),
    z_score NUMERIC(10,6),
    sma_fast NUMERIC(18,6),
    sma_slow NUMERIC(18,6),

    -- Trade Statistics (NULL for baselines)
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5,2),

    -- Metadata
    baseline_symbol VARCHAR(20),
    initial_capital NUMERIC(18,6),
    high_water_mark NUMERIC(18,6),
    trading_days_count INTEGER,

    -- Corner Case Handling (v1.1)
    days_since_previous INTEGER DEFAULT 1,
    is_first_day BOOLEAN DEFAULT FALSE,

    -- Incremental KPI State (Welford's algorithm)
    returns_sum NUMERIC(18,8),
    returns_sum_sq NUMERIC(18,8),
    downside_sum_sq NUMERIC(18,8),
    returns_count INTEGER,

    finalized_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uix_daily_perf UNIQUE (trading_date, entity_type, entity_id, mode)
);

CREATE INDEX idx_daily_perf_date ON daily_performance(trading_date);
CREATE INDEX idx_daily_perf_entity ON daily_performance(entity_type, entity_id);
CREATE INDEX idx_daily_perf_mode_entity ON daily_performance(mode, entity_type, entity_id, trading_date);
```

**Key Design Decisions**:
- Fixes Sharpe ratio bug (was showing -4 instead of ~0.82) by having exactly one row per day
- Supports both strategies and baselines (QQQ buy-and-hold) in single table
- Uses Welford's algorithm for numerically stable variance calculation
- Pre-computes all KPIs at EOD (4:15 PM ET) instead of on-the-fly

---

### live_trades

Complete audit trail of all trading activity.

```sql
CREATE TABLE live_trades (
    id SERIAL PRIMARY KEY,

    -- Trade Identification
    symbol VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    strategy_id VARCHAR(50) DEFAULT 'v3_5b',

    -- Execution Details
    action VARCHAR(10) NOT NULL,              -- 'BUY' or 'SELL'
    quantity INTEGER NOT NULL,
    target_price NUMERIC(18,6) NOT NULL,      -- Price at signal time
    fill_price NUMERIC(18,6),                 -- Actual execution (NULL for mock)
    fill_value NUMERIC(18,6),                 -- qty * price
    slippage_pct NUMERIC(10,6),               -- (fill - target) / target * 100

    -- External References
    schwab_order_id VARCHAR(50),              -- Schwab API order ID

    -- Strategy Context
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    t_norm NUMERIC(10,6),
    z_score NUMERIC(10,6),

    -- Classification
    reason VARCHAR(50),                       -- 'Rebalance', 'Signal Change'
    mode VARCHAR(20) NOT NULL,                -- 'offline_mock' or 'online_live'

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_live_trades_mode_ts ON live_trades(mode, timestamp);
CREATE INDEX idx_live_trades_symbol_mode ON live_trades(symbol, mode);
CREATE INDEX idx_live_trades_strategy ON live_trades(strategy_id, timestamp);
```

---

### positions

Current portfolio holdings by strategy and mode.

```sql
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,

    symbol VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost NUMERIC(18,6),
    market_value NUMERIC(18,6),
    unrealized_pnl NUMERIC(18,6),

    mode VARCHAR(20) NOT NULL,
    strategy_id VARCHAR(50) DEFAULT 'v3_5b',

    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uix_position_symbol_mode_strategy
        UNIQUE (symbol, mode, strategy_id)
);

CREATE INDEX idx_positions_mode ON positions(mode);
CREATE INDEX idx_positions_strategy ON positions(strategy_id);
```

---

### users

User authentication with RBAC and 2FA support.

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,

    -- Authentication
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,      -- bcrypt hash
    email VARCHAR(255) UNIQUE,

    -- RBAC
    role VARCHAR(20) DEFAULT 'viewer' NOT NULL,  -- 'admin' or 'viewer'
    is_active BOOLEAN DEFAULT TRUE,

    -- Account Lockout (brute force protection)
    failed_login_count INTEGER DEFAULT 0,
    locked_until TIMESTAMPTZ,

    -- Two-Factor Authentication
    totp_secret VARCHAR(255),                 -- Fernet-encrypted TOTP secret
    totp_enabled BOOLEAN DEFAULT FALSE,
    backup_codes JSON,                        -- bcrypt-hashed backup codes

    -- Session Tracking
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_role ON users(role);
```

**Security Features**:
- Passwords hashed with bcrypt (12 rounds)
- TOTP secrets encrypted with Fernet (AES-256-GCM)
- Backup codes stored as bcrypt hashes
- Account lockout after 10 failed attempts (30-minute lockout)

---

### passkeys

WebAuthn/FIDO2 credentials for passwordless 2FA.

```sql
CREATE TABLE passkeys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- WebAuthn Credential Data
    credential_id BYTEA NOT NULL UNIQUE,
    public_key BYTEA NOT NULL,                -- COSE format
    sign_count INTEGER DEFAULT 0 NOT NULL,    -- Replay attack protection

    -- Metadata
    device_name VARCHAR(100),                 -- 'MacBook Pro', 'iPhone 15'
    aaguid VARCHAR(36),                       -- Authenticator identification

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_passkeys_credential_id ON passkeys(credential_id);
CREATE INDEX idx_passkeys_user_id ON passkeys(user_id);
```

---

### system_state

Key-value store for system state persistence and crash recovery.

```sql
CREATE TABLE system_state (
    id SERIAL PRIMARY KEY,

    key VARCHAR(50) NOT NULL UNIQUE,
    value TEXT,                               -- JSON-serialized value
    value_type VARCHAR(20),                   -- 'string', 'int', 'json', 'datetime'

    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_system_state_key ON system_state(key);
```

**Common Keys**:
- `last_trading_job_run`: Timestamp of last trading execution
- `current_regime`: JSON with cell, trend_state, vol_state
- `scheduler_health`: Last health check status

---

## SQLAlchemy Models

### Model Hierarchy

```
Base (declarative_base)
├── MarketData
├── DataMetadata
├── DataAuditLog
├── LiveTrade
├── Position
├── PerformanceSnapshot
├── DailyPerformance
├── ConfigOverride
├── ConfigHistory
├── SystemState
├── User
│   └── passkeys (relationship)
├── Passkey
├── BlacklistedToken
├── UserInvitation
└── EODJobStatus
```

### Key Model Patterns

#### Financial Precision Pattern

```python
from sqlalchemy import Column, Numeric

# CORRECT: Use Numeric for money
total_equity = Column(Numeric(18, 6), nullable=False)

# WRONG: Float loses precision
total_equity = Column(Float, nullable=False)
```

#### Server Default Pattern

```python
from sqlalchemy import func

# CORRECT: Database applies default on ANY insert
created_at = Column(DateTime(timezone=True), server_default=func.now())

# WRONG: Only applies when SQLAlchemy creates the object
created_at = Column(DateTime, default=datetime.utcnow)
```

#### Multi-Strategy Pattern

```python
# All trading-related tables include strategy_id
strategy_id = Column(String(50), default='v3_5b')

# Unique constraints include strategy_id
__table_args__ = (
    UniqueConstraint('symbol', 'mode', 'strategy_id',
                     name='uix_position_symbol_mode_strategy'),
)
```

---

## Data Migration Strategy

### Alembic Configuration

Migrations are managed with Alembic, stored in `alembic/versions/`.

```
alembic/
├── alembic.ini
├── env.py
└── versions/
    ├── 20251216_0011_create_passkeys_table.py
    ├── 20260113_0001_add_user_roles_and_invitations.py
    ├── 20260114_0001_add_snapshot_source_column.py
    ├── 20260114_0002_add_indicator_columns.py
    ├── 20260114_0003_fix_backup_codes_column_type.py
    ├── 20260117_0001_encrypt_totp_hash_backup_codes.py
    ├── 20260120_0001_add_strategy_id_columns.py
    ├── 20260122_0001_add_strategy_id_to_positions.py
    └── 20260123_0001_add_daily_performance.py
```

### Migration Commands

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current revision
alembic current
```

### Migration Best Practices

| Practice | Rationale |
|----------|-----------|
| Always backup before migrating | Protect against data loss |
| Test migrations on staging first | Catch issues before production |
| Use `server_default` for new columns | Ensure compatibility with raw SQL |
| Add indexes in separate migration | Avoid long locks on large tables |

---

## Data Integrity Constraints

### Unique Constraints

| Table | Constraint | Purpose |
|-------|------------|---------|
| `market_data` | `(symbol, timeframe, timestamp)` | One bar per symbol/timeframe/time |
| `daily_performance` | `(trading_date, entity_type, entity_id, mode)` | One row per entity per day |
| `positions` | `(symbol, mode, strategy_id)` | One position per symbol/strategy |
| `users` | `(username)` | Unique usernames |
| `passkeys` | `(credential_id)` | Unique WebAuthn credentials |

### Foreign Key Constraints

```sql
-- Passkeys cascade delete with user
passkeys.user_id REFERENCES users(id) ON DELETE CASCADE
```

### Check Constraints (Application Level)

| Validation | Implementation |
|------------|----------------|
| Valid action | `action IN ('BUY', 'SELL')` |
| Valid mode | `mode IN ('offline_mock', 'online_live')` |
| Valid role | `role IN ('admin', 'viewer')` |
| Positive quantity | `quantity > 0` |
| Valid timeframe | `timeframe IN ('1D', '1H', '5m', '15m')` |

---

## Data Flow Patterns

### Market Data Ingestion

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MARKET DATA INGESTION FLOW                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌───────────┐     ┌───────────┐     ┌───────────┐                 │
│  │ Schwab    │     │ DataSync  │     │ market_   │                 │
│  │ Yahoo     │────►│ Service   │────►│ data      │                 │
│  │ CSV       │     │           │     │           │                 │
│  └───────────┘     │ • Normalize│     └─────┬─────┘                 │
│                    │ • Validate │           │                       │
│                    │ • Dedupe   │           ▼                       │
│                    └───────────┘     ┌───────────┐                 │
│                                      │ data_     │                 │
│                                      │ metadata  │                 │
│                                      └───────────┘                 │
│                                                                      │
│  Deduplication Strategy:                                            │
│  • Check (symbol, timeframe, trading_date) before insert            │
│  • Skip existing bars, only insert new data                         │
│  • Update data_metadata.last_bar_timestamp after sync               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Performance Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                   PERFORMANCE DATA FLOW                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  LIVE TRADING (3:55 PM ET)            EOD JOB (4:15 PM ET)          │
│  ─────────────────────────            ────────────────────           │
│                                                                      │
│  ┌───────────┐                       ┌───────────────────┐          │
│  │ Strategy  │                       │ EOD Finalization  │          │
│  │ Runner    │                       │ Job               │          │
│  └─────┬─────┘                       └─────────┬─────────┘          │
│        │                                       │                     │
│        ▼                                       ▼                     │
│  ┌───────────┐                       ┌───────────────────┐          │
│  │ live_     │                       │ daily_            │          │
│  │ trades    │──────────────────────►│ performance       │          │
│  │           │    Aggregates         │ (V2 API)          │          │
│  └───────────┘                       └─────────┬─────────┘          │
│        │                                       │                     │
│        ▼                                       │                     │
│  ┌───────────┐                                 │                     │
│  │ positions │                                 │                     │
│  └───────────┘                                 │                     │
│        │                                       │                     │
│        ▼                                       ▼                     │
│  ┌───────────┐                       ┌───────────────────┐          │
│  │performance│                       │ REST API          │          │
│  │_snapshots │──────────────────────►│ Dashboard         │          │
│  │(V1 Legacy)│    Real-time          │                   │          │
│  └───────────┘                       └───────────────────┘          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Lifecycle

| Stage | Tables Affected | Retention |
|-------|-----------------|-----------|
| **Ingest** | `market_data`, `data_metadata` | Indefinite |
| **Trade** | `live_trades`, `positions` | Indefinite |
| **Snapshot** | `performance_snapshots` | 1 year rolling |
| **Aggregate** | `daily_performance` | Indefinite |
| **Session** | `blacklisted_tokens` | 30 days |

---

## Backup and Recovery

### Backup Strategy

```bash
# Quick backup (PostgreSQL)
docker exec CONTAINER pg_dump -U jutsudB -d jutsu_labs > backup_$(date +%Y%m%d).sql

# Scheduled backup (cron - daily at 2 AM)
0 2 * * * docker exec $(docker ps -qf "ancestor=postgres") pg_dump -U jutsudB -d jutsu_labs > /backups/jutsu_$(date +\%Y\%m\%d).sql
```

### Recovery Procedure

```bash
# 1. Stop applications using database
docker stop jutsu-labs

# 2. Restore from backup
docker exec -i CONTAINER psql -U jutsudB -d jutsu_labs < backup_20260125.sql

# 3. Verify data integrity
docker exec CONTAINER psql -U jutsudB -d jutsu_labs -c "SELECT COUNT(*) FROM market_data;"

# 4. Restart application
docker start jutsu-labs
```

### Backup Best Practices

| Practice | Frequency | Retention |
|----------|-----------|-----------|
| Full database backup | Daily | 30 days |
| Transaction log backup | Hourly | 7 days |
| Pre-migration backup | Before each migration | Until verified |
| Offsite copy | Weekly | 90 days |

---

## Related Documents

| Document | Description |
|----------|-------------|
| [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | High-level system context |
| [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | Business domain concepts |
| [03_FUNCTIONAL_CORE](./03_FUNCTIONAL_CORE.md) | Core algorithms and EventLoop |
| [04_BOUNDARIES](./04_BOUNDARIES.md) | API layer and external integrations |
| [DATABASE_OPERATIONS](../Archive/DATABASE_OPERATIONS.md) | PostgreSQL operations guide |
| [PRD v4.0](../PRD.md) | Product Requirements Document |

---

## Appendix A: Table Summary

| Table | Purpose | Key Columns | Rows (Est.) |
|-------|---------|-------------|-------------|
| `market_data` | OHLCV price history | symbol, timestamp, close | 500K+ |
| `daily_performance` | EOD metrics (V2) | entity_id, trading_date, sharpe | 2K+ |
| `performance_snapshots` | Point-in-time state (V1) | strategy_id, timestamp, equity | 10K+ |
| `live_trades` | Trade audit trail | strategy_id, symbol, action | 5K+ |
| `positions` | Current holdings | symbol, quantity, strategy_id | 50 |
| `users` | User accounts | username, role, totp_enabled | 20 |
| `passkeys` | WebAuthn credentials | user_id, credential_id | 30 |
| `system_state` | Key-value state | key, value | 20 |
| `data_metadata` | Sync tracking | symbol, last_bar_timestamp | 50 |

---

*This document follows Arc42 and C4 Model conventions for architecture documentation.*
