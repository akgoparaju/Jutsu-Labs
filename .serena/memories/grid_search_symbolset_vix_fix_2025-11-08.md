# Grid Search SymbolSet Fix for MACD_Trend_v5

**Date**: 2025-11-08
**Component**: Grid Search (`jutsu_engine/application/grid_search_runner.py`)
**Status**: ✅ Fixed and Validated
**Impact**: Critical - Enables v5 grid search functionality

---

## Problem Summary

Grid search failed to load MACD_Trend_v5 configurations due to SymbolSet dataclass not supporting the vix_symbol parameter required for VIX regime detection.

---

## Error Details

**Error Message**:
```
TypeError: SymbolSet.__init__() got an unexpected keyword argument 'vix_symbol'. 
Did you mean 'bull_symbol'?
```

**Location**: `grid_search_runner.py:229` in `load_config()` method
**Trigger**: Loading v5 YAML config with vix_symbol field

**Example Config** (grid_search_macd_v5.yaml):
```yaml
symbol_sets:
  - name: "QQQ_TQQQ_VIX"
    signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: QQQ
    vix_symbol: VIX  # ← This field caused TypeError
```

---

## Root Cause Analysis

**Historical Context**:
- SymbolSet designed for MACD_Trend_v4 (3 symbols: signal, bull, defense)
- MACD_Trend_v5 added VIX regime detection (4th symbol requirement)
- Grid search configuration system not updated for v5

**Strategy Symbol Requirements**:
- **v4**: 3 symbols (signal, bull, defense)
- **v5**: 4 symbols (signal, bull, defense, VIX)

**Original SymbolSet Design**:
```python
@dataclass
class SymbolSet:
    name: str
    signal_symbol: str
    bull_symbol: str
    defense_symbol: str  # ← No vix_symbol field!
```

---

## Solution Implemented

**Approach**: Add optional vix_symbol field for backward compatibility

### Change 1: SymbolSet Dataclass (Lines 42-64)

**Added optional vix_symbol field**:
```python
@dataclass
class SymbolSet:
    """
    Grouped symbol configuration (prevents invalid combinations).
    
    Attributes:
        name: Human-readable name (e.g., "NVDA-NVDL" or "QQQ-TQQQ-VIX")
        signal_symbol: Symbol for signals (e.g., NVDA, QQQ)
        bull_symbol: Leveraged bull symbol (e.g., NVDL, TQQQ)
        defense_symbol: Defensive position symbol (e.g., NVDA, QQQ)
        vix_symbol: Optional VIX symbol for regime detection (e.g., VIX)
                   Required for MACD_Trend_v5 and other VIX-filtered strategies
    """
    name: str
    signal_symbol: str
    bull_symbol: str
    defense_symbol: str
    vix_symbol: Optional[str] = None  # ✅ NEW: Optional for backward compatibility
```

**Design Decision**: Optional field (None default) maintains v4 compatibility

---

### Change 2: RunConfig.to_dict() (Lines 103-123)

**Conditional vix_symbol inclusion in CSV exports**:
```python
def to_dict(self) -> Dict[str, Any]:
    """
    Flatten for CSV export.
    
    Returns:
        Dictionary with flattened structure for CSV row
    """
    result = {
        'run_id': self.run_id,
        'symbol_set': self.symbol_set.name,
        'signal_symbol': self.symbol_set.signal_symbol,
        'bull_symbol': self.symbol_set.bull_symbol,
        'defense_symbol': self.symbol_set.defense_symbol,
        **self.parameters
    }
    
    # Include vix_symbol if present (for v5 strategies)
    if self.symbol_set.vix_symbol is not None:
        result['vix_symbol'] = self.symbol_set.vix_symbol
    
    return result
```

**Impact**:
- v5 CSV exports: Include vix_symbol column
- v4 CSV exports: Do NOT include vix_symbol column (clean separation)

---

### Change 3: load_config() Validation (Lines 242-250)

**Strategy-specific validation for v5 requirements**:
```python
# Validate VIX symbol requirement for v5 strategies
strategy_name = data['strategy']
if strategy_name == 'MACD_Trend_v5':
    missing_vix = [s.name for s in symbol_sets if s.vix_symbol is None]
    if missing_vix:
        raise ValueError(
            f"Strategy '{strategy_name}' requires vix_symbol for all symbol_sets. "
            f"Missing vix_symbol in: {', '.join(missing_vix)}"
        )
```

**Benefits**:
- Fails fast at config load (not during backtest)
- Clear error message guides user to fix config
- No validation overhead for v4 configs
- Extensible to future VIX-based strategies

---

### Change 4: _run_single_backtest() (Lines 447-478)

