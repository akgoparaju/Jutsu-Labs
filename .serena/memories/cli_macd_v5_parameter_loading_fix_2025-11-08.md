# CLI Parameter Loading Fix for MACD_Trend_v5

**Date**: 2025-11-08
**Component**: CLI (`jutsu_engine/cli/main.py`)
**Status**: ✅ Fixed and Validated
**Impact**: Critical - Strategy now functional

---

## Problem Summary

MACD_Trend_v5 strategy failed to run despite correct .env configuration due to two sequential bugs in CLI parameter loading.

---

## Bug 1: Strategy-Specific Parameter Loading

### Error
```
✗ Backtest failed: MACD_Trend_v5 requires symbols ['VIX', 'NVDL', 'NVDA'] 
  but missing: ['VIX', 'NVDL', 'NVDA']. 
  Available symbols: ['QQQ', '$VIX', 'TQQQ']
```

### Root Cause Analysis

**Investigation Path**:
1. Read .env → Confirmed STRATEGY_MACD_V5_* parameters exist (lines 69-95)
2. Read CLI → Found only STRATEGY_MACD_V4_* parameters loaded (lines 52-62)
3. Traced parameter usage → All strategies used v4 variables (lines 564-569)

**Root Cause**: CLI had NO mechanism to differentiate between strategy versions
- Only v4 parameters loaded from .env
- No conditional logic based on strategy name
- v5 parameters completely ignored

### Solution Implemented

**Three-part fix in `jutsu_engine/cli/main.py`**:

**1. Load v5 Parameters** (added after line 62):
```python
# Load MACD_Trend_v5 parameters from .env
macd_v5_signal = os.getenv('STRATEGY_MACD_V5_SIGNAL_SYMBOL', 'QQQ')
macd_v5_bull = os.getenv('STRATEGY_MACD_V5_BULL_SYMBOL', 'TQQQ')
macd_v5_defense = os.getenv('STRATEGY_MACD_V5_DEFENSE_SYMBOL', 'QQQ')
vix_from_env = os.getenv('STRATEGY_MACD_V5_VIX_SYMBOL', 'VIX')
macd_v5_vix_symbol = f'${vix_from_env}' if not vix_from_env.startswith('$') else vix_from_env
macd_v5_vix_ema = int(os.getenv('STRATEGY_MACD_V5_VIX_EMA_PERIOD', '50'))
macd_v5_ema_calm = int(os.getenv('STRATEGY_MACD_V5_EMA_PERIOD_CALM', '200'))
macd_v5_atr_calm = float(os.getenv('STRATEGY_MACD_V5_ATR_STOP_CALM', '3.0'))
macd_v5_ema_choppy = int(os.getenv('STRATEGY_MACD_V5_EMA_PERIOD_CHOPPY', '75'))
macd_v5_atr_choppy = float(os.getenv('STRATEGY_MACD_V5_ATR_STOP_CHOPPY', '2.0'))
macd_v5_fast = int(os.getenv('STRATEGY_MACD_V5_FAST_PERIOD', '12'))
macd_v5_slow = int(os.getenv('STRATEGY_MACD_V5_SLOW_PERIOD', '26'))
macd_v5_signal_period = int(os.getenv('STRATEGY_MACD_V5_SIGNAL_PERIOD', '9'))
macd_v5_atr = int(os.getenv('STRATEGY_MACD_V5_ATR_PERIOD', '14'))
macd_v5_risk_bull = float(os.getenv('STRATEGY_MACD_V5_RISK_BULL', '0.025'))
macd_v5_alloc_defense = float(os.getenv('STRATEGY_MACD_V5_ALLOCATION_DEFENSE', '0.60'))
```

