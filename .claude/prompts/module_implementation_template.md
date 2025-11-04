# Module Implementation Prompt Template

**Purpose**: Template for Task agents implementing modules autonomously with full MCP access.

---

## Your Mission

You are implementing the **{MODULE_NAME}** module for the Jutsu Labs backtesting engine.

**Module Location**: `{FILE_PATH}`
**Layer**: {LAYER_NAME}
**Tests Location**: `{TEST_PATH}`

---

## You Have FULL MCP Access

🎁 **SuperClaude Capabilities Available**:

✅ **Context7 MCP**: Look up official documentation and framework patterns
- Python best practices, SQLAlchemy patterns, testing frameworks
- Use when you need official library documentation or patterns

✅ **Sequential MCP**: Multi-step reasoning for complex logic
- Use for complex algorithm design, architectural decisions
- Systematic analysis of dependencies and interactions

✅ **Serena MCP**: Project memory and context
- Read project memories if relevant to your module
- Write implementation notes for future sessions

✅ **All Standard Tools**: Read, Write, Edit, Grep, Glob, Bash
- Complete file system access within project
- Run tests, check code, analyze dependencies

---

## Module Specification

{AGENT_SPECIFICATION}

**Key Requirements**:
- {REQUIREMENT_1}
- {REQUIREMENT_2}
- {REQUIREMENT_3}

**Dependencies** (Allowed Imports):
{DEPENDENCIES}

**Interfaces to Implement**:
{INTERFACES}

---

## Architecture Constraints

**Layer**: {LAYER_NAME}
**Dependency Rule**: {DEPENDENCY_RULE}

{LAYER_NAME} layer can import:
- {ALLOWED_IMPORTS}

{LAYER_NAME} layer CANNOT import:
- {FORBIDDEN_IMPORTS}

**Why This Matters**: Hexagonal architecture keeps business logic independent of infrastructure. Violating the dependency rule breaks this separation.

---

## Deliverables

### 1. Implementation File: `{FILE_PATH}`
- [ ] All methods implemented (no TODOs, no stubs)
- [ ] Type hints on all public functions
- [ ] Google-style docstrings
- [ ] Logging with logger name '{LOGGER_NAME}'
- [ ] Financial precision: Use `Decimal` for all calculations
- [ ] Immutable data: No modifying historical data

### 2. Test File: `{TEST_PATH}`
- [ ] Unit tests with >80% coverage
- [ ] Test all public methods
- [ ] Test edge cases and error conditions
- [ ] Mock external dependencies
- [ ] Use fixtures from `tests/fixtures/` where applicable

### 3. Quality Standards
- [ ] Performance: {PERFORMANCE_TARGET}
- [ ] All tests passing: `pytest {TEST_PATH} -v`
- [ ] Type checking: `mypy {FILE_PATH}`
- [ ] Code formatting: `black {FILE_PATH}` and `isort {FILE_PATH}`

---

## Implementation Workflow

### Step 1: Understand Context
```bash
# Read the module agent specification
Read("{AGENT_MD_PATH}")

# Check existing code structure
Glob("jutsu_engine/{LAYER}/*.py")

# Look for similar modules for patterns
Read("jutsu_engine/{SIMILAR_MODULE}.py")
```

### Step 2: Use Context7 for Patterns (If Needed)
```python
# Example: If using SQLAlchemy
Context7: "SQLAlchemy repository pattern best practices"

# Example: If implementing async code
Context7: "Python asyncio patterns and error handling"

# Example: If working with Pandas
Context7: "Pandas DataFrame operations with Decimal precision"
```

### Step 3: Use Sequential for Complex Logic (If Needed)
```python
# Example: Complex algorithm design
Sequential: """
Analyze the trade execution algorithm:
1. What edge cases exist for partial fills?
2. How should we handle commission calculations?
3. What's the optimal data structure for position tracking?
"""
```

### Step 4: Implement Module
```python
# Write implementation
Write("{FILE_PATH}", implementation_code)

# Format code
Bash("black {FILE_PATH} && isort {FILE_PATH}")

# Type check
Bash("mypy {FILE_PATH}")
```

### Step 5: Write Tests
```python
# Create comprehensive tests
Write("{TEST_PATH}", test_code)

# Run tests
Bash("pytest {TEST_PATH} -v --cov={FILE_PATH} --cov-report=term")
```

### Step 6: Validate Quality
```bash
# Ensure >80% coverage
pytest {TEST_PATH} --cov={FILE_PATH} --cov-report=term

# Check type hints
mypy {FILE_PATH}

# Verify performance (if applicable)
pytest {TEST_PATH} -v -k performance
```

---

## Code Patterns to Follow

