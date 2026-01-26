# Volatility Z-Score System

## What It Is

The Volatility Z-Score is an adaptive regime detection system that measures current market volatility relative to its historical baseline using standardized statistical distance (z-score). This eliminates look-ahead bias and adapts to changing volatility regimes without hardcoded percentile thresholds.

**Purpose**: Classify market volatility as "Low" or "High" to adjust portfolio leverage and risk exposure dynamically.

## Mathematical Formula

### Step 1: Calculate Realized Volatility

**Log Returns**:
```
log_return(t) = ln(P(t) / P(t-1))
```

**Rolling Standard Deviation** (21-day window):
```
σ_daily = std(log_returns, window=21)
```

**Annualized Volatility**:
```
σ_annual = σ_daily * √(252)
```

Where `252` = trading days per year.

### Step 2: Calculate Baseline Statistics

**Volatility Time Series**:
```
σ_series = [σ_annual(t-125), σ_annual(t-124), ..., σ_annual(t)]
```

**Mean** (126-day baseline):
```
μ_vol = mean(σ_series, window=126)
```

**Standard Deviation** (126-day baseline):
```
σ_vol = std(σ_series, window=126)
```

### Step 3: Compute Z-Score

**Current Realized Volatility**:
```
σ_t = σ_annual(t)
```

**Z-Score**:
```
z_score = (σ_t - μ_vol) / σ_vol
```

**Interpretation**:
- `z_score = 0`: Volatility at historical average
- `z_score > 0`: Volatility above average (elevated risk)
- `z_score < 0`: Volatility below average (calm market)
- `|z_score| > 1`: Volatility >1 standard deviation from mean (significant regime shift)

## Input Parameters

### Golden Config Values (v3.5b)
From `grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml`:

```yaml
realized_vol_window: 21       # Rolling window for realized volatility calculation
vol_baseline_window: 126      # Baseline statistics window (mean, std)
upper_thresh_z: 1.0           # Z-score threshold for High volatility
lower_thresh_z: 0.2           # Z-score threshold for Low volatility
```

### Rationale
- **21 days**: ~1 month of trading data (responsive to recent volatility changes)
- **126 days**: ~6 months of baseline (captures medium-term regime)
- **Thresholds**:
  - `upper_thresh_z = 1.0`: High vol = 1σ above mean (top ~16% historically)
  - `lower_thresh_z = 0.2`: Low vol = 0.2σ above mean (below average but not extreme)

## Outputs

### 1. Realized Volatility (σ_t)
- **Type**: Decimal (annualized)
- **Range**: `[0, ∞)` (typically 10%-50% for QQQ)
- **Example**: `0.20` = 20% annualized volatility

### 2. Z-Score
- **Type**: Decimal
- **Range**: `(-∞, +∞)` (typically -2 to +3)
- **Example**: `1.5` = current vol is 1.5σ above baseline mean

### 3. Volatility State (via Hysteresis)
- **Type**: String ("Low" or "High")
- **Logic**: See `Hysteresis_State_Machine.md`

## Usage in Hierarchical Adaptive v3.5b

### Calculation
```python
def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
    """
    Calculate rolling z-score of realized volatility.

    Returns None if insufficient data (< 147 bars).
    """
    # Step 1: Calculate realized volatility
    vol_series = annualized_volatility(closes, lookback=21)

    # Step 2: Get baseline statistics (last 126 volatility values)
    vol_values = vol_series.tail(126)
    vol_mean = Decimal(str(vol_values.mean()))
    vol_std = Decimal(str(vol_values.std()))

    if vol_std == Decimal("0"):
        return Decimal("0")  # Edge case: constant volatility

    # Step 3: Compute z-score
    sigma_t = Decimal(str(vol_series.iloc[-1]))
    z_score = (sigma_t - vol_mean) / vol_std

    return z_score
```

### Integration with Hysteresis
```python
# Calculate z-score
z_score = self._calculate_volatility_zscore(closes)

if z_score is None:
    logger.error("Insufficient warmup data")
    return

# Apply hysteresis state machine (see Hysteresis_State_Machine.md)
self._apply_hysteresis(z_score)

# Result: self.vol_state ∈ {"Low", "High"}
```

## Code References

**Realized Volatility**: `jutsu_engine/indicators/technical.py`
- Function: `annualized_volatility()` (lines 429-466)
- Formula: `log_returns.rolling(window).std() * sqrt(252)`

**Z-Score Calculation**: `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py`
- Method: `_calculate_volatility_zscore()` (lines 615-659)
- Usage: line 433

