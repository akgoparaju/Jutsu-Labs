# Debugging Workflow Prompt Template

**Purpose**: Template for Task agents debugging issues autonomously with full MCP access.

---

## Your Mission

You are debugging an issue in the **{MODULE_NAME}** module.

**Issue Description**: {ISSUE_DESCRIPTION}
**Symptoms**: {SYMPTOMS}
**Affected Files**: {AFFECTED_FILES}
**Log Files**: {LOG_FILES}

---

## You Have FULL MCP Access

🎁 **SuperClaude Capabilities Available**:

✅ **Sequential MCP**: ROOT CAUSE ANALYSIS (Primary tool for debugging)
- Systematic hypothesis testing
- Multi-step reasoning for complex bugs
- Evidence-based diagnosis

✅ **Context7 MCP**: Official documentation and known issues
- Framework bug patterns
- Library-specific debugging guides
- Best practices for error handling

✅ **Serena MCP**: Project memory and historical context
- Check if similar bugs were fixed before
- Read debugging notes from previous sessions

✅ **All Standard Tools**: Read, Grep, Bash
- Read logs, search for patterns, run tests
- Execute code to reproduce issues

---

## Debugging Workflow

### Phase 1: Evidence Gathering

#### Step 1.1: Read Logs
```bash
# Read error logs
Read("{LOG_FILE}")

# Search for error patterns
Grep("ERROR|CRITICAL", path="{LOG_FILE}", output_mode="content", -B=5, -A=5)

# Find stack traces
Grep("Traceback|Exception", path="logs/", output_mode="content", -B=10, -A=10)
```

#### Step 1.2: Examine Affected Code
```bash
# Read the module with the issue
Read("{AFFECTED_FILE}")

# Check recent changes
Bash("git log -p --follow {AFFECTED_FILE} | head -100")

# Search for related code
Grep("{ERROR_KEYWORD}", path="jutsu_engine/", output_mode="files_with_matches")
```

#### Step 1.3: Gather Context
```bash
# Check Serena memories for similar issues
Serena: list_memories()
Serena: read_memory("debugging_notes")  # If exists

# Check test failures
Bash("pytest {TEST_FILE} -v --tb=long")
```

---

### Phase 2: Root Cause Analysis (Use Sequential MCP)

**Use Sequential for systematic analysis:**

```
Sequential: """
DEBUG ANALYSIS: {ISSUE_DESCRIPTION}

Evidence collected:
1. Error logs show: {LOG_EVIDENCE}
2. Stack trace points to: {STACK_TRACE_LOCATION}
3. Recent changes: {GIT_HISTORY}
4. Test failures: {TEST_FAILURES}

Systematic analysis:
1. What is the exact error/symptom?
2. When does it occur? (Always? Specific conditions?)
3. What changed recently that could cause this?
4. What are the most likely root causes?
5. What additional evidence would confirm/reject each hypothesis?

Generate ranked hypotheses with evidence requirements.
"""
```

---

### Phase 3: Hypothesis Testing

For each hypothesis from Sequential analysis:

#### Test Setup
```python
# Create minimal reproduction case
Write("tests/debug/test_reproduction.py", reproduction_test)

# Run reproduction test
Bash("pytest tests/debug/test_reproduction.py -v -s")
```

#### Hypothesis Validation
```python
# Test hypothesis 1
# Modify code to test hypothesis
Edit("{FILE}", old_code, test_code)

# Run tests
Bash("pytest {TEST_FILE} -v")

# Revert if hypothesis wrong
Edit("{FILE}", test_code, old_code)
```

#### Evidence Analysis
```
Sequential: """
Hypothesis testing results:
- Hypothesis 1: {RESULT_1}
- Hypothesis 2: {RESULT_2}
- Evidence supports: {CONCLUSION}

Recommended fix approach: {FIX_STRATEGY}
"""
```

---

### Phase 4: Implement Fix

#### Step 4.1: Design Fix
```
Sequential: """
Root cause confirmed: {ROOT_CAUSE}

Design fix that:
1. Addresses root cause (not just symptoms)
2. Doesn't introduce new issues
3. Handles edge cases
4. Is testable and verifiable

Proposed fix: {FIX_DESIGN}
Validation approach: {VALIDATION_STRATEGY}
"""
```

#### Step 4.2: Apply Fix
```python
# Implement the fix
Edit("{AFFECTED_FILE}", broken_code, fixed_code)

# Add error handling if needed
Edit("{AFFECTED_FILE}", old_section, section_with_error_handling)

# Update logging for better diagnostics
Edit("{AFFECTED_FILE}", old_log, enhanced_log)
```

#### Step 4.3: Add Tests for Bug
```python
# Write regression test
Write("tests/unit/test_{MODULE}_regression.py", regression_test)

# Ensure test fails with old code (before fix)
# Ensure test passes with fix
```

---

### Phase 5: Validation

#### Comprehensive Testing
```bash
# Run all module tests
pytest tests/unit/test_{MODULE}.py -v

# Run integration tests
pytest tests/integration/ -v -k {MODULE}

# Check test coverage (should maintain >80%)
pytest tests/unit/test_{MODULE}.py --cov=jutsu_engine/{MODULE} --cov-report=term

# Run full test suite (ensure no regressions)
pytest
```

#### Performance Validation
```bash
# If performance-related bug, validate fix doesn't hurt performance
pytest tests/unit/test_{MODULE}.py -v -k performance
```

#### Code Quality
```bash
# Type checking
mypy jutsu_engine/{MODULE}/

# Formatting
black jutsu_engine/{MODULE}/ tests/
isort jutsu_engine/{MODULE}/ tests/
```

