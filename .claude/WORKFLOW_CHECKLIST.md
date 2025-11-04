# Jutsu Labs Workflow Enforcement Checklist

**Purpose**: Quick reference guide ensuring mandatory agent architecture and Serena memory usage

**Version**: 1.0
**Last Updated**: November 2, 2025

---

## 🔴 EVERY SESSION START - Required Steps

### Step 1: Activate Serena Project
```python
mcp__serena__activate_project("Jutsu-Labs")
```
**Why**: Loads project context and makes memories accessible

### Step 2: List Available Memories
```python
mcp__serena__list_memories()
```
**Why**: Shows what knowledge has been preserved from previous sessions

### Step 3: Read Relevant Memories
```python
mcp__serena__read_memory("<memory_name>")
```
**Why**: Retrieves context about modules, past fixes, and project decisions

**Examples**:
- Working on Schwab API? Read `schwab_api_period_fix_2025-11-02`
- Working on EventLoop? Read `eventloop_*` memories
- Starting new feature? Read related module memories

---

## 🔴 EVERY TASK - Mandatory Routing

### Use `/orchestrate` Command for ALL Tasks

**Simple Bug Fix**:
```bash
/orchestrate fix bug in Schwab API, returns 0 bars
```

**Single-Line Change**:
```bash
/orchestrate fix typo in EventLoop docstring at line 45
```

**Feature Implementation**:
```bash
/orchestrate implement trailing stop-loss orders
```

**Analysis**:
```bash
/orchestrate analyze Schwab API reliability
```

**Refactoring**:
```bash
/orchestrate refactor Core layer for performance
```

### What `/orchestrate` Guarantees

✅ **Agent Context Integration**:
- Agent reads its context file from `.claude/layers/.../modules/*_AGENT.md`
- Agent knows its module ownership, responsibilities, dependencies
- Agent enforces architecture boundaries (allowed/forbidden imports)
- Agent applies module-specific patterns and conventions

✅ **Serena Memory System**:
- Serena activated automatically
- Relevant memories read based on task keywords
- New memory written after task completion
- Knowledge preserved across sessions

✅ **Multi-Level Validation**:
- Agent-level: Unit tests, type hints, logging
- Layer-level: Interface compatibility, dependencies
- System-level: Integration tests, end-to-end flow

✅ **Automatic Documentation**:
- CHANGELOG.md updated (Added/Fixed/Changed sections)
- Serena memory written with task details
- Architecture docs kept in sync

---

## 🔴 AGENT CONTEXT VERIFICATION

### Before Starting Work

**Check Agent Context File Exists**:
```bash
# Core Layer
.claude/layers/core/modules/EVENT_LOOP_AGENT.md
.claude/layers/core/modules/PORTFOLIO_AGENT.md
.claude/layers/core/modules/STRATEGY_AGENT.md
.claude/layers/core/modules/EVENTS_AGENT.md

# Application Layer
.claude/layers/application/modules/BACKTEST_RUNNER_AGENT.md
.claude/layers/application/modules/DATA_SYNC_AGENT.md

# Infrastructure Layer
.claude/layers/infrastructure/modules/DATABASE_HANDLER_AGENT.md
.claude/layers/infrastructure/modules/SCHWAB_FETCHER_AGENT.md
.claude/layers/infrastructure/modules/INDICATORS_AGENT.md
.claude/layers/infrastructure/modules/PERFORMANCE_AGENT.md
```

### During Work

**Agent MUST Read Its Context File**:
- ✅ Identity & Purpose
- ✅ Module Ownership (files, tests, configs)
- ✅ Responsibilities (what this agent handles)
- ✅ Allowed Dependencies (what can be imported)
- ✅ Forbidden Dependencies (architecture violations)
- ✅ Patterns & Conventions (how code should be written)
- ✅ Performance Targets (benchmarks to meet)
- ✅ Testing Requirements (coverage, test types)

