# Multi-Strategy Engine Implementation Plan

**Version**: 1.0
**Date**: 2026-01-20
**Status**: In Progress - Phase 1 Complete
**Author**: Claude Code / Anil Goparaju

## Implementation Progress

| Phase | Description | Status | Date |
|-------|-------------|--------|------|
| Phase 1 | Database & Config Foundation | ✅ Complete | 2026-01-20 |
| Phase 2 | Multi-Strategy Engine Core | ✅ Complete | 2026-01-20 |
| Phase 3 | API Updates | ⏳ Pending | - |
| Phase 4 | Frontend Updates | ⏳ Pending | - |
| Phase 5 | Backtest Data Generation | ⏳ Pending | - |
| Phase 6 | Testing & Validation | ⏳ Pending | - |
| Phase 7 | Deployment & Migration | ⏳ Pending | - |

### Phase 1 Deliverables
- ✅ `config/strategies_registry.yaml` - Central strategy registry
- ✅ `config/strategies/v3_5b.yaml` - Primary strategy config
- ✅ `config/strategies/v3_5d.yaml` - Secondary strategy config (with Cell 1 Exit Confirmation)
- ✅ `state/strategies/v3_5b/` - Strategy state directory with symlink for backward compatibility
- ✅ `state/strategies/v3_5d/` - New strategy state directory
- ✅ `scripts/add_strategy_id_columns.py` - Database migration script
- ✅ `alembic/versions/20260120_0001_add_strategy_id_columns.py` - Alembic migration
- ✅ `jutsu_engine/data/models.py` - Updated with strategy_id columns
- ✅ Database migration applied successfully

### Phase 2 Deliverables
- ✅ `jutsu_engine/live/strategy_registry.py` - StrategyRegistry class for loading and managing strategies
- ✅ `jutsu_engine/live/multi_state_manager.py` - MultiStrategyStateManager for per-strategy state
- ✅ `jutsu_engine/live/multi_strategy_runner.py` - MultiStrategyRunner for executing all strategies
- ✅ Updated `jutsu_engine/live/__init__.py` with multi-strategy exports

## Executive Summary

This document outlines the implementation plan for extending Jutsu Labs to support **multiple strategies running in parallel** with unified comparison capabilities. The architecture follows **Option B: Unified Multi-Strategy Engine** - a single engine that runs multiple strategies within one process, sharing data fetching while maintaining separate state and positions.

### Goals
1. Run multiple strategies (starting with v3_5b and v3_5d) in parallel
2. Fair comparison with identical data and timing
3. Unified dashboard with strategy selector and comparison views
4. Extensible architecture for adding future strategies
5. Maintain production safety (primary strategy protected)

### Current State
- **v3_5b**: Active paper trading with real positions
- **v3_5d**: New strategy, needs integration

---

## Architecture Overview

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                     SCHEDULER (APScheduler)                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  Multi-Strategy Runner                       ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       ││
│  │  │  Strategy 1  │  │  Strategy 2  │  │  Strategy N  │  ...  ││
│  │  │   (v3_5b)    │  │   (v3_5d)    │  │   (future)   │       ││
│  │  │   PRIMARY    │  │  SECONDARY   │  │  SECONDARY   │       ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘       ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                    Shared Data Fetcher                          │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    State Manager                             ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       ││
│  │  │ state_v3_5b  │  │ state_v3_5d  │  │ state_vX_Y   │  ...  ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘       ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ performance_    │  │     trades      │  │  strategy_      │  │
│  │ snapshots       │  │                 │  │  configs        │  │
│  │ +strategy_id    │  │ +strategy_id    │  │  (new table)    │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Dashboard (React)                           │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Strategy Selector: [v3_5b ▼] [v3_5d] [Compare]             ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  Performance │ Trades │ Backtest │ Config                   ││
│  │  (filtered by strategy_id)                                  ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Strategy Registry Pattern**: Central registry of all active strategies
2. **Shared Data, Isolated State**: One data fetch, separate state per strategy
3. **Primary/Secondary Designation**: Primary strategy is protected; secondary failures don't affect primary
4. **Strategy ID Everywhere**: All database tables and API responses include `strategy_id`
5. **Backward Compatible**: Existing v3_5b data remains accessible

