---
name: orchestrate
description: "MANDATORY for ALL Jutsu-Labs tasks - Universal autonomous orchestration with agent context and Serena memories"
category: utility
complexity: advanced
mcp-servers: ["sequential-thinking", "context7", "serena", "morphllm-fast-apply"]
personas: ["architect", "analyzer"]
---

# /orchestrate - Universal Autonomous Orchestration System

**🔴 MANDATORY**: Use this command for **ALL** work on Jutsu-Labs - from simple bug fixes to complex features.

Fully autonomous multi-agent orchestration using hierarchical agent structure, full SuperClaude MCP integration, agent context files, Serena project memories, and automatic CHANGELOG.md updates.

## ⚠️ Pre-Flight Checklist (MANDATORY)

**Before executing `/orchestrate`, verify:**

### Session Start (First orchestrate of session)
- [ ] Have I read `.claude/WORKFLOW_GUARD.md` this session?
- [ ] Do I understand the mandatory workflow requirement?
- [ ] Am I ready to NEVER use Edit/Write/MultiEdit directly?

### Task Clarity
- [ ] Is the task description clear and specific?
- [ ] Do I know which layer/module this affects?
- [ ] Have I checked for similar past fixes in Serena memories?

### Workflow Commitment
- [ ] Am I committed to routing through orchestrators?
- [ ] Will I let agents read their context files?
- [ ] Will I trust the agent architecture?

**If all checked ✅, proceed with `/orchestrate <description>`**

---

## Purpose

**Primary Command for ALL Tasks** - Replaces direct code editing:

### What This Command Does Automatically

**1. Agent Context Integration**:
- ✅ Reads agent context files from `.claude/layers/.../modules/*_AGENT.md`
- ✅ Loads module ownership, responsibilities, dependencies
- ✅ Enforces architecture boundaries (allowed/forbidden imports)
- ✅ Applies module-specific patterns and conventions
- ✅ Uses performance targets and testing requirements

**2. Serena Memory System**:
- ✅ Activates Serena project (`Jutsu-Labs`)
- ✅ Lists available memories
- ✅ Reads relevant memories based on task keywords
- ✅ Writes new memory after task completion
- ✅ Preserves knowledge across sessions

**3. Task Execution** (Handles EVERYTHING):
- ✅ **Simple Fixes**: 1-line changes, typos, quick edits
- ✅ **Bug Fixes**: Debug and fix with root cause analysis
- ✅ **Implementation**: Create modules/layers/systems from specs
- ✅ **Refactoring**: Improve code quality and performance
- ✅ **Analysis**: Comprehensive system/security/quality analysis
- ✅ **Optimization**: Performance improvements and bottleneck elimination

**4. Automatic Documentation**:
- ✅ CHANGELOG.md updated after every change (Added/Fixed/Changed)
- ✅ README.md updated for major features
- ✅ Serena memory written for future reference
- ✅ Architecture docs kept in sync

**5. Multi-Level Validation**:
- ✅ Agent-level: Unit tests, type hints, logging
- ✅ Layer-level: Interface compatibility, dependencies
- ✅ System-level: Integration tests, end-to-end flow

### Why Use This for Everything (Even Simple Tasks)

**Agent Context = Module Expertise**:
- Each agent knows its module deeply (from context files)
- Patterns, conventions, dependencies already documented
- Performance targets and quality standards enforced
- Past issues and solutions remembered

**Serena Memories = Project History**:
- Previous fixes and decisions preserved
- Cross-session continuity maintained
- Same bugs don't recur
- Best practices accumulate over time

**Examples**:
```bash
# Simple 1-line fix (Still uses agent context!)
/orchestrate fix typo in EventLoop docstring at line 45

# Bug fix (Agent reads logs + context + memories)
/orchestrate fix bug in Schwab API, returns 0 bars

# Complex feature (Multi-agent coordination)
/orchestrate implement trailing stop-loss orders

# Analysis (No code changes, just reporting)
/orchestrate analyze Schwab API reliability
```

