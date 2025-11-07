# Momentum-ATR Strategy: Symbol Validation Fix

**Date**: 2025-11-06
**Agent**: STRATEGY_AGENT (via `/orchestrate` routing)
**Issue**: Silent failure when required symbols missing from backtest

## Problem Diagnosed

**User Report**: "I don't see any trades happening" after running backtest

**Evidence Chain**:
1. Log file (`jutsu_labs_log_2025-11-06_171410.log`) showed:
   - Only 3 symbols loaded: `QQQ, TQQQ, SQQQ`
   - Missing: `$VIX` symbol
   - Result: `14383 bars processed, 0 signals, 0 fills`

2. Code analysis (`jutsu_engine/strategies/Momentum_ATR.py`):
   - Lines 122-126: Strategy requires VIX data for regime detection
   - Line 124: `if not vix_bars:` check
   - Line 126: Early return if VIX missing
   - Lines 127-200: Regime detection code never executed

3. Root cause:
   - User ran: `--symbols QQQ,TQQQ,SQQQ` (3 symbols)
   - Strategy requires: `QQQ, $VIX, TQQQ, SQQQ` (4 symbols)
   - Without $VIX, strategy silently exits on every QQQ bar
   - No error message, appeared to run successfully
   - Generated 0 trades due to regime detection never running

## Solution Implemented

**Added symbol validation** to fail fast with clear error message:

### Code Changes

**File**: `jutsu_engine/strategies/Momentum_ATR.py`

1. **Added validation state** (line 87):
   ```python
   self._symbols_validated: bool = False  # Track if validation completed
   ```

2. **Added `_validate_required_symbols()` method** (lines 98-131):
   - Checks all 4 required symbols present
   - Lists missing symbols with available symbols
   - Raises `ValueError` with actionable error message

3. **Modified `on_bar()` method** (lines 148-154):
   - Runs validation after enough bars loaded (≥ lookback)
   - Only validates once per backtest
   - Logs success message when validation passes

4. **Updated `init()` method** (line 96):
   - Resets validation flag for each new backtest

### Test Changes

**File**: `tests/unit/strategies/test_momentum_atr.py`

**Added 9 comprehensive validation tests**:
1. Happy path with all symbols
2. Missing $VIX specifically
3. Missing QQQ specifically
4. Missing TQQQ specifically
5. Missing SQQQ specifically
6. Multiple missing symbols
7. Error message quality check
8. Auto-validation during execution
9. Validation runs only once (performance)

**Added helper method**: `_create_test_bars()` for proper timestamp generation

## Validation Results

✅ **All 37 tests pass** (28 original + 9 new validation tests)
✅ **Type hints and docstrings** added to all new methods
✅ **Existing functionality** unchanged (all original tests still pass)

## Error Message Quality

**Before fix**: Silent failure, no indication of problem

**After fix**:
```
ValueError: Momentum_ATR requires symbols ['QQQ', '$VIX', 'TQQQ', 'SQQQ'] but 
missing: ['$VIX']. Available symbols: ['QQQ', 'TQQQ', 'SQQQ']. 
Please include all required symbols in your backtest command.
```

## Pattern Established

**Multi-Symbol Strategy Validation Pattern**:
- Validate required symbols early (first `on_bar()` call)
- Fail fast with clear, actionable error messages
- List both missing and available symbols
- Guide user on how to fix (include symbols in command)
- Only validate once per backtest (performance)

## User Impact

**Before**: Strategy silently produced 0 trades, difficult to debug

**After**: Clear error message on missing symbols, user knows exactly what to fix

## Related Fixes

This builds on the earlier **VIX Symbol Prefix Fix** (also 2025-11-06) which corrected the symbol from `'VIX'` to `'$VIX'` to match database naming convention.

## Files Modified

1. `jutsu_engine/strategies/Momentum_ATR.py`:
   - Added validation method and state tracking
   - Modified `__init__()` and `on_bar()` methods

2. `tests/unit/strategies/test_momentum_atr.py`:
   - Added 9 new validation tests
   - Added test helper method
   - Updated imports for `timedelta`

3. `CHANGELOG.md`:
   - Documented fix with evidence and validation results

## Future Considerations

**Potential Enhancements**:
- Strategy base class could provide validation framework
- CLI could validate required symbols before starting backtest
- Data handler could expose required symbol metadata
- Validation could suggest similar symbols if typo detected
