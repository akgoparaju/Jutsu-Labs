# Hierarchical Adaptive v2.0: Kalman‑Driven Exposure Overlay for QQQ / TQQQ / SQQQ

## 1. Strategy Overview

**Hierarchical Adaptive v2.0** is a Kalman‑driven exposure overlay designed to outperform buy‑and‑hold QQQ over long horizons while maintaining comparable or slightly lower risk (volatility and drawdown).

Instead of a hard risk‑on / risk‑off hierarchy with long periods in CASH, v2 maintains a **persistent core exposure to QQQ** and uses the Adaptive Kalman Filter to **scale exposure up or down continuously**. Leverage (TQQQ) and hedging (SQQQ) are used as controlled overlays rather than all‑or‑nothing bets.

High‑level behavior:

- **Always invested at least 40–50%** in QQQ except in extreme stress.
- **Scale exposure** between ~0.5× and ~1.3× of QQQ depending on trend strength and volatility.
- Use **TQQQ as a small overlay** in strong, low‑volatility bull regimes.
- Optionally use **SQQQ as a small hedge** in pronounced bear regimes (extension).

The Kalman trend signal remains the central innovation, but its role shifts from a **hard gate** (trade vs do nothing) to a **smooth exposure throttle**.

---

## 2. Design Goals

### 2.1 Return Objective

- Target **CAGR > QQQ** over multi‑decade backtests (e.g., 2010–2025) by:
  - Maintaining a high baseline exposure to the equity risk premium, and
  - Adding selective, risk‑controlled leverage in favorable conditions.

### 2.2 Risk & Drawdown Constraints

- Keep realized volatility within **0.8–1.1×** of QQQ.
- Keep maximum drawdown within **0.6–1.0×** of QQQ’s historical drawdown.
- Avoid catastrophic path dependency from large static short or leveraged positions.

### 2.3 Behavioral Profile

- **Core‑long, trend‑tilted**: feels like long‑term QQQ ownership with intelligent risk tilts.
- **Low turnover** relative to intraday systems, but materially more active than v1.
- Transparent, explainable decisions via logged trend strength, exposure, and vol metrics.

---

## 3. Conceptual Changes from v1.0

v2 preserves the key components of v1 (Adaptive Kalman, VIX, ATR, and regime notions) but rearranges them around a new core:

1. **No master CASH switch**:
   - VIX is no longer a hard gate. It becomes a **volatility modulator** that compresses or relaxes exposure.

2. **Kalman as scaler, not gate**:
   - Trend strength is mapped into a **continuous exposure target** rather than discrete regimes that can force 100% CASH.

3. **Always‑on QQQ core**:
   - Maintain a minimum QQQ allocation (e.g., 40–50%) under normal conditions.
   - This avoids the structural under‑exposure that crippled v1.

4. **TQQQ / SQQQ as overlays**:
   - TQQQ is used to gently raise effective exposure up to ~1.3×.
   - SQQQ is an optional hedge overlay (initially disabled or kept small).

5. **Explicit risk targeting**:
   - Realized volatility and drawdown feed back into exposure scaling.
   - Risk control is explicit, not purely emergent from being in CASH most of the time.

---

## 4. Architecture & Filter Hierarchy

### 4.1 Tier 0 – Core Exposure Engine

Defines the **target notional exposure** to QQQ, \(E_t\), as a function of:

- Kalman trend strength (primary driver),
- Realized volatility of QQQ,
- VIX / volatility state,
- Current drawdown of the strategy.

\(E_t\) is expressed as a **multiple of QQQ** (e.g., 0.5× to 1.3×) and is later mapped to an allocation in QQQ, TQQQ, and optionally SQQQ.

### 4.2 Tier 1 – Kalman Trend Engine

- Uses the existing **AdaptiveKalmanFilter** on QQQ (volume‑adjusted model) with tuned parameters:
  - Process noise terms as in v1.
  - Measurement noise and smoothing parameters chosen from best v1 optimization region (e.g., higher Alpha / lower smoothness to be more responsive).
- Outputs per bar:
  - **Oscillator** (short‑term tendency), and
  - **Trend strength** in approximately [-100, +100].

In v2, **trend strength** is treated as a continuous signal:

- Strong positive → increase exposure above 1.0×.
- Mild positive → keep exposure around 1.0×.
- Negative → reduce exposure toward 0.5× and optionally hedge.

