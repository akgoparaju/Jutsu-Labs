# **Strategy Specification: Kalman Gearing (v1.0)**

## **1\. Core Components**

* **Strategy Name:** Kalman Gearing (v1.0)  
* **Initial Portfolio:** $100,000 USD  
* **Signal Assets:** QQQ (Daily)  
* **Trading Vehicles:** TQQQ, QQQ, SQQQ, CASH  
* **Commission Model:** $0.00 per trade  
* **Slippage Model:** 0.05% per trade  
* **Execution:** Signals calculated at **Close**, execution at **Next Day's Open**.

## **2\. Core Philosophy**

This strategy is a dynamic "gearing" model. It replaces traditional trend indicators (like EMAs or MACD) with a single, more advanced **Adaptive Kalman Filter Trend Strength Oscillator**.

The core philosophy is to match the portfolio's leverage (from \-3x to \+3x) to the **magnitude and direction** of the trend as identified by the Kalman filter. The oscillator's output (from \-100 to \+100) is divided into four distinct regimes, each with an optimal trading vehicle. The "dead zone" (neutral) defaults to CASH to avoid whipsaw and volatility drag, which is the primary risk in leveraged strategies.

## **3\. Indicator Parameters**

* **Kalman Filter Parameters (on QQQ):**  
  * model: VOLUME\_ADJUSTED (Adapts to QQQ volume)  
  * process\_noise\_1: 0.01 (To be optimized)  
  * process\_noise\_2: 0.01 (Fixed)  
  * measurement\_noise: 500.0 (To be optimized)  
  * osc\_smoothness: 10 (To be optimized)  
  * strength\_smoothness: 10 (To be optimized)  
* **Regime Threshold Parameters (To be optimized):**  
  * Thresh\_Strong\_Bull: 70 (Upper "gear-up" level for TQQQ)  
  * Thresh\_Moderate\_Bull: 20 (Lower "long" level for QQQ)  
  * Thresh\_Strong\_Bear: \-70 (Lower "gear-down" level for SQQQ)  
* **Risk & Sizing Parameters:**  
  * ATR\_Period: 14 (For TQQQ/SQQQ stop-loss)  
  * ATR\_Stop\_Multiplier: 3.0 (For TQQQ/SQQQ stop-loss)  
  * Risk\_Leveraged: 2.5% (Risk 2.5% of total equity on all TQQQ/SQQQ trades)  
  * Allocation\_Unleveraged: 80% (Allocate 80% of total equity to QQQ trades)

## **4\. Hierarchical Logic (Calculated at Day's Close)**

The logic is based on the single trend\_strength output from the Kalman filter.

| Regime | Conditions | Target Vehicle |
| :---- | :---- | :---- |
| **STRONG BULL** | trend\_strength \> Thresh\_Strong\_Bull | **TQQQ** |
| **MODERATE BULL** | Thresh\_Moderate\_Bull \< trend\_strength \<= Thresh\_Strong\_Bull | **QQQ (1x)** |
| **STRONG BEAR** | trend\_strength \< Thresh\_Strong\_Bear | **SQQQ** |
| **CHOP / NEUTRAL** | Thresh\_Strong\_Bear \<= trend\_strength \<= Thresh\_Moderate\_Bull | **CASH** |

**Rationale:** The system only applies leverage (TQQQ/SQQQ) when the Kalman filter indicates a high-conviction trend (e.g., \> \+70 or \< \-70). It holds a standard 1x position (QQQ) in a moderate uptrend. Most importantly, it holds CASH in the entire "chop" zone (e.g., between \-70 and \+20) to protect against noise and trendless decay.

## **5\. Trade Execution & Position Sizing Rules**

### **A. On any Signal Change:**

1. Determine the final Target\_Vehicle from the hierarchical logic above.  
2. If Target\_Vehicle is different from Current\_Position, **liquidate all current holdings** at the Open.  
3. Execute the new regime's action:

#### **If Target\_Vehicle is TQQQ (Regime: STRONG BULL):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Leveraged  
* **Dollar\_Risk\_Per\_Share:** TQQQ\_ATR  
* $$today$$  
* \* ATR\_Stop\_Multiplier  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is SQQQ (Regime: STRONG BEAR):**

* **Action:** Execute a risk-based trade.  
* **Total\_Dollar\_Risk:** Portfolio\_Equity \* Risk\_Leveraged  
* **Dollar\_Risk\_Per\_Share:** SQQQ\_ATR  
* $$today$$  
* \* ATR\_Stop\_Multiplier  
* **Shares\_To\_Buy:** Total\_Dollar\_Risk / Dollar\_Risk\_Per\_Share  
* **Stop-Loss:** Fill\_Price \- Dollar\_Risk\_Per\_Share

#### **If Target\_Vehicle is QQQ (Regime: MODERATE BULL):**

* **Action:** Execute a flat allocation.  
* **Dollars\_To\_Allocate:** Portfolio\_Equity \* Allocation\_Unleveraged  
* **Shares\_To\_Buy:** Dollars\_To\_Allocate / QQQ\_Open\_Price  
* **Stop-Loss:** None. This position is managed by the regime filters.

#### **If Target\_Vehicle is CASH (Regime: CHOP / NEUTRAL):**

* **Action:** Hold 100% Cash.

### **B. Stop-Loss Management (TQQQ & SQQQ Only):**

* The ATR\_Stop\_Multiplier stop is a **hard stop**. If hit, liquidate the leveraged position and hold CASH for the remainder of the day.  
* The system will re-evaluate for a new entry at the close.

## **6\. Suggested Parameter Sweep for Robustness Test (WFO)**

This sweep is designed to find a "parameter plateau" (a robust region) rather than a single "peak."

* **Kalman Core (Smoothness vs. Lag):**  
  * measurement\_noise: \[100.0, 500.0, 1000.0, 2000.0\]  
  * process\_noise\_1: \[0.001, 0.01, 0.1\]  
* **Kalman Smoothing (Oscillator Stability):**  
  * osc\_smoothness: \[5, 10, 15\]  
  * strength\_smoothness: \[5, 10, 15\]  
* **Regime Thresholds (The "Gears"):**  
  * Thresh\_Strong\_Bull: \[60, 70, 80\]  
  * Thresh\_Moderate\_Bull: \[10, 20, 30\]  
  * Thresh\_Strong\_Bear: \[-60, \-70, \-80\]  
* **Risk Management:**  
  * ATR\_Stop\_Multiplier: \[2.0, 2.5, 3.0\]  
  * Risk\_Leveraged: \[0.015, 0.02, 0.025\]  
* **Sizing:**  
  * Allocation\_Unleveraged: \[0.6, 0.8, 1.0\]  
  1. 