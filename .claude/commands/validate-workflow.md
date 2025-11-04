---
name: validate-workflow
description: "Validate compliance with Jutsu-Labs agent architecture workflow and enforcement mechanisms"
category: utility
complexity: simple
mcp-servers: ["serena"]
personas: ["analyzer"]
---

# /validate-workflow - Workflow Compliance Validation

**Purpose**: Validate that the Jutsu-Labs agent architecture workflow has been followed correctly and identify any bypasses or violations.

## What This Command Does

**Compliance Checks**:
1. ✅ Verifies WORKFLOW_GUARD.md has been read this session
2. ✅ Checks that all code changes went through `/orchestrate`
3. ✅ Validates agent context files were loaded
4. ✅ Confirms CHANGELOG.md was updated
5. ✅ Verifies Serena memories were written
6. ✅ Checks multi-level validation occurred

**Violation Detection**:
- ❌ Direct Edit/Write/MultiEdit usage (bypassing orchestration)
- ❌ Missing CHANGELOG.md updates
- ❌ Missing Serena memory writes
- ❌ Agent context files not read
- ❌ Validation steps skipped

## Usage

```bash
# Validate current session
/validate-workflow

# Validate specific task
/validate-workflow --task "schwab api fix"

# Comprehensive validation
/validate-workflow --comprehensive
```

## Validation Levels

### Basic Validation (Default)
```bash
/validate-workflow
```

**Checks:**
- [ ] WORKFLOW_GUARD.md acknowledgment
- [ ] Recent orchestrate command usage
- [ ] CHANGELOG.md recent updates
- [ ] Serena memory writes

**Output:**
```
═══════════════════════════════════════════════════════════
🛡️ WORKFLOW COMPLIANCE VALIDATION

Session: 2025-11-02 14:30:00
Mode: BASIC

Checks:
  ✅ WORKFLOW_GUARD.md: Read this session
  ✅ Orchestration: Last command used /orchestrate
  ✅ CHANGELOG.md: Updated 5 minutes ago
  ✅ Serena memories: Written 5 minutes ago

Status: ✅ COMPLIANT
═══════════════════════════════════════════════════════════
```

### Task-Specific Validation
```bash
/validate-workflow --task "schwab api fix"
```

**Checks:**
- [ ] Task routed through `/orchestrate`
- [ ] Agent context file read (SCHWAB_FETCHER_AGENT.md)
- [ ] CHANGELOG.md updated with task details
- [ ] Serena memory written with task context
- [ ] Tests validated
- [ ] Layer validation performed

**Output:**
```
═══════════════════════════════════════════════════════════
🛡️ TASK COMPLIANCE VALIDATION

Task: "schwab api fix"
Date: 2025-11-02 14:25:00

Workflow Compliance:
  ✅ Routed via: /orchestrate fix bug in Schwab API
  ✅ Agent activated: SCHWAB_FETCHER_AGENT
  ✅ Context loaded: .claude/.../SCHWAB_FETCHER_AGENT.md
  ✅ CHANGELOG.md: Fixed section added
  ✅ Serena memory: schwab_api_period_fix_2025-11-02

Validation Gates:
  ✅ Agent-level: 23/23 tests passing
  ✅ Layer-level: Infrastructure validation PASSED
  ✅ System-level: N/A (single module)

Status: ✅ FULLY COMPLIANT
═══════════════════════════════════════════════════════════
```

### Comprehensive Validation
```bash
/validate-workflow --comprehensive
```

**Checks:**
- [ ] All session activity review
- [ ] Git commit history analysis
- [ ] File modification patterns
- [ ] Agent activation history
- [ ] Documentation synchronization
- [ ] Memory accumulation patterns

**Output:**
```
═══════════════════════════════════════════════════════════
🛡️ COMPREHENSIVE WORKFLOW VALIDATION

Session: 2025-11-02 (Full Day)
Analysis: Last 10 operations

Operations Analysis:
  Total operations: 10
  Via /orchestrate: 10 (100%) ✅
  Direct edits: 0 (0%) ✅

Agent Activation:
  SCHWAB_FETCHER_AGENT: 3 times ✅
  EVENT_LOOP_AGENT: 2 times ✅
  PORTFOLIO_AGENT: 2 times ✅
  Context files read: 7/7 (100%) ✅

Documentation Sync:
  CHANGELOG.md updates: 10/10 (100%) ✅
  Serena memories: 10/10 (100%) ✅
  README.md sync: 2/2 (100%) ✅

Validation Gates:
  Agent-level: 100% passed ✅
  Layer-level: 100% passed ✅
  System-level: 100% passed ✅

Git History:
  Commits: 8
  All via agent workflow: 8/8 (100%) ✅
  Documentation included: 8/8 (100%) ✅

Status: ✅ EXCELLENT COMPLIANCE
Recommendation: Continue current workflow
═══════════════════════════════════════════════════════════
```

## Violation Detection & Reporting

