# Agent Routing Guide

**Purpose**: How to activate and work with the multi-agent system in Jutsu Labs backtesting engine

**Version**: 2.0
**Last Updated**: November 2, 2025

---

## 🔴 MANDATORY: Agent Routing for ALL Tasks

**CRITICAL RULE**: **EVERY** task on Jutsu-Labs MUST route through the agent hierarchy - no exceptions.

### Why This is Mandatory

**Agent Context Files** (`.claude/layers/.../modules/*_AGENT.md`):
- Each agent has complete domain expertise for its module
- Contains module ownership, responsibilities, dependencies
- Defines allowed/forbidden imports (architecture enforcement)
- Documents patterns, performance targets, testing requirements
- Maintains knowledge of past issues and solutions

**Without Agent Routing**:
- ❌ Module expertise not used → incorrect implementations
- ❌ Architecture boundaries violated → dependency chaos
- ❌ Patterns inconsistent → technical debt accumulates
- ❌ Performance targets missed → degradation over time
- ❌ Knowledge lost → same bugs recur
- ❌ No Serena memories → context not preserved

**With Agent Routing**:
- ✅ Agent reads its context file → expert implementation
- ✅ Dependencies validated → architecture maintained
- ✅ Patterns followed → consistency enforced
- ✅ Performance met → targets validated
- ✅ Knowledge preserved → bugs stay fixed
- ✅ Serena memories written → context accumulates

### Universal Command: `/orchestrate`

**Use for EVERYTHING** (replaces manual agent routing):

```bash
# Simple bug fix
/orchestrate fix bug in Schwab API, returns 0 bars

# Single-line change
/orchestrate fix typo in EventLoop docstring

# Complex feature
/orchestrate implement trailing stop-loss orders

# Analysis
/orchestrate analyze Schwab API reliability

# Refactoring
/orchestrate refactor Core layer for performance
```

**What `/orchestrate` Guarantees**:
1. ✅ Serena activated and memories read
2. ✅ Routes to correct orchestrator (SYSTEM/CORE/APPLICATION/INFRASTRUCTURE)
3. ✅ Agent reads its context file from `.claude/layers/.../modules/`
4. ✅ Agent uses domain expertise and module knowledge
5. ✅ Multi-level validation (agent → layer → system)
6. ✅ CHANGELOG.md updated automatically
7. ✅ Serena memory written
8. ✅ Evidence-based completion report

### Routing Rules

**Rule 1**: ALL tasks route through agents (even 1-line fixes)
**Rule 2**: Agents ALWAYS read their context files
**Rule 3**: Context files are the source of truth for module expertise
**Rule 4**: Serena memories supplement agent context with project history
**Rule 5**: Validation happens at agent, layer, and system levels

---

## Overview

The Jutsu-Labs project uses a hierarchical multi-agent architecture where specialized agents handle different parts of the codebase. **Every agent has a context file** that contains complete domain expertise, and **every task must route through this system**.

## Quick Reference

### Primary Method: `/orchestrate` (REQUIRED)

**Use for ALL tasks**:

```bash
/orchestrate <task description>
```

**Auto-routes based on keywords**:
```
"Fix bug in EventLoop" → CORE/EVENT_LOOP_AGENT
"Optimize backtest performance" → APP/BACKTEST_RUNNER_AGENT
"Add Schwab API retry logic" → INFRA/SCHWAB_FETCHER_AGENT
"Change logging format" → LOGGING_ORCHESTRATOR
"Run full validation" → VALIDATION_ORCHESTRATOR
```

### Alternative: Manual `/agent` Command

**Only use when you need explicit control**:

```bash
/agent core/event-loop "add feature X"
/agent infrastructure/schwab-fetcher "fix API bug"
/agent logging "update format"
/agent system "coordinate new layer"
```

### Validation Before Commit

```bash
/orchestrate validate before commit
# or
/validate full
```

---

## Agent Hierarchy

```
SYSTEM_ORCHESTRATOR (Level 0)
├─ LOGGING_ORCHESTRATOR (Cross-cutting)
├─ VALIDATION_ORCHESTRATOR (Cross-cutting)
├─ CORE_ORCHESTRATOR (Layer 1)
│   ├─ EVENT_LOOP_AGENT
│   ├─ PORTFOLIO_AGENT
│   ├─ STRATEGY_AGENT
│   └─ EVENTS_AGENT
├─ APPLICATION_ORCHESTRATOR (Layer 2)
│   ├─ BACKTEST_RUNNER_AGENT
│   └─ DATA_SYNC_AGENT
└─ INFRASTRUCTURE_ORCHESTRATOR (Layer 3)
    ├─ DATABASE_HANDLER_AGENT
    ├─ SCHWAB_FETCHER_AGENT
    ├─ INDICATORS_AGENT
    └─ PERFORMANCE_AGENT
```