### 4.3 Tier 2 – Volatility Modulator (VIX + Realized Vol)

Inputs:

- **Realized volatility** of QQQ (e.g., 20‑day annualized stdev of log returns).
- **VIX state**, e.g.:
  - VIX value,
  - VIX_EMA (e.g., 50‑day),
  - VIX / VIX_EMA ratio, or
  - VIX percentile vs last N days.

Role:

- When volatility is **high** (realized vol >> target_vol or VIX significantly above its EMA):
  - Compress \(E_t\) toward 1.0× (reduce leverage and hedge intensity).
- When volatility is **moderate/low** and trend is favorable:
  - Allow \(E_t\) to expand up to the upper bound (e.g., 1.3×).

### 4.4 Tier 3 – Drawdown Governor

Track:

- Strategy equity curve and **peak‑to‑trough drawdown**.

Governance logic (example):

- If trailing drawdown < 10% → no drawdown penalty.
- If 10–20% → linearly compress \(E_t\) toward 1.0.
- If > 20% → cap \(E_t\) at 1.0 and disable leverage/hedge overlays.

This ensures that after a painful period, the system **de‑risks** and earns back losses with baseline QQQ exposure instead of doubling down.

### 4.5 Tier 4 – Instrument Mapping Layer

Given final \(E_t\), determine daily allocations to:

- **QQQ** (core long),
- **TQQQ** (long overlay),
- **SQQQ** (hedge overlay, optional),
- **Cash**.

Mapping is designed so that:

- Total invested capital ≈ 100% (no uncontrolled margin),
- Effective exposure (beta to QQQ) approximates \(E_t\).

---

## 5. Exposure Calculation Details

### 5.1 Trend Normalization

Let:

- \(TS_t\) = Kalman trend strength at time t (approx. [-100, +100]).
- \(T_{max}\) = reference strength (e.g., 60).

Define normalized trend:

\[
T^{norm}_t = \text{clip}\left( \frac{TS_t}{T_{max}}, -1, +1 \right)
\]

so that:

- \(T^{norm}_t \approx +1\) in strong bull conditions,
- \(T^{norm}_t \approx 0\) in neutral / choppy markets,
- \(T^{norm}_t \approx -1\) in strong bear conditions.

### 5.2 Baseline Trend‑Driven Exposure

Define:

- Neutral exposure \(E_0 = 1.0\) (equivalent to buy‑and‑hold QQQ).
- Trend sensitivity \(k_{trend}\) (e.g., 0.3).

Baseline exposure:

\[
E^{trend}_t = E_0 + k_{trend} \cdot T^{norm}_t
\]

With \(k_{trend} = 0.3\):

- Strong bull (\(T^{norm} \approx +1\)) → \(E^{trend} \approx 1.3\).
- Neutral (\(T^{norm} \approx 0\)) → \(E^{trend} \approx 1.0\).
- Strong bear (\(T^{norm} \approx -1\)) → \(E^{trend} \approx 0.7\).

### 5.3 Volatility Adjustment

Let:

- \(\sigma^{real}_t\) = 20‑day annualized realized volatility of QQQ.
- \(\sigma^{target}\) = target volatility (e.g., long‑run QQQ vol × 0.9).

Define a volatility scaler:

\[
S^{vol}_t = \text{clip}\left( \frac{\sigma^{target}}{\sigma^{real}_t},\ S^{min}_{vol},\ S^{max}_{vol} \right)
\]

where e.g. \(S^{min}_{vol} = 0.5\), \(S^{max}_{vol} = 1.5\).

Apply scaler only to the **deviation from 1.0**:

\[
E^{vol}_t = 1.0 + (E^{trend}_t - 1.0) \cdot S^{vol}_t
\]

Intuition:

- When realized vol exceeds target, \(S^{vol}_t < 1\) → compress leverage and hedging.
- When vol is low, \(S^{vol}_t > 1\) → allow tilts to be slightly stronger.

### 5.4 VIX‑Based Compression (Soft Filter)

Let:

- VIX_t = current VIX,
- VIX_EMA_t = EMA(VIX) with period e.g. 50 days,
- R^{VIX}_t = VIX_t / VIX_EMA_t.

Define VIX penalty factor:

\[
P^{VIX}_t = \begin{cases}
1, & R^{VIX}_t \le 1.0 \\
\frac{1}{1 + \alpha_{VIX} (R^{VIX}_t - 1)}, & R^{VIX}_t > 1.0
\end{cases}
\]