### Type Hints (REQUIRED)
```python
from decimal import Decimal
from datetime import datetime
from typing import List, Dict, Optional

def execute_order(
    symbol: str,
    quantity: int,
    price: Decimal,
    timestamp: datetime
) -> Dict[str, any]:
    """Execute a trade order."""
    ...
```

### Logging Pattern
```python
import logging
logger = logging.getLogger('{LOGGER_NAME}')

logger.info(f"Processing {symbol} at {price}")
logger.warning(f"Unusual condition: {details}")
logger.error(f"Operation failed: {error}")
```

### Financial Precision
```python
from decimal import Decimal

# ❌ NEVER use float
price = 100.15
total = price * 10  # Floating point errors!

# ✅ ALWAYS use Decimal
price = Decimal('100.15')
total = price * Decimal('10')  # Exact precision
```

### Immutable Data
```python
from dataclasses import dataclass

@dataclass(frozen=True)  # ← Makes it immutable
class MarketDataEvent:
    symbol: str
    close: Decimal
    timestamp: datetime
```

---

## Testing Patterns

### Unit Test Structure
```python
import pytest
from decimal import Decimal
from {MODULE_IMPORT_PATH} import {ModuleClass}

class Test{ModuleName}:
    def test_basic_functionality(self):
        """Test core functionality works."""
        instance = {ModuleClass}(initial_params)
        result = instance.method(args)
        assert result == expected

    def test_edge_case_handling(self):
        """Test edge cases are handled correctly."""
        instance = {ModuleClass}(initial_params)
        with pytest.raises(ValueError):
            instance.method(invalid_args)

    def test_performance_target(self):
        """Verify performance meets target."""
        import time
        instance = {ModuleClass}(initial_params)

        start = time.perf_counter()
        result = instance.method(args)
        elapsed = time.perf_counter() - start

        assert elapsed < {PERFORMANCE_THRESHOLD}
```

### Mock External Dependencies
```python
from unittest.mock import Mock, patch

@patch('jutsu_engine.data.handlers.database.DatabaseHandler')
def test_with_mocked_database(mock_db):
    mock_db.get_bars.return_value = [test_bars]

    instance = {ModuleClass}(db=mock_db)
    result = instance.process()

    mock_db.get_bars.assert_called_once()
```

---

## Performance Targets

**Target**: {PERFORMANCE_TARGET}

**How to Measure**:
```python
def test_performance():
    import time
    instance = {ModuleClass}()

    start = time.perf_counter()
    for _ in range(1000):
        instance.method(test_data)
    elapsed = time.perf_counter() - start

    avg_time = elapsed / 1000
    assert avg_time < {PERFORMANCE_THRESHOLD}
```

---

## Final Checklist

Before reporting completion, verify:

- [ ] ✅ Implementation complete (no TODOs, no stubs, no placeholders)
- [ ] ✅ All type hints present
- [ ] ✅ All docstrings written (Google style)
- [ ] ✅ Logging implemented with correct logger name
- [ ] ✅ Financial precision: All calculations use `Decimal`
- [ ] ✅ Tests written with >80% coverage
- [ ] ✅ All tests passing: `pytest {TEST_PATH} -v`
- [ ] ✅ Type checking passing: `mypy {FILE_PATH}`
- [ ] ✅ Code formatted: `black` and `isort`
- [ ] ✅ Performance target met: {PERFORMANCE_TARGET}
- [ ] ✅ No dependency rule violations

---

## Reporting Results

Return a structured summary:

```json
{
  "module": "{MODULE_NAME}",
  "status": "complete",
  "files_created": [
    "{FILE_PATH}",
    "{TEST_PATH}"
  ],
  "test_coverage": "X%",
  "tests_passing": "X/X",
  "performance": {
    "target": "{PERFORMANCE_TARGET}",
    "actual": "X ms",
    "status": "✅ Met"
  },
  "quality_checks": {
    "type_hints": "✅ Pass",
    "tests": "✅ Pass",
    "formatting": "✅ Pass"
  },
  "summary": "Brief description of what was implemented and key features"
}
```

---

## Remember

**You are autonomous** - Make implementation decisions based on:
1. Module specification from agent .md file
2. Architecture constraints (hexagonal, dependency rule)
3. Best practices from Context7
4. Patterns from existing codebase

**You have full MCP access** - Use Sequential for complex logic, Context7 for patterns, Serena for context.

**Quality is non-negotiable** - No partial implementations, no TODOs, >80% test coverage, performance targets met.

**Report when done** - Provide structured summary with evidence (test results, coverage, performance metrics).

---

**Now implement {MODULE_NAME} module autonomously. Good luck!** 🚀