---

## Automatic Routing Rules

### Keyword-Based Routing

**Core Domain (Layer 1)**:
- Keywords: `event loop`, `eventloop`, `portfolio`, `strategy`, `signal`, `event`, `order`, `fill`
- Routes to: `CORE_ORCHESTRATOR` → specific module agent

**Application (Layer 2)**:
- Keywords: `backtest`, `runner`, `data sync`, `datasync`, `optimization`, `parameter`
- Routes to: `APPLICATION_ORCHESTRATOR` → specific module agent

**Infrastructure (Layer 3)**:
- Keywords: `database`, `schwab`, `api`, `indicator`, `sma`, `rsi`, `performance analyzer`, `metrics`
- Routes to: `INFRASTRUCTURE_ORCHESTRATOR` → specific module agent

**Cross-Cutting**:
- Keywords: `logging`, `log level`, `log format`
- Routes to: `LOGGING_ORCHESTRATOR`
- Keywords: `validate`, `test`, `quality`, `performance benchmark`
- Routes to: `VALIDATION_ORCHESTRATOR`

### File-Based Routing

If your request mentions a specific file, routes to that file's agent:

```
"Fix event_loop.py" → CORE/EVENT_LOOP_AGENT
"Update backtest_runner.py" → APP/BACKTEST_RUNNER_AGENT
"Improve schwab.py performance" → INFRA/SCHWAB_FETCHER_AGENT
```

### Multi-Module Detection

If request affects multiple modules, routes to appropriate orchestrator:

```
"Add new event type for stop-loss"
→ Affects: Events, EventLoop, Strategy, Portfolio
→ Routes to: SYSTEM_ORCHESTRATOR
→ Creates coordination plan across CORE_ORCHESTRATOR modules
```

---

## Manual Routing Commands

### Format

```
/agent {level}/{agent-name} "{task description}"
```

### Agent Names

**System Level**:
```
/agent system "coordinate multi-layer feature"
/agent logging "change log format"
/agent validation "run full test suite"
```

**Layer Level**:
```
/agent core "review architecture"
/agent application "design new use case"
/agent infrastructure "evaluate new data source"
```

**Module Level**:
```
/agent core/event-loop "optimize performance"
/agent core/portfolio "add partial fills"
/agent core/strategy "update base class"
/agent core/events "add new event type"

/agent application/backtest-runner "add feature"
/agent application/data-sync "improve incremental sync"

/agent infrastructure/database-handler "optimize queries"
/agent infrastructure/schwab-fetcher "add retry logic"
/agent infrastructure/indicators "add new indicator"
/agent infrastructure/performance "improve metrics"
```

### Examples

```bash
# Module-level: Specific implementation
/agent core/event-loop "Add support for batched event processing"

# Layer-level: Architecture review
/agent core "Review dependency structure for circular imports"

# System-level: Multi-layer coordination
/agent system "Design risk management system across all layers"

# Cross-cutting: Logging change
/agent logging "Switch to JSON format for structured logging"

# Cross-cutting: Validation
/agent validation "Run full validation suite before release"
```

---

## Request Flow Examples

### Example 1: Simple Bug Fix

**User**: "EventLoop has memory leak when processing large backtests"

**Auto-Routing**:
1. System analyzes: "eventloop" keyword → Layer 1, Core
2. Routes to: `CORE_ORCHESTRATOR`
3. Orchestrator delegates to: `EVENT_LOOP_AGENT`
4. Agent analyzes code, identifies leak, implements fix
5. Layer validation: `CORE_ORCHESTRATOR` validates change
6. Reports back: "Memory leak fixed in event_loop.py:145"

**Agent Response**:
```
EVENT_LOOP_AGENT:
"Fixed memory leak in EventLoop._process_bars().
Issue: Bar history not cleared after backtest completion.
Solution: Added self._bars.clear() in cleanup.
Tests: Added test_memory_cleanup_after_backtest
Validation: PASSED (layer validation)"
```

---

### Example 2: Multi-Module Feature