with \(\alpha_{VIX} \in [0.5, 1.5]\).

Apply:

\[
E^{vol+VIX}_t = 1.0 + (E^{vol}_t - 1.0) \cdot P^{VIX}_t
\]

High VIX → \(P^{VIX}_t < 1\) → further compress deviations from 1.0 (less extreme leverage or hedge).

### 5.5 Drawdown Adjustment

Let:

- \(DD_t\) = current peak‑to‑trough drawdown of the strategy (as a positive number, e.g. 0.12 = 12%).

Define drawdown limiter:

- If \(DD_t \le DD_{soft}\) → \(P^{DD}_t = 1\).
- If \(DD_{soft} < DD_t < DD_{hard}\) → linearly map \(P^{DD}_t\) from 1 down to \(p_{min}\).
- If \(DD_t \ge DD_{hard}\) → \(P^{DD}_t = p_{min}\).

Example:

- \(DD_{soft} = 0.10\), \(DD_{hard} = 0.20\), \(p_{min} = 0.0\) (forces \(E_t\) → 1.0).

Final exposure before bounding:

\[
E^{raw}_t = 1.0 + (E^{vol+VIX}_t - 1.0) \cdot P^{DD}_t
\]

### 5.6 Final Exposure & Bounds

Impose hard bounds to keep the profile within design limits:

\[
E_t = \text{clip}(E^{raw}_t, E_{min}, E_{max})
\]

Typical defaults:

- \(E_{min} = 0.5\) (50% effective exposure),
- \(E_{max} = 1.3\) (130% effective exposure).

Only in rare extreme conditions (e.g., very high VIX and heavy drawdown) should we allow the engine to push close to \(E_{min}\).

---

## 6. Position Mapping to QQQ / TQQQ / SQQQ

### 6.1 Long‑Side Mapping (QQQ + TQQQ, No Hedge)

Given final \(E_t \in [0.5, 1.3]\), we want allocations:

- w_QQQ_t = weight in QQQ,
- w_TQQQ_t = weight in TQQQ,
- w_cash_t = 1 − w_QQQ_t − w_TQQQ_t,

such that **effective QQQ exposure**:

\[
E_t \approx 1 \cdot w_{QQQ,t} + 3 \cdot w_{TQQQ,t}
\]

and **invested capital** ≈ 1.0 (no margin usage by design).

Mapping:

1. If \(E_t \le 1.0\):
   - w_TQQQ_t = 0,
   - w_QQQ_t = E_t,
   - w_cash_t = 1 − E_t.

   → No leverage, partial cash to reduce exposure.

2. If \(E_t > 1.0\):
   - Solve:
     - w_{QQQ,t} + w_{TQQQ,t} = 1
     - 1·w_{QQQ,t} + 3·w_{TQQQ,t} = E_t
   - This yields:

\[
w_{TQQQ,t} = \frac{E_t - 1}{2}, \quad w_{QQQ,t} = 1 - w_{TQQQ,t}
\]

   - w_cash_t = 0.

For \(E_t = 1.3\):

- w_TQQQ_t = (1.3 − 1)/2 = 0.15,
- w_QQQ_t = 0.85,
- Effective exposure = 0.85·1 + 0.15·3 = 1.3,
- Invested capital = 1.0.

### 6.2 Optional Hedge Mapping with SQQQ (v2.1+)

Initial v2 implementation can **omit SQQQ entirely**. For a later version (v2.1+), a small hedge overlay can be defined for strongly negative \(T^{norm}_t\):

- For \(E_t < 1.0\) and \(T^{norm}_t < -\theta_{hedge}\) (e.g., −0.7):
  - Replace some cash with SQQQ such that:

\[
E_t \approx 1 \cdot w_{QQQ,t} - 3 \cdot w_{SQQQ,t}
\]

subject to a strict cap (e.g., w_{SQQQ,t} ≤ 0.10) to avoid aggressive short exposure.

This can be added once long‑side v2 behavior is validated.

---

## 7. Risk Management & Constraints

### 7.1 Portfolio‑Level Risk

- Primary risk control is via **exposure level** \(E_t\), not per‑trade stop‑losses.
- Per‑bar, enforce:
  - Exposure bounds \([E_{min}, E_{max}]\),
  - Optional additional constraint on **gross** notional (e.g., \(|w_{QQQ}| + |w_{TQQQ}| + |w_{SQQQ}| \le 1.05\)).

