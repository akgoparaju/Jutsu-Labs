# **Hierarchical Adaptive v4.0 \- Robust Regime Strategy Documentation**

Strategy Version: v4.0 (Correlation-Aware Regime Allocator with Crisis Alpha)  
Configuration: Proposed Grid-Search Baseline  
Date: November 29, 2025

## **Table of Contents**

1. [Strategy Overview](https://www.google.com/search?q=%23strategy-overview)  
2. [Core Concepts](https://www.google.com/search?q=%23core-concepts)  
3. [Indicator Systems](https://www.google.com/search?q=%23indicator-systems)  
4. [Regime Classification](https://www.google.com/search?q=%23regime-classification)  
5. [6-Cell Allocation Matrix (Robust)](https://www.google.com/search?q=%236-cell-allocation-matrix-robust)  
6. [Trading Logic](https://www.google.com/search?q=%23trading-logic)  
7. [Performance Characteristics](https://www.google.com/search?q=%23performance-characteristics)  
8. [Configuration Parameters](https://www.google.com/search?q=%23configuration-parameters)  
9. [Appendices](https://www.google.com/search?q=%23appendices)

## **Strategy Overview**

Hierarchical Adaptive v4.0 is a **robustness-focused evolution** of the v3.5b system. It directly addresses the structural failures identified in the **2015 choppy sideways market** and the **2022 inflationary bear market** by introducing macro-filtering and correlation awareness.

### **Key Features**

* **Macro Trend Filter**: Distinguishes between "Accumulation" (Bullish Sideways) and "Distribution" (Bearish Sideways) using a long-term baseline (SMA200)  
* **Correlation Guard**: Dynamically disables Bond hedges (TMF) when Stock/Bond correlation flips positive (inflation regime), defaulting to Cash/USD  
* **Crisis Alpha**: Activates short exposure (SQQQ) only in specific high-volatility crash regimes (Cell 6\)  
* **Vol-Crush Override**: (Retained from v3.5b) Detects V-shaped recoveries to force early re-entry  
* **Whipsaw Protection**: Removes leverage in high-volatility uptrends (Cell 2\) to prevent "Bull Trap" losses  
* **Smart Rebalancing**: Variable drift thresholds to reduce transaction costs in high-noise environments

### **Strategy Philosophy**

The strategy operates on three upgraded principles:

1. **Correlation Awareness**: Bonds are not always a hedge. In inflationary regimes (Correlation \> 0.2), Cash is the only safe haven.  
2. **Distribution Avoidance**: Sideways price action below the long-term trend (SMA200) is treated as a "bull trap" rather than a buying opportunity.  
3. **Asymmetric Leverage**: Leverage is maximized only in high-certainty regimes (Cell 1\) and eliminated in high-noise regimes (Cell 2).

## **Core Concepts**

### **Market Regime Framework**

The strategy retains the **6 discrete regimes** but fundamentally alters the asset selection logic within them:

**Dimension 1: Trend State** (3 states)

* **BullStrong**: Validated uptrend (Kalman \+ SMA structure)  
* **Sideways**: Ambiguous trend. **New in v4.0**: Split into "Safe Drift" vs "Danger Drift" based on Macro Trend  
* **BearStrong**: Validated downtrend

**Dimension 2: Volatility State** (2 states)

* **Low Volatility**: Safe for leverage  
* **High Volatility**: Dangerous for leverage (even in uptrends)

### **The Macro Trend Filter**

Problem: v3.5b treated all "Sideways" markets as opportunities to harvest premium. In 2022, "Sideways" often meant "slow bleed."  
Solution: We overlay a global Macro Bias:

* **Bull Bias**: Price \> SMA(200). Sideways markets are "dip buying" opportunities.  
* **Bear Bias**: Price \< SMA(200). Sideways markets are "distribution" zones.

### **The Correlation Guard**

Problem: In 2022, TMF (Long Bonds) crashed simultaneously with Stocks (Correlation \> 0).  
Solution: Before allocating to any Bond ETF (TMF or TMV), we check the rolling correlation between SPY and TLT.

* **Corr \< 0.2**: Bonds are a valid hedge. Use TMF/TMV based on Bond Trend.  
* **Corr \> 0.2**: Bonds are correlated risk. Force allocation to **Cash**.

## **Indicator Systems**

### **1\. Macro Trend Filter (New)**

**Purpose**: Define the global "Bias" of the market to contextualize Sideways regimes.

**Parameters** (Grid Search Baseline):

macro\_trend\_lookback: 200 days   \# The "Line in the Sand"

**Calculation**:

1. Compare current Close to SMA(200)  
2. Bias \= Bull if Close \> SMA(200)  
3. Bias \= Bear if Close \< SMA(200)

**Impact**: Determines whether Cell 3 (Sideways/Low) allocates to Equity (TQQQ) or Cash.

### **2\. Correlation Guard (New)**

**Purpose**: Prevent "Double Down" losses when Stocks and Bonds fall together.

**Parameters** (Grid Search Baseline):

corr\_lookback: 60 days           \# Rolling window  
corr\_symbol\_1: "SPY"             \# Equity proxy  
corr\_symbol\_2: "TLT"             \# Bond proxy  
corr\_threshold: 0.20             \# Positive correlation trigger

**Calculation**:

1. Calculate daily returns of SPY and TLT  
2. Compute rolling correlation over corr\_lookback  
3. If Correlation \> corr\_threshold: **Inflation Regime** (Unsafe for Bonds)  
4. Else: **Normal Regime** (Safe for Bonds)

**Output**: SafeHavenAsset \= TMF/TMV (Normal) or CASH (Inflation)

### **3\. Kalman Trend Detector (Retained)**

Purpose: Detect short-term momentum.  
Same parameters as v3.5b.

* T\_norm \> 0.2 \= Bullish Momentum  
* T\_norm \< \-0.3 \= Bearish Momentum

### **4\. Volatility Z-Score System (Retained)**

Purpose: Normalize volatility regimes.  
Same parameters as v3.5b.

* z\_score \> 1.0 \= High Vol  
* z\_score \< 0.2 \= Low Vol (with Hysteresis)

### **5\. Vol-Crush Override (Retained)**

**Purpose**: Detect rapid volatility collapse (V-shaped recoveries) and override bearish signals. Essential for 2020-style crashes.

**Parameters**:

vol\_crush\_threshold: \-0.15       \# \-15% vol drop triggers override  
vol\_crush\_lookback: 5 days       \# Detection window

**Detection Logic**:

1. Calculate realized volatility at t and t-5.  
2. Compute change: Δvol \= (σ\_t \- σ\_{t-5}) / σ\_{t-5}.  
3. If Δvol \< \-0.15 → Vol-crush detected.

**Override Actions (v4.0 Adapted)**:

* **Force VolState**: "Low" (regardless of z-score).  
* **Force TrendState**: "Sideways" (if currently BearStrong).  
* **Force MacroBias**: "Bull" (Implied).  
  * *Rationale*: A vol crush signals a psychological shift. We must treat this as a "Safe Drift" (Cell 3 Bull Bias) to ensure we allocate to TQQQ/SafeHaven rather than getting stuck in Cash due to a lagging SMA200.

## **Regime Classification**

### **Trend & Volatility Logic**

*The classification logic remains identical to v3.5b to preserve the stability of the HMM/Kalman signals. The major changes are in how we **act** on these signals (see Allocation Matrix).*

**Cell ID Mapping**:

Cell 1: BullStrong \+ Low Vol   (The "Green Zone")  
Cell 2: BullStrong \+ High Vol  (The "Whipsaw Zone")  
Cell 3: Sideways \+ Low Vol     (The "Drift Zone")  
Cell 4: Sideways \+ High Vol    (The "Noise Zone")  
Cell 5: BearStrong \+ Low Vol   (The "Bleed Zone")  
Cell 6: BearStrong \+ High Vol  (The "Crash Zone")

## **6-Cell Allocation Matrix (Robust)**

This matrix replaces the v3.5b allocation. It is designed to maximize **Calmar Ratio**.

| Cell | Regime | Condition | Allocation Strategy (v4.0) | Rationale |
| :---- | :---- | :---- | :---- | :---- |
| **1** | Bull | Low | **Aggressive** | **100% TQQQ** (Leverage 1.3x) |
| **2** | Bull | High | **Anti-Whipsaw** | **100% QQQ** (Leverage 1.0x) |
| **3** | Side | Low | **Contextual** | **If Bull Bias**: 50% TQQQ / 50% Safe **If Bear Bias**: 100% Cash |
| **4** | Side | High | **Defensive** | **100% Cash** |
| **5** | Bear | Low | **Hedged** | **50% SafeHaven / 50% Cash** |
| **6** | Bear | High | **Crisis Alpha** | **40% SafeHaven / 40% Cash / 20% SQQQ** |

### **Dynamic "Safe Haven" Selection Logic**

In Cells 3, 5, and 6, where "**SafeHaven**" is listed, the specific instrument is determined by the **Correlation Guard** and **Bond Trend**:

**Logic Flow**:

1. **Check Correlation**: Is Corr(SPY, TLT) \> 0.2?  
   * **YES**: Safe Haven \= **Cash** (Ignore Bond Trend \- Inflation is high)  
   * **NO**: Safe Haven \= **Bond Overlay** (Correlation is low/negative)  
2. **Bond Overlay (Only if Correlation is Low)**:  
   * If Bond Trend \= Bull: Use **TMF** (Deflationary Hedge)  
   * If Bond Trend \= Bear: Use **TMV** (Inflationary Hedge)

## **Trading Logic**

### **Smart Rebalancing**

**Purpose**: Reduce "churn" in Cell 4 (High Vol Chop) compared to v3.5b.

**Rules**:

1. **Regime Change**: Immediate Rebalance (e.g., Cell 1 → Cell 2\)  
2. **Drift Rebalance**:  
   * If in **Low Vol** Cells (1, 3, 5): Rebalance at **3.0%** drift  
   * If in **High Vol** Cells (2, 4, 6): Rebalance at **6.0%** drift (Wider bands to avoid noise)

### **Leverage Scaling**

**Parameter**:

lev\_scalar\_c1: 1.3               \# Overdrive for Cell 1  
lev\_scalar\_base: 1.0             \# Standard for others

**Application**:

* **Cell 1**: Target 130% exposure (requires margin or deep ITM calls, or simplified to 100% TQQQ which is internally 300%).  
* **Cell 2**: Hard-capped at 1.0x (QQQ).

## **Performance Characteristics**

### **Improvements over v3.5b**

1. **2022 Drawdown**: Specifically targeted by the **Correlation Guard**. By forcing Cash instead of TMF when correlation was high, the strategy avoids the "double loss."  
2. **2015 Chop**: Targeted by **Cell 4 \= 100% Cash** and **Macro Bias**. The strategy sits in cash rather than trying to trade the noise.  
3. **Total Return**: Enhanced by **Crisis Alpha (SQQQ)** in Cell 6 and increased aggression in Cell 1\.

### **Expected Behavior**

* **Bull Markets**: Similar to v3.5b, but potentially higher return due to Cell 1 focus.  
* **Bear Markets**: Significantly lower drawdown.  
* **Trade Count**: Lower. The Macro Bias filter prevents flipping in and out of positions during long sideways grinds.

## **Configuration Parameters**

### **Grid Search Scope (v4.0)**

These are the parameters to optimize to finalize the "Golden" v4.0 config.

\# \============================================  
\# HIERARCHICAL ADAPTIVE v4.0 \- ROBUST REGIME  
\# \============================================

strategy: "Hierarchical\_Adaptive\_v4\_0"

\# Symbols  
signal\_symbol: "QQQ"  
core\_long\_symbol: "QQQ"  
leveraged\_long\_symbol: "TQQQ"  
crisis\_short\_symbol: "SQQQ"       \# NEW: For Cell 6  
treasury\_trend\_symbol: "TLT"  
bull\_bond\_symbol: "TMF"  
bear\_bond\_symbol: "TMV"  
corr\_symbol\_1: "SPY"  
corr\_symbol\_2: "TLT"

\# Macro Filters (NEW)  
macro\_trend\_lookback: \[180, 200, 220\]     \# Grid Search: SMA Line  
corr\_lookback: \[40, 60, 80\]               \# Grid Search: Correlation Window  
corr\_threshold: \[0.1, 0.2, 0.3\]           \# Grid Search: Inflation Trigger

\# Kalman Trend Parameters (Existing)  
measurement\_noise: 3000.0  
T\_max: 50.0

\# Vol Crush (Retained)  
vol\_crush\_threshold: \-0.15

\# Allocation Logic (Refined)  
lev\_scalar\_c1: 1.3                        \# Aggressive Bull  
crisis\_alpha\_weight: \[0.1, 0.2, 0.3\]      \# SQQQ weight in Cell 6

\# Rebalancing  
drift\_low\_vol: 0.03  
drift\_high\_vol: 0.06

\# Volatility Thresholds  
upper\_thresh\_z: 1.0  
lower\_thresh\_z: 0.2

## **Appendices**

### **Appendix A: The v4.0 Decision Tree**

START  
│  
├─ 1\. GLOBAL CHECKS  
│  ├─ Macro Trend: Price(QQQ) \> SMA(200)? → BULL BIAS or BEAR BIAS  
│  └─ Correlation: Corr(SPY, TLT) \> 0.2? → INFLATION (Bonds Unsafe) or NORMAL  
│  
├─ 2\. CHECK OVERRIDES (Vol Crush)  
│  ├─ IF Vol Drop \> 15% in 5 days:  
│  │  ├─ Force Vol \= LOW  
│  │  ├─ Force Trend \= SIDEWAYS  
│  │  └─ Force Bias \= BULL (Safe Drift)  
│  
├─ 3\. DETERMINE REGIME (Trend x Vol)  
│  ├─ Cell 1: Bull / Low Vol  
│  ├─ Cell 2: Bull / High Vol  
│  ├─ Cell 3: Sideways / Low Vol  
│  ├─ Cell 4: Sideways / High Vol  
│  ├─ Cell 5: Bear / Low Vol  
│  └─ Cell 6: Bear / High Vol  
│  
├─ 4\. ALLOCATE (Based on Cell \+ Global Checks)  
│  
│  ├─ CELL 1 (Bull/Low)  
│  │  └─ 100% TQQQ  
│  
│  ├─ CELL 2 (Bull/High)  
│  │  └─ 100% QQQ (No Leverage)  
│  
│  ├─ CELL 3 (Side/Low)  
│  │  ├─ IF BULL BIAS (or VolCrush): 50% TQQQ \+ 50% SafeHaven  
│  │  └─ IF BEAR BIAS: 100% Cash  
│  
│  ├─ CELL 4 (Side/High)  
│  │  └─ 100% Cash  
│  
│  ├─ CELL 5 (Bear/Low)  
│  │  └─ 50% SafeHaven \+ 50% Cash  
│  
│  └─ CELL 6 (Bear/High)  
│     └─ 40% SafeHaven \+ 40% Cash \+ 20% SQQQ  
│  
└─ 5\. RESOLVE SAFE HAVEN  
   ├─ IF INFLATION REGIME (Corr \> 0.2):  
   │  └─ SafeHaven \= CASH  
   └─ IF NORMAL REGIME:  
      ├─ Bond Bull: SafeHaven \= TMF  
      └─ Bond Bear: SafeHaven \= TMV  