---

## File Structure Changes

### Current Structure
```
config/
  live_trading_config.yaml          # Single strategy config
  backtest/
    dashboard_Hierarchical_Adaptive_v3_5b.csv
    config_Hierarchical_Adaptive_v3_5b.yaml

state/
  state.json                        # Single strategy state
```

### Target Structure
```
config/
  strategies/                       # NEW: Strategy configs directory
    v3_5b.yaml                      # v3_5b paper trading config
    v3_5d.yaml                      # v3_5d paper trading config
    _template.yaml                  # Template for new strategies
  strategies_registry.yaml          # NEW: Active strategies list
  backtest/
    dashboard_Hierarchical_Adaptive_v3_5b.csv
    dashboard_Hierarchical_Adaptive_v3_5d.csv
    config_Hierarchical_Adaptive_v3_5b.yaml
    config_Hierarchical_Adaptive_v3_5d.yaml

state/
  strategies/                       # NEW: Per-strategy state
    v3_5b/
      state.json
      backups/
    v3_5d/
      state.json
      backups/
  scheduler_state.json              # Unchanged
```

---

## Database Schema Changes

### Modified Tables

#### `performance_snapshots`
```sql
-- Add strategy_id column (nullable for backward compatibility)
ALTER TABLE performance_snapshots 
ADD COLUMN strategy_id VARCHAR(50) DEFAULT 'v3_5b';

-- Add index for efficient filtering
CREATE INDEX idx_perf_snapshots_strategy 
ON performance_snapshots(strategy_id, snapshot_date);

-- Backfill existing data
UPDATE performance_snapshots 
SET strategy_id = 'v3_5b' 
WHERE strategy_id IS NULL;
```

#### `trades`
```sql
-- Verify strategy_name column exists (it does)
-- Add strategy_id for consistency (strategy_name is descriptive, strategy_id is the key)
ALTER TABLE trades 
ADD COLUMN strategy_id VARCHAR(50) DEFAULT 'v3_5b';

-- Backfill existing data
UPDATE trades 
SET strategy_id = 'v3_5b' 
WHERE strategy_id IS NULL;
```

### New Tables

#### `strategy_configs` (Optional - for UI config management)
```sql
CREATE TABLE strategy_configs (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    strategy_class VARCHAR(100) NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    config_yaml TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert initial strategies
INSERT INTO strategy_configs (strategy_id, display_name, strategy_class, is_primary, is_active)
VALUES 
    ('v3_5b', 'Hierarchical Adaptive v3.5b', 'Hierarchical_Adaptive_v3_5b', TRUE, TRUE),
    ('v3_5d', 'Hierarchical Adaptive v3.5d', 'Hierarchical_Adaptive_v3_5d', FALSE, TRUE);
```

---

## Implementation Phases

## Phase 1: Database & Config Foundation
**Estimated Effort**: 1 day  
**Risk**: LOW  
**Dependencies**: None

### Task 1.1: Database Schema Migration
**File**: `alembic/versions/xxx_add_strategy_id.py` (or manual migration)

- [ ] Create migration script for `strategy_id` column in `performance_snapshots`
- [ ] Create migration script for `strategy_id` column in `trades`
- [ ] Add indexes for strategy filtering
- [ ] Backfill existing data with `'v3_5b'`
- [ ] Test migration on development database
- [ ] Create rollback script

**Validation**:
```sql
SELECT strategy_id, COUNT(*) FROM performance_snapshots GROUP BY strategy_id;
-- Expected: v3_5b with existing row count
```

### Task 1.2: Strategy Registry Configuration
**File**: `config/strategies_registry.yaml`

