# **Strategy Specification: VIX-Filtered (V10.0)**

## **1\. Core Components**

* **Strategy Name:** VIX-Filtered (V10.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily), VIX (Daily)  
* **Trading Vehicles:** TQQQ, QQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals at **Close**, execution at **Next Day's Open**.

## **2\. Core Philosophy**

This strategy simplifies the dynamic regime concept from V9.0 to improve robustness and reduce the risk of curve-fitting.

It is **not** a "strategy-of-strategies." Instead, it uses the VIX as a single, binary **"Risk-On / Risk-Off"** master switch. This switch determines if the market is "CALM" or "CHOPPY".

The core logic is: **"Only run the Goldilocks V8.0 strategy (V4.md) when the market is CALM. Otherwise, hold CASH."**

## **3\. Indicator Parameters**

* **Primary Regime Filter (on VIX):**  
  * VIX\_EMA\_Period: 50-day Exponential Moving Average  
* **V8.0 Goldilocks Parameters (on QQQ):**  
  * EMA\_Trend: 100-day Exponential Moving Average  
  * MACD\_fast: 12, MACD\_slow: 26, MACD\_signal: 9  
  * ATR\_Period: 14 (For TQQQ stop-loss)  
  * ATR\_Stop\_Multiplier: 3.0 (For TQQQ stop-loss)  
* **Risk & Sizing Parameters:**  
  * Risk\_TQQQ: 2.5% (Risk 2.5% of total equity on all TQQQ trades)  
  * Allocation\_QQQ: 60% (Allocate 60% of total equity to QQQ trades)

## **4\. Hierarchical Logic (Calculated at Day's Close)**

The logic is run in two steps. If Step 1 triggers, Step 2 is ignored.

### **Step 1: Primary VIX Filter (The "Master Switch")**

| Regime | Conditions | Target Vehicle |
| :---- | :---- | :---- |
| **CHOPPY** | VIX\_raw\[today\] \> VIX\_EMA\_Period\[today\] | **CASH** |

### **Step 2: V8.0 Goldilocks Logic (Only if Market is "CALM")**

This logic only runs if VIX\_raw\[today\] \<= VIX\_EMA\_Period\[today\].

| Regime | Conditions | Target Vehicle |
| :---- | :---- | :---- |
| **RISK-OFF (Bear)** | QQQ\_Price\[today\] \< EMA\_Trend | **CASH** |
| **RISK-ON (Strong)** | QQQ\_Price\[today\] \> EMA\_Trend AND MACD\_Line \> Signal\_Line | **TQQQ** |
| **RISK-ON (Pause)** | QQQ\_Price\[today\] \> EMA\_Trend AND MACD\_Line \< Signal\_Line | **QQQ (1x)** |

**Combined Result:** The system will hold **CASH** if *either* the VIX is too high *or* if the VIX is low but the QQQ trend is broken (below its EMA\_Trend). It only takes on risk (QQQ or TQQQ) when *both* the VIX is calm *and* the QQQ price is in an uptrend.

## **5\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the final Target\_Vehicle from the hierarchical logic above.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings** at the Open.  
3. Execute the new regime's action:

#### **If Target\_Vehicle is TQQQ (Regime: Strong):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_TQQQ  
* **Dollar\_Risk\_Per\_Share:** TQQQ\_ATR\[today\] \* ATR\_Stop\_Multiplier  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is QQQ (Regime: Pause):**

* **Action:** Execute a flat allocation.  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_QQQ  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Open\_Price  
* **Stop-Loss:** None. This position is managed by the regime filters.

#### **If Target\_Vehicle is CASH (Regime: CHOPPY or RISK-OFF):**

* **Action:** Hold 100% Cash.

### **B. Stop-Loss Management (TQQQ Only):**

* The ATR\_Stop\_Multiplier stop is a **hard stop**. If hit, liquidate the TQQQ position and hold CASH for the remainder of the day.  
* The system will re-evaluate for a new entry at the close.

## **6\. Suggested Parameter Sweep for Robustness Test**

This sweep is designed to find a "parameter plateau" (a robust region) rather than a single "peak."

* **VIX Filter:**  
  * VIX\_EMA\_Period: \[20, 50, 75, 100\]  
* **Trend Filter:**  
  * EMA\_Trend: \[75, 100, 150, 200\]  
* **Risk Management:**  
  * ATR\_Stop\_Multiplier: \[2.0, 2.5, 3.0\]  
  * Risk\_TQQQ: \[0.015, 0.02, 0.025\] (Keeping risk conservative)  
* **Sizing:**  
  * Allocation\_QQQ: \[0.5, 0.6, 0.7\]