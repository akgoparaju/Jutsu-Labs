# System Integration Prompt Template

**Purpose**: Template for Task agents performing system-level integration and end-to-end validation.

---

## Your Mission

You are performing **system integration** for the Jutsu Labs backtesting engine.

**Integration Scope**: {INTEGRATION_SCOPE}
**Layers Involved**: {LAYER_LIST}
**Integration Type**: {INTEGRATION_TYPE}

---

## You Have FULL MCP Access

🎁 **SuperClaude Capabilities Available**:

✅ **Sequential MCP**: SYSTEM ANALYSIS (Primary tool)
- End-to-end workflow validation
- Cross-layer interaction analysis
- Integration issue diagnosis

✅ **Context7 MCP**: Integration patterns
- System integration best practices
- End-to-end testing patterns
- Architecture validation

✅ **Playwright MCP**: End-to-end testing (if CLI/UI involved)
- Real user workflow testing
- Complete system validation

✅ **All Standard Tools**: Read, Bash, Grep
- Run integration tests, analyze logs
- Check cross-module interactions

---

## Integration Workflow

### Phase 1: System Architecture Validation

#### Read System Specification
```python
# Read system orchestrator
Read(".claude/system/SYSTEM_ORCHESTRATOR.md")

# Read all layer orchestrators
for layer in {LAYER_LIST}:
    Read(f".claude/layers/{layer}/{layer.upper()}_ORCHESTRATOR.md")
```

#### Analyze System Design
```
Sequential: """
SYSTEM ARCHITECTURE ANALYSIS

Layers: {LAYER_LIST}
Integration points: {INTEGRATION_POINTS}

Analysis:
1. Are all layers properly connected?
2. Do interfaces between layers match?
3. Is data flow correct (Entry → App → Core → Infra)?
4. Are there any architectural violations?

Generate architecture validation report.
"""
```

---

## Phase 2: Integration Point Validation

### Identify Integration Points
```python
# For each layer interface
interfaces = Read("docs/INTERFACES.md")

# Check implementations
for interface in {INTERFACES}:
    # Provider (implements interface)
    provider_code = Read("{PROVIDER_FILE}")

    # Consumer (uses interface)
    consumer_code = Read("{CONSUMER_FILE}")

    # Verify compatibility
```

### Cross-Layer Flow Validation
```
Sequential: """
CROSS-LAYER FLOW VALIDATION

Workflow: {WORKFLOW_DESCRIPTION}

Trace data flow through layers:
Entry Point → Application → Core → Infrastructure

For each integration point:
1. Provider implements interface correctly?
2. Consumer uses interface correctly?
3. Data types compatible?
4. Error handling present?

Generate integration compatibility report.
"""
```

---

## Phase 3: End-to-End Testing

### Integration Test Suite
```bash
# Run all integration tests
pytest tests/integration/ -v --tb=long

# Check integration test coverage
pytest tests/integration/ --cov=jutsu_engine --cov-report=term

# Generate detailed report
pytest tests/integration/ -v --junitxml=integration_report.xml
```

### Critical User Workflows

#### Workflow 1: Data Sync → Backtest
```python
# Test complete workflow
Write("tests/integration/test_end_to_end_backtest.py", """
def test_complete_backtest_workflow():
    '''Test data sync → backtest → results workflow.'''

    # 1. Sync data
    syncer = DataSync(...)
    syncer.sync_symbol('AAPL', '2023-01-01', '2023-12-31')

    # 2. Run backtest
    runner = BacktestRunner(...)
    results = runner.run_backtest(
        symbol='AAPL',
        strategy_class=SMACrossover,
        start='2023-01-01',
        end='2023-12-31'
    )

    # 3. Validate results
    assert results['total_trades'] > 0
    assert 'sharpe_ratio' in results
    assert results['final_portfolio_value'] > 0
""")

# Run workflow test
Bash("pytest tests/integration/test_end_to_end_backtest.py -v -s")
```

