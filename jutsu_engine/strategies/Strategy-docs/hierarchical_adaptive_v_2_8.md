# Hierarchical Adaptive v2.8: Signed Long/Short Kalman Overlay for QQQ / TQQQ / SQQQ

## 1. Strategy Overview

**Hierarchical Adaptive v2.8** is a signed, long/short Kalman-driven overlay on QQQ implemented via **QQQ, TQQQ, and SQQQ**.

Relative to v2.5, v2.8:

- Preserves the **QQQ+ overlay character** (long bias around 1.0× net beta).
- Introduces a **signed trend layer** so strong downtrends can reduce exposure below 1.0 and occasionally below 0.
- Uses a **two-parameter floor system**:
  - **E_anchor**: positive defensive anchor used by the drawdown governor.
  - **E_short**: global lower bound (possibly negative) enabling controlled SQQQ usage.
- Maintains **volatility, VIX and drawdown modulators** to shape exposure rather than hard on/off regime switches.

High‑level behaviour:

- In strong persistent bull regimes: **1.1–1.8× net long** via QQQ + TQQQ.
- In neutral / choppy regimes: **~0.8–1.2×** net exposure, with preference for mild de‑risking.
- In strong persistent bear regimes: **0.3–0.9×** or occasionally **mild net short (down to E_short)** via SQQQ, bounded and rare.

The long‑run target is to achieve **CAGR > QQQ** with **max drawdown in the QQQ range** (~–35%) and higher Sharpe / Calmar.

---

## 2. Design Goals

### 2.1 Return Objective

- **Primary objective:** Maximize CAGR vs buy‑and‑hold QQQ over multi‑decade horizons.
- The strategy remains structurally long‑biased but allows:
  - Leveraged long in strong uptrends.
  - De‑risking (and occasionally mild short) in strong downtrends.

### 2.2 Risk & Drawdown Constraints

- Accept **QQQ‑like max drawdown** (≈ –35%) as an upper bound; avoid materially worse outcomes.
- Maintain realized volatility roughly in **1.0–1.5× QQQ** range.
- Use **volatility, VIX, and drawdown governors** to compress exposure in stressed environments.

### 2.3 Behavioural Profile

- Feels like a **“smarter QQQ+ core”**:
  - Adds upside through modest, trend‑aligned leverage.
  - Trims risk in choppy/high‑vol regimes.
  - Employs SQQQ only **occasionally and in a bounded way** when downtrends are strong and confirmed.

---

## 3. Conceptual Changes from v2.5

v2.8 addresses a key limitation in v2.5: with the previous parameter ranges and structure, **net exposure E_t was effectively constrained to be positive**, making SQQQ practically unreachable.

v2.8 introduces three core changes:

1. **Signed trend layer**
   - Trend is now explicitly **signed**, so strong negative regimes can yield **E_trend < 1 and potentially < 0**, enabling true defensive and mild short exposure.

2. **Two‑parameter floor system**
   - Introduces **E_anchor** (defensive positive anchor) and **E_short** (global lower bound) instead of a single E_min:
     - Drawdown governor pulls exposure toward **E_anchor** in deep DD.
     - Final clamp uses **E_short** as the lower bound, allowing **E_t < 0** when trend warrants.

3. **Stronger short‑side slope**
   - The negative trend slope **k_short** is allowed to exceed 1.0, so strong downtrends can drive **E_trend below zero** before modulators and clipping.

---

## 4. Architecture & Filter Hierarchy

### 4.1 Tier 1 – Kalman Trend Engine (Signed)

The Kalman filter operates on **QQQ** (e.g. using price and/or volume) and produces two outputs per bar:

- **Oscillator**: signed short‑term component (captures direction).
- **Strength**: non‑negative magnitude of the underlying trend.

Define a **signed trend strength**:

- Let `osc_t` = oscillator at time t.
- Let `strength_t` = non‑negative strength.

Then:

- `sign_t = +1` if `osc_t ≥ 0`, else `–1`.
- `trend_signed_t = sign_t × strength_t`.

This `trend_signed_t` is then normalized:

