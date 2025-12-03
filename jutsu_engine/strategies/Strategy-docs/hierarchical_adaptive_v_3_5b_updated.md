# **Hierarchical Adaptive v3.5b: Binarized Regime \+ Treasury Overlay**

## **1\. Strategy Overview**

**Hierarchical Adaptive v3.5b** extends the v3.5 binarized framework by introducing a **Dynamic Safe Haven Selector**.

Relative to v3.5, v3.5b:

* Replaces the static "Cash" allocation in defensive regimes with a **Treasury Logic Module**.  
* Dynamically selects between **Cash**, **TMF (Bull Bonds)**, or **TMV (Bear Bonds)** based on the correlation regime.  
* Aims to convert the "dead capital" of defensive buckets into an active alpha source during rate-driven market moves (e.g., 2008 deflation or 2022 inflation).

High-level behaviour:

* **Equities:** Identical to v3.5 (Kill Zone, Fragile, Drift).  
* **Defense (Chop/Crash Regimes):** instead of holding 100% Cash, the strategy checks the Bond Trend.  
  * **Rates Falling (Flight to Safety):** Long TMF (+3x Treasuries).  
  * **Rates Rising (Inflation Shock):** Long TMV (-3x Treasuries) or Cash.

## **2\. Design Goals**

### **2.1 Return Objective**

* **Primary:** Same as v3.5 (Geometric CAGR via volatility management).  
* **Secondary:** Capture "Crisis Alpha" from the bond market. Most equity crashes coincide with major moves in Treasuries (either up or down).

### **2.2 Risk & Constraints**

* **Correlation Risk:** The primary risk is a sudden correlation flip (e.g., stocks and bonds falling together, then bonds rallying while stocks fall).  
* **Constraint:** Bond exposure is capped (default 40%) to prevent the "hedge" from becoming the primary risk driver.

## **3\. Architecture & Regime Logic**

### **3.1 Tiers 1-3 (Equity Engine)**

*Identical to v3.5.*

* **Tier 1:** Kalman \+ SMA Trend Classification.  
* **Tier 2:** Volatility Z-Score with Hysteresis.  
* **Tier 3:** 3×2 Allocation Matrix.

### **3.2 Tier 4 – Treasury Trend Filter (New)**

Operates only when the Equity Engine selects **Cell 4 (Chop)** or **Cell 6 (Crash)**.

**Inputs:**

* TLT (20+ Year Treasury ETF).  
* Bond\_SMA\_Fast (20-day).  
* Bond\_SMA\_Slow (60-day).

**Logic:**

1. **Bond Bull (Deflation/Safety):** SMA\_Fast \> SMA\_Slow.  
   * *Implication:* Crisis is likely deflationary (2008, 2020).  
   * *Instrument:* **TMF**.  
2. **Bond Bear (Inflation):** SMA\_Fast \< SMA\_Slow.  
   * *Implication:* Crisis is likely inflationary/rate-driven (2022).  
   * *Instrument:* **TMV**.

## **4\. Exposure Calculation Summary**

Per bar t:

1. **Run Equity Engine:** Determine Trend Regime and Vol State.  
2. **Determine Cell:** Identify if we are in Cell 4 (Chop) or 6 (Crash).  
3. **Run Bond Filter:**  
   * IF in Cell 4/6: Calculate TLT SMAs. Determine Bond\_State (Bull/Bear).  
4. **Map Positions:**  
   * IF Cell 1-3 or 5: Use standard Equity Allocations.  
   * IF Cell 4 or 6: Apply **Safe Haven Logic** (Mix Cash \+ Bond ETF).

## **5\. Position Mapping (Updated Matrix)**

**Global Parameters:**

* max\_bond\_weight (Default 0.4): Max allocation to TMF/TMV.

### **5.1 Equity-Dominant Cells (Standard)**

**Cell 1 (Kill Zone), Cell 2 (Fragile), Cell 3 (Drift)**

* Identical to v3.5.

**Cell 5 (Grind)**

* *Logic:* 50% QQQ \+ 50% Safe Haven.  
* $w\_{QQQ} \= 0.5$  
* $w\_{SafeHaven} \= 0.5$ (Calculated below)

### **5.2 Defensive Cells (The Upgrade)**

Cell 4: Chop (Sideways \+ High Vol)  
Cell 6: Crash (Bear \+ High Vol)  
Instead of 100% Cash, we calculate w\_SafeHaven:

**Step A: Determine Instrument**

* IF Bond\_Trend \== Bull: Instrument \= **TMF**.  
* ELSE: Instrument \= **TMV**.