- [ ] Create strategies registry file
- [ ] Define schema for strategy entries
- [ ] Add v3_5b as primary strategy
- [ ] Add v3_5d as secondary strategy

**Example**:
```yaml
# config/strategies_registry.yaml
version: "1.0"

strategies:
  v3_5b:
    display_name: "Hierarchical Adaptive v3.5b"
    strategy_class: "Hierarchical_Adaptive_v3_5b"
    config_file: "config/strategies/v3_5b.yaml"
    is_primary: true
    is_active: true
    paper_trading: true
    
  v3_5d:
    display_name: "Hierarchical Adaptive v3.5d"  
    strategy_class: "Hierarchical_Adaptive_v3_5d"
    config_file: "config/strategies/v3_5d.yaml"
    is_primary: false
    is_active: true
    paper_trading: true

# Execution order (primary first)
execution_order:
  - v3_5b
  - v3_5d
```

### Task 1.3: Per-Strategy Config Files
**Files**: `config/strategies/v3_5b.yaml`, `config/strategies/v3_5d.yaml`

- [ ] Create `config/strategies/` directory
- [ ] Copy current `live_trading_config.yaml` to `config/strategies/v3_5b.yaml`
- [ ] Create `config/strategies/v3_5d.yaml` with v3_5d parameters
- [ ] Update state file paths in each config
- [ ] Create `_template.yaml` for future strategies

**v3_5d Config Differences**:
```yaml
strategy:
  name: "Hierarchical_Adaptive_v3_5d"
  parameters:
    # v3_5d specific: Cell 1 Exit Confirmation
    cell1_exit_confirmation_enabled: true
    cell1_exit_confirmation_days: 2
    # Golden config defaults (same as v3_5b)
    sma_fast: 40
    sma_slow: 140
    # ... rest of parameters

state:
  file_path: "state/strategies/v3_5d/state.json"
  backup_path: "state/strategies/v3_5d/backups/"
```

### Task 1.4: State Directory Structure
**Directory**: `state/strategies/`

- [ ] Create `state/strategies/v3_5b/` directory
- [ ] Create `state/strategies/v3_5d/` directory
- [ ] Move current `state/state.json` to `state/strategies/v3_5b/state.json`
- [ ] Create symlink `state/state.json` → `state/strategies/v3_5b/state.json` (backward compat)
- [ ] Initialize `state/strategies/v3_5d/state.json` with starting values
- [ ] Update `.gitignore` for new structure

**Initial v3_5d State**:
```json
{
  "last_run": null,
  "vol_state": 0,
  "trend_state": "Unknown",
  "current_positions": {},
  "account_equity": 10000.0,
  "last_allocation": {},
  "metadata": {
    "created_at": "2026-01-20T00:00:00Z",
    "version": "1.0",
    "strategy_id": "v3_5d"
  },
  "initial_qqq_price": null
}
```

---

## Phase 2: Multi-Strategy Engine Core
**Estimated Effort**: 2-3 days  
**Risk**: MEDIUM  
**Dependencies**: Phase 1

### Task 2.1: Strategy Registry Loader
**File**: `jutsu_engine/live/strategy_registry.py` (NEW)

- [ ] Create `StrategyRegistry` class
- [ ] Load strategies from `strategies_registry.yaml`
- [ ] Validate strategy configs exist
- [ ] Provide methods: `get_active_strategies()`, `get_primary()`, `get_by_id()`
- [ ] Add unit tests

**Interface**:
```python
class StrategyRegistry:
    def __init__(self, registry_path: Path = Path("config/strategies_registry.yaml")):
        ...
    
    def get_active_strategies(self) -> List[StrategyConfig]:
        """Return all active strategies in execution order."""
        
    def get_primary_strategy(self) -> StrategyConfig:
        """Return the primary strategy."""
        
    def get_strategy(self, strategy_id: str) -> Optional[StrategyConfig]:
        """Get strategy by ID."""
        
    def is_strategy_active(self, strategy_id: str) -> bool:
        """Check if strategy is active."""
```

