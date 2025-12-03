# Hierarchical Adaptive v2.5: Asymmetric Long/Short Kalman Overlay for QQQ / TQQQ / SQQQ

## 1. Strategy Overview

**Hierarchical Adaptive v2.5** is an asymmetric, Kalman‑driven long/short overlay on QQQ using **QQQ, TQQQ, and SQQQ**.

Relative to v2.0, v2.5:

- Explicitly targets **maximum long‑run return (CAGR)** while
- Constraining risk primarily through **drawdown and volatility controls**, not by staying near 1.0× exposure.
- Allows **exposure to drop below 1.0× QQQ** in bear regimes, and
- Introduces a **small, controlled SQQQ hedge overlay** to exploit strong downtrends and further manage risk.

High‑level behaviour:

- In strong bull regimes: run **1.1–1.8× net long** via QQQ + TQQQ.
- In choppy / neutral regimes: stay closer to **0.7–1.1×** net exposure.
- In strong bear regimes with elevated vol and drawdown: allow **net exposure to fall below 1.0** (down to a bounded **net short** or low‑beta state), using cash + SQQQ.

The **Adaptive Kalman Filter** remains the primary signal engine; volatility, VIX, and drawdown act as **modulators** that reshape exposure, not hard on/off switches.

---

## 2. Design Goals

### 2.1 Return Objective

- **Primary objective:** Maximize CAGR vs buy‑and‑hold QQQ over multi‑decade horizons.
- The system optimizes for **long‑run capital growth**, not a particular path smoothness, as long as drawdowns remain within acceptable structural limits.

### 2.2 Risk & Drawdown Constraints

- Target **max drawdown** substantially smaller than a naïve always‑levered posture (e.g., constant 1.5–2.0× QQQ).
- Keep realized volatility in a band of roughly **1.0–1.5× QQQ** depending on the regime.
- Use **explicit drawdown‑aware exposure compression** and bounded net short exposure via SQQQ to reduce tail risk.

### 2.3 Behavioural Profile

- Feels like a **“smart, opportunistic QQQ+”** strategy:
  - Aggressively long in clear uptrends.
  - Defensive and occasionally lightly short in structural downtrends.
  - Willing to tolerate some path volatility in exchange for materially higher long‑run growth.

---

## 3. Conceptual Changes from v2.0

v2.5 builds on v2.0 but introduces three key shifts:

1. **Drawdown governor anchored to E_min, not 1.0**
   - In v2.0, drawdown compression forced exposure back toward **1.0**, effectively “turning off leverage” but not allowing sub‑QQQ exposure unless the trend engine itself pushed below 1.0.
   - In v2.5, drawdown compression interpolates between **E_min** and the trend/vol/VIX‑driven exposure, meaning deep DD can yield **E_t < 1.0** (and eventually net short when combined with trend).

2. **Explicit long/short band**
   - v2.0: net exposure \(E_t\) was constrained to **[0.5, 1.3]**.
   - v2.5: \(E_t\) is allowed in a broader, asymmetric band \([E_{short}, E_{max}]\), e.g. **[−0.3, 1.8]**, enabling mild net short exposure in severe bear regimes.

3. **SQQQ hedge overlay**
   - v2.0 used only QQQ and TQQQ.
   - v2.5 introduces **SQQQ** as a controlled hedge/short overlay when the Kalman trend and risk modulators indicate a strong, persistent downtrend.
   - SQQQ exposure is **capped** (e.g., ≤ 20–30% of capital) to avoid runaway short‑side convexity.

---

## 4. Architecture & Filter Hierarchy

The architecture is tiered, with each layer feeding into the next:

### 4.1 Tier 1 – Kalman Trend Engine (Unchanged Core)

- Adaptive Kalman filter on **QQQ** (volume‑adjusted price model) with parameters:
  - `process_noise_1`, `process_noise_2` (fixed small values, e.g., 0.01),
  - `measurement_noise` (grid‑tuned),
  - `osc_smoothness` (short‑term oscillator smoothing),
  - `strength_smoothness` (trend_strength smoothing).