**2. Conditional Parameter Selection** (replaced lines 564-569):
```python
# Determine which parameter set to use based on strategy name
if strategy == "MACD_Trend_v5":
    # Use v5 parameters
    final_signal_symbol = signal_symbol if signal_symbol is not None else macd_v5_signal
    final_bull_symbol = bull_symbol if bull_symbol is not None else macd_v5_bull
    final_defense_symbol = defense_symbol if defense_symbol is not None else macd_v5_defense
    final_ema_trend = ema_trend_period if ema_trend_period is not None else macd_v5_ema_calm
    final_risk_bull = risk_bull if risk_bull is not None else macd_v5_risk_bull
    final_alloc_defense = allocation_defense if allocation_defense is not None else macd_v5_alloc_defense
    
    # v5-specific parameters
    final_vix_symbol = macd_v5_vix_symbol
    final_vix_ema = macd_v5_vix_ema
    final_ema_calm = macd_v5_ema_calm
    final_atr_calm = macd_v5_atr_calm
    final_ema_choppy = macd_v5_ema_choppy
    final_atr_choppy = macd_v5_atr_choppy
    
    # Override MACD/ATR with v5 values
    final_macd_fast = macd_fast_period if macd_fast_period is not None else macd_v5_fast
    final_macd_slow = macd_slow_period if macd_slow_period is not None else macd_v5_slow
    final_macd_signal = macd_signal_period if macd_signal_period is not None else macd_v5_signal_period
    final_atr_period = atr_period if atr_period is not None else macd_v5_atr
else:
    # Use v4 parameters (default for MACD_Trend_v4 and generic strategies)
    final_signal_symbol = signal_symbol if signal_symbol is not None else macd_v4_signal
    final_bull_symbol = bull_symbol if bull_symbol is not None else macd_v4_bull
    final_defense_symbol = defense_symbol if defense_symbol is not None else macd_v4_defense
    final_ema_trend = ema_trend_period if ema_trend_period is not None else macd_v4_ema
    final_risk_bull = risk_bull if risk_bull is not None else macd_v4_risk_bull
    final_alloc_defense = allocation_defense if allocation_defense is not None else macd_v4_alloc_defense
```

**3. Pass v5-Specific kwargs** (added after line 616):
```python
# MACD-Trend-v5 specific parameters
if strategy == "MACD_Trend_v5":
    if 'vix_symbol' in params:
        strategy_kwargs['vix_symbol'] = final_vix_symbol
    if 'vix_ema_period' in params:
        strategy_kwargs['vix_ema_period'] = final_vix_ema
    if 'ema_period_calm' in params:
        strategy_kwargs['ema_period_calm'] = final_ema_calm
    if 'atr_stop_calm' in params:
        strategy_kwargs['atr_stop_calm'] = Decimal(str(final_atr_calm))
    if 'ema_period_choppy' in params:
        strategy_kwargs['ema_period_choppy'] = final_ema_choppy
    if 'atr_stop_choppy' in params:
        strategy_kwargs['atr_stop_choppy'] = Decimal(str(final_atr_choppy))
```

### Validation After Bug 1 Fix
```
'signal_symbol': 'QQQ',      # ✅ CORRECT (was 'NVDA')
'bull_symbol': 'TQQQ',        # ✅ CORRECT (was 'NVDL')
'defense_symbol': 'QQQ',      # ✅ CORRECT (was 'NVDA')
```

But revealed **Bug 2**...

---

## Bug 2: VIX Symbol Normalization

### Error (After Bug 1 Fix)
```
✗ Backtest failed: MACD_Trend_v5 requires symbols ['VIX', 'QQQ', 'TQQQ'] 
  but missing: ['VIX']. 
  Available symbols: ['QQQ', 'TQQQ', '$VIX']
```

### Root Cause Analysis

**Investigation Path**:
1. Checked loaded data symbols → `['QQQ', 'TQQQ', '$VIX']` (with $ prefix)
2. Checked strategy expectations → `vix_symbol='VIX'` (no $ prefix)
3. Read other strategies → All hardcode `'$VIX'` with $ prefix
4. Traced CLI normalization → User input `VIX → $VIX` for database
5. Found inconsistency → .env loaded without normalization

**Root Cause**: Index symbol normalization not applied to .env parameters
- CLI normalizes user CLI input: `VIX → $VIX`
- Database stores: `$VIX`
- All hardcoded strategies use: `'$VIX'`
- v5 loaded from .env: `'VIX'` (no normalization)

### Solution Implemented

**Apply normalization to .env-loaded VIX symbol** (lines 68-70):
```python
# Before:
macd_v5_vix_symbol = os.getenv('STRATEGY_MACD_V5_VIX_SYMBOL', 'VIX')

# After:
vix_from_env = os.getenv('STRATEGY_MACD_V5_VIX_SYMBOL', 'VIX')
macd_v5_vix_symbol = f'${vix_from_env}' if not vix_from_env.startswith('$') else vix_from_env
```

**Logic**: Add $ prefix if not already present, maintaining consistency with:
- User CLI input normalization
- Database storage format
- Hardcoded strategy conventions

