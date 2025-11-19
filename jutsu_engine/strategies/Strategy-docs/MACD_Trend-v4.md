# **Strategy Specification: Goldilocks (V8.0)**

## **1\. Core Components**

* **Strategy Name:** Goldilocks (V8.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily)  
* **Trading Vehicles:** TQQQ, QQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals at **Close**, execution at **Next Day's Open**.

## **2\. Core Philosophy**

This is a **long-only, multi-regime** strategy. It uses a slow-moving average (100-EMA) as its primary "Risk-On / Risk-Off" filter. During "Risk-On" periods, it uses a faster momentum signal (MACD Crossover) to decide *how much* leverage to apply (3x or 1x). This is designed to capture strong trends aggressively while reducing both cash drag and whipsaw during pauses.

## **3\. Indicator Parameters**

* **Primary Trend Filter (on QQQ):**  
  * EMA\_Trend: 100-day Exponential Moving Average  
* **Momentum Signal (on QQQ):**  
  * MACD\_fast: 12, MACD\_slow: 26, MACD\_signal: 9  
  * **Calculated Value:** MACD\_Line, Signal\_Line  
* **Risk Management (on TQQQ):**  
  * ATR\_Period: 14  
  * ATR\_Stop\_Multiplier: 3.0 (Wider 3-ATR stop)

## **4\. Strategy Risk Parameters**

* **Risk\_TQQQ:** 2.5% (Risk 2.5% of total portfolio equity on all TQQQ trades)  
* **Allocation\_QQQ:** 60% (When entering QQQ, allocate a flat 60% of the portfolio)

## **5\. Regime & Decision-Tree Logic (Calculated at Day's Close)**

This system has three simple, hierarchical regimes.

| Priority | Regime | Conditions | Target Vehicle |
| :---- | :---- | :---- | :---- |
| **1** | **RISK-OFF (BEAR)** | Price\[today\] \< EMA\_Trend (100-day) | **CASH** |
| **2** | **RISK-ON (STRONG)** | Price\[today\] \> EMA\_Trend (100-day) AND MACD\_Line \> Signal\_Line | **TQQQ** |
| **3** | **RISK-ON (PAUSE)** | Price\[today\] \> EMA\_Trend (100-day) AND MACD\_Line \< Signal\_Line | **QQQ (1x)** |

## **6\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the new Target\_Vehicle from the regime logic above.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings** at the Open.  
3. Execute the new regime's action:

#### **If Target\_Vehicle is TQQQ (Regime 2):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_TQQQ (2.5%)  
* **Dollar\_Risk\_Per\_Share:** TQQQ\_ATR\[today\] \* ATR\_Stop\_Multiplier (3.0)  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is QQQ (Regime 3):**

* **Action:** Execute a flat allocation.  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_QQQ (60%)  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Open\_Price  
* **Stop-Loss:** None. This position is managed by the regime filters.

#### **If Target\_Vehicle is CASH (Regime 1):**

* **Action:** Hold 100% Cash.

### **B. On a Stop-Loss Hit (TQQQ only):**

1. **Liquidate** the TQQQ position immediately.  
2. **Hold CASH** and wait for a *new* signal at the end of the day.