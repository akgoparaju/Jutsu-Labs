# State Management Architecture

> Decision document for Jutsu-Labs state persistence strategy

**Status**: Draft  
**Created**: 2025-12-11  
**Authors**: Anil Goparaju  

---

## Executive Summary

This document analyzes the architectural options for managing trading state (`state.json`) in a multi-client deployment scenario (local development + Docker production). The recommendation is to implement **environment isolation** as the immediate solution, with database-backed state deferred until multi-writer scenarios are required.

---

## Current State

### state.json Structure

```json
{
  "last_run": "2025-12-11T15:09:59.684143+00:00",
  "vol_state": 0,
  "trend_state": "BullStrong",
  "current_positions": {
    "TQQQ": 109,
    "QQQ": 6
  },
  "account_equity": 10000.0,
  "last_allocation": {
    "TQQQ": 0.6,
    "QQQ": 0.4
  },
  "metadata": {
    "created_at": null,
    "version": "1.0"
  },
  "initial_qqq_price": 622.94
}
```

### Current Usage Patterns

| File | Usage |
|------|-------|
| `jutsu_engine/live/state_manager.py` | Primary read/write with atomic writes (temp + rename) |
| `jutsu_engine/live/health_monitor.py` | Validates state integrity |
| `jutsu_engine/live/data_refresh.py` | Reads for dashboard snapshots |
| `scripts/daily_dry_run.py` | Updates after strategy execution |
| `jutsu_engine/api/scheduler.py` | Separate `scheduler_state.json` for jobs |

### Problem Statement

With multiple clients (local deployment and Docker container) potentially accessing the same `state.json`:

1. **Stale Reads**: One client reads while another is writing
2. **Race Conditions**: Multiple clients attempting concurrent writes
3. **Data Loss**: Last writer wins without coordination
4. **No Locking**: Current implementation has no mutex mechanism

---

## Options Analysis

### Option 1: Database-Backed State

Migrate state from `state.json` to PostgreSQL using the existing `SystemState` table.

```python
# Already exists in jutsu_engine/data/models.py
class SystemState(Base):
    __tablename__ = 'system_state'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, index=True)
    value = Column(Text)  # JSON-serialized
    value_type = Column(String(20))
    last_updated = Column(DateTime(timezone=True))
```

**Pros**:
- ACID transactions guarantee consistency
- Row-level locking prevents race conditions
- Single source of truth for all clients
- Schema already exists

**Cons**:
- Requires database connection for simple state reads
- Increased code complexity (session management)
- Migration effort required
- Overkill for single-writer scenarios

**Implementation Complexity**: Medium (~200-300 LOC)

### Option 2: Environment Isolation

Separate dev and prod environments completely with their own state files and databases.

```
┌─────────────────┐         ┌─────────────────┐
│   LOCAL (Dev)   │         │  DOCKER (Prod)  │
├─────────────────┤         ├─────────────────┤
│ .env.dev        │         │ .env.prod       │
│ state/dev/      │         │ state/prod/     │
│ dev_database    │         │ prod_database   │
└─────────────────┘         └─────────────────┘
```

**Pros**:
- Complete isolation prevents accidents
- Low implementation effort
- No code changes required (configuration only)
- Clear separation of concerns

**Cons**:
- Doesn't solve multi-writer within same environment
- Two environments to maintain
- Testing production scenarios requires switching

**Implementation Complexity**: Low (configuration changes)

### Option 3: Single-Writer Pattern

Document and enforce that only one designated client writes to state in production.

**Pros**:
- Zero code changes
- No complexity added
- Works for current use case

**Cons**:
- Relies on convention, not enforcement
- Doesn't scale to HA scenarios
- Human error risk

**Implementation Complexity**: Very Low (documentation only)

---

## Decision Matrix

| Criteria | DB State | Env Isolation | Single-Writer |
|----------|----------|---------------|---------------|
| Implementation Effort | Medium | Low | Very Low |
| Multi-client Safe | ✅ Yes | ⚠️ Per environment | ❌ By convention |
| Dev/Prod Isolation | No help | ✅ Yes | No help |
| Future-proof | ✅ Yes | ✅ Yes | ❌ Limits scale |
| Code Complexity | Higher | Same | Same |
| Immediate Benefit | High | High | Low |

---

## Recommendation

### Phased Approach

**Phase 1: Environment Isolation** (Immediate - Low Effort, High Value)

Implement separate dev and prod environments:

```
state/
├── dev/
│   └── state.json       # Local development state
├── prod/
│   └── state.json       # Production state (Docker only)
└── state.json.template  # Template for new environments
```

Configuration:
```yaml
# .env or config.yaml
ENVIRONMENT: dev  # or prod
STATE_DIR: state/${ENVIRONMENT}/
DATABASE_URL: ${DEV_DATABASE_URL}  # or ${PROD_DATABASE_URL}
```

