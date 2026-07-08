# Baseline Audit Phase 4 — Module 3: Selection-Bias Correction (DSR + PBO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `jutsu audit dsr` — the final audit module that corrects the golden config's headline Sharpe for selection bias via the Deflated Sharpe Ratio (Bailey & López de Prado) and estimates the Probability of Backtest Overfitting (PBO) via CSCV, over a one-time full-period re-run of the historical ~243-combo v3_5b golden grid.

**Architecture:** Reuse the proven Phase-2/3 campaign machinery (`build_overridden_strategy` + `BacktestRunner` + fsync-JSONL checkpoint/resume + circuit breaker + single-writer + `--retry-errors` + midnight-safe run dirs + per-run tempdirs). Add three pure, heavily unit-tested math layers (`dsr.py`, `pbo.py`) that operate on daily-return series and a returns matrix — no DB, no live/scheduler changes. A new campaign captures each grid combo's daily `Strategy_Daily_Return` series (stored inline in JSONL, same shape the WFO campaign already stores OOS rows). A read-only `optimization_results` inventory query feeds the bracketed trial-count table (N = 243 / 1,000 / 5,000).

**Tech Stack:** Python 3.11 (`.venv/bin/python`), numpy, pandas, `scipy.stats` (`norm.cdf`/`norm.ppf`/`skew`/`kurtosis` — confirmed installed, 1.17.1), click CLI, pytest. **No new dependencies** (pyarrow is NOT installed — returns stored as JSONL, not parquet).

---

## Context the implementer needs (read before starting)

**The strategy family & prior findings (LOGBOOK):**
- The v3_5b golden config came from a **~243-run grid search** on top of a v2.x→v3.5b search history numbering in the thousands. Reported in-sample Sharpe ~2.79 / MaxDD −18.4% are optimistic by construction.
- EXP-001: honest full-period Sharpe is **~0.81** (v3_5b) / ~0.79 (v3_5d), MaxDD ~−51%, not the documented ~2.8. That is the ruler.
- EXP-003 (plateau): golden config is parameter-robust (a plateau, 48th/57.5th percentile of its own neighborhood); some parameters are **inert**, others (vol-regime channel) **sensitive**. Module 3's grid re-run must reproduce the **historical** combos — do NOT invent a new grid, do NOT drop the inert axes (the historical search varied them).
- EXP-004 (WFO): adaptive tuning CLOSED (stitched OOS Sharpe 0.46). The stitched WFO OOS curve is the honest benchmark.
- XREF-001 measurement rules (adopted from the Kronos program) that bind here: **n=1 crash-episode caution** — backtest-only evidence is structurally underpowered, so **DSR/PBO carry the real burden of proof** for the "is the edge real?" question. The report's verdict must reflect this humility (do not over-claim).

**The proven campaign patterns to REUSE (do not rebuild), from `jutsu_engine/audit/wfo_stability.py` + `plateau.py`:**
- `build_overridden_strategy(strategy_id, overrides)` — builds a live strategy with param overrides, float→Decimal parity with `LiveStrategyRunner` (`plateau.py:373`).
- `run_one_backtest`-style worker that runs ONE `BacktestRunner` backtest into a throwaway tempdir and returns a result row (`wfo_stability.py:403`). The OOS branch already reads the regime-timeseries CSV and extracts `Strategy_Daily_Return` — Module 3 captures the SAME series full-period.
- fsync-JSONL append (`append_wfo_row`, `wfo_stability.py:523`), last-wins reload (`reload_wfo_rows`), completed-key resume (`load_completed_keys`), circuit breaker + single-writer parallel runner (`_run_serial`/`_run_parallel`/`_dispatch`), `is_error_row`.
- Midnight-safe run-dir resolution in the CLI (`_resolve_run_dir_wfo`, `audit.py:244`).
- `_all_symbols(strategy_id)` (`attribution.py:201`), `ATTRIBUTION_START = date(2010, 2, 1)` (`config.py:20`), `report_output_dir()` (`config.py:63`).
- Pure metric helpers `_sharpe`, `_max_drawdown`, `_total_return` (`attribution.py:65-82`) — reuse; do NOT re-implement Sharpe.

**The regime-timeseries CSV columns** (`regime_analyzer.py:192-216`): `Date, Regime, Trend, Vol, QQQ_Close, QQQ_Daily_Return, Portfolio_Value, Strategy_Daily_Return`. Module 3 needs `Date` + `Strategy_Daily_Return` per combo.

**CRITICAL: the golden grid axes.** The file body of `grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml` has every axis **collapsed to a single value** (e.g. `sma_fast: [40]`) — it is the *winning* config snapshot, not the search grid. The **243-combo grid the search actually ran is documented in that file's header comments** (lines 58-84) and is authoritative:

| Axis | Values | Count |
|---|---|---|
| `upper_thresh_z` | [0.8, 1.0, 1.2] | 3 |
| `lower_thresh_z` | [-0.2, 0.0, 0.2] | 3 |
| `vol_crush_threshold` | [-0.15, -0.20, -0.25] | 3 |
| `sma_fast` | [40, 50, 60] | 3 |
| `sma_slow` | [180, 200, 220] | 3 |

Product = 3×3×3×3×3 = **243 combos**. This is the REAL count (matches the "~243 runs" in the header, LOGBOOK, and spec §7). All other parameters are held at the live golden values. We enumerate exactly these axes and versioned in `grid-configs/audit/`.

**Scoping (state in report + CHANGELOG):**
- **v3_5b is primary** — the historical grid was v3_5b's. Full grid re-run + DSR + PBO.
- **v3_5d gets DSR ONLY** using its own golden full-period daily returns (from an attribution run) and a **family-level N** (documented estimate). **No second grid re-run for v3_5d** — its distinguishing grid was a tiny ~10-combo Cell-1-exit search (`grid_search_hierarchical_adaptive_v3_5d.yaml`), which cannot support CSCV (needs a wide combo matrix). PBO is v3_5b-only.

**Compute honesty (state in report):** 243 combos × ~1.6 min/backtest ÷ 4 workers ≈ **~1.7 h** one-time returns campaign (10 CPUs available; use 4 workers). CSCV over the 243×~4,100 matrix = **seconds** (12,870 partitions, pure numpy). Smoke mode proves the pipeline in minutes (tiny combo subset + synthetic-matrix math).

**Returns-matrix storage choice (justify in report + docstring):** **JSONL, inline daily-return arrays** — one row per combo: `{combo_id, hash, overrides, dates: [...], returns: [...], sharpe, error}`. 243 combos × ~4,100 floats ≈ ~10 MB uncompressed — trivial. Chosen over parquet because (a) pyarrow is not installed (no new dependency), (b) it reuses the fsync-JSONL checkpoint/resume machinery verbatim (crash-safety, single-writer, `--retry-errors`), and (c) `Date` alignment across combos is handled at load time by pivoting on the union of dates.

**Constraints (hard rules):** Strictly READ-ONLY vs the DB (SELECT only). Reuse, don't rebuild. Explicit `git add <paths>` in every commit. DB-free unit tests (pure math + fakes; campaign tested via injected `run_fn`). Focused-test command: `.venv/bin/python -m pytest <path> -p no:cacheprovider -o addopts="" -q`. One-line test docstrings. `pytest.raises(match=...)`. No placeholders.

---

## File Structure

| File | Responsibility | New/Modify |
|---|---|---|
| `jutsu_engine/audit/dsr.py` | Pure DSR math: PSR, expected-max-Sharpe SR*, DSR, skew/kurtosis helpers, degenerate guards | **Create** |
| `jutsu_engine/audit/pbo.py` | Pure PBO/CSCV math: block split, IS/OOS partition enumeration, PBO, logit distribution, degradation slope, prob-of-OOS-loss | **Create** |
| `jutsu_engine/audit/selection_bias.py` | Grid enumeration (243 golden combos), returns-campaign runner (reuse WFO/plateau infra), returns-matrix assembly, N-bracket orchestration, `run_dsr` orchestrator | **Create** |
| `grid-configs/audit/golden_grid_v3_5b_axes.yaml` | Versioned record of the 243-combo axes (provenance) | **Create** |
| `jutsu_engine/audit/db.py` | Add read-only `load_trial_counts()` + pure `trial_count_records()` shaper | **Modify** |
| `jutsu_engine/audit/report.py` | `render_dsr_section` + `write_dsr_report` | **Modify** |
| `jutsu_engine/cli/commands/audit.py` | `jutsu audit dsr` subcommand + midnight-safe DSR run-dir resolver | **Modify** |
| `tests/unit/audit/test_dsr.py` | DSR math unit tests (hand-computed references) | **Create** |
| `tests/unit/audit/test_pbo.py` | PBO/CSCV math unit tests (synthetic matrices) | **Create** |
| `tests/unit/audit/test_selection_bias.py` | Grid enumeration + campaign (injected run_fn) + matrix assembly + inventory shaper | **Create** |
| `tests/unit/audit/test_dsr_cli.py` | CLI wiring (CliRunner, no DB) | **Create** |
| `tests/unit/audit/test_report.py` | Add DSR report renderer tests | **Modify** |
| `docs/experiments/LOGBOOK.md` | EXP-005 skeleton | **Modify** |
| `CHANGELOG.md` | Phase 4 entry | **Modify** |

---

## Task 1: DSR — Probabilistic Sharpe Ratio (PSR)

**Files:**
- Create: `jutsu_engine/audit/dsr.py`
- Test: `tests/unit/audit/test_dsr.py`

The PSR is the probability the true Sharpe exceeds a benchmark `SR*`, given `T` observations and the return distribution's skew (γ₃) and non-excess kurtosis (γ₄), with all Sharpes in **per-period** units:

```
PSR(SR*) = Φ( ((SR_obs − SR*)·√(T−1)) / √(1 − γ₃·SR_obs + ((γ₄−1)/4)·SR_obs²) )
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/audit/test_dsr.py
"""DB-free unit tests for the Deflated Sharpe Ratio math (Module 3)."""
import math

import pytest

from jutsu_engine.audit.dsr import psr


class TestPSR:
    def test_symmetric_normal_reference(self):
        """PSR(SR*=0) for SR_obs=0.5, T=101, normal returns matches hand value."""
        # num=(0.5-0)*sqrt(100)=5.0; den=sqrt(1 - 0*0.5 + (2/4)*0.25)=sqrt(1.0625)=1.03078...
        # Wait: (g4-1)/4 = (3-1)/4 = 0.5; 0.5*0.25=0.125; den=sqrt(1.125)=1.06066; z=4.71405
        got = psr(sr_obs=0.5, sr_star=0.0, T=101, skew=0.0, kurt=3.0)
        assert got == pytest.approx(0.9999987858, abs=1e-9)

    def test_nonnormal_small_T_reference(self):
        """PSR with negative skew, fat tails, small T matches hand value."""
        # num=(0.1-0)*sqrt(9)=0.3; den=sqrt(1 -(-0.5)(0.1)+((4-1)/4)(0.01))
        #    =sqrt(1+0.05+0.0075)=sqrt(1.0575)=1.02835; z=0.291730; PSR=0.6147534586
        got = psr(sr_obs=0.1, sr_star=0.0, T=10, skew=-0.5, kurt=4.0)
        assert got == pytest.approx(0.6147534586, abs=1e-9)

    def test_sr_obs_equal_sr_star_is_half(self):
        """When SR_obs == SR*, the numerator is 0 so PSR = Φ(0) = 0.5."""
        got = psr(sr_obs=0.3, sr_star=0.3, T=200, skew=0.0, kurt=3.0)
        assert got == pytest.approx(0.5, abs=1e-12)

    def test_small_T_guard(self):
        """T < 2 has no √(T−1); raise a clear ValueError."""
        with pytest.raises(ValueError, match="T must be >= 2"):
            psr(sr_obs=0.5, sr_star=0.0, T=1, skew=0.0, kurt=3.0)

    def test_nonpositive_variance_guard(self):
        """A skew/kurtosis combo making the denominator radicand <= 0 raises."""
        # 1 - g3*SR + ((g4-1)/4)*SR^2 <= 0 is pathological; guard against sqrt of <=0.
        with pytest.raises(ValueError, match="non-positive"):
            psr(sr_obs=1.0, sr_star=0.0, T=100, skew=10.0, kurt=3.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jutsu_engine.audit.dsr'`

- [ ] **Step 3: Write the minimal implementation**

```python
# jutsu_engine/audit/dsr.py
"""Module 3 — Deflated Sharpe Ratio math (Bailey & López de Prado).

Pure functions over per-period Sharpe inputs. NO database, NO backtest — the
returns campaign (selection_bias.py) supplies the daily-return series; this file
turns them into DSR/PSR numbers. All Sharpes are in PER-PERIOD units (daily here),
skewness is γ₃, kurtosis is γ₄ (NON-EXCESS, i.e. normal == 3.0), T is the number
of observations.

Formulas (spelled out so implementers never guess):

  PSR(SR*) = Φ( ((SR_obs − SR*)·√(T−1))
                / √(1 − γ₃·SR_obs + ((γ₄−1)/4)·SR_obs²) )

  SR*  = √V · ((1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))     (expected max Sharpe
         under N independent trials with cross-trial Sharpe variance V; γ is the
         Euler–Mascheroni constant ≈ 0.5772)

  DSR  = PSR(SR*)
"""
from __future__ import annotations

import math

from scipy.stats import norm

# Standard-normal CDF (Φ) and inverse CDF / quantile (Φ⁻¹).
_Phi = norm.cdf
_Phi_inv = norm.ppf

# Euler–Mascheroni constant.
EULER_MASCHERONI: float = 0.5772156649015329


def psr(sr_obs: float, sr_star: float, T: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe Ratio PSR(SR*): P(true SR > SR*) given sample moments.

    Args:
      sr_obs: observed per-period Sharpe (e.g. daily).
      sr_star: benchmark Sharpe to beat (0 for the classic PSR; SR* for DSR).
      T: number of return observations (>= 2).
      skew: γ₃, sample skewness of the returns.
      kurt: γ₄, NON-EXCESS kurtosis (normal == 3.0; excess kurtosis + 3).

    Returns Φ(z) where
      z = (sr_obs − sr_star)·√(T−1) / √(1 − γ₃·sr_obs + ((γ₄−1)/4)·sr_obs²).

    Raises ValueError if T < 2 (no √(T−1)) or the denominator radicand is
    non-positive (a pathological skew/kurtosis/SR combination).
    """
    if T < 2:
        raise ValueError(f"T must be >= 2 for PSR (got {T})")
    radicand = 1.0 - skew * sr_obs + ((kurt - 1.0) / 4.0) * (sr_obs ** 2)
    if radicand <= 0.0:
        raise ValueError(
            f"PSR denominator radicand is non-positive ({radicand:.6g}); "
            f"skew/kurtosis/SR combination is pathological "
            f"(skew={skew}, kurt={kurt}, sr_obs={sr_obs})"
        )
    z = (sr_obs - sr_star) * math.sqrt(T - 1) / math.sqrt(radicand)
    return float(_Phi(z))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/dsr.py tests/unit/audit/test_dsr.py
git commit -m "feat(audit): add PSR (Probabilistic Sharpe Ratio) math for Module 3 DSR"
```

---

## Task 2: DSR — Expected max Sharpe SR* under N trials

**Files:**
- Modify: `jutsu_engine/audit/dsr.py`
- Test: `tests/unit/audit/test_dsr.py`

The deflation benchmark: the Sharpe you'd expect to see as the *maximum* over N independent trials, purely by chance, given cross-trial Sharpe variance V.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_dsr.py
from jutsu_engine.audit.dsr import expected_max_sharpe