Outputs per bar:

- **Oscillator** (short‑term tendency).
- **Trend strength** \(TS_t\) in approximately [−100, +100].

### 4.2 Tier 2 – Trend Normalization & Asymmetric Scaling

- Normalize trend strength:

\[
T^{norm}_t = \text{clip} \left( \frac{TS_t}{T_{max}}, -1, +1 \right)
\]

where \(T_{max}\) is a tunable scale (e.g. 60).

- Optionally allow **asymmetric scaling** for long vs short:
  - \(k_{long}\) for \(T^{norm}_t > 0\),
  - \(k_{short}\) for \(T^{norm}_t < 0\).

Baseline trend exposure (before vol/VIX):

\[
E^{trend}_t = \begin{cases}
1.0 + k_{long} \cdot T^{norm}_t & \text{if } T^{norm}_t \ge 0 \\
1.0 + k_{short} \cdot T^{norm}_t & \text{if } T^{norm}_t < 0
\end{cases}
\]

Typical ranges:

- \(k_{long} \in [0.3, 0.6]\)
- \(k_{short} \in [0.2, 0.4]\)

This yields a pre‑modulated exposure band (before vol/VIX/DD) roughly around:

- Strong bull (\(T^{norm} \approx +1\)): \(E^{trend} \approx 1.3–1.6\)
- Neutral: \(E^{trend} \approx 1.0\)
- Strong bear (\(T^{norm} \approx −1\)): \(E^{trend} \approx 0.6–0.8\)

### 4.3 Tier 3 – Volatility Modulator

Inputs:

- Realized QQQ volatility \(\sigma^{real}_t\) (e.g., 20–60 day annualized stdev of log returns).
- Volatility target \(\sigma^{target}\) = \(\lambda_{vol} \cdot \sigma_{base}\), where \(\sigma_{base}\) is long‑run QQQ vol from a training window.

Define vol scaler:

\[
S^{vol}_t = \text{clip} \left( \frac{\sigma^{target}}{\sigma^{real}_t}, S^{min}_{vol}, S^{max}_{vol} \right)
\]

Apply scaler only to deviations from 1.0:

\[
E^{vol}_t = 1.0 + (E^{trend}_t - 1.0) \cdot S^{vol}_t
\]

High realized vol → \(S^{vol}_t < 1\) → compress deviations from 1.0 (less leverage, less shorting). Low vol → allow larger deviations.

### 4.4 Tier 4 – VIX Modulator

Inputs:

- VIX_t and its EMA: VIX_EMA_t (e.g., 50‑day EMA).
- VIX ratio: \(R^{VIX}_t = \frac{VIX_t}{VIX\_EMA_t}\).

Define VIX penalty factor:

\[
P^{VIX}_t = \begin{cases}
1 & R^{VIX}_t \le 1.0 \\
\dfrac{1}{1 + \alpha_{VIX} (R^{VIX}_t - 1)} & R^{VIX}_t > 1.0
\end{cases}
\]

Apply to deviations from 1.0:

\[
E^{vol+VIX}_t = 1.0 + (E^{vol}_t - 1.0) \cdot P^{VIX}_t
\]

VIX above its EMA compresses both long and short extremes back toward 1.0, reducing exposure in high‑fear environments unless the trend remains very strong.

### 4.5 Tier 5 – Drawdown Governor (Revised)

Let \(DD_t\) be current peak‑to‑trough drawdown (0.00–1.00).

Parameters:

- \(DD_{soft}\) (e.g., 5–10%) – start de‑risking.
- \(DD_{hard}\) (e.g., 20–25%) – maximum de‑risking.
- \(p_{min}\) (e.g., 0 or small positive) – minimum compression factor.

Compute drawdown compression factor \(P^{DD}_t\):

\[
P^{DD}_t = \begin{cases}
1 & DD_t \le DD_{soft} \\
\text{linear from 1 to } p_{min} & DD_{soft} < DD_t < DD_{hard} \\
p_{min} & DD_t \ge DD_{hard}
\end{cases}
\]

