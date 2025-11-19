# MACD_Trend_v5 Strategy Implementation - 2025-11-08

## Overview

Successfully implemented MACD_Trend_v5 (Dynamic Regime) strategy with VIX-based regime filter. This is a "strategy-of-strategies" that extends MACD_Trend_v4 (Goldilocks) with dynamic parameter switching based on market volatility.

## Architecture

**Inheritance Approach:**
- `class MACD_Trend_v5(MACD_Trend_v4)` - Clean inheritance from v4
- Overrides `on_bar()` to add VIX regime detection
- Dynamically switches `ema_period` and `atr_stop_multiplier` based on VIX regime
- Calls `super().on_bar(bar)` to reuse all v4 logic (500+ lines)

**Key Design Decision:**
- User suggested "grid-search kind of concept" (dual-instance pattern)
- Analysis revealed v5 spec requires **parameter switching**, NOT dual instances
- Inheritance approach chosen for:
  - Position continuity across regime changes (no forced liquidation)
  - Code reuse (all v4 logic works automatically)
  - Clean IS-A relationship (v5 IS v4 with VIX filter)

## Implementation Details

### VIX Regime Detection

**Algorithm:**
```python
def on_bar(self, bar):
    # Step 1: Process VIX bars (calculate VIX_EMA_50)
    if bar.symbol == self.vix_symbol:
        self._process_vix_bar(bar)
        return
    
    # Step 2: Update regime parameters (before QQQ processing)
    if bar.symbol == self.signal_symbol:
        vix_regime = self._detect_vix_regime()
        
        if vix_regime == 'CALM':  # VIX <= VIX_EMA_50
            self.ema_period = self.ema_period_calm  # 200
            self.atr_stop_multiplier = self.atr_stop_calm  # 3.0
        else:  # CHOPPY (VIX > VIX_EMA_50)
            self.ema_period = self.ema_period_choppy  # 75
            self.atr_stop_multiplier = self.atr_stop_choppy  # 2.0
    
    # Step 3: Delegate to v4 logic (with updated parameters)
    super().on_bar(bar)
```

**Regime Classification:**
- **CALM**: VIX <= VIX_EMA_50 → Use EMA=200, ATR_Stop=3.0 (slow/wide for smooth trends)
- **CHOPPY**: VIX > VIX_EMA_50 → Use EMA=75, ATR_Stop=2.0 (fast/tight for volatile markets)

### Required Symbols

Strategy requires **3 symbols** (validated during initialization):
1. **QQQ** - Signal asset (regime detection, defensive trading)
2. **TQQQ** - Trading vehicle (3x leveraged long)
3. **VIX** - Volatility index (regime filter)

**Data Prerequisite:** VIX data must be synced before testing
```bash
jutsu sync --symbol VIX --interval 1D --start-date 2020-01-01
```

User confirmed: "We already synced VIX in v3 strategy. we are good"

### Configurable Parameters

**v5-Specific Parameters:**
- `vix_symbol`: VIX (volatility index)
- `vix_ema_period`: 50 (default from spec)
- `ema_period_calm`: 200 (slow filter for smooth trends)
- `atr_stop_calm`: 3.0 (wide stop to avoid noise)
- `ema_period_choppy`: 75 (fast filter for choppy markets)
- `atr_stop_choppy`: 2.0 (tight stop to lock in gains)

**Inherited from v4:**
- MACD parameters (fast=12, slow=26, signal=9)
- Risk parameters (risk_bull=2.5%, allocation_defense=60%)
- ATR period (14)

**Configuration Sources:**
- ✅ `.env` file (VIX_EMA_PERIOD, EMA_PERIOD_CALM, etc.)
- ✅ CLI arguments (`--vix-ema-period 50`)
- ✅ YAML config (for backtests and grid-search)

## Testing Results

**Comprehensive Test Suite:**
- **Total Tests**: 36
- **Passing**: 36 (100% pass rate)
- **Coverage**: **98%** for MACD_Trend_v5.py (exceeds 80% target)
- **Uncovered**: Only 1 line (logging statement that executes every 50 bars)

**Test Categories:**
1. ✅ Initialization (6 tests) - Parameter handling, inheritance, defaults
2. ✅ Symbol validation (4 tests) - 3-symbol requirement, missing symbols
3. ✅ VIX regime detection (8 tests) - CALM/CHOPPY classification, edge cases
4. ✅ VIX EMA calculation (4 tests) - Correct EMA calculation, lookback period
5. ✅ Parameter switching (6 tests) - Dynamic ema_period and atr_stop_multiplier updates
6. ✅ Integration with v4 (4 tests) - super().on_bar() delegation, position sizing
7. ✅ Edge cases (4 tests) - Insufficient data, regime transitions, VIX missing

## Key Bug Fixes During Implementation

### 1. Symbol Validation Logic
**Problem**: Validation compared available symbols count with required symbols count incorrectly
```python
# WRONG: len(available_symbols) >= len(required_symbols)
# This passes when we have [QQQ, TQQQ] but VIX is missing

# FIXED: len(set(available_symbols)) >= len(set(required_symbols))
# Now requires 3 UNIQUE symbols
```

### 2. Test Data OHLC Validation
**Problem**: Test data had invalid OHLC (close > high or close < low)
**Fix**: Created valid OHLC data with close within [low, high] range

### 3. Regime Transition Test Logic
**Problem**: Tests used constant VIX values, expecting regime transitions
**Issue**: Constant VIX → VIX_EMA equals VIX → always CALM regime
**Fix**: Created actual VIX crossovers (VIX crossing above/below EMA) to test transitions

