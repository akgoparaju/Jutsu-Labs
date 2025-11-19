# **Strategy Specification: Kalman-MACD Adaptive (v1.0)**

## **1\. Core Components**

* **Strategy Name:** Kalman-MACD Adaptive (v1.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily, provides close, high, low, volume)  
* **Trading Vehicles:** TQQQ, QQQ, SQQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals calculated at **Close**, execution at **Next Day's Open**.

## **2\. Core Philosophy**

This is an adaptive, "strategy-of-strategies" model. It addresses the problem of parameter drift by first identifying the market's "personality" and then deploying a sub-strategy optimized for that specific environment.

It uses a slow-moving **Adaptive Kalman Filter Trend Strength Oscillator** as the master regime filter. This filter's output (-100 to \+100) categorizes the market into one of four regimes: **Strong Bull**, **Moderate Bull**, **Chop/Neutral**, or **Bear**.

For each regime, the system activates a different set of pre-defined MACD and Trend parameters. This allows the strategy to be aggressive in strong uptrends, cautious in moderate uptrends, and defensive (or short) in downtrends, while defaulting to CASH in directionless "chop" to avoid whipsaw.

## **3\. Indicator Parameters**

### **A. Master Regime Filter (on QQQ)**

* **Kalman Filter Parameters (Tuned for "Moderate Horizon"):**  
  * model: VOLUME\_ADJUSTED (Adapts to QQQ volume)  
  * measurement\_noise: 5000.0 (High value for a very smooth, slow signal. To be optimized.)  
  * osc\_smoothness: 20 (High value for smooth oscillator. To be optimized.)  
  * strength\_smoothness: 20 (High value for smooth oscillator. To be optimized.)  
  * process\_noise\_1: 0.01 (Fixed)  
  * process\_noise\_2: 0.01 (Fixed)

### **B. Regime Thresholds (To be optimized)**

* Thresh\_Strong\_Bull: 60  
* Thresh\_Moderate\_Bull: 20  
* Thresh\_Moderate\_Bear: \-20

### **C. Adaptive Parameter Sets (To be optimized)**

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
* ATR\_Stop\_Multiplier: 3.0 (To be optimized)  
* Risk\_Leveraged: 2.5% (Risk 2.5% of total equity on all TQQQ/SQQQ trades)  
* Allocation\_Unleveraged: 80% (Allocate 80% of total equity to QQQ trades)

## **4\. Hierarchical Logic (Calculated at Day's Close)**

Step 1: Calculate the trend\_strength value from the Kalman Filter.  
Step 2: Based on trend\_strength, select and execute the logic for one of the four regimes.

| Regime | Kalman Conditions | Logic to Execute | Target Vehicle |
| :---- | :---- | :---- | :---- |
| **STRONG BULL** | trend\_strength \> Thresh\_Strong\_Bull | Run Strong\_Bull\_Logic | (TQQQ, QQQ, or CASH) |
| **MODERATE BULL** | Thresh\_Mod\_Bull \< trend \<= Thresh\_Strong\_Bull | Run Moderate\_Bull\_Logic | (QQQ or CASH) |
| **CHOP / NEUTRAL** | Thresh\_Mod\_Bear \<= trend \<= Thresh\_Mod\_Bull | (Hold) | **CASH** |
| **BEAR** | trend\_strength \< Thresh\_Mod\_Bear | Run Bear\_Logic | (SQQQ or CASH) |

### **Sub-Strategy Logic Definitions**

#### **Strong\_Bull\_Logic**

* **Parameters:** Uses Params\_Strong\_Bull set.  
* **Logic:**  
  * IF QQQ\_Price \< EMA\_Trend\_SB \-\> **Target: CASH**  
  * IF QQQ\_Price \> EMA\_Trend\_SB AND MACD\_SB \> Signal\_SB \-\> **Target: TQQQ**  
  * IF QQQ\_Price \> EMA\_Trend\_SB AND MACD\_SB \< Signal\_SB \-\> **Target: QQQ**

#### **Moderate\_Bull\_Logic**

