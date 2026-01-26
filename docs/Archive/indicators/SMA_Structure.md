# SMA Structure (Simple Moving Average)

## What It Is

Simple Moving Average (SMA) is the arithmetic mean of prices over a specified number of periods. In the Hierarchical Adaptive v3.5b strategy, a **dual-SMA crossover system** acts as a structural trend filter to gate the fast Kalman trend signal.

**Purpose**: Provide slow, stable trend direction to prevent whipsaws in choppy markets and confirm Kalman-detected trends.

## Mathematical Formula

### SMA Calculation

For a price series `P = [P₁, P₂, ..., Pₙ]` and period `N`:

```
SMA(t, N) = (P(t) + P(t-1) + ... + P(t-N+1)) / N
```

**Example** (3-period SMA):
```
Prices: [100, 102, 101, 103, 105, 104, 106]
SMA(3): [NaN, NaN, 101.0, 102.0, 103.0, 104.0, 105.0]
```

Where:
- First N-1 values are NaN (insufficient data)
- SMA(t=2) = (100 + 102 + 101) / 3 = 101.0
- SMA(t=3) = (102 + 101 + 103) / 3 = 102.0

### Crossover Logic

**Bull Trend**: `SMA_fast > SMA_slow`
- Fast SMA above slow SMA indicates upward momentum
- Price structure trending higher

**Bear Trend**: `SMA_fast < SMA_slow`
- Fast SMA below slow SMA indicates downward momentum
- Price structure trending lower

## Input Parameters

### Golden Config Values (v3.5b)
From `grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml`:

```yaml
sma_fast: 40    # Fast structural trend (responsive to recent moves)
sma_slow: 140   # Slow structural trend (stable long-term direction)
```

### Rationale
- **40-day**: Captures 8-week (2-month) trend structure
- **140-day**: Captures ~28-week (7-month) trend structure
- **Ratio**: 3.5x separation prevents excessive whipsaws

## Outputs

### 1. SMA_fast
- **Type**: Decimal
- **Period**: 40 days
- **Description**: Short-term trend direction

### 2. SMA_slow
- **Type**: Decimal
- **Period**: 140 days
- **Description**: Long-term trend direction

### 3. Structural Trend (Derived)
- **Type**: String ("Bull" or "Bear")
- **Logic**:
  ```python
  "Bull" if sma_fast > sma_slow else "Bear"
  ```

## Usage in Hierarchical Adaptive v3.5b

### Calculation
```python
# Lookback must account for slow SMA + buffer
sma_lookback = self.sma_slow + 10  # 140 + 10 = 150 bars

closes = self.get_closes(
    lookback=sma_lookback,
    symbol=self.signal_symbol  # QQQ
)

sma_fast_series = sma(closes, period=40)
sma_slow_series = sma(closes, period=140)

sma_fast_val = Decimal(str(sma_fast_series.iloc[-1]))
sma_slow_val = Decimal(str(sma_slow_series.iloc[-1]))
```

### Hierarchical Trend Classification

**Two-Stage Gating**:
```python
is_struct_bull = sma_fast_val > sma_slow_val  # Stage 1: Structural filter

# Stage 2: Kalman signal gated by structural trend
if T_norm > 0.20 and is_struct_bull:
    trend_state = "BullStrong"
elif T_norm < -0.30 and not is_struct_bull:
    trend_state = "BearStrong"
else:
    trend_state = "Sideways"
```

**Logic**:
- Kalman (fast) detects short-term momentum
- SMA crossover (slow) confirms structural trend
- Both must align for "Strong" classification
- Misalignment → "Sideways" (defensive)

## Code References

**Implementation**: `jutsu_engine/indicators/technical.py`
- Function: `sma()` (lines 40-59)
- Formula: `series.rolling(window=period).mean()`

**Usage**: `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py`
- Calculation: lines 418-430
- Structural Trend: `_calculate_structural_trend()` (lines 598-613)
- Classification: `_classify_trend_regime()` (lines 745-774)

## Performance Characteristics

- **Computation**: O(N) rolling window average (pandas optimized)
- **Warmup**: N bars required (40 for fast, 140 for slow)
- **Stateless**: Pure function, no internal state
- **Memory**: O(lookback) temporary pandas Series

## Lag Characteristics

### Fast SMA (40-day)
- **Lag**: ~20 days (half-period)
- **Responsiveness**: Moderate (catches 2-month trends)
- **Noise**: Some sensitivity to short-term volatility

### Slow SMA (140-day)
- **Lag**: ~70 days (half-period)
- **Responsiveness**: Low (stable long-term direction)
- **Noise**: Highly smoothed (ignores short-term chop)

### Crossover Lag
- **Signal Delay**: 30-40 days after true trend change
- **Whipsaw Frequency**: Low (3.5x period ratio reduces false crossovers)
- **Trade-off**: Sacrifices early entry for reliability

## Why SMA Over EMA?

**EMA** (Exponential Moving Average):
- More responsive to recent prices
- Lower lag but higher whipsaw risk
- Better for short-term trading

**SMA** (Simple Moving Average):
- Equal weight to all prices in window
- Higher lag but more stable
- Better for structural trend confirmation

**v3.5b Choice**: SMA prioritizes stability over responsiveness because:
1. Kalman filter provides fast signal (handles responsiveness)
2. SMA acts as gate to prevent Kalman whipsaws
3. Strategy targets multi-week trend holds, not day-trades

## Example Scenario

**Market Context**: Bull market pullback

```
Day 100:
  Price: $450
  SMA_fast (40-day): $445
  SMA_slow (140-day): $420
  → is_struct_bull = True (445 > 420)

Day 110 (10% pullback):
  Price: $405
  SMA_fast (40-day): $442
  SMA_slow (140-day): $425
  → is_struct_bull = True (442 > 425, still bullish structure)

Day 150 (sustained downtrend):
  Price: $380
  SMA_fast (40-day): $415
  SMA_slow (140-day): $430
  → is_struct_bull = False (415 < 430, structure turned bearish)
```

**Insight**: SMA crossover lags price by ~40 days, confirming trend change only after sustained move.

## Interpretation Guidelines

### Bullish Structure
- `SMA_fast > SMA_slow`: Upward trend confirmed
- Strategy can hold aggressive positions (TQQQ) if Kalman also bullish
- Pullbacks treated as buying opportunities

### Bearish Structure
- `SMA_fast < SMA_slow`: Downward trend confirmed
- Strategy defensively positioned (Cash, PSQ, Bonds)
- Rallies treated as exit opportunities

### Sideways (Conflicting Signals)
- Kalman bullish but SMA bearish → Wait for structural confirmation
- Kalman bearish but SMA bullish → Reduce leverage (fragile uptrend)
- Both uncertain → Cash (avoid whipsaw)

## Warmup Requirements

**Minimum Warmup**: 140 bars (slow SMA period)

**Strategy Warmup** (lines 337-373):
```python
def get_required_warmup_bars(self) -> int:
    sma_lookback = self.sma_slow + 10  # 140 + 10 = 150
    vol_lookback = self.vol_baseline_window + self.realized_vol_window  # 126 + 21 = 147
    bond_lookback = self.bond_sma_slow if self.allow_treasury else 0  # 60

    return max(sma_lookback, vol_lookback, bond_lookback)  # 150
```

**Result**: 150 bars fetched before `start_date` to ensure valid SMA calculations.
