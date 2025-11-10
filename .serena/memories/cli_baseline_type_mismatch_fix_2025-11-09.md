# CLI Baseline Type Mismatch Fix (2025-11-09)

## Issue Summary

**Error**: `TypeError: unsupported operand type(s) for -: 'decimal.Decimal' and 'float'`
**Location**: `jutsu_engine/cli/main.py:329` in `_display_comparison_section()`
**Severity**: 🔴 HIGH (breaks CLI after successful backtest completion)

## Root Cause Analysis

### Type Inconsistency
The baseline comparison feature (implemented 2025-11-09) introduced a type mismatch between:
- `strategy_return` (float) from BacktestRunner results dictionary
- `baseline_return` (Decimal) from PerformanceAnalyzer baseline dictionary

### Why This Happened
1. **BacktestRunner** stores metrics as **float** in results dict (line 317-407)
2. **PerformanceAnalyzer** uses **Decimal** for financial precision (lines 903-975)
3. **CLI** extracts both without type conversion (lines 307-308)
4. Python **cannot** perform arithmetic between Decimal and float without explicit cast

### Error Location
```python
# Line 329: Type mismatch error
excess_return = strategy_return - baseline_return  # float - Decimal → TypeError

# Line 336: Also problematic  
ratio = strategy_return / baseline_return  # float / Decimal → TypeError
```

## Resolution

### Fix Applied
**File**: `jutsu_engine/cli/main.py` (lines 306-308)
**Change**: Cast both values to float at extraction

```python
# Before (broken):
strategy_return = results.get('total_return', 0)  # float
baseline_return = baseline.get('baseline_total_return', 0)  # Decimal

# After (fixed):
strategy_return = float(results.get('total_return', 0))  # float
baseline_return = float(baseline.get('baseline_total_return', 0))  # float
```

### Why This Fix Works
1. **Explicit Type Conversion**: Forces both values to float at extraction point
2. **Type Consistency**: Lines 329 and 336 now operate on float/float (compatible)
3. **Minimal Impact**: Only affects display logic, not financial calculations
4. **Backward Compatible**: Works with both Decimal and float inputs

## Testing

### Test Command
```bash
jutsu backtest --strategy MACD_Trend_v6 --symbols QQQ,TQQQ,VIX --start 2020-04-01 --end 2025-04-01
```

### Test Results
✅ **Baseline section displays correctly**:
```
BASELINE (Buy & Hold QQQ):
  Final Value:        $25,412.61
  Total Return:       154.13%
  Annualized Return:  20.52%
```

✅ **Comparison section displays correctly**:
```
PERFORMANCE vs BASELINE:
  Alpha:              1.50x (+50.13% outperformance)
  Excess Return:      +77.27%
  Return Ratio:       1.50:1 (strategy:baseline)
```

✅ **No type errors during execution**

## Prevention

### Future Considerations
1. **Type Hints**: Add explicit type hints to clarify expected types
2. **Validation**: Add type checking in _display_comparison_section()
3. **Documentation**: Document that CLI display uses float for arithmetic

### Related Components
- **BacktestRunner** (`jutsu_engine/application/backtest_runner.py`): Returns float metrics
- **PerformanceAnalyzer** (`jutsu_engine/performance/analyzer.py`): Uses Decimal for calculations
- **CLI Display** (`jutsu_engine/cli/main.py`): Handles presentation (float acceptable)

## Key Takeaway

**When mixing financial calculation code (Decimal) with display code (float), always cast explicitly at interface boundaries to prevent type mismatch errors.**

## Related Memories
- `baseline_comparison_feature_2025-11-09`: Original feature implementation
- `csv_export_feature_2025-11-07`: Similar type handling in CSV export

## Documentation
- **CHANGELOG.md**: Updated with Fixed section (lines 10-39)
- **Test Coverage**: Verified with 5-year MACD_Trend_v6 backtest
