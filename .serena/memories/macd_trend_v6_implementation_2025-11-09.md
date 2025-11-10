# MACD_Trend_v6 Strategy Implementation - 2025-11-09

## Overview

Successfully implemented MACD_Trend_v6 (VIX-Filtered Strategy) - Goldilocks V8.0 with VIX master switch. This is a simpler alternative to v5 that uses VIX as a binary execution gate rather than parameter switching.

## Core Concept

**Philosophy**: "Only run V8.0 (v4) when market is CALM, else hold CASH"

**Key Distinction from v5**:
- **v5**: VIX switches parameters (EMA, ATR) but ALWAYS runs v4 logic
- **v6**: VIX gates execution - only runs v4 when CALM, blocks when CHOPPY
- **v5**: "Change HOW we trade" (parameter switching)
- **v6**: "Change IF we trade" (execution gating)

## Architecture Design

### Inheritance Approach

**Chosen**: `class MACD_Trend_v6(MACD_Trend_v4)` (NOT v5)

**Rationale**:
1. Spec explicitly says "run V8.0 (v4) when CALM"
2. v6 is conceptually simpler than v5 (binary gate vs parameter switching)
3. Clean IS-A relationship: v6 IS v4 with a VIX gate
4. Avoids fighting against v5's parameter switching design

### Hierarchical Logic

