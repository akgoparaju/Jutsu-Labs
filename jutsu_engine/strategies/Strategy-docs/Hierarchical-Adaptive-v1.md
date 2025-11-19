# **Strategy Specification: Hierarchical Adaptive (v1.0)**

## **1\. Core Components**

* **Strategy Name:** Hierarchical Adaptive (v1.0)  
* **Initial Portfolio:** $10,000 USD  
* **Signal Assets:** QQQ (Daily), VIX (Daily)  
* **Trading Vehicles:** TQQQ, QQQ, SQQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals calculated using **Daily data**, execution **same day**.  
  * *Note: This implies all indicators are calculated on the prior day's close (\[t-1\]) or on the current day's Open/Price, with execution occurring immediately after the signal is confirmed.*

## **2\. Core Philosophy**

This is a capital-preservation-first, adaptive "strategy-of-strategies." It is built on a 3-step hierarchical filter to ensure that risk is only taken when market conditions are favorable.

1. **Filter 1: Volatility (Master Switch):** The VIX is used as the primary "Risk-On / Risk-Off" switch. If volatility is too high, the system defaults to CASH, regardless of any other signal. This is the primary defense against catastrophic intraday losses.  
2. **Filter 2: Regime (Strategy Selector):** *If the market is calm,* a slow-moving **Adaptive Kalman Filter** identifies the market's "personality" (Strong Bull, Moderate Bull, Chop, or Bear).  
3. **Filter 3: Signal (Entry Trigger):** *If the market is calm AND in a trending regime,* a set of **adaptive MACD parameters**, specifically tuned for that regime, provides the final trade signal.

The system will only enter a leveraged trade when all three filters are aligned.

## **3\. Indicator Parameters**

### **A. Filter 1: Volatility (on VIX)**

* VIX\_EMA\_Period: 20 (Based on successful MACD\_Trend-v6 backtest. To be optimized.)

### **B. Filter 2: Regime (on QQQ)**

* **Kalman Filter Parameters (Tuned for "Moderate Horizon"):**  
  * model: VOLUME\_ADJUSTED  
  * measurement\_noise: 5000.0 (High value for a slow signal. To be optimized.)  
  * osc\_smoothness: 20 (High value for smooth oscillator. To be optimized.)  
  * strength\_smoothness: 20 (High value for smooth oscillator. To be optimized.)  
  * process\_noise\_1: 0.01 (Fixed)  
  * process\_noise\_2: 0.01 (Fixed)  
* **Regime Thresholds (To be optimized):**  
  * Thresh\_Strong\_Bull: 60  
  * Thresh\_Moderate\_Bull: 20  
  * Thresh\_Moderate\_Bear: \-20

### **C. Filter 3: Signal (Adaptive MACD Sets)**

* **Params\_Strong\_Bull (Aggressive):**  
  * EMA\_Trend\_SB: 100  
  * MACD\_fast\_SB: 12, MACD\_slow\_SB: 26, MACD\_signal\_SB: 9  
* **Params\_Moderate\_Bull (Cautious):**  
  * EMA\_Trend\_MB: 150  
  * MACD\_fast\_MB: 20, MACD\_slow\_MB: 50, MACD\_signal\_MB: 12  
* **Params\_Bear (Defensive/Short):**  
  * EMA\_Trend\_B: 100  
  * MACD\_fast\_B: 12, MACD\_slow\_B: 26, MACD\_signal\_B: 9

### **D. Risk & Sizing Parameters**

* ATR\_Period: 14 (For TQQQ/SQQQ stop-loss)  
* ATR\_Stop\_Multiplier: 2.0 (Based on successful MACD\_Trend-v6 backtest. To be optimized.)  
* Risk\_Leveraged: 2.5% (Risk 2.5% of total equity on all TQQQ/SQQQ trades)  
* Allocation\_Unleveraged: 80% (Allocate 80% of total equity to QQQ trades)

## **4\. Hierarchical Logic (Calculated Intraday)**

The logic is run in order. If any "CASH" signal is triggered, the steps below it are ignored.

Target\_Vehicle is assumed to be CASH unless changed by the logic.

### **Step 1: VIX Volatility Filter (Master Switch)**

* **Condition:** VIX\_raw\[today\] \> VIX\_EMA\_Period\[today-1\]  
* **Action:** **Target\_Vehicle \= CASH**. Stop all further logic.  
* **Result:** *Proceed to Step 2 only if VIX is low (market is "CALM").*

### **Step 2: Kalman Regime Filter (Strategy Selector)**

* **Condition:** Calculate trend\_strength from Kalman Filter (using data up to \[today-1\]).  
* **Action:** Identify the current regime:  
  * IF trend\_strength \> Thresh\_Strong\_Bull \-\> Regime \= "STRONG\_BULL"  
  * IF Thresh\_Mod\_Bull \< trend \<= Thresh\_Strong\_Bull \-\> Regime \= "MODERATE\_BULL"  
  * IF trend\_strength \< Thresh\_Mod\_Bear \-\> Regime \= "BEAR"  
  * ELSE (CHOP / NEUTRAL) \-\> Regime \= "CHOP"  
