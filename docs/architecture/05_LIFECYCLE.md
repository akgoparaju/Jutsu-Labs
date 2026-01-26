# 05 - System Lifecycle

> Request flows, state transitions, operational workflows, and trading day lifecycle

**Last Updated**: 2026-01-25
**Status**: Complete
**Related Documents**: [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | [02_DATA_LAYER](./02_DATA_LAYER.md) | [03_FUNCTIONAL_CORE](./03_FUNCTIONAL_CORE.md) | [04_BOUNDARIES](./04_BOUNDARIES.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Trading Day Lifecycle](#2-trading-day-lifecycle)
3. [Live Trading Execution Flow](#3-live-trading-execution-flow)
4. [Backtest Execution Flow](#4-backtest-execution-flow)
5. [User Authentication Flow](#5-user-authentication-flow)
6. [Data Refresh Workflow](#6-data-refresh-workflow)
7. [Regime State Transitions](#7-regime-state-transitions)
8. [Engine State Machine](#8-engine-state-machine)
9. [Cross-References](#9-cross-references)

---

## 1. Overview

Jutsu Labs operates on a **daily execution cadence** anchored to NYSE market hours. The system's lifecycle is driven by scheduled jobs, user-initiated actions, and automated state transitions. This document captures the key operational flows that govern the platform's behavior from market open to close, from login to trade execution, and from data fetch to performance snapshot.

### Key Timing Reference (Eastern Time)

| Time | Event | Description |
|------|-------|-------------|
| 9:30 AM | Market Open | NYSE regular session begins |
| 1:00 PM | Half-Day Close | Early close on NYSE half-days |
| 1:15 PM | Half-Day EOD Job | EOD finalization for half-days |
| 3:55 PM | Trading Job | Strategy evaluation + order execution |
| 4:00 PM | Market Close | NYSE regular session ends |
| 4:05 PM | Market Close Job | Post-close data snapshot |
| 4:15 PM | EOD Performance Job | Daily performance finalization |
| Hourly | Data Refresh | Refresh dashboard data and indicators |

---

## 2. Trading Day Lifecycle

A complete trading day follows this sequence of automated and event-driven stages:

```
    9:30 AM ET                                                   4:15 PM ET
    ┌──────┐                                                     ┌──────┐
    │Market│                                                     │ EOD  │
    │ Open │                                                     │ Done │
    └──┬───┘                                                     └──────┘
       │
       ▼
┌─────────────┐   Hourly    ┌─────────────┐   3:55 PM   ┌─────────────┐
│  Data Sync  │ ──────────► │  Dashboard   │ ──────────► │  Trading    │
│  (startup)  │   refresh   │  Refresh     │             │  Job        │
└─────────────┘             └─────────────┘             └──────┬──────┘
                                                               │
                                                               ▼
                            ┌─────────────┐   4:05 PM   ┌─────────────┐
                            │  EOD Daily  │ ◄────────── │ Market Close│
                            │ Performance │   4:15 PM   │   Job       │
                            │    Job      │             └─────────────┘
                            └──────┬──────┘
                                   │
                                   ▼
                            ┌─────────────┐
                            │  Snapshot    │
                            │  Finalized  │
                            └─────────────┘
```

### Stage Details

#### Stage 1: Market Open + Data Sync

On application startup, the system:
1. Initializes database connections (`DatabaseFactory`)
2. Starts the scheduler (`SchedulerService.start()`)
3. Performs initial data refresh (`startup_data_refresh()` in app lifespan)
4. Checks scheduler health and recovers missed jobs (`scheduler_recovery_check()`)

#### Stage 2: Hourly Dashboard Refresh

The `_execute_hourly_refresh_job()` runs every hour during market hours:
1. Check if market is open (skip weekends/holidays)
2. Sync latest market data from Yahoo Finance
3. Fetch current prices from Schwab (if available)
4. Update position valuations (mark-to-market)
5. Recalculate indicator values
6. Save performance snapshot to database
7. Broadcast `data_refresh` event via WebSocket

#### Stage 3: Trading Job (3:55 PM ET)

The core trading execution, run by `_execute_trading_job()`:
1. Fetch latest market data for all strategy symbols
2. Run strategy evaluation for all registered strategies
3. Determine target allocations based on regime + signals
4. Calculate rebalance orders (current vs. target positions)
5. Execute orders via `ExecutorRouter` (mode-dependent)
6. Log trades to database with full strategy context
7. Broadcast `trade_executed` events via WebSocket
8. Update strategy state and save to database

#### Stage 4: Market Close Job (4:05 PM ET)

Post-market close data capture:
1. Fetch final closing prices
2. Save end-of-day performance snapshot
3. Update position values with closing prices

#### Stage 5: EOD Daily Performance Job (4:15 PM ET)

The `_execute_eod_finalization_job()` creates authoritative daily records:
1. Query latest performance snapshot for each strategy
2. Calculate daily return vs. previous day's close
3. Compute incremental KPIs (Sharpe, Sortino, Calmar, max drawdown)
4. Record one row per strategy + one per baseline in `daily_performance` table
5. Mark the day as finalized

For **half-days** (NYSE early close at 1:00 PM), the `_execute_eod_finalization_halfday_job()` runs at **1:15 PM ET** using the `pandas_market_calendars` library to detect early close dates.

---

## 3. Live Trading Execution Flow

### 3.1 Multi-Strategy Runner

The `MultiStrategyRunner` (`jutsu_engine/live/multi_strategy_runner.py`) orchestrates execution across all active strategies:

```
┌────────────────────────────────────────────────────┐
│              MultiStrategyRunner                    │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐                │
│  │ LiveStrategy  │  │ LiveStrategy  │  ...           │
│  │ Runner (v3_5b)│  │ Runner (v3_5d)│               │
│  └──────┬───────┘  └──────┬───────┘                │
│         │                  │                         │
│         ▼                  ▼                         │
│  ┌──────────────────────────────────┐               │
│  │        ExecutorRouter             │               │
│  │  Mock │ DryRun │ Paper │ Live    │               │
│  └──────────────────────────────────┘               │
└────────────────────────────────────────────────────┘
```

### 3.2 Single Strategy Execution Pipeline

Each `LiveStrategyRunner` (`jutsu_engine/live/strategy_runner.py`) follows this pipeline:

```
1. _load_config()           → Parse YAML, extract parameters
2. _validate_parameters()   → Check required fields present
3. _convert_decimal_params() → Convert floats to Decimal
4. _initialize_strategy()   → Create strategy instance, warmup
5. calculate_signals()      → Run strategy logic on latest data
6. get_strategy_context()   → Extract regime, indicators, allocations
7. determine_target_allocation() → Map signals to position targets
```

### 3.3 Execution Modes

The `ExecutorRouter` (`jutsu_engine/live/executor_router.py`) selects the executor based on trading mode:

| Mode | Executor | Behavior |
|------|----------|----------|
| `offline_mock` | `MockOrderExecutor` | Simulated fills, no real orders |
| `dry_run` | `DryRunExecutor` | Logged signals only, no execution |
| `paper` | `DryRunExecutor` | Paper trading with database logging |
| `online_live` | `SchwabOrderExecutor` | Real orders via Schwab API |

### 3.4 Order Execution Safety Chain

```
Signal Generated
    │
    ▼
┌──────────────────┐
│ Data Freshness   │ ← Verify data is current (not stale)
│ Check            │
└────────┬─────────┘
         │ Pass
         ▼
┌──────────────────┐
│ Position         │ ← Round to whole shares, validate
│ Rounding         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ SELL Orders      │ ← Execute sells first (reduce margin)
│ (first)          │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Slippage         │ ← Abort if fill deviates > 1%
│ Validation       │
└────────┬─────────┘
         │ Pass
         ▼
┌──────────────────┐
│ BUY Orders       │ ← Execute buys with freed capital
│ (second)         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Fill Logging     │ ← DB + security logger + WebSocket
└──────────────────┘
```

### 3.5 State Management

The `StateManager` (`jutsu_engine/live/state_manager.py`) persists strategy state between executions:

| Operation | Description |
|-----------|-------------|
| `load_state()` | Load previous state from file/DB |
| `save_state()` | Persist current state |
| `validate_state_integrity()` | Verify state consistency |
| `reconcile_with_account()` | Align state with Schwab account positions |
| `_backup_current_state()` | Create pre-execution backup |
| `_cleanup_old_backups()` | Remove stale backups |

The `MultiStateManager` handles state for multiple strategies simultaneously.

### 3.6 Fill Reconciliation

Daily at 5:00 PM ET, `FillReconciler` (`jutsu_engine/live/reconciliation.py`) compares local trades with Schwab:

| Check | Result |
|-------|--------|
| **matched** | Trade exists in both systems |
| **missing_local** | In Schwab but not in local DB |
| **missing_schwab** | In local DB but not in Schwab |
| **price_discrepancies** | Fill price mismatch |
| **quantity_discrepancies** | Fill quantity mismatch |
| **is_reconciled** | Overall pass/fail boolean |

---

## 4. Backtest Execution Flow

Backtesting uses the **EventLoop** (documented in [03_FUNCTIONAL_CORE](./03_FUNCTIONAL_CORE.md)) to simulate trading on historical data:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Load YAML  │ ──► │  Initialize  │ ──► │  Warmup Phase   │
│  Config     │     │  Strategy    │     │  (N bars)       │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │  Bar-by-Bar     │
                                          │  Simulation     │
                                          │                 │
                                          │  For each bar:  │
                                          │  1. Update data │
                                          │  2. Snapshot    │
                                          │  3. Signals     │
                                          │  4. Fill orders │
                                          │  5. Record      │
                                          └────────┬────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │  Performance    │
                                          │  Analysis       │
                                          │  (25+ metrics)  │
                                          └────────┬────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │  Export Results  │
                                          │  CSV + Dashboard │
                                          └─────────────────┘
```

### Key Backtest Characteristics

| Feature | Implementation |
|---------|---------------|
| **Lookahead Prevention** | Snapshot recorded BEFORE `update_market_value()` |
| **Warmup Period** | `max(indicator periods) + 5` bars before trading |
| **Position Sizing** | Cash-constrained, whole-share rounding |
| **Slippage Model** | Configurable percentage (default 0.1%) |
| **Commission Model** | Per-share or per-trade, configurable |
| **Regime Tracking** | 6-cell matrix state recorded each bar |

---

## 5. User Authentication Flow

### 5.1 Standard Login (Password + Optional 2FA)

```
User                    Frontend                   Backend
 │                        │                          │
 │  Enter credentials     │                          │
 │ ─────────────────────► │                          │
 │                        │  POST /api/auth/login    │
 │                        │ ────────────────────────►│
 │                        │                          │ Verify password
 │                        │                          │ Check lockout
 │                        │                          │
 │                        │  {requires_2fa: true}    │
 │                        │ ◄────────────────────────│  (if 2FA enabled)
 │                        │                          │
 │  Enter TOTP code       │                          │
 │ ─────────────────────► │                          │
 │                        │  POST /api/auth/login/2fa│
 │                        │ ────────────────────────►│
 │                        │                          │ Verify TOTP code
 │                        │  {access_token,          │
 │                        │   refresh_token}         │
 │                        │ ◄────────────────────────│
 │                        │                          │
 │  Dashboard loaded      │                          │
 │ ◄───────────────────── │                          │
```

### 5.2 Passkey Login (Passwordless 2FA Bypass)

```
User                    Frontend                   Backend
 │                        │                          │
 │  Enter credentials     │                          │
 │ ─────────────────────► │                          │
 │                        │  POST /api/auth/login    │
 │                        │ ────────────────────────►│
 │                        │                          │ Verify password
 │                        │  {requires_passkey: true,│
 │                        │   passkey_options: {...}} │
 │                        │ ◄────────────────────────│
 │                        │                          │
 │  Touch authenticator   │  navigator.credentials   │
 │ ─────────────────────► │  .get(publicKey)         │
 │                        │                          │
 │                        │  POST /api/passkey/      │
 │                        │  authenticate            │
 │                        │ ────────────────────────►│
 │                        │                          │ Verify sign_count
 │                        │                          │ Validate credential
 │                        │  {access_token,          │
 │                        │   refresh_token}         │
 │                        │ ◄────────────────────────│
 │                        │                          │
 │  Dashboard loaded      │                          │
 │  (2FA bypassed)        │                          │
 │ ◄───────────────────── │                          │
```

### 5.3 Token Refresh Flow

```
Frontend detects token near expiry
    │
    ▼
POST /api/auth/refresh
    │  (with refresh token)
    ▼
Backend validates refresh token
    │
    ├─ Valid   → Issue new access_token + refresh_token
    │
    └─ Invalid → 401 → Redirect to login
```

### 5.4 Invitation Onboarding Flow

```
Admin                  Backend                 New User
 │                       │                       │
 │ POST /api/users/invite│                       │
 │ {email, role}         │                       │
 │ ─────────────────────►│                       │
 │                       │ Generate 64-char token│
 │ ◄─────────────────────│                       │
 │ {token, expires_at}   │                       │
 │                       │                       │
 │ Share link with token  │                       │
 │ ──────────────────────────────────────────────►│
 │                       │                       │
 │                       │ GET /api/invitations/  │
 │                       │ {token}               │
 │                       │ ◄──────────────────────│
 │                       │ {valid, role, expiry}  │
 │                       │ ──────────────────────►│
 │                       │                       │
 │                       │ POST /api/invitations/ │
 │                       │ {token}/accept         │
 │                       │ {username, password}   │
 │                       │ ◄──────────────────────│
 │                       │                       │
 │                       │ Create user with role  │
 │                       │ {user created}         │
 │                       │ ──────────────────────►│
 │                       │                       │ Login normally
```

---

## 6. Data Refresh Workflow

### 6.1 Full Refresh Cycle

The `DashboardDataRefresher.full_refresh()` method orchestrates a complete data update:

```
full_refresh()
    │
    ├── 1. sync_market_data()
    │       │
    │       ├── Yahoo Finance: fetch daily bars
    │       ├── Update market_data table
    │       └── _fallback_sync() on failure
    │
    ├── 2. fetch_current_prices()
    │       │
    │       ├── Schwab API: real-time quotes (market hours)
    │       └── _get_database_prices() fallback
    │
    ├── 3. update_position_values()
    │       │
    │       ├── Mark-to-market all positions
    │       └── Recalculate total portfolio value
    │
    ├── 4. calculate_indicators()
    │       │
    │       ├── _get_historical_data() from DB
    │       ├── Run strategy warmup
    │       └── Compute all indicator values
    │
    └── 5. save_performance_snapshot()
            │
            ├── Calculate performance metrics
            ├── Insert into performance_snapshots
            └── Broadcast via WebSocket
```

### 6.2 Staleness Detection

The system tracks data freshness via `check_if_stale()`:

| Scenario | Stale Threshold | Action |
|----------|----------------|--------|
| Market hours | > 1 hour since last refresh | Auto-refresh triggered |
| Pre-market | > 24 hours since last snapshot | Refresh on startup |
| Weekend | No action | Data remains as Friday close |
| Holiday | No action | Skip based on market calendar |

### 6.3 Refresh Triggers

| Trigger | Source | Frequency |
|---------|--------|-----------|
| Startup | App lifespan | Once on boot |
| Hourly job | APScheduler | Every hour during market hours |
| Manual | `POST /api/control/data-refresh` | Admin-initiated |
| Staleness check | Dashboard load | On-demand |

---

## 7. Regime State Transitions

### 7.1 The 6-Cell Regime Matrix

The trading regime is classified into a 2×3 matrix combining trend state and volatility state (see [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md)):

```
                    Volatility State
                 Low     Normal    High
              ┌────────┬─────────┬────────┐
    Bullish   │ Cell 1 │ Cell 2  │ Cell 3 │
Trend         │ Max    │ Normal  │ Reduced│
State         ├────────┼─────────┼────────┤
    Bearish   │ Cell 4 │ Cell 5  │ Cell 6 │
              │Reduced │ Defensive│ Min    │
              └────────┴─────────┴────────┘
```

### 7.2 State Transition Flow

```
Daily Bar Received
    │
    ▼
┌─────────────────────────┐
│ Kalman Filter           │
│ (trend detection)       │
│                         │
│ Input: price series     │
│ Output: trend_state     │
│  (bullish/bearish)      │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Volatility Z-Score      │
│ (vol classification)    │
│                         │
│ Input: returns series   │
│ Output: vol_state       │
│  (low/normal/high)      │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Cell Classification     │
│                         │
│ trend + vol → cell(1-6) │
│                         │
│ Each cell maps to a     │
│ target allocation       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Hysteresis Check        │
│                         │
│ Prevent rapid switching │
│ between cells           │
│ (configurable threshold)│
└───────────┬─────────────┘
            │
            ├── No change → Hold current allocation
            │
            └── Regime changed → Rebalance to new target
                    │
                    ▼
             ┌──────────────┐
             │ Record in    │
             │ regime_      │
             │ timeseries   │
             └──────────────┘
```

### 7.3 Transition Characteristics

| Parameter | Details |
|-----------|---------|
| **Detection Frequency** | Every daily bar (once per trading day) |
| **Trend Indicator** | Adaptive Kalman Filter with gearing factor |
| **Vol Indicator** | Z-score of realized volatility vs. rolling average |
| **Hysteresis** | Configurable per strategy (prevents whipsawing) |
| **Cell Change** | Triggers rebalance at next execution window |
| **Historical Tracking** | `regime_timeseries` table records all transitions |

---

## 8. Engine State Machine

### 8.1 Engine States

The `EngineState` class (`jutsu_engine/api/dependencies.py`) tracks the trading engine lifecycle:

```
                ┌──────────┐
                │  STOPPED │ ← Initial state
                └────┬─────┘
                     │ start()
                     ▼
                ┌──────────┐
     ┌──────── │ RUNNING  │ ◄──────┐
     │         └────┬─────┘        │
     │              │               │
     │ set_error()  │ record_      │ restart()
     │              │ execution()  │
     ▼              ▼               │
┌──────────┐  ┌──────────┐        │
│  ERROR   │  │ RUNNING  │ ───────┘
│          │  │ (updated) │
└────┬─────┘  └──────────┘
     │
     │ stop() / start()
     ▼
┌──────────┐
│  STOPPED │
└──────────┘
```

### 8.2 State Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_running` | bool | Whether engine is actively processing |
| `mode` | str | `offline_mock`, `dry_run`, `paper`, `online_live` |
| `started_at` | datetime | Engine start timestamp |
| `last_execution` | datetime | Last trading job completion |
| `next_execution` | datetime | Scheduled next trading job |
| `last_error` | str | Most recent error message |
| `execution_count` | int | Total executions since start |
| `uptime_seconds` | float | Time since engine started |

### 8.3 Trading Mode Transitions

```
offline_mock ──► dry_run ──► paper ──► online_live
    │                                      │
    │              Progressive Safety      │
    └──────────────────────────────────────┘
                 (can skip stages)
```

| Mode | Real Orders | Database Logging | Requires `--confirm` |
|------|-------------|-----------------|---------------------|
| `offline_mock` | No | No | No |
| `dry_run` | No | Yes (signals) | No |
| `paper` | No | Yes (simulated) | No |
| `online_live` | Yes (Schwab) | Yes (real fills) | Yes + interactive 'YES' |

---

## 9. Cross-References

| Document | Relevant Sections |
|----------|-------------------|
| [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | System goals, deployment overview |
| [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | Regime types, strategy hierarchy |
| [02_DATA_LAYER](./02_DATA_LAYER.md) | Tables referenced in workflows (daily_performance, regime_timeseries) |
| [03_FUNCTIONAL_CORE](./03_FUNCTIONAL_CORE.md) | EventLoop, indicator calculations, portfolio simulator |
| [04_BOUNDARIES](./04_BOUNDARIES.md) | API endpoints triggered in each flow |
| [06_WORKERS](./06_WORKERS.md) | Scheduler job definitions and timing |
| [07_INTEGRATION_PATTERNS](./07_INTEGRATION_PATTERNS.md) | Error handling, state management patterns |

---

*This document is part of the [Jutsu Labs Architecture Documentation](./00_SYSTEM_OVERVIEW.md) series.*
