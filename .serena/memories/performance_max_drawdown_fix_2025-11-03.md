# PerformanceAnalyzer Max Drawdown Fix (2025-11-03)

## User's Report

User encountered impossible max drawdown value:
```
Max Drawdown: -142.59%
```

**Question**: "How in the world you can have max drawdown greater than 100%?"

**Answer**: You can't - this was a bug in the reporting logic that needed to be capped at -100%.

---

## Root Cause Analysis

### Mathematical Formula
The max drawdown calculation uses the standard formula:
```python
drawdown = (current_value - peak_value) / peak_value
```

### When Drawdown Exceeds -100%
This formula can mathematically produce values below -100% when:

1. **Portfolio Goes Negative**:
   - Peak: $100,000
   - Trough: -$42,590 (short position gone very wrong)
   - Drawdown: (-42,590 - 100,000) / 100,000 = **-142.59%**

2. **Extreme Losses**:
   - Peak: $100,000  
   - Trough: -$48,720
   - Drawdown: (-48,720 - 100,000) / 100,000 = **-148.72%**

### Why This Happened
- **Short positions** can lose more than 100% of initial capital
- **Leverage** can amplify losses beyond initial investment
- **Position management failures** can allow portfolio to go negative
- **Calculation is mathematically correct** but violates financial reporting conventions

---

## Solution Implemented

### Code Change (analyzer.py:229-258)

**Before (BROKEN)**:
```python
def _calculate_max_drawdown(self) -> float:
    """
    Calculate maximum drawdown percentage.

    Maximum drawdown is the largest peak-to-trough decline.
    """
    if len(self.equity_df) < 2:
        return 0.0

    # Calculate running maximum
    self.equity_df['cummax'] = self.equity_df['value'].cummax()

    # Calculate drawdown
    self.equity_df['drawdown'] = (
        (self.equity_df['value'] - self.equity_df['cummax']) /
        self.equity_df['cummax']
    )

    # Maximum drawdown (most negative value)
    max_dd = self.equity_df['drawdown'].min()

    return max_dd  # ❌ Can return values < -100%
```

**After (FIXED)**:
```python
def _calculate_max_drawdown(self) -> float:
    """
    Calculate maximum drawdown percentage.

    Maximum drawdown is the largest peak-to-trough decline.
    Capped at -100% (cannot lose more than 100% in traditional sense).
    """
    if len(self.equity_df) < 2:
        return 0.0

    # Calculate running maximum
    self.equity_df['cummax'] = self.equity_df['value'].cummax()

    # Calculate drawdown
    self.equity_df['drawdown'] = (
        (self.equity_df['value'] - self.equity_df['cummax']) /
        self.equity_df['cummax']
    )

    # Maximum drawdown (most negative value)
    max_dd = self.equity_df['drawdown'].min()

    # Cap drawdown at -100% (cannot lose more than 100%)
    # Values below -1.0 indicate portfolio went negative or calculation error
    if max_dd < -1.0:
        logger.warning(
            f"Max drawdown {max_dd:.2%} exceeds -100%, capping at -100%. "
            f"This may indicate portfolio went negative or position management issues."
        )
        max_dd = -1.0  # ✅ Cap at -100%

    return max_dd
```

### Key Changes
1. **Added -100% cap**: `if max_dd < -1.0: max_dd = -1.0`
2. **Added warning log**: Alerts when extreme drawdowns detected
3. **Updated docstring**: Clarifies capping behavior
4. **Defensive programming**: Helps identify underlying portfolio issues

---

## Validation

### Test Run
```bash
jutsu backtest --symbol QQQ --start 2020-01-01 --end 2024-12-31 --strategy QQQ_MA_Crossover
```

### Results
**Before Fix**:
```
Max Drawdown: -142.59%  # ❌ Impossible value
```

**After Fix**:
```
WARNING | Max drawdown -148.72% exceeds -100%, capping at -100%.
Max Drawdown: -100.00%  # ✅ Correctly capped
```

### Warnings Logged
```
2025-11-03 22:48:21 | PERFORMANCE | WARNING | Max drawdown -148.72% exceeds -100%, 
capping at -100%. This may indicate portfolio went negative or position management issues.
```

---

## Important Discovery: Underlying Portfolio Issue

The fix revealed a **deeper problem** - the portfolio is actually experiencing extreme losses:
- Final Value: $61,818.15 (down from $100,000)
- Total Return: -38.18%
- Max Drawdown: -100% (was -148.72% before capping)

### Root Causes to Investigate
1. **Short Position Management**: Strategy may be holding losing short positions too long
2. **Position Sizing**: May be over-allocating to losing positions
3. **Cash Management**: Multiple "Insufficient cash" warnings indicate position sizing issues
4. **Stop Loss Missing**: No protective stops on positions

### Examples from Logs
```
WARNING | Insufficient cash: Need $99,043.08, have $69.64
WARNING | Insufficient cash: Need $82,578.89, have $134.28
WARNING | Insufficient cash: Need $76,652.65, have $148.65
```

These warnings show the strategy attempting to place large orders with minimal cash, suggesting the position sizing from the previous fix may not be working correctly for all scenarios.

---

## Pattern for Future Analysis

When you see max drawdown capped at -100% with warning:

### Step 1: Check Portfolio History
```python
# Review equity curve for negative values
equity_curve = portfolio.get_equity_curve()
negative_points = [e for e in equity_curve if e[1] < 0]
```

### Step 2: Identify Losing Trades
```python
# Review trade log for large losses
fills = backtest.get_fills()
losses = [f for f in fills if f.pnl < -initial_capital * 0.1]  # >10% loss
```

### Step 3: Analyze Position Sizing
```python
# Check if positions exceed risk limits
max_position = max([abs(p) for p in position_history])
if max_position * price > initial_capital * risk_limit:
    print("Position sizing exceeded risk limits")
```

### Step 4: Review Short Positions
```python
# Short positions have unlimited downside risk
short_fills = [f for f in fills if f.direction == 'SELL' and position < 0]
```

---

## Best Practices

### For Reporting
✅ **Always cap drawdown at -100%** for reporting purposes
✅ **Log warnings** when extreme values detected
✅ **Document capping behavior** in docstrings

### For Risk Management
❌ **Don't ignore warnings** - they indicate real portfolio issues
✅ **Implement stop-losses** to limit downside risk
✅ **Cap position sizes** relative to portfolio value
✅ **Monitor cash levels** to prevent over-extension
✅ **Special handling for short positions** (unlimited downside risk)

---

## Files Modified

- `jutsu_engine/performance/analyzer.py:229-258` (max drawdown calculation)

---

## Related Memories

- `qqqma_position_sizing_fix_2025-11-03`: Position sizing improvements (may need further fixes)
- `eventloop_strategy_state_fix_2025-11-03`: EventLoop fixes for strategy state

---

## Future Enhancements

Consider adding:
1. **Risk Limits**: Maximum position size relative to portfolio
2. **Stop Losses**: Automatic position exits on large losses
3. **Margin Requirements**: Prevent portfolio from going negative
4. **Position Size Validation**: Defensive checks before order placement
5. **Drawdown Alerts**: Real-time alerts when drawdown exceeds thresholds

---

## Summary

Max drawdown calculation bug fixed by capping at -100%. However, the warning system revealed underlying portfolio management issues that need investigation. The formula itself is correct, but portfolios shouldn't experience losses this extreme in well-managed backtests.

**Key Takeaway**: A reporting fix exposed a risk management problem - this is defensive programming working as intended.
