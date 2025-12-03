# Hierarchical Adaptive v3.0: Regime‑Grid Allocator for QQQ / TQQQ / SQQQ

## 1. Strategy Overview

**Hierarchical Adaptive v3.0** is a regime‑driven allocator over **QQQ, TQQQ, SQQQ, and cash**. It builds on v2.5 / v2.8 but changes the mindset from:

> *"Continuous exposure as a smooth function of a single trend signal"*

to:

> *"Explicit regime buckets (trend × volatility) with a separate allocation rule per regime"*

The key shift is:

- We stop treating the **Kalman trend sign** as the sole bull/bear switch.
- We acknowledge that **QQQ has a strong long‑term positive drift** and that naïve “bear” classifications often occur in environments that are actually **positive or flat for QQQ**.
- We deliberately build **asymmetry** into the design:
  - Aggressive use of **TQQQ** in clear bull regimes.
  - Conservative, mostly **cash / low exposure** in noisy or pseudo‑bear regimes.
  - **Short exposure (SQQQ)** is rare, tightly capped, and gated by **both fast and slow regime filters**.

The result is a strategy that aims to:

- Capture **significant upside** in true bull/low‑vol regimes.
- Maintain a **modest positive edge** in sideways conditions.
- Avoid the catastrophic behaviour seen in v2.x when the system acted on noisy “bear” signals.

---

## 2. Retrospective: What We Learned from v2.x

### 2.1 Where v2.x Performed Well

From extensive v2.5 / v2.6 / v2.8 backtests and grid searches:

- In **BullStrong + LowVol** and **BullStrong + MedVol** environments (as proxied by high positive Kalman trend and moderate volatility):
  - v2.8 **significantly outperformed QQQ**, sometimes adding +10–20% annualized on top of already strong QQQ returns.
  - Modest, trend‑aligned use of TQQQ was clearly beneficial.

- In many **Sideways** regimes:
  - v2.8 maintained a positive edge by staying modestly long and letting the Kalman trend tilt exposure.

These observations confirm that the **core idea of a Kalman‑driven exposure overlay** is sound, particularly on the **long side**.

### 2.2 Where v2.x Failed

The same analyses also showed systematic weaknesses:

1. **Bear‑classified regimes underperformed badly.**
   - When we grouped days as `T_norm < 0` ("bear" according to the Kalman trend), QQQ often still had **positive drift**.
   - In these “bear” buckets, the strategy frequently:
     - Reduced exposure too much (losing QQQ drift), or
     - In extreme tests, went **leveraged short** and suffered large losses.

2. **Symmetric ±3× leverage was not viable.**
   - In the extreme v2.8 experiment where strong bull → +3× and strong bear → −3×, the strategy:
     - Dramatically underperformed QQQ.
     - Suffered **worse drawdowns and Sharpe**.
   - The short side had **no robust edge**; false bear signals and secular QQQ drift dominated.

3. **Short exposure (SQQQ) added little value in realistic v2.8 settings.**
   - Even with negative exposure enabled, SQQQ usage was rare and small.
   - Performance differences across `E_short` and `w_SQQQ_max` combinations were negligible within v2.8’s calibrated region.

### 2.3 Conclusions from v2.x

The empirical takeaway is:

- The Kalman trend engine is a **useful fast/medium‑term trend indicator**, especially for deciding when to lean into TQQQ.
- It is **not a reliable standalone bear regime classifier** in a secularly rising asset like QQQ.
- Symmetric treatment of bull and bear (e.g., ±3×) is inappropriate; the **upside drift is persistent**, while true sustained bear regimes are rare and noisy.

v3.0 therefore:

- Preserves the **strengths** of v2.x on the long side.
- Makes the regime logic **explicit** via a grid.
- Designs **asymmetric, conservative rules** for any short/defensive behaviour.

---

## 3. v3.0 Design Goals

### 3.1 Return & Risk Objectives

- Target **CAGR ≥ QQQ** over long horizons (e.g., 10–15+ years).
- Maintain **max drawdown in the QQQ range**, with a preference for equal or slightly better drawdown.
- Improve **risk‑adjusted returns** (Sharpe, Sortino, Calmar) relative to QQQ.

### 3.2 Behavioural Profile

- In **clear bull markets** (strong trend, low/medium vol):
  - Willing to run **elevated net exposure (>1×)**, with bounded TQQQ usage.
- In **sideways regimes**:
  - Maintain **modestly positive exposure**, accepting some noise but aiming for a small edge.
- In **apparent bear regimes**:
  - First goal: **avoid large losses**.
  - Prioritise **cash / low exposure**.
  - Only allow **small, tightly capped short exposure** when both fast and slow filters confirm a meaningful downtrend.

### 3.3 Architectural Principles

