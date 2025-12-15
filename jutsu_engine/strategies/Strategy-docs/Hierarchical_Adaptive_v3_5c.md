# Hierarchical Adaptive v3.5c — Golden Strategy Documentation (with Optional Shock Brake)

**Strategy Version**: v3.5c (Binarized Regime Allocator with Treasury Overlay + Optional Shock Brake)
**Configuration**: Golden Config + Shock Brake parameters
**Execution Model**: Signals evaluated at **EOD (close)**; trades executed **at EOD**; P&L realized from next session’s close-to-close

---

## Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [Core Concepts](#core-concepts)
3. [Indicator Systems](#indicator-systems)
4. [Regime Classification](#regime-classification)
5. [6-Cell Allocation Matrix](#6-cell-allocation-matrix)
6. [Trading Logic](#trading-logic)
7. [Performance Characteristics](#performance-characteristics)
8. [Configuration Parameters](#configuration-parameters)

---

## Strategy Overview

Hierarchical Adaptive v3.5b is a **regime-based tactical allocation strategy** that dynamically adjusts portfolio exposure across a **6-cell (Trend × Volatility)** grid using:

* **Fast trend** (Kalman-derived trend strength)
* **Slow trend structure confirmation** (SMA fast/slow)
* **Binary volatility state** (realized-vol z-score with hysteresis)
* **Treasury overlay** (TMF/TMV + Cash in defensive regimes)

### New Addition: Volatility Shock Brake (Optional Module)

The **Shock Brake** is an optional safety overlay designed to address the primary failure mode observed in backtests: **large down days occurring while volatility is still classified “Low”** (and the strategy is more levered).

* When a **single-day shock** exceeds a threshold (e.g., **3% absolute move**), the strategy **forces VolState = High** for a short **cooldown** period.
* This reduces downside tail events and is expected to improve **Sortino** and often **Calmar**, with limited impact to long-run returns when tuned conservatively.

---

## Core Concepts

### Key Features

* **Hierarchical Trend Detection**: Combines fast (Kalman) and slow (SMA) trend signals
* **Binarized Volatility**: Binary High/Low volatility classification with hysteresis
* **6-Cell Regime Grid**: Discrete allocation matrix (Trend × Volatility)
* **Treasury Overlay**: Dynamic safe haven selection (TMF/TMV) in defensive cells
* **Vol-Crush Override**: Rapid V-shaped recovery detection
* **Hysteresis State Machine**: Prevents regime flicker and overtrading
* **Shock Brake (NEW, Optional)**: Forces High-vol state after large single-day shocks

### Strategy Philosophy

1. **Regime Awareness**: Different market regimes demand different risk exposure
2. **Trend-Aligned Leverage**: Use leverage only in bull structure regimes
3. **Volatility Discipline**: Reduce exposure when volatility rises—avoid tail events
4. **Capital Preservation**: Use cash/treasuries defensively when conditions degrade

---

## Indicator Systems

### 1. Kalman Trend Detector (Fast Signal)

**Purpose**: Detect short-term momentum and trend strength

**Parameters** (Golden Config):

```yaml
measurement_noise: 3000.0      # Higher noise = smoother filter
process_noise_1: 0.01          # Position uncertainty
process_noise_2: 0.01          # Velocity uncertainty
osc_smoothness: 15             # Oscillator smoothing period
strength_smoothness: 15        # Trend strength smoothing period
T_max: 50.0                    # Normalization threshold
```

**Output**: `T_norm` (normalized trend strength, typically in [-1, +1])

---

### 2. SMA Structure Filter (Slow Confirmation)

**Purpose**: Confirm long-term market structure to prevent leverage in bearish structure

**Parameters** (Golden Config):

```yaml
sma_fast: 40                   # Fast SMA window (days)
sma_slow: 140                  # Slow SMA window (days)
```

**Output**: `Structure` = Bull or Bear (based on `SMA_fast > SMA_slow`)

---

### 3. Volatility Z-Score System

**Purpose**: Adaptive volatility regime detection without lookback bias

**Parameters** (Golden Config):

```yaml
realized_vol_window: 21        # Short-term vol calculation (days)
vol_baseline_window: 200       # Long-term baseline (days)
upper_thresh_z: 1.0            # Threshold for High vol state
lower_thresh_z: 0.2            # Threshold for Low vol state
```

**Calculation**:

1. Compute realized volatility over `realized_vol_window`: `σ_t`
2. Compute baseline mean/std over `vol_baseline_window`: `μ_vol`, `σ_vol`
3. Compute z-score: `z = (σ_t - μ_vol) / σ_vol`

**Output**: `z_score`

---

### 4. Hysteresis State Machine

**Purpose**: Prevent volatility state flicker when z-score hovers near threshold

**State Transition Rules**:

```
Current State: Low
  if z_score > upper_thresh_z → Transition to High
  else → Remain Low

Current State: High
  if z_score < lower_thresh_z → Transition to Low
  else → Remain High

Deadband: z ∈ [lower_thresh_z, upper_thresh_z] → No state change
```

**Output**: `VolState` = "Low" or "High"

---

### 5. Volatility Shock Brake (NEW, Optional)

**Purpose**: Force a defensive volatility state after large single-day shocks (tail-risk control)

**Parameters** (New):

```yaml
enable_shock_brake: True        # Master switch
shock_threshold_pct: 0.03       # 3% absolute daily move triggers brake
shock_cooldown_days: 5          # Days to force VolState=High after a shock
```

**Detection Logic (EOD)**:

1. Compute daily return of the signal symbol at close: `r_t = Close_t / Close_{t-1} - 1`
2. If `abs(r_t) >= shock_threshold_pct` then **ShockDetected = True**

**Brake State (Cooldown Timer)**:

* If ShockDetected → set `shock_timer = shock_cooldown_days`
* While `shock_timer > 0`:

  * **Force `VolState = High`**
  * Decrement `shock_timer` by 1 each trading day (EOD)

**Design Notes**:

* The Shock Brake is applied **after** z-score + hysteresis determination.
* The Shock Brake is intended to be **conservative**: it does not change trend classification, only volatility state.

---

### 6. Vol-Crush Override

**Purpose**: Detect rapid volatility collapse (V-shaped recoveries) and override overly defensive positioning

**Parameters** (Golden Config):

```yaml
vol_crush_threshold: -0.15      # -15% vol drop triggers override
vol_crush_lookback: 5           # Detection window (days)
```

**Detection Logic**:

1. Compute realized volatility at `t` and `t-lookback`: `σ_t`, `σ_{t-L}`
2. Compute change: `Δvol = (σ_t - σ_{t-L}) / σ_{t-L}`
3. If `Δvol < vol_crush_threshold` → Vol-crush detected

**Override Actions (high level)**:

* Allows earlier risk normalization during sharp volatility collapses (V-shaped recoveries)

**Precedence With Shock Brake**:

* If **Shock Brake timer is active**, Shock Brake takes priority (keeps VolState=High).
* Otherwise, Vol-crush may accelerate return toward Low-vol handling (as implemented in baseline logic).

---

## Regime Classification

### Trend Classification (from `T_norm` + SMA structure)

**Thresholds** (Golden Config):

```yaml
t_norm_bull_thresh: 0.05
t_norm_bear_thresh: -0.30
```

**Classification Logic**:

* **BullStrong**: `T_norm > t_norm_bull_thresh` AND `SMA_fast > SMA_slow`
* **BearStrong**: `T_norm < t_norm_bear_thresh` AND `SMA_fast < SMA_slow`
* **Sideways**: otherwise

---

### Volatility Classification (from z-score + hysteresis + Shock Brake)

1. Compute `z_score`
2. Apply hysteresis state machine → baseline `VolState`
3. If `enable_shock_brake == True` and `shock_timer > 0` → **force `VolState = High`**
4. Apply Vol-crush logic per baseline implementation (but do not override Shock Brake if active)

---

### 6 Regimes (Cells)

```
Cell 1: BullStrong + Low Vol
Cell 2: BullStrong + High Vol
Cell 3: Sideways   + Low Vol
Cell 4: Sideways   + High Vol
Cell 5: BearStrong + Low Vol
Cell 6: BearStrong + High Vol
```

---

## 6-Cell Allocation Matrix

### Base Allocations (Before Treasury Overlay)

| Cell | Trend      | Vol  | Name               | TQQQ | QQQ | Cash | Notes                 |
| ---: | ---------- | ---- | ------------------ | ---: | --: | ---: | --------------------- |
|    1 | BullStrong | Low  | Risk-On            |  60% | 40% |   0% | Primary growth engine |
|    2 | BullStrong | High | Risk-On (tempered) |  20% | 80% |   0% | Reduced leverage      |
|    3 | Sideways   | Low  | Neutral            |  20% | 80% |   0% | Mild participation    |
|    4 | Sideways   | High | Defensive          |   0% |  0% | 100% | Risk-off              |
|    5 | BearStrong | Low  | Defensive Tilt     |   0% | 50% |  50% | Partial participation |
|    6 | BearStrong | High | Full Defensive     |   0% |  0% | 100% | Capital preservation  |

> **Shock Brake Effect:** When active, it **moves the strategy into High-Vol cells (2/4/6)** for a cooldown period, reducing leverage and increasing defensiveness in precisely the conditions that historically produced tail losses.

---

## Trading Logic

### Execution Timing

* **At each market close (EOD):**

  1. Compute indicators (Kalman, SMA, volatility z-score)
  2. Update volatility state (hysteresis)
  3. Apply **Shock Brake** (if enabled)
  4. Determine regime cell
  5. Compute target allocation (apply Treasury overlay if in defensive cells)
  6. Rebalance if drift exceeds threshold
  7. Orders are filled at **EOD close** (per your execution model)

### Rebalancing Threshold

```yaml
rebalance_threshold: 0.025   # 2.5% drift threshold
```

### Shock Brake Integration (Operational)

**At EOD close t:**

* Detect shock using `abs(r_t) >= shock_threshold_pct`
* If shock → set shock_timer = shock_cooldown_days
* If shock_timer > 0 → force `VolState = High` in regime mapping
* Decrement timer each EOD

---

## Performance Characteristics

### Expected Impact of Shock Brake (Conceptual)

The Shock Brake is designed to improve outcomes primarily by reducing:

* **Largest negative daily returns** occurring under **BullStrong + Low Vol** classification
* **Downside deviation** (improving **Sortino**)
* **Tail drawdowns** (often improving **Calmar**)

### Trade-offs

* Can reduce exposure during abrupt rebounds immediately after a shock (mitigated by keeping cooldown short, e.g., 3–7 days)
* Increases time spent in High-Vol regimes during turbulent transitions (by design)

---

## Configuration Parameters

### Complete Golden Config (Baseline + Shock Brake)

```yaml
# ============================================
# HIERARCHICAL ADAPTIVE v3.5b - GOLDEN CONFIG
# (with Optional Shock Brake)
# ============================================

strategy: "Hierarchical_Adaptive_v3_5b"

# Symbols (Treasury Overlay enabled)
signal_symbol: "QQQ"
core_long_symbol: "QQQ"
leveraged_long_symbol: "TQQQ"
inverse_hedge_symbol: "PSQ"          # (disabled in golden)

# Kalman Trend
measurement_noise: 3000.0
process_noise_1: 0.01
process_noise_2: 0.01
osc_smoothness: 15
strength_smoothness: 15
T_max: 50.0

# SMA Structure
sma_fast: 40
sma_slow: 140

# Trend Thresholds
t_norm_bull_thresh: 0.05
t_norm_bear_thresh: -0.30

# Volatility Z-Score Parameters
realized_vol_window: 21
vol_baseline_window: 200
upper_thresh_z: 1.0
lower_thresh_z: 0.2

# --------------------------------------------
# NEW: Volatility Shock Brake (Optional)
# --------------------------------------------
enable_shock_brake: True
shock_threshold_pct: 0.03
shock_cooldown_days: 5

# Vol-Crush Override
vol_crush_threshold: -0.15
vol_crush_lookback: 5

# Treasury Overlay
allow_treasury: True
bond_sma_fast: 20
bond_sma_slow: 60
max_bond_weight: 0.4

# Rebalancing
rebalance_threshold: 0.025
```

---

## Usage Notes

* If you want the Shock Brake to be **less intrusive**, keep `shock_threshold_pct` higher (e.g., 0.035–0.05) or shorten `shock_cooldown_days` (e.g., 3).
* If your goal is **maximum Sortino improvement**, reduce `shock_threshold_pct` slightly (e.g., 0.025–0.03) while monitoring CAGR impact.

---

**End of Document**
