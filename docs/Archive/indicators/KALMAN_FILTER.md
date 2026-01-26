# Adaptive Kalman Filter - Trend Strength Oscillator

## Overview

The Adaptive Kalman Filter is a sophisticated stateful indicator that applies Kalman filtering to price data to produce:
1. **Filtered Price**: Smooth, noise-reduced price estimate
2. **Trend Strength**: Oscillator value from -100 to +100 indicating trend momentum

Based on the TradingView indicator by Zeiierman.

## Algorithm

### State Space Model

The filter models price as a 2-dimensional state vector:
- **Position** (x₁): Filtered price estimate
- **Velocity** (x₂): Rate of price change (momentum)

### Kalman Filter Cycle

**1. Prediction Step**:
```
X_pred = F @ X
P_pred = F @ P @ F.T + Q
```

**2. Measurement Update**:
```
Innovation = z - H @ X_pred
S = H @ P @ H.T + R
K = P @ H.T @ inv(S)  (Kalman Gain)
```

**3. State Update**:
```
X = X_pred + K @ innovation
P = (I - K @ H) @ P_pred
```

**4. Trend Strength**:
```
oscillator = X[1]  (velocity component)
trend_strength = WMA(oscillator / max_oscillator * 100)
```

### Matrices

- **F** (Transition): [[1, 1], [0, 1]]
- **H** (Observation): [[1, 0]]
- **Q** (Process Noise): Configurable 2x2
- **R** (Measurement Noise): Configurable 1x1 (model-dependent)
- **P** (Covariance): Evolves with each update
- **I** (Identity): [[1, 0], [0, 1]]

## Parameters

### Core Parameters

**process_noise_1** (default: 0.01)
- Primary noise factor for filter process
- Higher values → more responsive, less smooth
- Adjust based on market volatility
- Range: 0.0 to 10000.0

**process_noise_2** (default: 0.01)
- Secondary noise factor working with process_noise_1
- Affects velocity component noise
- Fine-tune alongside process_noise_1
- Range: 0.0 to 10000.0

**measurement_noise** (default: 500.0)
- Defines noise level in price data
- Higher values → rely more on past data, less responsive
- Controls smoothness vs responsiveness trade-off
- Range: 0.0 to 10000.0

### Model Selection

**model** (default: STANDARD)
- `STANDARD`: Fixed measurement noise
- `VOLUME_ADJUSTED`: Adapts noise based on volume ratio
- `PARKINSON_ADJUSTED`: Adapts noise based on price range volatility

### Oscillator Parameters

**osc_smoothness** (default: 10)
- Smoothing for trend strength oscillator
- Higher → smoother but delayed
- Lower → more reactive to trend changes
- Range: 2+

**strength_smoothness** (default: 10)
- Additional smoothing for trend strength
- Creates gradual trend strength curve
- Range: 2+

### Lookback Parameters

**sigma_lookback** (default: 500)
- Bars used for standard deviation calculation
- Higher → more stable, uses more history
- Lower → more responsive to recent changes
- Range: 2+

**trend_lookback** (default: 10)
- Period for trend strength calculation
- Shorter → sensitive to recent trends
- Longer → emphasizes longer-term movement
- Range: 2+

## Noise Adjustment Models

### Standard Model
```python
R_adjusted = R  # No adjustment
```

Fixed measurement noise throughout.

**Use when**: Standard conditions, no special market dynamics

### Volume-Adjusted Model
```python
R_adjusted = R * (volume[t-1] / min(volume[t-1], volume[t]))
```

Adapts measurement noise based on volume ratio:
- Low volume → higher noise (less trust in price)
- High volume → lower noise (more trust in price)

**Use when**: Volume is a good indicator of price reliability

**Requires**: `volume` parameter in `update()`

### Parkinson-Adjusted Model
```python
range_ratio = (high - low) / (high[t-1] - low[t-1])
R_adjusted = R * (1 + range_ratio)
```

Adapts measurement noise based on price range volatility:
- Wide range → higher noise (volatile, less reliable)
- Narrow range → lower noise (stable, more reliable)

**Use when**: Intraday range reflects market uncertainty

**Requires**: `high` and `low` parameters in `update()`

## Usage Examples

### Basic Usage (Standard Model)