---

### Phase 6: Documentation

#### Update CHANGELOG.md
```markdown
### Fixed
- **{MODULE_NAME}**: Fixed {BUG_DESCRIPTION}
  - Root cause: {ROOT_CAUSE}
  - Resolution: {FIX_SUMMARY}
  - Affected: {AFFECTED_FILES}
  - Tests added: {REGRESSION_TESTS}
```

#### Write Memory for Future
```python
Serena: write_memory("bug_fix_{MODULE}_{DATE}", {
  "bug": "{BUG_DESCRIPTION}",
  "root_cause": "{ROOT_CAUSE}",
  "fix": "{FIX_SUMMARY}",
  "lessons": "{LESSONS_LEARNED}"
})
```

#### Code Comments (If Complex)
```python
# Add comment explaining why fix is needed
"""
BUG FIX ({DATE}): {BRIEF_DESCRIPTION}

Root Cause: {ROOT_CAUSE}
Fix: {FIX_EXPLANATION}

See tests/unit/test_{MODULE}_regression.py for regression test.
"""
```

---

## Common Bug Patterns

### Pattern 1: Data Type Issues
```python
# Common in financial calculations
# Root cause: Using float instead of Decimal

# Bad
price = 100.15  # float
total = price * 10  # ❌ Floating point errors

# Good
price = Decimal('100.15')
total = price * Decimal('10')  # ✅ Exact precision
```

### Pattern 2: Lookback Bias
```python
# Root cause: Using future data in backtests

# Bad
all_bars = get_bars(symbol, end_date=today)
# Processing bar from yesterday but seeing today's data ❌

# Good
current_bar_index = ...
historical_bars = all_bars[:current_bar_index + 1]  # ✅ Only past data
```

### Pattern 3: Mutable Data Issues
```python
# Root cause: Modifying shared/historical data

# Bad
def process_bar(bar):
    bar.close = adjusted_price  # ❌ Mutating historical data

# Good
@dataclass(frozen=True)  # Immutable
class MarketDataEvent:
    close: Decimal
```

### Pattern 4: Missing Error Handling
```python
# Root cause: Not handling API failures, database errors

# Bad
data = api.fetch_bars(symbol)  # ❌ What if API fails?

# Good
try:
    data = api.fetch_bars(symbol)
except APIError as e:
    logger.error(f"API failure: {e}")
    # Fallback or retry logic
```

### Pattern 5: Race Conditions
```python
# Root cause: Concurrent access to shared state

# Bad
self.position += quantity  # ❌ Not thread-safe

# Good
with self._lock:
    self.position += quantity  # ✅ Thread-safe
```

---

## Performance Issues

### Profiling
```python
# Use cProfile for performance debugging
Bash("python -m cProfile -s cumulative {SCRIPT} > profile.txt")

# Read profile results
Read("profile.txt")

# Analyze bottlenecks with Sequential
Sequential: """
Profile shows:
{PROFILE_DATA}

Identify:
1. Hottest functions (most time spent)
2. Unnecessary operations
3. Optimization opportunities
"""
```

### Memory Issues
```python
# Check memory usage
Bash("python -m memory_profiler {SCRIPT}")

# Look for memory leaks
Grep("memory|leak", path="logs/", output_mode="content")
```

---

## Validation Checklist

Before reporting fix complete:

- [ ] ✅ Root cause identified and confirmed (not just guessing)
- [ ] ✅ Fix addresses root cause (not just symptoms)
- [ ] ✅ Regression test added (test fails before fix, passes after)
- [ ] ✅ All existing tests still pass
- [ ] ✅ No performance degradation
- [ ] ✅ Test coverage maintained (>80%)
- [ ] ✅ Code quality checks pass (mypy, black, isort)
- [ ] ✅ CHANGELOG.md updated with fix details
- [ ] ✅ Debugging notes written to Serena memory
- [ ] ✅ No new issues introduced

---

## Reporting Results

Return a structured summary:

```json
{
  "issue": "{ISSUE_DESCRIPTION}",
  "status": "fixed",
  "root_cause": {
    "description": "{ROOT_CAUSE}",
    "evidence": [
      "{EVIDENCE_1}",
      "{EVIDENCE_2}"
    ]
  },
  "fix": {
    "description": "{FIX_DESCRIPTION}",
    "files_modified": [
      "{FILE_1}",
      "{FILE_2}"
    ],
    "approach": "{FIX_APPROACH}"
  },
  "validation": {
    "regression_tests": "{TEST_FILE}",
    "all_tests_passing": "X/X tests pass",
    "performance_impact": "No degradation / Improved by X%",
    "coverage": "X% (maintained/improved)"
  },
  "prevention": {
    "lessons_learned": "{LESSONS}",
    "preventive_measures": [
      "{MEASURE_1}",
      "{MEASURE_2}"
    ]
  },
  "documentation": {
    "changelog_updated": true,
    "memory_written": "bug_fix_{MODULE}_{DATE}",
    "comments_added": true
  }
}
```

---

## Remember

**Systematic > Guessing**
- Use Sequential MCP for hypothesis-driven debugging
- Collect evidence before forming theories
- Test each hypothesis systematically

**Root Cause > Symptoms**
- Fix underlying issues, not just symptoms
- Understand WHY the bug occurred
- Prevent similar bugs in the future

**Evidence-Based**
- Every conclusion must be backed by evidence
- Logs, stack traces, test results, profiling data
- No assumptions without validation

**Quality Maintained**
- All tests pass
- Coverage maintained
- No performance degradation
- Clean, well-documented fix

---

**Now debug the issue autonomously using systematic analysis. Good luck!** 🔍