\[
T^{norm}_t = \text{clip}\left( \frac{trend\_signed_t}{T_{max}}, -1, +1 \right)
\]

Typical T_max range: **50–60**.

### 4.2 Tier 2 – Signed Trend & Asymmetric Scaling

Introduce a long‑bias baseline **E_bias ≈ 1.0** and asymmetric slopes:

- \(k_{long} > 0\) for \(T^{norm}_t \ge 0\).
- \(k_{short} > 0\) for \(T^{norm}_t < 0\), with **k_short ≥ k_long**.

Trend‑based exposure:

\[
E^{trend}_t =
\begin{cases}
E_{bias} + k_{long} \cdot T^{norm}_t & T^{norm}_t \ge 0 \\
E_{bias} + k_{short} \cdot T^{norm}_t & T^{norm}_t < 0
\end{cases}
\]

Recommended ranges:

- \(E_{bias} = 1.0\) (fixed long‑only baseline).
- \(k_{long} \in [0.5, 0.8]\) (e.g. 0.7).
- \(k_{short} \in [0.8, 1.2]\).

Implications (for \(T^{norm} \in [-1, 1]\)):

- Strong bull (\(T^{norm} = +1\)): \(E^{trend} \approx 1.5–1.8\).
- Neutral (\(T^{norm} \approx 0\)): \(E^{trend} \approx 1.0\).
- Strong bear (\(T^{norm} = -1\)): \(E^{trend} \approx 1 - k_{short}\), potentially **negative** when \(k_{short} > 1\).

### 4.3 Tier 3 – Volatility Modulator

Inputs:

- Realized volatility \(\sigma^{real}_t\): annualized stdev of log returns over a rolling window (e.g. 20–60 days).
- Long‑run baseline volatility \(\sigma_{base}\) for QQQ.
- Target multiplier \(\lambda_{vol}\): e.g. 0.8–1.0.

Target volatility:

\[
\sigma^{target} = \lambda_{vol} \cdot \sigma_{base}
\]

Volatility scaler:

\[
S^{vol}_t = \text{clip}\left( \frac{\sigma^{target}}{\sigma^{real}_t}, S^{min}_{vol}, S^{max}_{vol} \right)
\]

Typical:

- \(S^{min}_{vol} = 0.5\)
- \(S^{max}_{vol} = 1.5\)

Apply vol scaler only to deviations from 1.0:

\[
E^{vol}_t = 1.0 + (E^{trend}_t - 1.0) \cdot S^{vol}_t
\]

This compresses leverage (both long and short) in high‑vol regimes and allows larger deviations from 1.0 in low‑vol regimes.

### 4.4 Tier 4 – VIX Modulator

Inputs:

- Spot VIX: \(VIX_t\).
- Smoothed VIX: \(VIX^{EMA}_t\) (e.g. 50‑day EMA).

Define VIX ratio:

\[
R^{VIX}_t = \frac{VIX_t}{VIX^{EMA}_t}
\]

VIX penalty factor:

\[
P^{VIX}_t =
\begin{cases}
1 & R^{VIX}_t \le 1.0 \\
\dfrac{1}{1 + \alpha_{VIX}(R^{VIX}_t - 1)} & R^{VIX}_t > 1.0
\end{cases}
\]

Typical \(\alpha_{VIX}\) range: **1.5–3.0**.

Apply VIX penalty to deviations from 1.0:

\[
E^{vol+VIX}_t = 1.0 + (E^{vol}_t - 1.0) \cdot P^{VIX}_t
\]

High VIX relative to its EMA compresses both long and short extremes back toward 1.0, unless trend is exceptionally strong.

### 4.5 Tier 5 – Drawdown Governor with Defensive Anchor

Let \(DD_t\) be the current peak‑to‑trough drawdown (0–1).

Parameters:

- \(DD_{soft}\): start de‑risking (e.g. 0.10 = 10%).
- \(DD_{hard}\): maximum de‑risking (e.g. 0.25 = 25%).
- \(p_{min}\): minimum compression factor (e.g. 0.0–0.3).
- **E_anchor**: positive defensive anchor (e.g. 0.6–0.8).

Drawdown compression factor:

