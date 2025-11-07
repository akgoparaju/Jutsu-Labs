# CLI Index Symbol Normalization Fix

**Date**: 2025-11-06
**Agent**: CLI_AGENT (via `/orchestrate` routing)
**Issue**: Shell variable expansion strips $ from index symbols before CLI receives them

## Problem Diagnosed

**User Report**: "clearly script is unable to process $ sign, I guess"

**Evidence Chain**:

1. **User Command**:
   ```bash
   jutsu backtest --strategy Momentum_ATR --symbols QQQ,$VIX,TQQQ,SQQQ ...
   ```

2. **Shell Processing** (BEFORE Python CLI):
   - Bash sees `$VIX` as variable reference (shell special character)
   - Tries to expand environment variable `$VIX`
   - Variable `VIX` doesn't exist in environment → expands to empty string
   - Shell passes to CLI: `--symbols QQQ,,TQQQ,SQQQ` ← Double comma!

3. **CLI Parser Receives**:
   ```python
   value = "QQQ,,TQQQ,SQQQ"
   split_by_comma = ['QQQ', '', 'TQQQ', 'SQQQ']
   filtered = ['QQQ', 'TQQQ', 'SQQQ']  # Empty string removed by if s.strip()
   ```

4. **Log Evidence**:
   - Line 2: `BacktestRunner initialized: QQQ, TQQQ, SQQQ 1D` ← Missing $VIX!
   - Line 9: `MultiSymbolDataHandler initialized: 3 symbols, 756 total bars`
   - Strategy validation: `missing: ['$VIX']`

5. **Database Check**:
   ```sql
   SELECT DISTINCT symbol FROM market_data WHERE symbol LIKE '$%' → $VIX, $DJI
   ```

**Root Cause**: Shell variable expansion is a fundamental Bash feature. The `$` character triggers variable substitution before the command is executed. This affects ALL index symbols in the database: `$VIX`, `$DJI`.

## Solution Implemented

**User Experience Improvement**: Make CLI user-friendly by accepting index symbols WITHOUT `$` prefix.

### Code Changes

**File**: `jutsu_engine/cli/main.py`

1. **Added Known Index Symbols Set** (line 46):
   ```python
   # Known index symbols that require $ prefix in database
   INDEX_SYMBOLS = {'VIX', 'DJI', 'SPX', 'NDX', 'RUT', 'VXN'}
   ```

2. **Added Normalization Function** (lines 48-81):
   ```python
   def normalize_index_symbols(symbols: tuple) -> tuple:
       """
       Normalize index symbols by adding $ prefix if missing.
       
       Allows users to type 'VIX' instead of escaping '$VIX' in shell.
       
       Examples:
           ('QQQ', 'VIX', 'TQQQ') → ('QQQ', '$VIX', 'TQQQ')
           ('QQQ', '$VIX', 'TQQQ') → ('QQQ', '$VIX', 'TQQQ')  # Already prefixed
       """
       if not symbols:
           return symbols
       
       normalized = []
       for symbol in symbols:
           # Check if it's a known index symbol WITHOUT $ prefix
           if symbol.upper() in INDEX_SYMBOLS and not symbol.startswith('$'):
               normalized_symbol = f'${symbol.upper()}'
               logger.info(f"Normalized index symbol: {symbol} → {normalized_symbol}")
               normalized.append(normalized_symbol)
           else:
               normalized.append(symbol.upper())
       
       return tuple(normalized)
   ```

3. **Integrated in Backtest Command** (lines 405-410):
   ```python
   # Determine which symbols to use
   if symbols:
       # Multi-symbol mode (--symbols takes precedence)
       # Normalize index symbols (add $ prefix for VIX, DJI, etc.)
       normalized_symbols = normalize_index_symbols(symbols)
       symbol_list = list(normalized_symbols)
       is_multi_symbol = True
   ```

4. **Updated Help Text** (line 228):
   - Mentions auto-normalization
   - Shows new syntax examples

5. **Updated Docstring** (line 373):
   - Added example: `--symbols QQQ,VIX,TQQQ,SQQQ`
   - Documented index symbol auto-normalization

### Test Changes

**File**: `tests/unit/cli/test_symbol_normalization.py` (NEW)

**8 Comprehensive Tests**:
1. `test_normalize_vix_symbol` - VIX → $VIX
2. `test_normalize_dji_symbol` - DJI → $DJI
3. `test_already_prefixed_unchanged` - $VIX → $VIX (idempotent)
4. `test_regular_symbols_unchanged` - AAPL → AAPL (no change)
5. `test_case_insensitive` - vix → $VIX (uppercase)
6. `test_multiple_index_symbols` - Multiple at once
7. `test_empty_tuple` - Empty tuple handling
8. `test_none_handling` - None handling

## Validation Results

### Unit Tests
✅ **All 8 tests pass** in `test_symbol_normalization.py`

### Manual Tests

**Test 1: New Syntax (No Escaping)**
```bash
jutsu backtest --strategy Momentum_ATR --symbols QQQ,VIX,TQQQ,SQQQ \
    --timeframe 1D --start 2024-01-01 --end 2024-12-31 --capital 100000
```

