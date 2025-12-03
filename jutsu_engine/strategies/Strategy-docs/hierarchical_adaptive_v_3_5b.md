# **Hierarchical Adaptive v3.5: Binarized Regime Allocator for QQQ / TQQQ / PSQ**

## **1\. Strategy Overview**

**Hierarchical Adaptive v3.5** is a binarized regime-switching allocator over **QQQ, TQQQ, PSQ, and Cash**.

Relative to v3.0, v3.5:

* Simplifies the regime grid from **3×3 (Low/Med/High)** to **3×2 (Low/High)**.  
* Replaces static look-back percentiles with a **Rolling Z-Score** for volatility normalization.  
* Introduces **State Hysteresis (Latching)** to prevent regime flickering.  
* Replaces the "Continuous Exposure" logic of v2.x with discrete **Target Allocations** per regime cell.

High-level behaviour:

* **Kill Zone (Bull \+ Low Vol):** Aggressive leverage (approx 2.0×) via TQQQ.  
* **Fragile Trend (Bull \+ High Vol):** De-risked exposure (1.0×) to avoid volatility drag.  
* **Crash Protection (Bear \+ High Vol):** Cash or mild inverse hedge (PSQ) to limit drawdowns.

The long-run target is to maximize Geometric CAGR by effectively removing leverage during high-volatility chop, where beta decay destroys value.

## **2\. Design Goals**

### **2.1 Return Objective**

* **Primary objective:** Maximize Geometric Mean Return (CAGR) by minimizing "Volatility Drag" ($\\frac{1}{2}\\sigma^2$).  
* **Alpha Source:** Asymmetric leverage—betting big only when the "Signal-to-Noise" ratio (Trend/Vol) is favorable.

### **2.2 Risk & Drawdown Constraints**

* **Hard Constraint:** Max Drawdown $\\le$ QQQ.  
* **Soft Constraint:** Eliminate "False Bear" shorting losses (shorting the hole) by restricting inverse exposure to high-conviction crash regimes.

### **2.3 Behavioural Profile**

* **Decisive:** The strategy is either "Risk-On" (Leveraged) or "Risk-Off" (De-risked). It minimizes time spent in "lukewarm" middle states.  
* **Adaptive:** The Z-Score volatility baseline adjusts to the market era (e.g., 2017 low-vol vs. 2022 high-vol).

## **3\. Conceptual Changes from v3.0**

v3.5 addresses the primary statistical weakness of v3.0: the instability of the "Medium Volatility" bucket.

1. **Binarized Volatility (3×2 Grid)**  
   * **Insight:** TQQQ decay is non-linear. There is no "safe medium" zone. Either vol is low enough to outrun drag, or it isn't.  
   * **Change:** Eliminated "Medium Vol". Merged into a binary Low/High state with a hysteresis gap.  
2. **Rolling Z-Score Normalization**  
   * **Insight:** Static thresholds (e.g., "VIX \> 20") suffer from look-ahead bias.  
   * **Change:** Volatility is now defined relative to the trailing 6-month baseline. A Z-Score $\> \+1.0$ indicates "High Vol" relative to *current* conditions.  
3. **Vol-Crush Override**  
   * **Insight:** Moving averages lag during V-shaped recoveries.  
   * **Change:** A mechanism to force the system into "Low Vol" mode instantly if realized volatility collapses, capturing early recovery alpha.

## **4\. Architecture & Filter Hierarchy**

### **4.1 Tier 1 – Kalman Trend Engine (Hierarchical)**

The trend logic remains hierarchical: a **Fast Signal** gated by a **Slow Structural Filter**.

**Fast Signal (Kalman):**

* Compute T\_norm (Normalized Trend Score, clipped \[-1, \+1\]) using the standard v2.8 Kalman velocity model.

**Slow Signal (Structure):**

* SMA\_Fast \= 50-day Simple Moving Average.  
* SMA\_Slow \= 200-day Simple Moving Average.

**Trend Classification:**

1. **BullStrong:** T\_norm \> 0.3 AND SMA\_Fast \> SMA\_Slow.  
2. **BearStrong:** T\_norm \< \-0.3 AND SMA\_Fast \< SMA\_Slow.  
3. **Sideways:** All other conditions (e.g., Fast Bear but Structural Bull \= Correction/Sideways).

### **4.2 Tier 2 – Volatility Regime with Hysteresis**

We classify the market into **State 0 (Low Vol)** or **State 1 (High Vol)**.

**Inputs:**

* sigma\_t: Annualized realized volatility (21-day).  
* mu\_vol, sigma\_vol: Mean and StdDev of sigma\_t over rolling 126-day window.

**Z-Score Calculation:**

$$Z\_{vol} \= \\frac{\\sigma\_t \- \\mu\_{vol}}{\\sigma\_{vol}}$$  
**State Machine (Hysteresis Latch):**

* **Enter High Vol:** IF $Z\_{vol} \> 1.0$ (Upper Threshold).  
* **Enter Low Vol:** IF $Z\_{vol} \< 0.0$ (Lower Threshold).  
* **Else:** Maintain Previous\_Vol\_State.

**Vol-Crush Trigger:**

* IF $\\frac{\\sigma\_t \- \\sigma\_{t-5}}{\\sigma\_{t-5}} \< \-0.20$ (20% drop in 5 days):  
* Force **State 0 (Low Vol)** immediately.

### **4.3 Tier 3 – Regime Allocation Matrix**

The intersection of Trend (3 rows) and Volatility (2 columns) determines the target allocation cell.