**Verification Questions**:
- Does agent know what files it owns?
- Does agent enforce dependency rules?
- Does agent follow module-specific patterns?
- Does agent validate performance targets?

---

## 🔴 TASK COMPLETION - Required Steps

### Step 1: Update CHANGELOG.md

**For Bug Fixes**:
```markdown
### Fixed
- **[Module Name]**: Fixed [specific issue]
  - Root cause: [explanation]
  - Resolution: [what was changed]
  - Validation: [how it was tested]
  - Performance: [impact measurements]
```

**For Features**:
```markdown
### Added
- **[Module Name]**: [Feature description]
  - Implementation: [approach details]
  - Performance: [benchmark results]
  - Test coverage: [percentage] ✅
```

**For Refactoring**:
```markdown
### Changed
- **[Module Name]**: [What was improved]
  - Performance improvement: [metrics]
  - Quality improvement: [measurements]
  - Validation: [test results]
```

### Step 2: Write Serena Memory

```python
mcp__serena__write_memory(
    memory_name="<task_description>_<date>",
    content="""
    ## Task: [Brief description]

    ## What Was Done
    - [Action 1]
    - [Action 2]

    ## Files Modified
    - [file1.py]: [changes]
    - [file2.py]: [changes]

    ## Validation Results
    - Tests: [status]
    - Performance: [metrics]
    - Quality: [assessment]

    ## Key Learnings
    - [Insight 1]
    - [Insight 2]

    ## Related Memories
    - [Previous related memory]
    """
)
```

### Step 3: Validation Evidence

**Required Validation**:
- ✅ All tests passing
- ✅ Type checks passing (mypy)
- ✅ Code formatted (black, isort)
- ✅ Performance targets met
- ✅ No architecture violations

**Evidence Format**:
```
Validation Results:
✅ Unit tests: 45/45 passing
✅ Integration tests: 12/12 passing
✅ Type check: No errors
✅ Performance: <0.1ms per operation (target: <1ms)
✅ Test coverage: 94% (target: >80%)
```

### Step 4: Completion Report

**Report Structure**:
```markdown
## Task Completion Report

**Task**: [Description]
**Agent**: [Which agent handled it]
**Status**: ✅ Complete

### Implementation
- [What was done]
- [Files changed]
- [Approach used]

### Validation
[Evidence from Step 3]

### Documentation
- ✅ CHANGELOG.md updated
- ✅ Serena memory written: [memory_name]
- ✅ Agent context preserved

### Next Steps (if any)
- [Follow-up task 1]
- [Follow-up task 2]
```

---

## 🚨 VIOLATION DETECTION

### Red Flags (NEVER Do These)

❌ **Working Without Serena Activation**:
```python
# WRONG: Start coding immediately
# RIGHT: mcp__serena__activate_project("Jutsu-Labs") first
```

❌ **Direct Code Changes Without `/orchestrate`**:
```bash
# WRONG: Edit files directly
# RIGHT: /orchestrate fix bug in [module]
```

❌ **Ignoring Agent Context Files**:
```python
# WRONG: Implement without reading agent context
# RIGHT: Read .claude/layers/.../modules/*_AGENT.md first
```

❌ **Missing Documentation Updates**:
```bash
# WRONG: Fix bug, skip CHANGELOG.md and Serena memory
# RIGHT: Always update both after task completion
```

❌ **Violating Architecture Boundaries**:
```python
# WRONG: Core imports from Application layer
# RIGHT: Follow allowed/forbidden dependencies from agent context
```

### Self-Check Questions

**Before Starting**:
1. Did I activate Serena? (`mcp__serena__activate_project`)
2. Did I read relevant memories? (`mcp__serena__list_memories`)
3. Am I using `/orchestrate` command?

**During Work**:
4. Did the agent read its context file?
5. Is the agent following its module patterns?
6. Are dependency rules being enforced?

**After Completion**:
7. Did I update CHANGELOG.md?
8. Did I write Serena memory?
9. Did I provide validation evidence?
10. Did I create completion report?