**Output**:
```
2025-11-06 17:35:57 | CLI | INFO | Normalized index symbol: VIX → $VIX
BACKTEST: QQQ, $VIX, TQQQ, SQQQ 1D
...
MultiSymbolDataHandler: QQQ 1D ... (252 bars)
MultiSymbolDataHandler: $VIX 1D ... (252 bars)  ← Works!
MultiSymbolDataHandler: TQQQ 1D ... (252 bars)
MultiSymbolDataHandler: SQQQ 1D ... (252 bars)
MultiSymbolDataHandler initialized: 4 symbols, 1008 total bars
...
Final Value:        $103,682.97
Total Return:       3.68%
Annualized Return:  3.70%
Sharpe Ratio:       2.78
```

✅ **Success**: All 4 symbols loaded, backtest completed with VIX data

**Test 2: Backward Compatibility (Escaped Syntax)**
```bash
jutsu backtest --strategy Momentum_ATR --symbols QQQ,\$VIX,TQQQ,SQQQ \
    --timeframe 1D --start 2024-01-01 --end 2024-01-31 --capital 100000
```

**Output**:
```
BACKTEST: QQQ, $VIX, TQQQ, SQQQ 1D
MultiSymbolDataHandler: QQQ 1D ... (21 bars)
MultiSymbolDataHandler: $VIX 1D ... (21 bars)
```

✅ **Success**: No normalization log (already prefixed), backward compatible

**Test 3: Case Insensitivity**
```bash
jutsu backtest --strategy Momentum_ATR --symbols qqq,vix,tqqq,sqqq \
    --timeframe 1D --start 2024-01-01 --end 2024-01-31 --capital 100000
```

**Output**:
```
2025-11-06 17:36:30 | CLI | INFO | Normalized index symbol: VIX → $VIX
BACKTEST: QQQ, $VIX, TQQQ, SQQQ 1D
```

✅ **Success**: Lowercase normalized to uppercase

## User Experience Impact

### Before Fix (Required Escaping)
```bash
# User had to understand shell escaping rules
jutsu backtest --symbols QQQ,\$VIX,TQQQ,SQQQ      # Awkward!

# OR use single quotes (less flexible)
jutsu backtest --symbols 'QQQ,$VIX,TQQQ,SQQQ'    # Works but rigid

# Confusion if user forgot to escape
jutsu backtest --symbols QQQ,$VIX,TQQQ,SQQQ      # Silent failure! ❌
```

### After Fix (Natural Syntax)
```bash
# User can type index symbols naturally
jutsu backtest --symbols QQQ,VIX,TQQQ,SQQQ       # Easy! ✅

# Escaped syntax still works (backward compatible)
jutsu backtest --symbols QQQ,\$VIX,TQQQ,SQQQ     # Also works ✅

# Case insensitive
jutsu backtest --symbols QQQ,vix,TQQQ,SQQQ       # Works too ✅
```

## Pattern Established

**CLI Symbol Normalization Pattern**:
- Maintain database naming conventions (index symbols use `$` prefix)
- Make CLI user-friendly by accepting symbols without special characters
- Auto-normalize known index symbols transparently
- Log normalization for debugging visibility
- Preserve backward compatibility with escaped syntax
- Case-insensitive handling for better UX

## Known Index Symbols

**Currently in Database**:
- `$VIX` - CBOE Volatility Index
- `$DJI` - Dow Jones Industrial Average

**Supported by Normalization** (ready for future use):
- `$VIX` - CBOE Volatility Index
- `$DJI` - Dow Jones Industrial Average
- `$SPX` - S&P 500 Index
- `$NDX` - NASDAQ-100 Index
- `$RUT` - Russell 2000 Index
- `$VXN` - NASDAQ Volatility Index

## Related Fixes

This builds on two earlier fixes (also 2025-11-06):

1. **VIX Symbol Prefix Fix**: Corrected strategy code to use `'$VIX'` instead of `'VIX'`
2. **Symbol Validation Fix**: Added validation to fail fast when required symbols missing

Together, these 3 fixes form a complete solution:
- Database uses `$VIX` (prefix convention)
- Strategy expects `$VIX` (matches database)
- Strategy validates all symbols present (fail fast)
- CLI normalizes user input `VIX` → `$VIX` (UX improvement)

## Files Modified

1. `jutsu_engine/cli/main.py`:
   - Added `INDEX_SYMBOLS` set
   - Added `normalize_index_symbols()` function
   - Integrated normalization in `backtest` command
   - Updated help text and docstrings

2. `tests/unit/cli/test_symbol_normalization.py` (NEW):
   - 8 comprehensive unit tests
   - Test happy path, edge cases, backward compatibility

3. `CHANGELOG.md`:
   - Documented fix with evidence and validation results

## Future Considerations

**Potential Enhancements**:
- Add more index symbols as they're used (`$SPX`, `$NDX`, etc.)
- Consider making index symbol list configurable
- Extend normalization to other CLI commands (sync, status, validate)
- Add shell completion hints for index symbols