**Step B: Allocation**

* $w\_{Inst} \= \\text{max\\\_bond\\\_weight}$ (e.g., 0.4)  
* $w\_{Cash} \= 1.0 \- w\_{Inst}$ (e.g., 0.6)

*Note: In Cell 6, if allow\_psq is also True, the Cash portion can be split with PSQ.*

## **6\. Risk Management & Constraints**

### **6.1 Correlation Risk Control**

* **Max Bond Weight:** Strictly capped at 40-50%. Leveraged Bonds (TMF/TMV) are extremely volatile (durations \> 50).  
* **Rationale:** We do not want the hedge to drawdown 20% in a week if rates whip-saw.

### **6.2 Rebalancing**

* Same 5% threshold applies. Bond trends (20/60 SMA) are faster than equity trends, so this bucket may rebalance more frequently than the equity bucket.

## **7\. Parameter Summary (Additions)**

### **7.1 Treasury Parameters**

* bond\_sma\_fast: 20  
* bond\_sma\_slow: 60  
* max\_bond\_weight: 0.4 (40%)  
* allow\_treasury: True

*(All v3.5 parameters for Z-Score and Kalman remain active)*

## **Appendix: Safe Haven Selector Module Implementation**

This module implements the **Treasury Trend Filter**. It is designed to be dropped directly into your Hierarchical\_Adaptive\_v3\_5b.py script to replace the hard-coded Cash/PSQ logic in defensive cells.

### **Python Implementation**

Copy this entire method into your Strategy Class (e.g., right before rebalance\_portfolio).

**Key Changes for Integration:**

* Uses Decimal for all weight calculations to match your script's math standards.  
* Handles the case where TLT data might be missing (failsafe to Cash).

    def get\_safe\_haven\_allocation(self, tlt\_history\_series, current\_defensive\_weight\_decimal):  
        """  
        Determines the optimal defensive mix (Cash \+ Bonds) based on TLT trend.  
          
        Args:  
            tlt\_history\_series (pd.Series): Daily close prices of TLT (needs \~60 bars).  
            current\_defensive\_weight\_decimal (Decimal): The % of portfolio allocated to defense  
                                                        (e.g. Decimal("1.0") for Cell 4).  
          
        Returns:  
            dict: Target weights {Ticker: Decimal}  
        """  
        from decimal import Decimal  
          
        \# 1\. Constants  
        BOND\_FAST \= 20  
        BOND\_SLOW \= 60  
        \# Cap bond ETF allocation to 40% of total portfolio to control volatility  
        MAX\_BOND\_TOTAL\_PCT \= Decimal("0.40")   
          
        \# 2\. Safety Check: Data sufficiency  
        if tlt\_history\_series is None or len(tlt\_history\_series) \< BOND\_SLOW:  
            \# Fallback to 100% Cash for the defensive portion  
            return {"CASH": current\_defensive\_weight\_decimal}

        \# 3\. Calculate Indicators  
        \# Note: We use .iloc\[-1\] to get the most recent value  
        sma\_fast \= tlt\_history\_series.rolling(window=BOND\_FAST).mean().iloc\[-1\]  
        sma\_slow \= tlt\_history\_series.rolling(window=BOND\_SLOW).mean().iloc\[-1\]  
          
        \# 4\. Determine Instrument  
        \# TMF (+3x Bonds) for Deflation/Safety (Rates Falling)  
        \# TMV (-3x Bonds) for Inflation/Rate Shock (Rates Rising)  
        if sma\_fast \> sma\_slow:  
            selected\_ticker \= "TMF"  
        else:  
            selected\_ticker \= "TMV"  
              
        \# 5\. Sizing Logic  
        \# We utilize up to 40% of the Total Portfolio for Bonds.  
        \# If the defensive weight is small (e.g. 50% in Cell 5), we scale proportionally  
        \# but ensure we never exceed the global MAX\_BOND\_TOTAL\_PCT.  
          
        \# Calculate potential bond weight  
        \# e.g., if defensive portion is 1.0, bond part is 0.4. Cash is 0.6.  
        bond\_weight \= min(current\_defensive\_weight\_decimal \* Decimal("0.4"), MAX\_BOND\_TOTAL\_PCT)  
          
        \# The rest of the defensive bucket stays in Cash  
        cash\_weight \= current\_defensive\_weight\_decimal \- bond\_weight  
          
        return {  
            selected\_ticker: bond\_weight,  
            "CASH": cash\_weight  
        }  