\[
P^{DD}_t =
\begin{cases}
1 & DD_t \le DD_{soft} \\
\text{linear from } 1 \text{ to } p_{min} & DD_{soft} < DD_t < DD_{hard} \\
p_{min} & DD_t \ge DD_{hard}
\end{cases}
\]

Drawdown‑adjusted exposure:

\[
E^{DD}_t = E_{anchor} + (E^{vol+VIX}_t - E_{anchor}) \cdot P^{DD}_t
\]

Interpretation:

- Low DD → \(P^{DD} \approx 1\) → \(E^{DD} \approx E^{vol+VIX}\) (trend‑driven).
- High DD → \(P^{DD} \to p_{min}\) → \(E^{DD} \to E_{anchor}\) (return to safe positive exposure).

This allows **short exposure in downtrends** when DD is modest, but **prevents deep drawdowns from forcing the system further short**; instead, it returns to a stable positive floor.

### 4.6 Tier 6 – Final Exposure Bounds

Let **E_short** and **E_max** be global exposure bounds:

- \(E_{short} < 0\): negative floor (e.g. –0.2 to –0.3).
- \(E_{max} > 1\): upper leverage bound (e.g. 1.5–1.8).

Final net exposure:

\[
E_t = \text{clip}(E^{DD}_t, E_{short}, E_{max})
\]

In typical configurations, \(E_t \in [-0.3, 1.8]\).

---

## 5. Exposure Calculation Summary

Per bar t:

1. Compute **trend_signed_t** from Kalman outputs.
2. Normalize to **T_norm_t ∈ [-1, 1]**.
3. Compute **E_trend_t** using \(E_{bias}, k_{long}, k_{short}\).
4. Apply realized vol scaler → **E_vol_t**.
5. Apply VIX compression → **E_vol+VIX_t**.
6. Apply drawdown governor toward **E_anchor** → **E_DD_t**.
7. Clip to \([E_{short}, E_{max}]\) → **E_t**.

**E_t** is the **target net QQQ exposure** implemented via QQQ, TQQQ, SQQQ, and cash.

---

## 6. Position Mapping: QQQ / TQQQ / SQQQ / Cash

We map **E_t** to portfolio weights:

- \(w_{QQQ,t}\): weight in QQQ.
- \(w_{TQQQ,t}\): weight in TQQQ.
- \(w_{SQQQ,t}\): weight in SQQQ (inverse, ~3× short QQQ).
- \(w_{cash,t}\): cash.

Constraints:

- \(w_{QQQ,t} + w_{TQQQ,t} + w_{SQQQ,t} + w_{cash,t} = 1\).
- \(w_{TQQQ,t}, w_{SQQQ,t}, w_{cash,t} \ge 0\).
- **SQQQ cap:** \(w_{SQQQ,t} \le w^{max}_{SQQQ}\) (e.g. 0.2–0.25).

Effective net QQQ exposure:

\[
E_t \approx 1 \cdot w_{QQQ,t} + 3 \cdot w_{TQQQ,t} - 3 \cdot w_{SQQQ,t}
\]

### 6.1 Long‑Side Mapping (E_t ≥ 0)

For non‑negative exposures, use QQQ + TQQQ + cash only (no SQQQ):

1. **Sub‑QQQ (0 ≤ E_t ≤ 1):**

- \(w_{TQQQ,t} = 0\).
- \(w_{QQQ,t} = E_t\).
- \(w_{cash,t} = 1 - E_t\).
- \(w_{SQQQ,t} = 0\).

2. **Levered long (E_t > 1):**

Solve:

- \(w_{QQQ,t} + w_{TQQQ,t} = 1\).
- \(1 \cdot w_{QQQ,t} + 3 \cdot w_{TQQQ,t} = E_t\).

This yields:

\[
w_{TQQQ,t} = \frac{E_t - 1}{2}, \quad w_{QQQ,t} = 1 - w_{TQQQ,t}, \quad w_{cash,t} = 0, \quad w_{SQQQ,t} = 0
\]

### 6.2 Short / Hedge Mapping (E_t < 0)

For negative exposures, use SQQQ + cash only (simple version):

- For \(E_{short} \le E_t < 0\):