**User**: "Add support for trailing stop-loss orders"

**Auto-Routing**:
1. System analyzes: Complex feature affecting multiple modules
2. Routes to: `SYSTEM_ORCHESTRATOR`
3. System creates coordination plan:

```yaml
coordination_plan:
  phase_1:
    agent: CORE/EVENTS_AGENT
    task: "Define TrailingStopEvent dataclass"

  phase_2:
    agent: CORE/PORTFOLIO_AGENT
    task: "Implement trailing stop execution logic"

  phase_3:
    agent: CORE/STRATEGY_AGENT
    task: "Add trailing_stop() method to Strategy base class"

  phase_4:
    agent: CORE/EVENT_LOOP_AGENT
    task: "Handle TrailingStopEvent in processing loop"

  validation:
    agent: VALIDATION_ORCHESTRATOR
    tasks:
      - "Verify all tests pass"
      - "Check interface contracts"
      - "Performance regression check"
```

4. System executes plan sequentially
5. Each agent completes task, reports to orchestrator
6. Validation at each step
7. Final system validation
8. Reports back: "Trailing stop-loss feature complete and validated"

---

### Example 3: Performance Optimization

**User**: "Backtest is slow, need optimization"

**Auto-Routing**:
1. System analyzes: Performance issue, needs profiling first
2. Routes to: `VALIDATION_ORCHESTRATOR`
3. Validation runs performance profiling

**Profiling Result**:
```yaml
performance_profile:
  total_time: 10.5s
  breakdown:
    - indicator_calculation: 6.2s (59%)
    - database_queries: 2.8s (27%)
    - event_processing: 1.3s (12%)
    - other: 0.2s (2%)
```

4. System creates optimization plan:
```yaml
optimization_plan:
  priority_1:
    agent: INFRA/INDICATORS_AGENT
    impact: 59%
    task: "Optimize indicator calculations (caching, vectorization)"

  priority_2:
    agent: INFRA/DATABASE_HANDLER_AGENT
    impact: 27%
    task: "Optimize database queries (batching, indexing)"

  priority_3:
    agent: CORE/EVENT_LOOP_AGENT
    impact: 12%
    task: "Optimize event processing if still needed"
```

5. Executes optimizations in priority order
6. Validates performance improvements after each
7. Reports results

---

### Example 4: Logging Update

**User**: "Add timing information to all backtest operations"

**Auto-Routing**:
1. System analyzes: "logging" keyword → Cross-cutting concern
2. Routes to: `LOGGING_ORCHESTRATOR`
3. Logging Orchestrator analyzes scope: Affects all layers
4. Creates directive:

```yaml
logging_directive:
  target: ALL_LAYERS
  directive: "Add operation timing to long-running operations (>1s)"
  pattern: |
    start = time.time()
    result = operation()
    elapsed = time.time() - start
    logger.info(f"Operation completed in {elapsed:.2f}s")

  affected_modules:
    - BACKTEST_RUNNER_AGENT
    - DATA_SYNC_AGENT
    - EVENT_LOOP_AGENT
```

5. Routes directive to each layer orchestrator
6. Layer orchestrators coordinate with module agents
7. Each agent implements logging pattern
8. Logging Orchestrator validates consistency
9. Reports back: "Timing logging added to 8 modules"

---

## Validation Workflow

### Layer Validation (Automatic)

Runs automatically after every module change:

```
Module Agent completes change
    ↓
Layer Orchestrator runs validation:
├─ Type checking (mypy)
├─ Unit tests (pytest)
├─ Interface contracts
├─ Performance check
└─ Logging review
    ↓
PASS → Change approved
FAIL → Feedback to module agent
```

### Full System Validation (On Request)

**Trigger**:
- User says: "Validate before commit" or "Run full validation"
- User uses: `/validate full`
- Before any git commit

**Process**:
```
VALIDATION_ORCHESTRATOR runs:
├─ All unit tests
├─ Integration tests
├─ Architecture validation
├─ Performance benchmarks
├─ Security scan
├─ Documentation check
└─ Code quality analysis
    ↓
Generates comprehensive report
    ↓
APPROVED → Safe to commit
APPROVED_WITH_WARNINGS → Review warnings, can commit
BLOCKED → Must fix issues before commit
```

---

## Common Patterns

### Pattern 1: "I want to..."