---

## 📊 Visible Workflow Output

**What You'll See During Execution:**

### Phase 1: Initialization (0-5 seconds)
```
🔄 [ORCHESTRATOR] Initializing workflow...
📚 [SERENA] Activating project: Jutsu-Labs
📝 [SERENA] Reading memories: schwab_api_fixes, portfolio_patterns
✅ [ORCHESTRATOR] Context loaded, planning execution...
```

### Phase 2: Planning (5-15 seconds)
```
🧠 [SEQUENTIAL] Analyzing task: "fix bug in Schwab API"
📂 [ORCHESTRATOR] Task type: DEBUG
🎯 [ORCHESTRATOR] Routing: SYSTEM → INFRASTRUCTURE → SCHWAB_FETCHER_AGENT
📋 [ORCHESTRATOR] Creating TodoList: 4 steps
  ✅ 1. Read SCHWAB_FETCHER_AGENT.md
  🔄 2. Analyze logs and code
  ⏳ 3. Implement fix
  ⏳ 4. Validate and document
```

### Phase 3: Agent Activation (15-30 seconds)
```
🤖 [SCHWAB_FETCHER_AGENT] Activated
📖 [AGENT] Reading context: .claude/layers/infrastructure/modules/SCHWAB_FETCHER_AGENT.md
✅ [AGENT] Context loaded: Module ownership, patterns, constraints
🔍 [AGENT] Reading logs: logs/jutsu_engine_data.log
🧠 [AGENT] Analyzing with Sequential MCP...
```

### Phase 4: Execution (30 seconds - 5 minutes)
```
🔨 [AGENT] Root cause identified: Parameter conflict in API call
📝 [AGENT] Implementing fix: schwab.py:279-284
🧪 [AGENT] Running tests: pytest tests/unit/infrastructure/test_schwab_fetcher.py
✅ [AGENT] Tests passing: 23/23 (100%)
```

### Phase 5: Validation (5-10 seconds)
```
✅ [INFRASTRUCTURE_ORCHESTRATOR] Layer validation: PASSED
  ✅ Interface compatibility: OK
  ✅ Dependency rules: OK
  ✅ Performance targets: OK (2 requests/sec maintained)
  ✅ Test coverage: 91% (target: >80%)
```

### Phase 6: Documentation (10-20 seconds)
```
📝 [DOCUMENTATION_ORCHESTRATOR] Updating CHANGELOG.md...
✅ [CHANGELOG] Added: Fixed section with root cause and resolution
💾 [SERENA] Writing memory: schwab_api_period_fix_2025-11-02
✅ [SERENA] Memory written successfully
```

### Phase 7: Completion Report
```
═══════════════════════════════════════════════════════════
✅ ORCHESTRATION COMPLETE

Task: Fix bug in Schwab API
Status: ✅ RESOLVED
Duration: 3m 45s

Changes:
  - schwab.py:279-284 (API call fix)
  - test_schwab_fetcher.py:145-150 (test updates)

Validation:
  ✅ 23/23 tests passing
  ✅ 6,288 bars retrieved (MSFT)
  ✅ Layer validation: PASSED
  ✅ Performance: 2 req/sec maintained

Documentation:
  ✅ CHANGELOG.md: Fixed section updated
  ✅ Serena memory: schwab_api_period_fix_2025-11-02

Next Steps:
  - Review changes in schwab.py
  - Test with other symbols if needed
  - Commit when ready
═══════════════════════════════════════════════════════════
```

### Progress Indicators

**TodoWrite Updates (Real-Time)**:
```
[1/4] ✅ Read agent context
[2/4] 🔄 Analyze code and logs...
[3/4] ⏳ Implement fix
[4/4] ⏳ Validate and document
```

**Agent Status Markers**:
- 🔄 = In Progress
- ✅ = Completed
- ⏳ = Pending
- ❌ = Failed
- ⚠️ = Warning

