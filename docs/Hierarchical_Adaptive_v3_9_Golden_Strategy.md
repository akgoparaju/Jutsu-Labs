# Hierarchical Adaptive v3.9 Golden Strategy

**Version:** 3.9 ("The Aggressive Bull")
**Date:** December 2, 2025
**Status:** **Production Ready**
**Architecture:** Hierarchical Trend (Kalman/SMA) + Binarized Volatility (Hysteresis) - Same as 3.5b strategy with parameter set different

---

## 1. Strategy Overview

Hierarchical Adaptive v3.9 is a regime-based asset allocation strategy designed to maximize leveraged equity exposure (TQQQ) during stable bull markets while aggressively preserving capital during volatility clusters and structural downtrends.

**Core Philosophy:**
1.  **"Don't be Shy":** If the market structure is Bullish and Volatility is Low, we must be aggressively leveraged (Cell 1). We lowered the barrier to entry for this regime in v3.9 to capture the "meat" of the trend.
2.  **"Don't be a Hero":** In sideways chop (Cell 4), we hold 100% Cash. No hedging, no guessing.
3.  **"Don't Panic":** In volatile uptrends (Cell 2), we hold the underlying index (QQQ) to capture V-shaped recoveries without the decay risk of leverage.

### v3.9 Change Log & Reasoning
* **Trend Sensitivity (`t_norm_bull_thresh` 0.2 → 0.05):**
    * *Reasoning:* Backtests revealed v3.5b spent 68% of the Bull Market in "Cell 3" (20% Leverage). Lowering this threshold promoted ~370 trading days to "Cell 1" (60% Leverage), significantly boosting CAGR without increasing Max Drawdown.
* **Volatility Baseline (`vol_baseline_window` 126 → 160):**
    * *Reasoning:* A longer baseline smooths out the Z-score calculation, preventing "flicker" between Low and High volatility states. This rendered the need for a wide lower buffer (`0.2`) unnecessary.
* **Hysteresis Floor (`lower_thresh_z` 0.2 → 0.0):**
    * *Reasoning:* With the smoothed 160-day baseline, a 0.0 threshold offers slightly better capital preservation (lower drawdown) than 0.2 with negligible impact on returns.
* **Cell 4 Allocation (Treasury Overlay → 100% Cash):**
    * *Reasoning:* The "Chop" regime is statistically the worst for both Equities and Bonds. Cash is the only winning move.

---

## 2. Configuration Parameters (Golden Set)

### Structural Trend
| Parameter | Value | Description |
| :--- | :--- | :--- |
| **`sma_fast`** | **40** | Fast Structural Trend (Days) |
| **`sma_slow`** | **140** | Slow Structural Trend (Days) |
| **`t_norm_bull_thresh`** | **0.05** | **CRITICAL:** Threshold to promote Sideways → BullStrong |
| **`t_norm_bear_thresh`** | **-0.3** | Threshold to demote Sideways → BearStrong |

### Volatility Regime (Z-Score)
| Parameter | Value | Description |
| :--- | :--- | :--- |
| **`realized_vol_window`** | **21** | Lookback for current volatility (Days) |
| **`vol_baseline_window`** | **160** | **UPDATED:** Lookback for baseline stats (Smoother) |
| **`upper_thresh_z`** | **1.0** | Trigger for High Volatility |
| **`lower_thresh_z`** | **0.0** | **UPDATED:** Trigger for return to Low Volatility |
| **`vol_crush_threshold`** | **-0.15** | Override: V-shape recovery trigger (-15% vol drop) |

### Allocation Control
| Parameter | Value | Description |
| :--- | :--- | :--- |
| **`leverage_scalar`** | **1.0** | Multiplier for base weights |
| **`rebalance_threshold`** | **0.025** | 2.5% deviation triggers rebalance |
| **`allow_treasury`** | **True** | Enabled for Cell 5 & 6 (Disabled for Cell 4) |

---

## 3. The 6-Cell Allocation Matrix

The strategy maps the market into one of 6 regimes based on **Trend** (Rows) and **Volatility** (Columns).

| Cell | Trend State | Vol State | Regime Name | Allocation (v3.9) | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **BullStrong** | **Low** | **Kill Zone** | **60% TQQQ / 40% QQQ** | **Aggressive Upside.** Maximum leverage in safe waters. |
| **2** | **BullStrong** | **High** | **Volatile Bull** | **100% QQQ** | **Capture Recovery.** Avoid leverage decay, but stay fully invested. |
| **3** | **Sideways** | **Low** | **Drift** | **20% TQQQ / 80% QQQ** | **Conservative Growth.** Modest leverage for unclear trends. |
| **4** | **Sideways** | **High** | **Chop** | **100% Cash** | **Preservation.** The "Exit Tax." Volatility without trend = Loss. |
| **5** | **BearStrong** | **Low** | **Grind** | **50% QQQ / 50% Defensive** | **Defensive Hold.** Partial exposure + Bonds/Cash. |
| **6** | **BearStrong** | **High** | **Crash** | **100% Defensive** | **Survival.** Cash or Inverse Hedge (if enabled). |

### Treasury Overlay Rules (Defensive Buckets)
*Applies ONLY to Cells 5 and 6. Cell 4 is forced 100% Cash.*

* **Bond Bull (TLT SMA 20 > 60):** Use **TMF** (3x Bull Bonds) for defensive portion.
* **Bond Bear (TLT SMA 20 < 60):** Use **TMV** (3x Bear Bonds) for defensive portion.
* **Max Bond Weight:** 40% of Total Portfolio.

---

## 4. Execution Logic (Pseudo-Code)

```python
# 1. Calculate Indicators
T_norm = KalmanFilter(Price)
SMA_Fast = SMA(40)
SMA_Slow = SMA(140)
Z_Score = (Vol_21 - Mean_Vol_160) / Std_Vol_160

# 2. Determine States
# Trend Classification (Aggressive Promotion)
if SMA_Fast > SMA_Slow and T_norm > 0.05:
    Trend = "BullStrong"
elif SMA_Fast < SMA_Slow and T_norm < -0.3:
    Trend = "BearStrong"
else:
    Trend = "Sideways"

# Volatility Hysteresis
if Z_Score > 1.0:
    Vol = "High"
elif Z_Score < 0.0:
    Vol = "Low"
else:
    Vol = Previous_Vol_State # Deadband

# 3. Assign Cell & Allocation
if Trend == "BullStrong":
    if Vol == "Low": Allocation = {TQQQ: 0.6, QQQ: 0.4} # Cell 1
    else: Allocation = {QQQ: 1.0}                       # Cell 2 (100% QQQ)

elif Trend == "Sideways":
    if Vol == "Low": Allocation = {TQQQ: 0.2, QQQ: 0.8} # Cell 3
    else: Allocation = {Cash: 1.0}                      # Cell 4 (Strict Cash)

elif Trend == "BearStrong":
    if Vol == "Low": Allocation = {QQQ: 0.5, Defensive: 0.5} # Cell 5
    else: Allocation = {Defensive: 1.0}                      # Cell 6