---

## Final Validation

### Command
```bash
jutsu backtest --strategy MACD_Trend_v5 --symbols QQQ,TQQQ,VIX --start 2020-01-01 --end 2024-12-31
```

### Results
```
2025-11-08 15:27:30 | CLI | INFO | Normalized index symbol: VIX → $VIX
2025-11-08 15:27:30 | CLI | INFO | Loaded strategy: MACD_Trend_v5 with params: {
  'signal_symbol': 'QQQ',           # ✅ From STRATEGY_MACD_V5_SIGNAL_SYMBOL
  'bull_symbol': 'TQQQ',            # ✅ From STRATEGY_MACD_V5_BULL_SYMBOL
  'defense_symbol': 'QQQ',          # ✅ From STRATEGY_MACD_V5_DEFENSE_SYMBOL
  'vix_symbol': '$VIX',             # ✅ Normalized from STRATEGY_MACD_V5_VIX_SYMBOL
  'vix_ema_period': 50,
  'ema_period_calm': 200,
  'atr_stop_calm': Decimal('3.0'),
  'ema_period_choppy': 75,
  'atr_stop_choppy': Decimal('2.0'),
  'macd_fast_period': 12,
  'macd_slow_period': 26,
  'macd_signal_period': 9,
  'atr_period': 14,
  'risk_bull': Decimal('0.025'),
  'allocation_defense': Decimal('0.60')
}

Final Portfolio Value: $41,656.57
Total Return: 316.57%
Sharpe Ratio: 1.80
Total Trades: 45
```

### Verification Checklist
- ✅ All v5 parameters loaded from .env correctly
- ✅ VIX symbol normalized to `$VIX`
- ✅ VIX regime detection working (CALM/CHOPPY switching)
- ✅ Backtest completes successfully
- ✅ No breaking changes to v4 (backward compatibility)
- ✅ Regression test: v4 still works with original parameters

---

## Pattern Established for Future Strategies

### When Adding New Strategy Versions

**1. Add .env Parameters**:
```bash
# In .env
STRATEGY_<NAME>_<VERSION>_PARAMETER_NAME=value
```

**2. Load in CLI Module Scope** (after existing loads):
```python
# Load STRATEGY_<NAME>_<VERSION> parameters
param1 = os.getenv('STRATEGY_<NAME>_<VERSION>_PARAM1', 'default')
param2 = int(os.getenv('STRATEGY_<NAME>_<VERSION>_PARAM2', '42'))
# Apply normalization if needed (e.g., for index symbols)
```

**3. Add Conditional Selection** (in backtest function):
```python
if strategy == "<StrategyName>_<version>":
    final_param = cli_arg if cli_arg is not None else env_var
else:
    # Default/fallback behavior
```

**4. Pass Strategy-Specific kwargs** (after base kwargs):
```python
if strategy == "<StrategyName>_<version>":
    if 'version_specific_param' in params:
        strategy_kwargs['version_specific_param'] = final_value
```

### Symbol Normalization Pattern

**For any index symbol loaded from .env**:
```python
symbol_from_env = os.getenv('STRATEGY_X_INDEX_SYMBOL', 'VIX')
normalized_symbol = f'${symbol_from_env}' if not symbol_from_env.startswith('$') else symbol_from_env
```

**Applies to**: VIX, DJI, SPX, IXIC, RUT, and other index symbols

---

## Files Modified

- `jutsu_engine/cli/main.py`:
  - Lines 63-77: Load v5 parameters
  - Lines 68-70: VIX symbol normalization
  - Lines 564-598: Conditional parameter selection
  - Lines 617-631: v5-specific kwargs

- `CHANGELOG.md`: Comprehensive documentation added

---

## Key Learnings

1. **Multi-Version Parameter Management**: Need explicit conditional logic for strategy versions
2. **Symbol Normalization Consistency**: All symbol loading paths must apply same normalization
3. **Systematic Debugging**: Sequential root cause analysis revealed two related bugs
4. **Validation at Each Step**: Testing after each fix prevented compound errors
5. **Backward Compatibility**: Else branch maintains existing v4 behavior

---

## Related

- Strategy: `jutsu_engine/strategies/MACD_Trend_v5.py`
- Strategy Spec: `jutsu_engine/strategies/MACD_Trend-v5.md`
- .env Configuration: `.env` (lines 69-95)
- Agent: CLI_AGENT handled both fixes