### Task 2.2: Multi-Strategy State Manager
**File**: `jutsu_engine/live/state_manager.py` (MODIFY)

- [ ] Refactor `StateManager` to accept `strategy_id` parameter
- [ ] Update file paths to use per-strategy directories
- [ ] Add `strategy_id` to state metadata
- [ ] Create `MultiStrategyStateManager` wrapper class
- [ ] Maintain backward compatibility for single-strategy usage
- [ ] Add unit tests

**Interface**:
```python
class MultiStrategyStateManager:
    def __init__(self, registry: StrategyRegistry):
        self.managers: Dict[str, StateManager] = {}
        for strategy in registry.get_active_strategies():
            self.managers[strategy.id] = StateManager(
                state_file=Path(strategy.state_file_path)
            )
    
    def get_state(self, strategy_id: str) -> TradingState:
        """Get state for specific strategy."""
        
    def save_state(self, strategy_id: str, state: TradingState) -> None:
        """Save state for specific strategy."""
        
    def get_all_states(self) -> Dict[str, TradingState]:
        """Get states for all strategies."""
```

### Task 2.3: Multi-Strategy Runner
**File**: `jutsu_engine/live/multi_strategy_runner.py` (NEW)

- [ ] Create `MultiStrategyRunner` class
- [ ] Implement shared data fetching (fetch once, use for all)
- [ ] Execute strategies in order (primary first)
- [ ] Wrap each strategy in try/except (isolation)
- [ ] Log execution times per strategy
- [ ] Add error recovery and alerting
- [ ] Add unit tests

**Interface**:
```python
class MultiStrategyRunner:
    def __init__(
        self,
        registry: StrategyRegistry,
        state_manager: MultiStrategyStateManager,
        data_fetcher: DataFetcher,
    ):
        ...
    
    async def run_all_strategies(self) -> Dict[str, StrategyResult]:
        """
        Execute all active strategies.
        
        1. Fetch shared market data
        2. For each strategy (in order):
           a. Load strategy instance
           b. Execute strategy logic
           c. Save state
           d. Record to database
        3. Return results summary
        """
        
    async def run_strategy(self, strategy_id: str, market_data: MarketData) -> StrategyResult:
        """Execute single strategy with provided data."""
```

**Execution Flow**:
```python
async def run_all_strategies(self):
    results = {}
    
    # 1. Shared data fetch
    market_data = await self.data_fetcher.fetch_all_symbols()
    
    # 2. Execute each strategy
    for strategy_config in self.registry.get_active_strategies():
        try:
            result = await self.run_strategy(strategy_config.id, market_data)
            results[strategy_config.id] = result
            
            # Record to database
            await self.record_snapshot(strategy_config.id, result)
            
        except Exception as e:
            logger.error(f"Strategy {strategy_config.id} failed: {e}")
            results[strategy_config.id] = StrategyResult(
                success=False, 
                error=str(e)
            )
            
            # Alert if primary failed
            if strategy_config.is_primary:
                await self.alert_primary_failure(e)
    
    return results
```

### Task 2.4: Scheduler Integration
**File**: `jutsu_engine/api/scheduler.py` (MODIFY)

- [ ] Update scheduler to use `MultiStrategyRunner`
- [ ] Modify hourly refresh job to run all strategies
- [ ] Add per-strategy job status tracking
- [ ] Update job logging with strategy context
- [ ] Test with multiple strategies

**Changes**:
```python
# Before
async def _run_hourly_refresh(self):
    await self.data_refresh.refresh_live_data()

# After  
async def _run_hourly_refresh(self):
    runner = MultiStrategyRunner(
        registry=self.strategy_registry,
        state_manager=self.multi_state_manager,
        data_fetcher=self.data_fetcher,
    )
    results = await runner.run_all_strategies()
    
    for strategy_id, result in results.items():
        logger.info(f"Strategy {strategy_id}: {result.status}")
```

