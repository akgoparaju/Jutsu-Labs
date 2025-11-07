# **Strategy Specification: All-Weather (V6.0)**

## **1\. Core Components**

* **Strategy Name:** All-Weather (V6.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily), VIX Index (Daily)  
* **Trading Vehicles:** TQQQ, QQQ, SQQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals at **Close**, execution at **Next Day's Open**.

## **2\. Indicator Parameters**

* **Primary Trend (on QQQ):**  
  * EMA\_Trend: 100-day Exponential Moving Average  
* **Momentum (on QQQ):**  
  * MACD\_fast: 12, MACD\_slow: 26, MACD\_signal: 9  
  * **Calculated Value:** MACD\_Line, Signal\_Line, Zero\_Line (value \= 0\)  
* **Volatility Filter (on VIX):**  
  * VIX\_Kill\_Switch: 30.0  
* **Risk Management (on TQQQ, QQQ, SQQQ):**  
  * ATR\_Period: 14  
  * ATR\_Stop\_Multiplier: 3.0 (Wider 3-ATR stop)

## **3\. Strategy Risk Parameters**

* **Risk\_Per\_Trade:** 2.5% (Risk 2.5% of total portfolio equity on *any* new TQQQ or SQQQ position)  
* **Allocation\_QQQ:** 50% (When entering QQQ, allocate a flat 50% of the portfolio. This is a "risk-reduced" state, not an "all-in" trade).

## **4\. Regime & Decision-Tree Logic (Calculated at Day's Close)**

This system has four distinct states. The logic is checked in this priority order.

| Priority | Regime | Conditions | Target Vehicle |
| :---- | :---- | :---- | :---- |
| **1** | **VIX FEAR** | VIX\[today\] \> VIX\_Kill\_Switch (30.0) | **CASH** |
| **2** | **STRONG BULL** | Price\[today\] \> EMA\_Trend (100-day) AND MACD\_Line \> Signal\_Line | **TQQQ** |
| **3** | **WEAK BULL / PAUSE** | Price\[today\] \> EMA\_Trend (100-day) AND MACD\_Line \< Signal\_Line | **QQQ (1x)** |
| **4** | **STRONG BEAR** | Price\[today\] \< EMA\_Trend (100-day) AND MACD\_Line \< Zero\_Line | **SQQQ** |
| **5** | **CHOP / WEAK BEAR** | *All other conditions* (e.g., Price \< 100-EMA but MACD is still positive) | **CASH** |

## **5\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the new Target\_Vehicle from the regime logic above.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings** at the Open.  
3. Execute the new regime's action:

#### **If Target\_Vehicle is TQQQ (Regime 2):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Per\_Trade (2.5%)  
* **Dollar\_Risk\_Per\_Share:** TQQQ\_ATR\[today\] \* ATR\_Stop\_Multiplier (3.0)  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is QQQ (Regime 3):**

* **Action:** Execute a flat allocation (this is a "hold," not a "trade").  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_QQQ (50%)  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Open\_Price  
* **Stop-Loss:** None. This position is managed by the regime filters, not an ATR stop.

#### **If Target\_Vehicle is SQQQ (Regime 4):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Per\_Trade (2.5%)  
* **Dollar\_Risk\_Per\_Share:** SQQQ\_ATR\[today\] \* ATR\_Stop\_Multiplier (3.0)  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss (Reversed):** Fill\_Price \+ Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is CASH (Regime 1 or 5):**

* **Action:** Hold 100% Cash.

### **B. On a Stop-Loss Hit (TQQQ or SQQQ):**

1. **Liquidate** the position immediately.  
2. **Hold CASH** and wait for a *new* signal at the end of the day.