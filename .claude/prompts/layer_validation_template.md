# Layer Validation Prompt Template

**Purpose**: Template for Task agents validating layer implementation quality and architecture compliance.

---

## Your Mission

You are validating the **{LAYER_NAME}** layer implementation.

**Layer**: {LAYER_NAME} ({LAYER_DESCRIPTION})
**Modules Implemented**: {MODULE_LIST}
**Orchestrator**: {ORCHESTRATOR_PATH}

---

## You Have FULL MCP Access

🎁 **SuperClaude Capabilities Available**:

✅ **Sequential MCP**: VALIDATION ANALYSIS (Primary tool)
- Systematic quality assessment
- Architecture compliance checking
- Multi-dimensional analysis

✅ **Context7 MCP**: Best practices and patterns
- Framework validation patterns
- Testing best practices
- Quality standards

✅ **All Standard Tools**: Read, Grep, Bash
- Run test suites, analyze coverage
- Check code quality, search for issues

---

## Validation Dimensions

### 1. Architecture Compliance
### 2. Interface Contracts
### 3. Test Coverage & Quality
### 4. Performance Targets
### 5. Code Quality Standards
### 6. Documentation Completeness

---

## Phase 1: Architecture Compliance

### Check Dependency Rule
```python
# Read layer orchestrator for constraints
Read("{ORCHESTRATOR_PATH}")

# Check for dependency violations
Grep("from jutsu_engine.{FORBIDDEN_LAYER}", path="jutsu_engine/{LAYER}/", output_mode="content")
Grep("import jutsu_engine.{FORBIDDEN_LAYER}", path="jutsu_engine/{LAYER}/", output_mode="content")
```

**Validation Rules**:
- Core layer: CANNOT import from Application, Infrastructure, Entry Points
- Application layer: CANNOT import from Infrastructure, Entry Points (CAN import Core)
- Infrastructure layer: CAN import Core interfaces (CANNOT import Application, Entry Points)
- Entry Points: CAN import everything

### Analyze with Sequential
```
Sequential: """
ARCHITECTURE COMPLIANCE CHECK: {LAYER_NAME} Layer

Dependency Rule: {DEPENDENCY_RULE}

Import Analysis:
{IMPORT_GREP_RESULTS}

Questions:
1. Are there any dependency rule violations?
2. Are all imports from allowed layers?
3. Are there circular dependencies?
4. Is the hexagonal architecture preserved?

Generate compliance report with violations (if any).
"""
```

---

## Phase 2: Interface Contracts

### Check Interface Compliance
```python
# Read interface definitions
Read("docs/INTERFACES.md")

# For each module, verify it implements required interfaces
for module in {MODULE_LIST}:
    Read(f"jutsu_engine/{LAYER}/{module}.py")

    # Check interface methods present
    Grep("def {REQUIRED_METHOD}", path=f"jutsu_engine/{LAYER}/{module}.py")
```

### Validate Interface Contracts
```
Sequential: """
INTERFACE CONTRACT VALIDATION: {LAYER_NAME} Layer

Required Interfaces: {INTERFACE_LIST}

For each module:
1. Does it implement all required methods?
2. Are method signatures correct?
3. Are return types compatible?
4. Are input validations present?

Generate interface compliance report.
"""
```

---

## Phase 3: Test Coverage & Quality

### Run Test Suite
```bash
# Run all layer tests
pytest tests/unit/{LAYER}/ -v --cov=jutsu_engine/{LAYER} --cov-report=term

# Check integration tests
pytest tests/integration/{LAYER}/ -v

# Generate coverage report
pytest tests/unit/{LAYER}/ --cov=jutsu_engine/{LAYER} --cov-report=html
```

### Analyze Coverage
```
Sequential: """
TEST COVERAGE ANALYSIS: {LAYER_NAME} Layer

Coverage Results:
{COVERAGE_OUTPUT}

Target: >80% for unit tests, >70% for integration

Analysis:
1. Which modules are below target?
2. What critical paths are untested?
3. Are edge cases covered?
4. Are error paths tested?

Generate coverage assessment with gaps.
"""
```