- **Separately model:**
  - **Fast / medium trend** (Kalman, like v2.x).
  - **Slow structural trend / regime** (e.g., long moving averages or cumulative drawdown).
  - **Volatility state** (realized vol tiers).
- Use an **explicit regime grid** (trend × vol) with a defined allocation policy per cell.
- Keep **short exposure optional and structurally asymmetric**.

---

## 4. Regime Framework

v3.0 uses a **3 × 3 regime grid**:

- **Trend axis (rows)**: {BullStrong, Sideways, BearStrong}
- **Volatility axis (columns)**: {LowVol, MedVol, HighVol}

### 4.1 Trend Regime (Row) Definition

We combine:

1. **Fast Kalman trend signal** `T_norm` (as in v2.x, clipped to [−1, 1]).
2. **Slow trend filter** `R_slow` (e.g., based on long moving averages).

Example implementation:

- Compute `T_norm` from Kalman oscillator and strength (v2.8 logic).
- Compute a slow trend indicator, for example:
  - `MA_fast` = 50‑day SMA of QQQ
  - `MA_slow` = 200‑day SMA of QQQ
  - `R_slow` = sign(MA_fast − MA_slow) and/or slope of MA_slow.

Trend regimes:

1. **BullStrong**
   - `T_norm` in the upper third of its historical distribution (e.g., > +T_hi), **and**
   - `R_slow` indicates uptrend (e.g., MA_fast > MA_slow, or MA_slow slope ≥ 0).

2. **BearStrong**
   - `T_norm` in the lower third (e.g., < −T_lo), **and**
   - `R_slow` indicates downtrend (e.g., MA_fast < MA_slow, or MA_slow slope < 0).

3. **Sideways**
   - All other cases.

This structure ensures that:

- Fast Kalman trend is used, but **bear classification is gated by a slow structural filter**.
- Many noisy, short‑lived dips with `T_norm < 0` but positive slow trend are treated as **Sideways**, not BearStrong.

### 4.2 Volatility Regime (Column) Definition

We use **realized volatility** and optionally VIX:

- `sigma_real` = annualized realized volatility over a rolling window (e.g., 20–40 days).
- Compute two thresholds from historical sigma_real distribution:
  - `σ_low` = 33rd percentile.
  - `σ_high` = 67th percentile.

Vol regimes:

1. **LowVol**: `sigma_real ≤ σ_low`
2. **MedVol**: `σ_low < sigma_real ≤ σ_high`
3. **HighVol**: `sigma_real > σ_high`

Optionally, incorporate VIX:

- If VIX ratio `R_VIX = VIX / EMA(VIX)` is very high (e.g., > 1.5), upgrade to **HighVol**, even if sigma_real is still moderate.

---

## 5. Regime → Exposure Map

For each cell (Trend, Vol), we specify:

- Target **net exposure range** `E_target` (in QQQ‑beta units).
- Permitted instruments and caps:
  - Max TQQQ weight.
  - Max SQQQ weight (if any).
  - Minimum cash fraction.

v3.0 is deliberately **asymmetric**:

- Aggressive leverage only in **BullStrong**.
- Short exposure only in **BearStrong + HighVol**, and even there, tightly capped.

### 5.1 BullStrong Row

1. **BullStrong–LowVol**
   - Rationale: Historically, strongest outperformance vs QQQ in v2.8.
   - Target net exposure: **1.5× to 2.2×**.
   - Implementation:
     - TQQQ allowed up to **60–70%** of portfolio.
     - Remaining in QQQ, little or no cash.
   - Example target mapping:
     - `w_TQQQ ≈ 0.6–0.7`, `w_QQQ ≈ 0.3–0.4`, `w_SQQQ ≈ 0`, `w_cash ≈ 0`.

2. **BullStrong–MedVol**
   - Rationale: Still favourable, but risk is higher.
   - Target net exposure: **1.2× to 1.6×**.
   - Implementation:
     - TQQQ allowed up to **40–50%**.
     - QQQ as core, minimal cash.
   - Example target mapping:
     - `w_TQQQ ≈ 0.3–0.4`, `w_QQQ ≈ 0.6–0.7`, `w_SQQQ = 0`, `w_cash ≈ 0`.

3. **BullStrong–HighVol**
   - Rationale: Positive trend, but fragility is high.
   - Target net exposure: **0.9× to 1.2×**.
   - Implementation:
     - TQQQ use is modest and conditional.
     - QQQ is dominant; some cash allowed.
   - Example target mapping:
     - `w_TQQQ ≈ 0.1–0.2`, `w_QQQ ≈ 0.6–0.8`, `w_cash ≈ 0–0.3`, `w_SQQQ = 0`.

### 5.2 Sideways Row

Sideways regimes cover mixed or weak trend states.

