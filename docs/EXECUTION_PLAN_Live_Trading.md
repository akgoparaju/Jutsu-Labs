# Execution Plan: Jutsu Labs Live Trading System

**Version:** 1.0
**Based On:** PRD-Auto-Trader-Live-v2.md (v2.0.1)
**Created:** December 3, 2025
**Status:** Ready for Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [Dependency Mapping](#3-dependency-mapping)
4. [Phase 0: Foundation Enhancement](#4-phase-0-foundation-enhancement)
5. [Phase 1: Offline Mock Trading](#5-phase-1-offline-mock-trading)
6. [Phase 2: Online Live Trading](#6-phase-2-online-live-trading)
7. [Phase 3: Dashboard MVP](#7-phase-3-dashboard-mvp)
8. [Phase 4: Dashboard Advanced](#8-phase-4-dashboard-advanced)
9. [Phase 5: Production Hardening](#9-phase-5-production-hardening)
10. [Quality Gates](#10-quality-gates)
11. [Agentic Execution Hierarchy](#11-agentic-execution-hierarchy)
12. [Risk Assessment](#12-risk-assessment)

---

## 1. Executive Summary

### 1.1 Objective

Transform the existing Jutsu Labs backtesting engine into a production-grade live trading system for the **Hierarchical Adaptive v3.5b** strategy with dual-mode operation (offline mock + online live), web dashboard, and local trade tracking.

### 1.2 Scope

| Metric | Value |
|--------|-------|
| Total Phases | 6 (Phase 0-5) |
| Estimated Duration | 15+ weeks |
| New Files to Create | ~15 files |
| Existing Files to Refactor | 5 files |
| Database Tables to Add | 6 tables |
| API Endpoints | 10 REST + 1 WebSocket |

### 1.3 Critical Path

```
Phase 0 (BLOCKING) → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
    ↓                    ↓         ↓
strategy_runner fix   CLI live  Schwab executor
config migration      command   refactor
```

---

## 2. Current State Analysis

### 2.1 Existing Live Module Infrastructure

**Location:** `jutsu_engine/live/`

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `__init__.py` | - | Package init | Exists |
| `data_fetcher.py` | ~200 | Fetch historical bars + quotes | Exists, functional |
| `strategy_runner.py` | 282 | Execute strategy on live data | **BROKEN** (wrong params) |
| `state_manager.py` | ~150 | State file management | Exists, functional |
| `position_rounder.py` | ~100 | Convert weights to shares | Exists, functional |
| `dry_run_executor.py` | ~150 | Simulate order execution | Exists, rename to MockOrderExecutor |
| `order_executor.py` | 462 | Schwab order execution + CSV logging | Exists, refactor to SchwabOrderExecutor |
| `slippage_validator.py` | ~80 | Validate slippage thresholds | Exists, functional |
| `alert_manager.py` | ~100 | Alert notifications | Exists, incomplete |
| `health_monitor.py` | ~80 | Health checks | Exists, incomplete |
| `market_calendar.py` | ~50 | Trading day validation | Exists, functional |
| `exceptions.py` | ~30 | Custom exceptions | Exists, functional |

**Total:** 12 existing files in `jutsu_engine/live/`

### 2.2 Existing Database Models

**Location:** `jutsu_engine/data/models.py`

| Model | Purpose | Status |
|-------|---------|--------|
| `MarketData` | OHLCV price data | Exists |
| `DataMetadata` | Sync tracking | Exists |
| `DataAuditLog` | Operation audit | Exists |
| `LiveTrade` | Live trade records | **MISSING** |
| `positions` | Position tracking | **MISSING** |
| `performance_snapshots` | Performance history | **MISSING** |
| `config_overrides` | Parameter overrides | **MISSING** |
| `config_history` | Config change log | **MISSING** |
| `system_state` | System state KV store | **MISSING** |

### 2.3 Strategy Execution Times

**Location:** `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py:54-59`

```python
EXECUTION_TIMES = {
    "open": time(9, 30),               # Exists
    "15min_after_open": time(9, 45),   # Exists
    "15min_before_close": time(15, 45), # Exists
    "close": time(16, 0),               # Exists
    # "5min_before_close": time(15, 55)  # MISSING - Required by PRD
}
```

### 2.4 CLI Commands

**Location:** `jutsu_engine/cli/main.py`

| Command | Purpose | Status |
|---------|---------|--------|
| `jutsu init` | Initialize database | Exists |
| `jutsu sync` | Sync market data | Exists |
| `jutsu status` | Check data status | Exists |
| `jutsu validate` | Validate data | Exists |
| `jutsu backtest` | Run backtest | Exists |
| `jutsu grid-search` | Parameter optimization | Exists |
| `jutsu wfo` | Walk-forward optimization | Exists |
| `jutsu live` | Live trading | **MISSING** |
| `jutsu dashboard` | Start dashboard | **MISSING** |

### 2.5 Configuration Files

| File | Purpose | Status |
|------|---------|--------|
| `config/live_trading_config.yaml` | Live trading config | Exists, **BROKEN** (nested structure) |
| Grid search output configs | Flat parameter structure | Reference for correct format |

---

## 3. Dependency Mapping

### 3.1 Component Dependencies

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DEPENDENCY GRAPH                              │
└─────────────────────────────────────────────────────────────────────┘

Level 0 (Foundation - No Dependencies):
├── Database Models (LiveTrade, positions, etc.)
├── Config Migration (YAML flat structure)
├── Mode Enum Definition
└── Execution Time Addition (5min_before_close)

Level 1 (Depends on Level 0):
├── strategy_runner.py fix (depends on: config format, models)
├── executor_router.py (depends on: mode enum)
└── MockOrderExecutor (depends on: models, mode enum)

Level 2 (Depends on Level 1):
├── CLI `jutsu live --mode offline` (depends on: strategy_runner, mock_executor)
├── SchwabOrderExecutor refactor (depends on: models, executor_router)
└── daily_dry_run.py refactor (depends on: strategy_runner, mock_executor)

Level 3 (Depends on Level 2):
├── CLI `jutsu live --mode online` (depends on: schwab_executor)
├── FastAPI backend (depends on: all models, executors)
└── Performance snapshots (depends on: live trades table)

Level 4 (Depends on Level 3):
├── React Dashboard (depends on: FastAPI backend)
├── WebSocket updates (depends on: FastAPI backend)
└── Parameter editor (depends on: config_overrides table)

Level 5 (Depends on Level 4):
├── Health monitoring (depends on: full system)
├── Alert system (depends on: health monitoring)
└── Crash recovery (depends on: state management)
```

### 3.2 File Dependency Matrix

| File | Depends On | Blocks |
|------|-----------|--------|
| `models.py` (new tables) | None | All executors, API |
| `live_trading_config.yaml` | None | strategy_runner.py |
| `strategy_runner.py` | config.yaml, models | CLI, daily_dry_run |
| `executor_router.py` | mode enum | CLI |
| `mock_executor.py` | models | CLI offline |
| `schwab_executor.py` | models, order_executor | CLI online |
| `cli/main.py` (live cmd) | all executors | Dashboard |
| `api/main.py` | all models, executors | Dashboard |
| `dashboard/` | api/main.py | None |

---

## 4. Phase 0: Foundation Enhancement

**Duration:** Week 1-2
**Priority:** CRITICAL (Blocking all other phases)

### 4.0.1 Task: Add Missing Database Models

**File:** `jutsu_engine/data/models.py`

**Agent:** DATABASE_HANDLER_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 4.0.1.1 | Add `LiveTrade` model (see PRD Section 3.4) | ~40 |
| 4.0.1.2 | Add `Position` model | ~20 |
| 4.0.1.3 | Add `PerformanceSnapshot` model | ~25 |
| 4.0.1.4 | Add `ConfigOverride` model | ~20 |
| 4.0.1.5 | Add `ConfigHistory` model | ~15 |
| 4.0.1.6 | Add `SystemState` model | ~15 |
| 4.0.1.7 | Create database migration script | ~50 |

**Acceptance Criteria:**
- [ ] All 6 models defined with correct column types
- [ ] Decimal precision (18,6) for financial fields
- [ ] Proper indexes on query-heavy columns
- [ ] Migration script creates tables without data loss
- [ ] Unit tests for model creation

**Dependencies:** None
**Blocks:** All executor implementations

---

### 4.0.2 Task: Fix LiveStrategyRunner Parameter Injection

**File:** `jutsu_engine/live/strategy_runner.py`

**Agent:** STRATEGY_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 4.0.2.1 | Refactor `_initialize_strategy()` to use `**params` | ~15 |
| 4.0.2.2 | Remove nested config parsing (lines 82-126) | -40 |
| 4.0.2.3 | Add parameter validation before injection | ~20 |
| 4.0.2.4 | Update tests for new parameter flow | ~50 |

**Current (BROKEN):**
```python
# Lines 92-116 - WRONG
strategy = self.strategy_class(
    signal_symbol=universe['signal_symbol'],
    leveraged_long_symbol=universe['bull_symbol'],  # Wrong key
    # ... 15+ params MISSING
)
```

**Target (CORRECT):**
```python
def _initialize_strategy(self) -> Strategy:
    params = self.config['strategy']['parameters'].copy()
    params.pop('name', None)
    params.pop('trade_logger', None)
    strategy = self.strategy_class(**params)
    strategy.init()
    return strategy
```

**Acceptance Criteria:**
- [ ] All 32 parameters injected from config
- [ ] Parameter names match strategy `__init__` exactly
- [ ] Validation errors for missing required params
- [ ] Existing tests updated and passing

**Dependencies:** 4.0.3 (config migration)
**Blocks:** Phase 1 (offline trading)

---

### 4.0.3 Task: Migrate Config to Flat Structure

**File:** `config/live_trading_config.yaml`

**Agent:** INFRASTRUCTURE_ORCHESTRATOR

| Task | Description | LOC Est. |
|------|-------------|----------|
| 4.0.3.1 | Backup current config | ~5 |
| 4.0.3.2 | Convert nested structure to flat | ~80 |
| 4.0.3.3 | Add all 32 parameters with Golden Config values | ~50 |
| 4.0.3.4 | Validate against grid search output format | - |
| 4.0.3.5 | Update config loading in all modules | ~30 |

**Canonical Format (from PRD Section 4.1):**
```yaml
strategy:
  name: Hierarchical_Adaptive_v3_5b
  parameters:
    # All 32 parameters FLAT
    measurement_noise: 3000.0
    process_noise_1: 0.01
    # ... (complete list in PRD)
```

**Acceptance Criteria:**
- [ ] Config matches grid search output format exactly
- [ ] All 32 parameters present with correct values
- [ ] `strategy_runner.py` loads config successfully
- [ ] Backup of old config preserved

**Dependencies:** None
**Blocks:** 4.0.2 (strategy_runner fix)

---

### 4.0.4 Task: Add 5min_before_close Execution Time

**File:** `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py`

**Agent:** STRATEGY_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 4.0.4.1 | Add `5min_before_close: time(15, 55)` to EXECUTION_TIMES | ~2 |
| 4.0.4.2 | Verify scheduler can use new time | ~10 |
| 4.0.4.3 | Update documentation | ~5 |

**Acceptance Criteria:**
- [ ] EXECUTION_TIMES has 5 options (not 4)
- [ ] Strategy accepts `execution_time="5min_before_close"`
- [ ] Scheduler triggers at 15:55 ET

**Dependencies:** None
**Blocks:** CLI execution time option

---

### 4.0.5 Task: Create Mode Enum and Validation

**File:** `jutsu_engine/live/mode.py` (NEW)

**Agent:** CORE_ORCHESTRATOR

| Task | Description | LOC Est. |
|------|-------------|----------|
| 4.0.5.1 | Create TradingMode enum (OFFLINE_MOCK, ONLINE_LIVE) | ~15 |
| 4.0.5.2 | Create mode validation function | ~20 |
| 4.0.5.3 | Add mode to all relevant models | ~10 |
| 4.0.5.4 | Write unit tests | ~30 |

**Acceptance Criteria:**
- [ ] `TradingMode.OFFLINE_MOCK` and `TradingMode.ONLINE_LIVE` defined
- [ ] String serialization/deserialization works
- [ ] Validation rejects invalid mode strings

**Dependencies:** None
**Blocks:** Executor router

---

### 4.0.6 Task: Create Executor Router

**File:** `jutsu_engine/live/executor_router.py` (NEW)

**Agent:** INFRASTRUCTURE_ORCHESTRATOR

| Task | Description | LOC Est. |
|------|-------------|----------|
| 4.0.6.1 | Define `ExecutorInterface` ABC | ~30 |
| 4.0.6.2 | Create `ExecutorRouter` class | ~50 |
| 4.0.6.3 | Implement mode-based routing | ~20 |
| 4.0.6.4 | Write unit tests | ~40 |

**Interface:**
```python
class ExecutorInterface(ABC):
    @abstractmethod
    def execute_orders(self, orders: List[Order]) -> List[Fill]:
        pass

class ExecutorRouter:
    def get_executor(self, mode: TradingMode) -> ExecutorInterface:
        if mode == TradingMode.OFFLINE_MOCK:
            return MockOrderExecutor()
        return SchwabOrderExecutor()
```

**Acceptance Criteria:**
- [ ] Routes to MockOrderExecutor for offline mode
- [ ] Routes to SchwabOrderExecutor for online mode
- [ ] Common interface for both executors

**Dependencies:** 4.0.5 (mode enum)
**Blocks:** Phase 1, Phase 2

---

### Phase 0 Summary

| Task ID | Description | Priority | Effort | Dependencies |
|---------|-------------|----------|--------|--------------|
| 4.0.1 | Database models | P0 | 2 days | None |
| 4.0.2 | strategy_runner fix | P0 | 1 day | 4.0.3 |
| 4.0.3 | Config migration | P0 | 0.5 days | None |
| 4.0.4 | 5min_before_close | P0 | 0.5 days | None |
| 4.0.5 | Mode enum | P0 | 0.5 days | None |
| 4.0.6 | Executor router | P0 | 1 day | 4.0.5 |

**Total Phase 0 Effort:** ~5.5 days (Week 1-2)

---

## 5. Phase 1: Offline Mock Trading

**Duration:** Week 3-4
**Priority:** HIGH

### 5.1.1 Task: Create MockOrderExecutor

**File:** `jutsu_engine/live/mock_executor.py` (NEW)

**Agent:** INFRASTRUCTURE_ORCHESTRATOR

| Task | Description | LOC Est. |
|------|-------------|----------|
| 5.1.1.1 | Rename/refactor `dry_run_executor.py` | ~150 |
| 5.1.1.2 | Implement `ExecutorInterface` | ~30 |
| 5.1.1.3 | Simulate fills at mid-price | ~40 |
| 5.1.1.4 | Write to LiveTrade table (mode=offline_mock) | ~30 |
| 5.1.1.5 | Unit tests with mocked market data | ~80 |

**Acceptance Criteria:**
- [ ] Implements `ExecutorInterface`
- [ ] Simulates fills at current market price
- [ ] Records all trades to database with `mode='offline_mock'`
- [ ] No Schwab API calls made

**Dependencies:** 4.0.1 (models), 4.0.6 (executor router)
**Blocks:** CLI offline command

---

### 5.1.2 Task: Add CLI Live Command

**File:** `jutsu_engine/cli/main.py`

**Agent:** CLI_AGENT (via APPLICATION_ORCHESTRATOR)

| Task | Description | LOC Est. |
|------|-------------|----------|
| 5.1.2.1 | Add `jutsu live` command group | ~30 |
| 5.1.2.2 | Add `--mode` option (offline/online) | ~20 |
| 5.1.2.3 | Add `--execution-time` option | ~20 |
| 5.1.2.4 | Add `--confirm` flag for online mode | ~15 |
| 5.1.2.5 | Integrate with executor router | ~40 |
| 5.1.2.6 | Add `jutsu live status` subcommand | ~30 |
| 5.1.2.7 | Add `jutsu live trades` subcommand | ~40 |
| 5.1.2.8 | Write integration tests | ~80 |

**CLI Structure:**
```bash
jutsu live                           # Start live trading
jutsu live --mode offline            # Mock trading
jutsu live --mode online --confirm   # Real trading
jutsu live status                    # Check status
jutsu live trades --limit 20         # View trade history
jutsu live export --output file.csv  # Export trades
```

**Acceptance Criteria:**
- [ ] `jutsu live --mode offline` runs successfully
- [ ] `jutsu live status` shows current state
- [ ] `jutsu live trades` shows trade history from database
- [ ] Online mode requires `--confirm` flag

**Dependencies:** 5.1.1 (MockOrderExecutor)
**Blocks:** Phase 2

---

### 5.1.3 Task: Implement Strategy Context Logging

**File:** `jutsu_engine/live/strategy_runner.py`

**Agent:** STRATEGY_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 5.1.3.1 | Capture strategy cell, trend_state, vol_state | ~30 |
| 5.1.3.2 | Capture t_norm, z_score indicator values | ~20 |
| 5.1.3.3 | Pass context to executor for trade recording | ~15 |
| 5.1.3.4 | Unit tests for context capture | ~40 |

**Acceptance Criteria:**
- [ ] Every trade record includes strategy_cell (1-6)
- [ ] trend_state captured (BullStrong, Sideways, BearStrong)
- [ ] vol_state captured (Low, High)
- [ ] t_norm and z_score values recorded

**Dependencies:** 4.0.2 (strategy_runner fix)
**Blocks:** Dashboard indicator display

---

### 5.1.4 Task: Implement Daily Performance Snapshots

**File:** `jutsu_engine/live/performance_tracker.py` (NEW)

**Agent:** PERFORMANCE_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 5.1.4.1 | Create PerformanceTracker class | ~80 |
| 5.1.4.2 | Calculate daily return | ~30 |
| 5.1.4.3 | Calculate cumulative return | ~20 |
| 5.1.4.4 | Calculate drawdown | ~30 |
| 5.1.4.5 | Write to performance_snapshots table | ~20 |
| 5.1.4.6 | Schedule daily snapshot at EOD | ~20 |
| 5.1.4.7 | Unit tests | ~60 |

**Acceptance Criteria:**
- [ ] Daily snapshot recorded at 16:05 ET
- [ ] Metrics: total_equity, daily_return, cumulative_return, drawdown
- [ ] Strategy cell included in snapshot
- [ ] Separate tracking for offline vs online modes

**Dependencies:** 4.0.1 (models)
**Blocks:** Dashboard performance display

---

### 5.1.5 Task: Refactor daily_dry_run.py

**File:** `scripts/daily_dry_run.py`

**Agent:** APPLICATION_ORCHESTRATOR

| Task | Description | LOC Est. |
|------|-------------|----------|
| 5.1.5.1 | Replace direct execution with unified executor | ~50 |
| 5.1.5.2 | Use refactored strategy_runner | ~30 |
| 5.1.5.3 | Update for database trade logging | ~20 |
| 5.1.5.4 | Integration tests | ~40 |

**Acceptance Criteria:**
- [ ] Uses ExecutorRouter for order execution
- [ ] Trades written to database (not CSV)
- [ ] Compatible with new flat config structure

**Dependencies:** 5.1.1, 4.0.2, 4.0.3
**Blocks:** None (parallel with CLI)

---

### Phase 1 Summary

| Task ID | Description | Priority | Effort | Dependencies |
|---------|-------------|----------|--------|--------------|
| 5.1.1 | MockOrderExecutor | P0 | 2 days | Phase 0 |
| 5.1.2 | CLI live command | P0 | 2 days | 5.1.1 |
| 5.1.3 | Strategy context logging | P1 | 1 day | 4.0.2 |
| 5.1.4 | Performance snapshots | P1 | 1.5 days | 4.0.1 |
| 5.1.5 | daily_dry_run refactor | P2 | 1 day | 5.1.1 |

**Total Phase 1 Effort:** ~7.5 days (Week 3-4)

---

## 6. Phase 2: Online Live Trading

**Duration:** Week 5-6
**Priority:** HIGH

### 6.2.1 Task: Refactor OrderExecutor to SchwabOrderExecutor

**File:** `jutsu_engine/live/schwab_executor.py` (refactored from `order_executor.py`)

**Agent:** SCHWAB_FETCHER_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 6.2.1.1 | Implement `ExecutorInterface` | ~30 |
| 6.2.1.2 | Migrate from CSV to database logging | ~50 |
| 6.2.1.3 | Add mode='online_live' to all trades | ~10 |
| 6.2.1.4 | Capture Schwab order ID | ~15 |
| 6.2.1.5 | Calculate and store slippage_pct | ~20 |
| 6.2.1.6 | Integration tests with Schwab API mock | ~100 |

**Existing Functionality (to preserve):**
- Schwab API order placement (`schwab.order_spec.market_order()`)
- Retry logic with exponential backoff
- Slippage validation
- Order status tracking

**New Functionality:**
- SQLite trade logging (replacing CSV)
- Strategy context capture
- Mode tracking
- Slippage calculation and storage

**Acceptance Criteria:**
- [ ] Implements `ExecutorInterface`
- [ ] Real orders placed via Schwab API
- [ ] Trades written to database with `mode='online_live'`
- [ ] Slippage calculated: `(fill_price - target_price) / target_price`
- [ ] Schwab order ID stored for reconciliation

**Dependencies:** 4.0.1 (models), 4.0.6 (executor router)
**Blocks:** CLI online command

---

### 6.2.2 Task: Implement Slippage Abort Mechanism

**File:** `jutsu_engine/live/schwab_executor.py`

**Agent:** SCHWAB_FETCHER_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 6.2.2.1 | Add slippage threshold config (default 1%) | ~10 |
| 6.2.2.2 | Pre-fill slippage estimation | ~30 |
| 6.2.2.3 | Abort order if slippage > threshold | ~20 |
| 6.2.2.4 | Log abort reason | ~15 |
| 6.2.2.5 | Unit tests for abort logic | ~50 |

**Logic:**
```python
if abs(fill_price - target_price) / target_price > SLIPPAGE_THRESHOLD:
    self.abort_order(order_id)
    log.warning(f"Order aborted: slippage {slippage_pct}% > {threshold}%")
```

**Acceptance Criteria:**
- [ ] Orders aborted if slippage > 1%
- [ ] Abort logged with reason
- [ ] Partial fills handled correctly

**Dependencies:** 6.2.1
**Blocks:** None

---

### 6.2.3 Task: Implement Fill Reconciliation

**File:** `jutsu_engine/live/reconciliation.py` (NEW)

**Agent:** INFRASTRUCTURE_ORCHESTRATOR

| Task | Description | LOC Est. |
|------|-------------|----------|
| 6.2.3.1 | Fetch Schwab order history | ~40 |
| 6.2.3.2 | Compare local trades with Schwab records | ~50 |
| 6.2.3.3 | Flag discrepancies | ~30 |
| 6.2.3.4 | Generate reconciliation report | ~40 |
| 6.2.3.5 | Daily reconciliation schedule | ~20 |
| 6.2.3.6 | Unit tests | ~60 |

**Acceptance Criteria:**
- [ ] Daily reconciliation at 17:00 ET
- [ ] Discrepancies logged and alerted
- [ ] Report includes: matched, missing_local, missing_schwab

**Dependencies:** 6.2.1
**Blocks:** Dashboard reconciliation view

---

### 6.2.4 Task: Add Online Mode Confirmation

**File:** `jutsu_engine/cli/main.py`

**Agent:** CLI_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 6.2.4.1 | Require `--confirm` flag for online mode | ~15 |
| 6.2.4.2 | Interactive confirmation prompt | ~25 |
| 6.2.4.3 | Record first-trade timestamp | ~10 |
| 6.2.4.4 | Tests for confirmation flow | ~30 |

**Acceptance Criteria:**
- [ ] `jutsu live --mode online` without `--confirm` shows warning
- [ ] `jutsu live --mode online --confirm` proceeds with trading
- [ ] First trade requires interactive "I understand" confirmation

**Dependencies:** 5.1.2 (CLI live command)
**Blocks:** None

---

### Phase 2 Summary

| Task ID | Description | Priority | Effort | Dependencies |
|---------|-------------|----------|--------|--------------|
| 6.2.1 | SchwabOrderExecutor | P0 | 3 days | Phase 0 |
| 6.2.2 | Slippage abort | P0 | 1 day | 6.2.1 |
| 6.2.3 | Fill reconciliation | P1 | 2 days | 6.2.1 |
| 6.2.4 | Online confirmation | P0 | 0.5 days | 5.1.2 |

**Total Phase 2 Effort:** ~6.5 days (Week 5-6)

---

## 7. Phase 3: Dashboard MVP

**Duration:** Week 7-10
**Priority:** MEDIUM

### 7.3.1 Task: Create FastAPI Backend

**Directory:** `jutsu_engine/api/` (NEW)

**Agent:** BACKEND_ARCHITECT (via Task agent)

| File | Description | LOC Est. |
|------|-------------|----------|
| `__init__.py` | Package init | ~5 |
| `main.py` | FastAPI app, CORS, routes | ~100 |
| `routes/status.py` | GET /api/status | ~50 |
| `routes/config.py` | GET/PUT /api/config | ~80 |
| `routes/trades.py` | GET /api/trades, export | ~100 |
| `routes/performance.py` | GET /api/performance | ~60 |
| `routes/control.py` | POST /api/control/start,stop | ~80 |
| `schemas.py` | Pydantic models | ~150 |
| `dependencies.py` | Database session, auth | ~50 |

**API Endpoints (from PRD Section 6.3):**
```yaml
GET  /api/status           # System status, regime, portfolio
GET  /api/config           # Current configuration
PUT  /api/config           # Update configuration
GET  /api/trades           # Trade history (paginated)
GET  /api/trades/export    # Export trades as CSV
GET  /api/performance      # Performance metrics
POST /api/control/start    # Start trading engine
POST /api/control/stop     # Stop trading engine
GET  /api/indicators       # Current indicator values
```

**Acceptance Criteria:**
- [ ] All 10 REST endpoints functional
- [ ] Pydantic validation on all inputs
- [ ] CORS configured for dashboard
- [ ] Swagger docs at /docs
- [ ] Integration tests for all endpoints

**Dependencies:** Phase 0, 1, 2 (all models and executors)
**Blocks:** React dashboard

---

### 7.3.2 Task: Create React Dashboard Structure

**Directory:** `dashboard/` (NEW)

**Agent:** FRONTEND_ARCHITECT (via Task agent)

| Directory/File | Description |
|----------------|-------------|
| `package.json` | React 18, shadcn/ui, React Query |
| `src/App.tsx` | Main app with routing |
| `src/components/ControlPanel.tsx` | Mode toggle, execution time |
| `src/components/RegimeDisplay.tsx` | Cell, trend, vol state |
| `src/components/PortfolioView.tsx` | Allocation bars |
| `src/components/TradeHistory.tsx` | Trade table |
| `src/hooks/useStatus.ts` | React Query hooks |
| `src/api/client.ts` | API client |

**P0 Features (from PRD Section 6.2):**
- Mode Toggle (Offline/Online)
- Regime Display (cell, trend, vol)
- Portfolio View (allocation %)
- Trade History (table with filtering)

**Acceptance Criteria:**
- [ ] React 18 with TypeScript
- [ ] shadcn/ui components
- [ ] Mode toggle functional
- [ ] Real data from API
- [ ] Responsive design

**Dependencies:** 7.3.1 (FastAPI backend)
**Blocks:** Phase 4

---

### 7.3.3 Task: Add CLI Dashboard Command

**File:** `jutsu_engine/cli/main.py`

**Agent:** CLI_AGENT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 7.3.3.1 | Add `jutsu dashboard` command | ~30 |
| 7.3.3.2 | Start FastAPI server | ~20 |
| 7.3.3.3 | Optional `--port` flag | ~10 |
| 7.3.3.4 | Health check before start | ~15 |

**Acceptance Criteria:**
- [ ] `jutsu dashboard` starts server on port 8000
- [ ] `jutsu dashboard --port 3000` uses custom port
- [ ] Server accessible at http://localhost:8000

**Dependencies:** 7.3.1
**Blocks:** None

---

### Phase 3 Summary

| Task ID | Description | Priority | Effort | Dependencies |
|---------|-------------|----------|--------|--------------|
| 7.3.1 | FastAPI backend | P0 | 5 days | Phase 0-2 |
| 7.3.2 | React dashboard | P0 | 7 days | 7.3.1 |
| 7.3.3 | CLI dashboard cmd | P1 | 0.5 days | 7.3.1 |

**Total Phase 3 Effort:** ~12.5 days (Week 7-10)

---

## 8. Phase 4: Dashboard Advanced

**Duration:** Week 11-14
**Priority:** MEDIUM

### 8.4.1 Task: Parameter Editor UI

**Files:** Dashboard components

**Agent:** FRONTEND_ARCHITECT (via Task agent)

| Task | Description | LOC Est. |
|------|-------------|----------|
| 8.4.1.1 | Parameter form component | ~150 |
| 8.4.1.2 | Validation UI (min/max constraints) | ~80 |
| 8.4.1.3 | PUT /api/config integration | ~50 |
| 8.4.1.4 | Config history view | ~100 |

**Acceptance Criteria:**
- [ ] All 32 parameters editable
- [ ] Validation errors shown inline
- [ ] Changes saved to config_overrides table
- [ ] History of changes viewable

**Dependencies:** 7.3.2 (dashboard)
**Blocks:** None

---

### 8.4.2 Task: WebSocket Live Updates

**Files:** FastAPI + React

**Agent:** BACKEND_ARCHITECT + FRONTEND_ARCHITECT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 8.4.2.1 | FastAPI WebSocket endpoint | ~80 |
| 8.4.2.2 | Real-time status broadcast | ~50 |
| 8.4.2.3 | React Socket.io client | ~60 |
| 8.4.2.4 | Live indicator updates | ~80 |

**Acceptance Criteria:**
- [ ] WS /ws/live endpoint functional
- [ ] Status updates < 1 second latency
- [ ] Reconnection on disconnect
- [ ] Indicator values update in real-time

**Dependencies:** 7.3.1, 7.3.2
**Blocks:** None

---

### 8.4.3 Task: Equity Curve Chart

**Files:** Dashboard components

**Agent:** FRONTEND_ARCHITECT

| Task | Description | LOC Est. |
|------|-------------|----------|
| 8.4.3.1 | Lightweight-charts integration | ~80 |
| 8.4.3.2 | Performance data fetching | ~40 |
| 8.4.3.3 | Equity curve component | ~100 |
| 8.4.3.4 | Regime timeline overlay | ~80 |

**Acceptance Criteria:**
- [ ] Equity curve with daily data points
- [ ] Regime colors on timeline
- [ ] Zoom and pan functionality
- [ ] Export chart as image

**Dependencies:** 5.1.4 (performance snapshots)
**Blocks:** None

---

### Phase 4 Summary

| Task ID | Description | Priority | Effort | Dependencies |
|---------|-------------|----------|--------|--------------|
| 8.4.1 | Parameter editor | P2 | 4 days | Phase 3 |
| 8.4.2 | WebSocket updates | P2 | 3 days | Phase 3 |
| 8.4.3 | Equity curve chart | P3 | 3 days | Phase 1 |

**Total Phase 4 Effort:** ~10 days (Week 11-14)

---

## 9. Phase 5: Production Hardening

**Duration:** Week 15+
**Priority:** LOW (until Phase 4 complete)

### 9.5.1 Task: Health Monitoring

**File:** `jutsu_engine/live/health_monitor.py` (enhance existing)

| Task | Description | LOC Est. |
|------|-------------|----------|
| 9.5.1.1 | System health checks | ~80 |
| 9.5.1.2 | API health endpoint | ~30 |
| 9.5.1.3 | Scheduler health | ~40 |
| 9.5.1.4 | Database connectivity | ~30 |

---

### 9.5.2 Task: Alert System

**File:** `jutsu_engine/live/alert_manager.py` (enhance existing)

| Task | Description | LOC Est. |
|------|-------------|----------|
| 9.5.2.1 | SMS integration (Twilio) | ~80 |
| 9.5.2.2 | Email integration | ~60 |
| 9.5.2.3 | Alert thresholds config | ~40 |
| 9.5.2.4 | Alert history tracking | ~30 |

---

### 9.5.3 Task: Crash Recovery

**File:** `jutsu_engine/live/recovery.py` (NEW)

| Task | Description | LOC Est. |
|------|-------------|----------|
| 9.5.3.1 | State persistence | ~60 |
| 9.5.3.2 | Automatic restart | ~80 |
| 9.5.3.3 | Missed execution detection | ~50 |
| 9.5.3.4 | Recovery notifications | ~30 |

---

### Phase 5 Summary

| Task ID | Description | Priority | Effort | Dependencies |
|---------|-------------|----------|--------|--------------|
| 9.5.1 | Health monitoring | P3 | 2 days | Phase 4 |
| 9.5.2 | Alert system | P3 | 3 days | 9.5.1 |
| 9.5.3 | Crash recovery | P3 | 3 days | Phase 4 |

**Total Phase 5 Effort:** ~8 days (Week 15+)

---

## 10. Quality Gates

### 10.1 Phase 0 Quality Gates

| Gate | Criteria | Validation Method |
|------|----------|-------------------|
| G0.1 | All 6 database models created | `pytest tests/unit/data/test_models.py` |
| G0.2 | strategy_runner uses flat params | Manual test with 32 params |
| G0.3 | Config matches grid search format | Diff against grid search output |
| G0.4 | 5 execution times available | Unit test EXECUTION_TIMES dict |
| G0.5 | Mode enum works | Unit tests for serialization |

### 10.2 Phase 1 Quality Gates

| Gate | Criteria | Validation Method |
|------|----------|-------------------|
| G1.1 | Offline mode runs 24 hours | Continuous test run |
| G1.2 | Trades written to database | Query live_trades table |
| G1.3 | Strategy context captured | Verify all fields populated |
| G1.4 | CLI commands functional | Integration tests |
| G1.5 | Performance snapshots recorded | Query performance_snapshots |

### 10.3 Phase 2 Quality Gates

| Gate | Criteria | Validation Method |
|------|----------|-------------------|
| G2.1 | Schwab orders placed | Test with small position |
| G2.2 | Slippage < 1% threshold | Review actual fills |
| G2.3 | Reconciliation matches | Daily reconciliation report |
| G2.4 | Confirmation flow works | Manual test |

### 10.4 Phase 3 Quality Gates

| Gate | Criteria | Validation Method |
|------|----------|-------------------|
| G3.1 | All 10 API endpoints work | Postman/curl tests |
| G3.2 | Dashboard loads | Browser test |
| G3.3 | Mode toggle functional | End-to-end test |
| G3.4 | Trade history displays | Visual verification |

### 10.5 Success Criteria (from PRD Section 10)

| Mode | Criterion | Target |
|------|-----------|--------|
| Offline | Uptime | 20 consecutive days |
| Offline | Logic Match | 100% vs backtest |
| Offline | Database Integrity | 100% trades recorded |
| Online | Fill Rate | 100% |
| Online | Slippage | <0.5% average |
| Online | Reconciliation | 100% match |
| Dashboard | Availability | 99.9% during market hours |
| Dashboard | Latency | <1s refresh |

---

## 11. Agentic Execution Hierarchy

### 11.1 Orchestration Structure

```
SYSTEM_ORCHESTRATOR
├── LOGGING_ORCHESTRATOR (cross-cutting)
├── VALIDATION_ORCHESTRATOR (cross-cutting)
├── DOCUMENTATION_ORCHESTRATOR (cross-cutting)
│
├── CORE_ORCHESTRATOR
│   ├── STRATEGY_AGENT
│   │   └── Tasks: strategy_runner fix, execution times
│   └── EVENTS_AGENT
│       └── Tasks: mode enum
│
├── APPLICATION_ORCHESTRATOR
│   └── BACKTEST_RUNNER_AGENT
│       └── Tasks: daily_dry_run refactor
│
└── INFRASTRUCTURE_ORCHESTRATOR
    ├── DATABASE_HANDLER_AGENT
    │   └── Tasks: database models, migrations
    ├── SCHWAB_FETCHER_AGENT
    │   └── Tasks: SchwabOrderExecutor, reconciliation
    └── PERFORMANCE_AGENT
        └── Tasks: performance snapshots

EXTERNAL_AGENTS (via Task tool)
├── FRONTEND_ARCHITECT
│   └── Tasks: React dashboard
├── BACKEND_ARCHITECT
│   └── Tasks: FastAPI backend
└── CLI_AGENT
    └── Tasks: CLI commands
```

### 11.2 Agent Assignment Matrix

| Phase | Tasks | Primary Agent | Support Agent |
|-------|-------|---------------|---------------|
| 0 | Database models | DATABASE_HANDLER_AGENT | - |
| 0 | strategy_runner fix | STRATEGY_AGENT | - |
| 0 | Config migration | INFRASTRUCTURE_ORCHESTRATOR | - |
| 0 | Mode enum | CORE_ORCHESTRATOR | - |
| 0 | Executor router | INFRASTRUCTURE_ORCHESTRATOR | - |
| 1 | MockOrderExecutor | INFRASTRUCTURE_ORCHESTRATOR | - |
| 1 | CLI live command | Task(CLI_AGENT) | - |
| 1 | Strategy context | STRATEGY_AGENT | - |
| 1 | Performance tracker | PERFORMANCE_AGENT | - |
| 2 | SchwabOrderExecutor | SCHWAB_FETCHER_AGENT | - |
| 2 | Reconciliation | INFRASTRUCTURE_ORCHESTRATOR | - |
| 3 | FastAPI backend | Task(BACKEND_ARCHITECT) | - |
| 3 | React dashboard | Task(FRONTEND_ARCHITECT) | - |
| 4 | WebSocket updates | Task(BACKEND_ARCHITECT) | Task(FRONTEND_ARCHITECT) |
| 5 | Health monitoring | INFRASTRUCTURE_ORCHESTRATOR | - |

### 11.3 Parallel Execution Opportunities

**Phase 0 (3 parallel tracks):**
```
Track A: Database models (4.0.1)
Track B: Config migration (4.0.3) → strategy_runner fix (4.0.2)
Track C: Mode enum (4.0.5) → Executor router (4.0.6)
         + 5min_before_close (4.0.4) [parallel with anything]
```

**Phase 1 (2 parallel tracks after 5.1.1):**
```
Track A: CLI live command (5.1.2)
Track B: Strategy context (5.1.3) + Performance tracker (5.1.4) + daily_dry_run (5.1.5)
```

**Phase 3 (2 parallel tracks after 7.3.1):**
```
Track A: FastAPI backend (7.3.1)
Track B: React dashboard (7.3.2) [starts after 7.3.1 complete]
```

---

## 12. Risk Assessment

### 12.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Schwab API changes | Medium | High | Monitor changelog, abstract API layer |
| Slippage exceeds threshold | Medium | Medium | Pre-market testing, conservative thresholds |
| Database corruption | Low | High | Backups, transactions, audit log |
| Strategy logic drift | Medium | High | Compare live vs backtest signals |
| WebSocket connection drops | Medium | Low | Auto-reconnection, fallback polling |

### 12.2 Dependency Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Phase 0 delays | Medium | High | Prioritize critical path items |
| React/FastAPI learning curve | Medium | Medium | Use established patterns, shadcn/ui |
| Schwab API rate limits | Low | Medium | Batch requests, caching |

### 12.3 Operational Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Missed execution window | Low | High | Scheduler monitoring, alerts |
| Incorrect parameter config | Medium | High | Validation constraints, UI feedback |
| Market holiday handling | Low | Low | Market calendar integration |

---

## Appendix A: File Change Summary

### New Files to Create

| File | Phase | LOC Est. |
|------|-------|----------|
| `jutsu_engine/live/mode.py` | 0 | 50 |
| `jutsu_engine/live/executor_router.py` | 0 | 100 |
| `jutsu_engine/live/mock_executor.py` | 1 | 200 |
| `jutsu_engine/live/performance_tracker.py` | 1 | 200 |
| `jutsu_engine/live/schwab_executor.py` | 2 | 400 |
| `jutsu_engine/live/reconciliation.py` | 2 | 200 |
| `jutsu_engine/api/__init__.py` | 3 | 5 |
| `jutsu_engine/api/main.py` | 3 | 100 |
| `jutsu_engine/api/routes/*.py` (5 files) | 3 | 370 |
| `jutsu_engine/api/schemas.py` | 3 | 150 |
| `jutsu_engine/api/dependencies.py` | 3 | 50 |
| `jutsu_engine/live/recovery.py` | 5 | 150 |
| `dashboard/` (entire React app) | 3-4 | ~2000 |

**Total New Code:** ~4000 LOC

### Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| `jutsu_engine/data/models.py` | 0 | Add 6 models (~150 LOC) |
| `jutsu_engine/live/strategy_runner.py` | 0 | Refactor _initialize_strategy |
| `config/live_trading_config.yaml` | 0 | Convert to flat structure |
| `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py` | 0 | Add execution time |
| `jutsu_engine/cli/main.py` | 1-3 | Add live, dashboard commands |
| `jutsu_engine/live/dry_run_executor.py` | 1 | Refactor to MockOrderExecutor |
| `jutsu_engine/live/order_executor.py` | 2 | Refactor to SchwabOrderExecutor |
| `scripts/daily_dry_run.py` | 1 | Use unified executor |
| `jutsu_engine/live/health_monitor.py` | 5 | Enhance health checks |
| `jutsu_engine/live/alert_manager.py` | 5 | Add SMS/email |

---

## Appendix B: Test Coverage Requirements

| Phase | Unit Tests | Integration Tests | E2E Tests |
|-------|------------|-------------------|-----------|
| 0 | 50+ | 10+ | - |
| 1 | 40+ | 20+ | 5+ |
| 2 | 30+ | 15+ | 5+ |
| 3 | 60+ | 30+ | 10+ |
| 4 | 40+ | 20+ | 10+ |
| 5 | 30+ | 15+ | 5+ |

**Total:** ~250 unit tests, ~110 integration tests, ~35 E2E tests

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Dec 3, 2025 | Claude | Initial execution plan based on PRD v2.0.1 |

---

**End of Document**
