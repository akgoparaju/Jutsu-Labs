# Module Agent Template

**Purpose**: Template for creating the remaining 10 module agents

## Agent Creation Guide

Use the **EVENT_LOOP_AGENT.md** as the reference template. Each module agent should follow the same structure with module-specific details.

## Remaining Agents to Create

### Layer 1: Core Domain (3 more agents)

**1. PORTFOLIO_AGENT**
- **File**: `.claude/layers/core/modules/PORTFOLIO_AGENT.md`
- **Module**: `jutsu_engine/portfolio/simulator.py`
- **Responsibilities**: Portfolio state management, trade execution, PnL calculation
- **Key Interfaces**: Implements Portfolio interface, uses Events
- **Performance Targets**: <0.1ms per order execution
- **Test Coverage**: >90%

**2. STRATEGY_AGENT**
- **File**: `.claude/layers/core/modules/STRATEGY_AGENT.md`
- **Module**: `jutsu_engine/core/strategy_base.py`
- **Responsibilities**: Define Strategy ABC, provide helper methods, enforce contract
- **Key Interfaces**: Defines Strategy interface for all strategies
- **Performance Targets**: N/A (interface definition)
- **Test Coverage**: >95% (base class and helpers)

**3. EVENTS_AGENT**
- **File**: `.claude/layers/core/modules/EVENTS_AGENT.md`
- **Module**: `jutsu_engine/core/events.py`
- **Responsibilities**: Event dataclass definitions, immutability, validation
- **Key Interfaces**: Defines MarketDataEvent, SignalEvent, OrderEvent, FillEvent
- **Performance Targets**: <0.01ms per event creation
- **Test Coverage**: 100% (simple dataclasses, all paths testable)

### Layer 2: Application (2 agents)

**4. BACKTEST_RUNNER_AGENT**
- **File**: `.claude/layers/application/modules/BACKTEST_RUNNER_AGENT.md`
- **Module**: `jutsu_engine/application/backtest_runner.py`
- **Responsibilities**: Orchestrate full backtest execution, coordinate Core + Infrastructure
- **Key Interfaces**: Uses Core interfaces (Strategy, EventLoop, Portfolio), uses Infrastructure services
- **Performance Targets**: <5% overhead of total backtest time
- **Test Coverage**: >85% (mock Core and Infrastructure)

**5. DATA_SYNC_AGENT**
- **File**: `.claude/layers/application/modules/DATA_SYNC_AGENT.md`
- **Module**: `jutsu_engine/application/data_sync.py`
- **Responsibilities**: Orchestrate market data synchronization, coordinate metadata and API
- **Key Interfaces**: Uses Infrastructure services (MetadataRepository, SchwabDataFetcher, MarketDataRepository)
- **Performance Targets**: <10% overhead of API call time
- **Test Coverage**: >85% (mock Infrastructure)

### Layer 3: Infrastructure (5 agents)

**6. DATABASE_HANDLER_AGENT**
- **File**: `.claude/layers/infrastructure/modules/DATABASE_HANDLER_AGENT.md`
- **Module**: `jutsu_engine/data/handlers/database.py`
- **Responsibilities**: Implement DataHandler interface, efficient database queries, caching
- **Key Interfaces**: Implements DataHandler (Core interface), uses SQLAlchemy models
- **Performance Targets**: <50ms for 1000 bars, <1ms for single bar
- **Test Coverage**: >85% (use in-memory SQLite for tests)

**7. SCHWAB_FETCHER_AGENT**
- **File**: `.claude/layers/infrastructure/modules/SCHWAB_FETCHER_AGENT.md`
- **Module**: `jutsu_engine/data/fetchers/schwab.py`
- **Responsibilities**: Schwab API integration, OAuth, rate limiting, retry logic
- **Key Interfaces**: Provides data fetching service to Application layer
- **Performance Targets**: <2s per API call (including rate limiting)
- **Test Coverage**: >80% (mock API calls)

**8. INDICATORS_AGENT**
- **File**: `.claude/layers/infrastructure/modules/INDICATORS_AGENT.md`
- **Module**: `jutsu_engine/indicators/technical.py`
- **Responsibilities**: Pure indicator functions (SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, OBV)
- **Key Interfaces**: Stateless functions, no interfaces
- **Performance Targets**: <10ms for SMA on 1000 bars, <15ms for RSI, <20ms for Bollinger
- **Test Coverage**: >90% (pure functions, easy to test)

**9. PERFORMANCE_AGENT**
- **File**: `.claude/layers/infrastructure/modules/PERFORMANCE_AGENT.md`
- **Module**: `jutsu_engine/performance/analyzer.py`
- **Responsibilities**: Calculate metrics (Sharpe, drawdown, win rate, etc.), performance attribution
- **Key Interfaces**: Provides analysis service to Application layer
- **Performance Targets**: <500ms for typical backtest metrics
- **Test Coverage**: >85% (use fixture trade data)