---

## 📊 Workflow Quality Metrics

### Session Success Criteria

**100% Required**:
- ✅ Serena activated at session start
- ✅ All tasks routed through `/orchestrate`
- ✅ Agent context files read and used
- ✅ CHANGELOG.md updated for code changes
- ✅ Serena memory written for completed tasks

**80%+ Target**:
- ✅ Test coverage maintained above 80%
- ✅ Performance targets met
- ✅ No architecture violations
- ✅ Type hints on all new code

### Knowledge Preservation Score

**High Quality** (90%+):
- All memories written with comprehensive details
- All context files kept up to date
- All decisions documented in CHANGELOG.md
- All validation evidence provided

**Medium Quality** (70-89%):
- Most memories written, some details missing
- Context files mostly current
- Documentation partially complete

**Low Quality** (<70%):
- Memories missing or incomplete
- Context files outdated
- Documentation gaps

---

## 🔧 Quick Reference Commands

### Serena Operations
```python
# Activate project
mcp__serena__activate_project("Jutsu-Labs")

# List memories
mcp__serena__list_memories()

# Read memory
mcp__serena__read_memory("<memory_name>")

# Write memory
mcp__serena__write_memory(
    memory_name="<name>",
    content="<markdown_content>"
)

# Delete memory (only when outdated)
mcp__serena__delete_memory("<memory_name>")
```

### Orchestration Commands
```bash
# Universal task command
/orchestrate <task_description>

# Implementation
/orchestrate implement layer/core
/orchestrate implement module/portfolio

# Debugging
/orchestrate fix bug in EventLoop, check logs/error.log

# Refactoring
/orchestrate refactor Core layer for performance

# Analysis
/orchestrate analyze system security
```

### Validation Commands
```bash
# Run tests
pytest

# Type check
mypy jutsu_engine/

# Format code
black . && isort .

# Full validation
/validate full
```

---

## 📚 Reference Documents

### Agent System
- `.claude/system/ROUTING_GUIDE.md` - Complete agent routing documentation
- `.claude/system/SYSTEM_ORCHESTRATOR.md` - System-level coordination
- `.claude/commands/orchestrate.md` - `/orchestrate` command specification

### Agent Context Files
- `.claude/layers/core/CORE_ORCHESTRATOR.md` - Core layer coordination
- `.claude/layers/core/modules/*_AGENT.md` - Core module agents
- `.claude/layers/application/modules/*_AGENT.md` - Application module agents
- `.claude/layers/infrastructure/modules/*_AGENT.md` - Infrastructure module agents

### Project Documentation
- `.claude/CLAUDE.md` - Main project context
- `docs/SYSTEM_DESIGN.md` - Architecture and design decisions
- `docs/BEST_PRACTICES.md` - Coding standards and conventions
- `CHANGELOG.md` - All changes and updates

---

## ✅ Success Checklist Template

**Copy this for every task**:

```markdown
## Task: [Description]

### Session Start
- [ ] Activated Serena project
- [ ] Listed available memories
- [ ] Read relevant memories for this task

### Task Execution
- [ ] Used `/orchestrate` command
- [ ] Agent read its context file
- [ ] Agent followed module patterns
- [ ] Agent enforced dependency rules

### Validation
- [ ] All tests passing
- [ ] Type checks passing
- [ ] Code formatted
- [ ] Performance targets met
- [ ] No architecture violations

### Documentation
- [ ] CHANGELOG.md updated
- [ ] Serena memory written
- [ ] Completion report created
- [ ] Validation evidence provided

### Quality Metrics
- [ ] Test coverage >80%
- [ ] All context files current
- [ ] Knowledge preserved
- [ ] Evidence-based completion
```

---

**Remember**: This workflow is MANDATORY for ALL work on Jutsu-Labs. No exceptions, even for simple 1-line changes. The agent architecture and Serena memory system are the foundation of knowledge preservation and quality assurance.