| Trend \\ Vol | Low Volatility (0) | High Volatility (1) |
| :---- | :---- | :---- |
| **Bull** | **Cell 1: Kill Zone** | **Cell 2: Fragile** |
| **Side** | **Cell 3: Drift** | **Cell 4: Chop** |
| **Bear** | **Cell 5: Grind** | **Cell 6: Crash** |

## **5\. Exposure Calculation Summary**

Per bar t:

1. Compute **Trend Regime** (Bull / Side / Bear) via Kalman \+ SMA logic.  
2. Compute **Vol Z-Score** and update **Vol State** (0 or 1\) using hysteresis thresholds.  
3. Check **Vol-Crush** condition; override Vol State to 0 if triggered.  
4. Identify **Target Cell** (1–6) from the Matrix.  
5. Retrieve **Target Weights** ($w\_{TQQQ}, w\_{QQQ}, w\_{PSQ}, w\_{Cash}$) for that cell.  
6. Check rebalance thresholds.

## **6\. Position Mapping (The Matrix Rules)**

We map each cell to a specific instrument mix.

**Global Parameters:**

* leverage\_scalar (Default 1.0): Multiplier for TQQQ weight.  
* allow\_psq (Default True): Enable inverse hedging in Cell 6\.

### **6.1 Cell Definitions**

**Cell 1: Kill Zone (Bull \+ Low Vol)**

* *Logic:* Maximum Aggression.  
* $w\_{TQQQ} \= 0.6 \\times \\text{scalar}$  
* $w\_{QQQ} \= 1.0 \- w\_{TQQQ}$

**Cell 2: Fragile (Bull \+ High Vol)**

* *Logic:* De-risk. Trend is up, but volatility threatens leverage.  
* $w\_{QQQ} \= 1.0$

**Cell 3: Drift (Sideways \+ Low Vol)**

* *Logic:* Capture drift with mild leverage.  
* $w\_{TQQQ} \= 0.2 \\times \\text{scalar}$  
* $w\_{QQQ} \= 1.0 \- w\_{TQQQ}$

**Cell 4: Chop (Sideways \+ High Vol)**

* *Logic:* The "Widowmaker". Maximum defense.  
* $w\_{Cash} \= 1.0$

**Cell 5: Grind (Bear \+ Low Vol)**

* *Logic:* "Buying the dip" in a slow correction.  
* $w\_{QQQ} \= 0.5$  
* $w\_{Cash} \= 0.5$

**Cell 6: Crash (Bear \+ High Vol)**

* *Logic:* Panic defense.  
* IF allow\_psq: $w\_{PSQ} \= 0.5$, $w\_{Cash} \= 0.5$  
* ELSE: $w\_{Cash} \= 1.0$

## **7\. Risk Management & Constraints**

### **7.1 Rebalancing Logic**

* **Threshold:** Only rebalance if $|w\_{current} \- w\_{target}| \> 5\\%$.  
* **Reasoning:** Prevents churn in "Drift" or "Grind" regimes where weights are close to static.

### **7.2 Leverage Limits**

* **Max Net Beta:** Implicitly capped by Cell 1 (\~2.2x).  
* **Max Inverse:** Capped at \-0.5x (50% PSQ) to prevent ruin from "Bear Traps".

## **8\. Parameter Summary (Initial Defaults)**

### **8.1 Kalman & Trend**

* measurement\_noise: 2000–3000  
* t\_thresh\_bull: \+0.3  
* t\_thresh\_bear: \-0.3  
* sma\_fast: 50  
* sma\_slow: 200

### **8.2 Volatility Hysteresis**

* z\_window: 126 days (6 months)  
* z\_upper: \+1.0 (Enter Defense)  
* z\_lower: 0.0 (Enter Aggression)  
* crush\_trigger: \-0.20 (20% drop in 5 days)

### **8.3 Allocation**

* leverage\_scalar: 1.0  
* w\_kill\_zone\_tqqq: 0.6  
* allow\_psq: True

## **9\. Pseudo-Code Walkthrough**

Per daily bar t:

1. **Calculate Indicators:**  
   * Update Kalman osc and strength \-\> T\_norm.  
   * Update SMA\_50, SMA\_200.  
   * Calculate sigma\_t (21d vol).  
   * Update rolling stats (mu\_vol, sigma\_vol) over 126d.  
2. **Update Vol State:**  
   * z\_score \= (sigma\_t \- mu\_vol) / sigma\_vol  
   * IF z\_score \> 1.0: vol\_state \= 1  
   * ELIF z\_score \< 0.0: vol\_state \= 0  
   * ELSE: vol\_state remains unchanged.  
   * **Override:** IF (sigma\_t / sigma\_t-5) \- 1 \< \-0.20: vol\_state \= 0\.  
3. **Update Trend Regime:**  
   * struct\_bull \= SMA\_50 \> SMA\_200  
   * IF T\_norm \> 0.3 AND struct\_bull: row \= Bull  
   * ELIF T\_norm \< \-0.3 AND NOT struct\_bull: row \= Bear  
   * ELSE: row \= Sideways  
4. **Determine Target Weights:**  
   * Lookup (row, vol\_state) in Matrix (Section 6).  
   * Set target\_weights.  
5. **Execution:**  
   * Check diff between current\_weights and target\_weights.  
   * If diff \> 5%, execute trades.

## **10\. Backtest & Evaluation Plan**

1. **Sensitivity Analysis:**  
   * Test z\_upper range \[0.8, 1.2\].  
   * Test sma\_slow range \[180, 220\].  
2. **Stress Test:**  
   * Verify behavior in **Feb 2018** (Vol Spike).  
   * Verify behavior in **Dec 2018** (V-Shape Recovery).  
   * Verify behavior in **Mar 2020** (Crash).