```python
from jutsu_engine.indicators.kalman import (
    AdaptiveKalmanFilter,
    KalmanFilterModel
)
from decimal import Decimal

# Initialize filter
kf = AdaptiveKalmanFilter(
    process_noise_1=0.01,
    measurement_noise=500.0,
    model=KalmanFilterModel.STANDARD
)

# Update bar-by-bar
for bar in historical_data:
    filtered_price, trend_strength = kf.update(close=bar.close)

    print(f"Filtered: {filtered_price}, Trend: {trend_strength}")
```

### Volume-Adjusted Model

```python
# Initialize with volume adjustment
kf = AdaptiveKalmanFilter(
    model=KalmanFilterModel.VOLUME_ADJUSTED,
    measurement_noise=300.0  # Lower base noise
)

# Provide volume data
for bar in historical_data:
    filtered_price, trend_strength = kf.update(
        close=bar.close,
        volume=bar.volume  # Required for this model
    )
```

### Parkinson-Adjusted Model

```python
# Initialize with range-based adjustment
kf = AdaptiveKalmanFilter(
    model=KalmanFilterModel.PARKINSON_ADJUSTED,
    measurement_noise=400.0
)

# Provide high/low data
for bar in historical_data:
    filtered_price, trend_strength = kf.update(
        close=bar.close,
        high=bar.high,    # Required
        low=bar.low       # Required
    )
```

### Strategy Integration

```python
from jutsu_engine.core.strategy_base import Strategy

class KalmanTrendStrategy(Strategy):
    def init(self):
        self.kf = AdaptiveKalmanFilter(
            model=KalmanFilterModel.VOLUME_ADJUSTED,
            measurement_noise=500.0
        )
        self.trend_threshold = Decimal('30.0')

    def on_bar(self, bar):
        # Update filter
        filtered_price, trend_strength = self.kf.update(
            close=bar.close,
            volume=bar.volume
        )

        # Trading logic
        if trend_strength > self.trend_threshold:
            # Strong uptrend
            if not self.has_position():
                self.buy(bar.symbol, 100)

        elif trend_strength < -self.trend_threshold:
            # Strong downtrend
            if self.has_position():
                self.sell(bar.symbol, 100)
```

## Interpretation

### Filtered Price
- **Smooth price estimate** with reduced noise
- Use for: Support/resistance levels, trend identification
- Always lags actual price (inherent to filtering)

### Trend Strength
- **Range**: -100 (strong downtrend) to +100 (strong uptrend)
- **Zero**: No clear trend
- **±30**: Moderate trend threshold
- **±70**: Strong trend threshold (used in TradingView)

**Signals**:
- `> 30`: Bullish momentum building
- `> 70`: Overbought, strong uptrend
- `< -30`: Bearish momentum building
- `< -70`: Oversold, strong downtrend
- `-30 to +30`: Neutral/ranging market

## Performance Characteristics

- **Update Time**: <5ms per bar (NumPy optimized)
- **Memory**: O(lookback_period) for buffers
- **Initialization**: Requires ~2-3 bars for stability
- **State**: Maintains across updates (stateful)

## Limitations

1. **Lag**: Inherent to all filtering - filtered price lags actual price
2. **Initialization**: First few bars may be unstable
3. **Statefulness**: Must maintain filter instance across bars
4. **Model Selection**: Wrong model can reduce effectiveness
5. **Parameter Tuning**: Requires optimization for specific markets

## Mathematical Background

### Kalman Filter Theory

The Kalman filter is an optimal recursive estimator for linear dynamic systems with Gaussian noise.

**Assumptions**:
- Price follows linear dynamics: X(t+1) = F @ X(t) + w
- Observations are linear: z(t) = H @ X(t) + v
- Noise is Gaussian: w ~ N(0, Q), v ~ N(0, R)

**Optimality**:
- Minimizes mean squared error of state estimate
- Optimal for linear-Gaussian systems
- Suboptimal but robust for non-linear/non-Gaussian (like prices)

### Weighted Moving Average (WMA)

```
WMA = (p₁·1 + p₂·2 + ... + pₙ·n) / (1 + 2 + ... + n)
```

Where recent prices have higher weights.

## References

1. **Original Indicator**: "Adaptive Kalman filter - Trend Strength Oscillator" by Zeiierman (TradingView)
2. **Kalman Filter**: Kalman, R.E. (1960). "A New Approach to Linear Filtering and Prediction Problems"
3. **Parkinson Volatility**: Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance of the Rate of Return"

## See Also

- `docs/API_REFERENCE.md`: Full API documentation
- `jutsu_engine/indicators/kalman.py`: Source code
- `tests/unit/indicators/test_kalman.py`: Test suite and examples