### Task 2.5: Database Recording Updates
**File**: `jutsu_engine/live/data_refresh.py` (MODIFY)

- [ ] Add `strategy_id` parameter to `_record_performance_snapshot()`
- [ ] Update INSERT queries to include `strategy_id`
- [ ] Add `strategy_id` to trade recording
- [ ] Ensure backward compatibility (default to 'v3_5b')

---

## Phase 3: API Updates
**Estimated Effort**: 1-2 days  
**Risk**: LOW  
**Dependencies**: Phase 2

### Task 3.1: Strategy List Endpoint
**File**: `jutsu_engine/api/routes/strategies.py` (NEW)

- [ ] Create new router for strategy management
- [ ] `GET /api/strategies` - List all strategies
- [ ] `GET /api/strategies/{id}` - Get strategy details
- [ ] `GET /api/strategies/{id}/state` - Get strategy state
- [ ] Add to main router

**Endpoints**:
```python
@router.get("/strategies")
async def list_strategies() -> List[StrategyInfo]:
    """List all registered strategies with status."""
    
@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str) -> StrategyDetail:
    """Get detailed strategy information."""
    
@router.get("/strategies/{strategy_id}/state")
async def get_strategy_state(strategy_id: str) -> StrategyState:
    """Get current state for a strategy."""
```

### Task 3.2: Performance API Updates
**File**: `jutsu_engine/api/routes/performance.py` (MODIFY)

- [ ] Add `strategy_id` query parameter to all endpoints
- [ ] Filter database queries by `strategy_id`
- [ ] Default to primary strategy if not specified
- [ ] Add comparison endpoint

**Updated Endpoints**:
```python
@router.get("/performance")
async def get_performance(
    strategy_id: Optional[str] = Query(None, description="Strategy ID (default: primary)")
) -> PerformanceResponse:
    ...

@router.get("/performance/compare")
async def compare_strategies(
    strategy_ids: List[str] = Query(..., description="Strategy IDs to compare")
) -> ComparisonResponse:
    """Compare performance across multiple strategies."""
```

### Task 3.3: Backtest API Updates
**File**: `jutsu_engine/api/routes/backtest.py` (MODIFY)

- [ ] Add `strategy_id` query parameter
- [ ] Update `_find_dashboard_csv()` to support strategy selection
- [ ] Add endpoint to list available backtest strategies
- [ ] Support comparison view

**Updated Endpoints**:
```python
@router.get("/backtest/strategies")
async def list_backtest_strategies() -> List[str]:
    """List strategies with available backtest data."""
    # Returns: ["Hierarchical_Adaptive_v3_5b", "Hierarchical_Adaptive_v3_5d"]

@router.get("/backtest/data")
async def get_backtest_data(
    strategy_id: Optional[str] = Query(None, description="Strategy ID")
) -> BacktestDataResponse:
    ...
```

### Task 3.4: Status API Updates
**File**: `jutsu_engine/api/routes/status.py` (MODIFY)

- [ ] Add multi-strategy status overview
- [ ] Return status for all active strategies
- [ ] Include per-strategy health indicators

**New Response**:
```python
@router.get("/status/strategies")
async def get_strategies_status() -> Dict[str, StrategyStatus]:
    """Get status for all active strategies."""
    return {
        "v3_5b": {"state": "running", "last_run": "...", "equity": 10162.54},
        "v3_5d": {"state": "running", "last_run": "...", "equity": 10000.00},
    }
```

### Task 3.5: Trades API Updates
**File**: `jutsu_engine/api/routes/trades.py` (MODIFY)

- [ ] Add `strategy_id` filter parameter
- [ ] Update queries to filter by strategy
- [ ] Default to showing all strategies (with strategy_id in response)

---