Instead of pulling exposure toward 1.0, v2.5 interpolates between **E_min** and the vol/VIX‑adjusted exposure:

\[
E^{DD}_t = E_{min} + (E^{vol+VIX}_t - E_{min}) \cdot P^{DD}_t
\]

- When \(DD_t \le DD_{soft}\): \(P^{DD}_t = 1\) ⇒ \(E^{DD}_t = E^{vol+VIX}_t\).
- When \(DD_t \ge DD_{hard}\): \(P^{DD}_t = p_{min}\) ⇒ \(E^{DD}_t \approx E_{min}\).

This makes \(E_{min}\) a **real lower bound** in deep drawdowns (rather than reverting to 1.0 as in v2.0).

Optionally, you can **gate the strength** of \(P^{DD}_t\) by trend sign, e.g.: only allow full compression to E_min when \(T^{norm}_t < 0\) (Kalman agrees it’s a structural downtrend).

### 4.6 Tier 6 – Final Exposure Bounds

Constrain final net exposure:

\[
E_t = \text{clip}(E^{DD}_t, E_{short}, E_{max})
\]

where:

- \(E_{short}\) is a small negative number (e.g., −0.3),
- \(E_{max}\) is upper exposure bound (e.g., 1.8).

Thus \(E_t\) is allowed to range from mild net short (−0.3× QQQ) to moderately high net long (1.5–1.8×).

---

## 5. Exposure Calculation Summary

Putting tiers 1–6 together:

1. Compute \(TS_t\) via Kalman.
2. Normalize to \(T^{norm}_t\).
3. Compute \(E^{trend}_t\) using asymmetric slopes \(k_{long}, k_{short}\).
4. Apply vol scaler → \(E^{vol}_t\).
5. Apply VIX compression → \(E^{vol+VIX}_t\).
6. Apply drawdown governor anchored to \(E_{min}\) → \(E^{DD}_t\).
7. Clip to \([E_{short}, E_{max}]\) → \(E_t\).

\(E_t\) is the **target net exposure** to QQQ at time t, which is then implemented via QQQ, TQQQ, SQQQ, and cash.

---

## 6. Position Mapping: QQQ / TQQQ / SQQQ / Cash

We now map net exposure \(E_t\) into portfolio weights:

- \(w_{QQQ,t}\): weight in QQQ
- \(w_{TQQQ,t}\): weight in TQQQ
- \(w_{SQQQ,t}\): weight in SQQQ (inverse; 3× short QQQ)
- \(w_{cash,t}\): uninvested cash

Constraints:

- \(w_{QQQ,t} + w_{TQQQ,t} + w_{SQQQ,t} + w_{cash,t} = 1\)
- \(w_{TQQQ,t}, w_{SQQQ,t} \ge 0\), \(w_{cash,t} \ge 0\)
- SQQQ exposure capped: \(w_{SQQQ,t} \le w^{max}_{SQQQ}\) (e.g., 0.2–0.3)

Effective net QQQ exposure:

\[
E_t \approx 1 \cdot w_{QQQ,t} + 3 \cdot w_{TQQQ,t} - 3 \cdot w_{SQQQ,t}
\]

### 6.1 Long‑Side Mapping (E_t ≥ 0)

If \(E_t \ge 0\), do not use SQQQ (pure long side):

1. **Sub‑QQQ exposure (0 ≤ E_t ≤ 1):**
   - \(w_{TQQQ,t} = 0\)
   - \(w_{QQQ,t} = E_t\)
   - \(w_{cash,t} = 1 - E_t\)

2. **Levered long (E_t > 1):**
   - Solve:
     - \(w_{QQQ,t} + w_{TQQQ,t} = 1\)
     - \(1 \cdot w_{QQQ,t} + 3 \cdot w_{TQQQ,t} = E_t\)
   - Gives:

\[
w_{TQQQ,t} = \frac{E_t - 1}{2}, \quad w_{QQQ,t} = 1 - w_{TQQQ,t}, \quad w_{cash,t} = 0
\]