1. **Sideways–LowVol**
   - Rationale: QQQ often drifts sideways with occasional breakouts; v2.8 showed modest positive edge.
   - Target net exposure: **0.8× to 1.1×**.
   - Implementation:
     - Primarily QQQ.
     - TQQQ occasional and small (only when `T_norm` is slightly positive).
   - Example mapping:
     - `w_QQQ ≈ 0.8–1.0`, `w_TQQQ ≤ 0.2`, `w_cash ≈ 0–0.2`, `w_SQQQ = 0`.

2. **Sideways–MedVol**
   - Rationale: Choppier conditions; over‑trading leverage is dangerous.
   - Target net exposure: **0.7× to 1.0×**.
   - Implementation:
     - QQQ core.
     - Little or no TQQQ.
     - Some cash buffer.
   - Example mapping:
     - `w_QQQ ≈ 0.6–0.9`, `w_TQQQ ≤ 0.1`, `w_cash ≈ 0.1–0.4`, `w_SQQQ = 0`.

3. **Sideways–HighVol**
   - Rationale: High noise; drift may still be positive but risk of whipsaw is high.
   - Target net exposure: **0.5× to 0.8×**.
   - Implementation:
     - QQQ plus significant cash.
     - No TQQQ, no SQQQ.
   - Example mapping:
     - `w_QQQ ≈ 0.5–0.7`, `w_cash ≈ 0.3–0.5`, `w_TQQQ = 0`, `w_SQQQ = 0`.

### 5.3 BearStrong Row

BearStrong regimes are only recognised when **both** fast and slow filters align.

1. **BearStrong–LowVol**
   - Rationale: v2.x showed that many `T_norm < 0` + low vol situations are actually **good environments for QQQ**.
   - v3.0 therefore treats this as **"suspect bear"**.
   - Target net exposure: **0.4× to 0.8×**.
   - Implementation:
     - QQQ at reduced weight + cash.
     - No shorts.
   - Example mapping:
     - `w_QQQ ≈ 0.4–0.7`, `w_cash ≈ 0.3–0.6`, `w_TQQQ = 0`, `w_SQQQ = 0`.

2. **BearStrong–MedVol**
   - Rationale: Higher risk of drawdowns; QQQ may be flat or mildly negative.
   - Target net exposure: **0.2× to 0.6×**.
   - Implementation:
     - Majority cash.
     - QQQ as residual exposure.
     - Short side is still disabled by default.
   - Example mapping:
     - `w_QQQ ≈ 0.2–0.5`, `w_cash ≈ 0.5–0.8`, `w_TQQQ = 0`, `w_SQQQ = 0`.

3. **BearStrong–HighVol** (Optional Short Cell)

This is the only cell where **short exposure is permitted**, and even here, it is:

- **Tightly capped** (e.g., max net short −0.5× to −1.0×).
- **Gated** by additional conditions, for example:
  - QQQ price is in a drawdown > 20–25% from a 2‑year high, and
  - VIX ratio `R_VIX` is elevated (e.g., > 1.3–1.5).

Target net exposure:

- Base design: **0.0× to −0.5×** (mild net short at most).

Implementation:

- Primary allocation: **cash + small SQQQ + possibly a small QQQ hedge**.
- Example mapping (when short conditions are met):
  - `w_SQQQ ≈ 0.15–0.25` (net −0.45× to −0.75×),
  - `w_cash ≈ 0.75–0.85`,
  - `w_QQQ = 0`, `w_TQQQ = 0`.

Otherwise (if short gate not met), treat as **BearStrong–MedVol**.

---

## 6. Implementation Layers

v3.0 keeps the hierarchical structure but changes how each layer is used.

### 6.1 Fast Kalman Layer

- Same core Kalman engine as v2.8 for `oscillator` and `strength`.
- Compute `T_norm` as a signed, normalized trend measure.
- Use `T_norm`:
  - To classify **BullStrong / Sideways / BearStrong** (with slow filter).
  - To modulate **within‑cell** exposure (e.g., higher end of range when `T_norm` is at extremes).

### 6.2 Slow Structural Trend Filter

- Use a long moving average or equivalent (e.g., 200‑day SMA) and its slope.
- Gate BearStrong classification:
  - Only classify a day as **BearStrong** if `T_norm` is in the bottom tertile **and** slow trend is down.
  - Otherwise, treat negative `T_norm` as **Sideways**.

### 6.3 Volatility Engine

- Compute `sigma_real` and percentile thresholds `σ_low` and `σ_high`.
- Optionally incorporate VIX ratio to upgrade to HighVol.
- Feed Vol regime into the regime grid to select the appropriate column.

### 6.4 Allocation Engine