#### Workflow 2: CLI → Application → Core
```python
# Test CLI integration
Write("tests/integration/test_cli_integration.py", """
def test_cli_backtest_command():
    '''Test CLI → BacktestRunner → EventLoop integration.'''

    # Run via CLI
    result = subprocess.run([
        'vibe', 'backtest',
        '--symbol', 'AAPL',
        '--strategy', 'SMACrossover',
        '--start', '2023-01-01',
        '--end', '2023-12-31'
    ], capture_output=True)

    assert result.returncode == 0
    assert 'Backtest complete' in result.stdout.decode()
""")
```

### Analyze Test Results
```
Sequential: """
INTEGRATION TEST ANALYSIS

Test Results:
{TEST_OUTPUT}

Analysis:
1. Which workflows are fully tested?
2. Which integration points lack tests?
3. Are error scenarios tested?
4. Are all layers exercised?

Generate test coverage report with gaps.
"""
```

---

## Phase 4: Example Script Validation

### Create Example Scripts
```python
# Example 1: Simple backtest
Write("scripts/example_simple_backtest.py", """
'''Example: Simple SMA Crossover Backtest'''

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.strategies.sma_crossover import SMACrossover
from decimal import Decimal
from datetime import datetime

def main():
    # Initialize backtest runner
    runner = BacktestRunner(
        initial_capital=Decimal('100000'),
        commission=Decimal('0.001')
    )

    # Run backtest
    results = runner.run_backtest(
        symbol='AAPL',
        strategy_class=SMACrossover,
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 12, 31)
    )

    # Print results
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.2%}")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown']:.2%}")

if __name__ == '__main__':
    main()
""")

# Test example script
Bash("python scripts/example_simple_backtest.py")
```

### Example 2: Data Sync
```python
Write("scripts/example_data_sync.py", """
'''Example: Sync Market Data from Schwab API'''

from jutsu_engine.application.data_sync import DataSync
from datetime import datetime

def main():
    # Initialize data sync
    syncer = DataSync()

    # Sync AAPL data
    syncer.sync_symbol(
        symbol='AAPL',
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 12, 31),
        timeframe='1D'
    )

    print(f"Data sync complete for AAPL")

if __name__ == '__main__':
    main()
""")
```

---

## Phase 5: System-Level Performance Testing

### Performance Benchmarks
```python
# System-level performance test
Write("tests/integration/test_system_performance.py", """
def test_backtest_performance():
    '''Verify system meets performance targets end-to-end.'''
    import time

    runner = BacktestRunner(...)

    start = time.perf_counter()
    results = runner.run_backtest(
        symbol='AAPL',
        strategy_class=SMACrossover,
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 12, 31)  # ~250 bars
    )
    elapsed = time.perf_counter() - start

    # Target: <1 second for 250 bars
    assert elapsed < 1.0, f"Backtest took {elapsed:.2f}s (target: <1.0s)"

    # Check EventLoop performance (<1ms per bar)
    avg_bar_time = elapsed / 250
    assert avg_bar_time < 0.001, f"Avg bar time: {avg_bar_time*1000:.2f}ms"
""")

# Run performance tests
Bash("pytest tests/integration/test_system_performance.py -v")
```

### Stress Testing
```python
# System stress test
Write("tests/integration/test_system_stress.py", """
def test_large_dataset_backtest():
    '''Test system with large dataset (5 years = ~1250 bars).'''

    runner = BacktestRunner(...)
    results = runner.run_backtest(
        symbol='AAPL',
        strategy_class=SMACrossover,
        start_date=datetime(2019, 1, 1),
        end_date=datetime(2023, 12, 31)
    )

    assert results['total_trades'] > 0
    assert results['final_portfolio_value'] > 0

def test_multiple_symbols():
    '''Test system with multiple symbols concurrently.'''

    symbols = ['AAPL', 'GOOGL', 'MSFT']
    results = {}

    for symbol in symbols:
        runner = BacktestRunner(...)
        results[symbol] = runner.run_backtest(
            symbol=symbol,
            strategy_class=SMACrossover,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31)
        )

    assert all(r['total_trades'] > 0 for r in results.values())
""")
```