* **Parameters:** Uses Params\_Moderate\_Bull set.  
* **Logic (More Cautious \- No 3x Leverage):**  
  * IF QQQ\_Price \< EMA\_Trend\_MB \-\> **Target: CASH**  
  * IF QQQ\_Price \> EMA\_Trend\_MB AND MACD\_MB \> Signal\_MB \-\> **Target: QQQ**  
  * IF QQQ\_Price \> EMA\_Trend\_MB AND MACD\_MB \< Signal\_MB \-\> **Target: CASH**

#### **Bear\_Logic**

* **Parameters:** Uses Params\_Bear set.  
* **Logic (Inverted):**  
  * IF QQQ\_Price \> EMA\_Trend\_B \-\> **Target: CASH**  
  * IF QQQ\_Price \< EMA\_Trend\_B AND MACD\_B \< Signal\_B \-\> **Target: SQQQ**  
  * IF QQQ\_Price \< EMA\_Trend\_B AND MACD\_B \> Signal\_B \-\> **Target: CASH**

## **5\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the final Target\_Vehicle from the hierarchical logic above.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings** at the Open.  
3. Execute the new regime's action:

#### **If Target\_Vehicle is TQQQ (Regime: STRONG BULL):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Leveraged  
* **Dollar\_Risk\_Per\_Share:** TQQQ\_ATR\[today\] \* ATR\_Stop\_Multiplier  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is SQQQ (Regime: BEAR):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Leveraged  
* **Dollar\_Risk\_Per\_Share:** SQQQ\_ATR\[today\] \* ATR\_Stop\_Multiplier  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is QQQ (Regime: STRONG or MODERATE BULL):**

* **Action:** Execute a flat allocation.  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_Unleveraged  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Open\_Price  
* **Stop-Loss:** None. This position is managed by the regime filters.

#### **If Target\_Vehicle is CASH (Regime: CHOP or logic-driven):**

* **Action:** Hold 100% Cash.

### **B. Stop-Loss Management (TQQQ & SQQQ Only):**

* The ATR\_Stop\_Multiplier stop is a **hard stop**. If hit, liquidate the leveraged position and hold CASH for the remainder of the day.  
* The system will re-evaluate for a new entry at the close.

## **6\. Suggested Parameter Sweep for Robustness Test (WFO)**

This strategy has many "degrees of freedom." The goal is to optimize the parameter *sets* for each regime independently, then optimize the Kalman filter to switch between them.

* **Kalman Regime Filter:**  
  * measurement\_noise: \[2000.0, 5000.0, 10000.0\]  
  * osc\_smoothness: \[15, 20, 30\]  
  * strength\_smoothness: \[15, 20, 30\]  
* **Kalman Thresholds:**  
  * Thresh\_Strong\_Bull: \[60, 70, 80\]  
  * Thresh\_Moderate\_Bull: \[15, 20, 30\]  
  * Thresh\_Moderate\_Bear: \[-15, \-20, \-30\]  
* **Adaptive Parameter Sets (Optimize one set at a time):**  
  * Params\_Strong\_Bull Set:  
    * EMA\_Trend\_SB: \[75, 100, 125\]  
    * MACD\_fast\_SB: \[12, 20\], MACD\_slow\_SB: \[26, 50\], MACD\_signal\_SB: \[9\]  
  * Params\_Moderate\_Bull Set:  
    * EMA\_Trend\_MB: \[100, 150, 200\]  
    * MACD\_fast\_MB: \[12, 20\], MACD\_slow\_MB: \[26, 50\], MACD\_signal\_MB: \[9, 12\]  
  * Params\_Bear Set:  
    * EMA\_Trend\_B: \[75, 100, 125\]  
    * MACD\_fast\_B: \[12, 20\], MACD\_slow\_B: \[26, 50\], MACD\_signal\_B: \[9\]  
* **Risk & Sizing:**  
  * ATR\_Stop\_Multiplier: \[2.0, 2.5, 3.0\]  
  * Risk\_Leveraged: \[0.015, 0.02, 0.025\]  
  * Allocation\_Unleveraged: \[0.6, 0.8, 1.0\]