**10. CLI_AGENT** (Entry Point)
- **File**: `.claude/layers/entry_points/CLI_AGENT.md`
- **Module**: `jutsu_cli/main.py`
- **Responsibilities**: CLI interface (Click/Typer), command routing, user interaction
- **Key Interfaces**: Uses Application layer (BacktestRunner, DataSync)
- **Performance Targets**: <100ms command startup overhead
- **Test Coverage**: >75% (test command parsing and routing)

## Module Agent Structure

Each module agent should have these sections (copy from EVENT_LOOP_AGENT.md):

```markdown
# {MODULE_NAME} Module Agent

**Type**: Module Agent (Level 4)
**Layer**: {1-3 or Entry Point}
**Module**: `{module_path}`
**Orchestrator**: {LAYER}_ORCHESTRATOR

## Identity & Purpose
Brief description and philosophy

## Module Ownership
- Primary files
- Test files
- Dependencies (allowed imports)

## Responsibilities
- Primary tasks
- Boundaries (will do / won't do / coordinates with)

## Current Implementation
- Class structure
- Key methods
- Performance requirements

## Interfaces
- Depends On (uses these interfaces)
- Provides (exposes these interfaces)

## Implementation Standards
- Code quality requirements
- Logging pattern
- Testing requirements

## Common Tasks
- Task examples with approach and validation

## Decision Log
- Reference to DECISIONS.md
- Recent decisions

## Communication Protocol
- To orchestrator
- To other module agents

## Error Scenarios
- Common error handling patterns

## Future Enhancements
- Planned improvements by phase

## Quick Reference
- Key facts and reminders

## Summary
- One paragraph summary
```

## Quick Reference Table

| Agent | Layer | Module | Key Responsibility |
|-------|-------|--------|-------------------|
| EVENT_LOOP | Core (1) | event_loop.py | Bar-by-bar coordinator |
| PORTFOLIO | Core (1) | portfolio/simulator.py | State management, execution |
| STRATEGY | Core (1) | core/strategy_base.py | Strategy interface definition |
| EVENTS | Core (1) | core/events.py | Event dataclass definitions |
| BACKTEST_RUNNER | Application (2) | application/backtest_runner.py | Backtest orchestration |
| DATA_SYNC | Application (2) | application/data_sync.py | Data sync orchestration |
| DATABASE_HANDLER | Infrastructure (3) | data/handlers/database.py | Database access |
| SCHWAB_FETCHER | Infrastructure (3) | data/fetchers/schwab.py | API integration |
| INDICATORS | Infrastructure (3) | indicators/technical.py | TA calculations |
| PERFORMANCE | Infrastructure (3) | performance/analyzer.py | Metrics calculation |
| CLI | Entry Point | jutsu_cli/main.py | Command-line interface |

## Supporting Documents

Each module should reference:
- **DECISIONS.md**: Module-specific architectural decisions
- **INTERFACES.md**: Interface contracts the module depends on or provides

## Creation Priority

**High Priority** (needed for MVP):
1. PORTFOLIO_AGENT - Core state management
2. BACKTEST_RUNNER_AGENT - Primary use case
3. DATABASE_HANDLER_AGENT - Data access
4. INDICATORS_AGENT - TA calculations

**Medium Priority** (improve development workflow):
5. DATA_SYNC_AGENT - Data management
6. SCHWAB_FETCHER_AGENT - API integration
7. PERFORMANCE_AGENT - Metrics

**Lower Priority** (can use EVENT_LOOP_AGENT as reference):
8. STRATEGY_AGENT - Interface definition
9. EVENTS_AGENT - Dataclass definitions
10. CLI_AGENT - Entry point

## Usage Instructions

1. **Copy EVENT_LOOP_AGENT.md** to new location
2. **Replace all placeholders** with module-specific details
3. **Update responsibilities** based on module purpose
4. **Define interfaces** (depends on / provides)
5. **Set performance targets** based on module role
6. **Write test coverage requirements** based on complexity
7. **Add common tasks** relevant to module
8. **Review with orchestrator** before finalizing

## Example: Creating PORTFOLIO_AGENT

```bash
# 1. Copy template
cp .claude/layers/core/modules/EVENT_LOOP_AGENT.md \
   .claude/layers/core/modules/PORTFOLIO_AGENT.md

# 2. Replace these throughout the file:
#    - EVENT_LOOP → PORTFOLIO
#    - event_loop.py → portfolio/simulator.py
#    - "Central coordinator" → "Portfolio state management"
#    - etc.

# 3. Update specific sections:
#    - Responsibilities: Trade execution, PnL, position tracking
#    - Performance Targets: <0.1ms per order
#    - Interfaces: Implements Portfolio, uses Events
#    - Common Tasks: Add partial fill support, optimize execution
```

---

## Summary

This template provides the structure for creating the remaining 10 module agents. Use EVENT_LOOP_AGENT.md as the reference implementation, and customize each section for the specific module. Prioritize agents based on MVP needs (Portfolio, BacktestRunner, DatabaseHandler, Indicators first).