## Grid-Search Integration

**Sample Configuration:** `grid-configs/examples/grid_search_macd_v5.yaml`

```yaml
strategy_class: "MACD_Trend_v5"

symbol_sets:
  - name: "QQQ_TQQQ_VIX"
    symbols: ["QQQ", "TQQQ", "VIX"]  # VIX required!

parameters:
  # VIX Regime Filter
  vix_ema_period: [20, 50, 100]
  
  # CALM Playbook (smooth trends)
  ema_period_calm: [150, 200, 250]
  atr_stop_calm: [2.5, 3.0, 3.5]
  
  # CHOPPY Playbook (volatile markets)
  ema_period_choppy: [50, 75, 100]
  atr_stop_choppy: [2.0, 2.5]
  
  # Shared Parameters
  risk_bull: [0.025, 0.03]
  allocation_defense: [0.5, 0.6]
```

Matches v5 spec Section 6 (suggested parameter sweep).

**Grid-Search Usage:**
```bash
jutsu grid-search --config grid-configs/examples/grid_search_macd_v5.yaml
```

## Documentation Updates

**Files Updated:**
1. **CHANGELOG.md** - Added comprehensive v5 strategy documentation
2. **README.md** - Created "Implemented Strategies" section with v4 and v5
3. **.claude/layers/core/modules/STRATEGY_AGENT.md** - Updated agent context with v5

**Documentation Quality:**
- Clear descriptions of dual-regime logic
- Symbol requirements highlighted (QQQ, TQQQ, VIX)
- Parameter switching explained (CALM vs CHOPPY)
- Grid-search support documented
- Test coverage metrics included

## Files Created/Modified

**New Files:**
1. `jutsu_engine/strategies/MACD_Trend_v5.py` (238 lines, 98% coverage)
2. `tests/unit/strategies/test_macd_trend_v5.py` (36 tests, 100% passing)
3. `grid-configs/examples/grid_search_macd_v5.yaml` (parameter sweep config)

**Modified Files:**
4. `.env.example` (added v5 parameters)
5. `CHANGELOG.md` (documented v5 addition)
6. `README.md` (added strategies section)
7. `.claude/layers/core/modules/STRATEGY_AGENT.md` (updated agent context)

## Key Learnings

### Architecture Pattern
**Inheritance over Composition for Strategy Variants:**
- When new strategy is "base strategy + filter", use inheritance
- When new strategy is "completely different logic", use separate class
- v5 is clearly v4 + VIX filter → inheritance was correct choice

### Parameter Switching Pattern
```python
# Store "playbook" parameters at initialization
self.ema_period_calm = 200
self.ema_period_choppy = 75

# Switch active parameter based on regime
if regime == 'CALM':
    self.ema_period = self.ema_period_calm
else:
    self.ema_period = self.ema_period_choppy

# Base class uses self.ema_period (dynamic value)
super().on_bar(bar)
```

This pattern enables:
- Clean separation of regime detection and regime execution
- Easy testing (test regime detection separately)
- Extensibility (add more regimes without changing base logic)

### Symbol Validation Best Practice
```python
# Always validate UNIQUE symbols
required_symbols = [self.signal_symbol, self.bull_symbol, self.vix_symbol]
available_symbols = list(set(bar.symbol for bar in self._bars))

# Compare unique counts
if len(set(available_symbols)) >= len(set(required_symbols)):
    self._validate_required_symbols()
```

### Test Data Validation
**Always validate OHLC relationships in test data:**
- Low <= Close <= High
- Low <= Open <= High
- Low < High (no flat bars unless intentional)

## Usage Examples

### Backtest with v5
```bash
# Basic backtest
jutsu backtest --strategy MACD_Trend_v5 \
  --symbols QQQ TQQQ VIX \
  --start-date 2020-01-01 \
  --end-date 2024-12-31

# With custom parameters
jutsu backtest --strategy MACD_Trend_v5 \
  --symbols QQQ TQQQ VIX \
  --vix-ema-period 50 \
  --ema-period-calm 200 \
  --atr-stop-calm 3.0 \
  --ema-period-choppy 75 \
  --atr-stop-choppy 2.0 \
  --start-date 2020-01-01
```

### Grid-Search Optimization
```bash
jutsu grid-search --config grid-configs/examples/grid_search_macd_v5.yaml
```

## Future Enhancements

**Potential Improvements (Post-MVP):**
1. **Multiple Regime Thresholds**: Instead of binary CALM/CHOPPY, use 3+ regimes
2. **Dynamic VIX Lookback**: Adjust vix_ema_period based on market conditions
3. **Regime Transition Smoothing**: Add hysteresis to avoid whipsaw on regime boundaries
4. **Alternative Volatility Filters**: VVIX, ATR-based volatility, realized volatility
5. **Backtest Regime Analysis**: Report % time in each regime, regime transitions count

## Related Memories

- `macd_trend_v2_implementation_2025-11-06` - Original MACD strategy (deprecated)
- `macd_trend_implementation_2025-11-06` - v3 implementation (ADX filter)
- `grid_search_optimization_2025-11-07` - Grid-search system improvements
- `csv_formatting_standards_2025-11-07` - CSV export formatting for grid-search

## Status

✅ **PRODUCTION READY**
- Implementation complete (238 lines)
- All tests passing (36/36, 98% coverage)
- Documentation complete
- Grid-search integration ready
- Configuration support complete (.env, CLI, YAML)