### 7.2 Instrument‑Level Considerations

- **TQQQ and SQQQ** suffer from **volatility decay**; they are used only as small overlays (≤ 20–25% of capital).
- No attempt to hold TQQQ for extremely long multi‑year periods; exposure tapers as trend weakens or volatility rises.

### 7.3 Liquidity & Execution

- Execute at daily close or next‑open, consistent with v1 backtest conventions.
- Include realistic slippage and commissions for production, even if ignored in early R&D.

---

## 8. Parameter Summary (Initial Defaults)

Grouped by tier.

### 8.1 Kalman Trend Engine

- process_noise_1: 0.01 (fixed)
- process_noise_2: 0.01 (fixed)
- measurement_noise: e.g., 2000.0 (from best v1 region)
- osc_smoothness: e.g., 10–20
- strength_smoothness: e.g., 10–20
- T_max: 60

### 8.2 Exposure Engine

- E_0 (neutral exposure): 1.0
- k_trend (trend sensitivity): 0.3
- E_min: 0.5
- E_max: 1.3

### 8.3 Volatility Modulator

- sigma_target: long‑run QQQ vol × 0.9 (calibrated from history)
- realized_vol_lookback: 20 trading days
- S_vol_min: 0.5
- S_vol_max: 1.5

### 8.4 VIX Modulator

- vix_ema_period: 50
- alpha_VIX: 1.0

### 8.5 Drawdown Governor

- DD_soft: 0.10 (10%)
- DD_hard: 0.20 (20%)
- p_min: 0.0 (forces exposure deviation → 0 beyond DD_hard)

### 8.6 Symbols

- signal_symbol: QQQ
- core_long_symbol: QQQ
- leveraged_long_symbol: TQQQ
- leveraged_short_symbol: SQQQ (optional)
- vix_symbol: VIX

These defaults should be refined via grid search and walk‑forward tests, but the tuning space is now **low‑dimensional and interpretable**.

---

## 9. Pseudo‑Code Walkthrough

High‑level daily loop (for QQQ bar at time t):

1. **Update Kalman**
   - Feed QQQ OHLCV to AdaptiveKalmanFilter.
   - Receive trend_strength_t.

2. **Compute normalized trend**
   - T_norm_t = clip(trend_strength_t / T_max, −1, +1).

3. **Compute baseline trend exposure**
   - E_trend_t = 1.0 + k_trend · T_norm_t.

4. **Compute realized volatility scaler**
   - sigma_real_t = realized_vol_20d(QQQ).
   - S_vol_t = clip(sigma_target / sigma_real_t, S_vol_min, S_vol_max).
   - E_vol_t = 1.0 + (E_trend_t − 1.0) · S_vol_t.

5. **Compute VIX compression**
   - vix, vix_ema_t = current VIX, EMA(VIX, vix_ema_period).
   - R_VIX_t = vix / vix_ema_t.
   - P_VIX_t = 1 if R_VIX_t ≤ 1 else 1 / (1 + alpha_VIX · (R_VIX_t − 1)).
   - E_volVIX_t = 1.0 + (E_vol_t − 1.0) · P_VIX_t.

6. **Apply drawdown governor**
   - DD_t = current drawdown.
   - Compute P_DD_t based on DD_soft, DD_hard.
   - E_raw_t = 1.0 + (E_volVIX_t − 1.0) · P_DD_t.

7. **Bound final exposure**
   - E_t = clip(E_raw_t, E_min, E_max).

8. **Map exposure to allocations**
   - If E_t ≤ 1.0:
     - w_TQQQ_t = 0,
     - w_QQQ_t = E_t,
     - w_cash_t = 1 − E_t.
   - Else:
     - w_TQQQ_t = (E_t − 1) / 2,
     - w_QQQ_t = 1 − w_TQQQ_t,
     - w_cash_t = 0.

9. **Rebalance portfolio**
   - Compute desired dollar holdings = weights × portfolio_equity.
   - Generate buy/sell orders for QQQ and TQQQ to achieve desired weights.

10. **Log context**
    - Log trend_strength_t, T_norm_t, E_t, w_QQQ_t, w_TQQQ_t, sigma_real_t, VIX state, DD_t.

---

## 10. Implementation Specifications (v2.0)

### 10.1 Version Scope: Long-Side Only

