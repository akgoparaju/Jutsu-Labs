# **Strategy Specification: ADX-Trend (Version 2.0)**

#### **1\. Core Components**

* **Portfolio:** $10,000 USD  
* **Signal Asset:** QQQ (Daily Data)  
* **Trading Vehicles:** TQQQ (Long), SQQQ (Short), QQQ (1x Long), CASH  
* **Execution Assumption:** Signals are calculated at the **close** of the current day (Bar D). All trades (Buy/Sell/Rebalance) are executed at the **open** of the next day (Bar D+1).

#### **2\. Indicator Parameters (on QQQ Daily)**

* EMA\_fast: 20-day Exponential Moving Average  
* EMA\_slow: 50-day Exponential Moving Average  
* ADX\_val: 14-day Average Directional Index (ADX)  
* ADX\_threshold\_low: 20  
* ADX\_threshold\_high: 25

#### **3\. State & Regime Definitions**

At the close of each day, determine the **Trend Direction** and **Trend Strength**:

* **Trend\_Direction:**  
  * 'Bullish' IF EMA\_fast \> EMA\_slow  
  * 'Bearish' IF EMA\_fast \< EMA\_slow  
* **Trend\_Strength:**  
  * 'Strong' IF ADX\_val \> ADX\_threshold\_high (25)  
  * 'Building' IF ADX\_val \> ADX\_threshold\_low (20) AND ADX\_val \<= ADX\_threshold\_high (25)  
  * 'Weak' IF ADX\_val \<= ADX\_threshold\_low (20)

#### **4\. Logic & Allocation Matrix (Execute at Next Open)**

Your backtesting loop will check these 6 regimes in order. The Target\_Position is the portfolio state to hold for the *entire next day*.

| Regime | Trend Strength (ADX\_val) | Trend Direction (EMA\_fast vs EMA\_slow) | Target Vehicle | Target Allocation | Target Position Value |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **1** | 'Strong' (\> 25\) | 'Bullish' | **TQQQ** | 60% | $6,000 |
| **2** | 'Building' (20-25) | 'Bullish' | **TQQQ** | 30% | $3,000 |
| **3** | 'Strong' (\> 25\) | 'Bearish' | **SQQQ** | 60% | $6,000 |
| **4** | 'Building' (20-25) | 'Bearish' | **SQQQ** | 30% | $3,000 |
| **5** | 'Weak' (\< 20\) | 'Bullish' | **QQQ** | 50% | $5,000 |
| **6** | 'Weak' (\< 20\) | 'Bearish' | **CASH** | 100% | $0 (in assets) |

#### **5\. Backtesting Logic Notes**

* **Portfolio Sizing:** The "Target Position Value" is based on the *initial* $10k. For a dynamic backtest, you must calculate this based on the **current portfolio equity** at the time of the trade.  
  * **Example (Regime 1):** Target\_Dollars \= Current\_Portfolio\_Equity \* 0.60  
  * Shares\_to\_Hold \= Target\_Dollars / TQQQ\_Open\_Price  
* **Rebalancing:** On *any* regime change, your code must first liquidate\_all\_positions() and then create\_new\_position() based on the new regime's target. This simplifies the logic versus calculating complex deltas.  
* **No Change:** If the regime on Day D is the same as Day D-1 (e.g., remains in Regime 1), **no trades are made**. The position is simply held. The allocation will drift with market action, which is an intended part of the strategy (i.e., you let winners run). You only rebalance back to the 60%/30%/50% target *when a regime changes*.