## Phase 4: Frontend Updates
**Estimated Effort**: 2 days  
**Risk**: LOW  
**Dependencies**: Phase 3

### Task 4.1: Strategy Context Provider
**File**: `dashboard/src/contexts/StrategyContext.tsx` (NEW)

- [ ] Create React context for selected strategy
- [ ] Store selected strategy ID in state
- [ ] Persist selection in localStorage
- [ ] Provide strategy list from API

**Implementation**:
```typescript
interface StrategyContextType {
  strategies: Strategy[];
  selectedStrategy: string;
  setSelectedStrategy: (id: string) => void;
  isCompareMode: boolean;
  setCompareMode: (enabled: boolean) => void;
  compareStrategies: string[];
}

export const StrategyProvider: React.FC = ({ children }) => {
  const [selectedStrategy, setSelectedStrategy] = useState(
    localStorage.getItem('selectedStrategy') || 'v3_5b'
  );
  // ...
};
```

### Task 4.2: Strategy Selector Component
**File**: `dashboard/src/components/StrategySelector.tsx` (NEW)

- [ ] Create dropdown/tabs for strategy selection
- [ ] Show strategy name and status indicator
- [ ] Add "Compare" toggle button
- [ ] Style consistently with existing UI

**Design**:
```
┌─────────────────────────────────────────────────┐
│  Strategy: [v3.5b ▼]  [v3.5d]  │ ☐ Compare    │
│            ●active    ○active                   │
└─────────────────────────────────────────────────┘
```

### Task 4.3: Update Performance Page
**File**: `dashboard/src/pages/v2/PerformanceV2.tsx` (MODIFY)

- [ ] Add StrategySelector to header
- [ ] Filter data by selected strategy
- [ ] Add comparison view (side-by-side metrics)
- [ ] Update charts to show multiple series in compare mode

**Compare Mode Layout**:
```
┌────────────────────────────────────────────────────────┐
│  Strategy: [Compare Mode]  v3.5b vs v3.5d              │
├────────────────────────────────────────────────────────┤
│  Metric         │  v3.5b      │  v3.5d      │  Diff   │
│  Total Return   │  +15.2%     │  +16.8%     │  +1.6%  │
│  CAGR           │  +12.4%     │  +13.1%     │  +0.7%  │
│  Sharpe         │  1.24       │  1.31       │  +0.07  │
│  Max Drawdown   │  -8.2%      │  -7.5%      │  +0.7%  │
├────────────────────────────────────────────────────────┤
│  [Equity Curve Chart - Both strategies overlaid]       │
└────────────────────────────────────────────────────────┘
```

### Task 4.4: Update Backtest Page
**File**: `dashboard/src/pages/v2/BacktestV2.tsx` (MODIFY)

- [ ] Add StrategySelector to header
- [ ] Fetch strategy list from `/api/backtest/strategies`
- [ ] Update API calls with strategy parameter
- [ ] Add comparison view for backtest data

### Task 4.5: Update Trades Page
**File**: `dashboard/src/pages/v2/TradesV2.tsx` (MODIFY)

- [ ] Add strategy filter dropdown
- [ ] Show strategy column in trades table
- [ ] Filter by selected strategy (or show all)

### Task 4.6: Update Dashboard Home
**File**: `dashboard/src/pages/v2/DashboardV2.tsx` (MODIFY)

- [ ] Show multi-strategy status cards
- [ ] Quick comparison metrics
- [ ] Strategy health indicators

---

## Phase 5: Backtest Data Generation
**Estimated Effort**: 0.5 days  
**Risk**: LOW  
**Dependencies**: None (can run in parallel)

### Task 5.1: Generate v3_5d Backtest
**Command**: Run backtest with dashboard export

- [ ] Use golden config from `grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5d.yaml`
- [ ] Run backtest with `--export-dashboard` flag
- [ ] Verify CSV generated correctly
- [ ] Place in `config/backtest/dashboard_Hierarchical_Adaptive_v3_5d.csv`