**Conditional VIX data loading and parameter passing**:
```python
# Prepare symbols list (conditionally include vix_symbol)
symbols = [
    run_config.symbol_set.signal_symbol,
    run_config.symbol_set.bull_symbol,
    run_config.symbol_set.defense_symbol
]
if run_config.symbol_set.vix_symbol is not None:
    symbols.append(run_config.symbol_set.vix_symbol)

# Prepare strategy params (conditionally include vix_symbol)
strategy_params = {
    'signal_symbol': run_config.symbol_set.signal_symbol,
    'bull_symbol': run_config.symbol_set.bull_symbol,
    'defense_symbol': run_config.symbol_set.defense_symbol,
    **run_config.parameters
}
if run_config.symbol_set.vix_symbol is not None:
    strategy_params['vix_symbol'] = run_config.symbol_set.vix_symbol

# Prepare backtest config
config = {
    **self.config.base_config,
    'start_date': start_date,
    'end_date': end_date,
    'symbols': symbols,  # ✅ VIX included if present
    'strategy_name': self.config.strategy_name,
    'strategy_params': strategy_params,  # ✅ vix_symbol included if present
}
```

**Impact**:
- v5 backtests: VIX data loaded, vix_symbol passed to strategy constructor
- v4 backtests: No VIX data loaded, no vix_symbol parameter

---

## Validation Results

### Test 1: Config Loading (v5)
```python
config = GridSearchRunner.load_config('grid-configs/examples/grid_search_macd_v5.yaml')
# ✅ PASSED
# Strategy: MACD_Trend_v5
# Symbol sets: 1 (QQQ_TQQQ_VIX with vix_symbol=VIX)
# Total combinations: 432
```

### Test 2: Combination Generation
```python
runner = GridSearchRunner(config)
combos = runner.generate_combinations()
# ✅ PASSED: 432 combinations
# First combo includes: vix_symbol='VIX'
```

### Test 3: CSV Export Structure
```python
combo.to_dict()
# ✅ v5: {'run_id': '001', ..., 'vix_symbol': 'VIX'}
# ✅ v4: {'run_id': '001', ...}  # No vix_symbol key
```

### Test 4: Validation (Missing vix_symbol)
```python
# Config: MACD_Trend_v5 with symbol_set missing vix_symbol
# ✅ PASSED: Clear error message
# "Strategy 'MACD_Trend_v5' requires vix_symbol for all symbol_sets. Missing vix_symbol in: QQQ_TQQQ"
```

### Test 5: Backward Compatibility (v4)
```python
# v4 config loading and execution
# ✅ PASSED: Works exactly as before
# ✅ No vix_symbol in symbols list
# ✅ No vix_symbol in strategy_params
# ✅ CSV does not include vix_symbol column
```

---

## Backward Compatibility

✅ **100% Backward Compatible with v4 Configs**:
- Optional field (None default) doesn't break existing configs
- Conditional logic only activates for v5
- v4 CSV exports unchanged (no vix_symbol column)
- v4 backtests unchanged (no VIX data loaded)

**Migration Path for v4 → v5**:
1. Copy v4 grid search YAML
2. Add `vix_symbol: VIX` to each symbol_set
3. Change `strategy: MACD_Trend_v4` to `strategy: MACD_Trend_v5`
4. Add v5-specific parameters (vix_ema_period, ema_period_calm, etc.)

---

## Files Modified

- `jutsu_engine/application/grid_search_runner.py`:
  - Lines 42-64: SymbolSet dataclass (vix_symbol field)
  - Lines 103-123: RunConfig.to_dict() (conditional export)
  - Lines 242-250: load_config() (v5 validation)
  - Lines 447-478: _run_single_backtest() (conditional VIX)

---

## Pattern Established

**For Future Strategies Requiring Additional Symbols**:

1. **Add optional field to SymbolSet**:
   ```python
   new_symbol: Optional[str] = None
   ```

2. **Add validation in load_config()**:
   ```python
   if strategy_name == 'StrategyName':
       if symbol_set.new_symbol is None:
           raise ValueError(...)
   ```

3. **Update _run_single_backtest()**:
   ```python
   if run_config.symbol_set.new_symbol is not None:
       symbols.append(...)
       strategy_params['new_symbol'] = ...
   ```

4. **Update to_dict()** for CSV export if needed

---

## Key Learnings

1. **Optional Fields for Extensibility**: Using Optional with None default maintains backward compatibility while enabling new features
2. **Fail-Fast Validation**: Validate requirements at config load, not during backtest execution
3. **Conditional Logic**: Apply new behavior only when relevant (check if field is not None)
4. **Clear Error Messages**: Guide users to fix configuration issues with specific, actionable error messages
5. **CSV Export Flexibility**: Conditional column inclusion keeps v4/v5 exports clean and differentiated

---

## Related

- Strategy: `jutsu_engine/strategies/MACD_Trend_v5.py`
- Strategy Spec: `jutsu_engine/strategies/MACD_Trend-v5.md`
- Grid Search Config: `grid-configs/examples/grid_search_macd_v5.yaml`
- Previous Fix: CLI parameter loading (cli_macd_v5_parameter_loading_fix_2025-11-08)
- Agent: APPLICATION layer agent (Grid Search Runner module)
