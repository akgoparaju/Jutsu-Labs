# Trade Execution Timing - Technical Documentation

**Last Updated**: 2025-11-17
**Status**: Current behavior is correct and realistic for end-of-day strategies

---

## Executive Summary

The Jutsu Labs backtesting engine executes trades at **same-bar close** (4:00 PM market close) for end-of-day strategies. This is the **realistic and correct behavior** for strategies that make decisions at market close.

**Key Point**: Signal generated at Day 1 close → Executed at Day 1 close (NOT next day)

---

## Current Execution Flow

### Timeline for End-of-Day Strategy

```
Day 1, 4:00 PM (Market Close)
├─ Complete OHLCV bar available
├─ Strategy.on_bar() processes bar
├─ Strategy calculates indicators
├─ Strategy generates BUY/SELL signal
├─ EventLoop receives signal
├─ EventLoop executes signal IMMEDIATELY
├─ Portfolio calculates position size
├─ Fill price = bar.close (closing auction)
└─ Slippage applied (disadvantageous to trader)
```

**Result**: Trade executed at 4:00 PM using closing auction price

---

## Code Architecture

### 1. EventLoop Coordination (event_loop.py)

```python
def run(self):
    """Process bars sequentially, execute signals immediately."""
    for bar in self.data_handler.get_next_bar():
        # Step 1: Update portfolio market values
        self.portfolio.update_market_value(self.current_bars)

        # Step 2: Update strategy state
        self.strategy._update_bar(bar)

        # Step 3: Feed bar to strategy
        self.strategy.on_bar(bar)

        # Step 4: Collect signals
        signals = self.strategy.get_signals()

        # Step 5: Execute signals IMMEDIATELY using CURRENT bar
        for signal in signals:
            fill = self.portfolio.execute_signal(signal, bar)  # ← Current bar

        # Step 6: Record portfolio value
        self.portfolio.record_portfolio_value(bar.timestamp)
```

**Key Design**: Signal execution happens in **same iteration** as signal generation, using `bar` (current bar).

### 2. Portfolio Execution (simulator.py)

```python
def execute_order(self, order: OrderEvent, current_bar: MarketDataEvent):
    """Execute order using current bar data."""

    # Determine fill price from CURRENT bar
    if order_type == 'MARKET':
        fill_price = self._latest_prices.get(symbol, current_bar.close)

        # Apply slippage (disadvantageous to trader)
        if direction == 'BUY':
            fill_price = fill_price * (Decimal('1') + self.slippage_percent)
        else:  # SELL
            fill_price = fill_price * (Decimal('1') - self.slippage_percent)

    # Create fill event
    fill = FillEvent(
        timestamp=current_bar.timestamp,  # ← Same timestamp as bar
        symbol=symbol,
        fill_price=fill_price,  # ← Current bar close + slippage
        ...
    )
```

**Key Design**: Fill price comes from `current_bar.close`, NOT next bar.

### 3. Strategy Signal Generation (strategy_base.py)

```python
def buy(self, symbol: str, portfolio_percent: Decimal):
    """Generate BUY signal for immediate execution."""
    signal = SignalEvent(
        symbol=symbol,
        signal_type='BUY',
        timestamp=self._bars[-1].timestamp,  # ← Current bar timestamp
        portfolio_percent=portfolio_percent,
        ...
    )
    self._signals.append(signal)
```

**Key Design**: Signal timestamp = current bar timestamp, executed same bar.

---

## Why Same-Bar Execution is Realistic

### For End-of-Day Strategies

1. **Market Close at 4:00 PM**:
   - Complete bar data available
   - All indicators can be calculated
   - Decision made at 4:00 PM

2. **Closing Auction**:
   - Real market mechanism at 4:00 PM
   - Significant volume (10-20% of daily volume)
   - Traders CAN participate at close

3. **Realistic Execution**:
   - Using `bar.close` as fill price is accurate
   - Represents closing auction price
   - Slippage models market impact

4. **No Artificial Delay**:
   - Real traders don't wait until next day open
   - Closing auction is immediate and liquid
   - Strategy decision → Execution is instantaneous at close

### Comparison with Next-Bar Open Execution

| Aspect | Same-Bar Close (Current) | Next-Bar Open (Alternative) |
|--------|-------------------------|----------------------------|
| **Timing** | 4:00 PM same day | 9:30 AM next day |
| **Delay** | Immediate | 17.5 hours (overnight) |
| **Fill Price** | bar.close | next_bar.open |
| **Realism** | Realistic for EOD | More conservative |
| **Overnight Gap** | No exposure | Exposed to overnight gap |
| **Use Case** | End-of-day strategies | Ultra-conservative testing |

---

## Verification

### No Hidden Next-Bar Logic

✅ **EventLoop** (event_loop.py):
- No signal queue
- No delay mechanism
- Executes immediately in same loop iteration

✅ **Portfolio** (simulator.py):
- No pending orders
- No next-bar execution path
- Uses current_bar parameter throughout

✅ **Strategy** (strategy_base.py):
- No delayed signal generation
- Signals created for immediate execution
- No "execute next bar" flag