### When Violations Found
```
═══════════════════════════════════════════════════════════
⚠️ WORKFLOW VIOLATIONS DETECTED

Session: 2025-11-02 14:30:00

Violations:
  ❌ Direct Edit usage: schwab.py (14:22:00)
    - Bypassed: /orchestrate command
    - Missing: Agent context loading
    - Missing: CHANGELOG.md update
    - Missing: Serena memory write

  ❌ Missing validation: Portfolio module (14:25:00)
    - Tests not run
    - Layer validation skipped

Compliance Score: 70% (7/10 checks passed)

Impact:
  - Context loss: Agent patterns not applied
  - Documentation gap: Changes not documented
  - Memory loss: Future sessions won't benefit
  - Validation gap: Quality not verified

Remediation:
  1. Review direct edits in schwab.py
  2. Re-apply via: /orchestrate fix schwab.py using agent context
  3. Run validation: pytest tests/unit/infrastructure/test_schwab_fetcher.py
  4. Update CHANGELOG.md manually or re-apply via orchestrate
  5. Write Serena memory: schwab_fix_context_2025-11-02

Status: ⚠️ VIOLATIONS REQUIRE REMEDIATION
═══════════════════════════════════════════════════════════
```

## Metrics Tracked

### Orchestration Usage
- **Target**: 100%
- **Measurement**: (orchestrate commands / total code changes) × 100

### Agent Context Reads
- **Target**: 100%
- **Measurement**: (agent context reads / agent activations) × 100

### Documentation Sync
- **Target**: 100%
- **Measurement**: (CHANGELOG updates / code changes) × 100

### Memory Accumulation
- **Target**: 100%
- **Measurement**: (Serena writes / completed tasks) × 100

### Validation Coverage
- **Target**: 100%
- **Measurement**: (validation gates passed / total gates) × 100

## Integration with Development Workflow

### Before Commit
```bash
/validate-workflow --comprehensive
git status
git diff
# If validation passes:
git add .
git commit -m "..."
git push
```

### After Long Session
```bash
/validate-workflow --comprehensive
# Review compliance score
# Remediate any violations
# Ensure all changes documented
```

### Daily/Weekly Review
```bash
/validate-workflow --comprehensive --period week
# Track compliance trends
# Identify improvement areas
# Celebrate excellent compliance
```

## Compliance Scoring

### Excellent (90-100%)
```
Status: ✅ EXCELLENT COMPLIANCE
Recommendation: Continue current workflow
```

### Good (75-89%)
```
Status: ✅ GOOD COMPLIANCE
Recommendation: Minor improvements suggested
```

### Needs Improvement (60-74%)
```
Status: ⚠️ NEEDS IMPROVEMENT
Recommendation: Review workflow practices
```

### Poor (<60%)
```
Status: ❌ POOR COMPLIANCE
Recommendation: IMMEDIATE REMEDIATION REQUIRED
```

## Options

### --task
Validate specific task by description:
```bash
/validate-workflow --task "schwab api fix"
```

### --comprehensive
Run full compliance analysis:
```bash
/validate-workflow --comprehensive
```

### --period
Analyze specific time period:
```bash
/validate-workflow --period today
/validate-workflow --period week
/validate-workflow --period month
```

### --fix
Auto-generate remediation steps:
```bash
/validate-workflow --fix
```

Output:
```
Remediation Plan:
1. Re-apply direct edits via /orchestrate
2. Generate missing CHANGELOG.md entries
3. Write missing Serena memories
4. Run skipped validation gates

Execute remediation? [y/N]
```

## Benefits

✅ **Quality Assurance**: Ensures workflow compliance
✅ **Early Detection**: Catches violations immediately
✅ **Trend Analysis**: Tracks compliance over time
✅ **Remediation Guidance**: Clear steps to fix issues
✅ **Accountability**: Visible compliance metrics
✅ **Continuous Improvement**: Identifies patterns and areas for improvement

## When to Use

**Mandatory**:
- Before committing changes
- After complex multi-file operations
- End of development session

**Recommended**:
- After each `/orchestrate` execution
- Before creating pull requests
- Daily/weekly compliance reviews

**Optional**:
- Spot checks during development
- When feeling uncertain about workflow
- To confirm best practices

## Quick Reference

**Syntax**: `/validate-workflow [--options]`

**Modes**: basic (default) | task-specific | comprehensive

**Metrics**: orchestration usage, context reads, documentation sync, memory accumulation

**Scoring**: 90-100% (excellent), 75-89% (good), 60-74% (needs improvement), <60% (poor)

**Integration**: Use before commits, after sessions, in daily/weekly reviews

---

## Summary

The `/validate-workflow` command ensures that the Jutsu-Labs agent architecture workflow is being followed correctly. It detects bypasses, validates compliance, tracks metrics, and provides remediation guidance when violations occur. Use it regularly to maintain excellent workflow compliance and maximize the benefits of the agent architecture system.

**Your compliance guardian - ensuring quality, consistency, and knowledge preservation across all development work.**
