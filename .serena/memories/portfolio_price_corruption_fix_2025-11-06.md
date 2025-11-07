# Portfolio Price Corruption Fix - Multi-Symbol Strategies

**Date**: 2025-11-06
**Status**: ✅ FIXED (Comprehensive solution implemented and validated)
**Severity**: CRITICAL - Data integrity issue
**Affected**: All multi-symbol strategies with signal asset pattern (e.g., QQQ → TQQQ/SQQQ)

## Summary

Fixed critical price corruption bug where portfolio values exploded to $140M-$274M instead of staying in $10K range. Root cause: EventLoop passed wrong symbol's bar to `execute_signal()`, causing SQQQ trades to use QQQ prices.

## The Bug

**Symptoms**:
- Portfolio_Value_Before jumps from $10K to $140M-$274M
- Only occurs with signal asset pattern (QQQ signal → TQQQ/SQQQ execution)
- Mathematical proof: $140M = $6,999 + (66 shares × $2.1M) proves SQQQ priced at QQQ's $2.1M instead of $46

**Root Cause**:
EventLoop line 159: `self.portfolio.execute_signal(signal, bar)` passes `bar` (current symbol, e.g., QQQ) for ALL signals, including SQQQ signals.

Three locations in Portfolio used `current_bar.close` incorrectly:
1. **execute_signal() line 282**: Price for quantity calculation
2. **execute_order() line 522**: Fill price for market orders
3. **execute_order() lines 546-552**: High/low for limit order validation

## The Fix

**Key Insight**: EventLoop ALREADY updated ALL symbol prices correctly via `update_market_value(self.current_bars)` at line 138. The `_latest_prices` dict has correct prices for ALL symbols.

**Solution**: Use `self._latest_prices.get(symbol, current_bar.close)` instead of `current_bar.close`

### Code Changes (jutsu_engine/portfolio/simulator.py)

**Location 1 (execute_signal line 281-292)**:
```python
# Use price already set by EventLoop.update_market_value()
# Fallback to current_bar.close for direct usage (tests, manual execution)
price = self._latest_prices.get(signal.symbol, current_bar.close)

# Log if using fallback (indicates potential symbol mismatch)
if signal.symbol not in self._latest_prices:
    logger.debug(
        f"Using fallback price from current_bar for {signal.symbol} "
        f"(current_bar.symbol={current_bar.symbol}). "
        f"This is expected for direct portfolio usage but NOT in EventLoop context."
    )
```

**Location 2 (execute_order line 529-542)**: Same pattern for fill_price

**Location 3 (execute_order line 542-552)**: Added validation for limit orders

### Why Fallback is Necessary

Initial fix without fallback broke ALL unit tests:
- Tests call `portfolio.execute_signal(signal, bar)` directly
- Tests don't call `update_market_value()` first
- `_latest_prices` is empty → fix returned None → tests failed

**Solution**: Graceful fallback to `current_bar.close` for direct usage (tests, manual), while still preferring `_latest_prices[symbol]` in EventLoop context (production).

## Validation

### Unit Tests
```bash
pytest tests/unit/core/test_portfolio.py -v
# Result: 21/21 PASSED ✅
```

### Integration Test (Full Backtest)
```bash
jutsu backtest --strategy ADX_Trend --symbols QQQ,TQQQ,SQQQ --start 2010-01-01 --end 2025-11-01 --capital 10000
```

**Before Fix**:
- Trade 1: Portfolio_Value_After=$150,254,679 (150M!)
- Trade 2: Portfolio_Value_Before=$140,286,039 (140M!)
- Values escalate to $274M

**After Fix**:
- Trade 1: Portfolio_Value_After=$9,881 ✅
- Trade 2: Portfolio_Value_Before=$11,528 ✅
- All values stay in $9K-$11K range ✅
- Final Value=$10,988.45, Total Return=9.88% ✅

## Why First Fix Attempt Failed

**First attempt (incomplete)**: Only deleted line 269 (`self._latest_prices[signal.symbol] = current_bar.close`)

**Why it failed**: There were TWO MORE locations using `current_bar.close`:
- execute_signal() line 282: `price = current_bar.close`
- execute_order() line 522: `fill_price = current_bar.close`

**Lesson**: Must analyze ALL usages of `current_bar` in the method, not just the obvious one.

## Performance Impact

**None** - Actually FASTER:
- Before: Accessed `current_bar.close` (field lookup)
- After: Uses `_latest_prices[symbol]` (dict lookup, already computed)
- Fallback only triggers in non-EventLoop contexts (tests, manual usage)

## Related Code

**EventLoop Coordination** (`jutsu_engine/core/event_loop.py:134-161`):
```python
# Line 134-135: Update current bars dict
self.current_bars[bar.symbol] = bar

# Line 138-139: Update portfolio market values (ALL symbols)
self.portfolio.update_market_value(self.current_bars)  # ← Sets _latest_prices correctly

# Line 155-161: Process signals
for signal in signals:
    fill = self.portfolio.execute_signal(signal, bar)  # ← Passes CURRENT bar, not signal's bar
```

**update_market_value** (`jutsu_engine/portfolio/simulator.py:700-722`):
```python
def update_market_value(self, current_bars: Dict[str, MarketDataEvent]) -> None:
    """Update latest prices and market values for all positions."""
    for symbol, bar in current_bars.items():
        self._latest_prices[symbol] = bar.close  # ← ALL symbols updated correctly
```

## Future Improvements

**Option 1** (Current): Use `_latest_prices` with fallback
- ✅ Works with EventLoop (production)
- ✅ Works with direct usage (tests, manual)
- ✅ No EventLoop changes needed

**Option 2** (Alternative): Pass `current_bars` dict to execute_signal()
```python
# EventLoop line 159:
fill = self.portfolio.execute_signal(signal, self.current_bars)

# Portfolio.execute_signal():
def execute_signal(self, signal, current_bars):
    price = current_bars[signal.symbol].close
```
- ✅ More explicit
- ❌ Requires EventLoop changes
- ❌ Breaks existing Portfolio API

**Recommendation**: Keep current solution (Option 1). It's robust, backward-compatible, and performant.

## Related Memories

- `csv_logging_debug_session_2025-11-06`: Previous session fixed TIMING issues (capture before update)
- This session fixed SYMBOL issues (use correct symbol's price)

## Key Takeaways

1. **EventLoop owns price updates**: `update_market_value()` is the single source of truth
2. **Portfolio uses _latest_prices**: Don't use `current_bar.close` directly, use `_latest_prices[symbol]`
3. **Fallback pattern**: `_latest_prices.get(symbol, current_bar.close)` handles both EventLoop and direct usage
4. **Complete analysis required**: One location fix is insufficient, must analyze ALL usages
5. **Test both contexts**: EventLoop path (production) AND direct usage path (tests, manual)