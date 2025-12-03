# Kalman Trend Detector (Adaptive Kalman Filter)

## What It Is

The Adaptive Kalman Filter is a stateful indicator that provides noise-filtered price predictions with directional trend strength measurement. Unlike traditional moving averages, it uses Bayesian estimation to recursively update price predictions based on new measurements, adapting to changing market conditions.

**Purpose**: Filter market noise from price data and quantify trend strength with direction (+/-) for regime classification.

## Model Type

This implementation uses the **VOLUME_ADJUSTED** model:
- Higher trading volume → Lower measurement noise → More confidence in price signal
- Lower trading volume → Higher measurement noise → Less confidence (filter dampens changes)

## Mathematical Foundation

### State-Space Model

The filter tracks a 2D state vector:
```
X = [position, velocity]
```

Where:
- `position` = filtered price estimate
- `velocity` = rate of price change (trend momentum)

### Kalman Filter Equations

**Prediction Step**:
```
X_pred = F @ X
P_pred = F @ P @ F^T + Q
```

**Update Step**:
```
Innovation = z - H @ X_pred
S = H @ P_pred @ H^T + R
K = P_pred @ H^T @ inv(S)
X = X_pred + K @ Innovation
P = (I - K @ H) @ P_pred
```

### Matrices

**State Transition Matrix (F)**:
```
F = [[1.0, 1.0],
     [0.0, 1.0]]
```

**Observation Matrix (H)**:
```
H = [[1.0, 0.0]]  # Observe position only
```

**Process Noise Matrix (Q)**:
```
Q = [[process_noise_1,           0.0],
     [          0.0, process_noise_2]]
```

**Measurement Noise Matrix (R)** (Volume-Adjusted):
```
R_base = [[measurement_noise]]

# Volume adjustment (higher volume → lower noise)
if volume > prev_volume:
    vol_ratio = prev_volume / volume
    R_adjusted = R_base * vol_ratio
else:
    R_adjusted = R_base
```

### Trend Strength Calculation

**Oscillator**:
```
max_innovation = max(abs(innovation) over sigma_lookback=500 bars)
oscillator = (innovation / max_innovation) * 100
```

**Trend Strength** (Weighted Moving Average of Oscillator):
```
weights = [1, 2, 3, ..., osc_smoothness]
trend_strength_signed = WMA(oscillator, period=osc_smoothness)
```

**Output Range**: `[-100, +100]`
- Positive values: Bullish trend (prices exceeding prediction)
- Negative values: Bearish trend (prices below prediction)
- Magnitude: Strength of trend

## Input Parameters

### Golden Config Values (v3.5b)
From `grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml`:

```yaml
measurement_noise: 3000.0      # Base measurement noise (higher = more smoothing)
process_noise_1: 0.01          # Position uncertainty (low = trust model dynamics)
process_noise_2: 0.01          # Velocity uncertainty
osc_smoothness: 15             # Oscillator smoothing period
strength_smoothness: 15        # Trend strength smoothing period
```

### Fixed Parameters
```python
model=KalmanFilterModel.VOLUME_ADJUSTED  # Volume-weighted noise adjustment
sigma_lookback=500                        # Innovation buffer size
trend_lookback=10                         # Oscillator buffer size
return_signed=True                        # Return signed trend strength
```

## Outputs

### 1. Filtered Price
- **Type**: Decimal
- **Description**: Kalman-filtered price estimate (noise-reduced)
- **Usage**: Not directly used in v3.5b (trend strength is primary signal)

### 2. Trend Strength (Signed)
- **Type**: Decimal
- **Range**: `[-100, +100]`
- **Description**: Directional trend strength oscillator
- **Interpretation**:
  - `> 0`: Bullish momentum
  - `< 0`: Bearish momentum
  - `|value|`: Magnitude of trend

**Normalized Form (T_norm)** used in v3.5b:
```python
T_norm = trend_strength_signed / T_max
```

Where `T_max = 50.0` (golden config), resulting in:
- `T_norm ∈ [-1.0, +1.0]`

## Usage in Hierarchical Adaptive v3.5b

### Initialization
```python
self.kalman_filter = AdaptiveKalmanFilter(
    model=KalmanFilterModel.VOLUME_ADJUSTED,
    measurement_noise=float(3000.0),
    process_noise_1=float(0.01),
    process_noise_2=float(0.01),
    osc_smoothness=15,
    strength_smoothness=15,
    return_signed=True
)
```

### Bar-by-Bar Update
```python
filtered_price, trend_strength_signed = self.kalman_filter.update(
    close=bar.close,
    high=bar.high,
    low=bar.low,
    volume=bar.volume  # Required for VOLUME_ADJUSTED model
)

T_norm = trend_strength_signed / Decimal("50.0")  # Normalize to [-1, +1]
```

### Trend Classification
```python
# Hierarchical logic: Fast (Kalman) gated by Slow (SMA)
if T_norm > 0.20 and sma_fast > sma_slow:
    trend_state = "BullStrong"
elif T_norm < -0.30 and sma_fast < sma_slow:
    trend_state = "BearStrong"
else:
    trend_state = "Sideways"
```

## Code References

**Implementation**: `jutsu_engine/indicators/kalman.py`
- Class: `AdaptiveKalmanFilter` (lines 51-401)
- Volume Adjustment: `_adjust_measurement_noise()` (lines 268-318)
- Trend Strength: `_calculate_trend_strength()` (lines 320-363)

**Usage**: `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py`
- Initialization: lines 317-325
- Update: lines 401-407
- Normalization: `_calculate_kalman_trend()` (lines 585-596)
- Classification: `_classify_trend_regime()` (lines 745-774)

## Performance Characteristics

- **Update Time**: <5ms per bar (NumPy matrix operations)
- **Memory**: O(sigma_lookback) = O(500) for innovation buffer
- **Warmup**: 1 bar minimum (initializes state on first bar)
- **State**: Maintains internal matrices and buffers (stateful indicator)

## Key Properties

1. **Adaptive**: Volume-weighted noise adjustment responds to market activity
2. **Directional**: Signed output preserves trend direction
3. **Normalized**: T_norm ∈ [-1, +1] for consistent threshold application
4. **Stateful**: Must be initialized once per symbol and updated sequentially
5. **Robust**: Handles missing volume gracefully (falls back to base noise)

## Interpretation Guidelines

### T_norm Thresholds (Golden Config)
- `T_norm > 0.20`: Moderate bullish trend (BullStrong threshold)
- `T_norm < -0.30`: Strong bearish trend (BearStrong threshold)
- `|T_norm| < 0.20`: Weak/sideways trend

### Signal Quality
- Higher volume → Lower noise → More responsive filter
- Lower volume → Higher noise → More smoothing (trend confirmation)
- Innovation spikes → Trend strength increases
- Sustained innovations → Strong directional trend