---

## Usage

```bash
/orchestrate <task_description> [--options]
```

## Task Types (Auto-Detected)

The orchestrator automatically detects task type from your description:

### Implementation
```bash
/orchestrate implement layer/core
/orchestrate implement system
/orchestrate implement module/portfolio
/orchestrate create Events module
```

**Workflow:**
1. Read hierarchical agent structure (.claude/)
2. Analyze dependencies
3. Spawn Task agents (with MCP access)
4. Validate implementation
5. Update CHANGELOG.md
6. Report completion

### Debugging
```bash
/orchestrate fix bug in EventLoop, check logs/error.log
/orchestrate debug performance issue in Portfolio
/orchestrate investigate error in logs/jutsu_engine.log
```

**Workflow:**
1. Read logs and error messages
2. Analyze code using agent specs
3. Spawn analyzer Task agent (with Sequential MCP)
4. Identify root cause
5. Spawn fix Task agent
6. Validate fix
7. Update CHANGELOG.md (Fixed section)
8. Report resolution

### Refactoring
```bash
/orchestrate refactor Core layer for better performance
/orchestrate cleanup code in Portfolio module
/orchestrate improve EventLoop architecture
```

**Workflow:**
1. Read existing code
2. Analyze patterns and issues
3. Spawn refactoring Task agents
4. Validate improvements
5. Update CHANGELOG.md (Changed section)
6. Report improvements

### Analysis
```bash
/orchestrate analyze system security
/orchestrate review architecture quality
/orchestrate audit code standards
```

**Workflow:**
1. Read relevant agent specs
2. Spawn specialized analyzer Task agents
3. Generate comprehensive report
4. No changelog update (analysis only)

### Optimization
```bash
/orchestrate optimize Portfolio module performance
/orchestrate speed up EventLoop processing
```

**Workflow:**
1. Profile current performance
2. Identify bottlenecks
3. Spawn optimization Task agents
4. Validate performance improvements
5. Update CHANGELOG.md (Changed section)
6. Report metrics

## Scope Levels

### System Level (All Layers)
```bash
/orchestrate implement system
```
Implements: Core → Application → Infrastructure → Entry Points

### Layer Level
```bash
/orchestrate implement layer/core
/orchestrate implement layer/application
/orchestrate implement layer/infrastructure
```
Implements all modules in specified layer

### Module Level
```bash
/orchestrate implement module/portfolio
/orchestrate implement module/event-loop
```
Implements single module

### Custom
```bash
/orchestrate fix bug in EventLoop
/orchestrate analyze security
```
Handles any custom task description

## Options

### --focus
Focus optimization on specific aspect:
```bash
/orchestrate refactor layer/core --focus performance
/orchestrate refactor layer/core --focus security
/orchestrate refactor layer/core --focus quality
```

### --safe
Enable extra validation and safety checks:
```bash
/orchestrate implement system --safe
```

### --with-tests
Emphasize comprehensive testing:
```bash
/orchestrate implement module/portfolio --with-tests
```

## MCP Integration (Automatic)

### Orchestrator Level (Claude Code)
Every orchestration uses FULL SuperClaude MCP:

**📝 TodoWrite**
- Tracks progress across all phases
- Updates status as layers/modules complete
- Visual progress for user

**🧠 Sequential MCP**
- Task decomposition and planning
- Dependency analysis
- Complex decision making

**📚 Context7 MCP**
- Framework patterns and best practices
- Library documentation lookup
- Official patterns for implementation

**💾 Serena MCP**
- Checkpoint/resume functionality
- Project memory management
- Cross-session persistence

**🔧 Morphllm MCP**
- Large-scale code analysis
- Pattern-based transformations

### Task Agent Level
All Task agents get FULL MCP access:

