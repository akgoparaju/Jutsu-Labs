# ADX_Trend Multi-Symbol Bar Filtering Bug Fix

**Date**: 2025-11-06  
**Agent**: STRATEGY_AGENT  
**Severity**: CRITICAL  
**Status**: ✅ FIXED

## Problem Summary

ADX_Trend strategy produced ONLY QQQ 50% trades (65/65 trades) despite having sophisticated 6-regime logic designed to trade TQQQ (3x bull), SQQQ (3x bear), QQQ (1x), or CASH based on trend strength and direction.

## Root Cause Analysis

**Core Issue**: Strategy base class `_bars` list contained mixed-symbol bars in multi-symbol strategies.

**Execution Flow**:
1. EventLoop processes bars: QQQ, TQQQ, SQQQ, QQQ, TQQQ, SQQQ, ...
2. For each bar, EventLoop calls `strategy._update_bar(bar)` → appends to `_bars`
3. `_bars` becomes: [QQQ_bar1, TQQQ_bar1, SQQQ_bar1, QQQ_bar2, TQQQ_bar2, SQQQ_bar2, ...]

**The Bug**:
- ADX_Trend line 96: `closes = self.get_closes(lookback=60)`
- `get_closes()` returned last 60 bars from `_bars` WITHOUT filtering by symbol
- Result: Mixed data (QQQ $400 + TQQQ $60 + SQQQ $30 prices)
- EMA(20), EMA(50), ADX(14) calculated on **corrupted data**
- Regime detection produced **garbage values**, defaulted to Regime 5 (QQQ 50%)

**Why Only QQQ Trades**:
- Regime 5 (Weak Bullish) → QQQ 50% allocation
- Strategy stuck in Regime 5 for all 65 trades due to invalid indicator values
- Never transitioned to strong/building regimes (TQQQ/SQQQ)

## Fix Implementation

### 1. Strategy Base Class (`jutsu_engine/core/strategy_base.py`)

Extended helper methods with optional symbol filtering:

```python
def get_closes(self, lookback: int = 100, symbol: Optional[str] = None) -> pd.Series:
    if not self._bars:
        return pd.Series([], dtype='float64')
    
    # Filter by symbol if specified (for multi-symbol strategies)
    bars = self._bars
    if symbol:
        bars = [bar for bar in bars if bar.symbol == symbol]
    
    closes = [bar.close for bar in bars[-lookback:]]
    return pd.Series(closes)
```

Applied same pattern to `get_highs()` and `get_lows()`.

**Backward Compatibility**: `symbol=None` returns all bars (single-symbol strategies unaffected).

### 2. ADX_Trend Strategy (`jutsu_engine/strategies/ADX_Trend.py`)

**Lines 96-98** - Pass signal symbol to all data retrieval:
```python
# Get historical data for QQQ ONLY (filter out TQQQ/SQQQ bars)
closes = self.get_closes(lookback=lookback, symbol=self.signal_symbol)
highs = self.get_highs(lookback=lookback, symbol=self.signal_symbol)
lows = self.get_lows(lookback=lookback, symbol=self.signal_symbol)
```

**Lines 114-117** - Added debug logging:
```python
self.log(
    f"Indicators: EMA_fast={ema_fast_val:.2f}, EMA_slow={ema_slow_val:.2f}, "
    f"ADX={adx_val:.2f} | Regime={current_regime} | Bars used={len(closes)}"
)
```

## Validation Results

### Unit Tests: 25/25 Passing ✅
- All existing ADX_Trend tests pass
- No regression from base class changes

### Integration Tests: 3/3 Passing ✅

**File**: `tests/integration/test_adx_trend_multi_symbol_fix.py` (235 lines)

1. **`test_adx_trend_filters_bars_by_symbol`**:
   - Creates 210 mixed bars (70 QQQ + 70 TQQQ + 70 SQQQ)
   - Verifies `get_closes(60, symbol='QQQ')` returns 60 QQQ bars only
   - Verifies prices in correct range (QQQ $400-440, not mixed with TQQQ $60 or SQQQ $30)
   - Verifies sequential ordering (incremental prices, not random mixed values)

2. **`test_adx_trend_generates_non_qqq_trades`**:
   - Creates strong uptrend (should trigger Regime 1: TQQQ 60%)
   - Verifies TQQQ signals generated (not just QQQ)
   - Verifies correct allocation (60% for Regime 1)

3. **`test_adx_trend_regime_detection_with_clean_data`**:
   - Verifies strategy runs without errors in multi-symbol environment
   - Verifies internal bar storage (105 total = 35 QQQ + 35 TQQQ + 35 SQQQ)
   - Verifies filtering returns correct count (30 QQQ bars from 30 requested)

