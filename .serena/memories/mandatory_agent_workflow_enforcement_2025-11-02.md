# Mandatory Agent Workflow Enforcement Documentation Updates

**Date**: 2025-11-02
**Context**: User identified that agent architecture and Serena memory system weren't being used in previous Schwab API bug fix session

---

## Problem Identified

During Schwab API debugging (fixing "0 bars returned" issue), work was performed **without**:
1. ✅ Activating Serena project
2. ✅ Reading existing project memories
3. ✅ Using agent hierarchy (INFRASTRUCTURE_ORCHESTRATOR → SCHWAB_FETCHER_AGENT)
4. ✅ Routing through agent context files (`.claude/layers/.../modules/*_AGENT.md`)
5. ✅ Writing memories after completion

**Root Cause**: SuperClaude framework treated agent architecture as **opt-in** for complex tasks, but user expects it to be **mandatory for ALL tasks** (including simple bug fixes).

---

## Solution: Documentation Updates

Updated 4 core files to enforce mandatory agent architecture workflow:

### 1. `.claude/CLAUDE.md`

**Changes Made**:
- Rewrote "Working with Claude Code" section (lines 958-1203)
- Added **MANDATORY WORKFLOW** header
- Documented Session Start Protocol:
  ```python
  mcp__serena__activate_project("Jutsu-Labs")
  mcp__serena__list_memories()
  mcp__serena__read_memory("<relevant_memory>")
  ```
- Made `/orchestrate` command universal for ALL tasks
- Explained automatic agent context file usage
- Provided examples (bug fix, feature implementation)
- Listed all agents by layer with expertise

**Key Section Added**:
```markdown
### Universal Task Execution (REQUIRED - All Tasks)
**Use `/orchestrate` for EVERYTHING**:
- Bug fixes
- Features
- Analysis
- Refactoring
- Optimization
```

### 2. `.claude/system/ROUTING_GUIDE.md`

**Changes Made**:
- Added "🔴 MANDATORY: Agent Routing for ALL Tasks" section at top (lines 1-120)
- Documented why agent context files are critical
- Explained consequences of not using agent routing
- Defined 5 routing rules:
  1. ALL tasks route through agents (even 1-line fixes)
  2. Agents ALWAYS read their context files
  3. Context files are source of truth for module expertise
  4. Serena memories supplement agent context
  5. Validation at agent, layer, system levels
- Updated version to 2.0
- Updated date to November 2, 2025

**Key Sections**:
- Without Agent Routing: Lists 6 problems
- With Agent Routing: Lists 6 benefits
- Universal Command: `/orchestrate` for everything

### 3. `.claude/commands/orchestrate.md`

**Changes Made**:
- Updated description to "MANDATORY for ALL Jutsu-Labs tasks"
- Added "Agent Context Integration" section
- Added "Serena Memory System" section
- Emphasized use for simple tasks (even 1-line fixes)
- Documented what orchestrate does automatically:
  1. Agent context file reading
  2. Serena activation and memory reading
  3. Multi-level validation
  4. CHANGELOG.md updates
  5. Memory writing

**Key Addition**:
```markdown
**3. Task Execution** (Handles EVERYTHING):
- ✅ **Simple Fixes**: 1-line changes, typos, quick edits
- ✅ **Bug Fixes**: Debug and fix with root cause analysis
- ✅ **Implementation**: Create modules/layers/systems from specs
```

### 4. `.claude/WORKFLOW_CHECKLIST.md` (NEW)

**Created**: Complete workflow enforcement reference guide

**Sections**:
1. **Every Session Start**: 3-step Serena activation protocol
2. **Every Task**: `/orchestrate` command usage for ALL tasks
3. **Agent Context Verification**: Before, during work
4. **Task Completion**: 4-step completion protocol
5. **Violation Detection**: Red flags and self-check questions
6. **Workflow Quality Metrics**: Success criteria
7. **Quick Reference Commands**: Serena, orchestration, validation
8. **Success Checklist Template**: Copy-paste for every task

**Key Features**:
- Quick reference format (checklists, examples)
- Red flag detection system
- Self-check questions
- Quality metrics
- Evidence requirements
- Completion criteria

---

## Key Principles Enforced

### 1. Agent Context Files Are Source of Truth

**Agent Context Files** (`.claude/layers/.../modules/*_AGENT.md`) contain:
- Identity & Purpose
- Module Ownership (files, tests, configs)
- Responsibilities (what this agent handles)
- Allowed/Forbidden Dependencies (architecture enforcement)
- Patterns & Conventions (how code should be written)
- Performance Targets (benchmarks to meet)
- Testing Requirements (coverage, test types)
- Known Issues & Solutions (past fixes)