```
"I want to add a new indicator"
→ INFRA/INDICATORS_AGENT

"I want to optimize EventLoop"
→ CORE/EVENT_LOOP_AGENT

"I want to add Monte Carlo simulation"
→ SYSTEM_ORCHESTRATOR (multi-layer feature)

"I want to change log levels"
→ LOGGING_ORCHESTRATOR
```

### Pattern 2: "Fix bug in..."

```
"Fix bug in portfolio calculation"
→ CORE/PORTFOLIO_AGENT

"Fix Schwab API timeout"
→ INFRA/SCHWAB_FETCHER_AGENT

"Fix backtest results wrong"
→ Multiple agents possible, starts with VALIDATION (profiling)
```

### Pattern 3: "How do I..."

```
"How do I add a new strategy?"
→ CORE/STRATEGY_AGENT (provides pattern/example)

"How do I add custom metrics?"
→ INFRA/PERFORMANCE_AGENT (provides pattern)

"How do I test my changes?"
→ VALIDATION_ORCHESTRATOR (provides testing guide)
```

---

## Agent Response Patterns

### Module Agent Response
```markdown
**Agent**: EVENT_LOOP_AGENT
**Task**: Optimize bar processing loop

**Analysis**: Current loop processes bars one at a time with dict lookups

**Solution**:
- Batch process bars in chunks of 100
- Use local variable caching for hot path
- Reduce dict lookups by 80%

**Implementation**:
- Modified: event_loop.py:123-156
- Added: _process_bar_batch() method
- Tests: test_batch_processing_performance

**Performance**:
- Before: 1.2s for 1000 bars
- After: 0.4s for 1000 bars
- Improvement: 67% faster

**Validation**: PASSED (layer validation)
**Ready for**: System validation before commit
```

### Orchestrator Response
```markdown
**Agent**: CORE_ORCHESTRATOR
**Task**: Coordinate new event type addition

**Coordination Plan**:
1. EVENTS_AGENT: Define RiskEvent ✅
2. EVENT_LOOP_AGENT: Add handling ✅
3. STRATEGY_AGENT: Update interface ✅
4. PORTFOLIO_AGENT: Implement execution ⏳

**Status**: 3/4 complete, in progress

**Interface Changes**:
- Added: RiskEvent dataclass
- Modified: EventLoop.process_event() signature
- Added: Strategy.on_risk_event() hook

**Validation**: Layer validation passed for completed modules
**Next**: Complete PORTFOLIO_AGENT implementation
```

---

## Best Practices

### 1. Let Auto-Routing Work

**Preferred**:
```
"Add retry logic to Schwab API"
→ Auto-routes to SCHWAB_FETCHER_AGENT
```

**Not Needed**:
```
/agent infrastructure/schwab-fetcher "Add retry logic to Schwab API"
→ Works, but unnecessary overhead
```

### 2. Use Manual Routing for Precision

**When to Use**:
- Complex requests that might confuse auto-routing
- Orchestrator-level discussions
- Cross-cutting concerns

**Examples**:
```
/agent core "Review architecture for circular dependencies"
/agent system "Design new layer for live trading"
/agent logging "Implement structured JSON logging"
```

### 3. Request Validation Explicitly

Before committing:
```
"Run full validation"
or
/validate full
```

For specific checks:
```
"Validate performance only"
"Run security scan"
"Check test coverage"
```

### 4. Ask for Clarification

Agents can ask questions back:

```
User: "Add new event type"

EVENTS_AGENT:
"What kind of event? Please specify:
- Signal event (trading signal)
- Order event (order placement)
- Fill event (order execution)
- Market event (market data)
- Other (please describe)"
```

---

## Troubleshooting

### "Request not routed correctly"

**Solution**: Use manual routing
```
/agent {layer}/{module} "specific task"
```

### "Agent asks for more context"

**Agents need**:
- Clear task description
- Acceptance criteria
- Context about why the change is needed

**Example**:
```
❌ "Make EventLoop faster"

✅ "Optimize EventLoop bar processing - currently 1.2s for 1000 bars, target <0.5s"
```

### "Validation failing"

**Check**:
1. Layer validation results (specific errors)
2. Fix issues reported
3. Rerun validation
4. If still failing, ask VALIDATION_ORCHESTRATOR for details

---

## Summary

**For most tasks**: Just describe what you want in natural language
**For precision**: Use `/agent` command
**For quality**: Always validate before committing

The multi-agent system is designed to route intelligently while giving you full control when needed.