**v2.0 Implementation**: QQQ + TQQQ exposure scaling (long-side only)
- SQQQ hedge functionality **deferred to v2.1** (future enhancement)
- Focus on validating core continuous exposure engine
- Simpler testing and optimization (fewer moving parts)
- E_t range effectively becomes [0.5, 1.3] with no negative exposure

**Rationale**: Validate fundamental paradigm shift (continuous vs discrete) before adding hedge complexity.

### 10.2 Portfolio Rebalancing Strategy

**Daily Drift-Based Rebalancing** with conservative threshold:
- Check actual portfolio weights vs target weights **every bar**
- Rebalance **only if deviation > 2-3%** (not 5%, for tighter tracking)
- Reduces turnover while maintaining exposure discipline

**Implementation**:
```python
# Pseudo-code
current_qqq_weight = portfolio.positions['QQQ'] / portfolio.equity
current_tqqq_weight = portfolio.positions['TQQQ'] / portfolio.equity

weight_deviation = abs(current_qqq_weight - target_qqq_weight) + \
                   abs(current_tqqq_weight - target_tqqq_weight)

if weight_deviation > 0.025:  # 2.5% total deviation threshold
    rebalance_to_target_weights()
```

**Threshold Parameter**: `rebalance_threshold` (default: 0.025, tunable in grid-search)

### 10.3 Sigma_target Calibration

**Tunable Parameter Approach**:
- Base estimate: Calculate QQQ realized vol from full historical period (2010-2025)
- Make `sigma_target_multiplier` a **grid-search parameter** (e.g., [0.8, 0.9, 1.0, 1.1])
- Final: `sigma_target = historical_qqq_vol × sigma_target_multiplier`

**NOT Rolling**: Use fixed historical estimate (not rolling 252-day calculation)
- Simpler, more stable
- Avoid regime-dependent vol targeting
- Can revisit rolling approach in v2.1+ if needed

**Implementation**:
```python
# One-time calculation (in init or pre-backtest)
qqq_closes = get_all_historical_closes('QQQ', '2010-03-01', '2025-11-01')
historical_qqq_vol = annualized_volatility(qqq_closes, lookback=len(qqq_closes))

# Parameter (tunable in grid-search)
sigma_target_multiplier = 0.9  # [0.8, 0.9, 1.0, 1.1]

# Final target
sigma_target = historical_qqq_vol * sigma_target_multiplier
```

### 10.4 Realized Volatility Calculation

**New Indicator Function**: Add to `jutsu_engine/indicators/technical.py`

```python
def annualized_volatility(
    closes: pd.Series,
    lookback: int = 20,
    trading_days_per_year: int = 252
) -> pd.Series:
    """
    Calculate annualized realized volatility from price series.
    
    Uses log returns for statistical properties:
    - Symmetry (up/down moves)
    - Time additivity
    - Better for compounding
    
    Args:
        closes: Price series
        lookback: Window for volatility calculation (default: 20 days)
        trading_days_per_year: Annualization factor (default: 252)
    
    Returns:
        Series of annualized volatility (e.g., 0.20 = 20% annual vol)
    
    Example:
        >>> closes = pd.Series([100, 101, 99, 102, 98])
        >>> vol = annualized_volatility(closes, lookback=20)
        >>> # Returns rolling 20-day annualized volatility
    """
    log_returns = np.log(closes / closes.shift(1))
    rolling_std = log_returns.rolling(window=lookback).std()
    annualized_vol = rolling_std * np.sqrt(trading_days_per_year)
    return annualized_vol
```

**Usage in Strategy**:
```python
# In on_bar()
closes = self.get_closes(lookback=self.realized_vol_lookback, symbol='QQQ')
vol_series = annualized_volatility(closes, lookback=self.realized_vol_lookback)
sigma_real_t = Decimal(str(vol_series.iloc[-1]))
```

### 10.5 Initial Grid-Search Scope

**Phase 1: Focused Core Optimization** (Recommended Start)
- Focus: Kalman trend engine + exposure sensitivity (k_trend)
- Parameters:
  - `measurement_noise`: [1000.0, 2000.0, 5000.0] (3 values)
  - `osc_smoothness`: [10, 15, 20] (3 values)
  - `strength_smoothness`: [10, 15, 20] (3 values)
  - `T_max`: [50, 60, 70] (3 values)
  - `k_trend`: [0.2, 0.3, 0.4] (3 values) ← **CRITICAL**