**Phase 2: Enhanced State Markers** (Immediate - Low Effort)

Add environment and writer identification to state:

```json
{
  "environment": "production",
  "writer_id": "docker-scheduler",
  "last_run": "2025-12-11T15:09:59.684143+00:00",
  ...
}
```

Add validation in `StateManager` to warn on environment mismatch:

```python
def validate_environment(self, state: Dict) -> bool:
    expected_env = os.getenv('ENVIRONMENT', 'dev')
    state_env = state.get('environment')
    if state_env and state_env != expected_env:
        logger.warning(f"State environment mismatch: {state_env} != {expected_env}")
        return False
    return True
```

**Phase 3: Database Migration** (Deferred - When Needed)

Migrate to `SystemState` table only when:
- Multiple production instances writing simultaneously
- High-availability / failover requirements
- Cross-region deployments

---

## Implementation Guide

### Phase 1: Directory Structure

```bash
# Create environment-specific state directories
mkdir -p state/dev state/prod

# Copy current state as prod baseline
cp state/state.json state/prod/state.json

# Create fresh dev state
cp state/state.json.template state/dev/state.json
```

### Phase 2: Configuration Changes

**Option A: Environment Variable**
```bash
# .env.dev
ENVIRONMENT=dev
STATE_DIR=state/dev
DATABASE_URL=sqlite:///data/dev_market_data.db

# .env.prod
ENVIRONMENT=prod
STATE_DIR=state/prod
DATABASE_URL=postgresql://user:pass@host:port/jutsu_labs
```

**Option B: Config File**
```yaml
# config/environments/dev.yaml
environment: dev
state:
  directory: state/dev
database:
  url: sqlite:///data/dev_market_data.db

# config/environments/prod.yaml
environment: prod
state:
  directory: state/prod
database:
  url: ${PROD_DATABASE_URL}
```

### Phase 3: Code Changes (StateManager)

```python
# jutsu_engine/live/state_manager.py

class StateManager:
    def __init__(
        self,
        state_file: Path = None,
        environment: str = None,
        ...
    ):
        self.environment = environment or os.getenv('ENVIRONMENT', 'dev')
        
        if state_file is None:
            state_dir = os.getenv('STATE_DIR', f'state/{self.environment}')
            state_file = Path(state_dir) / 'state.json'
        
        self.state_file = state_file
        ...
    
    def save_state(self, state: Dict[str, Any]) -> None:
        # Add environment marker
        state['environment'] = self.environment
        state['writer_id'] = os.getenv('WRITER_ID', 'unknown')
        ...
```

---

## Future: Database State Migration

When multi-writer scenarios become necessary, implement `DatabaseStateManager`:

```python
class DatabaseStateManager:
    """
    Database-backed state manager using SystemState table.
    
    Provides ACID-compliant state persistence with row-level
    locking for concurrent access.
    """
    
    STATE_KEY = 'trading_state'
    
    def __init__(self, session_maker):
        self.session_maker = session_maker
    
    def load_state(self) -> Dict[str, Any]:
        with self.session_maker() as session:
            record = session.query(SystemState).filter(
                SystemState.key == self.STATE_KEY
            ).first()
            
            if record is None:
                return self._default_state()
            
            return json.loads(record.value)
    
    def save_state(self, state: Dict[str, Any]) -> None:
        with self.session_maker() as session:
            # Row-level lock with FOR UPDATE
            record = session.query(SystemState).filter(
                SystemState.key == self.STATE_KEY
            ).with_for_update().first()
            
            if record is None:
                record = SystemState(
                    key=self.STATE_KEY,
                    value_type='json'
                )
                session.add(record)
            
            record.value = json.dumps(state, default=str)
            record.last_updated = datetime.now(timezone.utc)
            session.commit()
```

---

## Appendix: Root Cause of Recent Issue

The regime cell discrepancy (12/4-12/10 showing Cell 3 instead of Cell 1) was caused by:

1. `daily_dry_run.py` didn't save `trend_state` to `state.json` before commit `0347004`
2. `data_refresh.py` reads `trend_state` from `state.json` for snapshots
3. When missing, it defaulted to `'Sideways'` → Cell 3
4. Fix applied in commit `0347004`: now saves `trend_state` to `state.json`

This issue was about **data completeness**, not concurrency. However, it highlighted the importance of `state.json` as a critical persistence layer, prompting this architectural review.

---

## References

- `jutsu_engine/live/state_manager.py` - Current file-based implementation
- `jutsu_engine/data/models.py:SystemState` - Existing DB schema for future use
- `jutsu_engine/live/data_refresh.py` - Consumer of state for dashboard
- Commit `0347004` - Fix for trend_state persistence

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2025-12-11 | Anil Goparaju | Initial draft |
