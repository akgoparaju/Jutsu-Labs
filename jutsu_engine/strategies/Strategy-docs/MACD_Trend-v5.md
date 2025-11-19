# **Strategy Specification: Dynamic Regime (V9.0)**

## **1\. Core Components**

* **Strategy Name:** Dynamic Regime (V9.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily), VIX (Daily)  
* **Trading Vehicles:** TQQQ, QQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals at **Close**, execution at **Next Day's Open**.

## **2\. Core Philosophy**

This is a **dynamic, dual-regime** strategy. It is a "strategy-of-strategies" that first identifies the market's volatility regime (Calm vs. Choppy) by comparing the raw VIX to its 50-day EMA.

It then applies the V8.0 "Goldilocks" logic (TQQQ/QQQ/CASH) but uses a *different set of parameters* (a "playbook") that is optimized for that specific regime. This is designed to be aggressive in smooth bull markets while tightening up defense and reacting faster in choppy, high-fear markets.

## **3\. Indicator Parameters**

### **A. Regime Switch Filter (on VIX Daily)**

* VIX\_EMA\_Period: 50-day EMA  
* **Calculated Value:** VIX\_EMA\_50

### **B. "Playbook 1: CALM" Parameters (Active when VIX\_raw \<= VIX\_EMA\_50)**

* EMA\_Period\_Calm: 200 (Slow filter for smooth trends)  
* ATR\_Stop\_Calm: 3.0 (Wide stop to avoid noise)

### **C. "Playbook 2: CHOPPY" Parameters (Active when VIX\_raw \> VIX\_EMA\_50)**

* EMA\_Period\_Choppy: 75 (Fast filter for choppy markets)  
* ATR\_Stop\_Choppy: 2.0 (Tight stop to lock in gains)

### **D. Static Parameters (Shared by both playbooks)**

* **Momentum Signal (on QQQ):**  
  * MACD\_fast: 12, MACD\_slow: 26, MACD\_signal: 9  
  * **Calculated Values:** MACD\_Line, Signal\_Line  
* **Risk & Sizing:**  
  * Risk\_TQQQ: 2.5% (0.025)  
  * Allocation\_QQQ: 60% (0.60)  
* **ATR Period (on TQQQ):** 14 (This is static; only the *multiplier* changes)

## **4\. Dynamic Regime & Signal Logic**

### **Step 1: Determine Active Parameters (Run this first each day)**

* **IF VIX\_raw\[today\] \<= VIX\_EMA\_50\[today\]:**  
  * The market is **"CALM"**.  
  * Set Active\_EMA \= EMA\_Period\_Calm (200)  
  * Set Active\_ATR\_Stop\_Multiplier \= ATR\_Stop\_Calm (3.0)  
* **ELSE (VIX\_raw\[today\] \> VIX\_EMA\_50\[today\]):**  
  * The market is **"CHOPPY"**.  
  * Set Active\_EMA \= EMA\_Period\_Choppy (75)  
  * Set Active\_ATR\_Stop\_Multiplier \= ATR\_Stop\_Choppy (2.0)

### **Step 2: Determine Target Regime (V8.0 Logic using *Active* Parameters)**

| Regime ID | Regime Name | Logic | Target Vehicle |
| :---- | :---- | :---- | :---- |
| **1** | **RISK-OFF** | Price\[today\] \< Active\_EMA | **CASH** |
| **2** | **RISK-ON (STRONG)** | Price\[today\] \> Active\_EMA AND MACD\_Line \> Signal\_Line | **TQQQ** |
| **3** | **RISK-ON (PAUSE)** | Price\[today\] \> Active\_EMA AND MACD\_Line \< Signal\_Line | **QQQ (1x)** |

## **5\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the new Target\_Vehicle from the logic in Step 2\.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings** at the Open.  
3. Execute the new regime's action:

#### **If Target\_Vehicle is TQQQ (Regime 2):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_TQQQ (2.5%)  
* **Dollar\_Risk\_Per\_Share:** TQQQ\_ATR\[today\] \* Active\_ATR\_Stop\_Multiplier (Uses 3.0 or 2.0)  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is QQQ (Regime 3):**

* **Action:** Execute a flat allocation.  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_QQQ (60%)  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Open\_Price  
* **Stop-Loss:** None (This is a 1x strategic hold).

#### **If Target\_VEHICLE is CASH (Regime 1):**

* **Action:** Hold 100% in cash.

### **B. Stop-Loss Management (TQQQ Only)**

* The 2-ATR or 3-ATR stop (based on Active\_ATR\_Stop\_Multiplier) is a **hard stop**. If hit, liquidate the TQQQ position and hold CASH for the remainder of the day.  
* The system will re-evaluate for a new entry at the close.

## **6\. Suggested Parameter Sweep for Optimization**

This is the sweep I recommend to find the best-performing "strategy-of-strategies."

* **VIX\_EMA\_Period**: \[20, 50, 100\]  
* **EMA\_Period\_Calm**: \[150, 200, 250\]  
* **ATR\_Stop\_Calm**: \[2.5, 3.0, 3.5\]  
* **EMA\_Period\_Choppy**: \[50, 75, 100\]  
* **ATR\_Stop\_Choppy**: \[2.0, 2.5\]  
* **Risk\_TQQQ**: \[0.025, 0.03\]  
* **Allocation\_QQQ**: \[0.5, 0.6\]