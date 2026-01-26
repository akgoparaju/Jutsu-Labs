# 07 - Integration Patterns

> Cross-cutting architectural patterns, design decisions, and technical conventions for the Jutsu Labs trading platform.

**Last Updated**: 2026-01-25
**Related Documents**: [00_SYSTEM_OVERVIEW.md](00_SYSTEM_OVERVIEW.md) | All architecture documents

---

## Table of Contents

1. [Dependency Injection & Factories](#1-dependency-injection--factories)
2. [Configuration Management](#2-configuration-management)
3. [Logging & Observability](#3-logging--observability)
4. [Error Handling Patterns](#4-error-handling-patterns)
5. [Caching Strategies](#5-caching-strategies)
6. [Testing Architecture](#6-testing-architecture)
7. [Known Technical Debt](#7-known-technical-debt)
8. [Architecture Decision Records](#8-architecture-decision-records)

---

## 1. Dependency Injection & Factories

### Database Factory

The `DatabaseFactory` provides a unified interface for creating database engines, abstracting SQLite (development) from PostgreSQL (production):

```python
# jutsu_engine/data/database_factory.py

class DatabaseFactory:
    @staticmethod
    def create_engine(db_type: Literal['sqlite', 'postgresql'], config: Dict) -> Engine:
        if db_type == 'sqlite':
            return DatabaseFactory._create_sqlite_engine(config)
        elif db_type == 'postgresql':
            return DatabaseFactory._create_postgresql_engine(config)
```

**SQLite Configuration** (development):
- File-based or `:memory:` for testing
- `check_same_thread=False` for multi-threaded access
- `StaticPool` for in-memory databases

**PostgreSQL Configuration** (production):
- `QueuePool` with configurable pool size (default: 10)
- `max_overflow=20` for burst capacity
- `pool_pre_ping=True` to detect stale connections
- `pool_recycle=3600` to refresh connections hourly

### Session Management

FastAPI dependency injection provides database sessions per-request:

```python
# jutsu_engine/api/dependencies.py

engine = create_engine(get_database_url())
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Usage in routes:
@router.get("/api/v2/performance")
def get_performance(db: Session = Depends(get_db)):
    ...
```

### Singleton Services

Several services use the singleton pattern for application-wide state:

| Service | Module | Pattern |
|---------|--------|---------|
| `SchedulerService` | `jutsu_engine/api/scheduler.py` | `__new__` singleton |
| `Config` | `jutsu_engine/utils/config.py` | Module-level `_config` singleton |
| `DataRefresher` | `jutsu_engine/live/data_refresh.py` | `get_data_refresher()` factory |
| `StrategyRegistry` | `jutsu_engine/live/strategy_registry.py` | Instance-per-use (YAML-backed) |

### Strategy Registry

The strategy registry provides loose coupling between the scheduler and strategy implementations:

```python
# jutsu_engine/live/strategy_registry.py
# config/strategies_registry.yaml

class StrategyRegistry:
    def get_active_strategies() -> List[StrategyConfig]
    def get_strategy(strategy_id: str) -> StrategyConfig
```

Strategies are defined in YAML (`config/strategies/v3_5b.yaml`, `config/strategies/v3_5d.yaml`) and loaded at runtime. This allows adding strategies without code changes.

---

## 2. Configuration Management

### Configuration Layers

```
Priority (Highest → Lowest)
═══════════════════════════

1. Environment Variables
   │ Source: OS env, Docker env, .env file
   │ Scope: All runtime settings, secrets
   │ Example: POSTGRES_HOST, SECRET_KEY, AUTH_REQUIRED
   │
2. Docker Secrets
   │ Source: /run/secrets/<name> or *_FILE env vars
   │ Scope: Sensitive values in production
   │ Example: /run/secrets/db_password
   │
3. Database Overrides
   │ Source: config_overrides table
   │ Scope: Runtime-changeable parameters
   │ Example: execution_time for scheduler
   │
4. YAML Configuration Files
   │ Source: config/config.yaml, config/live_trading_config.yaml
   │ Scope: Application structure, defaults
   │ Example: database type, pool sizes, data source settings
   │
5. Code Defaults
   │ Source: Config class __init__, function defaults
   │ Scope: Fallback values
   │ Example: initial_capital=100000, commission_per_share=0.01
```

### Config Singleton

```python
# jutsu_engine/utils/config.py

class Config:
    def __init__(self):
        self._yaml = self._load_yaml()

    # Typed accessors with environment variable override
    @property
    def database_url(self) -> str: ...
    @property
    def schwab_api_key(self) -> Optional[str]: ...
    @property
    def log_level(self) -> str: ...
    @property
    def environment(self) -> str: ...      # 'development' | 'staging' | 'production'
    @property
    def is_production(self) -> bool: ...
    @property
    def use_daily_performance(self) -> bool: ...  # Feature flag
```

### Secrets Management

```python
def get_secret(secret_name: str, env_var: str = None, default: str = None) -> str:
    """
    Resolution order:
    1. Docker secrets: /run/secrets/<secret_name>
    2. File-based: ENV_VAR_FILE -> read file contents
    3. Environment variable: ENV_VAR
    4. Default value
    """
```

This pattern supports both Docker Swarm secrets (production) and plain environment variables (development) without code changes.

### Feature Flags

Feature flags control gradual rollouts:

```python
# Currently active feature flags:
USE_DAILY_PERFORMANCE  # env: USE_DAILY_PERFORMANCE=true
                       # Controls: V2 API uses daily_performance table
                       # Default: false (V1 calculates on-the-fly)

DISABLE_DOCS           # env: DISABLE_DOCS=true
                       # Controls: OpenAPI /docs, /redoc visibility
                       # Default: false (docs visible)

AUTH_REQUIRED          # env: AUTH_REQUIRED=true
                       # Controls: JWT authentication enforcement
                       # Default: false (open access for development)
```

### YAML Configuration Structure

```
config/
├── config.yaml                           # Main app config (DB, data sources)
├── config.yaml.example                   # Template for new environments
├── live_trading_config.yaml              # Trading execution settings
├── strategies_registry.yaml              # Active strategy definitions
├── strategies/
│   ├── v3_5b.yaml                        # Strategy-specific parameters
│   └── v3_5d.yaml
├── backtest/
│   ├── config_Hierarchical_Adaptive_v3_5b.yaml  # Backtest configs
│   └── config_Hierarchical_Adaptive_v3_5d.yaml
├── examples/
│   └── monte_carlo_config.yaml
└── wfo/                                  # Walk-forward optimization configs
```

---

## 3. Logging & Observability

### Standard Logging

All modules use Python's standard `logging` module with a consistent naming convention:

```python
import logging
logger = logging.getLogger(__name__)

# Output format (configured in main.py):
# 2026-01-25 14:45:03,123 | MODULE | LEVEL | Message
```

### Security Event Logging

A dedicated security logger produces structured JSON events for security monitoring:

```python
# jutsu_engine/utils/security_logger.py

class SecurityLogger:
    def log_login_success(username, ip, user_agent): ...
    def log_login_failure(username, ip, reason): ...
    def log_token_created(username, token_type): ...
    def log_access_denied(username, resource, ip): ...
    def log_rate_limited(ip, endpoint): ...
    def log_suspicious_activity(ip, activity_type, details): ...
    def log_2fa_success(username): ...
    def log_passkey_authenticated(username, credential_id): ...
    # ... 20+ event types
```

**Event Types** (SecurityEventType enum):
- Authentication: `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGOUT`
- Tokens: `TOKEN_CREATED`, `TOKEN_REFRESHED`, `TOKEN_INVALID`
- OAuth: `OAUTH_INITIATED`, `OAUTH_COMPLETED`, `OAUTH_FAILED`, `OAUTH_TOKEN_DELETED`
- Access: `ACCESS_DENIED`, `RATE_LIMITED`, `SUSPICIOUS_ACTIVITY`
- 2FA: `2FA_ENABLED`, `2FA_DISABLED`, `2FA_SUCCESS`, `2FA_FAILURE`
- Passkeys: `PASSKEY_REGISTERED`, `PASSKEY_AUTHENTICATED`, `PASSKEY_REVOKED`

**Severity Levels**: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`

### Database URL Masking

```python
# jutsu_engine/utils/config.py
def get_safe_database_url_for_logging() -> str:
    """Masks passwords as **** in database URLs for safe logging."""
    # postgresql://jutsu:****@192.168.7.100:5423/jutsu_labs
```

### WebSocket Real-Time Events

The system broadcasts events via WebSocket for real-time dashboard updates:

```python
# jutsu_engine/api/websocket.py
await broadcast_data_refresh({
    'refresh_type': 'market_close' | 'hourly' | 'eod_finalization',
    'strategies': [...],
})
```

Event types: `trade_executed`, `regime_change`, `data_refresh`, `error`

---

## 4. Error Handling Patterns

### API Error Conventions

The REST API follows a consistent error response pattern:

```python
# Standard error responses
HTTP 400: {"detail": "Invalid parameter: ..."}
HTTP 401: {"detail": "Not authenticated"}
HTTP 403: {"detail": "Insufficient permissions"}
HTTP 404: {"detail": "Resource not found"}
HTTP 429: {"detail": "Rate limit exceeded"}
HTTP 500: {"detail": "Internal server error"}  # Generic (no info disclosure)
```

**Information Disclosure Prevention**: Production error responses never expose stack traces, database queries, or internal paths. The `error_info_disclosure_fix` (2025-12-10) ensures all unexpected exceptions return generic messages.

### Rate Limiting

```python
# jutsu_engine/api/main.py
# Library: slowapi

LOGIN_RATE_LIMIT = "5/minute"  # Configurable via env var

# IP detection chain (for reverse proxies):
# 1. CF-Connecting-IP (Cloudflare)
# 2. X-Real-IP (nginx)
# 3. X-Forwarded-For
# 4. Direct client IP
```

### Job Error Isolation

Background jobs use a fail-safe pattern that prevents one failure from affecting others:

```python
# Each strategy is processed independently
for strategy in active_strategies:
    try:
        success = await process_strategy_eod(db, strategy.id, ...)
    except Exception as e:
        errors.append(f"Strategy {strategy.id}: {str(e)}")
        # Continue processing other strategies

# Final status reflects partial success
status = 'partial' if strategies_processed > 0 and errors else
         'completed' if not errors else
         'failed'
```

### Atomic File Operations

Configuration and state files use atomic writes to prevent corruption:

```python
# Write to temp file, then atomic rename
temp_file = state_file.with_suffix('.tmp')
with open(temp_file, 'w') as f:
    json.dump(state, f)
temp_file.rename(state_file)  # Atomic on POSIX
```

---

## 5. Caching Strategies

### Data Refresh Caching

The data refresh system uses a multi-level caching approach:

```
Level 1: In-Memory (DataRefresher instance)
  │ TTL: Session lifetime
  │ Content: Strategy configs, indicator state
  │
Level 2: Database (performance_snapshots)
  │ TTL: Until next refresh
  │ Content: Calculated P&L, equity curves, positions
  │
Level 3: File System (CSV cache)
  │ TTL: Configurable
  │ Content: Historical market data, backtest results
```

### Strategy Registry Caching

The strategy registry loads from YAML files. Each access reads the file (no in-memory caching) to ensure configuration changes are reflected immediately.

### Frontend Query Caching

React Query handles client-side caching with strategy-aware cache keys:

```typescript
// All queries include strategy_id in the cache key
queryKey: ['performance', strategyId, timeRange]

// Strategy changes trigger automatic refetch
useEffect(() => {
    queryClient.invalidateQueries(['performance', currentStrategy]);
}, [currentStrategy]);
```

---

## 6. Testing Architecture

### Directory Structure

```
tests/
├── conftest.py           # Shared fixtures, database setup
├── fixtures/             # Test data files
├── unit/                 # Fast, isolated tests
│   ├── api/              # API route tests
│   ├── application/      # Application layer tests
│   ├── cli/              # CLI command tests
│   ├── core/             # Event loop, strategy base tests
│   ├── indicators/       # Indicator calculation tests
│   ├── infrastructure/   # Database, config tests
│   ├── jobs/             # Background job tests
│   ├── live/             # Live trading component tests
│   ├── performance/      # Performance analyzer tests
│   ├── portfolio/        # Portfolio simulator tests
│   ├── strategies/       # Strategy implementation tests
│   └── utils/            # Utility function tests
├── integration/          # Multi-component tests
│   ├── api/              # API integration tests
│   ├── test_data_flow.py
│   ├── test_eod_finalization.py
│   ├── test_live_trading_workflow.py
│   └── ...
└── e2e/                  # End-to-end tests
    └── test_performance_dashboard.py
```

### Testing Patterns

**Unit Tests**: Isolated component testing with mocks for external dependencies:
- Database: In-memory SQLite via `DatabaseFactory.create_engine('sqlite', {'database': ':memory:'})`
- External APIs: Mock Schwab, Yahoo Finance responses
- File system: Temporary directories

**Integration Tests**: Multi-component interaction verification:
- Database: Test PostgreSQL instance or in-memory SQLite
- API: FastAPI `TestClient` with real routers
- Data flow: End-to-end backtest → snapshot → API pipeline

**E2E Tests**: Full system validation:
- Performance dashboard data flow
- Auth flow with 2FA

### Test Count

~1,472 unit tests as of January 2026 (verified by CI).

### Test Fixtures

```python
# tests/conftest.py
@pytest.fixture
def db_session():
    """Create in-memory database session for testing."""
    engine = DatabaseFactory.create_engine('sqlite', {'database': ':memory:'})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

---

## 7. Known Technical Debt

### TD-1: Synchronous Trading Script in Async Scheduler

**Location**: `scheduler.py:_execute_trading_job()` → `run_in_executor()`
**Issue**: The multi-strategy trading script runs synchronously and is wrapped in `run_in_executor()` to avoid blocking the FastAPI event loop.
**Impact**: Consumes a thread pool slot during execution; limits concurrency.
**Recommended Fix**: Refactor `daily_multi_strategy_run.py` to be async-native.

### TD-2: Circular Import Workarounds

**Location**: Multiple scheduler job methods use late imports:
```python
# Inside _execute_trading_job():
import sys
from pathlib import Path
scripts_path = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(scripts_path))
from scripts.daily_multi_strategy_run import main
```
**Issue**: Script directory is added to `sys.path` at runtime.
**Impact**: Fragile path resolution; tight coupling to directory structure.
**Recommended Fix**: Move execution scripts into the engine package or use entry points.

### TD-3: Dual State Persistence

**Location**: Scheduler state is split between two systems:
- APScheduler jobs → `SQLAlchemyJobStore` (PostgreSQL)
- Scheduler operational state → `state/scheduler_state.json` (file)

**Issue**: Two persistence mechanisms for related state.
**Impact**: State can diverge if one system fails without the other.
**Recommended Fix**: Consolidate scheduler state into the database.

### TD-4: V1/V2 API Coexistence

**Location**: `jutsu_api/routers/` - Parallel V1 and V2 API routes
**Issue**: V1 API calculates metrics on-the-fly from `performance_snapshots`; V2 uses pre-computed `daily_performance` table.
**Impact**: Maintenance burden of two calculation paths; potential metric divergence.
**Recommended Fix**: Complete V2 migration and deprecate V1 endpoints.

### TD-5: Config Override Database Table

**Location**: `config_overrides` table
**Issue**: Database overrides can silently override YAML configuration with no audit trail.
**Impact**: Caused production incident (2026-01-23) where scheduler ran at wrong time due to stale override.
**Recommended Fix**: Add audit logging for override changes; add expiration dates.

---

## 8. Architecture Decision Records

### ADR-01: SQLite for Development, PostgreSQL for Production

**Date**: 2025-11 (project inception)
**Context**: Need a database that supports rapid local development while scaling to production.
**Decision**: Use SQLite for development/backtesting and PostgreSQL for production/live trading.
**Rationale**:
- SQLite: Zero-config, file-based, ideal for backtesting (single-user, read-heavy)
- PostgreSQL: Connection pooling, concurrent access, ACID compliance for trading
**Consequences**: `DatabaseFactory` abstracts differences; some SQL dialect differences require attention (e.g., `JSONB` vs `TEXT` for JSON columns).
**Status**: Active

### ADR-02: Multi-Strategy Engine

**Date**: 2026-01-20
**Context**: Need to compare and A/B test multiple trading strategies simultaneously.
**Decision**: Implement a strategy registry pattern with per-strategy data isolation (`strategy_id` column in performance tables).
**Rationale**:
- Enables parallel strategy execution
- Supports gradual migration between strategy versions
- Allows independent performance tracking
**Consequences**: All queries must filter by `strategy_id`; registry YAML defines available strategies.
**Status**: Active

### ADR-03: V1 → V2 API Migration

**Date**: 2026-01-23
**Context**: V1 API calculated Sharpe ratio on-the-fly from `daily_return` column in `performance_snapshots`, which contained corrupt data (returns between consecutive same-day snapshots rather than day-over-day).
**Decision**: Create V2 API backed by `daily_performance` table with pre-computed, equity-based KPIs.
**Rationale**:
- Single authoritative source for performance metrics
- Pre-computation eliminates on-the-fly calculation bugs
- EOD finalization job ensures data quality
**Consequences**: Parallel V1/V2 APIs during migration; frontend migrated to V2 endpoints.
**Status**: Active (V1 deprecated, V2 primary)

### ADR-04: Scheduler as Regime Source of Truth

**Date**: 2026-01-14
**Context**: Both the data refresh process and the scheduler calculated regime values (trend_state, vol_state, strategy_cell), producing conflicting results displayed on the dashboard.
**Decision**: Only the scheduler's trading job writes regime data. Data refresh is restricted to P&L calculations.
**Rationale**:
- Scheduler uses fresh market data (synced before calculation)
- Scheduler's calculation determines actual trade execution
- Eliminates conflicting values from stale cached data
**Consequences**: Dashboard regime display depends on scheduler running; stale regime data until next scheduler run.
**Status**: Active

### ADR-05: EOD Daily Performance Table

**Date**: 2026-01-23
**Context**: Sharpe ratio displayed as -4.06 instead of ~0.82. Root cause: `daily_return` in `performance_snapshots` was calculated from previous same-day snapshot (corrupted by 5-13 snapshots/day from different sources).
**Decision**: Create `daily_performance` table with one authoritative row per strategy per trading day, populated by a 4:15 PM ET job using equity-based returns.
**Rationale**:
- One row per day eliminates multi-snapshot corruption
- Equity-based returns (not stored `daily_return`) are always accurate
- Pre-computed KPIs avoid on-the-fly calculation errors
**Consequences**: Requires backfill job for historical data; feature flag for gradual rollout.
**Status**: Active

### ADR-06: Self-Healing Scheduler

**Date**: 2026-01-21
**Context**: Scheduler had a single point of failure at startup. If the database was unavailable when the container started, the scheduler permanently failed with no recovery path.
**Decision**: Implement three-layer defense: retry with exponential backoff → background recovery task → API health endpoint.
**Rationale**:
- Containers may start before databases in orchestration environments
- Critical trading operations cannot depend on startup order
- Degraded mode (MemoryJobStore fallback) is better than no operation
**Consequences**: Added complexity to scheduler startup; health monitoring via API.
**Status**: Active

### ADR-07: Passkey Authentication (WebAuthn)

**Date**: 2025-12-15
**Context**: Needed passwordless authentication option alongside existing JWT + 2FA (TOTP) flow.
**Decision**: Implement WebAuthn/FIDO2 passkey authentication as an additional auth method.
**Rationale**:
- Phishing-resistant authentication
- Superior UX for trusted devices
- Complements existing 2FA without replacing it
**Consequences**: Users can register multiple passkeys; passkey auth bypasses 2FA challenge; requires secure context (HTTPS).
**Status**: Active

### ADR-08: Role-Based Access Control

**Date**: 2026-01-13
**Context**: Platform grew from single-user to multi-user with different permission needs.
**Decision**: Two roles: `admin` (full access) and `viewer` (read-only + self-management).
**Rationale**:
- Simple two-role model covers current use cases
- Admin has wildcard permission
- Viewer has 7 specific permissions (view performance, trades, regime, etc.)
- Invitation-based onboarding with 48-hour token expiry
**Consequences**: All API endpoints require permission checks; viewer cannot modify trading configuration.
**Status**: Active

### ADR-09: Database Configuration Priority Chain

**Date**: 2026-01-23
**Context**: Multiple configuration sources (database, YAML, state file) existed without clear precedence.
**Decision**: Establish explicit priority: Database overrides > YAML config > State file defaults.
**Rationale**:
- Database overrides enable runtime changes without restart
- YAML provides base configuration
- State file preserves last-known-good values
**Consequences**: Stale database overrides can silently affect behavior (incident 2026-01-23). Requires operational discipline to deactivate overrides.
**Status**: Active (with TD-5 noted for improvement)

---

## Cross-References

- **System Overview**: See [00_SYSTEM_OVERVIEW.md](00_SYSTEM_OVERVIEW.md) for technology stack
- **Domain Model**: See [01_DOMAIN_MODEL.md](01_DOMAIN_MODEL.md) for business concepts
- **Data Layer**: See [02_DATA_LAYER.md](02_DATA_LAYER.md) for database schema and models
- **Functional Core**: See [03_FUNCTIONAL_CORE.md](03_FUNCTIONAL_CORE.md) for algorithms and indicators
- **Boundaries**: See [04_BOUNDARIES.md](04_BOUNDARIES.md) for API and security details
- **Lifecycle**: See [05_LIFECYCLE.md](05_LIFECYCLE.md) for request flows and state transitions
- **Workers**: See [06_WORKERS.md](06_WORKERS.md) for background job architecture