---

## Phase 6: Documentation Integration

### Update README
```python
# Verify README examples work
readme = Read("README.md")

# Extract code examples
# Run them to verify they work
```

### API Reference
```python
# Update API_REFERENCE.md with complete system API
Write("docs/API_REFERENCE.md", """
# API Reference

## Application Layer

### BacktestRunner
{BACKTEST_RUNNER_API}

### DataSync
{DATA_SYNC_API}

## Core Layer

### EventLoop
{EVENT_LOOP_API}

### Strategy
{STRATEGY_API}

### Portfolio
{PORTFOLIO_API}

## Infrastructure Layer

### DataHandler
{DATA_HANDLER_API}

### PerformanceAnalyzer
{PERFORMANCE_API}

## Entry Points

### CLI
{CLI_API}
""")
```

---

## Integration Validation Checklist

### Critical Checks (MUST PASS)
- [ ] ✅ All integration tests passing
- [ ] ✅ End-to-end workflows functional
- [ ] ✅ No circular dependencies
- [ ] ✅ All layers integrate correctly
- [ ] ✅ Example scripts execute successfully

### Important Checks (SHOULD PASS)
- [ ] ✅ System performance targets met
- [ ] ✅ Integration test coverage >70%
- [ ] ✅ All critical workflows tested
- [ ] ✅ Stress tests passing

### Recommended Checks (NICE TO HAVE)
- [ ] ✅ Documentation examples verified
- [ ] ✅ API reference complete
- [ ] ✅ Multiple-symbol support tested
- [ ] ✅ Error recovery tested

---

## Reporting Results

Use Sequential to compile comprehensive integration report:

```
Sequential: """
SYSTEM INTEGRATION REPORT

Compile findings from all integration phases:
1. Architecture validation
2. Integration point validation
3. End-to-end testing
4. Example script validation
5. Performance testing
6. Documentation integration

Generate structured report with:
- Integration status (pass/fail/warn)
- Test results and coverage
- Performance benchmarks
- Blockers and recommendations
"""
```

Return structured JSON:

```json
{
  "integration": "system",
  "date": "{DATE}",
  "status": "pass|warn|fail",
  "architecture": {
    "status": "✅ Pass",
    "layers_integrated": 4,
    "violations": []
  },
  "integration_points": {
    "status": "✅ Pass",
    "validated": 12,
    "issues": []
  },
  "end_to_end_tests": {
    "status": "✅ Pass",
    "total": 15,
    "passing": 15,
    "coverage": "75%"
  },
  "workflows_validated": [
    "Data sync → Backtest → Results",
    "CLI → Application → Core",
    "Strategy → Portfolio → Performance"
  ],
  "performance": {
    "status": "✅ Pass",
    "benchmarks": {
      "backtest_250_bars": "0.8s (target: <1.0s)",
      "bar_processing": "0.9ms (target: <1.0ms)",
      "large_dataset": "4.2s for 1250 bars"
    }
  },
  "examples": {
    "status": "✅ Pass",
    "scripts_tested": [
      "scripts/example_simple_backtest.py",
      "scripts/example_data_sync.py"
    ],
    "all_working": true
  },
  "blockers": [],
  "warnings": [],
  "recommendations": [
    "Add integration tests for error recovery scenarios",
    "Create example for multi-symbol backtests"
  ],
  "ready_for_mvp": true
}
```

---

## Remember

**End-to-End > Unit Tests**
- Integration validates the whole system works together
- Unit tests validate pieces, integration validates connections
- Both are necessary for quality

**Real Workflows > Synthetic Tests**
- Test actual user workflows (CLI commands, library usage)
- Verify example scripts work
- Ensure documentation examples are executable

**Performance at Scale**
- Don't just test small datasets
- Stress test with large datasets
- Verify performance doesn't degrade

**Documentation = Integration**
- README examples are integration tests
- API docs should reflect actual implementation
- Working examples prove integration success

---

**Now perform system integration validation autonomously. Good luck!** 🔗