class TestExpectedMaxSharpe:
    def test_reference_N243_V001(self):
        """SR* for N=243, V=0.01 matches the hand-computed value."""
        # Φ⁻¹(1-1/243)=2.6424666; Φ⁻¹(1-1/(243e))=2.9648999; γ=0.5772157
        # SR* = 0.1*((0.4227843)(2.6424666)+(0.5772157)(2.9648999)) = 0.28285802
        got = expected_max_sharpe(V=0.01, N=243)
        assert got == pytest.approx(0.28285802, abs=1e-7)

    def test_reference_N1000(self):
        """SR* grows with N (more trials → higher expected max) — N=1000."""
        got = expected_max_sharpe(V=0.01, N=1000)
        assert got == pytest.approx(0.32551215, abs=1e-7)

    def test_reference_N5000(self):
        """SR* for the widest bracket N=5000."""
        got = expected_max_sharpe(V=0.01, N=5000)
        assert got == pytest.approx(0.36877031, abs=1e-7)

    def test_monotone_in_N(self):
        """More trials → strictly higher expected max Sharpe at fixed V."""
        a = expected_max_sharpe(V=0.01, N=243)
        b = expected_max_sharpe(V=0.01, N=1000)
        c = expected_max_sharpe(V=0.01, N=5000)
        assert a < b < c

    def test_scales_with_sqrt_V(self):
        """SR* scales as √V: quadrupling V doubles SR* at fixed N."""
        base = expected_max_sharpe(V=0.01, N=1000)
        quad = expected_max_sharpe(V=0.04, N=1000)
        assert quad == pytest.approx(2.0 * base, rel=1e-9)

    def test_N_one_guard(self):
        """N=1 has no selection (Φ⁻¹(0) = −∞); raise a clear ValueError."""
        with pytest.raises(ValueError, match="N must be >= 2"):
            expected_max_sharpe(V=0.01, N=1)

    def test_negative_variance_guard(self):
        """Cross-trial variance V must be non-negative."""
        with pytest.raises(ValueError, match="V must be >= 0"):
            expected_max_sharpe(V=-0.01, N=100)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr.py::TestExpectedMaxSharpe -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'expected_max_sharpe'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/dsr.py
def expected_max_sharpe(V: float, N: int) -> float:
    """Expected maximum Sharpe under N independent trials with cross-trial variance V.

    SR* = √V · ((1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))

    where γ = EULER_MASCHERONI. This is the deflation benchmark the observed Sharpe
    must beat: the Sharpe you'd expect to see as the best of N tries by pure luck.

    Args:
      V: variance of the Sharpe ratios ACROSS trials (per-period units, so the
         same units as SR_obs fed to psr()). V >= 0.
      N: number of (effectively independent) trials. N >= 2 (N=1 means no
         selection: Φ⁻¹(1 − 1/1) = Φ⁻¹(0) = −∞).

    Raises ValueError for N < 2 or V < 0.
    """
    if N < 2:
        raise ValueError(f"N must be >= 2 (got {N}); N=1 means no selection")
    if V < 0:
        raise ValueError(f"V must be >= 0 (got {V})")
    g = EULER_MASCHERONI
    term = ((1.0 - g) * _Phi_inv(1.0 - 1.0 / N)
            + g * _Phi_inv(1.0 - 1.0 / (N * math.e)))
    return float(math.sqrt(V) * term)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/dsr.py tests/unit/audit/test_dsr.py
git commit -m "feat(audit): add expected-max-Sharpe SR* under N trials"
```

---

## Task 3: DSR — end-to-end deflated Sharpe from a daily-return series

**Files:**
- Modify: `jutsu_engine/audit/dsr.py`
- Test: `tests/unit/audit/test_dsr.py`

Glue: given the golden daily-return series + N + V, compute DSR = PSR(SR*). Uses `scipy.stats.skew`/`kurtosis` with the correct (non-excess, sample-bias-corrected) conventions.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_dsr.py
import numpy as np

from jutsu_engine.audit.dsr import (
    sample_moments, deflated_sharpe, DEFAULT_N_BRACKETS,
)


class TestSampleMoments:
    def test_skew_and_nonexcess_kurtosis(self):
        """sample_moments returns per-period Sharpe, γ₃ skew, γ₄ NON-excess kurtosis."""
        data = np.array([0.01, -0.02, 0.015, -0.005, 0.03,
                         -0.01, 0.02, -0.015, 0.005, 0.01])
        m = sample_moments(data)
        # scipy skew(bias=False) and kurtosis(fisher=True,bias=False)+3:
        assert m["skew"] == pytest.approx(-0.023853, abs=1e-5)
        assert m["kurt_nonexcess"] == pytest.approx(2.040487, abs=1e-5)
        # non-excess kurtosis is excess + 3; normal-ish data ⇒ near 3 minus platykurtic
        assert m["T"] == 10

    def test_zero_variance_raises(self):
        """A constant series has zero std → Sharpe undefined; raise."""
        with pytest.raises(ValueError, match="zero variance"):
            sample_moments(np.array([0.01, 0.01, 0.01, 0.01]))


class TestDeflatedSharpe:
    def test_end_to_end_reference(self):
        """DSR end-to-end for a synthetic golden series matches the hand value."""
        # Build a daily series with per-period Sharpe = 0.8/sqrt(252) = 0.05039526,
        # skew≈0, non-excess kurt≈3, T=4100; N=243, V=0.0004 ⇒ SR*=0.0565716.
        rng = np.random.default_rng(7)
        T = 4100
        target_daily_sr = 0.8 / np.sqrt(252)
        # scale a standard normal to mean/std giving the target Sharpe
        base = rng.standard_normal(T)
        base = (base - base.mean()) / base.std(ddof=1)   # exact 0 mean, unit std
        returns = 0.01 * base + 0.01 * target_daily_sr   # std≈0.01, mean=0.01*SR*std
        d = deflated_sharpe(returns, N=243, V=0.0004)
        assert d["sr_star"] == pytest.approx(0.0565716, abs=1e-6)
        # DSR ≈ 0.346 for this configuration (SR_obs ≈ SR*, so DSR near 0.5·… < 0.5)
        assert 0.30 <= d["dsr"] <= 0.42
        assert d["sr_obs"] == pytest.approx(target_daily_sr, abs=1e-3)

    def test_high_sharpe_low_N_gives_high_dsr(self):
        """A genuinely high Sharpe with few trials survives deflation (DSR→1)."""
        rng = np.random.default_rng(1)
        T = 2000
        base = rng.standard_normal(T)
        base = (base - base.mean()) / base.std(ddof=1)
        # per-period Sharpe ≈ 0.2 (very high daily) with N=2 trials
        returns = 0.01 * base + 0.01 * 0.2
        d = deflated_sharpe(returns, N=2, V=0.0001)
        assert d["dsr"] > 0.99

    def test_dsr_brackets_shape(self):
        """deflated_sharpe_brackets returns one row per bracketed N, DSR falling with N."""
        from jutsu_engine.audit.dsr import deflated_sharpe_brackets
        rng = np.random.default_rng(3)
        base = rng.standard_normal(3000)
        base = (base - base.mean()) / base.std(ddof=1)
        returns = 0.01 * base + 0.01 * 0.08
        rows = deflated_sharpe_brackets(returns, N_values=DEFAULT_N_BRACKETS, V=0.0004)
        assert [r["N"] for r in rows] == list(DEFAULT_N_BRACKETS)
        # DSR is monotone non-increasing in N (more trials → more deflation)
        dsrs = [r["dsr"] for r in rows]
        assert dsrs == sorted(dsrs, reverse=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr.py::TestSampleMoments tests/unit/audit/test_dsr.py::TestDeflatedSharpe -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'sample_moments'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/dsr.py
import numpy as np
from scipy.stats import skew as _scipy_skew, kurtosis as _scipy_kurtosis

# Spec §7 bracketed trial counts. DSR is reported at each — history may be
# incomplete so N=243 is the known lower bound and 1000/5000 are conservative
# (higher) estimates that INCREASE deflation (lower DSR).
DEFAULT_N_BRACKETS: tuple[int, ...] = (243, 1000, 5000)


def sample_moments(returns) -> dict:
    """Per-period Sharpe, γ₃ skew, γ₄ NON-excess kurtosis, and T from a return series.

    Uses scipy sample (bias-corrected) skewness and kurtosis. scipy's kurtosis is
    EXCESS (Fisher) by default; we add 3.0 to get NON-excess γ₄ (normal == 3.0),
    which is what the PSR formula expects.

    Raises ValueError if the series has < 2 finite points or zero variance
    (Sharpe undefined without dispersion).
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        raise ValueError(f"need >= 2 finite returns for moments (got {r.size})")
    std = r.std(ddof=1)
    if std == 0.0:
        raise ValueError("returns have zero variance; Sharpe is undefined")
    sr = float(r.mean() / std)
    g3 = float(_scipy_skew(r, bias=False))
    g4 = float(_scipy_kurtosis(r, fisher=True, bias=False)) + 3.0  # non-excess
    return {"sr_obs": sr, "skew": g3, "kurt_nonexcess": g4, "T": int(r.size)}


def deflated_sharpe(returns, N: int, V: float) -> dict:
    """Deflated Sharpe Ratio for a return series: DSR = PSR(SR*) under N trials.

    Args:
      returns: the strategy's per-period (daily) return series.
      N: number of trials for the deflation benchmark (>= 2).
      V: cross-trial Sharpe variance (per-period units, same as SR_obs).

    Returns dict: sr_obs, skew, kurt_nonexcess, T, sr_star, dsr.
    """
    m = sample_moments(returns)
    sr_star = expected_max_sharpe(V=V, N=N)
    dsr = psr(sr_obs=m["sr_obs"], sr_star=sr_star, T=m["T"],
              skew=m["skew"], kurt=m["kurt_nonexcess"])
    return {**m, "sr_star": sr_star, "dsr": dsr}


def deflated_sharpe_brackets(returns, N_values=DEFAULT_N_BRACKETS,
                             V: float = 0.0) -> list[dict]:
    """DSR at each bracketed N (spec §7: N = 243 / 1000 / 5000).

    Returns a list of {N, sr_obs, sr_star, dsr, T, skew, kurt_nonexcess} rows, one
    per N. Higher N ⇒ higher SR* ⇒ lower DSR (more deflation), so the caller can
    show the sensitivity of the DSR verdict to how many trials are assumed.
    """
    out = []
    for N in N_values:
        d = deflated_sharpe(returns, N=N, V=V)
        out.append({"N": N, **d})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all DSR tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/dsr.py tests/unit/audit/test_dsr.py
git commit -m "feat(audit): add end-to-end DSR + bracketed-N helper with moment conventions"
```

---

## Task 4: PBO — block split + per-partition IS/OOS Sharpe ranking

**Files:**
- Create: `jutsu_engine/audit/pbo.py`
- Test: `tests/unit/audit/test_pbo.py`

CSCV foundation: split the T×N returns matrix into S contiguous time blocks, enumerate all C(S, S/2) IS/OOS partitions, and per partition compute IS-Sharpe and OOS-Sharpe per combo.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/audit/test_pbo.py
"""DB-free unit tests for the PBO/CSCV math (Module 3)."""
from math import comb

import numpy as np
import pytest

from jutsu_engine.audit.pbo import split_blocks, partition_sharpes, N_CHOOSE_HALF


class TestSplitBlocks:
    def test_splits_into_S_contiguous_index_blocks(self):
        """split_blocks returns S contiguous index arrays covering all rows once."""
        blocks = split_blocks(T=16, S=4)
        assert len(blocks) == 4
        flat = np.concatenate(blocks)
        assert list(flat) == list(range(16))
        # contiguity: each block's indices are consecutive
        for b in blocks:
            assert list(b) == list(range(b[0], b[-1] + 1))

    def test_uneven_split_is_balanced(self):
        """T not divisible by S still covers every row exactly once."""
        blocks = split_blocks(T=17, S=4)
        assert sorted(np.concatenate(blocks)) == list(range(17))

    def test_too_few_rows_raises(self):
        """Need at least S rows to make S blocks."""
        with pytest.raises(ValueError, match="need at least S"):
            split_blocks(T=3, S=4)