### Quality Checks
```bash
# Check for missing tests
for module in {MODULE_LIST}:
    if ! test -f tests/unit/{LAYER}/test_{module}.py; then
        echo "❌ Missing tests for {module}"
    fi

# Check test quality
Grep("TODO|FIXME|SKIP|xfail", path="tests/unit/{LAYER}/", output_mode="content")
```

---

## Phase 4: Performance Targets

### Run Performance Tests
```bash
# Run performance benchmarks
pytest tests/unit/{LAYER}/ -v -k performance --benchmark-only

# Check for performance regressions
pytest tests/unit/{LAYER}/ -v -k performance --benchmark-compare
```

### Validate Performance
```
Sequential: """
PERFORMANCE VALIDATION: {LAYER_NAME} Layer

Performance Targets:
{PERFORMANCE_TARGETS}

Benchmark Results:
{BENCHMARK_OUTPUT}

Analysis:
1. Which modules meet performance targets?
2. Which modules are below target?
3. Are there performance regressions?
4. What optimization opportunities exist?

Generate performance assessment.
"""
```

---

## Phase 5: Code Quality Standards

### Type Checking
```bash
# Run mypy on entire layer
mypy jutsu_engine/{LAYER}/

# Check for missing type hints
Grep("def .*\(.*\):", path="jutsu_engine/{LAYER}/", output_mode="content") | grep -v " -> "
```

### Code Formatting
```bash
# Check black formatting
black --check jutsu_engine/{LAYER}/

# Check isort
isort --check jutsu_engine/{LAYER}/
```

### Linting
```bash
# Run flake8
flake8 jutsu_engine/{LAYER}/

# Run pylint
pylint jutsu_engine/{LAYER}/ --rcfile=.pylintrc
```

### Financial Data Handling
```bash
# Check for float usage in financial calculations
Grep("float|Float", path="jutsu_engine/{LAYER}/", output_mode="content")

# Verify Decimal usage
Grep("from decimal import Decimal|Decimal\(", path="jutsu_engine/{LAYER}/", output_mode="content")

# Check for mutable data issues
Grep("@dataclass\(frozen=True\)", path="jutsu_engine/{LAYER}/", output_mode="content")
```

---

## Phase 6: Documentation Completeness

### Check Docstrings
```bash
# Find functions without docstrings
Grep("^def [^_].*\):", path="jutsu_engine/{LAYER}/", output_mode="content") -A=1 | grep -v '"""'

# Check docstring style (should be Google style)
Read("jutsu_engine/{LAYER}/{MODULE}.py")
```

### Module Documentation
```python
# Check if module agent docs are up to date
for module in {MODULE_LIST}:
    agent_doc = Read(f".claude/layers/{LAYER}/modules/{module.upper()}_AGENT.md")

    # Verify "Current Implementation" section reflects actual code
```

### API Documentation
```bash
# Check if INTERFACES.md is current
Read("docs/INTERFACES.md")

# Compare with actual implementations
```

---

## Validation Report Structure

Use Sequential to generate comprehensive report:

```
Sequential: """
LAYER VALIDATION REPORT: {LAYER_NAME}

Compile findings from all validation phases:
1. Architecture Compliance
2. Interface Contracts
3. Test Coverage & Quality
4. Performance Targets
5. Code Quality Standards
6. Documentation Completeness

For each dimension:
- Status: ✅ Pass / ⚠️ Warnings / ❌ Fail
- Details: Specific findings
- Issues: List of problems (if any)
- Recommendations: Suggested fixes

Generate structured validation report.
"""
```

---

## Quality Gates

### Gate 1: Architecture (CRITICAL)
- [ ] ✅ No dependency rule violations
- [ ] ✅ No circular dependencies
- [ ] ✅ Hexagonal architecture preserved