\[
w_{SQQQ,t} = \min\left( \frac{-E_t}{3}, w^{max}_{SQQQ} \right), \quad w_{cash,t} = 1 - w_{SQQQ,t}
\]

and:

\[
w_{QQQ,t} = 0, \quad w_{TQQQ,t} = 0
\]

Given typical \(E_{short} \in [-0.3, 0]\) and \(w^{max}_{SQQQ} \in [0.2, 0.25]\), this yields **mild net short** exposures at most:

- Max net short \(\approx -3 \cdot w^{max}_{SQQQ} \in [-0.75, -0.6]\).

Optionally, for \(E_t \ll -1\) (if ever allowed by configuration), one could use QQQ + SQQQ pair trades to fully deploy capital while maintaining the desired net short; in v2.8, typical parameter choices **avoid E_t ≤ -1** altogether.

---

## 7. Risk Management & Constraints

### 7.1 Portfolio‑Level Controls

- **Exposure band:** enforce \(E_t \in [E_{short}, E_{max}]\).
- **SQQQ cap:** \(w_{SQQQ,t} \le w^{max}_{SQQQ}\) to bound short convexity.
- **Drawdown governor:** pulls exposure back toward \(E_{anchor}\) as DD grows, preventing deep drawdowns from forcing ever more extreme positions.

### 7.2 Instrument‑Level Considerations

- TQQQ and SQQQ both suffer from **volatility decay**; they are used only as **bounded overlays** (typical \(w_{TQQQ}\) or \(w_{SQQQ}\) ≤ 25%).
- SQQQ usage is intended to be **episodic**, not persistent: it should occur only in strong, confirmed downtrends.

### 7.3 Rebalancing Logic

- Compute target weights daily.
- Rebalance only when deviations exceed a small threshold (e.g. |Δw| ≥ 2–3% per symbol) and implied trade sizes are meaningful.
- This limits turnover while keeping realized exposure close to target.

---

## 8. Parameter Summary (Initial Defaults & Ranges)

### 8.1 Kalman Trend Engine

- `process_noise_1`: 0.01 (fixed).
- `process_noise_2`: 0.01 (fixed).
- `measurement_noise`: 2000–3000 (smoother is generally better).
- `osc_smoothness`: 10–20.
- `strength_smoothness`: 10–20.
- `T_max`: 50–60 (50 recommended baseline).

### 8.2 Trend Exposure

- `E_bias`: 1.0 (fixed).
- `k_long`: 0.5–0.8 (0.7 baseline).
- `k_short`: 0.8–1.2 (1.0–1.2 enables negative E_trend in strong bears).
- `E_short`: –0.3 to 0.0 (floor for net short).
- `E_max`: 1.5–1.8.

### 8.3 Volatility Modulator

- `sigma_lookback`: 20–60 days.
- `sigma_target_multiplier` (\(\lambda_{vol}\)): 0.8–1.0.
- `S_vol_min`: 0.5.
- `S_vol_max`: 1.5.

### 8.4 VIX Modulator

- `vix_ema_period`: 50.
- `alpha_VIX`: 1.5–3.0 (2.0–3.0 often works best).

### 8.5 Drawdown Governor

- `DD_soft`: 0.10 (10%).
- `DD_hard`: 0.20–0.25 (20–25%).
- `p_min`: 0.0–0.3.
- `E_anchor`: 0.6–0.8.

### 8.6 SQQQ Cap

- `w_SQQQ_max`: 0.2–0.25.

### 8.7 Symbols

- `signal_symbol`: QQQ.
- `core_long_symbol`: QQQ.
- `leveraged_long_symbol`: TQQQ.
- `leveraged_short_symbol`: SQQQ.
- `vix_symbol`: VIX.

---

## 9. Pseudo‑Code Walkthrough (v2.8)

Per daily bar t:

1. **Kalman update**
   - Feed QQQ OHLCV to Kalman engine.
   - Receive `(osc_t, strength_t)`.

2. **Signed trend normalization**
   - `sign_t = +1 if osc_t >= 0 else -1`.
   - `trend_signed_t = strength_t * sign_t`.
   - `T_norm_t = clip(trend_signed_t / T_max, -1, +1)`.