### 6.2 Short / Hedge Mapping (E_t < 0)

For \(E_t < 0\), use SQQQ as a hedge overlay with cash (no TQQQ):

- Let \(E_t \in [E_{short}, 0]\), where \(E_{short} < 0\) is the minimum net exposure (e.g., −0.3).
- Use only SQQQ + cash (no long QQQ):

\[
E_t \approx -3 \cdot w_{SQQQ,t} \Rightarrow w_{SQQQ,t} = \min \left( \frac{-E_t}{3}, w^{max}_{SQQQ} \right)
\]

and

\[
w_{cash,t} = 1 - w_{SQQQ,t}, \quad w_{QQQ,t} = w_{TQQQ,t} = 0
\]

Optionally, for more nuance you can mix QQQ and SQQQ (e.g., pair trades) to maintain full capital deployment with small net short exposure; the simple version above is easier to implement and reason about.

---

## 7. Risk Management & Constraints

### 7.1 Portfolio‑Level Risk Controls

- **Exposure band:** enforce \(E_t \in [E_{short}, E_{max}]\).
- **SQQQ cap:** \(w_{SQQQ,t} \le w^{max}_{SQQQ}\) to prevent excessive short convexity.
- **Drawdown‑based compression:** as DD grows, \(P^{DD}_t\) reduces deviations from \(E_{min}\) toward safer exposures.

### 7.2 Instrument‑Level Considerations

- TQQQ and SQQQ both suffer from **volatility decay**; they are used only as **small overlays** relative to QQQ (typically ≤ 20–30% of capital in either direction).
- No attempt is made to hold SQQQ through entire multi‑year bears; shorter, high‑conviction downtrend windows are preferred.

### 7.3 Rebalancing Logic

- Compute \(E_t\) and target weights daily.
- Rebalance only if weight deviations exceed a small threshold (e.g., 2–3% absolute per symbol) and the implied trade size is material.
- This keeps realized exposure close to target while limiting turnover and trading costs.

---

## 8. Parameter Summary (Initial Defaults)

### 8.1 Kalman Trend Engine

- `process_noise_1`: 0.01 (fixed)
- `process_noise_2`: 0.01 (fixed)
- `measurement_noise`: 1000–5000 (grid‑tuned)
- `osc_smoothness`: 10–20 (grid‑tuned)
- `strength_smoothness`: 10–20 (grid‑tuned)
- `T_max`: 50–70 (grid‑tuned)

### 8.2 Trend Exposure

- `k_long`: 0.3–0.6
- `k_short`: 0.2–0.4
- `E_min`: 0.6–0.8 (lower bound in severe DD)
- `E_short`: −0.1 to −0.3
- `E_max`: 1.5–1.8

### 8.3 Volatility Modulator

- `sigma_lookback`: 20–60 days
- `sigma_target_multiplier` (λ_vol): 0.8–1.0
- `S_vol_min`: 0.5
- `S_vol_max`: 1.5

### 8.4 VIX Modulator

- `vix_ema_period`: 50
- `alpha_VIX`: 0.5–1.5

### 8.5 Drawdown Governor

- `DD_soft`: 0.05–0.10 (5–10%)
- `DD_hard`: 0.20–0.25 (20–25%)
- `p_min`: 0.0–0.3

### 8.6 SQQQ Cap

- `w_SQQQ_max`: 0.2–0.3 (20–30% capital)

### 8.7 Symbols

- `signal_symbol`: QQQ
- `core_long_symbol`: QQQ
- `leveraged_long_symbol`: TQQQ
- `leveraged_short_symbol`: SQQQ
- `vix_symbol`: VIX

---

## 9. Pseudo‑Code Walkthrough

For each daily bar t on QQQ:

1. **Update Kalman**
   - Feed QQQ OHLCV to Kalman engine.
   - Get `trend_strength_t`.

2. **Normalize trend**
   - `T_norm_t = clip(trend_strength_t / T_max, −1, +1)`.

