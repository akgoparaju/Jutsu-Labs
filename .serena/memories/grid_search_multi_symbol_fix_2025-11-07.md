# Grid Search Multi-Symbol Bug Fix - 2025-11-07

## Issue Summary
Grid search was failing for multi-symbol strategies (like MACD_Trend_v4) with error: "MACD_Trend_v4 requires symbols ['NVDA', 'NVDL'] but missing: ['NVDL']"

## Root Cause
**Location**: `jutsu_engine/application/grid_search_runner.py:447`

GridSearchRunner's `_run_single_backtest()` method only passed `signal_symbol` to BacktestRunner:
```python
'symbols': [run_config.symbol_set.signal_symbol],  # Only 1 symbol!
```

But multi-symbol strategies require ALL symbols from SymbolSet (signal, bull, defense) to be loaded as market data.

## Data Flow
1. GridSearchRunner creates config with 'symbols' list
2. BacktestRunner receives config and loads data for symbols
3. Strategy init validates all required symbols are present
4. **Failure**: Strategy expects 3 symbols but only 1 was loaded

## Fix Applied
**File**: `grid_search_runner.py`
**Lines**: 447-451
**Change**:
```python
# BEFORE:
'symbols': [run_config.symbol_set.signal_symbol],

# AFTER:
'symbols': [
    run_config.symbol_set.signal_symbol,
    run_config.symbol_set.bull_symbol,
    run_config.symbol_set.defense_symbol
],
```

## Implementation Notes
- Multi-line format for readability
- Handles duplicate symbols gracefully (e.g., NVDA as both signal and defense)
- BacktestRunner/DataHandler handle duplicate symbol requests efficiently
- No need to deduplicate - the data layer handles it

## Validation
✅ **Unit Tests**: 27/27 passing in test_grid_search_runner.py
✅ **Integration**: Verified in logs - "BacktestRunner initialized: NVDA, NVDL, NVDA"
✅ **Backward Compatibility**: Maintains all existing functionality

## Impact
- Grid search now works with MACD_Trend_v4 and other multi-symbol strategies
- No more symbol validation errors
- Symbol sets (NVDA-NVDL, QQQ-TQQQ) execute correctly

## Related Context
- **SymbolSet**: Data structure containing signal_symbol, bull_symbol, defense_symbol
- **MACD_Trend_v4**: Strategy requiring 3 symbols for indicator calculation and position management
- **BacktestRunner**: Expects 'symbols' list to load all required market data

## Future Considerations
- Consider adding validation in GridSearchRunner to check strategy symbol requirements
- Add unit test specifically for multi-symbol symbol set handling
- Document SymbolSet design pattern in grid search guide

## Agent
GRID_SEARCH_AGENT (APPLICATION layer), coordinated by ORCHESTRATOR with Sequential MCP analysis