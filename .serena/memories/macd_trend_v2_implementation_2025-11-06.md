# MACD_Trend_v2 (All-Weather V6.0) Strategy Implementation

**Date**: 2025-11-06
**Implementation Type**: New Strategy (5-Regime Adaptive System)
**Status**: ✅ COMPLETE - 56/56 tests passed, 87% coverage

## Strategy Overview

All-Weather V6.0 is a 5-regime adaptive trend-following strategy that balances aggressive (TQQQ), defensive (QQQ), and inverse (SQQQ) positions based on market conditions.

**Named**: MACD_Trend_v2 (per user request)
**Specification**: `jutsu_engine/strategies/MACD_Trend-v2.md`
**Implementation**: `jutsu_engine/strategies/MACD_Trend_v2.py` (668 lines)
**Tests**: `tests/unit/strategies/test_macd_trend_v2.py` (981 lines, 56 tests)

## Key Characteristics

### Trading Universe
- **Signal Assets**: QQQ (MACD + 100-EMA), $VIX (volatility filter)
- **Trading Vehicles**: TQQQ (3x bull), QQQ (1x defensive), SQQQ (3x bear), CASH
- **Total Symbols**: 4 symbols ['QQQ', '$VIX', 'TQQQ', 'SQQQ']
- **QQQ Dual Role**: Used for BOTH signals AND defensive trading

### 5-Regime Priority System

**Priority Enforcement**: Uses if/elif ladder - first matching condition wins

**Regime 1: VIX FEAR** (Priority 1 - overrides everything)
- Condition: `VIX > 30.0`
- Action: CASH 100%
- Exit: N/A (cash position)

**Regime 2: STRONG BULL** (Priority 2)
- Conditions: `Price > 100-EMA AND MACD_Line > Signal_Line`
- Action: TQQQ (2.5% risk, ATR-based)
- Stop: `Fill_Price - (ATR × 3.0)`
- Exit: Regime change OR stop hit

**Regime 3: WEAK BULL/PAUSE** (Priority 3)
- Conditions: `Price > 100-EMA AND MACD_Line <= Signal_Line`
- Action: QQQ (50% flat allocation)
- Stop: **NONE** (regime-managed only)
- Exit: Regime change from 3 to any other
- **Key**: Track `qqq_position_regime` for exit management

**Regime 4: STRONG BEAR** (Priority 4)
- Conditions: `Price < 100-EMA AND MACD_Line < 0` (ZERO-LINE CHECK!)
- Action: SQQQ (2.5% risk, ATR-based)
- Stop: `Fill_Price + (ATR × 3.0)` (INVERSE for short)
- Exit: Regime change OR stop hit

**Regime 5: CHOP/WEAK BEAR** (Priority 5 - default)
- Conditions: All other conditions
- Action: CASH 100%
- Exit: N/A (cash position)

### Dual Position Sizing (CRITICAL Feature)

**ATR Mode** (TQQQ/SQQQ):
```python
# Calculate ATR on trading vehicle (not signal asset)
atr_series = atr(highs, lows, closes, period=14)
current_atr = Decimal(str(atr_series.iloc[-1]))
dollar_risk_per_share = current_atr * Decimal('3.0')

# Generate signal WITH risk_per_share parameter
self.buy('TQQQ', Decimal('0.025'), risk_per_share=dollar_risk_per_share)
# or
self.sell('SQQQ', Decimal('0.025'), risk_per_share=dollar_risk_per_share)
```

**Flat Allocation Mode** (QQQ):
```python
# NO ATR calculation
# NO risk_per_share parameter
# Just flat 50% allocation

self.buy('QQQ', Decimal('0.50'))  # NO risk_per_share!

# Track regime for exit management
self.qqq_position_regime = 3
```

## Implementation Patterns

### Class Structure

**Parameters** (in `init()`):
```python
# Indicator parameters
self.ema_period = 100
self.macd_fast = 12
self.macd_slow = 26
self.macd_signal = 9
self.vix_threshold = Decimal('30.0')

# ATR parameters
self.atr_period = 14
self.atr_stop_multiplier = Decimal('3.0')

# Position sizing (DUAL MODE)
self.leveraged_risk = Decimal('0.025')  # 2.5% for TQQQ/SQQQ
self.qqq_allocation = Decimal('0.50')   # 50% flat for QQQ

# State tracking
self.previous_regime = 0  # Track regime (1-5)
self.qqq_position_regime = None  # Track QQQ regime for exit
```

### Key Methods