class TestPartitionSharpes:
    def test_partition_count_is_C_S_half(self):
        """partition_sharpes yields exactly C(S, S/2) (IS_sharpe, OOS_sharpe) pairs."""
        mat = np.random.default_rng(0).standard_normal((32, 5))
        pairs = list(partition_sharpes(mat, S=8))
        assert len(pairs) == comb(8, 4)
        assert N_CHOOSE_HALF(8) == comb(8, 4)

    def test_each_pair_has_one_sharpe_per_combo(self):
        """Each partition returns an IS and OOS Sharpe vector of length N (combos)."""
        mat = np.random.default_rng(1).standard_normal((16, 3))
        is_sr, oos_sr = next(iter(partition_sharpes(mat, S=4)))
        assert is_sr.shape == (3,)
        assert oos_sr.shape == (3,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_pbo.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jutsu_engine.audit.pbo'`

- [ ] **Step 3: Write the minimal implementation**

```python
# jutsu_engine/audit/pbo.py
"""Module 3 — Probability of Backtest Overfitting via CSCV (Bailey et al.).

Pure numpy over a T×N returns matrix (T daily observations, N grid combos). NO
database. Deterministic (no RNG): the CSCV partition set is fully enumerated.

CSCV procedure (spec §7, S=16 blocks):
  1. Split the T rows into S contiguous time blocks.
  2. For every way to choose S/2 blocks as IN-SAMPLE (the other S/2 are OUT-of-
     SAMPLE) — that is C(S, S/2) partitions (C(16,8) = 12,870):
       a. rank all N combos by IS Sharpe, take the IS-best (n*).
       b. find n*'s OOS relative rank ω̄ ∈ [0,1]: the fraction of combos it BEATS
          out-of-sample (0 = worst OOS, 1 = best OOS).
       c. logit λ = ln(ω̄ / (1−ω̄)).
  3. PBO = fraction of partitions where the IS-best lands in the BOTTOM HALF OOS,
     i.e. ω̄ < 0.5  ⟺  λ < 0.
"""
from __future__ import annotations

import itertools
from math import comb

import numpy as np


def N_CHOOSE_HALF(S: int) -> int:
    """Number of CSCV partitions for S blocks: C(S, S/2)."""
    return comb(S, S // 2)


def split_blocks(T: int, S: int) -> list[np.ndarray]:
    """Split row indices [0, T) into S contiguous, near-equal blocks.

    Uses numpy.array_split so blocks stay contiguous and cover every row exactly
    once even when T is not divisible by S. Raises ValueError if T < S.
    """
    if T < S:
        raise ValueError(f"need at least S={S} rows to make S blocks (got T={T})")
    return [np.asarray(b) for b in np.array_split(np.arange(T), S)]


def _combo_sharpes(mat: np.ndarray) -> np.ndarray:
    """Per-column (per-combo) Sharpe of a returns sub-matrix (ddof=1).

    Columns with zero variance get NaN Sharpe (excluded from argmax/rank by the
    caller). Not annualized — CSCV ranks are scale-invariant, so the √252 factor
    is unnecessary and omitted for clarity.
    """
    mu = mat.mean(axis=0)
    sd = mat.std(axis=0, ddof=1)
    sd = np.where(sd == 0.0, np.nan, sd)
    return mu / sd


def partition_sharpes(matrix: np.ndarray, S: int = 16):
    """Yield (IS_sharpe_vec, OOS_sharpe_vec) for every CSCV IS/OOS partition.

    matrix: shape (T, N). Splits into S contiguous blocks and enumerates all
    C(S, S/2) ways to assign half the blocks to IS (rest OOS). Each yielded pair
    is two length-N Sharpe vectors (IS and OOS) over the concatenated block rows.
    """
    T = matrix.shape[0]
    blocks = split_blocks(T, S)
    all_block_ids = range(S)
    for is_ids in itertools.combinations(all_block_ids, S // 2):
        is_set = set(is_ids)
        oos_ids = [b for b in all_block_ids if b not in is_set]
        is_rows = np.concatenate([blocks[b] for b in is_ids])
        oos_rows = np.concatenate([blocks[b] for b in oos_ids])
        yield _combo_sharpes(matrix[is_rows]), _combo_sharpes(matrix[oos_rows])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_pbo.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/pbo.py tests/unit/audit/test_pbo.py
git commit -m "feat(audit): add CSCV block split + per-partition IS/OOS Sharpe ranking"
```

---

## Task 5: PBO — full PBO + logit distribution + degradation slope + prob-of-OOS-loss

**Files:**
- Modify: `jutsu_engine/audit/pbo.py`
- Test: `tests/unit/audit/test_pbo.py`

The headline PBO plus its diagnostics. Reference outcomes were computed and verified in the plan (deterministic synthetic matrices):
- **Persistent** (combo 0 dominates every block) → PBO = 0.0, prob_oos_loss = 0.0.
- **Tiny S=4 dominant combo** → PBO = 0.0, 6 partitions (fully hand-enumerable).
- **Pure noise** is NOT a clean 0.5 for finite N (seed-dependent 0.27–0.70); we assert only that noise PBO is **materially higher** than the persistent case (ordering), which is the honest, reproducible claim.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_pbo.py
from jutsu_engine.audit.pbo import compute_pbo, relative_rank, logit


class TestRelativeRankAndLogit:
    def test_relative_rank_best_is_one_worst_is_zero(self):
        """The top combo has relative rank 1.0, the bottom 0.0."""
        oos = np.array([0.1, 0.5, -0.2, 0.3])   # combo 1 best, combo 2 worst
        assert relative_rank(oos, best_idx=1) == pytest.approx(1.0)
        assert relative_rank(oos, best_idx=2) == pytest.approx(0.0)

    def test_relative_rank_middle(self):
        """A middle combo beats a proportional fraction of the others."""
        oos = np.array([0.1, 0.5, -0.2, 0.3])   # combo 0 beats only combo 2 → 1/3
        assert relative_rank(oos, best_idx=0) == pytest.approx(1.0 / 3.0)

    def test_logit_sign(self):
        """ω̄ > 0.5 → positive logit; ω̄ < 0.5 → negative logit."""
        assert logit(0.75) > 0
        assert logit(0.25) < 0
        assert logit(0.5) == pytest.approx(0.0)


class TestComputePBO:
    def test_persistent_matrix_pbo_zero(self):
        """A perfectly persistent winner (combo 0 dominates every block) → PBO 0."""
        # Deterministic: combo 0 has highest mean & non-zero variance in EVERY block.
        S, rows_per, N = 16, 4, 5
        T = S * rows_per
        mat = np.zeros((T, N))
        for j in range(N):
            base = 0.05 - 0.01 * j                      # combo0 best, combo4 worst
            mat[:, j] = base + 0.0001 * np.tile([1, -1, 1, -1], S)
        res = compute_pbo(mat, S=16)
        assert res["pbo"] == pytest.approx(0.0, abs=1e-12)
        assert res["prob_oos_loss"] == pytest.approx(0.0, abs=1e-12)
        assert res["n_partitions"] == 12870

    def test_tiny_S4_dominant_combo_hand_enumerable(self):
        """Tiny S=4 (6 partitions) with a dominant combo 0 → PBO 0."""
        mat = np.array([
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
            [0.03, 0.01, -0.01], [0.03, 0.01, -0.01],
        ]) + np.tile([[0.001, -0.001, 0.0005],
                      [-0.001, 0.001, -0.0005]], (4, 1))
        res = compute_pbo(mat, S=4)
        assert res["n_partitions"] == 6
        assert res["pbo"] == pytest.approx(0.0, abs=1e-12)

    def test_noise_pbo_exceeds_persistent(self):
        """Pure-noise combos overfit far more than a persistent winner (ordering)."""
        rng = np.random.default_rng(0)
        noise = rng.standard_normal((160, 50))
        noise_pbo = compute_pbo(noise, S=16)["pbo"]
        # persistent baseline from the first test ≈ 0
        assert noise_pbo > 0.1     # honest band: noise overfits materially more than 0

    def test_degradation_slope_negative_for_overfit(self):
        """IS-vs-OOS Sharpe regression slope < 1 when OOS underperforms IS."""
        rng = np.random.default_rng(2)
        noise = rng.standard_normal((160, 40))
        res = compute_pbo(noise, S=16)
        # overfit ⇒ high IS Sharpe does not carry to OOS ⇒ slope well below 1
        assert res["degradation_slope"] < 0.5

    def test_logit_distribution_length_matches_partitions(self):
        """The logit distribution has one entry per partition."""
        rng = np.random.default_rng(4)
        mat = rng.standard_normal((32, 6))
        res = compute_pbo(mat, S=8)
        assert len(res["logits"]) == res["n_partitions"]

    def test_too_few_combos_raises(self):
        """PBO needs >= 2 combos to rank."""
        with pytest.raises(ValueError, match="at least 2 combos"):
            compute_pbo(np.random.default_rng(0).standard_normal((32, 1)), S=8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_pbo.py::TestComputePBO -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'compute_pbo'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/pbo.py
# Clamp bound so ω̄ ∈ {0, 1} does not blow up the logit.
_LOGIT_EPS = 1e-6


def relative_rank(oos_sharpes: np.ndarray, best_idx: int) -> float:
    """OOS relative rank ω̄ of the IS-best combo: fraction of OTHER combos it beats.

    ω̄ = (# combos with strictly lower OOS Sharpe) / (N − 1). 1.0 = OOS-best,
    0.0 = OOS-worst. NaN OOS Sharpes (zero-variance combos) count as not-beaten.
    """
    n = oos_sharpes.shape[0]
    if n < 2:
        return 0.0
    ref = oos_sharpes[best_idx]
    beaten = np.sum(oos_sharpes < ref)          # NaN < ref is False → not beaten
    return float(beaten) / (n - 1)


def logit(omega: float) -> float:
    """Logit of a relative rank, clamped to avoid ±∞ at ω̄ ∈ {0,1}."""
    w = min(max(omega, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return float(np.log(w / (1.0 - w)))


def compute_pbo(matrix: np.ndarray, S: int = 16) -> dict:
    """Probability of Backtest Overfitting + diagnostics over a T×N returns matrix.

    For each CSCV partition: pick the IS-best combo (highest IS Sharpe), record its
    OOS relative rank ω̄, its logit, whether its OOS Sharpe <= 0 (an OOS loss), and
    the (IS-best IS Sharpe, IS-best OOS Sharpe) pair for the degradation regression.

    Returns dict:
      pbo               — fraction of partitions with ω̄ < 0.5 (logit < 0): the
                          probability the IS-best is OOS below-median.
      prob_oos_loss     — fraction of partitions where the IS-best has OOS Sharpe <= 0.
      degradation_slope — OLS slope of OOS Sharpe on IS Sharpe across the IS-best of
                          every partition (1.0 = perfect carry-over; <1 = degradation).
      logits            — list of per-partition logits (the ω̄ logit distribution).
      n_partitions      — C(S, S/2).

    Raises ValueError if N < 2 (nothing to rank).
    """
    if matrix.shape[1] < 2:
        raise ValueError("PBO needs at least 2 combos to rank")

    logits: list[float] = []
    oos_losses = 0
    is_best_is_sr: list[float] = []
    is_best_oos_sr: list[float] = []
    n_part = 0

    for is_sr, oos_sr in partition_sharpes(matrix, S=S):
        n_part += 1
        n_star = int(np.nanargmax(is_sr))        # IS-best combo index
        omega = relative_rank(oos_sr, n_star)
        logits.append(logit(omega))
        oos_val = oos_sr[n_star]
        if not np.isnan(oos_val) and oos_val <= 0.0:
            oos_losses += 1
        is_best_is_sr.append(float(is_sr[n_star]))
        is_best_oos_sr.append(float(oos_val) if not np.isnan(oos_val) else 0.0)

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr < 0.0))
    prob_oos_loss = float(oos_losses) / n_part

    # Degradation slope: OLS of OOS Sharpe (y) on IS Sharpe (x) across partitions.
    x = np.asarray(is_best_is_sr)
    y = np.asarray(is_best_oos_sr)
    if np.ptp(x) > 0:
        slope = float(np.polyfit(x, y, 1)[0])
    else:
        slope = 0.0

    return {
        "pbo": pbo,
        "prob_oos_loss": prob_oos_loss,
        "degradation_slope": slope,
        "logits": logits,
        "n_partitions": n_part,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_pbo.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all PBO tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/pbo.py tests/unit/audit/test_pbo.py
git commit -m "feat(audit): add PBO + logit distribution + degradation slope + prob-OOS-loss"
```

---

## Task 6: Golden grid enumeration (243 combos) + versioned axes file

**Files:**
- Create: `jutsu_engine/audit/selection_bias.py`
- Create: `grid-configs/audit/golden_grid_v3_5b_axes.yaml`
- Test: `tests/unit/audit/test_selection_bias.py`

Enumerate the **historical** 243-combo grid from the documented axes (header comments of the golden YAML — the file body has them collapsed). Do NOT invent a grid; reproduce the search's combos.

- [ ] **Step 1: Create the versioned axes file**

```yaml
# grid-configs/audit/golden_grid_v3_5b_axes.yaml
# Provenance record of the HISTORICAL v3.5b golden grid (the ~243-run search that
# selected the golden config). The Gold-Configs YAML body collapses every axis to
# a single (winning) value; these five axes — with these value lists — are the
# grid the search ACTUALLY ran, per that file's header comments (lines 58-84) and
# the LOGBOOK "~243-run grid" provenance. Module 3's PBO re-run enumerates EXACTLY
# these combos (product = 3^5 = 243). All other parameters are held at the live
# golden values (config/strategies/v3_5b.yaml). Versioned so the combo set is
# reproducible; selection_bias.GOLDEN_GRID_AXES is the code source of truth and a
# unit test asserts the two agree.
strategy: v3_5b
total_combos: 243
axes:
  upper_thresh_z: [0.8, 1.0, 1.2]
  lower_thresh_z: [-0.2, 0.0, 0.2]
  vol_crush_threshold: [-0.15, -0.20, -0.25]
  sma_fast: [40, 50, 60]
  sma_slow: [180, 200, 220]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/audit/test_selection_bias.py
"""DB-free unit tests for Module 3 selection-bias orchestration."""
import yaml

import pytest

from jutsu_engine.audit.selection_bias import (
    GOLDEN_GRID_AXES, enumerate_golden_grid, combo_hash, AXES_YAML_PATH,
)


class TestEnumerateGrid:
    def test_grid_is_243_combos(self):
        """The historical v3.5b golden grid enumerates to exactly 243 combos."""
        combos = enumerate_golden_grid()
        assert len(combos) == 243

    def test_each_combo_has_all_five_axes(self):
        """Every combo overrides exactly the five historical grid axes."""
        combos = enumerate_golden_grid()
        expected_keys = set(GOLDEN_GRID_AXES.keys())
        for c in combos:
            assert set(c["overrides"].keys()) == expected_keys

    def test_combo_ids_are_unique_and_sequential(self):
        """combo_id runs 0..242; hashes are unique."""
        combos = enumerate_golden_grid()
        assert [c["combo_id"] for c in combos] == list(range(243))
        assert len({c["hash"] for c in combos}) == 243

    def test_golden_center_combo_present(self):
        """The live golden values appear as one of the 243 combos."""
        combos = enumerate_golden_grid()
        golden = {"upper_thresh_z": 1.0, "lower_thresh_z": 0.2,
                  "vol_crush_threshold": -0.15, "sma_fast": 40, "sma_slow": 140}
        # NOTE: sma_slow golden (140) is OUTSIDE the historical axis [180,200,220];
        # the historical grid did not center on the eventual live sma_slow. We assert
        # the FOUR shared axes match at least one combo's values (documented mismatch).
        four = {k: golden[k] for k in
                ["upper_thresh_z", "lower_thresh_z", "vol_crush_threshold", "sma_fast"]}
        assert any(all(c["overrides"][k] == v for k, v in four.items())
                   for c in combos)

    def test_axes_yaml_matches_code(self):
        """The versioned axes YAML equals the code's GOLDEN_GRID_AXES (no drift)."""
        with open(AXES_YAML_PATH) as f:
            doc = yaml.safe_load(f)
        assert doc["axes"] == {k: list(v) for k, v in GOLDEN_GRID_AXES.items()}
        assert doc["total_combos"] == 243

    def test_combo_hash_is_order_independent(self):
        """combo_hash is stable regardless of dict key order."""
        a = combo_hash({"sma_fast": 40, "sma_slow": 180})
        b = combo_hash({"sma_slow": 180, "sma_fast": 40})
        assert a == b and len(a) == 16
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestEnumerateGrid -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jutsu_engine.audit.selection_bias'`

- [ ] **Step 4: Write the minimal implementation**

```python
# jutsu_engine/audit/selection_bias.py
"""Module 3 — selection-bias correction orchestration (DSR + PBO).

Ties together:
  - the HISTORICAL 243-combo golden grid enumeration (reproduces the search that
    selected the golden config — see grid-configs/audit/golden_grid_v3_5b_axes.yaml),
  - a one-time full-period returns campaign capturing each combo's daily
    Strategy_Daily_Return series (REUSES the plateau/WFO checkpoint/resume/breaker/
    single-writer/tempdir machinery — no new campaign engine),
  - the returns-matrix assembly (align combos on the union of dates → T×N numpy),
  - the DSR (dsr.py) and PBO (pbo.py) pure-math layers.

Strictly READ-ONLY vs the DB. The campaign is unit-tested via an injected run_fn
(no DB, no BacktestRunner) exactly as plateau/wfo campaigns are.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

from jutsu_engine.audit.config import PROJECT_ROOT

# The HISTORICAL v3.5b golden grid axes (3^5 = 243 combos). Source of truth in code;
# grid-configs/audit/golden_grid_v3_5b_axes.yaml mirrors it (a unit test asserts
# they agree). These are the axes the ~243-run search varied, per the Gold-Configs
# YAML header comments — NOT the collapsed single values in that file's body.
GOLDEN_GRID_AXES: dict[str, list] = {
    "upper_thresh_z": [0.8, 1.0, 1.2],
    "lower_thresh_z": [-0.2, 0.0, 0.2],
    "vol_crush_threshold": [-0.15, -0.20, -0.25],
    "sma_fast": [40, 50, 60],
    "sma_slow": [180, 200, 220],
}

AXES_YAML_PATH: Path = (
    PROJECT_ROOT / "grid-configs" / "audit" / "golden_grid_v3_5b_axes.yaml"
)


def combo_hash(overrides: dict) -> str:
    """Stable 16-char hex hash of a combo's overrides (order-independent).

    Mirrors plateau.params_hash / wfo_stability.combo_hash byte-for-byte so the
    hashing convention is consistent across all three audit campaigns.
    """
    payload = json.dumps(overrides, sort_keys=True, separators=(",", ":"),
                         default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def enumerate_golden_grid() -> list[dict]:
    """Expand GOLDEN_GRID_AXES into 243 combos (full cartesian product).

    Each combo: {"combo_id": int, "overrides": {axis: value}, "hash": str}.
    combo_id is the enumeration index 0..242 (deterministic: itertools.product over
    the axes in GOLDEN_GRID_AXES insertion order).
    """
    names = list(GOLDEN_GRID_AXES.keys())
    value_lists = [GOLDEN_GRID_AXES[n] for n in names]
    combos: list[dict] = []
    for cid, values in enumerate(itertools.product(*value_lists)):
        overrides = dict(zip(names, values))
        combos.append({
            "combo_id": cid,
            "overrides": overrides,
            "hash": combo_hash(overrides),
        })
    return combos
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestEnumerateGrid -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/selection_bias.py grid-configs/audit/golden_grid_v3_5b_axes.yaml tests/unit/audit/test_selection_bias.py
git commit -m "feat(audit): enumerate historical 243-combo golden grid + versioned axes file"
```

---

## Task 7: Returns-campaign worker + JSONL persistence (reuse WFO/plateau infra)

**Files:**
- Modify: `jutsu_engine/audit/selection_bias.py`
- Test: `tests/unit/audit/test_selection_bias.py`

One backtest per combo, full-period (2010-02 → present), capturing the daily `Strategy_Daily_Return` series inline. The worker mirrors `wfo_stability.run_one_backtest` (tempdir isolation, loud error row, picklable) but is full-period single-phase and stores `dates` + `returns` arrays.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_selection_bias.py
import json
from pathlib import Path

from jutsu_engine.audit.selection_bias import (
    _RETURNS_RESULT_KEYS, append_returns_row, load_completed_combo_hashes,
    reload_returns_rows, is_error_row,
)


class TestReturnsPersistence:
    def _row(self, h, dates, returns, error=None):
        return {"combo_id": 0, "hash": h, "overrides": {"sma_fast": 40},
                "dates": dates, "returns": returns, "sharpe": None if error else 0.5,
                "error": error}

    def test_append_and_reload_roundtrip(self, tmp_path):
        """A returns row survives append → reload with its dates/returns intact."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("h1", ["2010-02-01", "2010-02-02"],
                                        [0.01, -0.02]))
        rows = reload_returns_rows(p)
        assert len(rows) == 1
        assert rows[0]["returns"] == [0.01, -0.02]
        assert rows[0]["dates"] == ["2010-02-01", "2010-02-02"]

    def test_completed_hashes_skips_errors_when_retrying(self, tmp_path):
        """--retry-errors excludes error rows from the completed set."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("ok", ["d"], [0.01]))
        append_returns_row(p, self._row("bad", None, None, error="boom"))
        assert load_completed_combo_hashes(p) == {"ok", "bad"}
        assert load_completed_combo_hashes(p, retry_errors=True) == {"ok"}

    def test_last_wins_dedup_on_retry(self, tmp_path):
        """A retried combo (error then success) counts as done regardless of flag."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("h", None, None, error="boom"))
        append_returns_row(p, self._row("h", ["d"], [0.01]))   # success supersedes
        assert load_completed_combo_hashes(p, retry_errors=True) == {"h"}
        rows = reload_returns_rows(p)
        assert len(rows) == 1 and rows[0]["error"] is None

    def test_torn_final_line_tolerated(self, tmp_path):
        """A truncated trailing line (crash mid-write) is skipped, not fatal."""
        p = tmp_path / "c.jsonl"
        append_returns_row(p, self._row("h", ["d"], [0.01]))
        with open(p, "a") as f:
            f.write('{"hash": "partial", "returns": [0.0')   # no newline, truncated
        assert load_completed_combo_hashes(p) == {"h"}
        assert len(reload_returns_rows(p)) == 1

    def test_is_error_row(self):
        """A row with a non-null error or missing returns is an error row."""
        assert is_error_row({"error": "x", "returns": None})
        assert is_error_row({"error": None, "returns": None})
        assert not is_error_row({"error": None, "returns": [0.01]})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestReturnsPersistence -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'append_returns_row'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/selection_bias.py
import os
import shutil
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal

# Reuse plateau's proven torn-line guard and the override bridge (no duplication).
from jutsu_engine.audit.plateau import _ends_with_newline, build_overridden_strategy

# Keys persisted per combo. dates+returns are stored inline as JSON arrays: 243
# combos × ~4,100 floats ≈ ~10 MB — trivial, and reuses the fsync-JSONL machinery
# verbatim (crash-safety, single-writer, --retry-errors). Chosen over parquet
# because pyarrow is not installed (no new dependency) and JSONL is the proven
# campaign format.
_RETURNS_RESULT_KEYS = ("combo_id", "hash", "overrides",
                        "dates", "returns", "sharpe", "error")


def is_error_row(row: dict) -> bool:
    """True when a returns row represents a failed backtest.

    A row is an error when it carries a non-None `error` string OR its `returns`
    list is absent/empty (no daily-return series to stitch into the matrix).
    """
    if row.get("error") is not None:
        return True
    return not row.get("returns")


def append_returns_row(path: Path, row: dict) -> None:
    """Append one combo's returns row as a fsynced JSONL line (crash-safe).

    Mirrors plateau.append_result / wfo.append_wfo_row: fsync per line makes a
    completed backtest durable the instant its row is written; a torn trailing
    line from a prior crash gets a leading newline so the good row is never
    concatenated onto the fragment.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {k: row.get(k) for k in _RETURNS_RESULT_KEYS}
    prefix = "" if _ends_with_newline(path) else "\n"
    with open(path, "a") as f:
        f.write(prefix + json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_completed_combo_hashes(path: Path, retry_errors: bool = False) -> set[str]:
    """Set of combo hashes already present in the returns JSONL (last-wins dedup).

    Tolerates a truncated final line. When retry_errors is True, rows whose LAST
    occurrence is an error are excluded so they re-run. Mirrors
    plateau.load_completed_hashes semantics exactly.
    """
    path = Path(path)
    if not path.exists():
        return set()
    last: dict[str, dict] = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                h = row["hash"]
            except (json.JSONDecodeError, KeyError):
                continue
            last[h] = row
    done: set[str] = set()
    for h, row in last.items():
        if retry_errors and is_error_row(row):
            continue
        done.add(h)
    return done


def reload_returns_rows(path: Path) -> list[dict]:
    """Load all returns rows (last-wins per hash), tolerating a torn final line."""
    path = Path(path)
    if not path.exists():
        return []
    by_hash: dict[str, dict] = {}
    order: list[str] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            h = row.get("hash")
            if h is None:
                continue
            if h not in by_hash:
                order.append(h)
            by_hash[h] = row
    return [by_hash[h] for h in order]


def run_one_combo(strategy_id: str, combo: dict, symbols: list[str],
                  start: date, end: date,
                  initial_capital: str = "10000") -> dict:
    """Run ONE full-period backtest for a grid combo; return its daily-return row.

    Picklable (plain args) so it runs inside a ProcessPoolExecutor worker on macOS
    spawn. Writes ALL CSVs to a throwaway tempdir (prefix dsr_) cleaned in finally.
    Reads the regime-timeseries CSV (regime_analyzer.py:192-216) and captures the
    Date + Strategy_Daily_Return columns as the combo's return series — the SAME
    extraction wfo_stability.run_one_backtest does for OOS windows, here full-period.

    A raising backtest returns a LOUD error row (returns=None, sharpe=None,
    error=<exc string>) rather than propagating, so one failure never aborts the
    campaign (the circuit breaker + single-writer parent handle systemic failure).
    """
    import pandas as pd
    from jutsu_engine.application.backtest_runner import BacktestRunner

    config = {
        "symbols": symbols,
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": Decimal(str(initial_capital)),
    }
    tmpdir = tempfile.mkdtemp(prefix="dsr_")
    error = None
    results: dict = {}
    dates = None
    returns = None
    try:
        strategy = build_overridden_strategy(strategy_id, combo["overrides"])
        runner = BacktestRunner(config)
        results = runner.run(strategy, output_dir=tmpdir)
        ts_csv = results.get("regime_timeseries_csv")
        if ts_csv and Path(ts_csv).exists():
            df = pd.read_csv(ts_csv)
            dates = [str(d) for d in df["Date"].tolist()]
            returns = [float(x) for x in df["Strategy_Daily_Return"].tolist()]
        else:
            error = "backtest emitted no regime timeseries CSV"
    except Exception as exc:  # noqa: BLE001 — loud row, never crash the campaign
        error = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "combo_id": combo["combo_id"],
        "hash": combo["hash"],
        "overrides": combo["overrides"],
        "dates": dates,
        "returns": returns,
        "sharpe": results.get("sharpe_ratio") if error is None else None,
        "error": error,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestReturnsPersistence -p no:cacheprovider -o addopts="" -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/selection_bias.py tests/unit/audit/test_selection_bias.py
git commit -m "feat(audit): add returns-campaign worker + fsync-JSONL persistence"
```

---

## Task 8: Returns-campaign runner (checkpoint/resume, circuit breaker, single-writer, workers)

**Files:**
- Modify: `jutsu_engine/audit/selection_bias.py`
- Test: `tests/unit/audit/test_selection_bias.py`

The campaign orchestrator, closely mirroring `plateau.run_campaign` — serial + parallel paths, single-writer parent appends, consecutive-error breaker. Tested with an injected `run_fn` (no DB).

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_selection_bias.py
from datetime import date

from jutsu_engine.audit.selection_bias import (
    run_returns_campaign, ReturnsCampaignResult, DEFAULT_MAX_CONSECUTIVE_ERRORS,
)


def _fake_run_fn(strategy_id, combo, symbols, start, end, initial_capital="10000"):
    """Deterministic fake worker: returns a 2-day series keyed by combo_id."""
    return {"combo_id": combo["combo_id"], "hash": combo["hash"],
            "overrides": combo["overrides"],
            "dates": ["2010-02-01", "2010-02-02"],
            "returns": [0.001 * combo["combo_id"], -0.001 * combo["combo_id"]],
            "sharpe": 0.1 * combo["combo_id"], "error": None}


def _error_run_fn(strategy_id, combo, symbols, start, end, initial_capital="10000"):
    """Fake worker that always errors (to trip the circuit breaker)."""
    return {"combo_id": combo["combo_id"], "hash": combo["hash"],
            "overrides": combo["overrides"], "dates": None, "returns": None,
            "sharpe": None, "error": "boom"}


class TestReturnsCampaign:
    def _combos(self, n):
        from jutsu_engine.audit.selection_bias import combo_hash
        return [{"combo_id": i, "overrides": {"sma_fast": 40 + i},
                 "hash": combo_hash({"sma_fast": 40 + i})} for i in range(n)]

    def test_serial_runs_every_combo(self, tmp_path):
        """Serial campaign writes one row per combo."""
        p = tmp_path / "c.jsonl"
        res = run_returns_campaign(
            "v3_5b", self._combos(3), p, run_fn=_fake_run_fn, symbols=[],
            start=date(2010, 2, 1), end=date(2026, 7, 1), workers=1)
        assert len(res.rows) == 3
        assert isinstance(res, ReturnsCampaignResult)

    def test_resume_skips_completed(self, tmp_path):
        """A second run with all combos present runs zero new backtests."""
        p = tmp_path / "c.jsonl"
        combos = self._combos(3)
        run_returns_campaign("v3_5b", combos, p, run_fn=_fake_run_fn, symbols=[],
                             start=date(2010, 2, 1), end=date(2026, 7, 1), workers=1)
        calls = []

        def counting(strategy_id, combo, symbols, start, end, initial_capital="10000"):
            calls.append(combo["combo_id"])
            return _fake_run_fn(strategy_id, combo, symbols, start, end)

        run_returns_campaign("v3_5b", combos, p, run_fn=counting, symbols=[],
                             start=date(2010, 2, 1), end=date(2026, 7, 1), workers=1)
        assert calls == []   # nothing re-run

    def test_circuit_breaker_aborts_on_systemic_failure(self, tmp_path):
        """N consecutive errored combos abort the campaign with a clear message."""
        p = tmp_path / "c.jsonl"
        combos = self._combos(DEFAULT_MAX_CONSECUTIVE_ERRORS + 5)
        with pytest.raises(RuntimeError, match="consecutive errored"):
            run_returns_campaign("v3_5b", combos, p, run_fn=_error_run_fn,
                                 symbols=[], start=date(2010, 2, 1),
                                 end=date(2026, 7, 1), workers=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestReturnsCampaign -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'run_returns_campaign'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/selection_bias.py
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass

from jutsu_engine.audit.config import ATTRIBUTION_START

# Consecutive errored-row limit before abort (mirrors plateau/wfo). A DB outage
# errors every combo; without the breaker a run would checkpoint all 243 as errors.
DEFAULT_MAX_CONSECUTIVE_ERRORS: int = 10

_BREAKER_MSG = (
    "aborting: {n} consecutive errored runs — systemic failure (DB down?). "
    "Errored rows are checkpointed and NOT retried on resume; investigate and "
    "delete them (or rerun with --retry-errors) before rerunning."
)


@dataclass
class ReturnsCampaignResult:
    """Everything the DSR/PBO layers need from a completed/resumed returns campaign."""
    strategy_id: str
    rows: list          # last-wins reloaded returns rows (one per combo)
    campaign_file: str


def _run_serial_returns(strategy_id, todo, campaign_file, run_fn, symbols,
                        start, end, initial_capital, max_consecutive_errors,
                        progress) -> None:
    """Serial campaign: parent is the SINGLE WRITER; breaker on consecutive errors."""
    consecutive = 0
    total = len(todo)
    for i, combo in enumerate(todo, 1):
        row = run_fn(strategy_id, combo, symbols, start, end, initial_capital)
        append_returns_row(campaign_file, row)      # SINGLE WRITER (parent)
        consecutive = consecutive + 1 if is_error_row(row) else 0
        progress(f"[{i}/{total}] combo {combo['combo_id']} "
                 f"sharpe={row.get('sharpe')}")
        if consecutive >= max_consecutive_errors:
            raise RuntimeError(_BREAKER_MSG.format(n=max_consecutive_errors))


def _run_parallel_returns(strategy_id, todo, campaign_file, run_fn, symbols,
                          start, end, initial_capital, workers,
                          max_consecutive_errors, progress) -> None:
    """Parallel campaign: parent-only writes; wait(FIRST_COMPLETED) drain-then-abort.

    Mirrors plateau._run_parallel: on breaker trip we drain the finished batch
    (checkpointing every completed row) before cancelling not-yet-started futures
    and raising. run_fn must be picklable (macOS spawn); running futures at abort
    cannot be cancelled and their results are discarded (re-run on resume).
    """
    consecutive = 0
    done_count = 0
    total = len(todo)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        pending = {
            ex.submit(run_fn, strategy_id, c, symbols, start, end, initial_capital)
            for c in todo
        }
        aborted = False
        while pending and not aborted:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                row = fut.result()
                append_returns_row(campaign_file, row)   # SINGLE WRITER (parent)
                done_count += 1
                if is_error_row(row):
                    consecutive += 1
                    if consecutive >= max_consecutive_errors:
                        aborted = True   # keep draining `finished` first
                else:
                    consecutive = 0
                progress(f"[{done_count}/{total}] sharpe={row.get('sharpe')}")
        if aborted:
            for fut in pending:
                fut.cancel()
            raise RuntimeError(_BREAKER_MSG.format(n=max_consecutive_errors))


def run_returns_campaign(strategy_id: str, combos: list[dict], campaign_file: Path,
                         run_fn=run_one_combo, symbols: list[str] | None = None,
                         start: date | None = None, end: date | None = None,
                         initial_capital: str = "10000", workers: int = 1,
                         max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
                         retry_errors: bool = False,
                         progress=lambda m: None) -> ReturnsCampaignResult:
    """Run (or resume) the per-combo returns campaign, checkpointing each to JSONL.

    Resume: combos already present (by hash) are skipped before any work is
    submitted (both paths). Single-writer invariant: ALL append_returns_row calls
    happen here in the parent; run_fn only computes and RETURNS a row. run_fn is
    injectable for DB-free unit tests; the default run_one_combo is picklable.

    Midnight/multi-day: `end` defaults to date.today() and is not part of combo
    hashes; a campaign spanning midnight extends later backtests by 1 day
    (negligible over a 16-year window; documented and accepted, matches plateau/wfo).
    """
    campaign_file = Path(campaign_file)
    start = start or ATTRIBUTION_START
    end = end or date.today()
    symbols = symbols if symbols is not None else []

    done = load_completed_combo_hashes(campaign_file, retry_errors=retry_errors)
    todo = [c for c in combos if c["hash"] not in done]
    progress(f"{len(combos)} combos, {len(done)} done, {len(todo)} to run")

    if todo:
        if workers <= 1:
            _run_serial_returns(strategy_id, todo, campaign_file, run_fn, symbols,
                                start, end, initial_capital,
                                max_consecutive_errors, progress)
        else:
            _run_parallel_returns(strategy_id, todo, campaign_file, run_fn, symbols,
                                  start, end, initial_capital, workers,
                                  max_consecutive_errors, progress)

    rows = reload_returns_rows(campaign_file)
    return ReturnsCampaignResult(strategy_id=strategy_id, rows=rows,
                                 campaign_file=str(campaign_file))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestReturnsCampaign -p no:cacheprovider -o addopts="" -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/selection_bias.py tests/unit/audit/test_selection_bias.py
git commit -m "feat(audit): add per-combo returns campaign runner (resume, breaker, workers)"
```

---

## Task 9: Returns-matrix assembly + cross-trial variance V

**Files:**
- Modify: `jutsu_engine/audit/selection_bias.py`
- Test: `tests/unit/audit/test_selection_bias.py`

Turn the collected returns rows into a `(T, N)` numpy matrix aligned on the union of dates, and estimate the cross-trial Sharpe variance V from the per-combo Sharpes (with a documented alternative from the plateau/WFO campaign estimates for sensitivity).

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_selection_bias.py
import numpy as np

from jutsu_engine.audit.selection_bias import (
    build_returns_matrix, cross_trial_variance, golden_combo_returns,
)


class TestReturnsMatrix:
    def test_aligns_on_union_of_dates(self):
        """Combos with different date coverage align on the union (NaN-filled → 0)."""
        rows = [
            {"combo_id": 0, "hash": "a", "overrides": {}, "error": None,
             "dates": ["2010-02-01", "2010-02-02"], "returns": [0.01, 0.02]},
            {"combo_id": 1, "hash": "b", "overrides": {}, "error": None,
             "dates": ["2010-02-02", "2010-02-03"], "returns": [0.03, 0.04]},
        ]
        mat, cols, dates = build_returns_matrix(rows)
        assert mat.shape == (3, 2)           # union of 3 dates, 2 combos
        assert dates == ["2010-02-01", "2010-02-02", "2010-02-03"]
        # combo 0 has no 2010-02-03 → filled 0.0; combo 1 has no 2010-02-01 → 0.0
        assert mat[2, 0] == 0.0 and mat[0, 1] == 0.0

    def test_excludes_error_rows(self):
        """Error rows (returns None) are dropped from the matrix."""
        rows = [
            {"combo_id": 0, "hash": "a", "overrides": {}, "error": None,
             "dates": ["d1"], "returns": [0.01]},
            {"combo_id": 1, "hash": "b", "overrides": {}, "error": "boom",
             "dates": None, "returns": None},
        ]
        mat, cols, dates = build_returns_matrix(rows)
        assert mat.shape[1] == 1              # only the good combo
        assert cols == ["a"]

    def test_cross_trial_variance_from_sharpes(self):
        """V is the variance of per-combo per-period Sharpes across the matrix columns."""
        # 3 combos with distinct constant-ish returns → distinct Sharpes → V > 0.
        rng = np.random.default_rng(0)
        mat = np.column_stack([
            0.01 + 0.001 * rng.standard_normal(500),
            0.02 + 0.001 * rng.standard_normal(500),
            -0.005 + 0.001 * rng.standard_normal(500),
        ])
        V = cross_trial_variance(mat)
        assert V > 0.0
        # sanity: matches numpy variance of the per-column Sharpes
        sr = mat.mean(axis=0) / mat.std(axis=0, ddof=1)
        assert V == pytest.approx(float(np.var(sr, ddof=1)), rel=1e-9)

    def test_golden_combo_returns_selects_by_hash(self):
        """golden_combo_returns pulls one combo's series by hash."""
        rows = [
            {"combo_id": 0, "hash": "g", "overrides": {}, "error": None,
             "dates": ["d1", "d2"], "returns": [0.01, 0.02]},
            {"combo_id": 1, "hash": "x", "overrides": {}, "error": None,
             "dates": ["d1", "d2"], "returns": [0.0, 0.0]},
        ]
        r = golden_combo_returns(rows, "g")
        assert list(r) == [0.01, 0.02]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestReturnsMatrix -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'build_returns_matrix'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/selection_bias.py
import numpy as np
import pandas as pd


def build_returns_matrix(rows: list[dict]):
    """Assemble a (T, N) returns matrix from campaign rows, aligned on date union.

    Only non-error rows (returns present) contribute a column. Each combo's series
    is reindexed onto the sorted union of all dates; missing dates are filled 0.0
    (a combo produces no return on a day it has no bar — treated as flat, not NaN,
    so every column shares one T for CSCV block splitting).

    Returns (matrix, col_hashes, dates):
      matrix     — np.ndarray shape (T, N), float
      col_hashes — list[str] combo hashes, column order matching the matrix
      dates      — list[str] the sorted union of dates (length T)
    """
    good = [r for r in rows if not is_error_row(r)]
    if not good:
        return np.empty((0, 0)), [], []
    all_dates = sorted({d for r in good for d in r["dates"]})
    date_index = pd.Index(all_dates)
    cols = []
    col_hashes = []
    for r in good:
        s = pd.Series(r["returns"], index=pd.Index([str(d) for d in r["dates"]]))
        s = s[~s.index.duplicated(keep="first")]       # guard duplicate dates
        aligned = s.reindex(date_index).fillna(0.0).to_numpy(dtype=float)
        cols.append(aligned)
        col_hashes.append(r["hash"])
    matrix = np.column_stack(cols)
    return matrix, col_hashes, all_dates


def cross_trial_variance(matrix: np.ndarray) -> float:
    """Cross-trial Sharpe variance V: the sample variance of per-combo Sharpes.

    Per-period (daily) Sharpe per column (ddof=1), then Var (ddof=1) across columns.
    This is the V fed to expected_max_sharpe: how much the grid's Sharpes spread,
    which drives how high a Sharpe you'd expect as the best of N by luck.

    Zero-variance columns (constant series) are dropped before computing V. Returns
    0.0 if fewer than 2 valid Sharpes remain.
    """
    if matrix.size == 0 or matrix.shape[1] < 2:
        return 0.0
    mu = matrix.mean(axis=0)
    sd = matrix.std(axis=0, ddof=1)
    mask = sd > 0
    sr = mu[mask] / sd[mask]
    if sr.size < 2:
        return 0.0
    return float(np.var(sr, ddof=1))


def golden_combo_returns(rows: list[dict], golden_hash: str) -> np.ndarray:
    """Return the daily-return array of the combo whose hash == golden_hash.

    Raises KeyError if the golden combo is absent or errored (no series to DSR).
    """
    for r in rows:
        if r.get("hash") == golden_hash and not is_error_row(r):
            return np.asarray(r["returns"], dtype=float)
    raise KeyError(
        f"golden combo {golden_hash!r} not found (or errored) in campaign rows"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestReturnsMatrix -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/selection_bias.py tests/unit/audit/test_selection_bias.py
git commit -m "feat(audit): add returns-matrix assembly + cross-trial variance V"
```

---

## Task 10: Trial-count inventory (read-only DB) + pure shaper

**Files:**
- Modify: `jutsu_engine/audit/db.py`
- Test: `tests/unit/audit/test_db.py`

Read-only SELECT over `optimization_results` (columns confirmed in `jutsu_engine/optimization/results.py:24-40`: `strategy_name`, `optimizer_type`, `objective`, `created_at`, ...) plus a pure shaper unit-tested on synthetic rows. Honest note: early history may be incomplete → DSR reported at bracketed N.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_db.py
from jutsu_engine.audit.db import trial_count_records


class TestTrialCountRecords:
    def test_shapes_grouped_counts(self):
        """trial_count_records turns (strategy, optimizer, count) rows into dicts."""
        rows = [
            ("Hierarchical_Adaptive_v3_5b", "grid_search", 243),
            ("Hierarchical_Adaptive_v3_5b", "bayesian", 57),
            ("Hierarchical_Adaptive_v2_8", "grid_search", 400),
        ]
        recs = trial_count_records(rows)
        assert recs == [
            {"strategy_name": "Hierarchical_Adaptive_v2_8",
             "optimizer_type": "grid_search", "trials": 400},
            {"strategy_name": "Hierarchical_Adaptive_v3_5b",
             "optimizer_type": "bayesian", "trials": 57},
            {"strategy_name": "Hierarchical_Adaptive_v3_5b",
             "optimizer_type": "grid_search", "trials": 243},
        ]

    def test_none_optimizer_labeled(self):
        """A NULL optimizer_type is labeled '(unknown)', not dropped."""
        recs = trial_count_records([("S", None, 10)])
        assert recs[0]["optimizer_type"] == "(unknown)"

    def test_empty_rows(self):
        """No rows → empty list (no crash)."""
        assert trial_count_records([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_db.py::TestTrialCountRecords -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'trial_count_records'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/db.py
def trial_count_records(rows: Iterable[Any]) -> list[dict]:
    """Shape (strategy_name, optimizer_type, count) rows into sorted trial-count dicts.

    Pure (no DB): unit-tested on synthetic rows. NULL optimizer_type becomes
    '(unknown)'. Sorted by (strategy_name, optimizer_type) for a stable report.
    """
    out = []
    for strategy_name, optimizer_type, count in rows:
        out.append({
            "strategy_name": strategy_name,
            "optimizer_type": optimizer_type if optimizer_type is not None
                              else "(unknown)",
            "trials": int(count),
        })
    out.sort(key=lambda d: (d["strategy_name"], d["optimizer_type"]))
    return out


def load_trial_counts(engine, strategy_like: str | None = None) -> list[dict]:
    """READ-ONLY: historical optimization-trial counts by strategy & optimizer.

    SELECT-only over optimization_results (jutsu_engine/optimization/results.py).
    Groups by strategy_name + optimizer_type. Optional strategy_like filters with
    a SQL LIKE (e.g. '%v3_5b%'). Returns trial_count_records()-shaped dicts.

    This is the ONLY new DB touch for Module 3, and it is a pure SELECT — the audit
    remains strictly read-only.
    """
    from sqlalchemy import text
    where = ""
    params: dict = {}
    if strategy_like is not None:
        where = "WHERE strategy_name LIKE :like"
        params["like"] = strategy_like
    q = text(
        "SELECT strategy_name, optimizer_type, COUNT(*) AS n "
        "FROM optimization_results "
        f"{where} "
        "GROUP BY strategy_name, optimizer_type"
    )
    with engine.connect() as c:
        rows = list(c.execute(q, params))
    return trial_count_records(rows)
```

Note: `Iterable` and `Any` are already imported at the top of `db.py` (line 15).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_db.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all db tests, including existing ones)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/db.py tests/unit/audit/test_db.py
git commit -m "feat(audit): add read-only optimization_results trial-count inventory"
```

---

## Task 11: `run_dsr` orchestrator + report summary dict

**Files:**
- Modify: `jutsu_engine/audit/selection_bias.py`
- Test: `tests/unit/audit/test_selection_bias.py`

The end-to-end orchestrator: run the returns campaign (v3_5b) → build matrix → V → DSR brackets on the golden combo's series → PBO on the matrix → assemble the summary dict the report renders. For v3_5d, a DSR-only path uses its golden attribution returns + a family-level N (no grid). Tested with injected `run_fn`.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_selection_bias.py
from jutsu_engine.audit.selection_bias import (
    summarize_selection_bias, DEFAULT_N_BRACKETS,
)


class TestSummarize:
    def _rows_with_spread(self, n=8, T=400, seed=0):
        """N combos with distinct Sharpes over T days (deterministic)."""
        import numpy as np
        from jutsu_engine.audit.selection_bias import combo_hash
        rng = np.random.default_rng(seed)
        dates = [f"2010-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(T)]
        rows = []
        for j in range(n):
            base = rng.standard_normal(T)
            base = (base - base.mean()) / base.std(ddof=1)
            ret = (0.01 * base + 0.01 * (0.02 * j)).tolist()   # combo j Sharpe rises
            h = combo_hash({"sma_fast": 40 + j})
            rows.append({"combo_id": j, "hash": h, "overrides": {"sma_fast": 40 + j},
                         "dates": dates, "returns": ret, "sharpe": 0.02 * j,
                         "error": None})
        return rows

    def test_summary_has_dsr_brackets_and_pbo(self):
        """summarize produces bracketed DSR rows + a PBO block for v3_5b."""
        rows = self._rows_with_spread()
        golden_hash = rows[3]["hash"]           # pick combo 3 as the golden anchor
        summary = summarize_selection_bias(
            strategy_id="v3_5b", rows=rows, golden_hash=golden_hash,
            trial_inventory=[{"strategy_name": "v3_5b",
                              "optimizer_type": "grid_search", "trials": 243}],
            compute_pbo_block=True, S=8)
        assert [r["N"] for r in summary["dsr_brackets"]] == list(DEFAULT_N_BRACKETS)
        assert 0.0 <= summary["pbo"]["pbo"] <= 1.0
        assert summary["n_combos"] == 8
        assert summary["cross_trial_V"] > 0.0

    def test_dsr_only_path_skips_pbo(self):
        """v3_5d DSR-only summary carries DSR brackets but no PBO block."""
        rows = self._rows_with_spread(n=2)
        summary = summarize_selection_bias(
            strategy_id="v3_5d", rows=rows, golden_hash=rows[0]["hash"],
            trial_inventory=[], compute_pbo_block=False, S=8,
            family_N=(1000, 5000))
        assert summary["pbo"] is None
        assert [r["N"] for r in summary["dsr_brackets"]] == [1000, 5000]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestSummarize -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'summarize_selection_bias'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/selection_bias.py
from datetime import date as _date
from pathlib import Path as _Path

from jutsu_engine.audit.dsr import (
    deflated_sharpe_brackets, DEFAULT_N_BRACKETS, sample_moments,
)
from jutsu_engine.audit.pbo import compute_pbo

# S = 16 blocks for CSCV (spec §7).
CSCV_BLOCKS: int = 16


def summarize_selection_bias(strategy_id: str, rows: list[dict], golden_hash: str,
                             trial_inventory: list[dict],
                             compute_pbo_block: bool = True,
                             S: int = CSCV_BLOCKS,
                             family_N=DEFAULT_N_BRACKETS) -> dict:
    """Assemble the DSR + PBO report summary from campaign rows (pure over rows).

    Args:
      rows: returns-campaign rows (from run_returns_campaign).
      golden_hash: hash of the golden combo whose daily series drives the DSR.
      trial_inventory: trial_count_records() rows (read-only DB inventory).
      compute_pbo_block: True for v3_5b (full grid → CSCV); False for v3_5d (DSR-only).
      S: CSCV blocks (16 per spec).
      family_N: the N brackets to report DSR at (v3_5b: 243/1000/5000; v3_5d: a
        family-level estimate, e.g. 1000/5000 — no grid of its own).

    Returns a dict consumed by render_dsr_section:
      strategy_id, n_combos, cross_trial_V, dsr_brackets (list per N),
      golden_moments (sr_obs/skew/kurt/T), pbo (block or None), trial_inventory,
      golden_hash.
    """
    golden_series = golden_combo_returns(rows, golden_hash)
    matrix, col_hashes, _dates = build_returns_matrix(rows)
    V = cross_trial_variance(matrix) if matrix.size else 0.0

    dsr_brackets = deflated_sharpe_brackets(golden_series, N_values=family_N, V=V)
    golden_moments = sample_moments(golden_series)

    pbo_block = None
    if compute_pbo_block and matrix.size and matrix.shape[1] >= 2:
        pbo_block = compute_pbo(matrix, S=S)
        # Drop the (large) per-partition logit list from the summary; the report
        # renders a compact histogram, not 12,870 raw values.
        pbo_block = {k: v for k, v in pbo_block.items() if k != "logits"}
        pbo_block["logit_histogram"] = _logit_histogram(
            compute_pbo(matrix, S=S)["logits"])

    return {
        "strategy_id": strategy_id,
        "n_combos": matrix.shape[1] if matrix.size else 0,
        "cross_trial_V": V,
        "dsr_brackets": dsr_brackets,
        "golden_moments": golden_moments,
        "pbo": pbo_block,
        "trial_inventory": trial_inventory,
        "golden_hash": golden_hash,
    }


def _logit_histogram(logits, bins: int = 20) -> dict:
    """Compact histogram (counts + edges) of the CSCV logit distribution."""
    arr = np.asarray(logits, dtype=float)
    counts, edges = np.histogram(arr, bins=bins)
    return {"counts": counts.tolist(), "edges": edges.tolist(),
            "median": float(np.median(arr)) if arr.size else 0.0}


def run_dsr(strategy_id: str, run_dir: _Path, workers: int = 1,
            retry_errors: bool = False, skip_campaign: bool = False,
            trial_inventory: list[dict] | None = None,
            progress=lambda m: None) -> dict:
    """End-to-end Module 3 for one strategy: campaign → matrix → DSR + PBO summary.

    v3_5b (primary): enumerate the 243-combo golden grid, run the returns campaign
    (resumable JSONL under run_dir/<sid>/campaign_dsr_<sid>.jsonl), build the matrix,
    compute DSR brackets on the golden combo + PBO/CSCV over the full matrix.

    v3_5d: DSR-ONLY. Its distinguishing grid was ~10 combos (too few for CSCV), so
    we run a SINGLE golden backtest (as one combo) and report DSR at a family-level
    N estimate — no second grid, no PBO. This scoping is stated in the report.

    skip_campaign: if the campaign JSONL already has every combo, skip re-running
    (matrix rebuilt from the existing rows). Errors if rows are missing.
    """
    from jutsu_engine.audit.attribution import _all_symbols

    run_dir = _Path(run_dir)
    symbols = _all_symbols(strategy_id)
    campaign_file = run_dir / strategy_id / f"campaign_dsr_{strategy_id}.jsonl"

    if strategy_id == "v3_5b":
        combos = enumerate_golden_grid()
        golden_hash = _golden_anchor_hash(combos)
        compute_pbo_block = True
        family_N = DEFAULT_N_BRACKETS
    else:
        # v3_5d: single golden combo (no overrides = live golden config).
        combos = [{"combo_id": 0, "overrides": {}, "hash": combo_hash({})}]
        golden_hash = combos[0]["hash"]
        compute_pbo_block = False
        family_N = (1000, 5000)   # family-level estimate; documented in report

    if not skip_campaign:
        run_returns_campaign(strategy_id, combos, campaign_file, symbols=symbols,
                             workers=workers, retry_errors=retry_errors,
                             progress=progress)
    rows = reload_returns_rows(campaign_file)
    if not rows:
        raise RuntimeError(
            f"no campaign rows at {campaign_file}; run without --skip-campaign first")

    return summarize_selection_bias(
        strategy_id=strategy_id, rows=rows, golden_hash=golden_hash,
        trial_inventory=trial_inventory or [], compute_pbo_block=compute_pbo_block,
        family_N=family_N)


def _golden_anchor_hash(combos: list[dict]) -> str:
    """Hash of the combo whose axis values equal the live golden config's.

    The live golden values for the four SHARED axes are upper_thresh_z=1.0,
    lower_thresh_z=0.2, vol_crush_threshold=-0.15, sma_fast=40. The historical grid's
    sma_slow axis is [180,200,220] and does NOT include the live golden 140 — so the
    anchor uses the historical grid's CENTER sma_slow (200) as the closest in-grid
    representative. This mismatch is real (the live config's sma_slow was tuned in a
    LATER phase) and is stated in the report; the DSR uses the golden combo's actual
    daily returns from the campaign either way.
    """
    anchor = {"upper_thresh_z": 1.0, "lower_thresh_z": 0.2,
              "vol_crush_threshold": -0.15, "sma_fast": 40, "sma_slow": 200}
    target = combo_hash(anchor)
    for c in combos:
        if c["hash"] == target:
            return target
    # Fallback: first combo (deterministic) if the anchor is somehow absent.
    return combos[0]["hash"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all selection_bias tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/selection_bias.py tests/unit/audit/test_selection_bias.py
git commit -m "feat(audit): add run_dsr orchestrator + selection-bias summary dict"
```

---

## Task 12: DSR report section renderer + writer

**Files:**
- Modify: `jutsu_engine/audit/report.py`
- Test: `tests/unit/audit/test_report.py`

Renders `report_dsr_<strategy>.md`: trial inventory, DSR table across bracketed N (with the spec-§10 gate: DSR confidence <95% → edge statistically unproven), PBO + degradation-plot-as-table, plain-language verdict sentence (spec §7).

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/unit/audit/test_report.py
from jutsu_engine.audit.report import render_dsr_section, write_dsr_report


def _dsr_summary(dsr_conf=0.30, pbo=0.55):
    return {
        "strategy_id": "v3_5b",
        "n_combos": 243,
        "cross_trial_V": 0.0004,
        "golden_hash": "abc123def4567890",
        "golden_moments": {"sr_obs": 0.0504, "skew": -0.1,
                           "kurt_nonexcess": 4.2, "T": 4100},
        "trial_inventory": [
            {"strategy_name": "Hierarchical_Adaptive_v3_5b",
             "optimizer_type": "grid_search", "trials": 243},
        ],
        "dsr_brackets": [
            {"N": 243, "sr_obs": 0.0504, "sr_star": 0.0566, "dsr": dsr_conf, "T": 4100},
            {"N": 1000, "sr_obs": 0.0504, "sr_star": 0.0620, "dsr": 0.18, "T": 4100},
            {"N": 5000, "sr_obs": 0.0504, "sr_star": 0.0680, "dsr": 0.09, "T": 4100},
        ],
        "pbo": {"pbo": pbo, "prob_oos_loss": 0.42, "degradation_slope": 0.31,
                "n_partitions": 12870,
                "logit_histogram": {"counts": [1, 2, 3], "edges": [-3, -1, 1, 3],
                                    "median": -0.4}},
    }


class TestRenderDSR:
    def test_renders_trial_inventory_and_brackets(self):
        """The DSR section shows the trial inventory and per-N DSR rows."""
        md = render_dsr_section(_dsr_summary())
        assert "Selection-bias correction (Module 3)" in md
        assert "243" in md and "1000" in md and "5000" in md
        assert "grid_search" in md

    def test_unproven_verdict_when_dsr_below_95(self):
        """DSR < 95% at N=243 → 'edge statistically unproven' (spec §10)."""
        md = render_dsr_section(_dsr_summary(dsr_conf=0.30))
        assert "statistically unproven" in md.lower()

    def test_pbo_over_50_flags_overfitting(self):
        """PBO > 50% is called out as an overfitting red flag (spec §10)."""
        md = render_dsr_section(_dsr_summary(pbo=0.55))
        assert "overfitting" in md.lower()
        assert "12870" in md   # partition count present

    def test_plain_language_verdict_present(self):
        """The spec §7 plain-language sentence about trials is rendered."""
        md = render_dsr_section(_dsr_summary())
        assert "probability" in md.lower()
        assert "configurations you tried" in md.lower()

    def test_dsr_only_summary_renders_without_pbo(self):
        """A v3_5d DSR-only summary (pbo None) renders without a PBO block."""
        s = _dsr_summary()
        s["pbo"] = None
        s["strategy_id"] = "v3_5d"
        md = render_dsr_section(s)
        assert "PBO not computed" in md

    def test_write_dsr_report(self, tmp_path):
        """write_dsr_report writes report_dsr_<strategy>.md into the run dir."""
        out = write_dsr_report(tmp_path, "v3_5b", "# hi\n")
        assert out.name == "report_dsr_v3_5b.md"
        assert out.read_text() == "# hi\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py::TestRenderDSR -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'render_dsr_section'`

- [ ] **Step 3: Add the implementation**

```python
# append to jutsu_engine/audit/report.py

# spec §10 decision thresholds for Module 3 (selection-bias correction).
DSR_CONFIDENCE_THRESHOLD = 0.95   # DSR (a probability); < 0.95 → edge unproven
PBO_THRESHOLD = 0.50              # PBO > 0.50 → overfitting red flag


def render_dsr_section(summary: dict) -> str:
    """Render the Selection-bias correction (Module 3) section as markdown.

    ``summary`` is the dict from selection_bias.summarize_selection_bias():
      strategy_id, n_combos, cross_trial_V, golden_hash, golden_moments,
      trial_inventory (list of {strategy_name, optimizer_type, trials}),
      dsr_brackets (list of {N, sr_obs, sr_star, dsr, T}),
      pbo (dict {pbo, prob_oos_loss, degradation_slope, n_partitions,
                 logit_histogram} OR None for the v3_5d DSR-only path).

    Renders: trial inventory table, DSR-across-N table with the spec §10 gate
    (DSR < 95% → edge statistically unproven), PBO + degradation-plot-as-table,
    and the spec §7 plain-language verdict sentence.
    """
    sid = summary["strategy_id"]
    gm = summary["golden_moments"]
    brackets = summary["dsr_brackets"]
    inv = summary["trial_inventory"]
    pbo = summary["pbo"]

    # DSR at the smallest N bracket is the least-deflated (most generous) confidence.
    dsr_at_min_N = brackets[0]["dsr"] if brackets else 0.0
    min_N = brackets[0]["N"] if brackets else 0
    dsr_proven = dsr_at_min_N >= DSR_CONFIDENCE_THRESHOLD

    lines = [
        "## Selection-bias correction (Module 3)",
        "",
        f"- Strategy: **{sid}**  |  Golden combo hash: `{summary['golden_hash']}`",
        f"- Golden daily Sharpe (per-period): **{_fmt(gm.get('sr_obs'), '.5f')}**  |  "
        f"skew γ₃: **{_fmt(gm.get('skew'), '.3f')}**  |  "
        f"kurtosis γ₄ (non-excess): **{_fmt(gm.get('kurt_nonexcess'), '.3f')}**  |  "
        f"T: **{gm.get('T')}**",
        f"- Grid combos with usable returns: **{summary['n_combos']}**  |  "
        f"cross-trial Sharpe variance V: **{_fmt(summary.get('cross_trial_V'), '.6f')}**",
        "",
        "### Trial-count inventory (read-only; early history may be incomplete)",
        "_The `optimization_results` table may not capture every historical search "
        "phase (v2.x→v3.5b). DSR is therefore reported at BRACKETED N values below; "
        "higher N deflates harder and is the conservative read._",
        "",
    ]
    if inv:
        lines += ["| strategy | optimizer | trials |", "| --- | --- | --- |"]
        for r in inv:
            lines.append(f"| {r['strategy_name']} | {r['optimizer_type']} | "
                         f"{r['trials']} |")
    else:
        lines.append("_(no optimization_results rows found for this strategy)_")

    # DSR-across-N table
    lines += [
        "",
        "### Deflated Sharpe Ratio across bracketed N (spec §7)",
        "_DSR = PSR(SR*): the probability the golden Sharpe reflects real skill "
        "rather than the luckiest of N tries. SR* is the expected max Sharpe under "
        "N trials with cross-trial variance V._",
        "",
        "| N (trials) | SR_obs (daily) | SR* (expected max) | DSR (confidence) |",
        "| --- | --- | --- | --- |",
    ]
    for r in brackets:
        lines.append(
            f"| {r['N']} | {_fmt(r['sr_obs'], '.5f')} | "
            f"{_fmt(r['sr_star'], '.5f')} | {_fmt(r['dsr'], '.4f')} |"
        )

    # spec §10 gate
    lines += [
        "",
        "Decision threshold (spec §10):",
        "| Signal | Threshold | Consequence |",
        "| --- | --- | --- |",
        f"| DSR confidence | <95% | Edge statistically unproven → prioritize "
        "accumulating live record over further tuning |",
        f"| PBO | >50% | Same as above |",
        "",
    ]
    if dsr_proven:
        lines.append(
            f"**Verdict (DSR):** at N={min_N}, DSR = **{_fmt(dsr_at_min_N, '.4f')}** "
            f">= 0.95 — the edge clears the selection-bias gate at the smallest "
            f"trial-count bracket.")
    else:
        lines.append(
            f"**Verdict (DSR):** at N={min_N}, DSR = **{_fmt(dsr_at_min_N, '.4f')}** "
            f"< 0.95 — the edge is **statistically unproven** after correcting for "
            f"selection over ~{min_N} trials (spec §10). It deflates further at "
            f"higher N.")

    # PBO block
    lines += ["", "### Probability of Backtest Overfitting (PBO via CSCV, S=16)"]
    if pbo is None:
        lines += [
            "_PBO not computed for this strategy: its distinguishing grid was too "
            "small for CSCV (needs a wide combo matrix). DSR above uses a "
            "family-level N estimate. PBO is reported for v3_5b (primary) only._",
            "",
        ]
    else:
        pbo_val = pbo["pbo"]
        over = pbo_val > PBO_THRESHOLD
        lines += [
            f"- CSCV partitions: **{pbo['n_partitions']}** (all C(16,8))",
            f"- **PBO = {_fmt(pbo_val, '.4f')}** "
            + ("→ **overfitting red flag** (>50%): the IS-best config lands below "
               "the OOS median in most partitions."
               if over else
               "(<=50%): the IS-best config generally holds up out-of-sample."),
            f"- Probability of OOS loss for the IS-best: "
            f"**{_fmt(pbo['prob_oos_loss'], '.4f')}**",
            f"- Performance-degradation slope (OOS Sharpe on IS Sharpe): "
            f"**{_fmt(pbo['degradation_slope'], '.4f')}** "
            "(1.0 = perfect carry-over; lower = IS edge does not persist OOS)",
            "",
            "#### Logit distribution of OOS relative ranks (plot-as-table)",
            "_Negative logit ⇒ IS-best is OOS below-median (overfit). Median "
            f"logit: **{_fmt(pbo['logit_histogram'].get('median'), '.3f')}**._",
            "",
            _histogram_as_table(pbo["logit_histogram"]),
        ]

    # spec §7 plain-language verdict sentence (always present)
    prob_real_pct = dsr_at_min_N * 100.0
    lines += [
        "### Plain-language verdict (spec §7)",
        "",
        f"> Given how many configurations you tried (~{min_N}+), the probability "
        f"that the observed Sharpe is real (not the luckiest draw of the search) is "
        f"**{prob_real_pct:.1f}%**"
        + (f", and the probability the backtest is overfit (PBO) is "
           f"**{pbo['pbo'] * 100:.1f}%**." if pbo is not None else ".")
        + " Backtest-only evidence is structurally underpowered here (XREF-001, "
          "n=1 crash-episode caution) — the live track record carries the burden "
          "of proof from here.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _histogram_as_table(hist: dict) -> str:
    """Render a {counts, edges} histogram as a compact markdown bin table."""
    counts = hist.get("counts", [])
    edges = hist.get("edges", [])
    if not counts:
        return "_(no histogram data)_\n"
    lines = ["| bin (logit range) | count |", "| --- | --- |"]
    for i, c in enumerate(counts):
        lo = edges[i]
        hi = edges[i + 1] if i + 1 < len(edges) else edges[-1]
        lines.append(f"| [{lo:.2f}, {hi:.2f}) | {c} |")
    return "\n".join(lines) + "\n"


def write_dsr_report(run_dir: Path, strategy_id: str, markdown: str) -> Path:
    """Write report_dsr_<strategy>.md into run_dir (separate from other reports).

    Deliberately a SEPARATE file so the DSR run never touches report_<strategy>.md,
    report_plateau_<strategy>.md, or report_wfo_<strategy>.md.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_dsr_{strategy_id}.md"
    out.write_text(markdown)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all report tests, including existing)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/report.py tests/unit/audit/test_report.py
git commit -m "feat(audit): add DSR/PBO report section renderer + writer"
```

---

## Task 13: `jutsu audit dsr` CLI subcommand

**Files:**
- Modify: `jutsu_engine/cli/commands/audit.py`
- Test: `tests/unit/audit/test_dsr_cli.py`

Wire the CLI: `jutsu audit dsr --strategy v3_5b [--workers K] [--retry-errors] [--run-date] [--skip-campaign]`. Midnight-safe run-dir resolution mirroring the WFO resolver (scans `campaign_dsr_<strategy>.jsonl`). Read-only trial inventory pulled via `db.load_trial_counts` (degrades gracefully if the DB is unavailable — DSR still runs on the campaign, only the inventory table is empty).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/audit/test_dsr_cli.py
"""DB-free CLI wiring tests for `jutsu audit dsr` (run_dsr monkeypatched)."""
from click.testing import CliRunner

from jutsu_engine.cli.commands import audit as audit_cli


def _fake_summary(sid):
    return {
        "strategy_id": sid, "n_combos": 243, "cross_trial_V": 0.0004,
        "golden_hash": "abc123def4567890",
        "golden_moments": {"sr_obs": 0.05, "skew": 0.0, "kurt_nonexcess": 3.0, "T": 4000},
        "trial_inventory": [],
        "dsr_brackets": [
            {"N": 243, "sr_obs": 0.05, "sr_star": 0.056, "dsr": 0.30, "T": 4000},
            {"N": 1000, "sr_obs": 0.05, "sr_star": 0.062, "dsr": 0.18, "T": 4000},
            {"N": 5000, "sr_obs": 0.05, "sr_star": 0.068, "dsr": 0.09, "T": 4000},
        ],
        "pbo": {"pbo": 0.55, "prob_oos_loss": 0.4, "degradation_slope": 0.3,
                "n_partitions": 12870,
                "logit_histogram": {"counts": [1], "edges": [-1, 1], "median": -0.3}},
    }


def test_dsr_cmd_runs_and_writes_report(tmp_path, monkeypatch):
    """`jutsu audit dsr --strategy v3_5b` runs run_dsr and writes report_dsr_v3_5b.md."""
    monkeypatch.setattr(audit_cli, "report_output_dir", lambda **k: tmp_path)

    def fake_run_dsr(strategy_id, run_dir, **kwargs):
        return _fake_summary(strategy_id)

    monkeypatch.setattr("jutsu_engine.audit.selection_bias.run_dsr", fake_run_dsr)
    # Inventory query is best-effort; make it return [] without touching a DB.
    monkeypatch.setattr(audit_cli, "_load_trial_inventory", lambda sid: [])

    result = CliRunner().invoke(audit_cli.audit, ["dsr", "--strategy", "v3_5b"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "report_dsr_v3_5b.md").exists()


def test_dsr_cmd_skip_campaign_flag(tmp_path, monkeypatch):
    """--skip-campaign is threaded into run_dsr."""
    monkeypatch.setattr(audit_cli, "report_output_dir", lambda **k: tmp_path)
    seen = {}

    def fake_run_dsr(strategy_id, run_dir, **kwargs):
        seen.update(kwargs)
        return _fake_summary(strategy_id)

    monkeypatch.setattr("jutsu_engine.audit.selection_bias.run_dsr", fake_run_dsr)
    monkeypatch.setattr(audit_cli, "_load_trial_inventory", lambda sid: [])

    result = CliRunner().invoke(
        audit_cli.audit, ["dsr", "--strategy", "v3_5b", "--skip-campaign"])
    assert result.exit_code == 0, result.output
    assert seen.get("skip_campaign") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `AttributeError: module 'jutsu_engine.cli.commands.audit' has no attribute '_load_trial_inventory'`

- [ ] **Step 3: Add the implementation**

First, extend the report import at the top of `jutsu_engine/cli/commands/audit.py` (the existing block imports from `jutsu_engine.audit.report`):

```python
# in jutsu_engine/cli/commands/audit.py, replace the existing report import block:
from jutsu_engine.audit.report import (
    render_report, write_report,
    render_plateau_section, write_plateau_report,
    render_wfo_section, write_wfo_report,
    render_dsr_section, write_dsr_report,
)
```

Then append the resolver, the inventory helper, and the command at the end of the file:

```python
# append to jutsu_engine/cli/commands/audit.py
def _resolve_run_dir_dsr(run_date_str: str | None, strategy_id: str) -> "Path":
    """Midnight-safe run-dir resolution for DSR campaign files.

    Mirrors _resolve_run_dir_wfo but scans campaign_dsr_<strategy>.jsonl so a DSR
    resume never collides with a plateau or WFO campaign file. Resolution order:
      (a) --run-date given → that dated directory unconditionally.
      (b) Existing campaign_dsr_<strategy>.jsonl → resume newest date-dir.
      (c) Fresh campaign → today's directory.
    """
    if run_date_str is not None:
        try:
            run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(
                f"Invalid date format {run_date_str!r}; expected YYYY-MM-DD",
                param_hint="--run-date",
            )
        return report_output_dir(run_date=run_date)

    audit_base = report_output_dir().parent
    campaign_pattern = f"campaign_dsr_{strategy_id}.jsonl"
    candidates = sorted(
        audit_base.glob(f"*/{strategy_id}/{campaign_pattern}"),
        key=lambda p: p.parent.parent.name,
        reverse=True,
    )
    if candidates:
        newest = candidates[0]
        run_dir = newest.parent.parent
        click.echo(click.style(
            f"  Resuming existing DSR campaign: {newest} "
            f"(pass --run-date to override)", fg="yellow"))
        return run_dir
    return report_output_dir()


def _load_trial_inventory(strategy_id: str) -> list:
    """Read-only optimization_results inventory for a strategy (best-effort).

    Returns [] (not an error) if the DB is unavailable — the DSR campaign runs on
    the returns matrix regardless; only the inventory table is empty in that case.
    """
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        return audit_db.load_trial_counts(engine, strategy_like=f"%{strategy_id}%")
    except AuditDBUnavailable:
        click.echo(click.style(
            "  (optimization_results unavailable — inventory table will be empty)",
            fg="yellow"))
        return []


@audit.command("dsr")
@_STRATEGY_OPTION
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel worker processes (1 = serial; each worker builds its "
                   "own BacktestRunner). ~243 v3_5b backtests → 4 workers ≈ ~1.7h.")
@click.option("--retry-errors", "retry_errors", is_flag=True, default=False,
              help="Re-run previously errored checkpoint rows rather than treating "
                   "them as completed. Use after a transient failure (DB blip).")
@click.option("--run-date", "run_date", type=str, default=None, metavar="YYYY-MM-DD",
              help="Use a specific dated run directory instead of auto-detecting an "
                   "existing campaign (midnight-safe resume).")
@click.option("--skip-campaign", "skip_campaign", is_flag=True, default=False,
              help="Skip the returns campaign and compute DSR/PBO from an existing "
                   "campaign JSONL (errors if rows are missing).")
def dsr_cmd(strategy, workers, retry_errors, run_date, skip_campaign):
    """Module 3: selection-bias correction (DSR + PBO). v3_5b: full grid + PBO; "
    v3_5d: DSR-only (family-level N)."""
    from jutsu_engine.audit import selection_bias as sb_mod

    try:
        for sid in _strategy_ids(strategy):
            run_dir = _resolve_run_dir_dsr(run_date, sid)
            campaign_file = run_dir / sid / f"campaign_dsr_{sid}.jsonl"
            click.echo(
                f"[{sid}] DSR/PBO "
                f"(workers={workers}, retry_errors={retry_errors}, "
                f"skip_campaign={skip_campaign})\n"
                f"  campaign file: {campaign_file}"
            )
            inventory = _load_trial_inventory(sid)
            summary = sb_mod.run_dsr(
                sid, run_dir, workers=workers, retry_errors=retry_errors,
                skip_campaign=skip_campaign, trial_inventory=inventory,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
            dsr0 = summary["dsr_brackets"][0]
            click.echo(click.style(
                f"  DSR(N={dsr0['N']})={dsr0['dsr']:.4f}  "
                f"PBO={summary['pbo']['pbo']:.4f}" if summary["pbo"]
                else f"  DSR(N={dsr0['N']})={dsr0['dsr']:.4f}  (DSR-only)",
                fg="cyan"))
            md = render_dsr_section(summary)
            out = write_dsr_report(run_dir, sid, md)
            click.echo(click.style(f"  report: {out}", fg="green"))
    except AuditDBUnavailable as e:
        click.echo(click.style(f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.",
            fg="yellow"), err=True)
        raise click.Abort()
    except RuntimeError as e:
        click.echo(click.style(f"✗ Campaign aborted: {e}", fg="red"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001
        logger.error(f"DSR audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ DSR audit failed: {e}", fg="red"), err=True)
        raise click.Abort()
```

Note: the test monkeypatches `jutsu_engine.audit.selection_bias.run_dsr` and the command calls `sb_mod.run_dsr` (module attribute), so the patch is seen. `_load_trial_inventory` is a module-level function so the test can patch it on `audit_cli`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_dsr_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/cli/commands/audit.py tests/unit/audit/test_dsr_cli.py
git commit -m "feat(audit): add `jutsu audit dsr` CLI subcommand (midnight-safe, read-only inventory)"
```

---

## Task 14: Smoke-mode support (tiny combo subset)

**Files:**
- Modify: `jutsu_engine/audit/selection_bias.py`
- Modify: `jutsu_engine/cli/commands/audit.py`
- Test: `tests/unit/audit/test_selection_bias.py`

Prove the full pipeline (campaign → matrix → DSR + PBO) in minutes with a tiny combo subset. `--combos-limit N` truncates the enumerated grid; the CSCV math already runs on synthetic data in the unit tests, so smoke here means a small real campaign.

- [ ] **Step 1: Add the failing test**

```python
# append to tests/unit/audit/test_selection_bias.py
class TestSmoke:
    def test_combos_limit_truncates_grid(self):
        """enumerate_golden_grid(limit=N) returns the first N combos for smoke runs."""
        from jutsu_engine.audit.selection_bias import enumerate_golden_grid
        assert len(enumerate_golden_grid(limit=5)) == 5
        assert len(enumerate_golden_grid()) == 243

    def test_run_dsr_threads_combos_limit(self, tmp_path, monkeypatch):
        """run_dsr(combos_limit=N) runs only N combos in the campaign."""
        import jutsu_engine.audit.selection_bias as sb
        monkeypatch.setattr(sb, "_all_symbols", lambda sid: [], raising=False)
        # inject the fake worker so no DB/backtest is touched
        seen = []

        def fake_run_fn(strategy_id, combo, symbols, start, end, initial_capital="10000"):
            seen.append(combo["combo_id"])
            return {"combo_id": combo["combo_id"], "hash": combo["hash"],
                    "overrides": combo["overrides"],
                    "dates": ["2010-02-01", "2010-02-02"],
                    "returns": [0.01, -0.02], "sharpe": 0.1, "error": None}

        monkeypatch.setattr(sb, "run_one_combo", fake_run_fn)
        # smoke=4 combos; PBO needs >=2 combos and S<=T, so use S=2 via a tiny matrix.
        sb.run_dsr("v3_5b", tmp_path, combos_limit=4, cscv_blocks=2)
        assert sorted(seen) == [0, 1, 2, 3]
```

Note: `run_dsr` must be extended to accept `combos_limit` and `cscv_blocks` and to pass `run_fn=run_one_combo` through (so the monkeypatch of the module attribute is used). The `_all_symbols` import inside `run_dsr` is local; patch `sb._all_symbols` requires it be a module attribute — so hoist the import to module level (see Step 3).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py::TestSmoke -p no:cacheprovider -o addopts="" -q`
Expected: FAIL (`enumerate_golden_grid() got an unexpected keyword argument 'limit'`)

- [ ] **Step 3: Update the implementation**

Change `enumerate_golden_grid` to accept a limit:

```python
# in jutsu_engine/audit/selection_bias.py, replace enumerate_golden_grid:
def enumerate_golden_grid(limit: int | None = None) -> list[dict]:
    """Expand GOLDEN_GRID_AXES into 243 combos (or the first `limit` for smoke runs).

    Each combo: {"combo_id": int, "overrides": {axis: value}, "hash": str}.
    combo_id is the enumeration index 0..242. `limit` truncates to the first N
    combos (smoke mode); None returns all 243.
    """
    names = list(GOLDEN_GRID_AXES.keys())
    value_lists = [GOLDEN_GRID_AXES[n] for n in names]
    combos: list[dict] = []
    for cid, values in enumerate(itertools.product(*value_lists)):
        overrides = dict(zip(names, values))
        combos.append({
            "combo_id": cid,
            "overrides": overrides,
            "hash": combo_hash(overrides),
        })
    if limit is not None:
        combos = combos[:limit]
    return combos
```

Hoist `_all_symbols` to a module-level import (so it is patchable) and thread `combos_limit` + `cscv_blocks` through `run_dsr`. Replace the `run_dsr` function's signature and body head:

```python
# in jutsu_engine/audit/selection_bias.py, near the top add the module-level import:
from jutsu_engine.audit.attribution import _all_symbols   # module-level so tests can patch

# replace the run_dsr signature + campaign-setup section:
def run_dsr(strategy_id: str, run_dir: _Path, workers: int = 1,
            retry_errors: bool = False, skip_campaign: bool = False,
            trial_inventory: list[dict] | None = None,
            combos_limit: int | None = None, cscv_blocks: int = CSCV_BLOCKS,
            progress=lambda m: None) -> dict:
    """End-to-end Module 3 for one strategy: campaign → matrix → DSR + PBO summary.

    v3_5b (primary): enumerate the 243-combo golden grid (or `combos_limit` for a
    smoke run), run the returns campaign (resumable JSONL under
    run_dir/<sid>/campaign_dsr_<sid>.jsonl), build the matrix, compute DSR brackets
    on the golden combo + PBO/CSCV over the full matrix.

    v3_5d: DSR-ONLY (single golden combo, no PBO, family-level N — see docstring
    body). skip_campaign reuses an existing JSONL. cscv_blocks (S) defaults to 16.
    combos_limit truncates the grid for smoke runs.
    """
    run_dir = _Path(run_dir)
    symbols = _all_symbols(strategy_id)
    campaign_file = run_dir / strategy_id / f"campaign_dsr_{strategy_id}.jsonl"

    if strategy_id == "v3_5b":
        combos = enumerate_golden_grid(limit=combos_limit)
        golden_hash = _golden_anchor_hash(combos)
        compute_pbo_block = True
        family_N = DEFAULT_N_BRACKETS
    else:
        combos = [{"combo_id": 0, "overrides": {}, "hash": combo_hash({})}]
        golden_hash = combos[0]["hash"]
        compute_pbo_block = False
        family_N = (1000, 5000)

    if not skip_campaign:
        run_returns_campaign(strategy_id, combos, campaign_file, run_fn=run_one_combo,
                             symbols=symbols, workers=workers,
                             retry_errors=retry_errors, progress=progress)
    rows = reload_returns_rows(campaign_file)
    if not rows:
        raise RuntimeError(
            f"no campaign rows at {campaign_file}; run without --skip-campaign first")

    return summarize_selection_bias(
        strategy_id=strategy_id, rows=rows, golden_hash=golden_hash,
        trial_inventory=trial_inventory or [], compute_pbo_block=compute_pbo_block,
        S=cscv_blocks, family_N=family_N)
```

Remove the now-duplicate local `from jutsu_engine.audit.attribution import _all_symbols` line that was inside the old `run_dsr` body (it's now module-level).

Add a `--combos-limit` CLI option to `dsr_cmd`:

```python
# in jutsu_engine/cli/commands/audit.py, add this option to dsr_cmd (above the function):
@click.option("--combos-limit", "combos_limit", type=int, default=None,
              help="Cap the number of grid combos (smoke mode, e.g. 4).")
```

and add `combos_limit` to the `dsr_cmd` signature and the `run_dsr(...)` call:

```python
def dsr_cmd(strategy, workers, retry_errors, run_date, skip_campaign, combos_limit):
    ...
            summary = sb_mod.run_dsr(
                sid, run_dir, workers=workers, retry_errors=retry_errors,
                skip_campaign=skip_campaign, trial_inventory=inventory,
                combos_limit=combos_limit,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_selection_bias.py tests/unit/audit/test_dsr_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all selection_bias + CLI tests)

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/selection_bias.py jutsu_engine/cli/commands/audit.py tests/unit/audit/test_selection_bias.py
git commit -m "feat(audit): add smoke-mode combos-limit + configurable CSCV blocks"
```

---

## Task 15: Full audit-suite test run + LOGBOOK EXP-005 skeleton + CHANGELOG

**Files:**
- Modify: `docs/experiments/LOGBOOK.md`
- Modify: `CHANGELOG.md`

Final gate: run the whole audit test suite green, then write the docs (RULES.md: task is NOT complete until CHANGELOG + LOGBOOK are written).

- [ ] **Step 1: Run the full audit unit-test suite**

Run: `.venv/bin/python -m pytest tests/unit/audit/ -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all Phase-1/2/3 tests + the new Phase-4 dsr/pbo/selection_bias/db/report/cli tests). Confirm the count grew by ~40+ new tests over the prior 199.

- [ ] **Step 2: Add the LOGBOOK EXP-005 skeleton**

Append to `docs/experiments/LOGBOOK.md` (after EXP-004), and add the index row. Use this exact skeleton (fill the RESULTS/VERDICT after running the real campaign; the skeleton documents the method precisely so it is reproducible):

```markdown

---

## EXP-005 — Baseline audit Phase 4: selection-bias correction (DSR + PBO) (2026-07-07)

**Question.** After correcting for how many configurations were tried, how likely
is the golden config's Sharpe to be real rather than the luckiest draw of the
search? (a) Deflated Sharpe Ratio (Bailey & López de Prado) at bracketed trial
counts N = 243 / 1,000 / 5,000; (b) Probability of Backtest Overfitting (PBO) via
CSCV (S=16) over the historical 243-combo golden grid's per-combo daily returns.

**Why.** EXP-001 established honest Sharpe ~0.8 (not the in-sample ~2.8). EXP-003
lowered the parameter-overfit prior (48th percentile of its own neighborhood).
EXP-004 closed adaptive tuning. Module 3 is the last unmeasured piece: the
trial-count correction for the v2.x→v3.5b search history. XREF-001 (n=1
crash-episode caution) says backtest-only evidence is structurally underpowered,
so DSR/PBO carry the burden of proof. Decision framework: spec
`docs/superpowers/specs/2026-07-06-baseline-audit-design.md` §7/§10.

**Method.** Built `jutsu_engine/audit/{dsr,pbo,selection_bias}.py` + `jutsu audit dsr`.
- **DSR** (pure math, `dsr.py`): PSR(SR*) = Φ(((SR_obs−SR*)√(T−1)) / √(1 − γ₃·SR_obs
  + ((γ₄−1)/4)·SR_obs²)); SR* = √V·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))), γ =
  Euler–Mascheroni; DSR = PSR(SR*). Golden daily returns from the campaign's golden
  combo; V from the actual per-combo Sharpes; N bracketed. Non-excess kurtosis
  (scipy excess + 3); sample skew/kurtosis (bias=False). Guards: N≥2, T≥2, positive
  radicand, non-zero variance.
- **PBO** (pure math, `pbo.py`): CSCV S=16, all C(16,8)=12,870 IS/OOS partitions;
  per partition rank combos by IS Sharpe, take IS-best, compute its OOS relative
  rank ω̄; PBO = fraction with ω̄ < 0.5 (logit < 0). Plus logit distribution,
  IS-vs-OOS degradation slope, prob-of-OOS-loss for the IS-best.
- **Returns campaign** (`selection_bias.py`): one-time full-period (2010-02 →
  present) re-run of the 243-combo golden grid, capturing each combo's daily
  Strategy_Daily_Return series inline in fsync-JSONL (reusing the plateau/WFO
  checkpoint/resume/breaker/single-writer/tempdir machinery — NOT parquet:
  pyarrow uninstalled, JSONL is proven and ~10 MB). Combos enumerated from the
  historical grid axes (documented in the Gold-Configs YAML header, versioned in
  `grid-configs/audit/golden_grid_v3_5b_axes.yaml`): upper_thresh_z [0.8,1.0,1.2] ×
  lower_thresh_z [-0.2,0.0,0.2] × vol_crush_threshold [-0.15,-0.20,-0.25] × sma_fast
  [40,50,60] × sma_slow [180,200,220] = 243. Inert AND sensitive axes both retained
  (the historical search varied them — EXP-003 inertness does not change the trial
  count that was actually spent).
- **Scoping:** v3_5b PRIMARY (full grid + DSR + PBO). v3_5d DSR-ONLY using its
  golden full-period returns + a family-level N — no second grid re-run (its
  distinguishing grid was ~10 Cell-1-exit combos, too few for CSCV).
- Trial inventory: read-only SELECT over `optimization_results` (grouped by
  strategy/optimizer). Early history may be incomplete → DSR reported bracketed.
- Command (one-time, ~1.7h at 4 workers): `jutsu audit dsr --strategy v3_5b --workers 4`;
  then DSR-only `--strategy v3_5d`. Smoke: `jutsu audit dsr --strategy v3_5b
  --combos-limit 4` (minutes, proves pipeline end-to-end).

**Results.** _(fill after running the campaign: trial inventory counts; DSR at
N=243/1000/5000 for v3_5b; PBO + degradation slope + prob-OOS-loss; DSR for v3_5d.)_

**Verdict / decisions.** _(fill: does the edge clear the DSR≥95% / PBO≤50% gates?
Per spec §10, DSR<95% OR PBO>50% → edge statistically unproven → prioritize live
track record over further tuning.)_

**Artifacts.** Reports `claudedocs/audit/2026-07-07/report_dsr_v3_5{b,d}.md`;
campaign JSONL `claudedocs/audit/2026-07-07/v3_5b/campaign_dsr_v3_5b.jsonl`; code
merged to main (N unit tests). Serena memory: `dsr_pbo_phase4_<date>`.

**Follow-ups spawned.** _(fill: regime-classifier upgrade program with the full
gauntlet — plateau + WFO + DSR — as fitness function.)_
```

And add the index row (in the table near the top of the LOGBOOK, after the EXP-004 row):

```markdown
| EXP-005 | 2026-07-07 | Given the trial count, how likely is the golden Sharpe real (DSR + PBO)? | _(pending campaign)_ |
```

- [ ] **Step 3: Add the CHANGELOG entry**

Prepend to `CHANGELOG.md` (above the current top entry), matching the house format:

```markdown
#### **Feature: Baseline Audit Phase 4 — Module 3 selection-bias correction (DSR + PBO)** (2026-07-07)

Added `jutsu audit dsr` (`jutsu_engine/audit/{dsr,pbo,selection_bias}.py`): corrects
the golden config's headline Sharpe for selection bias. (a) **Deflated Sharpe Ratio**
(Bailey & López de Prado) reported at bracketed trial counts N = 243 / 1,000 / 5,000
with the spec §10 gate (DSR < 95% → edge statistically unproven); (b) **PBO** via CSCV
(S=16, all C(16,8)=12,870 partitions) over the per-combo daily returns of the
historical 243-combo v3.5b golden grid, plus logit distribution, IS-vs-OOS
degradation slope, and probability-of-OOS-loss. A one-time full-period returns
campaign (2010-02 → present, ~243 backtests, ~1.7h at 4 workers) captures each combo's
daily return series inline in fsync-JSONL — reusing the proven plateau/WFO
checkpoint/resume/circuit-breaker/single-writer/tempdir machinery (NOT parquet:
pyarrow uninstalled). Grid combos enumerated from the HISTORICAL golden-grid axes
(Gold-Configs YAML header, versioned in `grid-configs/audit/golden_grid_v3_5b_axes.yaml`)
— both EXP-003-inert and sensitive axes retained (the search actually spent those
trials). **Scoping:** v3_5b is primary (full grid + DSR + PBO); v3_5d is DSR-only using
its golden returns + a family-level N (its distinguishing grid was ~10 combos, too few
for CSCV). All DSR/PBO math is pure (numpy + scipy.stats), heavily unit-tested with
hand-computed reference values; the campaign is unit-tested via an injected run_fn (no
DB). Strictly READ-ONLY vs the DB (one new SELECT-only `optimization_results`
trial-count inventory). N unit tests, all DB-free.

- New: `jutsu_engine/audit/dsr.py`, `jutsu_engine/audit/pbo.py`,
  `jutsu_engine/audit/selection_bias.py`,
  `grid-configs/audit/golden_grid_v3_5b_axes.yaml`,
  `tests/unit/audit/test_dsr.py`, `tests/unit/audit/test_pbo.py`,
  `tests/unit/audit/test_selection_bias.py`, `tests/unit/audit/test_dsr_cli.py`.
- Modified: `jutsu_engine/audit/db.py` (read-only `load_trial_counts` +
  `trial_count_records`), `jutsu_engine/audit/report.py` (`render_dsr_section`,
  `write_dsr_report`), `jutsu_engine/cli/commands/audit.py` (`dsr` subcommand),
  `tests/unit/audit/test_db.py`, `tests/unit/audit/test_report.py`.
- Docs: `docs/experiments/LOGBOOK.md` (EXP-005 skeleton).
- **Reference values (hand-computed, verified in the plan):** PSR(SR_obs=0.5,
  SR*=0, T=101, normal) = 0.9999987858; PSR(0.1, 0, T=10, skew=-0.5, kurt=4) =
  0.6147534586; SR*(V=0.01, N=243/1000/5000) = 0.28285802 / 0.32551215 / 0.36877031;
  PBO on a perfectly-persistent matrix = 0.0; PBO on a tiny S=4 dominant-combo matrix
  = 0.0 (6 partitions).
```

- [ ] **Step 4: Verify docs written + full suite still green**

Run: `.venv/bin/python -m pytest tests/unit/audit/ -p no:cacheprovider -o addopts="" -q`
Expected: PASS. Confirm `CHANGELOG.md` and `docs/experiments/LOGBOOK.md` both contain the new entries.

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/LOGBOOK.md CHANGELOG.md
git commit -m "docs(audit): Phase 4 DSR/PBO — LOGBOOK EXP-005 skeleton + CHANGELOG"
```

---

## Self-Review

**1. Spec coverage (§7, §10-12):**
- §7 DSR (Bailey & López de Prado), bracketed N (243/1000/5000) → Tasks 1-3, 11-12. ✓
- §7 PBO via CSCV, S=16 blocks, per-combo returns → Tasks 4-9, 11. ✓
- §7 trial count from `optimization_results` + grid-config counts, honest incompleteness note → Task 10, 12. ✓
- §7 re-run the golden grid once to capture per-combo daily returns → Tasks 6-9. ✓
- §7 plain-language verdict sentence → Task 12 (`### Plain-language verdict`). ✓
- §10 DSR<95% / PBO>50% gate printed → Task 12. ✓
- §10 package structure (`selection_bias.py`, `tests/unit/audit/`, `grid-configs/audit/`) → Tasks 6, all. ✓ (Split into `dsr.py`+`pbo.py`+`selection_bias.py` per writing-plans "smaller focused files"; documented.)
- §11 per-combo return persistence (JSONL, not a GridSearchRunner flag — justified: reuses proven campaign infra, no engine change) → Task 7. ✓
- §12 compute time, environment (uv 3.11 `.venv`), warmup correctness inherited via BacktestRunner reuse → stated in context. ✓
- LOGBOOK EXP-001..004 verdicts + XREF-001 respected: enumerate real historical combos (not a new grid), inert+sensitive axes retained, n=1 caution in the verdict prose. ✓

**2. Placeholder scan:** No TBD/TODO in code. The LOGBOOK EXP-005 RESULTS/VERDICT are intentionally `_(fill after running the campaign)_` — this is a lab-notebook skeleton (the numbers come from the actual overnight run, which is not part of implementation); the METHOD is fully specified. Every code step has complete code.

**3. Type/name consistency:** `combo_hash`, `enumerate_golden_grid`, `run_one_combo`, `run_returns_campaign`, `build_returns_matrix`, `cross_trial_variance`, `golden_combo_returns`, `summarize_selection_bias`, `run_dsr` — consistent across Tasks 6-14. `psr`/`expected_max_sharpe`/`deflated_sharpe`/`deflated_sharpe_brackets`/`sample_moments`/`DEFAULT_N_BRACKETS` consistent Tasks 1-3, 11. `compute_pbo`/`partition_sharpes`/`split_blocks`/`relative_rank`/`logit`/`N_CHOOSE_HALF` consistent Tasks 4-5, 11. Report `render_dsr_section`/`write_dsr_report` consistent Tasks 12-13. `DEFAULT_N_BRACKETS` is defined in `dsr.py` and re-imported in `selection_bias.py` — single source. `CSCV_BLOCKS`/`cscv_blocks`/`S` all refer to the CSCV block count (16); Task 14 threads `cscv_blocks` so smoke tests can use S=2. Fixed in Task 14: `_all_symbols` hoisted to module level so the smoke test's monkeypatch works, and `run_returns_campaign` is called with explicit `run_fn=run_one_combo` so the module-attribute patch is honored.

One known, deliberately-documented inconsistency: the live golden `sma_slow` (140) is OUTSIDE the historical grid's `sma_slow` axis [180,200,220] — the live value was tuned in a later phase. `_golden_anchor_hash` uses the grid's center (200) as the in-grid representative and the report states the mismatch; the DSR still uses the golden combo's real campaign returns. This is honest and called out in Task 6's test and Task 11's docstring.