✅ **MACD_Trend_v4** (reference strategy):
- Generates signals during on_bar()
- Immediate execution pattern
- Same-bar close execution

---

## Example: MACD_Trend_v4 Strategy

### Signal Generation Pattern

```python
def _enter_tqqq(self, bar):
    """Enter TQQQ position with ATR-based sizing."""

    # Calculate current price and risk
    current_price = trade_bars[-1].close  # ← Current bar close
    dollar_risk_per_share = current_atr * self.atr_stop_multiplier

    # Log strategy context BEFORE signal
    if self._trade_logger:
        self._trade_logger.log_strategy_context(
            timestamp=bar.timestamp,  # ← Current bar timestamp
            symbol=self.bull_symbol,
            ...
        )

    # Generate signal for immediate execution
    self.buy(self.bull_symbol, self.risk_bull,
             risk_per_share=dollar_risk_per_share)
```

**Execution Flow**:
1. Calculate indicators at bar close
2. Determine position size using current price
3. Generate signal with current bar timestamp
4. EventLoop executes immediately
5. Fill at current bar close (with slippage)

---

## Trade Logging

### Timestamp Behavior

Trade logs will show:
- **Signal Timestamp**: bar.timestamp (4:00 PM Day 1)
- **Fill Timestamp**: bar.timestamp (4:00 PM Day 1)
- **Same Day**: Signal and fill occur same day

This is **correct behavior** - not a bug.

### Example Trade Log Entry

```csv
Trade_ID,Date,Bar_Number,Ticker,Decision,Fill_Price,Position_Value
1,2025-01-15 16:00:00,42,TQQQ,BUY,45.50,22750.00
```

- Date: 2025-01-15 16:00:00 ← Market close time
- Signal generated: 4:00 PM
- Fill executed: 4:00 PM (same timestamp)
- Fill price: Closing auction price + slippage

---

## When to Use Next-Bar Open Execution

### Conservative Backtesting Scenarios

You might want next-bar open execution if:

1. **Ultra-Conservative Testing**:
   - Assume can't execute at close
   - Add overnight gap risk
   - More pessimistic performance

2. **Intraday Open Strategies**:
   - Strategy specifically trades at open
   - Not applicable to current EOD design

3. **Regulatory Constraints**:
   - Some funds can't trade at close
   - Must wait for next open

### Implementation Would Require

If next-bar open execution is needed:

1. **EventLoop Changes**:
   - Store signals in queue
   - Delay execution by 1 bar
   - Execute on next iteration using next_bar

2. **Portfolio Changes**:
   - Accept next_bar parameter
   - Use next_bar.open for fill_price
   - Update tests

3. **Breaking Change**:
   - Existing strategies would behave differently
   - Backtest results would change
   - CHANGELOG.md documentation required

---

## Best Practices

### For Strategy Developers

1. **Understand Execution Timing**:
   - Signals execute at same-bar close
   - Use indicators calculated from current bar
   - Fill price = bar.close + slippage

2. **Realistic Price Assumptions**:
   - Don't use bar.high or bar.low for fills
   - Use bar.close (closing auction price)
   - Slippage is applied automatically

3. **Avoid Lookback Bias**:
   - Only use data from current and past bars
   - Don't peek at future data
   - EventLoop enforces chronological processing

4. **Log Strategy Context**:
   - Call `_trade_logger.log_strategy_context()` BEFORE signals
   - Include all indicators and thresholds
   - Aids in debugging and analysis

---

## References

### Code Files
- `jutsu_engine/core/event_loop.py` - EventLoop coordination
- `jutsu_engine/portfolio/simulator.py` - Order execution
- `jutsu_engine/core/strategy_base.py` - Strategy interface
- `jutsu_engine/strategies/MACD_Trend_v4.py` - Reference implementation

### Related Documentation
- `docs/SYSTEM_DESIGN.md` - Overall architecture
- `docs/BEST_PRACTICES.md` - Coding standards
- `jutsu_engine/performance/trade_logger.py` - Trade logging

### Serena Memories
- `architecture_strategy_portfolio_separation` - Design philosophy
- `trade_execution_timing_clarification_2025-11-17` - This analysis

---

## FAQ

### Q: Why does my trade log show same-day execution?
**A**: This is correct. Signals execute at same-bar close (4:00 PM), not next day.

### Q: Is this realistic for end-of-day strategies?
**A**: Yes. Real traders can execute at closing auction (4:00 PM). Using bar.close as fill price is accurate.

### Q: How do I make execution more conservative?
**A**: Next-bar open execution would add overnight gap risk, but requires code changes. Current same-bar close is already realistic with slippage applied.

### Q: Does slippage account for execution delay?
**A**: Slippage models market impact and spread at closing auction. No delay needed - closing auction is immediate.

### Q: Can I execute intraday (before bar close)?
**A**: No. Current design is for end-of-day bars only. Intraday execution requires 1min/5min bars and different architecture.

---

**Conclusion**: Same-bar close execution is the **correct and realistic** behavior for end-of-day backtesting. No code changes are needed.