**Command**:
```bash
python -m jutsu_engine.application.backtest_runner \
  --config grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5d.yaml \
  --export-dashboard \
  --output-dir config/backtest/
```

### Task 5.2: Create v3_5d Backtest Config
**File**: `config/backtest/config_Hierarchical_Adaptive_v3_5d.yaml`

- [ ] Extract parameters from grid search golden config
- [ ] Format as backtest config
- [ ] Verify config loads correctly in API

---

## Phase 6: Testing & Validation
**Estimated Effort**: 1 day  
**Risk**: LOW  
**Dependencies**: Phases 1-5

### Task 6.1: Unit Tests
- [ ] `test_strategy_registry.py` - Registry loading and querying
- [ ] `test_multi_state_manager.py` - Multi-strategy state management
- [ ] `test_multi_strategy_runner.py` - Parallel execution
- [ ] `test_api_strategy_filter.py` - API filtering by strategy

### Task 6.2: Integration Tests
- [ ] Test full workflow: scheduler → runner → database → API
- [ ] Test strategy isolation (one failure doesn't affect other)
- [ ] Test backward compatibility (existing v3_5b data accessible)

### Task 6.3: Manual Validation
- [ ] Run both strategies in dry_run mode
- [ ] Verify separate state files created
- [ ] Verify database records have correct strategy_id
- [ ] Test dashboard strategy switching
- [ ] Test comparison view

### Task 6.4: Production Readiness
- [ ] Backup existing state files
- [ ] Backup database
- [ ] Create rollback procedure
- [ ] Document manual switchover steps

---

## Phase 7: Deployment & Migration
**Estimated Effort**: 0.5 days  
**Risk**: MEDIUM  
**Dependencies**: Phases 1-6

### Task 7.1: Database Migration (Production)
- [ ] Schedule maintenance window
- [ ] Run migration script
- [ ] Verify data integrity
- [ ] Test API endpoints

### Task 7.2: Config Migration
- [ ] Create new directory structure
- [ ] Move state files
- [ ] Update symlinks
- [ ] Restart services

### Task 7.3: Initialize v3_5d
- [ ] Create initial state file
- [ ] Set starting equity ($10,000)
- [ ] Enable in registry
- [ ] Verify first run

### Task 7.4: Monitoring
- [ ] Add strategy-specific metrics
- [ ] Set up alerts for per-strategy failures
- [ ] Monitor comparison metrics

---

## Rollback Procedure

If issues arise, rollback to single-strategy mode:

1. **Disable v3_5d in registry**:
   ```yaml
   # config/strategies_registry.yaml
   strategies:
     v3_5d:
       is_active: false
   ```

2. **Restore state symlink**:
   ```bash
   rm state/state.json
   ln -s strategies/v3_5b/state.json state/state.json
   ```

3. **Restart services**:
   ```bash
   systemctl restart jutsu-scheduler
   systemctl restart jutsu-api
   ```

4. **Database** (if needed):
   ```sql
   -- Data remains intact, just filter by strategy_id = 'v3_5b'
   ```

---

## Future Extensibility

### Adding a New Strategy

1. **Create strategy config**:
   ```bash
   cp config/strategies/_template.yaml config/strategies/v3_5e.yaml
   # Edit with new strategy parameters
   ```

2. **Add to registry**:
   ```yaml
   # config/strategies_registry.yaml
   strategies:
     v3_5e:
       display_name: "Hierarchical Adaptive v3.5e"
       strategy_class: "Hierarchical_Adaptive_v3_5e"
       config_file: "config/strategies/v3_5e.yaml"
       is_primary: false
       is_active: true
   ```

3. **Initialize state**:
   ```bash
   mkdir -p state/strategies/v3_5e
   cp state/strategies/_template.json state/strategies/v3_5e/state.json
   ```

4. **Restart services** - automatically picks up new strategy

### Promoting a Strategy to Primary

1. **Update registry**:
   ```yaml
   strategies:
     v3_5b:
       is_primary: false  # Demote
     v3_5d:
       is_primary: true   # Promote
   ```

2. **Update execution order**:
   ```yaml
   execution_order:
     - v3_5d  # Now first
     - v3_5b
   ```

3. **Restart services**

---

## Timeline Summary

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| 1 | Database & Config Foundation | 1 day | None |
| 2 | Multi-Strategy Engine Core | 2-3 days | Phase 1 |
| 3 | API Updates | 1-2 days | Phase 2 |
| 4 | Frontend Updates | 2 days | Phase 3 |
| 5 | Backtest Data Generation | 0.5 days | None |
| 6 | Testing & Validation | 1 day | Phases 1-5 |
| 7 | Deployment & Migration | 0.5 days | Phases 1-6 |

**Total Estimated Effort**: 8-10 days

---

## Appendix A: Strategy Config Template

```yaml
# config/strategies/_template.yaml
# Template for new strategy configurations
# Copy this file and modify for new strategies

# ==============================================================================
# STRATEGY IDENTIFICATION
# ==============================================================================
strategy_id: "vX_Y"  # Unique identifier (used in DB, API, state)
version: "1.0"

# ==============================================================================
# STRATEGY CONFIGURATION
# ==============================================================================
strategy:
  name: "Strategy_Class_Name"  # Must match class name in jutsu_engine/strategies/
  
  parameters:
    # Add all strategy-specific parameters here
    # These are passed to strategy.__init__()
    param1: value1
    param2: value2

# ==============================================================================
# EXECUTION SETTINGS
# ==============================================================================
execution:
  rebalance_threshold_pct: 5.0
  max_slippage_pct: 0.5
  execution_time: "15min_after_open"

# ==============================================================================
# STATE MANAGEMENT
# ==============================================================================
state:
  file_path: "state/strategies/vX_Y/state.json"
  backup_enabled: true
  backup_path: "state/strategies/vX_Y/backups/"

# ==============================================================================
# SYMBOL CONFIGURATION
# ==============================================================================
symbols:
  signal_symbol: "QQQ"
  core_long_symbol: "QQQ"
  leveraged_long_symbol: "TQQQ"
  # Add other symbols as needed
```

---

## Appendix B: API Response Examples

### GET /api/strategies
```json
{
  "strategies": [
    {
      "id": "v3_5b",
      "display_name": "Hierarchical Adaptive v3.5b",
      "is_primary": true,
      "is_active": true,
      "status": "running",
      "last_run": "2026-01-20T15:55:00Z",
      "current_equity": 10162.54
    },
    {
      "id": "v3_5d",
      "display_name": "Hierarchical Adaptive v3.5d",
      "is_primary": false,
      "is_active": true,
      "status": "running",
      "last_run": "2026-01-20T15:55:00Z",
      "current_equity": 10000.00
    }
  ]
}
```

### GET /api/performance/compare?strategy_ids=v3_5b&strategy_ids=v3_5d
```json
{
  "comparison": {
    "period": {
      "start_date": "2024-01-01",
      "end_date": "2026-01-20",
      "trading_days": 504
    },
    "strategies": {
      "v3_5b": {
        "total_return": 15.23,
        "cagr": 12.45,
        "sharpe_ratio": 1.24,
        "max_drawdown": -8.21,
        "current_regime": "Cell_3"
      },
      "v3_5d": {
        "total_return": 16.78,
        "cagr": 13.12,
        "sharpe_ratio": 1.31,
        "max_drawdown": -7.54,
        "current_regime": "Cell_3"
      }
    },
    "differences": {
      "total_return": 1.55,
      "cagr": 0.67,
      "sharpe_ratio": 0.07,
      "max_drawdown": 0.67
    },
    "winner": "v3_5d"
  }
}
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-20 | Claude Code | Initial document |