3. **Compute baseline trend exposure**
   - If `T_norm_t >= 0`:
     - `E_trend_t = 1.0 + k_long * T_norm_t`
   - Else:
     - `E_trend_t = 1.0 + k_short * T_norm_t`

4. **Apply realized vol scaler**
   - `sigma_real_t = realized_volatility(QQQ_close, sigma_lookback)`.
   - `S_vol_t = clip(sigma_target / sigma_real_t, S_vol_min, S_vol_max)`.
   - `E_vol_t = 1.0 + (E_trend_t - 1.0) * S_vol_t`.

5. **Apply VIX compression**
   - Compute `VIX_t`, `VIX_EMA_t`, `R_VIX_t = VIX_t / VIX_EMA_t`.
   - `P_VIX_t = 1 if R_VIX_t <= 1 else 1 / (1 + alpha_VIX * (R_VIX_t - 1))`.
   - `E_volVIX_t = 1.0 + (E_vol_t - 1.0) * P_VIX_t`.

6. **Apply drawdown governor (anchored to E_min)**
   - Compute `DD_t` from equity curve.
   - Compute `P_DD_t` from DD_soft, DD_hard, p_min.
   - Optionally reduce `P_DD_t` only when `T_norm_t < 0`.
   - `E_DD_t = E_min + (E_volVIX_t - E_min) * P_DD_t`.

7. **Clip to exposure band**
   - `E_t = clip(E_DD_t, E_short, E_max)`.

8. **Map to QQQ / TQQQ / SQQQ / cash weights**
   - If `E_t >= 0`:
     - If `E_t <= 1.0`:
       - `w_TQQQ = 0`
       - `w_QQQ = E_t`
       - `w_cash = 1 - E_t`
       - `w_SQQQ = 0`
     - Else:
       - `w_TQQQ = (E_t - 1) / 2`
       - `w_QQQ = 1 - w_TQQQ`
       - `w_cash = 0`
       - `w_SQQQ = 0`
   - If `E_t < 0`:
     - `w_SQQQ = min(-E_t / 3, w_SQQQ_max)`
     - `w_cash = 1 - w_SQQQ`
     - `w_QQQ = 0`
     - `w_TQQQ = 0`

9. **Apply rebalance threshold**
   - Compare current weights to target weights.
   - If any symbol deviates by more than `rebalance_threshold` and trade size is material, generate orders to rebalance.

10. **Log context**
    - Log `trend_strength_t`, `T_norm_t`, `E_t`, `w_QQQ`, `w_TQQQ`, `w_SQQQ`, `sigma_real_t`, `R_VIX_t`, `DD_t` for diagnostics and research.

---

## 10. Backtest & Evaluation Plan

1. **Data & Span**
   - QQQ, TQQQ, SQQQ, and VIX daily data from 2010‑03‑01 to present.

2. **Benchmarks**
   - Buy‑and‑hold QQQ.
   - v2.0 best configuration (Run 139) as a reference.

3. **Metrics**
   - CAGR, annualized volatility, Sharpe, Sortino.
   - Max drawdown, Calmar.
   - Beta/correlation vs QQQ.
   - Exposure statistics (mean, median, time in net short, time > 1.5×, etc.).

4. **Year‑by‑Year Diagnostics**
   - Focus years: 2013, 2017, 2018, 2019–2021, 2022–2023.
   - Examine how v2.5 behaves vs v2.0 and QQQ in each environment.

5. **Robustness**
   - Walk‑forward studies: train on early years, test on later, etc.
   - Sensitivity analysis on \(E_{short}, E_{max}, k_{long}, k_{short}, \lambda_{vol}\).

---

## 11. Open Questions / Future Extensions

- Whether to introduce **pair‑trade hedging** (QQQ + SQQQ mix) instead of pure SQQQ + cash in net short regimes.
- Whether to allow **time‑varying bounds** \(E_{short}, E_{max}\) (e.g., narrowing band in high volatility).
- Exploration of **multi‑timeframe Kalman signals** (weekly + daily) to refine regime classification.
- Potential use of **options overlays** (e.g., protective puts, call overwriting) once core ETF overlay behaviour is fully validated.

