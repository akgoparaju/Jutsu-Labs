# **Hierarchical Adaptive v5.1 \- Golden Strategy Documentation**

Strategy Version: v5.1 (Commodity-Augmented Regime Allocator)  
Configuration: Golden Config v5.1 (DXY-Filtered)  
Date: December 2, 2025

## **Table of Contents**

1. [Strategy Overview](https://www.google.com/search?q=%23strategy-overview)  
2. [Indicator Systems](https://www.google.com/search?q=%23indicator-systems)  
3. [The Macro-Safe-Haven Switch](https://www.google.com/search?q=%23the-macro-safe-haven-switch)  
4. [9-Cell Allocation Matrix](https://www.google.com/search?q=%239-cell-allocation-matrix)  
5. [Configuration Parameters](https://www.google.com/search?q=%23configuration-parameters)  
6. [Trading Logic](https://www.google.com/search?q=%23trading-logic)

## **Strategy Overview**

Hierarchical Adaptive v5.1 is an evolution of v3.5b. It retains the **Trend × Volatility** hierarchy but adds a third decision layer: **Macro-Sentiment Context**. While v3.5b relied exclusively on Treasuries (TMF/TMV) for defense, v5.1 introduces **Gold (GLD)** and **Silver (SLV)** as defensive pivots when the Dollar (DXY) or Stock-Bond correlations indicate systemic risk.

### **Key Enhancements from v3.5b**

* **Hedge Preference Logic**: Detects if the standard stock-bond inverse correlation is broken.  
* **Dollar Sentiment Filter**: Uses DXY momentum to prioritize Gold over Treasuries during currency debasement.  
* **Silver Momentum Kicker**: Adds high-beta silver exposure during confirmed commodity bull regimes.  
* **9-Cell Grid**: Expands the regime matrix to include "Hard Asset" defensive states.

## **Indicator Systems**

### **1\. Trend & Volatility (Inherited from v3.5b)**

* **Fast Signal**: Kalman Filter (State estimate vs. Price).  
* **Slow Signal**: 200-day Simple Moving Average (SMA).  
* **Volatility**: Binary High/Low classification via VIX \+ standard deviation thresholds.

### **2\. The Hedge Preference Signal (HPS) \- *NEW***

This signal determines the "Safe Haven of Choice."

* **Correlation Filter**: 60-day rolling correlation of QQQ and TLT.  
* **Dollar Filter**: 50-day SMA trend of the **DXY Index**.  
* **Regime Classification**:  
  * **PAPER HEDGE**: Triggered if $Corr(QQQ, TLT) \< 0.2$ AND $DXY \> SMA\_{50}$. (Market favors Bonds/Cash).  
  * **HARD HEDGE**: Triggered if $Corr(QQQ, TLT) \> 0.2$ OR $DXY \< SMA\_{50}$. (Market favors Gold/Silver).

## **9-Cell Allocation Matrix**

The matrix expands the previous 6-cell model by splitting the "High Volatility" defensive cells into **Paper** and **Hard** asset preferences.

| Cell ID | Trend State | Vol State | Hedge Pref | Allocation | Logic |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **C1** | Bull | Low | N/A | **TQQQ (100%)** | Full Momentum; Risk-On. |
| **C2** | Bull | High | N/A | **TQQQ (50%) / GLD (25%) / Cash (25%)** | Cautious Growth; Gold anchor. |
| **C3** | Neutral | Low | N/A | **QQQ (60%) / GLD (40%)** | Equilibrium/Permanent Portfolio. |
| **C4** | Neutral | High | **Paper** | **PSQ (20%) / TMF (80%)** | Deflationary Volatility Hedge. |
| **C5** | Neutral | High | **Hard** | **PSQ (20%) / GLD (60%) / SLV (20%)** | **Stagflationary Volatility Hedge.** |
| **C6** | Bear | Low | N/A | **PSQ (50%) / TMV (50%)** | Orderly Decline; Rate-Sensitive Shorting. |
| **C7** | Bear | High | **Paper** | **Cash (100%)** | Maximum Safety / Liquidity Crisis. |
| **C8** | Bear | High | **Hard** | **GLD (70%) / SLV (30%)** | **Black Swan / Geopolitical Shelter.** |
| **C9** | Recovery | Vol-Crush | N/A | **TQQQ (100%)** | V-Recovery Capture (Override). |

## **Configuration Parameters (v5.1)**

| Parameter | Value | Description |
| :---- | :---- | :---- |
| kalman\_q | 1e-4 | Kalman process noise (from Golden Config 3.5b). |
| kalman\_r | 1e-2 | Kalman measurement noise. |
| hedge\_corr\_threshold | \+0.20 | Threshold where Bonds stop acting as a hedge. |
| dxy\_sma\_period | 50 | Lookback for U.S. Dollar Index trend. |
| gold\_silver\_ratio | 0.7/0.3 | Ratio within the "Hard Hedge" basket. |
| vol\_hysteresis | 0.05 | Prevents rapid flipping between High/Low vol states. |

## **Trading Logic**

### **Logic Flow for v5.1 Execution**

1. **Daily Input**: Fetch QQQ, TLT, DXY, GLD, SLV, and VIX.  
2. **Trend Check**: Run Kalman Filter on QQQ. If $Price \> State$, Trend \= Bull.  
3. **Vol Check**: If $VIX \> 22$ or $1-Day Change \> Threshold$, Vol \= High.  
4. **Safe-Haven Filter**:  
   * Calculate 60-day correlation of QQQ/TLT.  
   * Check if DXY is above its 50-day SMA.  
   * If Correlation \> 0.2 OR DXY Trend is Negative → **Hedge Preference \= HARD**.  
   * Otherwise → **Hedge Preference \= PAPER**.  
5. **Matrix Mapping**: Select Cell (C1-C9) based on the 3 inputs.  
6. **Vol-Crush Override**: If VIX drops \> 15% in 48 hours, force C9 (TQQQ) regardless of other signals.  
7. **Rebalance**: Execute trades if current weight deviates \> 3% from target.

## **Expected Characteristics (v5.1 vs v3.5b)**

* **Drawdown Resilience**: By adding C5 and C8, the strategy avoids the "2022 Trap" where Bonds (TMF) and Stocks (TQQQ) crashed together.  
* **Crisis Alpha**: Gold and Silver provide non-correlated returns during periods of USD weakness or geopolitical tension that PSQ/TMV alone cannot capture.  
* **Turnover**: Turnover remains moderate, as the DXY and Correlation filters use long lookbacks (50-60 days) to prevent "whipsawing."

**End of v5.1 Specification**