* **Result:** *If Regime \== "CHOP", Target\_Vehicle \= CASH. Otherwise, proceed to Step 3 with the active Regime.*

### **Step 3: Adaptive MACD Signal (Entry Trigger)**

This logic only runs if Regime is "STRONG\_BULL", "MODERATE\_BULL", or "BEAR".

* **Case 1: Regime \== "STRONG\_BULL"**  
  * Uses Params\_Strong\_Bull (e.g., EMA\_Trend\_SB: 100, MACD\_SB: 12/26/9)  
  * IF QQQ\_Price\[today\] \< EMA\_SB\[today-1\] \-\> Target\_Vehicle \= CASH  
  * IF QQQ\_Price\[today\] \> EMA\_SB\[today-1\] AND MACD\_SB \> Signal\_SB \-\> Target\_Vehicle \= TQQQ  
  * IF QQQ\_Price\[today\] \> EMA\_SB\[today-1\] AND MACD\_SB \< Signal\_SB \-\> Target\_Vehicle \= QQQ  
* **Case 2: Regime \== "MODERATE\_BULL"**  
  * Uses Params\_Moderate\_Bull (e.g., EMA\_Trend\_MB: 150, MACD\_MB: 20/50/12)  
  * IF QQQ\_Price\[today\] \< EMA\_MB\[today-1\] \-\> Target\_Vehicle \= CASH  
  * IF QQQ\_Price\[today\] \> EMA\_MB\[today-1\] AND MACD\_MB \> Signal\_MB \-\> Target\_Vehicle \= QQQ  
  * IF QQQ\_Price\[today\] \> EMA\_MB\[today-1\] AND MACD\_MB \< Signal\_MB \-\> Target\_Vehicle \= CASH  
* **Case 3: Regime \== "BEAR"**  
  * Uses Params\_Bear (e.g., EMA\_Trend\_B: 100, MACD\_B: 12/26/9)  
  * IF QQQ\_Price\[today\] \> EMA\_B\[today-1\] \-\> Target\_Vehicle \= CASH  
  * IF QQQ\_Price\[today\] \< EMA\_B\[today-1\] AND MACD\_B \< Signal\_B \-\> Target\_Vehicle \= SQQQ  
  * IF QQQ\_Price\[today\] \< EMA\_B\[today-1\] AND MACD\_B \> Signal\_B \-\> Target\_Vehicle \= CASH

## **5\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the final Target\_Vehicle from the hierarchical logic above.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings**.  
3. **Execute the trade** for the new Target\_Vehicle immediately.

#### **If Target\_Vehicle is TQQQ or SQQQ (Leveraged):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Leveraged  
* **Dollar\_Risk\_Per\_Share:** ATR\[today-1\] \* ATR\_Stop\_Multiplier  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share (for TQQQ) or Fill\_Price \+ Dollar\_Risk\_Per\_Share (for SQQQ).

#### **If Target\_Vehicle is QQQ (Unleveraged):**

* **Action:** Execute a flat allocation.  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_Unleveraged  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Price\[today\]  
* **Stop-Loss:** None. This position is managed by the regime filters.

### **B. Stop-Loss Management (TQQQ & SQQQ Only):**

* The ATR\_Stop\_Multiplier stop is a **hard stop**. If hit intraday, liquidate the position and hold CASH for the remainder of the day.  
* The system will re-evaluate for a new entry on the next bar (or next day).

## **6\. Suggested Parameter Sweep for Robustness Test (WFO)**

* **Filter 1 (VIX):**  
  * VIX\_EMA\_Period: \[20, 50, 75\]  
* **Filter 2 (Kalman):**  
  * measurement\_noise: \[2000.0, 5000.0, 10000.0\]  
  * osc\_smoothness: \[15, 20, 30\]  
  * strength\_smoothness: \[15, 20, 30\]  
  * Thresh\_Strong\_Bull: \[60, 70\]  
  * Thresh\_Moderate\_Bull: \[20, 30\]  
  * Thresh\_Moderate\_Bear: \[-20, \-30\]  
* **Filter 3 (Adaptive Sets):**  
  * Params\_Strong\_Bull Set:  
    * EMA\_Trend\_SB: \[75, 100\]  
    * MACD\_fast\_SB: \[12\], MACD\_slow\_SB: \[26\], MACD\_signal\_SB: \[9\]  
  * Params\_Moderate\_Bull Set:  
    * EMA\_Trend\_MB: \[150, 200\]  
    * MACD\_fast\_MB: \[20\], MACD\_slow\_MB: \[50\], MACD\_signal\_MB: \[12\]  
* **Risk & Sizing:**  
  * ATR\_Stop\_Multiplier: \[2.0, 2.5\]  
  * Risk\_Leveraged: \[0.015, 0.025\]  
  * Allocation\_Unleveraged: \[0.8, 1.0\]