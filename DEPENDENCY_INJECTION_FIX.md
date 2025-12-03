# Dependency Injection Fix - Execution Timing Feature

## Problem Summary

The execution timing feature in Hierarchical_Adaptive_v3_5b was not working in grid-search mode. All three execution_time values (`open`, `15min_after_open`, `close`) produced identical results.

## Root Cause

**The dependency injection code was NEVER implemented in BacktestRunner.run().**

The strategy methods `set_end_date()` and `set_data_handler()` exist in the strategy file, but BacktestRunner was never calling them. This meant:

1. `strategy._end_date` remained unset → `_is_last_day()` always returned False
2. `strategy._data_handler` remained None → intraday data fetching was skipped
3. All execution times fell back to EOD data (line 511 check: `if self._data_handler is None`)

## Evidence

### Log Analysis
```
# OLD LOGS (2025-11-24 23:35:18) - No injection messages
2025-11-24 23:35:18 | BACKTEST | INFO | Starting backtest with strategy...
# Missing: "Injected end_date into strategy..."
# Missing: "Injected data_handler into strategy..."
```

### Code Verification
```bash
# Committed version (HEAD) has NO injection code
$ git show HEAD:jutsu_engine/application/backtest_runner.py | grep -A 5 "strategy.init()"
strategy.init()

# Extract signal_symbol from strategy...  # <-- No injection here!

# hasattr() works correctly
$ python3 -c "from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b; s = Hierarchical_Adaptive_v3_5b(...); print(hasattr(s, 'set_end_date'))"
True  # Methods exist!
```

## Solution Implemented

Added dependency injection code to `BacktestRunner.run()` at TWO locations:

### Location 1: After strategy.init() (Line 346-349)
```python
# Inject end_date for last day detection (execution timing feature)
if hasattr(strategy, 'set_end_date'):
    strategy.set_end_date(self.config['end_date'])
    logger.info(f"Injected end_date into strategy: {self.config['end_date'].date()}")
```

### Location 2: After data_handler creation (Line 387-390)
```python
# Inject data_handler for intraday data access (execution timing feature)
if hasattr(strategy, 'set_data_handler'):
    strategy.set_data_handler(data_handler)
    logger.info("Injected data_handler into strategy for intraday data access")
```

## Files Modified

1. **jutsu_engine/application/backtest_runner.py**
   - Added: Dependency injection at lines 346-349 (set_end_date)
   - Added: Dependency injection at lines 387-390 (set_data_handler)

## Verification

After fix, log files will show:
```
2025-XX-XX HH:MM:SS | BACKTEST | INFO | Injected end_date into strategy: 2025-11-24
2025-XX-XX HH:MM:SS | BACKTEST | INFO | Injected data_handler into strategy for intraday data access
2025-XX-XX HH:MM:SS | STRATEGY.HIERARCHICAL_ADAPTIVE_V3_5B | INFO | Strategy end_date set to 2025-11-24 for execution timing
2025-XX-XX HH:MM:SS | STRATEGY.HIERARCHICAL_ADAPTIVE_V3_5B | INFO | Strategy data_handler set for intraday execution timing
```

## Expected Impact

With dependency injection working:
- **`execution_time="open"`**: Executes at market open (9:30 AM)
- **`execution_time="15min_after_open"`**: Executes at 9:45 AM
- **`execution_time="close"`**: Executes at market close (4:00 PM EOD)

Different execution times will now produce DIFFERENT results due to:
- Different intraday prices at different times
- Different slippage characteristics
- Different indicator values based on partial-day data

## Testing

1. **Unit Test** (Verify methods exist):
   ```bash
   python3 test_injection_debug.py
   # Should show: ✓ ALL TESTS PASSED
   ```

2. **Grid Search Test** (Verify different results):
   ```bash
   python3 -m jutsu_engine.application.grid_search_runner \
       --config grid-configs/examples/grid_search_hierarchical_adaptive_v3_5b_execution_timing.yaml

   # Check logs for injection messages
   tail -f logs/jutsu_labs_log_*.log | grep -i "inject\|end_date set\|data_handler set"

   # Verify results differ
   # open != 15min_after_open != close
   ```

## Why This Wasn't Caught Earlier

1. **New Feature**: Execution timing is a new feature - methods exist in strategy but injection was never added to BacktestRunner
2. **Silent Fallback**: Strategy gracefully falls back to EOD data when `_data_handler is None` (line 511)
3. **No Errors**: Code ran successfully, just with incorrect behavior (all times identical)
4. **Cached .pyc Files**: Cleared cache to ensure fresh code execution

## Lesson Learned

**Always verify dependency injection happens at runtime, not just that methods exist.**

- Methods can exist but never be called
- Silent fallbacks can mask missing injection
- Use logger.info() (not logger.debug()) for critical injection points
- Clear Python cache (.pyc files) when investigating runtime behavior