- Each day:
  1. Determine **TrendRegime ∈ {BullStrong, Sideways, BearStrong}`.
  2. Determine **VolRegime ∈ {LowVol, MedVol, HighVol}`.
  3. Look up the **allocation cell** (row, column).
  4. Within that cell, set target weights:
     - Use `T_norm` to choose where within the exposure band to sit.
     - Enforce instrument caps (TQQQ max, SQQQ max, min cash).

- Rebalance when weights deviate from targets beyond a threshold (e.g., 2–3%) or when the regime cell changes.

---

## 7. Parameter Summary (Initial Ranges)

These are starting ranges; calibration should be done by grid search and walk‑forward tests.

### 7.1 Kalman Trend

- As in v2.8, with tuning around the best v2.8 region:
  - `measurement_noise`: 2000–3000
  - `process_noise_1, process_noise_2`: 0.01
  - `osc_smoothness, strength_smoothness`: 10–20
  - `T_max`: 50–60

### 7.2 Slow Trend Filter

- `MA_fast`: 50 days (or 63 for quarterly)
- `MA_slow`: 200 days
- Slow trend up:
  - `MA_fast > MA_slow` and `slope(MA_slow) ≥ 0`
- Slow trend down:
  - `MA_fast < MA_slow` and `slope(MA_slow) < 0`

### 7.3 Volatility & VIX

- `sigma_lookback`: 20–40 days
- `σ_low`, `σ_high`: empirical 33rd and 67th percentiles of sigma_real
- `vix_ema_period`: 50 days
- `R_VIX_high`: 1.3–1.5 threshold for HighVol override

### 7.4 Exposure Bands & Caps

- BullStrong–LowVol: E_target ≈ 1.5–2.2, max `w_TQQQ` ≈ 0.7
- BullStrong–MedVol: E_target ≈ 1.2–1.6, max `w_TQQQ` ≈ 0.5
- BullStrong–HighVol: E_target ≈ 0.9–1.2, max `w_TQQQ` ≈ 0.2

- Sideways–LowVol: E_target ≈ 0.8–1.1
- Sideways–MedVol: E_target ≈ 0.7–1.0
- Sideways–HighVol: E_target ≈ 0.5–0.8

- BearStrong–LowVol: E_target ≈ 0.4–0.8
- BearStrong–MedVol: E_target ≈ 0.2–0.6
- BearStrong–HighVol: E_target ≈ 0.0 to −0.5 (only if short gate is met)

- `w_SQQQ_max` in BearStrong–HighVol: 0.15–0.25 (mild net short).

---

## 8. Backtesting & Evaluation Plan

1. **Horizon**:
   - At least 2010–present, using daily data for QQQ, TQQQ, SQQQ, and VIX.

2. **Benchmarks**:
   - Buy‑and‑hold QQQ.
   - Best v2.8 configuration from Phase‑2.

3. **Metrics**:
   - CAGR, annualized volatility, Sharpe, Sortino.
   - Max drawdown, Calmar.
   - Time spent in each regime cell; P&L contribution per cell.

4. **Regime Attribution**:
   - For each of the 3×3 cells, compute:
     - Number of days.
     - QQQ annualized return.
     - Strategy annualized return.
     - Contribution to total P&L.
   - Validate that:
     - BullStrong + Low/MedVol cells show **clear outperformance**.
     - Sideways cells show **moderate outperformance**.
     - BearStrong cells **no longer drive catastrophic underperformance**.

5. **Robustness Checks**:
   - Walk‑forward tests (e.g., recalibrate thresholds every few years and test on subsequent periods).
   - Sensitivity analysis on:
     - Trend tertile thresholds.
     - Vol tertile thresholds.
     - Short gate conditions.

---

## 9. Why This Direction Makes Sense

v3.0 is a direct response to empirical evidence from v2.x:

- We saw that a **single fast trend signal** is powerful for **modulating long exposure**, but unreliable as a **macro bear detector**.
- We confirmed that **QQQ’s secular drift is strongly upward**, making symmetric ±3× treatment dangerous.
- We identified that **most of the alpha in v2.8 comes from bull and sideways regimes**, while **most of the damage comes from self‑declared bear regimes**.

The v3.0 design therefore:

- Keeps the **Kalman engine** where it works best: scaling **long** exposure in clear bull states.
- Adds a **slow filter** to prevent spurious, short‑term noise from being treated as a structural bear market.
- Encodes an **explicit regime grid**, so that desired behaviour in each cell is clear, inspectable, and testable.
- Treats **short exposure as optional, bounded, and gated**, rather than as a symmetric counterpart to long leverage.

This combination respects the statistical reality of QQQ, leverages the strengths of your existing indicator, and focuses further research on a tractable, interpretable object: the **regime → allocation matrix**, which can be iteratively refined as more backtest evidence accumulates.