**`_determine_regime(bar)` → int**:
```python
def _determine_regime(self, bar: MarketDataEvent) -> int:
    """Determine regime 1-5 based on priority order."""
    # Get indicators on QQQ
    closes = self.get_closes(lookback=110, symbol='QQQ')
    ema_slow = ema(closes, self.ema_period)
    macd_line, signal_line, _ = macd(closes, ...)
    
    # Get current values
    current_price = bar.close
    current_ema = Decimal(str(ema_slow.iloc[-1]))
    current_macd_line = Decimal(str(macd_line.iloc[-1]))
    current_signal_line = Decimal(str(signal_line.iloc[-1]))
    
    # Get VIX
    vix_bars = [b for b in self._bars if b.symbol == '$VIX']
    current_vix = vix_bars[-1].close
    
    # Priority order (if/elif ladder)
    if current_vix > self.vix_threshold:
        return 1  # VIX FEAR
    
    if current_price > current_ema and current_macd_line > current_signal_line:
        return 2  # STRONG BULL
    
    if current_price > current_ema and current_macd_line <= current_signal_line:
        return 3  # WEAK BULL (NOTE: <=, not <, for edge case)
    
    if current_price < current_ema and current_macd_line < Decimal('0.0'):
        return 4  # STRONG BEAR (ZERO-LINE CHECK)
    
    return 5  # CHOP (default)
```

**`on_bar(bar)` Processing**:
```python
def on_bar(self, bar: MarketDataEvent):
    """Main bar processing - only process QQQ bars for signals."""
    # 1. Only process QQQ bars for regime determination
    if bar.symbol != 'QQQ':
        return
    
    # 2. Validate all symbols present (once)
    if not self.symbols_validated:
        self._validate_symbols()
        self.symbols_validated = True
    
    # 3. Need sufficient bars for indicators
    if len(self._bars) < 110:
        return
    
    # 4. Determine current regime
    current_regime = self._determine_regime(bar)
    
    # 5. Handle regime transitions
    if current_regime != self.previous_regime:
        # Exit current positions if needed
        # Enter new positions based on new regime
        self.previous_regime = current_regime
    
    # 6. Check stop-losses for leveraged positions (TQQQ/SQQQ)
    if bar.symbol in ['TQQQ', 'SQQQ']:
        self._check_stop_loss(bar)
```

### Exit Logic Differences

**TQQQ/SQQQ** (ATR mode):
- Portfolio module manages ATR stops automatically
- Strategy just checks for regime changes
- Exit on regime change OR stop hit

**QQQ** (Flat mode):
```python
# In on_bar() - check for QQQ exit
if self.has_position('QQQ') and current_regime != 3:
    # Regime changed from WEAK BULL - exit QQQ
    self.buy('QQQ', Decimal('0.0'))  # Close position
    self.qqq_position_regime = None
```

## Critical Implementation Details

### 1. MACD Zero-Line Check
```python
# Regime 4 condition (CRITICAL!)
if current_price < current_ema and current_macd_line < Decimal('0.0'):
    return 4  # STRONG BEAR

# NOT just MACD < Signal (that would be wrong)
# Must check MACD < 0 (zero-line)
```

### 2. Edge Case: MACD == Signal_Line
```python
# Regime 3 condition (NOTE: <=, not <)
if current_price > current_ema and current_macd_line <= current_signal_line:
    return 3  # WEAK BULL

# If MACD_Line == Signal_Line → Should be regime 3 (WEAK BULL), not 5 (CHOP)
# This was a bug fix - initially used < instead of <=
```

### 3. QQQ State Tracking
```python
# Track which regime opened QQQ position
self.qqq_position_regime = None  # Initially None

# On QQQ entry (regime 3)
def _enter_qqq(self, bar):
    self.buy('QQQ', self.qqq_allocation)  # No risk_per_share!
    self.qqq_position_regime = 3  # Track regime

# On regime change
if self.has_position('QQQ') and current_regime != 3:
    self.buy('QQQ', Decimal('0.0'))  # Exit
    self.qqq_position_regime = None  # Reset tracking
```

### 4. SQQQ Inverse Stop Logic
```python
# For SQQQ (short position), stop is ABOVE entry (not below)
# Stop = Fill_Price + (ATR × 3.0)

# Portfolio module handles this automatically when risk_per_share passed
# Strategy just generates SELL signal
self.sell('SQQQ', Decimal('0.025'), risk_per_share=dollar_risk_per_share)
```

## Testing Strategy

### Test Coverage: 56 tests, 87% coverage

**Category 1: Initialization** (6 tests):
- Default parameters
- Custom parameters
- Trading symbols
- State tracking
- Dual role QQQ

**Category 2: Symbol Validation** (5 tests):
- All symbols present
- Missing QQQ, VIX, TQQQ, SQQQ

**Category 3: Regime Determination** (13 tests):
- Each regime independently (1-5)
- Priority order enforcement
- MACD zero-line check
- Edge cases (VIX=30, MACD=0, Price=EMA, MACD=Signal)

**Category 4: Position Sizing** (8 tests):
- TQQQ ATR mode
- SQQQ ATR mode (inverse stop)
- QQQ flat mode (no risk_per_share)
- QQQ no stop tracking
- TQQQ/SQQQ stop tracking
- Allocation parameters

**Category 5: Regime Transitions** (10 tests):
- All entry transitions (1→2, 2→3, 3→2, 3→4, 4→1)
- QQQ regime-managed exit
- TQQQ/SQQQ exits on regime change
- Stop-loss exits
- Complex transitions (TQQQ→SQQQ)

**Category 6: Multi-Symbol Processing** (6 tests):
- Only QQQ bars trigger regime checks
- VIX/TQQQ/SQQQ bars ignored
- All 4 symbols required
- QQQ dual role
- Stop checks on leveraged symbols only