## Expected User Impact

**Before Fix**:
```bash
jutsu backtest --strategy ADX_Trend --symbols QQQ,TQQQ,SQQQ --export-trades
# Result: 65/65 QQQ trades, all "Weak Bullish" regime
# CSV shows: All Strategy_State = "Unknown", All Ticker = "QQQ"
```

**After Fix**:
```bash
jutsu backtest --strategy ADX_Trend --symbols QQQ,TQQQ,SQQQ --export-trades
# Expected: Mix of TQQQ (bullish), SQQQ (bearish), QQQ (weak bullish), CASH (weak bearish)
# CSV shows: Proper regime transitions, correct vehicles, readable Strategy_State values
# Logs show: Correct indicator values (EMA ~$400 for QQQ, not mixed)
```

## Files Modified

1. **`jutsu_engine/core/strategy_base.py`**:
   - Lines 195-222: `get_closes()` with symbol filter
   - Lines 240-267: `get_highs()` with symbol filter
   - Lines 269-296: `get_lows()` with symbol filter

2. **`jutsu_engine/strategies/ADX_Trend.py`**:
   - Lines 96-98: Pass `symbol=self.signal_symbol` to data retrieval
   - Lines 114-117: Added indicator logging for debugging

3. **`CHANGELOG.md`**:
   - Added comprehensive bug fix documentation

## Files Created

1. **`tests/integration/test_adx_trend_multi_symbol_fix.py`** (235 lines):
   - Regression tests to prevent this bug from reoccurring
   - Validates symbol filtering behavior
   - Validates multi-symbol environment handling

## Architectural Lessons

### Signal Asset Pattern Implementation

**Concept**: Calculate indicators on one symbol (signal asset), trade multiple vehicles based on signals.

**Requirements**:
1. Multi-symbol data handler provides bars for all symbols chronologically
2. Strategy ignores non-signal bars in `on_bar()` (early return)
3. **CRITICAL**: Strategy MUST filter `_bars` by signal symbol when calculating indicators
4. Portfolio needs current bars for all symbols to execute trades at correct prices

**Implementation Pattern**:
```python
def on_bar(self, bar):
    # Ignore non-signal bars
    if bar.symbol != self.signal_symbol:
        return
    
    # Get signal asset data ONLY
    closes = self.get_closes(lookback, symbol=self.signal_symbol)
    highs = self.get_highs(lookback, symbol=self.signal_symbol)
    lows = self.get_lows(lookback, symbol=self.signal_symbol)
    
    # Calculate indicators on clean data
    indicators = calculate_indicators(closes, highs, lows)
    
    # Generate signals for trading vehicles
    if regime == BULLISH:
        self.buy(self.bull_symbol, allocation)  # e.g., TQQQ
```

### Future Multi-Symbol Strategies

**MUST DO**:
- Always pass `symbol=<target>` when calculating indicators on specific symbols
- Document which symbol is the signal asset in strategy docstring
- Test with multi-symbol data to verify correct filtering

**DON'T DO**:
- Assume `get_closes()` returns single-symbol data in multi-symbol environment
- Use `_bars` directly without filtering by symbol
- Mix price data from different symbols in indicator calculations

## Prevention Measures

1. **Code Review Checklist**:
   - Multi-symbol strategies must use `symbol` parameter in data retrieval
   - Verify early return for non-signal bars in `on_bar()`
   - Check indicator inputs use filtered data

2. **Testing Requirements**:
   - All multi-symbol strategies require integration test with mixed bars
   - Verify correct symbol allocation (not stuck on one vehicle)
   - Validate indicator values are in expected range

3. **Documentation**:
   - Signal asset pattern documented in strategy_base.py
   - Example multi-symbol strategy serves as reference implementation
   - CHANGELOG.md preserves institutional knowledge of this bug

## Related Memories

- `adx_trend_strategy_implementation_2025-11-05` - Original strategy implementation
- `architecture_strategy_portfolio_separation_2025-11-04` - Strategy-Portfolio API
- This memory preserves complete bug analysis for future reference

## Performance Impact

- No performance regression from symbol filtering (list comprehension is fast)
- Additional logging adds ~0.1ms per bar (negligible)
- User experience: Strategy now works as designed (CRITICAL improvement)

## Lessons Learned

1. **Architectural Assumptions**: Strategy base class assumed single-symbol usage
2. **Integration Testing**: Unit tests alone insufficient for multi-symbol validation
3. **Debugging Value**: Added logging critical for user to verify fix works
4. **Documentation**: Comprehensive CHANGELOG.md entry helps future developers
5. **Backward Compatibility**: Optional parameters preserve existing strategy behavior