3. **Trend exposure**
   - If `T_norm_t >= 0`:
     - `E_trend_t = E_bias + k_long * T_norm_t`.
   - Else:
     - `E_trend_t = E_bias + k_short * T_norm_t`.

4. **Realized vol scaler**
   - `sigma_real_t = realized_volatility(QQQ_close, sigma_lookback)`.
   - `S_vol_t = clip(sigma_target / sigma_real_t, S_vol_min, S_vol_max)`.
   - `E_vol_t = 1.0 + (E_trend_t - 1.0) * S_vol_t`.

5. **VIX compression**
   - Compute `VIX_t`, `VIX_EMA_t`, `R_VIX_t = VIX_t / VIX_EMA_t`.
   - `P_VIX_t = 1 if R_VIX_t <= 1 else 1 / (1 + alpha_VIX * (R_VIX_t - 1))`.
   - `E_volVIX_t = 1.0 + (E_vol_t - 1.0) * P_VIX_t`.

6. **Drawdown governor toward E_anchor**
   - Compute current drawdown `DD_t` from equity curve.
   - Compute `P_DD_t` via DD_soft, DD_hard, p_min.
   - `E_DD_t = E_anchor + (E_volVIX_t - E_anchor) * P_DD_t`.

7. **Clip to exposure band**
   - `E_t = clip(E_DD_t, E_short, E_max)`.

8. **Map to QQQ/TQQQ/SQQQ/cash**
   - If `E_t >= 0`:
     - If `E_t <= 1.0`:
       - `w_QQQ = E_t`, `w_TQQQ = 0`, `w_SQQQ = 0`, `w_cash = 1 - E_t`.
     - Else:
       - `w_TQQQ = (E_t - 1.0) / 2.0`.
       - `w_QQQ = 1.0 - w_TQQQ`.
       - `w_SQQQ = 0`, `w_cash = 0`.
   - Else (`E_t < 0`):
     - `w_SQQQ = min(-E_t / 3.0, w_SQQQ_max)`.
     - `w_cash = 1 - w_SQQQ`.
     - `w_QQQ = 0`, `w_TQQQ = 0`.

9. **Apply rebalance threshold**
   - Compare current weights vs target weights.
   - If any |Δw| > `rebalance_threshold` and trade size is material: generate orders.

10. **Log diagnostics**
    - Log `trend_signed_t`, `T_norm_t`, `E_t`, weights, `sigma_real_t`, `R_VIX_t`, `DD_t`, etc. for research.

---

## 10. Backtest & Evaluation Plan

1. **Data & Horizon**
   - QQQ, TQQQ, SQQQ, VIX daily data from 2010‑03‑01 to present.

2. **Benchmarks**
   - Buy‑and‑hold QQQ.
   - Best long‑only v2.6 configuration (e.g. Run 268) as a control.

3. **Metrics**
   - CAGR, annualized volatility, Sharpe, Sortino.
   - Max drawdown, Calmar.
   - Beta and correlation vs QQQ.
   - Time in net short (E_t < 0), time with E_t > 1.2, etc.

4. **Regime‑by‑regime analysis**
   - Focus on years: 2013 (clean bull), 2018 (chop), 2020 (crash + rebound), 2022 (bear).
   - Examine exposure, SQQQ usage, and P&L per regime.

5. **Robustness checks**
   - Walk‑forward studies (early vs later years).
   - Sensitivity analysis on \(k_{short}, E_{anchor}, E_{short}, w^{max}_{SQQQ}\).

---

## 11. Open Questions / Future Extensions

- Should \(E_{bias}\) be allowed to drift (e.g. slightly < 1 after very long drawdowns)?
- Would a multi‑timeframe Kalman signal (e.g. weekly + daily) improve downtrend detection for SQQQ usage?
- Is there value in **pair‑trade hedges** (QQQ + SQQQ mix) in prolonged sideways‑down markets, instead of pure SQQQ + cash?
- Once the ETF overlay is stable, could **options overlays** (e.g. protective puts, covered calls) further improve tail protection or yield without sacrificing CAGR?

