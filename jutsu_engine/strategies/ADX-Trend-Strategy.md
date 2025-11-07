# **Strategy Specification: Momentum-ATR (V4.0)**

## **1\. Core Components**

* **Strategy Name:** Momentum-ATR (V4.0)  
* **Initial Portfolio:** $10,000 USD  
* **Signal Assets (for calculation):** QQQ (Daily), VIX Index (Daily)  
* **Trading Vehicles (for execution):** TQQQ, SQQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Execution:** Signals are calculated at the **Close** of the current day (Bar D). All trade actions (Buy, Sell, Stop-Loss) are executed on the **Next Day** (Bar D+1) at the **Open**.

## **2\. Indicator Parameters**

* **Momentum (on QQQ):**  
  * MACD\_fast\_period: 12  
  * MACD\_slow\_period: 26  
  * MACD\_signal\_period: 9  
  * **Calculated Values:** Histogram (MACD Line \- Signal Line), Histogram\_Delta (Histogram\[today\] \- Histogram\[yesterday\])  
* **Volatility Filter (on VIX):**  
  * VIX\_Kill\_Switch\_Level: 30.0  
* **Risk Management (on TQQQ & SQQQ):**  
  * ATR\_Period: 14  
  * ATR\_Stop\_Multiplier: 2.0 (i.e., a 2-ATR stop-loss)

## **3\. Strategy Risk Parameters**

* **Risk\_Strong\_Trend:** 3.0% (Risk 3% of total portfolio equity on strong trend signals)  
* **Risk\_Waning\_Trend:** 1.5% (Risk 1.5% of total portfolio equity on weakening trend signals)

## **4\. Regime & Decision-Tree Logic (Calculated at Day's Close)**

At the end of each day, determine the Target\_Vehicle and the Risk\_To\_Apply for the next session.

| Priority | Condition | Regime | Target Vehicle | Risk to Apply |
| :---- | :---- | :---- | :---- | :---- |
| **1** | VIX\[today\] \> 30.0 | **Risk-Off / Kill-Switch** | **CASH** | 0.0% |
| **2** | VIX\[today\] \<= 30.0 AND Histogram \> 0 AND Histogram\_Delta \> 0 | **Strong Bull** | **TQQQ** | Risk\_Strong\_Trend (3.0%) |
| **3** | VIX\[today\] \<= 30.0 AND Histogram \> 0 AND Histogram\_Delta \<= 0 | **Waning Bull** | **TQQQ** | Risk\_Waning\_Trend (1.5%) |
| **4** | VIX\[today\] \<= 30.0 AND Histogram \< 0 AND Histogram\_Delta \< 0 | **Strong Bear** | **SQQQ** | Risk\_Strong\_Trend (3.0%) |
| **5** | VIX\[today\] \<= 30.0 AND Histogram \< 0 AND Histogram\_Delta \>= 0 | **Waning Bear** | **SQQQ** | Risk\_Waning\_Trend (1.5%) |
| **6** | *Any other condition* (e.g., VIX \<= 30 but Histogram \= 0\) | **Neutral / Flat** | **CASH** | 0.0% |

## **5\. Trade Execution & Position Sizing Rules (Executed at Next Day's Open)**

This strategy holds a maximum of one position at a time and is governed by two main events: **Signal Change** or **Stop-Loss Hit**.

### **A. On a Signal Change:**

1. Check the Current\_Position against the new Target\_Vehicle.  
2. If Target\_Vehicle is different from Current\_Position:  
   a. Liquidate any and all existing positions at the Open.  
   b. If Target\_Vehicle is CASH: Do nothing further. Hold cash.  
   c. If Target\_Vehicle is TQQQ or SQQQ:  
   i. Get the Current\_ATR (14-day) of the Target\_Vehicle (TQQQ or SQQQ).  
   ii. Calculate Dollar Risk per Share: Dollar\_Risk\_Per\_Share \= Current\_ATR \* ATR\_Stop\_Multiplier  
   iii. Calculate Total Dollar Risk for Trade: Total\_Dollar\_Risk \= Portfolio\_Equity \* Risk\_To\_Apply  
   iv. Calculate Position Size: Shares\_To\_Buy \= Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
   v. Execute BUY order for Shares\_To\_Buy at the Open.  
   vi. Place a Stop-Loss Order (GTC) based on the fill price:  
   \- For TQQQ (Long): Stop\_Price \= Fill\_Price \- Dollar\_Risk\_Per\_Share  
   \- For SQQQ (Short): Stop\_Price \= Fill\_Price \+ Dollar\_Risk\_Per\_Share

### **B. On a Stop-Loss Hit:**

1. If the active Stop-Loss Order is triggered:  
   a. Liquidate the position immediately.  
   b. Hold CASH for the remainder of the day.  
   c. Do not enter any new trades until a new signal change occurs at the end of the day.

### **C. If No Signal Change and No Stop-Loss Hit:**

1. **Do nothing.** Hold the current position and maintain the existing Stop-Loss Order.