```python
# Every Task agent spawned as:
Task("Implement Portfolio", {
  subagent_type: "general-purpose",  # ← ALL MCP servers!
  prompt: """
  You have full MCP access:
  - Context7: Look up patterns
  - Sequential: Complex analysis
  - Serena: Read project memories

  Implement Portfolio module...
  """
})
```

## Documentation Updates (Automatic)

### CHANGELOG.md
**After every operation**, DOCUMENTATION_ORCHESTRATOR updates CHANGELOG.md:

**Implementation:**
```markdown
### Added
- **Portfolio Module**: State management and trade execution
  - Position tracking with Decimal precision
  - Commission and slippage modeling
  - Performance: <0.1ms per order ✅
  - Test coverage: 91% ✅
```

**Bug Fix:**
```markdown
### Fixed
- **EventLoop Module**: Fixed performance degradation
  - Root cause: Memory loading issue
  - Resolution: Generator pattern implementation
  - Performance improvement: 3x faster
```

**Refactoring:**
```markdown
### Changed
- **Core Layer**: Performance optimization
  - EventLoop: Reduced processing time by 40%
  - Portfolio: Optimized position tracking
  - Overall: <1ms per bar maintained ✅
```

### Other Documentation
- **README.md**: Updated for major features
- **SYSTEM_DESIGN.md**: Updated for architecture changes
- **API_REFERENCE.md**: Updated for interface changes

## Examples

### Example 1: Implement Core Layer
```bash
/orchestrate implement layer/core
```

**Execution (~15 min):**
```
┌─────────────────────────────────────┐
│ ORCHESTRATOR: TodoWrite + Sequential│
│ ✅ Plan: 4 modules, 2 waves         │
│ ✅ Read: CORE_ORCHESTRATOR.md       │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ WAVE 1: Events (no dependencies)    │
│ Task("Events", with MCP access)     │
│ ✅ events.py + tests (96% coverage) │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ WAVE 2: EventLoop, Portfolio, Strategy│
│ (PARALLEL execution)                │
│ ✅ All 3 modules complete           │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ VALIDATION: Layer-level checks      │
│ ✅ Interfaces compatible            │
│ ✅ Performance targets met          │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ DOCUMENTATION: Auto-update          │
│ ✅ CHANGELOG.md: Added 4 modules    │
│ ✅ README.md: Updated features      │
└─────────────────────────────────────┘
         ↓
✅ Core layer complete (83 tests, 94% coverage)
```

### Example 2: Debug Bug
```bash
/orchestrate fix bug in EventLoop, check logs/error.log
```

**Execution (~5 min):**
```
┌─────────────────────────────────────┐
│ ORCHESTRATOR: TodoWrite + Sequential│
│ ✅ Read: logs/error.log             │
│ ✅ Read: EVENT_LOOP_AGENT.md        │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ ANALYZER AGENT: Root cause analysis │
│ Uses Sequential MCP for diagnosis   │
│ ✅ Identified: Memory loading issue │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ FIX AGENT: Implement solution       │
│ Uses Context7 for Python patterns   │
│ ✅ Implemented: Generator pattern   │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ VALIDATION: Test suite              │
│ ✅ All tests passing                │
│ ✅ Performance improved 3x          │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ DOCUMENTATION: Auto-update          │
│ ✅ CHANGELOG.md: Fixed section      │
│ ✅ Serena: write_memory bug fix     │
└─────────────────────────────────────┘
         ↓
✅ Bug fixed (18/18 tests passing, 3x faster)
```

### Example 3: Full System Implementation
```bash
/orchestrate implement system
```