**Category 7: Edge Cases** (4 tests):
- VIX exactly 30
- MACD exactly 0
- Price exactly equals EMA
- MACD exactly equals Signal

**Category 8: on_bar Processing** (4 tests):
- Insufficient bars handling
- Symbol validation (once only)
- Regime determination
- Stop-loss checking

## Issues Fixed During Implementation

### Issue 1: Regime 3 Condition (MACD == Signal_Line)
**Problem**: Tests expected regime 3 when `MACD_Line == Signal_Line`, but got regime 5 (CHOP)
**Root Cause**: Used strict `<` instead of `<=`
**Fix**: Changed line 316 from `macd_line < signal_line` to `macd_line <= signal_line`
**Impact**: 2 tests now pass

### Issue 2: ATR Mocking in Tests
**Problem**: 4 tests failed with `AttributeError: 'builtin_function_or_method' object has no attribute 'return_value'`
**Root Cause**: Trying to mock pandas Series `iloc` accessor incorrectly
**Fix**: Use actual pandas Series: `mock_series = pd.Series([value]); mock_atr.return_value = mock_series`
**Impact**: 4 tests now pass

## Comparison to Other Strategies

### vs MACD_Trend V5.0 (just implemented):
- **Regimes**: 5 vs 2 states (more complex)
- **Trading**: Multi-directional (bull/defensive/bear) vs long-only
- **Vehicles**: 4 (TQQQ/QQQ/SQQQ/CASH) vs 2 (TQQQ/CASH)
- **Sizing**: Dual mode (ATR + flat) vs ATR only
- **QQQ**: Trading vehicle vs signal only
- **MACD**: Zero-line check added vs line vs signal only
- **Complexity**: Medium vs Simple

### vs Momentum_ATR:
- **Regimes**: 5 vs 6 (simpler)
- **Logic**: Priority order vs histogram delta tracking
- **Trend Filter**: 100-EMA added vs none
- **Risk**: Fixed 2.5% vs variable (3.0%/1.5%)
- **QQQ**: Trades QQQ (50%) vs no QQQ trading
- **Stop**: 3.0 ATR vs 2.0 ATR

## Files Modified

1. **`jutsu_engine/strategies/MACD_Trend_v2.py`** (668 lines) - NEW
2. **`tests/unit/strategies/test_macd_trend_v2.py`** (981 lines, 56 tests) - NEW
3. **`.claude/layers/core/modules/STRATEGY_AGENT.md`** (842 lines) - UPDATED (Task 0 added)
4. **`CHANGELOG.md`** - UPDATED (comprehensive entry added)

## Performance Metrics

- **Test Runtime**: 1.84 seconds ✅
- **Test Pass Rate**: 100% (56/56) ✅
- **Coverage**: 87% (exceeds >80% target) ✅
- **Type Hints**: All functions ✅
- **Docstrings**: Google-style on all methods ✅
- **Logging**: Uses `self.log()` for all regime transitions ✅

## Usage Example

```python
from jutsu_engine.strategies.MACD_Trend_v2 import MACD_Trend_v2
from jutsu_engine.application.backtest_runner import BacktestRunner

# Create strategy instance
strategy = MACD_Trend_v2(
    ema_period=100,
    macd_fast=12,
    macd_slow=26,
    macd_signal=9,
    vix_threshold=30.0,
    atr_period=14,
    atr_stop_multiplier=3.0,
    leveraged_risk=0.025,  # 2.5% for TQQQ/SQQQ
    qqq_allocation=0.50    # 50% for QQQ
)

# Run backtest
runner = BacktestRunner(
    strategy=strategy,
    symbols=['QQQ', '$VIX', 'TQQQ', 'SQQQ'],
    start_date='2020-01-01',
    end_date='2024-12-31',
    initial_capital=100000
)

results = runner.run()
```

## Lessons Learned

1. **Priority Systems**: if/elif ladder enforces priority better than independent checks
2. **Edge Cases**: Always test equality conditions (MACD == Signal, Price == EMA, etc.)
3. **Dual Modes**: Separate parameters for different sizing modes (risk_per_share vs None)
4. **State Tracking**: Track state for regime-managed exits (qqq_position_regime)
5. **Test Mocking**: Use actual pandas Series, not MagicMock for iloc accessor
6. **Zero-Line Checks**: MACD < 0 is different from MACD < Signal (both important)
7. **Inverse Stops**: Short positions (SQQQ) have stops ABOVE entry, not below

## Ready for Production

✅ **Implementation**: Complete with all features
✅ **Testing**: 56 tests, 100% pass rate, 87% coverage
✅ **Documentation**: CHANGELOG.md + agent context updated
✅ **Quality**: Type hints, docstrings, logging, follows V5.0 patterns
✅ **Performance**: <2 second test runtime
✅ **Integration**: Ready for BacktestRunner use

**Next Steps** (if needed):
1. Run production backtest with real historical data
2. Analyze performance metrics (Sharpe, drawdown, etc.)
3. Compare results against MACD_Trend V5.0 and Momentum_ATR
4. Optimize parameters if needed (grid search, walk-forward)
