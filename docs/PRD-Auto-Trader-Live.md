# **Product Requirements Document: Auto-Trader v3.5b (Live)**

**Version:** 1.0
**Status:** Draft
**Platform:** Schwab-py (Thinkorswim)
**Target Env:** Paper Money (Incubation)

-----

### **1. Objective**

To automate the execution of the **Hierarchical Adaptive v3.5b** strategy, replicating the "Market-On-Close" (MOC) backtest performance in a live environment by synthesizing daily signals at **15:55 EST**.

-----

### **2. Strategy Logic Specification (The "Titan" Config)**

The system must implement the exact parameters validated in the "Run 1" Backtest.

  * **Universe:** `QQQ` (Signal), `TQQQ` (Bull), `TLT` (Bond Signal), `TMF` (Bull Bond), `TMV` (Bear Bond).
  * **Trend Engine:**
      * Equity: SMA 40 (Fast) vs SMA 140 (Slow).
      * Bond: SMA 20 (Fast) vs SMA 60 (Slow).
      * Kalman: Standard v3.5 velocity model.
  * **Volatility Engine:**
      * Metric: 21-day Realized Volatility vs 126-day Baseline.
      * Z-Score Gates: Upper `1.0`, Lower `0.2`.
      * Vol Crush: `-0.15` (15% drop in 5 days).
  * **Allocation Matrix:**
      * Leverage Scalar: **1.0** (Safety First).
      * Inverse Hedge (PSQ): **False**.
      * Safe Haven Module: **Active** (Max Bond Weight 40%).

-----

### **3. Execution Architecture**

The system operates on a **Scheduled Cron** basis, not an event stream.

#### **3.1 The "3:55 Protocol"**

To solve the look-ahead bias, the system operates 5 minutes before the market closes.

  * **Trigger Time:** Trading Days @ **15:50 EST**.
  * **Logic Window:** 15:50 - 15:55 EST.
  * **Execution Time:** 15:55:00 EST.

#### **3.2 The "Synthetic Daily Bar"**

The strategy requires a "Daily Close" to calculate indicators, but the market hasn't closed yet.

  * **Requirement:** System must fetch the *current* price at 15:51.
  * **Transformation:** This price is appended to the `N-1` historical daily bars to create a temporary `N` size dataset.
  * **Assumption:** The price at 15:55 is statistically statistically significant proxy for the 16:00 Close.

-----

### **4. Functional Requirements (FR)**

#### **FR-1: Authentication & Session Management**

  * **Library:** `schwab-py`.
  * **Requirement:** System must handle OAuth2 token refresh automatically.
  * **Failure Mode:** If auth fails at 15:50, trigger immediate SMS/Email alert (Critical Failure).

#### **FR-2: Data Ingestion (Split-Aware)**

  * **Source:** Schwab API (Price History & Quotes).
  * **Requirement:** Fetch last 250 daily candles for QQQ and TLT.
  * **Validation:** Check for unadjusted splits.
      * *Logic:* If `Close[t] / Close[t-1] < 0.6` (40% drop) without corresponding market crash, flag as Data Error and **ABORT**.

#### **FR-3: Logic Engine**

  * **Input:** Historical DataFrames + Current Quote + Account Equity.
  * **Process:**
    1.  Calc Z-Score & Trend State.
    2.  Determine Target Cell (1-6).
    3.  Run Safe Haven Selector (if Cell 4/6).
    4.  Output `Target_Weights` (e.g., `{'QQQ': 0.5, 'TMV': 0.2, 'CASH': 0.3}`).

#### **FR-4: Order Management (The Diff Engine)**

  * **Logic:** Compare `Target_Allocation` vs `Current_Positions`.
  * **Rebalance Threshold:** **5%**.
      * *Example:* If Target is 20% TQQQ and Current is 18% TQQQ, Diff = 2%. **Do Not Trade.**
      * *Reason:* Prevents churning on noise.
  * **Order Type:** `MARKET` (Since execution is immediate at 15:55).
  * **Sequence:** Sell orders first (raise cash), then Buy orders.

#### **FR-5: Safety Guardrails**

  * **Wash Sale Prevention:** (Optional for Paper, Critical for Taxable). Logic to check if a ticker was sold at a loss in the last 30 days.
  * **Max Order Size:** Hard cap order value at 95% of `Buying_Power` (leave buffer for fluctuations).

-----

### **5. Data Structures**

#### **A. State File (`state.json`)**

Persist the Hysteresis state between days.

```json
{
  "last_run": "2025-11-22",
  "vol_state": 0,
  "current_positions": {"TQQQ": 150, "Cash": 4000}
}
```

#### **B. Trade Log (`live_trades.csv`)**

Mirror the backtest log format for comparison.

```csv
Date, Time, Ticker, Action, Qty, Price, Reason (Z-Score, Trend)
```

-----

### **6. Workflow Diagram**

1.  **15:50** -\> Wake Up & Auth.
2.  **15:51** -\> Fetch History (QQQ, TLT).
3.  **15:51** -\> Validation Check (Data Integrity).
4.  **15:52** -\> Logic Calculation (v3.5b).
5.  **15:53** -\> Fetch Account Positions & Equity.
6.  **15:54** -\> Calculate `Diff` (Target - Current).
7.  **15:55** -\> **EXECUTE ORDERS**.
8.  **15:56** -\> Write Logs & Sleep.

-----

### **7. Success Criteria (Paper Trading Phase)**

The implementation is considered "Production Ready" only when:

1.  **Uptime:** Script runs for 10 consecutive days without Auth/API errors.
2.  **Fidelity:** Real-time execution prices match the 4:00 PM Close within **0.2%**.
3.  **Logic Match:** The live decision matches the Backtest Re-Run (running the backtest on the same day's data) 100% of the time.

### **8. Next Steps**

1.  **API Setup:** Create your Schwab Developer App and get Key/Secret.
2.  **Token Script:** Write a standalone script just to authenticate and fetch a quote (Hello World).
3.  **Logic Port:** Copy the `Strategy` class from your backtest and wrap it in the `LiveTrader` shell.

This document is your roadmap. You can now write the code module by module.