### 2. Serena Memories Supplement Agent Context

**Project Memories** preserve:
- Past fixes and root causes
- Decisions and rationale
- Performance improvements
- Architecture evolution
- Cross-session continuity

### 3. Multi-Level Validation

**Three-tier validation**:
- **Agent-level**: Unit tests, type hints, logging
- **Layer-level**: Interface compatibility, dependencies
- **System-level**: Integration tests, end-to-end flow

### 4. Automatic Documentation

**Every task completion**:
- CHANGELOG.md updated (Added/Fixed/Changed)
- Serena memory written
- Completion report with evidence

---

## Workflow Changes

### Before (Incorrect)

```
User: "Schwab API returns 0 bars"
Claude: *directly edits schwab.py*
Claude: *writes CHANGELOG.md manually*
Claude: *forgets Serena memory*
```

**Problems**:
- ❌ No agent context used
- ❌ Module expertise not applied
- ❌ Dependencies not validated
- ❌ Knowledge not preserved

### After (Correct)

```bash
/orchestrate fix bug in Schwab API, returns 0 bars

# Automatic Execution:
# 1. Serena activated
# 2. Reads schwab_* memories
# 3. Routes to INFRASTRUCTURE_ORCHESTRATOR
# 4. Delegates to SCHWAB_FETCHER_AGENT
# 5. Agent reads: .claude/layers/infrastructure/modules/SCHWAB_FETCHER_AGENT.md
# 6. Agent uses domain expertise
# 7. Fix implemented with validation
# 8. CHANGELOG.md updated automatically
# 9. Memory written: schwab_api_period_fix_2025-11-02
# 10. Report: Evidence and results
```

**Benefits**:
- ✅ Agent context applied
- ✅ Module expertise used
- ✅ Dependencies validated
- ✅ Knowledge preserved

---

## Files Modified

1. `.claude/CLAUDE.md` - Main project context
2. `.claude/system/ROUTING_GUIDE.md` - Agent routing documentation
3. `.claude/commands/orchestrate.md` - `/orchestrate` command spec
4. `.claude/WORKFLOW_CHECKLIST.md` - Enforcement reference guide (NEW)

---

## Impact

### Immediate

**For ALL future work**:
- Every session must activate Serena
- Every task must use `/orchestrate`
- Every agent must read its context file
- Every completion must update docs and memory

### Long-term

**Knowledge Accumulation**:
- Context files become richer over time
- Serena memories preserve institutional knowledge
- Same bugs don't recur
- Patterns become consistent

**Quality Improvement**:
- Architecture boundaries enforced
- Performance targets validated
- Testing requirements met
- Documentation always current

**Efficiency Gains**:
- Agents work in parallel
- Specialized expertise applied
- Context preserved across sessions
- Faster implementation with validation

---

## Related Memories

- `schwab_api_period_fix_2025-11-02` - Bug fix that triggered this enforcement update
- Future: All task memories will reference agent context usage

---

## Usage Guidelines

### For Every Session

1. Read this memory at session start
2. Follow Session Start Protocol (Serena activation)
3. Use `/orchestrate` for ALL tasks
4. Verify agent context usage
5. Complete Task Completion Protocol

### For Every Task

1. Route through `/orchestrate`
2. Agent reads its context file
3. Agent applies domain expertise
4. Multi-level validation
5. CHANGELOG.md + memory updates

### Enforcement

**Self-check before starting work**:
- Did I activate Serena?
- Am I using `/orchestrate`?
- Will the agent read its context file?

**Self-check before completing**:
- Did I update CHANGELOG.md?
- Did I write Serena memory?
- Did I provide validation evidence?

---

## Key Learnings

1. **Agent architecture is not optional** - It's the foundation of quality and knowledge preservation
2. **Context files contain domain expertise** - They're not just documentation, they're operational knowledge
3. **Serena memories enable continuity** - Cross-session knowledge prevents repeated mistakes
4. **Automation ensures compliance** - `/orchestrate` handles workflow automatically
5. **Documentation is mandatory** - CHANGELOG.md and memories are not optional

---

## Next Steps

**For future development**:
1. All work must follow this enforced workflow
2. Agent context files should be kept current
3. Serena memories written for every task
4. WORKFLOW_CHECKLIST.md used as reference
5. Violations corrected immediately

**For workflow improvements**:
1. Monitor compliance via self-checks
2. Update enforcement docs as needed
3. Add more examples to checklist
4. Refine agent context templates
5. Expand Serena memory coverage