**Execution (~60 min):**
```
Layer 1: Core (15 min)
  Wave 1: Events
  Wave 2: EventLoop, Portfolio, Strategy (parallel)
  ✅ 4 modules, 83 tests, 94% coverage

Layer 2: Application (10 min)
  Wave 1: BacktestRunner, DataSync (parallel)
  ✅ 2 modules, 27 tests, 89% coverage

Layer 3: Infrastructure (15 min)
  Wave 1: DatabaseHandler, SchwabFetcher, Indicators, Performance (parallel)
  ✅ 4 modules, 70 tests, 91% coverage

Layer 4: Entry Points (10 min)
  Wave 1: CLI
  ✅ 1 module, 10 tests, 88% coverage

System Integration (10 min)
  ✅ 12 integration tests
  ✅ 2 example scripts

Documentation Update
  ✅ CHANGELOG.md: 11 modules added
  ✅ README.md: Full feature set
  ✅ API_REFERENCE.md: Complete API docs

✅ Full MVP complete (190 tests, 92% coverage)
```

## Status & Resume

### Check Progress
```bash
/orchestrate status
```

Returns:
```
Orchestration in progress:
  Task: implement system
  Layer: Core (75% complete)
    ✅ Events (completed)
    ✅ EventLoop (completed)
    ✅ Portfolio (completed)
    🔄 Strategy (in progress)

  Next: Application layer
  Estimated: 20 min remaining
```

### Resume After Interruption
```bash
/orchestrate resume
```

Reads Serena checkpoint and continues from last incomplete task.

## Performance

### Targets
- **Command startup**: <100ms
- **Planning phase**: <500ms
- **Per module**: 2-5 min
- **Per layer**: 10-20 min
- **Full system**: 60-90 min

### Parallelization
- Modules within layer: **PARALLEL**
- Layers: **SEQUENTIAL** (dependency order)
- Task agents: **CONCURRENT**

## Integration with Existing Agents

Uses ALL existing agent structure:
- ✅ SYSTEM_ORCHESTRATOR.md
- ✅ Layer orchestrators (CORE, APPLICATION, INFRASTRUCTURE)
- ✅ Module agents (all 11 created)
- ✅ Cross-cutting orchestrators (LOGGING, VALIDATION, DOCUMENTATION)

## Quality Gates

Automatic validation at multiple levels:
1. **Module-level**: Unit tests, type hints, logging
2. **Layer-level**: Interface compatibility, dependencies
3. **System-level**: Integration tests, end-to-end flow
4. **Documentation**: CHANGELOG.md, README.md sync

## Error Handling

### Retry Logic
- Module implementation fails → retry with error context
- Still fails → report and stop

### Validation Failures
- Validation fails → spawn fix agents
- Re-validate → repeat until clean

### Graceful Degradation
- MCP timeout → use fallback methods
- Task agent failure → detailed error report

## Benefits

✅ **Universal**: Handles ANY task (implement, debug, refactor, analyze)
✅ **Autonomous**: Zero manual intervention
✅ **Intelligent**: Full MCP integration at all levels
✅ **Documented**: Automatic CHANGELOG.md updates
✅ **Hierarchical**: Respects existing agent structure
✅ **Parallel**: Maximum efficiency
✅ **Resumable**: Checkpoint/resume capability
✅ **Validated**: Multi-level quality gates

---

## Quick Reference

**Syntax**: `/orchestrate <task_description> [--options]`

**Task Types**: implement, debug, refactor, analyze, optimize (auto-detected)

**Scope**: system | layer/<name> | module/<name> | custom

**MCP**: TodoWrite, Sequential, Context7, Serena, Morphllm (automatic)

**Documentation**: CHANGELOG.md, README.md, SYSTEM_DESIGN.md (automatic)

**Time**: ~60 min for full system, ~15 min per layer, ~3 min per module

**Quality**: Multi-level validation, >90% test coverage target

---

## Summary

The `/orchestrate` command is a universal autonomous orchestration system that can handle ANY development task. It automatically detects task type, uses the hierarchical agent structure, gives full MCP access to all agents, and updates CHANGELOG.md after every operation. Whether implementing entire systems, debugging specific issues, refactoring for performance, or analyzing security - one command does it all, fully autonomously, with complete documentation.

**Your productivity multiplier - type one command, get production-ready implementation with tests and docs.**