**If fails**: BLOCK - Must fix before proceeding

### Gate 2: Interfaces (CRITICAL)
- [ ] ✅ All required interfaces implemented
- [ ] ✅ Method signatures correct
- [ ] ✅ Return types compatible

**If fails**: BLOCK - Must fix before proceeding

### Gate 3: Testing (IMPORTANT)
- [ ] ✅ >80% unit test coverage
- [ ] ✅ >70% integration test coverage
- [ ] ✅ All tests passing
- [ ] ✅ No skipped/disabled tests

**If fails**: WARNING - Can proceed with plan to fix

### Gate 4: Performance (IMPORTANT)
- [ ] ✅ All modules meet performance targets
- [ ] ✅ No performance regressions

**If fails**: WARNING - Can proceed with plan to fix

### Gate 5: Code Quality (RECOMMENDED)
- [ ] ✅ Type hints on all public functions
- [ ] ✅ Code formatted (black, isort)
- [ ] ✅ Linting passing (flake8, pylint >8.0)
- [ ] ✅ Financial data handling correct (Decimal, immutable)

**If fails**: RECOMMEND - Note in report

### Gate 6: Documentation (RECOMMENDED)
- [ ] ✅ All public APIs have docstrings
- [ ] ✅ Module agent docs current
- [ ] ✅ INTERFACES.md reflects implementation

**If fails**: RECOMMEND - Note in report

---

## Reporting Results

Return a structured validation report:

```json
{
  "layer": "{LAYER_NAME}",
  "validation_date": "{DATE}",
  "overall_status": "pass|warn|fail",
  "quality_gates": {
    "architecture": {
      "status": "✅ Pass",
      "violations": [],
      "details": "All dependency rules followed"
    },
    "interfaces": {
      "status": "✅ Pass",
      "violations": [],
      "details": "All contracts implemented correctly"
    },
    "testing": {
      "status": "⚠️ Warning",
      "coverage": {
        "unit": "85%",
        "integration": "68%"
      },
      "issues": ["Integration coverage below 70%"],
      "recommendation": "Add integration tests for DataSync module"
    },
    "performance": {
      "status": "✅ Pass",
      "benchmarks": {
        "module1": "✅ 0.8ms (target: <1ms)",
        "module2": "✅ 0.05ms (target: <0.1ms)"
      }
    },
    "code_quality": {
      "status": "✅ Pass",
      "type_hints": "100%",
      "formatting": "✅ Pass",
      "linting": "✅ Pass (8.5/10)",
      "financial_handling": "✅ All using Decimal"
    },
    "documentation": {
      "status": "✅ Pass",
      "docstrings": "98%",
      "module_docs": "Current",
      "api_docs": "Current"
    }
  },
  "summary": {
    "modules_validated": 4,
    "critical_issues": 0,
    "warnings": 1,
    "recommendations": 2
  },
  "blockers": [],
  "recommendations": [
    "Increase integration test coverage for DataSync module",
    "Add performance benchmarks for edge cases"
  ],
  "next_steps": [
    "Proceed to system integration validation",
    "Address integration test coverage in next iteration"
  ]
}
```

---

## Remember

**Quality Gates Are Non-Negotiable**
- Architecture and Interface gates MUST pass
- Testing and Performance gates should pass (can proceed with plan)
- Code Quality and Documentation should pass (recommend fixing)

**Evidence-Based Validation**
- Run actual tests, don't just check if files exist
- Analyze actual coverage numbers, not estimates
- Use Sequential for systematic analysis

**Comprehensive > Quick**
- Better to find issues now than in production
- Validation is quality investment, not overhead
- Thorough validation prevents integration problems

**Document Everything**
- Structured JSON report for tracking
- Clear blockers vs. recommendations
- Actionable next steps

---

**Now validate {LAYER_NAME} layer autonomously with systematic quality checks. Good luck!** ✅