- Fixed (initially):
  - `E_min`: 0.5, `E_max`: 1.3
  - `vix_ema_period`: 50
  - `alpha_VIX`: 1.0
  - Vol/DD governor params at defaults
- **Total**: 3^5 = 243 runs (~30-45 minutes)
- **Goal**: Validate core continuous exposure paradigm works

**Phase 2: Full Modulator Optimization** (If Phase 1 succeeds)
- Add VIX modulator params: `vix_ema_period` [30, 50, 75], `alpha_VIX` [0.5, 1.0, 1.5]
- Add vol modulator params: `S_vol_min` [0.3, 0.5], `S_vol_max` [1.3, 1.5]
- Add drawdown governor: `DD_soft` [0.08, 0.10, 0.12]
- **Total**: 243 × 3 × 3 × 2 × 2 × 3 = ~13,122 runs (expand cautiously!)
- **Alternative**: Use Phase 1 winners, add modulators incrementally

### 10.6 Parameter Summary (v2.0 Implementation)

**Total Parameters**: ~20 (vs v1's 28)

**Tier 0: Core Exposure Engine**
- `E_0`: 1.0 (neutral exposure, fixed)
- `k_trend`: 0.3 (trend sensitivity, **CRITICAL**, tunable [0.2-0.4])
- `E_min`: 0.5 (min exposure, tunable [0.4-0.6])
- `E_max`: 1.3 (max exposure, tunable [1.2-1.5])

**Tier 1: Kalman Trend Engine**
- `process_noise_1`: 0.01 (fixed)
- `process_noise_2`: 0.01 (fixed)
- `measurement_noise`: 2000.0 (tunable [1000-5000])
- `osc_smoothness`: 15 (tunable [10-20])
- `strength_smoothness`: 15 (tunable [10-20])
- `T_max`: 60 (tunable [50-70])

**Tier 2: Volatility Modulator**
- `sigma_target_multiplier`: 0.9 (tunable [0.8-1.1])
- `realized_vol_lookback`: 20 (tunable [15-30])
- `S_vol_min`: 0.5 (tunable [0.3-0.5])
- `S_vol_max`: 1.5 (tunable [1.3-1.7])

**Tier 3: VIX Modulator**
- `vix_ema_period`: 50 (tunable [30-75])
- `alpha_VIX`: 1.0 (tunable [0.5-1.5])

**Tier 4: Drawdown Governor**
- `DD_soft`: 0.10 (10%, tunable [0.08-0.12])
- `DD_hard`: 0.20 (20%, tunable [0.15-0.25])
- `p_min`: 0.0 (fixed, forces E_t → 1.0 beyond DD_hard)

**Tier 5: Rebalancing Control** (NEW)
- `rebalance_threshold`: 0.025 (2.5%, tunable [0.02-0.05])

**Symbols**
- `signal_symbol`: "QQQ"
- `core_long_symbol`: "QQQ"
- `leveraged_long_symbol`: "TQQQ"
- `vix_symbol`: "VIX"

---

## 11. Backtest & Evaluation Plan

1. **Data & Span**
   - Same span as v1: 2010‑03‑01 → present (e.g., 2025‑10‑31).
   - Daily bars for QQQ, TQQQ, SQQQ, VIX.

2. **Benchmarks**
   - Buy‑and‑hold QQQ.
   - “Signal‑timed QQQ” baselines:
     - Always E_t ≡ 1.0 (pure QQQ).
     - E_t from trend only, with volatility and VIX modulators disabled.

3. **Metrics**
   - CAGR, annualized volatility, Sharpe.
   - Max drawdown, Calmar.
   - Beta and correlation vs QQQ.
   - Turnover and average holding periods.

4. **Robustness**
   - Walk‑forward optimization across sub‑periods.
   - Sensitivity analysis on E_min, E_max, k_trend, sigma_target.

---

## 11. Open Questions / Future Enhancements

- Whether to allow **small SQQQ hedging** in strongly negative Kalman regimes.
- Whether to re‑introduce a **soft EMA trend filter** as a gating multiplier (e.g., compress E_t when price < 200‑day EMA).
- Whether to include **skew / kurtosis** or **term‑structure of vol (VIX vs VXST/VXV)** into the volatility modulator.
- Design of a **multi‑timeframe Kalman overlay** (e.g., weekly and daily) for additional robustness.

v2 is intentionally simpler and more continuous than v1, with the goal of delivering a realistic path to beating QQQ while staying within a reasonable risk envelope.

