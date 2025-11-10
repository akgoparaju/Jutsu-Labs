# Grid Search Baseline Calculation - Config Object Access Fix

**Date**: 2025-11-09
**Type**: Bug Fix
**Severity**: Medium (Feature broken, no data corruption)
**Module**: Application Layer - GridSearchRunner
**Status**: ✅ RESOLVED

## Issue Summary

Grid search summary CSV files were missing baseline statistics - all Alpha values showed "N/A" instead of calculated comparison metrics. This prevented users from comparing strategy performance against buy-and-hold baseline (QQQ).

**Affected Run**: `grid_search_MACD_Trend_v6_2025-11-09_211621` (all 432 runs)

## Root Cause Analysis

### Technical Details

**Location**: `jutsu_engine/application/grid_search_runner.py:857`

**Error**: `TypeError: 'Config' object is not subscriptable`

**Problem Code**:
```python
# Line 856-857
db_config = get_config()  # Returns Config object from jutsu_engine.utils.config
database_url = self.config.base_config.get('database_url', db_config['database_url'])  # ❌
```

### Why It Failed

The `Config` class (from `jutsu_engine/utils/config.py`) implements configuration properties as class attributes with `@property` decorators:

```python
# config.py:146
@property
def database_url(self) -> str:
    """Get database URL."""
    return self.get('DATABASE_URL', 'sqlite:///data/market_data.db')
```

**Attribute Access Required**: `config.database_url` ✅
**Subscript Access Not Supported**: `config['database_url']` ❌

### Error Chain

1. Grid search completes all 432 backtests successfully
2. During summary generation, calls `_calculate_baseline_for_grid_search()` (line 819)
3. Line 857 attempts subscript access: `db_config['database_url']`
4. Python raises `TypeError: 'Config' object is not subscriptable`
5. Exception caught at line 928, logs error, returns `None`
6. `_generate_summary_comparison()` (line 564) receives `None` for baseline
7. Line 620 check fails: `if baseline_total_return is not None`
8. Alpha calculation skipped, all runs get "N/A" for Alpha column

### Log Evidence

```
2025-11-09 21:16:21 | APPLICATION.GRID_SEARCH | INFO | Calculating buy-and-hold baseline (QQQ)...
2025-11-09 21:16:21 | APPLICATION.GRID_SEARCH | ERROR | Baseline calculation failed: 'Config' object is not subscriptable
2025-11-09 21:16:21 | APPLICATION.GRID_SEARCH | WARNING | Baseline calculation failed or insufficient data. Summary CSV will not include baseline row (000) or alpha column.
```

## Resolution

### Fix Applied

**File**: `jutsu_engine/application/grid_search_runner.py`
**Line**: 857
**Change**: Single line - subscript to attribute access

```python
# Before (BROKEN):
database_url = self.config.base_config.get('database_url', db_config['database_url'])

# After (FIXED):
database_url = self.config.base_config.get('database_url', db_config.database_url)
```

### Codebase Verification

Searched all occurrences of `get_config()` usage:
- ✅ `scripts/example_backtest.py` - uses attribute access
- ✅ `jutsu_engine/optimization/results.py` - uses attribute access
- ✅ `jutsu_engine/cli/main.py` (multiple) - uses attribute access
- ✅ `jutsu_engine/application/backtest_runner.py` - uses attribute access
- ❌ `jutsu_engine/application/grid_search_runner.py:857` - **ONLY occurrence of subscript access**

**Conclusion**: Isolated bug, not a systemic pattern issue.

## Impact

### Before Fix
- Grid search runs completed but baseline calculation failed silently
- Summary CSV Alpha column: All values "N/A"
- Unable to compare strategy vs baseline performance
- Grid search comparison metrics unusable

### After Fix
- Baseline calculation succeeds during grid search
- Summary CSV Alpha column: Numeric values (e.g., "1.50" = 50% better than baseline)
- Full baseline comparison metrics available (Alpha, Excess Return, Return Ratio)
- Grid search output complete and functional

## Testing Recommendations

### Validation Test
```bash
# Run grid search to verify fix
jutsu grid-search --config grid-configs/examples/grid_search_macd_v6.yaml
```

### Expected Results
- Grid search completes without TypeError
- Log shows: "Baseline calculated: QQQ X.XX% total return"
- Summary CSV includes:
  - Row 000: Baseline (QQQ) performance
  - Alpha column: Numeric values for all runs (not "N/A")
  - Baseline comparison metrics populated

### Alpha Calculation Formula
```python
alpha = strategy_total_return / baseline_total_return
# Example: 1.50 = Strategy returned 50% more than baseline
# Example: 0.82 = Strategy returned 18% less than baseline
```

## Related Files

**Modified**:
- `jutsu_engine/application/grid_search_runner.py:857` (bug fix)
- `CHANGELOG.md:147-197` (documentation)

**Reference**:
- `jutsu_engine/utils/config.py:146` (Config.database_url property)
- `jutsu_engine/application/grid_search_runner.py:819-931` (_calculate_baseline_for_grid_search method)
- `jutsu_engine/application/grid_search_runner.py:564-698` (_generate_summary_comparison method)

## Lessons Learned

### Config Object Access Pattern
Always use attribute access for Config objects:
```python
config = get_config()
db_url = config.database_url  # ✅ Correct
db_url = config['database_url']  # ❌ TypeError
```

### Why This Pattern
- Config class uses `@property` decorators for convenience methods
- Properties are accessed like attributes, not dictionary keys
- Maintains clean API while allowing dynamic configuration loading

### Detection
- Look for `get_config()` followed by subscript brackets `[]`
- Should be replaced with dot notation for property access

## Future Prevention

### Code Review Checklist
- [ ] Verify Config object access uses attribute notation
- [ ] Check for subscript access on non-dict objects
- [ ] Test grid search baseline calculation in CI/CD

### Testing Strategy
- Unit test for `_calculate_baseline_for_grid_search()` with mocked database
- Integration test for full grid search with baseline comparison
- Verify summary CSV Alpha column contains numeric values

## Keywords
`grid search`, `baseline calculation`, `Config object`, `TypeError`, `subscriptable`, `Alpha`, `summary CSV`, `database_url`, `property decorator`, `attribute access`
