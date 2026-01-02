# **Hierarchical Adaptive v5.0 \- Commodity-Augmented Regime Strategy**

Strategy Version: v5.0 (Tri-Asset Regime Allocator with Precious Metals Overlay)  
Status: Research/Draft Phase  
Base Logic: v3.5b Hierarchical Adaptive Framework

## **1\. Strategy Overview**

Hierarchical Adaptive v5.0 is an evolution of the v3.5b model. It maintains the core **Trend × Volatility** hierarchy but introduces a third macro filter: **Commodity Momentum**. This allows the strategy to pivot into Gold (GLD) and Silver (SLV) during regimes where traditional Treasury hedges (TMF/TMV) are ineffective due to rising real yields or currency debasement.

### **Key Enhancements in v5.0**

* **Tri-Asset Matrix**: Expands the 6-cell grid to 9 cells to accommodate "Commodity-Preferred" states.  
* **Precious Metals Overlay**: Integrates GLD and SLV as non-correlated defensive assets.  
* **Real-Yield Filter**: A new macro-indicator to decide between Bonds (TMF) or Gold (GLD) as the primary hedge.  
* **Silver Momentum Kicker**: Uses SLV as a high-beta performance booster during commodity bull cycles.

## **2\. New Indicator Systems**

In addition to the **Kalman Filter** and **VIX-based Volatility** from v3.5b, v5.0 introduces:

### **A. Gold Momentum (G-Trend)**

* **Logic**: Uses a 100-day/200-day SMA crossover on GLD.  
* **Purpose**: Determines if the "Safe Haven" preference is shifting from paper (Treasuries) to hard assets (Gold).

### **B. Silver Relative Strength (S-Beta)**

* **Logic**: Ratio of SLV:GLD 20-day ROC (Rate of Change).  
* **Purpose**: If Gold is trending, Silver is used to increase defensive "alpha" if SLV is outperforming GLD.

### **C. The "Hedge Preference" Signal**

* **Signal**: Compare 60-day correlation of QQQ and TLT.  
* **Paper Hedge (TMF)**: Triggered if Correlation is negative (Bonds move opposite to Stocks).  
* **Hard Hedge (GLD)**: Triggered if Correlation is positive (Stocks and Bonds moving together/down).

## **3\. The 9-Cell Allocation Matrix**

The matrix now incorporates a **Hard Asset Preference (HAP)** state based on the Hedge Preference Signal.

| Trend State | Vol State | Hedge Pref | Primary Ticker | Defensive/Overlay | Logic |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **Bull** | Low | N/A | **TQQQ (80%)** | QQQ (20%) | Standard Bull Run |
| **Bull** | High | N/A | **TQQQ (50%)** | GLD (20%) / Cash | Cautious Bull with Gold anchor |
| **Neutral** | Low | N/A | **QQQ (60%)** | GLD (40%) | The "Permanent Portfolio" mix |
| **Neutral** | High | Paper | **PSQ (20%)** | TMF (80%) | Standard Volatility Protection |
| **Neutral** | High | Hard | **PSQ (20%)** | GLD (60%) / SLV (20%) | **NEW: Inflationary Neutral** |
| **Bear** | Low | N/A | **PSQ (50%)** | TMV (50%) | Orderly decline; Shorting via PSQ |
| **Bear** | High | Paper | **Cash (100%)** | \- | Maximum Safety / Crash Avoidance |
| **Bear** | High | Hard | **GLD (70%)** | SLV (30%) | **NEW: The Black Swan / Stagflation** |
| **Recovery** | Vol-Crush | N/A | **TQQQ (100%)** | \- | Rapid V-Recovery Capture |

## **4\. Configuration Parameters (v5.0)**

| Parameter | Default Value | Description |
| :---- | :---- | :---- |
| commodity\_ma\_period | 150 | SMA period for GLD trend detection. |
| gold\_weight\_max | 0.60 | Maximum allocation to GLD in any "Hard Hedge" cell. |
| silver\_vol\_multiplier | 0.5 | Scales SLV weight relative to GLD (due to higher volatility). |
| hedge\_corr\_threshold | \+0.2 | Correlation level between QQQ/TLT that triggers the pivot to Gold. |
| leverage\_scalar | 1.0 | Global multiplier for TQQQ/TMF/TMV exposure. |
| silver\_momentum\_gate | True | Only allows SLV if its 20-day return \> GLD 20-day return. |

## **5\. Trading Logic Flow (v5.0)**

graph TD  
    A\[Start Daily Loop\] \--\> B{Check Kalman Trend}  
    B \-- Bull/Neutral \--\> C{Check VIX/Volatility}  
    B \-- Bear \--\> D{Check QQQ-TLT Correlation}  
      
    D \-- Correlation \< 0.2 \--\> E\[Defensive: TMF/TMV Focus\]  
    D \-- Correlation \> 0.2 \--\> F\[Defensive: GLD/SLV Focus\]  
      
    F \--\> G{Check SLV Relative Strength}  
    G \-- SLV \> GLD \--\> H\[Allocate GLD \+ SLV Kicker\]  
    G \-- SLV \< GLD \--\> I\[Allocate 100% GLD for Hedge\]  
      
    C \-- High Vol \--\> J\[Apply Hysteresis Filter\]  
    J \-- Stable \--\> K\[Execute Cell-Specific Rebalance\]

## **6\. Expected Performance Characteristics**

* **Drawdown Protection**: Version 5.0 is specifically designed to perform better in "2022-style" markets where TMF failed as a hedge. Expected Max DD reduction: **\~15-20% improvement over v3.5b**.  
* **Yield Profile**: By adding SLV during commodity bull runs, the strategy aims to capture "inflation alpha" that Treasuries cannot provide.  
* **Turnover**: Turnover will increase slightly due to the Gold/Silver rotation, but will be mitigated by the commodity\_ma\_period hysteresis.

## **7\. Next Steps for Backtesting**

1. **Correlation Stress Test**: Test the 2022 period specifically to see if the hedge\_corr\_threshold correctly pivots to GLD.  
2. **Silver Beta Tuning**: Evaluate if AGQ (2x Silver) is too volatile for the "Hard Hedge" cell or if SLV (1x) is sufficient.  
3. **Gold-TQQQ Ratio**: Experiment with using the GLD/TQQQ ratio as a "Macro-Regime" exit signal for all equity positions.

**End of v5.0 Specification**