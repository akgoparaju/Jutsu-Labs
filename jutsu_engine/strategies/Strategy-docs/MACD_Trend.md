# **Strategy Specification: MACD-Trend (V5.0)**

## **1\. Core Components**

* **Strategy Name:** MACD-Trend (V5.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily), VIX Index (Daily)  
* **Trading Vehicles:** TQQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals at **Close**, execution at **Next Day's Open**.

## **2\. Core Philosophy**

This strategy is a **medium-term, trend-following, long-only** system. It is designed to capture the "meat" of a strong uptrend (the "Trend") and move to cash during all other periods (the "Filter"). It is slow, robust, and designed to avoid "whipsaw" and volatility decay. **It never shorts (buys SQQQ).**

## **3\. Indicator Parameters**

* **Trend Signal (on QQQ):**  
  * MACD\_fast: 12, MACD\_slow: 26, MACD\_signal: 9  
  * **Calculated Value:** MACD\_Line, Signal\_Line  
* **Trend Filter (on QQQ):**  
  * EMA\_Slow: 100-day Exponential Moving Average  
* **Volatility Filter (on VIX):**  
  * VIX\_Kill\_Switch: 30.0  
* **Risk Management (on TQQQ):**  
  * ATR\_Period: 14  
  * ATR\_Stop\_Multiplier: 3.0 (Wider 3-ATR stop to allow trend to "breathe")

## **4\. Strategy Risk Parameters**

* **Risk\_Per\_Trade:** 2.5% (Risk 2.5% of total portfolio equity on every trade)

## **5\. Regime & Decision-Tree Logic (Calculated at Day's Close)**

This system has only two states: **IN (TQQQ)** or **OUT (CASH)**.

### **Go "IN" (Buy TQQQ) Signal:**

A "BUY" signal is generated **only if all 3** of these conditions are met:

1. **Main Trend is Up:** Price\[today\] (of QQQ) \> EMA\_Slow\[today\] (100-day EMA)  
2. **Momentum is Bullish:** MACD\_Line\[today\] \> Signal\_Line\[today\]  
3. **Market is Not in Fear:** VIX\[today\] \<= VIX\_Kill\_Switch (30.0)

### **Go "OUT" (Sell to CASH) Signal:**

An "SELL" signal is generated **if ANY 1** of these conditions is met:

1. **Main Trend Fails:** Price\[today\] (of QQQ) \< EMA\_Slow\[today\]  
2. **Momentum Fails:** MACD\_Line\[today\] \< Signal\_Line\[today\]  
3. **Market is in Fear:** VIX\[today\] \> VIX\_Kill\_Switch

## **6\. Trade Execution & Position Sizing Rules**

### **A. On a Signal Change:**

1. If Current\_Position is CASH and a "BUY" signal fires:  
   a. Get Current\_ATR (14-day) of TQQQ.  
   b. Calculate Dollar Risk per Share: Dollar\_Risk\_Per\_Share \= Current\_ATR \* ATR\_Stop\_Multiplier (3.0)  
   c. Calculate Total Dollar Risk: Total\_Dollar\_Risk \= Portfolio\_Equity \* Risk\_Per\_Trade (2.5%)  
   d. Calculate Position Size: Shares\_To\_Buy \= Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
   e. Execute BUY order for Shares\_To\_Buy at the Open.  
   f. Place a Stop-Loss Order at Stop\_Price \= Fill\_Price \- Dollar\_Risk\_Per\_Share.  
2. If Current\_Position is TQQQ and a "SELL" signal fires:  
   a. Liquidate the entire TQQQ position at the Open.  
   b. Hold CASH.

### **B. On a Stop-Loss Hit:**

1. If the active Stop-Loss Order is triggered:  
   a. Liquidate the TQQQ position immediately.  
   b. Hold CASH and wait for a new "BUY" signal (must meet all 3 "IN" conditions again).