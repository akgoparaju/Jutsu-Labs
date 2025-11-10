# Grid Search Configuration Schema Fix (2025-11-09)

## Problem
Grid search for MACD_Trend_v6 failed with: `ValueError: Missing required keys: strategy, base_config`

## Root Cause Analysis

The `grid_search_macd_v6.yaml` configuration file was written in an incompatible format that didn't match the validated schema expected by `GridSearchRunner.load_config()`.

### Five Critical Issues

1. **Wrong Top-Level Key**
   - Had: `strategy_class: "MACD_Trend_v6"`
   - Expected: `strategy: "MACD_Trend_v6"`
   - Why: GridSearchRunner validates for `strategy` key at line 227

2. **Missing base_config Section**
   - Had: Flat structure with `start_date`, `end_date`, `initial_capital` at root
   - Expected: All wrapped in `base_config:` section
   - Why: GridSearchRunner expects `base_config` dictionary at line 227

3. **Missing Required Keys**
   - Missing: `timeframe` (required at line 253)
   - Missing: `commission` (optional but standard)
   - Missing: `slippage` (optional but standard)
   - Why: Secondary validation checks for these keys in base_config

4. **Wrong symbol_sets Structure**
   - Had: `symbols: ["QQQ", "TQQQ", "$VIX"]` (list format)
   - Expected: Individual keys (signal_symbol, bull_symbol, defense_symbol, vix_symbol)
   - Why: SymbolSet dataclass requires individual keys (line 44-63)

5. **Unrecognized Sections**
   - Had: `fixed_parameters:`, `output:`, `optimization_metrics:`, `parallel:`, `reports:`
   - Expected: Symbol keys in symbol_sets, parameters as single-value lists
   - Why: These sections are not part of the validated schema

## Solution

Rewrote `grid-configs/examples/grid_search_macd_v6.yaml` to match the working v4 config pattern.

### Correct Schema Format

```yaml
# Strategy identification
strategy: "MACD_Trend_v6"

# Symbol groupings (prevent invalid combinations)
symbol_sets:
  - name: "QQQ_TQQQ_VIX"
    signal_symbol: "QQQ"      # For MACD/EMA signals
    bull_symbol: "TQQQ"        # Leveraged position
    defense_symbol: "QQQ"      # Conservative position
    vix_symbol: "$VIX"         # VIX filter (v6-specific)

# Fixed backtest configuration
base_config:
  start_date: "2020-01-01"
  end_date: "2024-12-31"
  timeframe: "1D"              # REQUIRED
  initial_capital: 10000
  commission: 0.0
  slippage: 0.0

# Parameters to optimize
parameters:
  # Parameters with multiple values will be grid searched
  vix_ema_period: [20, 50, 75, 100]
  ema_period: [75, 100, 150, 200]
  atr_stop_multiplier: [2.0, 2.5, 3.0]
  risk_bull: [0.015, 0.020, 0.025]
  allocation_defense: [0.5, 0.6, 0.7]
  
  # Parameters with single values are "fixed"
  macd_fast_period: [12]
  macd_slow_period: [26]
  macd_signal_period: [9]
  atr_period: [14]

# Optional constraints
max_combinations: 500
checkpoint_interval: 10
```

## Key Learnings

### Schema Validation Location
- File: `jutsu_engine/application/grid_search_runner.py`
- Method: `GridSearchRunner.load_config()` (lines 197-287)
- Validation order:
  1. Top-level keys: strategy, symbol_sets, base_config, parameters (line 227)
  2. Symbol set structure (line 238)
  3. VIX symbol requirement for v5 strategies (line 244)
  4. Base config keys: start_date, end_date, timeframe, initial_capital (line 253)
  5. Date range validation (line 259)
  6. Parameters structure (line 268)

### Symbol Set Structure
```python
@dataclass
class SymbolSet:
    name: str
    signal_symbol: str          # REQUIRED
    bull_symbol: str            # REQUIRED
    defense_symbol: str         # REQUIRED
    vix_symbol: Optional[str] = None  # Optional (v5/v6 strategies)
```

### VIX Symbol Requirement
- MACD_Trend_v5 and MACD_Trend_v6 require `vix_symbol` in all symbol_sets
- Use `$VIX` notation for index symbols
- Validated at line 244-250

## Testing
Validated configuration loads successfully:
```bash
python -c "
from jutsu_engine.application.grid_search_runner import GridSearchRunner
config = GridSearchRunner.load_config('grid-configs/examples/grid_search_macd_v6.yaml')
print(f'✅ Strategy: {config.strategy_name}')
print(f'✅ Symbol Sets: {len(config.symbol_sets)}')
print(f'✅ Parameters: {len(config.parameters)}')
"
```

Output:
```
✅ Strategy: MACD_Trend_v6
✅ Symbol Sets: 1
✅ Parameters: 9
✅ Config loaded successfully
```

## Future Reference

When creating new grid search configs:
1. ✅ Use `strategy:` (not strategy_class)
2. ✅ Wrap all backtest settings in `base_config:` section
3. ✅ Always include `timeframe` in base_config
4. ✅ Use individual keys in symbol_sets (not list format)
5. ✅ Include `vix_symbol` for v5/v6 strategies
6. ✅ Put "fixed" parameters in parameters section as single-value lists
7. ✅ Reference working v4 config as template: `grid-configs/examples/grid_search_macd_v4.yaml`

## Related Files
- Config file: `grid-configs/examples/grid_search_macd_v6.yaml`
- Validator: `jutsu_engine/application/grid_search_runner.py` (GridSearchRunner.load_config)
- Template: `grid-configs/examples/grid_search_macd_v4.yaml`
- Documentation: CHANGELOG.md (Fixed section)