## Performance Characteristics

- **Computation**: O(N) rolling window statistics (pandas)
- **Warmup**: 147 bars minimum (21 + 126)
- **Update**: Real-time on each bar
- **Memory**: O(lookback) temporary pandas Series

## Advantages Over Static Percentiles

### Static Percentile Approach (v1.0-v2.8)
```python
# Look-ahead bias: Uses future data to calibrate thresholds
vol_percentiles = np.percentile(all_volatility, [33, 66])

if vol < vol_percentiles[0]:
    vol_state = "Low"
elif vol < vol_percentiles[1]:
    vol_state = "Medium"
else:
    vol_state = "High"
```

**Problems**:
1. **Look-ahead bias**: Thresholds depend on entire dataset (including future)
2. **Regime instability**: 2010 thresholds don't work for 2020
3. **Magic numbers**: Percentiles don't adapt to changing baselines

### Z-Score Approach (v3.5b)
```python
# Rolling baseline: Only uses past data
z_score = (current_vol - rolling_mean) / rolling_std

if z_score > 1.0:
    vol_state = "High"
elif z_score < 0.2:
    vol_state = "Low"
```

**Advantages**:
1. **No look-ahead**: Only uses historical data available at decision time
2. **Adaptive**: Thresholds adjust to changing volatility regimes
3. **Statistical**: z-score has consistent interpretation across decades
4. **Robust**: Works on 2010-2015 (low vol) and 2020-2022 (high vol) equally well

## Example Calculation

**Market Context**: Post-COVID recovery (2020-2021)

```
Date: 2021-03-15

Step 1: Realized Volatility
  Closes (last 21 days): [420, 422, 418, ..., 425]
  Log returns: [0.0048, -0.0095, ..., 0.0024]
  σ_daily = std(log_returns, 21) = 0.0125
  σ_annual = 0.0125 * √252 = 0.198 (19.8%)

Step 2: Baseline Statistics
  Volatility series (last 126 days): [0.15, 0.16, ..., 0.198]
  μ_vol = mean([0.15, ..., 0.198]) = 0.18
  σ_vol = std([0.15, ..., 0.198]) = 0.025

Step 3: Z-Score
  z_score = (0.198 - 0.18) / 0.025 = 0.72

Interpretation:
  z_score = 0.72 < upper_thresh_z (1.0)
  z_score = 0.72 > lower_thresh_z (0.2)
  → Within deadband → Maintain current vol_state (hysteresis)
```

## Regime Examples

### Low Volatility Regime (2017)
```
σ_t = 8% annualized
μ_vol = 12% (baseline)
σ_vol = 3%
z_score = (0.08 - 0.12) / 0.03 = -1.33 < 0.2
→ vol_state = "Low" (calm market)
```

### High Volatility Regime (March 2020)
```
σ_t = 65% annualized
μ_vol = 18% (pre-COVID baseline)
σ_vol = 8%
z_score = (0.65 - 0.18) / 0.08 = 5.875 > 1.0
→ vol_state = "High" (crisis)
```

### Moderate Volatility Regime (2021)
```
σ_t = 20% annualized
μ_vol = 18% (post-COVID baseline)
σ_vol = 5%
z_score = (0.20 - 0.18) / 0.05 = 0.40
→ Within deadband (0.2 to 1.0) → Maintain previous state
```

## Interpretation Guidelines

### Z-Score Ranges
- `z < -1.0`: Extremely calm (rare)
- `-1.0 ≤ z < 0.2`: Low volatility (bullish for leverage)
- `0.2 ≤ z ≤ 1.0`: Moderate volatility (deadband - maintain state)
- `z > 1.0`: Elevated volatility (bearish for leverage)
- `z > 2.0`: High volatility (reduce leverage aggressively)
- `z > 3.0`: Extreme volatility (crisis mode)

### Allocation Impact
- **Low Vol**: Leverage up (TQQQ allocations)
- **High Vol**: Leverage down (QQQ, Cash, Bonds)

## Warmup Requirements

**Total Warmup**: 147 bars minimum
- 21 bars for first realized vol calculation
- 126 bars for baseline statistics

**Strategy Ensures Sufficient Data** (lines 631-633):
```python
if len(closes) < self.vol_baseline_window + self.realized_vol_window:
    return None  # Insufficient data
```

**EventLoop Handles Warmup** (lines 93, 174-175):
```
warmup_end_date = start_date - timedelta(days=150)
# Fetches 150 bars before start_date (warmup phase, no trades)
```
