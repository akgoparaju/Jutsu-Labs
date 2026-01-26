# 06 - Workers & Background Jobs

> APScheduler-based background processing architecture for the Jutsu Labs trading platform.

**Last Updated**: 2026-01-25
**Related Documents**: [05_LIFECYCLE.md](05_LIFECYCLE.md) | [02_DATA_LAYER.md](02_DATA_LAYER.md) | [04_BOUNDARIES.md](04_BOUNDARIES.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [APScheduler Architecture](#2-apscheduler-architecture)
3. [Scheduled Jobs Registry](#3-scheduled-jobs-registry)
4. [Job Implementations](#4-job-implementations)
5. [Self-Healing Architecture](#5-self-healing-architecture)
6. [Job Persistence](#6-job-persistence)
7. [Error Handling & Recovery](#7-error-handling--recovery)
8. [Monitoring & Health Checks](#8-monitoring--health-checks)
9. [Configuration Priority](#9-configuration-priority)
10. [Architectural Decisions](#10-architectural-decisions)

---

## 1. Overview

The platform uses **APScheduler** (AsyncIOScheduler) to manage all background processing. A singleton `SchedulerService` orchestrates five distinct job types that collectively manage the trading day lifecycle.

### Key Design Principles

- **Single Instance Per Job**: `max_instances=1` prevents overlapping execution
- **Coalesced Execution**: Missed runs collapse into a single execution
- **Self-Healing**: Automatic recovery from startup failures and database outages
- **Persistent Jobs**: SQLAlchemyJobStore survives container restarts
- **Market-Aware**: All jobs check trading day calendars before executing

### Component Map

```
jutsu_engine/api/scheduler.py     # SchedulerService (singleton), SchedulerState
jutsu_engine/jobs/                 # Job-specific implementations
  ├── __init__.py
  └── eod_finalization.py          # EOD daily performance job
jutsu_engine/api/main.py           # Startup integration, recovery task
scripts/daily_multi_strategy_run.py  # Trading execution script
jutsu_engine/live/data_refresh.py  # Data refresh logic
jutsu_engine/utils/notifications.py  # Webhook notifications (Slack/Discord)
```

---

## 2. APScheduler Architecture

### Singleton Pattern

`SchedulerService` uses a singleton via `__new__` to guarantee exactly one scheduler instance across the application:

```python
class SchedulerService:
    _instance = None
    _initialized = False

    def __new__(cls, ...):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

Access via the module-level helper:

```python
def get_scheduler_service() -> SchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service
```

### Scheduler Configuration

```python
AsyncIOScheduler(
    jobstores={'default': SQLAlchemyJobStore(url=database_url)},
    timezone=pytz.timezone('US/Eastern'),
    job_defaults={
        'misfire_grace_time': 300,  # 5-minute grace period
        'coalesce': True,           # Combine missed runs into one
        'max_instances': 1,         # Only one instance at a time
    },
)
```

**Why 300s misfire grace time**: The default 1-second grace time caused jobs to be marked "missed" during normal event loop delays (network I/O, database queries). A 5-minute window tolerates transient delays while still catching genuinely missed executions.

### State Management

`SchedulerState` persists configuration via a JSON file (`state/scheduler_state.json`):

```python
# Default state
{
    'enabled': False,
    'execution_time': '15min_after_open',  # Configurable trading time
    'last_run': None,       # ISO timestamp
    'last_run_status': None, # 'success' | 'failed' | 'skipped'
    'last_error': None,
    'run_count': 0,
}
```

State writes use atomic file operations (write to `.tmp`, then rename) to prevent corruption during concurrent access. A `threading.Lock` guards in-memory state mutations.

**Pickle Compatibility**: `SchedulerState` implements `__getstate__`/`__setstate__` because APScheduler's SQLAlchemyJobStore pickles job objects. `threading.Lock` and `pathlib.Path` objects (Python 3.11+) cannot be pickled, so they are excluded and recreated on deserialization.

---

## 3. Scheduled Jobs Registry

### Job Timeline (Eastern Time)

```
Trading Day Timeline (Mon-Fri)
═══════════════════════════════════════════════════════════════════

09:30  Market Open
       │
09:45  ── daily_trading_job (default) ─────────────── Trading Execution
       │   Configurable: 'open', '15min_after_open',
       │   '15min_before_close', '5min_before_close', 'close'
       │
10:00  ── hourly_refresh_job ──────────────────────── Intraday Prices
       │   Every 1 hour (10 AM - 3:30 PM only)
       │
11:00  ── hourly_refresh_job
       │
12:00  ── hourly_refresh_job
       │
  ...    (continues hourly)
       │
13:15  ── eod_finalization_halfday_job ────────────── Half-Day EOD
       │   Only runs on early-close trading days
       │   (day after Thanksgiving, Christmas Eve, etc.)
       │
15:30  ── (last hourly refresh window)
       │
15:45  ── (no hourly - outside window)
       │
15:55  ── daily_trading_job (if '5min_before_close')
       │
16:00  Market Close
       │
16:05  ── market_close_refresh_job ────────────────── EOD Data Sync
       │   Full data refresh with indicator recalculation
       │
16:15  ── eod_finalization_job ────────────────────── Daily Metrics
       │   Calculates Sharpe, Sortino, Calmar, etc.
       │   Stores in daily_performance table
       │
       ── token_expiration_check_job ──────────────── Every 12 Hours
           Monitors Schwab OAuth token lifecycle
```

### Execution Time Configuration

```python
EXECUTION_TIME_MAP: Dict[str, time] = {
    'open':                  time(9, 30),
    '15min_after_open':      time(9, 45),   # Default
    '15min_before_close':    time(15, 45),
    '5min_before_close':     time(15, 55),
    'close':                 time(16, 0),
}
```

The execution time is resolved through a priority chain (see [Section 9](#9-configuration-priority)).

### Complete Job Registry

| Job ID | Schedule | Trigger Type | Purpose |
|--------|----------|-------------|---------|
| `daily_trading_job` | Configurable (default 9:45 AM) | CronTrigger (Mon-Fri) | Execute trading strategies |
| `market_close_refresh_job` | 4:00 PM ET | CronTrigger (Mon-Fri) | Sync prices, calculate P&L |
| `hourly_refresh_job` | Every 1 hour | IntervalTrigger | Intraday price updates |
| `token_expiration_check_job` | Every 12 hours | IntervalTrigger | Monitor Schwab OAuth token |
| `eod_finalization_job` | 4:15 PM ET | CronTrigger (Mon-Fri) | Calculate daily performance KPIs |
| `eod_finalization_job_halfday` | 1:15 PM ET | CronTrigger (Mon-Fri) | EOD for early-close days |

---

## 4. Job Implementations

### 4.1 Daily Trading Job

**File**: `jutsu_engine/api/scheduler.py` → `_execute_trading_job()`
**Delegate**: `scripts/daily_multi_strategy_run.py`

```
Trigger (9:45 AM ET)
  │
  ├─ Guard: _is_running_job check (prevent overlap)
  ├─ Check: is_trading_day() via NYSE calendar
  │   └─ Skip if holiday/weekend → record_run('skipped')
  │
  ├─ Import: daily_multi_strategy_run.main()
  │   └─ Run in thread executor (avoid blocking event loop)
  │       └─ main(check_freshness=True)
  │           ├─ Sync latest market data from Schwab
  │           ├─ Run each active strategy
  │           ├─ Generate signals
  │           └─ Execute orders (or dry-run)
  │
  ├─ Success: record_run('success')
  └─ Failure: record_run('failed', error_message)
```

**Key Detail**: The trading script runs synchronously, so it is wrapped in `loop.run_in_executor()` to avoid blocking the FastAPI event loop. This is necessary because the script performs CPU-intensive indicator calculations.

### 4.2 Market Close Refresh Job

**File**: `jutsu_engine/api/scheduler.py` → `_execute_data_refresh_job()`
**Delegate**: `jutsu_engine/live/data_refresh.py`

```
Trigger (4:00 PM ET)
  │
  ├─ Guard: _is_running_refresh check
  ├─ Check: is_trading_day()
  │
  ├─ Load active strategies from StrategyRegistry
  ├─ Execute full_refresh():
  │   ├─ sync_data=True  (fetch latest prices)
  │   └─ calculate_ind=True (recalculate indicators)
  │
  ├─ WebSocket broadcast: { refresh_type: 'market_close' }
  └─ Log results / errors
```

**Architectural Note**: This job does NOT write regime data (trend_state, vol_state, strategy_cell). Per the [Regime Architecture Decision](../architecture/01_DOMAIN_MODEL.md), only the trading job's scheduler is authoritative for regime calculations. The refresh job handles P&L and equity updates only.

### 4.3 Hourly Refresh Job

**File**: `jutsu_engine/api/scheduler.py` → `_execute_hourly_refresh_job()`

```
Trigger (every 1 hour)
  │
  ├─ Guard: _is_running_hourly_refresh OR _is_running_refresh
  ├─ Time Window: 10:00 AM - 3:30 PM ET only
  ├─ Day Check: weekday + is_trading_day()
  │
  ├─ Load active strategies from StrategyRegistry
  ├─ Execute full_refresh():
  │   ├─ sync_data=True
  │   └─ calculate_ind=False  (skip indicators for speed)
  │
  ├─ WebSocket broadcast: { refresh_type: 'hourly' }
  └─ Log results
```

**Why skip indicators**: Indicator recalculation (Kalman filter, moving averages) is CPU-intensive. Hourly refreshes focus on price updates for the dashboard. Full indicator recalculation happens at market close.

### 4.4 Token Expiration Check Job

**File**: `jutsu_engine/api/scheduler.py` → `_check_token_expiration_job()`

Monitors the Schwab OAuth refresh token (30-day lifecycle) and sends tiered notifications:

| Threshold | Level | Notification Type |
|-----------|-------|------------------|
| 5 days remaining | INFO | Webhook alert |
| 2 days remaining | WARNING | Webhook alert |
| 1 day remaining | CRITICAL | Webhook alert |
| 12 hours remaining | URGENT | Webhook alert |
| Expired | CRITICAL | Expired alert |

**Deduplication**: Notification state is persisted to avoid duplicate alerts. The system tracks `last_notification_level` and only sends alerts when escalating to a more urgent tier (5d → 2d → 1d → 12h).

### 4.5 EOD Finalization Job

**File**: `jutsu_engine/jobs/eod_finalization.py`
**Scheduler Method**: `_execute_eod_finalization_job()`

This is the most complex background job. It calculates daily performance KPIs and stores them in the `daily_performance` table (see [02_DATA_LAYER.md](02_DATA_LAYER.md)).

```
Trigger (4:15 PM ET)
  │
  ├─ Guard: _is_running_eod_finalization
  ├─ Check: is_trading_day()
  ├─ Check: is_half_day() → skip if half-day (1:15 PM job handles it)
  │
  ├─ Call run_eod_finalization_with_recovery()
  │   │
  │   ├─ RECOVERY PHASE:
  │   │   ├─ Scan last 7 trading days
  │   │   ├─ Find: missing jobs, failed jobs, stuck jobs (>1 hour)
  │   │   └─ Backfill/retry each missed date
  │   │
  │   └─ CURRENT DAY PHASE:
  │       ├─ Create EODJobStatus record (status='running')
  │       ├─ For each active strategy:
  │       │   └─ process_strategy_eod(db, strategy_id, mode, trading_date)
  │       ├─ For each unique baseline (deduplicated):
  │       │   └─ process_baseline_eod(db, symbol, mode, trading_date)
  │       └─ Update EODJobStatus → 'completed' | 'partial' | 'failed'
  │
  ├─ WebSocket broadcast: { refresh_type: 'eod_finalization' }
  └─ Log summary (strategies processed, baselines processed, errors)
```

**Half-Day Support**: An additional `eod_finalization_halfday_job` runs at 1:15 PM ET for early-close days (NYSE half-days). The 4:15 PM job skips execution when it detects a half-day, deferring to the earlier trigger.

**Baseline Deduplication**: If multiple strategies use the same baseline symbol (e.g., QQQ), it is processed only once per day. Baselines are tracked via a `set()` of `(symbol, mode)` tuples.

---

## 5. Self-Healing Architecture

A critical architectural fix (2026-01-21) addressed a fundamental reliability problem: the scheduler had a single point of failure at startup.

### The Problem

```
Container Start
  │
  ├─ FastAPI starts
  ├─ SchedulerService.start() called ONCE
  │   └─ Database unavailable? → PERMANENT FAILURE
  │       └─ Scheduler never recovers
  │       └─ No jobs run for the entire container lifetime
  └─ No health monitoring
```

### The Solution: Three-Layer Defense

```
Layer 1: Retry Logic at Startup
  │
  ├─ start(max_retries=5, initial_delay=2.0)
  ├─ Exponential backoff: 2s → 4s → 8s → 16s → 32s
  ├─ Clean up failed scheduler instances between retries
  └─ Fallback: MemoryJobStore if all DB retries fail
      └─ Jobs work but are lost on restart (degraded mode)

Layer 2: Background Recovery Task (main.py)
  │
  ├─ Waits 30 seconds after startup
  ├─ Calls is_healthy() to check scheduler state
  │   └─ Verifies: scheduler exists, is running, jobs accessible
  └─ Calls ensure_running() if unhealthy
      └─ start(max_retries=3, initial_delay=1.0)

Layer 3: Health Monitoring via API
  │
  ├─ GET /api/scheduler/status returns:
  │   ├─ scheduler_running: bool
  │   └─ scheduler_healthy: bool
  └─ External monitoring can trigger alerts
```

### Health Check Algorithm

```python
def is_healthy() -> bool:
    # 1. Scheduler instance exists?
    if self._scheduler is None:
        return False
    # 2. Scheduler process running?
    if not self._scheduler.running:
        return False
    # 3. Jobs accessible and not corrupted?
    try:
        job = self._scheduler.get_job(self._job_id)
        if job is not None:
            _ = job.next_run_time  # Detect corruption
        return True
    except (AttributeError, Exception):
        return False  # Corrupted or inaccessible
```

---

## 6. Job Persistence

### SQLAlchemyJobStore

Jobs are persisted in the database via APScheduler's `SQLAlchemyJobStore`. This ensures jobs survive container restarts.

```
┌─────────────────────────────────────────────────┐
│  apscheduler_jobs table                         │
├─────────────────────────────────────────────────┤
│  id           VARCHAR    (job identifier)       │
│  next_run_time FLOAT     (Unix timestamp)       │
│  job_state    BLOB       (pickled Job object)   │
└─────────────────────────────────────────────────┘
```

**Pickle Serialization**: Job objects (including `SchedulerState`) are serialized via Python's pickle module. This created several issues:

1. **threading.Lock**: Not picklable → excluded via `__getstate__`
2. **pathlib.Path**: Python 3.11+ internal module changes broke unpickling → converted to `str`
3. **Job Corruption**: Corrupted pickle data causes `AttributeError: 'Job' object has no attribute 'next_run_time'`

**Migration from MemoryJobStore**: The system originally used `MemoryJobStore`, which lost all jobs on container restart. Architecture decision (2026-01-14) migrated to SQLAlchemyJobStore for reliability.

### Fallback Strategy

```
Start Attempt
  ├─ Try SQLAlchemyJobStore (5 retries with exponential backoff)
  │   └─ Success → Persistent mode (jobs survive restarts)
  │
  └─ All retries fail
      └─ Fall back to MemoryJobStore
          └─ Degraded mode (jobs lost on restart)
          └─ Log: CRITICAL warning
```

### SchedulerState Persistence

Separate from APScheduler's job persistence, the scheduler's operational state (enabled, execution time, run history) is stored in a JSON file:

```
state/scheduler_state.json
{
  "enabled": true,
  "execution_time": "15min_after_open",
  "last_run": "2026-01-25T14:45:03+00:00",
  "last_run_status": "success",
  "last_error": null,
  "run_count": 147
}
```

---

## 7. Error Handling & Recovery

### Per-Job Error Isolation

Each job method uses a guard pattern to prevent concurrent execution and ensure cleanup:

```python
async def _execute_trading_job(self):
    if self._is_running_job:
        logger.warning("Job already running, skipping")
        return

    self._is_running_job = True
    try:
        # ... job logic ...
    finally:
        self._is_running_job = False  # Always reset
```

### EOD Recovery Strategy

The EOD finalization job includes automatic recovery for missed or failed runs:

```python
async def run_eod_finalization_with_recovery():
    # Scan last 7 trading days for:
    #   - Missing jobs (no EODJobStatus record)
    #   - Failed jobs (status='failed' or 'partial')
    #   - Stuck jobs (status='running' for >1 hour)
    #
    # Backfill/retry each problematic date before
    # processing the current day.
```

### Job Status Tracking

The `EODJobStatus` table tracks job execution:

| Column | Type | Purpose |
|--------|------|---------|
| `job_date` | DateTime | Primary key - trading date |
| `started_at` | DateTime (UTC) | Job start time |
| `completed_at` | DateTime (UTC) | Job completion time |
| `status` | String | `running`, `completed`, `partial`, `failed` |
| `strategies_total` | Integer | Total strategies to process |
| `strategies_processed` | Integer | Successfully processed count |
| `baselines_total` | Integer | Total baselines to process |
| `baselines_processed` | Integer | Successfully processed count |
| `error_message` | Text | First 5 errors (semicolon-separated) |

### Error Propagation

```
Job Failure
  │
  ├─ Individual strategy failure → Continue processing other strategies
  │   └─ Status: 'partial' (if at least one succeeded)
  │
  ├─ All strategies fail → Status: 'failed'
  │
  └─ System-level failure (DB, import) → Status: 'failed'
      └─ Will be retried by recovery on next EOD run
```

---

## 8. Monitoring & Health Checks

### API Status Endpoint

`GET /api/scheduler/status` returns comprehensive operational state:

```json
{
  "enabled": true,
  "execution_time": "15min_after_open",
  "execution_time_est": "09:45 AM EST",
  "next_run": "2026-01-27T14:45:00+00:00",
  "next_refresh": "2026-01-27T21:00:00+00:00",
  "next_hourly_refresh": "2026-01-27T16:00:00+00:00",
  "next_eod_finalization": "2026-01-27T21:15:00+00:00",
  "last_run": "2026-01-24T14:45:03+00:00",
  "last_run_status": "success",
  "last_error": null,
  "run_count": 147,
  "is_running": false,
  "is_running_refresh": false,
  "is_running_hourly_refresh": false,
  "is_running_eod_finalization": false,
  "scheduler_running": true,
  "scheduler_healthy": true,
  "valid_execution_times": ["open", "15min_after_open", "15min_before_close", "5min_before_close", "close"]
}
```

### EOD Finalization Status

`GET /api/v2/performance/eod/status` returns EOD job health:

```python
def get_eod_finalization_status():
    # Returns: last job date, status, duration, strategies processed
```

### WebSocket Notifications

Jobs broadcast completion events via WebSocket for real-time dashboard updates:

```python
await broadcast_data_refresh({
    'refresh_type': 'market_close' | 'hourly' | 'eod_finalization',
    'strategies': [...],    # For refresh jobs
    'date': '2026-01-25',  # For EOD finalization
})
```

---

## 9. Configuration Priority

The trading execution time is resolved through a priority chain:

```
Priority 1 (Highest): Database Overrides
  │ Table: config_overrides
  │ Query: WHERE parameter_name='execution_time' AND is_active=TRUE
  │
Priority 2: YAML Configuration
  │ File: live_trading_config.yaml
  │ Key: execution_time
  │
Priority 3 (Lowest): State File Fallback
  │ File: state/scheduler_state.json
  │ Key: execution_time
  │ Default: '15min_after_open'
```

**Operational Note**: Database overrides take precedence over all other sources. If an override is accidentally left active (as happened 2026-01-23), it can cause the scheduler to run at unexpected times. Deactivate via:

```sql
UPDATE config_overrides
SET is_active = FALSE, deactivated_at = NOW()
WHERE parameter_name = 'execution_time' AND is_active = TRUE;
```

---

## 10. Architectural Decisions

### ADR-W1: SQLAlchemyJobStore over MemoryJobStore

**Context**: Container restarts lost all scheduled jobs, requiring manual re-enabling.
**Decision**: Use `SQLAlchemyJobStore` backed by the same PostgreSQL database.
**Consequences**: Jobs persist across restarts; introduces pickle serialization complexity.
**Date**: 2026-01-14

### ADR-W2: Self-Healing Scheduler

**Context**: If the database was unavailable at container startup, the scheduler failed permanently with no recovery path.
**Decision**: Implement three-layer defense: retry with exponential backoff → background recovery task → API health monitoring.
**Consequences**: Scheduler recovers from transient failures; MemoryJobStore fallback provides degraded operation.
**Date**: 2026-01-21

### ADR-W3: Separate EOD Finalization Job

**Context**: Performance metrics (Sharpe ratio) were calculated on-the-fly from corrupted daily_return values in the performance_snapshots table.
**Decision**: Create a dedicated EOD finalization job that runs at 4:15 PM ET, calculating authoritative KPIs from equity-based returns into a new `daily_performance` table.
**Consequences**: Accurate Sharpe/Sortino/Calmar ratios; decoupled from snapshot creation; recovery for missed days.
**Date**: 2026-01-23

### ADR-W4: Scheduler as Regime Authority

**Context**: Both the data refresh process and the scheduler calculated regime values (trend_state, vol_state, strategy_cell), leading to conflicting dashboard displays.
**Decision**: Only the scheduler's trading job writes regime data. The data refresh job is restricted to P&L and equity updates.
**Consequences**: Single source of truth for regime; eliminates stale-data conflicts.
**Date**: 2026-01-14

### ADR-W5: 5-Minute Misfire Grace Time

**Context**: Default 1-second misfire grace time caused jobs to be marked "missed" during normal event loop delays.
**Decision**: Set `misfire_grace_time=300` (5 minutes) with `coalesce=True`.
**Consequences**: Tolerates transient delays; coalescence prevents redundant executions.

---

## Cross-References

- **Trading Day Lifecycle**: See [05_LIFECYCLE.md](05_LIFECYCLE.md) for the complete daily timeline
- **Data Models**: See [02_DATA_LAYER.md](02_DATA_LAYER.md) for `daily_performance` and `EODJobStatus` schemas
- **API Endpoints**: See [04_BOUNDARIES.md](04_BOUNDARIES.md) for scheduler API routes
- **Strategy Execution**: See [03_FUNCTIONAL_CORE.md](03_FUNCTIONAL_CORE.md) for the backtesting engine
- **Domain Concepts**: See [01_DOMAIN_MODEL.md](01_DOMAIN_MODEL.md) for regime state machine