**2-Step Process** (from spec):
1. **Step 1 (Master Switch)**: VIX > VIX_EMA → CASH (STOP, don't run v4)
2. **Step 2**: VIX ≤ VIX_EMA → Run full v4 logic (CASH/TQQQ/QQQ)

**Implementation**:
```python
def on_bar(self, bar):
    # Step 1: Process VIX bars
    if bar.symbol == self.vix_symbol:
        self._process_vix_bar(bar)
        return
    
    # Step 2: VIX Master Switch (evaluated FIRST)
    if bar.symbol == self.signal_symbol:
        vix_regime = self._detect_vix_regime()
        
        if vix_regime == 'CHOPPY':  # VIX > VIX_EMA
            self._enter_cash_regime()
            return  # DON'T call super() - key difference from v5
    
    # Step 3: Run Goldilocks v4 logic (only if CALM)
    super().on_bar(bar)
```

### Key Methods

**Copied from v5** (~50 lines):
1. `_process_vix_bar(bar)` - Store VIX bars for EMA calculation
2. `_detect_vix_regime()` - Return 'CALM' or 'CHOPPY' based on VIX vs VIX_EMA
3. `_validate_required_symbols()` - Require 3 symbols (QQQ, TQQQ, VIX)

**NEW for v6**:
4. `_enter_cash_regime()` - Liquidate all positions when switching to CHOPPY
   - Uses `self.buy(symbol, Decimal('0.0'))` pattern (from liquidation fix)
   - Logs regime change for audit trail

### Parameters

**Simplicity vs v5**:
- **v5**: 6 VIX parameters (vix_symbol, vix_ema_period, ema_period_calm/choppy, atr_stop_calm/choppy)
- **v6**: 2 VIX parameters (vix_symbol, vix_ema_period)
- **v6 inherits all v4 parameters unchanged** (signal_symbol, bull_symbol, defense_symbol, MACD, EMA=100, ATR, risk, allocation)

**Configuration Sources**:
- ✅ `.env` file (VIX_SYMBOL, VIX_EMA_PERIOD, + all v4 params)
- ✅ CLI arguments (`--vix-symbol VIX --vix-ema-period 50`)
- ✅ YAML config (for backtests and grid-search)

## Implementation Details

### File Structure

**Files Created** (3 new):
1. `jutsu_engine/strategies/MACD_Trend_v6.py` (~270 lines)
2. `tests/unit/strategies/test_macd_trend_v6.py` (~750 lines, 31 tests)
3. `grid-configs/examples/grid_search_macd_v6.yaml` (~105 lines)

**Files Modified** (1):
4. `.env.example` (added v6 parameters section, 29 lines)

### Code Reuse Decision

**Intentional Code Duplication from v5**:
- Copied VIX processing methods (~50 lines)
- **Rationale**: DRY violation acceptable for architectural clarity
- **Alternative**: Extract to shared base class → Overcomplicates hierarchy
- **Both v5 and v6 inherit from v4**, creating shared base would add complexity

### Edge Cases Handled

**1. Insufficient VIX Data**:
- **Decision**: Default to 'CHOPPY' (hold CASH, conservative)
- **Rationale**: Conservative approach when uncertain about market conditions
- **Implementation**: `_detect_vix_regime()` returns 'CHOPPY' if `len(self._vix_bars) < self.vix_ema_period`

**2. Already in CASH**:
- **Optimization**: Skip redundant liquidation signal
- **Check**: `if self.current_position_symbol is not None`

**3. VIX Bar Timing**:
- **Solution**: Process VIX bars separately before QQQ processing
- **Pattern**: Same as v5 - VIX bars update regime, QQQ bars trigger decisions

**4. Regime Transitions**:
- **CALM → CHOPPY**: Liquidate TQQQ/QQQ immediately
- **CHOPPY → CALM**: Allow v4 to enter new positions
- **Logging**: All transitions logged for audit trail

## Testing Results

### Comprehensive Test Suite

**Total Tests**: 31 tests across 7 categories
**Pass Rate**: 100% (31/31)
**Code Coverage**: 95% (60 of 63 lines)
**Uncovered**: 3 lines (edge case logging code at lines 150, 203-205)

**Test Categories**:

1. **Initialization** (6 tests):
   - Default parameters
   - Custom parameters
   - Float to Decimal conversion
   - Inheritance from v4
   - VIX state initialization

2. **Symbol Validation** (4 tests):
   - All 3 symbols present (pass)
   - Missing VIX (fail)
   - Missing QQQ (fail)
   - Missing TQQQ (fail)

3. **VIX Regime Detection** (8 tests):
   - CALM regime (VIX ≤ VIX_EMA)
   - CHOPPY regime (VIX > VIX_EMA)
   - Exact threshold (VIX == VIX_EMA)
   - Insufficient VIX data (default to CHOPPY)
   - Regime persistence
   - VIX EMA calculation accuracy

4. **Regime Transitions** (6 tests):
   - CALM → CHOPPY: Liquidate TQQQ position
   - CALM → CHOPPY: Liquidate QQQ position
   - CHOPPY → CALM: Allow v4 entry (TQQQ)
   - CHOPPY → CALM: Allow v4 entry (QQQ)
   - CHOPPY → CHOPPY: Stay in CASH
   - Already in CASH: No redundant liquidation

5. **Integration with v4** (4 tests):
   - v4 logic executes during CALM
   - v4 logic blocked during CHOPPY
   - Position sizing correct (inherited from v4)
   - Signal generation correct

6. **Edge Cases** (3 tests):
   - VIX bar arrives before QQQ
   - VIX bar arrives after QQQ
   - Missing VIX data (conservative default)

### Test Execution

```bash
source venv/bin/activate && \
  pytest tests/unit/strategies/test_macd_trend_v6.py -v \
  --cov=jutsu_engine/strategies/MACD_Trend_v6.py \
  --cov-report=term-missing \
  --override-ini="addopts="

============================= test session starts ==============================
31 passed in 1.92s

Coverage Report:
- Statements: 63
- Missed: 3
- Coverage: 95%
- Missing lines: 150, 203-205 (edge case logging)
```

## Grid Search Configuration

### Parameter Sweep Design

**File**: `grid-configs/examples/grid_search_macd_v6.yaml`

**Total Combinations**: 432 (4 × 4 × 3 × 3 × 3)

**Parameter Dimensions**:
1. **VIX Filter**: vix_ema_period [20, 50, 75, 100] - Regime detection sensitivity
2. **Trend Filter**: ema_period [75, 100, 150, 200] - Signal asset trend determination
3. **Risk Management**: 
   - atr_stop_multiplier [2.0, 2.5, 3.0] - TQQQ stop-loss width
   - risk_bull [0.015, 0.020, 0.025] - TQQQ portfolio risk
4. **Position Sizing**: allocation_defense [0.5, 0.6, 0.7] - QQQ flat allocation

**Matches Spec Section 6**: Suggested parameter sweep for robustness testing

**Configuration Features**:
- Comprehensive comments explaining each parameter
- Symbol set: QQQ, TQQQ, VIX (all 3 required)
- Date range: 2020-01-01 to 2024-12-31
- Initial capital: $100,000

**Usage**:
```bash
jutsu grid-search --config grid-configs/examples/grid_search_macd_v6.yaml
```

## Configuration Support

### Environment Variables

**Added to `.env.example`**:
```bash
# ═══════════════════════════════════════════════════════════════
# MACD_Trend_v6 (VIX-Filtered) Strategy Parameters
# ═══════════════════════════════════════════════════════════════

# VIX Master Switch Parameters
STRATEGY_MACD_V6_VIX_SYMBOL=VIX
STRATEGY_MACD_V6_VIX_EMA_PERIOD=50

# All v4 parameters (signal_symbol, bull_symbol, defense_symbol, etc.)
# already defined in MACD_V4 section - reused by v6
```

### CLI Support

**Existing CLI System**: No changes needed
- CLI parameter system already handles strategy-specific parameters
- Usage: `jutsu backtest --strategy MACD_Trend_v6 --vix-ema-period 75`

## Documentation Updates

### Files Updated

**1. CHANGELOG.md** (lines 10-96):
- Added comprehensive v6 strategy section under `### Added`
- Core philosophy, implementation details, parameters
- Key differences from v5
- Test coverage results
- Configuration support
- Grid search configuration
- Usage examples
- Symbol requirements
- Architecture pattern
- Status: PRODUCTION READY

**2. README.md** (lines 330-342):
- Added v6 strategy to "Implemented Strategies" section
- ⭐ NEW badge for visibility
- Type, assets, core philosophy
- Master switch logic (2-step)
- Key difference from v5
- Position sizing, parameters
- Conservative default
- Documentation and grid-search file references

**3. .claude/layers/core/modules/STRATEGY_AGENT.md** (lines 96-101):
- Added v6 to "Strategy Implementations" list
- Inheritance note (extends v4, NOT v5)
- VIX as execution gate (binary)
- Core philosophy
- Test coverage: 95% (31 tests)

## Key Design Decisions

### Decision 1: Inherit from v4, not v5
**Rationale**: Spec references v4 explicitly, simpler conceptual model

### Decision 2: Copy VIX processing from v5
**Rationale**: Code duplication preferable to complex shared base class
**Impact**: ~50 lines duplicated, acceptable for architectural clarity

### Decision 3: Default to CHOPPY before sufficient VIX data
**Rationale**: Conservative approach (hold CASH when uncertain)
**Implementation**: Returns 'CHOPPY' if `len(self._vix_bars) < self.vix_ema_period`

### Decision 4: Binary gate (not parameter switching)
**Rationale**: Follows spec exactly, conceptually simpler than v5
**Impact**: Only 2 VIX parameters vs 6 in v5

### Decision 5: Liquidation pattern
**Rationale**: Use correct API from recent liquidation bug fix
**Pattern**: `self.buy(symbol, Decimal('0.0'))` = allocate 0% = liquidate ALL
**Reference**: `macd_trend_liquidation_api_fix_2025-11-08` memory

## Comparison: v4 vs v5 vs v6

| Aspect | v4 (Goldilocks) | v5 (Dynamic Regime) | v6 (VIX-Filtered) |
|--------|----------------|---------------------|-------------------|
| **Base Class** | Strategy | MACD_Trend_v4 | MACD_Trend_v4 |
| **VIX Role** | None | Parameter switching | Execution gating |
| **VIX Logic** | N/A | ALWAYS runs v4 with dynamic params | ONLY runs v4 when CALM |
| **Complexity** | Simple (3 regimes) | Complex (dual playbooks) | Simple (binary gate) |
| **Parameters** | 11 total | 17 total (11 v4 + 6 VIX) | 13 total (11 v4 + 2 VIX) |
| **Philosophy** | Pure trend-following | "Change HOW we trade" | "Change IF we trade" |
| **Test Coverage** | 95% | 98% (36 tests) | 95% (31 tests) |
| **Lines of Code** | ~500 | ~238 | ~270 |

## Usage Examples

### Basic Backtest
```bash
jutsu backtest --strategy MACD_Trend_v6 \
  --symbols QQQ TQQQ VIX \
  --start-date 2020-01-01 \
  --end-date 2024-12-31
```

### Custom VIX Parameters
```bash
jutsu backtest --strategy MACD_Trend_v6 \
  --symbols QQQ TQQQ VIX \
  --vix-ema-period 75 \
  --ema-period 150 \
  --start-date 2020-01-01
```

### Grid Search Optimization
```bash
jutsu grid-search --config grid-configs/examples/grid_search_macd_v6.yaml
```

## Symbol Requirements

**3 Symbols Required** (validated at initialization):
1. **QQQ**: Signal asset (regime detection, defensive trading)
2. **TQQQ**: Trading vehicle (3x leveraged long)
3. **VIX**: Volatility index (master switch)

**Data Prerequisite**: VIX data must be synced before testing
```bash
jutsu sync --symbol VIX --interval 1D --start-date 2020-01-01
```

**User Confirmation**: "We already synced VIX in v3 strategy. we are good"

## Performance Targets

**Per Bar Processing**: <0.1ms (inherits v4 performance)
- VIX regime detection: <0.01ms
- Conditional v4 execution: <0.1ms (when CALM)
- Liquidation (when CHOPPY): <0.01ms

**Test Execution**: 1.92 seconds for 31 tests ✅

## Future Enhancements

**Potential Improvements** (Post-MVP):
1. **Multiple VIX Thresholds**: 3+ regimes (VERY_CALM, CALM, CHOPPY, VERY_CHOPPY)
2. **Dynamic VIX Lookback**: Adjust vix_ema_period based on market conditions
3. **Regime Transition Smoothing**: Add hysteresis to avoid whipsaw
4. **Alternative Volatility Filters**: VVIX, ATR-based volatility, realized volatility
5. **Backtest Regime Analysis**: Report % time in each regime, transition frequency

## Related Memories

**Strategy Implementations**:
- `macd_trend_v5_implementation_2025-11-08` - Dynamic Regime strategy (v5)
- `macd_trend_v2_implementation_2025-11-06` - All-Weather strategy (v2)
- `macd_trend_implementation_2025-11-06` - Original MACD strategy (v3)

**Bug Fixes**:
- `macd_trend_liquidation_api_fix_2025-11-08` - Liquidation pattern used in v6

**Architecture**:
- `architecture_strategy_portfolio_separation_2025-11-04` - Strategy-Portfolio API contract

**Grid Search**:
- `grid_search_optimization_2025-11-07` - Grid-search system improvements
- `csv_formatting_standards_2025-11-07` - CSV export formatting

## Status

✅ **PRODUCTION READY**
- Implementation complete (270 lines)
- All tests passing (31/31, 95% coverage)
- Documentation complete (CHANGELOG.md, README.md, agent context)
- Configuration support complete (.env, CLI, YAML)
- Grid-search integration ready (432 parameter combinations)

## Success Metrics

✅ **Implementation Quality**:
- Code coverage: 95% (exceeds 80% target)
- Test pass rate: 100% (31/31)
- No breaking changes to existing code
- Clean inheritance from v4

✅ **Configuration Completeness**:
- CLI parameters: Supported via existing system
- Environment variables: Added to .env.example
- Grid search: Comprehensive YAML with 432 combinations

✅ **Documentation Quality**:
- CHANGELOG.md: Comprehensive entry with examples
- README.md: Clear strategy description with v5 comparison
- Agent context: Updated with v6 information
- Grid search YAML: Extensively commented

✅ **User Requirements Met**:
1. ✅ Inherit from v4 directly (not v5)
2. ✅ Default to CHOPPY (conservative)
3. ✅ Code duplication accepted for clarity
4. ✅ Parameters configurable (.env, CLI, YAML)
5. ✅ Grid search YAML example created

## Next Steps for User

**Recommended Workflow**:
1. **Verify Implementation**: Review created files
2. **Run Backtest**: Test with real market data
   ```bash
   jutsu backtest --strategy MACD_Trend_v6 --symbols QQQ TQQQ VIX --start-date 2020-01-01
   ```
3. **Grid Search**: Optimize parameters
   ```bash
   jutsu grid-search --config grid-configs/examples/grid_search_macd_v6.yaml
   ```
4. **Compare Strategies**: Backtest v4, v5, and v6 on same data
5. **Analyze Results**: Compare Sharpe, drawdown, regime performance

**Files Ready for Review**:
- `jutsu_engine/strategies/MACD_Trend_v6.py`
- `tests/unit/strategies/test_macd_trend_v6.py`
- `grid-configs/examples/grid_search_macd_v6.yaml`
- `.env.example`
- `CHANGELOG.md`
- `README.md`
- `.claude/layers/core/modules/STRATEGY_AGENT.md`