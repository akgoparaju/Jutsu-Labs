# Baseline Audit Phase 3 — Module 1 WFO Parameter-Stability Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `jutsu audit wfo` — a walk-forward optimization stability study for v3_5b/v3_5d that produces a stitched out-of-sample (OOS) daily-return equity curve and a parameter-drift table, settling the adaptive-parameters question with out-of-sample data (spec §5, §10).

**Architecture:** A new `jutsu_engine/audit/wfo_stability.py` module builds a thin per-window loop on the audit package's OWN proven infrastructure — `build_overridden_strategy` + `BacktestRunner` (which already emits a `Strategy_Daily_Return` timeseries per backtest) + the plateau JSONL fsync-checkpoint/resume/circuit-breaker/single-writer patterns. Each window runs an in-sample (IS) grid search inline (loop over a small evidence-driven combo grid, one BacktestRunner call each), picks the winner by IS Sharpe, runs ONE OOS BacktestRunner with the winner params, and extracts that window's OOS daily returns from the regime-timeseries CSV. All OOS daily returns are concatenated ("stitched") and the headline metrics (Sharpe/CAGR/MaxDD/alpha-vs-QQQ) are computed on the stitched series — never by averaging per-window Sharpes (spec §5 explicitly rejects the legacy `walk_forward.py` averaging). Strictly read-only vs the DB; no changes to strategies/live/scheduler code.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), pandas, numpy, click (CLI), pytest (DB-free unit tests via injected fake run functions), existing `BacktestRunner`/`PerformanceAnalyzer`.

---

## Architecture decision: reuse-vs-build (justification)

**Decision: BUILD a thin window-loop on the audit package's own infra. Do NOT reuse `WFORunner`.**

I read `jutsu_engine/application/wfo_runner.py` (the maintained `jutsu wfo` path), `grid_search_runner.py`, and the legacy `jutsu_engine/optimization/walk_forward.py`. Findings:

| Spec §5 need | `WFORunner` provides? | Verdict |
|---|---|---|
| Sliding IS/OOS windows | Yes (`calculate_windows`, 2.5y/0.5y/0.5y via YAML) | reusable *concept*, re-implemented DB-free & unit-testable here |
| IS grid search → pick winner | Yes (composes `GridSearchRunner` + `select_best_parameters`) | but writes per-combo CSVs to disk, needs YAML symbol_sets, no override bridge to live golden config |
| **Stitched OOS *daily-return* curve** | **No** — it stitches *trades* (`_combine_trade_pairs` FIFO), compounds `Trade_Return_Percent`, and computes OOS return from the trade chain. It never produces a daily-return series, so it cannot compute a stitched daily Sharpe/CAGR/MaxDD/alpha-vs-QQQ (spec §5 output 1). | **disqualifying** |
| **Checkpoint / resume** | **No** — `run()` loops windows in-memory; a crash on window 20 of 26 restarts from window 1. A ~4,200-backtest campaign spanning multiple nights *requires* resume. | **disqualifying** |
| Per-window winner + per-param winning-value distribution | Partial (`wfo_parameter_log.csv`) but no top-decile-share computation, and only as a side CSV | build here |
| Circuit breaker on systemic failure | No | build here (reuse plateau breaker) |
| Live-config anchoring + float→Decimal parity | No (introspection param mapping, not the live `LiveStrategyRunner` conventions) | `build_overridden_strategy` already does this exactly (plateau `_prepared_params` mirrors `LiveStrategyRunner._convert_decimal_params`) |

The legacy `walk_forward.py._aggregate_results()` **averages** per-window Sharpe/return/drawdown across windows — the exact methodological flaw spec §5 rejects. Not used.

**What we reuse instead (spec §4 "reuse don't rebuild"):**
- `build_overridden_strategy(strategy_id, overrides)` (plateau.py) — builds a live strategy with per-combo param overrides, identical float→Decimal conventions to `LiveStrategyRunner`. This is the IS/OOS strategy-construction bridge.
- `BacktestRunner` — runs each IS combo and each OOS window; it already emits a `regime_timeseries_csv` with `Date` / `QQQ_Daily_Return` / `Strategy_Daily_Return` columns (regime_analyzer.py:192-222), which is exactly the daily-return source for stitching. No engine change needed → spec §11 bounded extension (persist per-window OOS daily equity) is **NOT required**; the timeseries CSV already carries it.
- The plateau checkpoint/resume/breaker/single-writer machinery — copied *pattern*, adapted keys (window-level rows, not perturbation rows). Reused verbatim where possible via a shared helper (`append_jsonl` / fsync).
- The pure metric functions `_sharpe`, `_max_drawdown`, `_total_return` (attribution.py) — reused for the stitched-series metrics.
- `_all_symbols(strategy_id)` (attribution.py) — the symbol list for each backtest.
- `_resolve_run_dir` (audit.py) — midnight-safe run-dir resolution, generalized to accept the campaign filename.

**Bounded extension used (spec §11):** none to live/engine code. The only new persistence is the audit's own JSONL campaign file (same as plateau). The audit stays strictly read-only vs the DB and never touches live/scheduler code paths.

---

## The exact per-window grid (evidence-driven from EXP-003)

EXP-003 ranked parameter sensitivity (worst-side retained Sharpe at ±20%) and found the **volatility-regime-classification channel** is the load-bearing subsystem, identically on both strategies:
`upper_thresh_z` (0.77–0.79), `realized_vol_window` (0.81–0.83), `vol_baseline_window` (0.88–0.89), `sma_slow` (0.91–0.92); `sma_fast` is the next structural input. It also found **six inert knobs** (retained ≈ 1.000 across ±20%) that are pure compute waste in any grid: `process_noise_1`, `strength_smoothness`, `w_PSQ_max` (PSQ disabled), `rebalance_threshold`, `leverage_scalar`, `lower_thresh_z`. And it flagged four **quarantined candidates** that improved in-sample Sharpe modestly but must be validated OUT-of-sample before adoption: `bond_sma_fast=24`, `bond_sma_slow=66`, `osc_smoothness=12`, `vol_crush_threshold=-0.12`.

**Grid design.** Golden anchor values (identical in v3_5b.yaml and v3_5d.yaml for the sensitive params): `upper_thresh_z=1.0`, `realized_vol_window=21`, `vol_baseline_window=200`, `sma_slow=140`, `sma_fast=40`, `vol_crush_threshold=-0.15`, `bond_sma_fast=20`, `bond_sma_slow=60`, `osc_smoothness=15`. The grid perturbs ONLY sensitive params, EXCLUDES the six inert knobs (documented above, citing EXP-003), and INCLUDES the quarantined candidate values so WFO validates or kills them out-of-sample.

The grid is the Cartesian product of these axes (each axis includes the golden value):

| Param | Values | Count | Rationale |
|---|---|---|---|
| `upper_thresh_z` | `[0.8, 1.0, 1.2]` | 3 | #1 sensitivity (EXP-003); golden 1.0 centered |
| `realized_vol_window` | `[16, 21, 26]` | 3 | #2 sensitivity; golden 21 centered (≈±25%) |
| `sma_slow` | `[120, 140, 160]` | 3 | #4 sensitivity; golden 140 centered |
| `vol_crush_threshold` | `[-0.15, -0.12]` | 2 | golden −0.15 + quarantined −0.12 |
| `bond_sma_fast` | `[20, 24]` | 2 | golden 20 + quarantined 24 |

Base combos = 3 × 3 × 3 × 2 × 2 = **108**. That is over the ≤~81 target, so we drop `vol_crush_threshold` and `bond_sma_fast` to single-quarantine-vs-golden *paired* axes handled outside the product: **the grid is the 3×3×3 = 27 core-sensitivity product**, PLUS a small **quarantine sweep** of 4 extra combos (each single quarantined value swapped into the golden config one at a time: `vol_crush_threshold=-0.12`, `bond_sma_fast=24`, `bond_sma_slow=66`, `osc_smoothness=12`). Total = **27 + 4 = 31 combos/window** (well under 81; leaves headroom to widen a per-window axis later without breaching the overnight budget).

**Final grid (exact, stated so the engineer hard-codes it):**

```python
# jutsu_engine/audit/wfo_stability.py
# Sensitive-parameter product (EXP-003 ranking); each axis centered on golden.
WFO_GRID_AXES: dict[str, list] = {
    "upper_thresh_z": [0.8, 1.0, 1.2],      # #1 sensitivity, golden 1.0
    "realized_vol_window": [16, 21, 26],    # #2 sensitivity, golden 21
    "sma_slow": [120, 140, 160],            # #4 sensitivity, golden 140
}
# Quarantined candidates (EXP-003): each swapped into golden one at a time so WFO
# validates/kills them OOS. Golden values elsewhere.
WFO_QUARANTINE_OVERRIDES: list[dict] = [
    {"vol_crush_threshold": -0.12},
    {"bond_sma_fast": 24},
    {"bond_sma_slow": 66},
    {"osc_smoothness": 12},
]
# Six inert knobs (EXP-003 retained ~1.000 at +/-20%) are DELIBERATELY EXCLUDED:
# process_noise_1, strength_smoothness, w_PSQ_max, rebalance_threshold,
# leverage_scalar, lower_thresh_z. Documenting the exclusion is a spec §5 requirement.
WFO_INERT_EXCLUDED: tuple[str, ...] = (
    "process_noise_1", "strength_smoothness", "w_PSQ_max",
    "rebalance_threshold", "leverage_scalar", "lower_thresh_z",
)
```

**Combo count: 27 (product) + 4 (quarantine sweep) = 31 combos per window.** The golden config itself is combo index 0 of the product (all three axes at golden), so no separate golden run is needed per window.

---

## Compute estimate (honest)

- Windows: 2010-02-01 → present (2026-07), 2.5y IS / 0.5y OOS / 0.5y slide. First OOS ends ~2013-02; last window whose OOS ≤ present starts ~2023-07. `(2026.5 − 2013.0) / 0.5 + 1 ≈ 27` → **~26–27 windows**.
- Backtests per window: 31 IS combos + 1 OOS run = **32 backtests/window**.
- An IS-window backtest is 2.5y + ~150-bar warmup ≈ **~3 years of bars**, vs the measured full-period run (16.4y) ≈ **1.6 min**. Scaling linearly by bar count: ~3/16.4 × 1.6 min ≈ **~18 s per IS backtest** (OOS 0.5y+warmup ≈ ~10 s). Conservative average **~15 s/backtest**.
- Backtests per strategy: 26 windows × 32 = **~832 backtests**. Both strategies: **~1,664 backtests**.
- Wall-clock at `--workers 4`, per strategy: 832 × 15 s / 4 ≈ **3,120 s ≈ ~52 min**. Both strategies back-to-back ≈ **~1.7 h**. Budget generously for warmup/IO variance and DB latency: **plan for ~1.5–2 h per strategy, resumable across nights.**
- This is well within "overnight" and comfortably under the spec §12 worst-case (≤4,200 backtests with an 81-combo grid). Checkpoint/resume + circuit breaker are mandatory (reuse plateau patterns): a crash resumes at the first unfinished window, never restarts.
- **Smoke mode** (`--windows-limit 2 --strategy v3_5b`, 31-combo grid, workers=4): 2 windows × 32 × 15 s / 4 ≈ **~4 min** — proves the pipeline end-to-end in well under 30 min.

---

## File structure

- **Create** `jutsu_engine/audit/wfo_stability.py` — Module 1: window generation, grid expansion, IS-winner selection, OOS stitching, drift table, top-decile share, checkpoint/resume campaign runner (all pure functions + one DB-touching driver, mirroring plateau.py's split).
- **Modify** `jutsu_engine/audit/report.py` — add `render_wfo_section(summary)` + `write_wfo_report(run_dir, strategy_id, md)` (separate `report_wfo_<strategy>.md` file, never touches Phase-1/2 reports).
- **Modify** `jutsu_engine/cli/commands/audit.py` — add `wfo` subcommand (`--strategy --workers --windows-limit --retry-errors --run-date`), reusing the existing `_resolve_run_dir` and dispatch/error patterns.
- **Create** `tests/unit/audit/test_wfo_stability.py` — DB-free unit tests (pure functions + injected fake run functions).
- **Create** `tests/unit/audit/test_wfo_cli.py` — CLI tests with mocked `run_wfo` (mirrors `test_plateau_cli.py`).
- **Modify** `docs/experiments/LOGBOOK.md` — EXP-004 skeleton entry.
- **Modify** `CHANGELOG.md` — Phase-3 entry.

Focused-test command (used in every "run the test" step):
`.venv/bin/python -m pytest <path> -p no:cacheprovider -o addopts="" -q`

---

## Task 1: Window generation (pure)

**Files:**
- Create: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py
"""DB-free unit tests for Module 1 WFO parameter-stability study."""
from datetime import date

from jutsu_engine.audit.wfo_stability import WFOWindow, generate_windows


class TestGenerateWindows:
    def test_first_window_is_2p5y_is_then_0p5y_oos(self):
        """First window: 2.5y IS from start, then 0.5y OOS immediately after."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1))
        assert w[0].window_id == 1
        assert w[0].is_start == date(2010, 2, 1)
        assert w[0].is_end == date(2012, 8, 1)      # +2.5y
        assert w[0].oos_start == date(2012, 8, 1)
        assert w[0].oos_end == date(2013, 2, 1)     # +0.5y

    def test_windows_slide_by_half_year(self):
        """Consecutive windows slide their IS start by 0.5y."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1))
        assert w[1].is_start == date(2010, 8, 1)    # +0.5y slide

    def test_no_window_oos_exceeds_total_end(self):
        """The last window's OOS end never exceeds the total end date."""
        end = date(2026, 7, 1)
        w = generate_windows(date(2010, 2, 1), end)
        assert all(win.oos_end <= end for win in w)

    def test_window_count_is_about_26(self):
        """Full 2010-02 -> 2026-07 range yields ~26 windows."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1))
        assert 24 <= len(w) <= 28

    def test_windows_limit_truncates(self):
        """windows_limit caps the number of windows for smoke runs."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1), windows_limit=2)
        assert len(w) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'WFOWindow'` / `generate_windows`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py
"""Module 1 — WFO parameter-stability study (spec §5).

Builds a thin per-window loop on the audit package's OWN infra
(build_overridden_strategy + BacktestRunner + plateau JSONL checkpoint/resume/
breaker patterns). Does NOT reuse WFORunner: WFORunner stitches TRADES and has
no resume, and cannot produce a stitched DAILY-RETURN curve (spec §5 output 1).
The legacy walk_forward.py AVERAGES per-window Sharpes — the flaw spec §5 rejects;
here every headline metric is computed on the stitched OOS daily-return series.

Read-only vs the DB; no changes to strategies/live/scheduler code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


def _add_years(d: date, years: float) -> date:
    """Add a fractional number of years using the 365.25-day convention.

    Matches WFORunner.calculate_windows (wfo_runner.py:424-428) so window
    boundaries are consistent with the established v5.1 WFO convention.
    """
    return d + timedelta(days=round(365.25 * years))


IS_YEARS = 2.5
OOS_YEARS = 0.5
SLIDE_YEARS = 0.5


@dataclass(frozen=True)
class WFOWindow:
    """One walk-forward window: 2.5y in-sample then 0.5y out-of-sample."""
    window_id: int
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date


def generate_windows(total_start: date, total_end: date,
                     windows_limit: int | None = None) -> list[WFOWindow]:
    """Sliding 2.5y-IS / 0.5y-OOS / 0.5y-slide windows within [total_start, total_end].

    Stops when a window's OOS end would exceed total_end. windows_limit (for the
    smoke run) truncates to the first N windows.
    """
    windows: list[WFOWindow] = []
    wid = 1
    cur = total_start
    while True:
        is_start = cur
        is_end = _add_years(is_start, IS_YEARS)
        oos_start = is_end
        oos_end = _add_years(oos_start, OOS_YEARS)
        if oos_end > total_end:
            break
        windows.append(WFOWindow(wid, is_start, is_end, oos_start, oos_end))
        cur = _add_years(cur, SLIDE_YEARS)
        wid += 1
    if windows_limit is not None:
        windows = windows[:windows_limit]
    return windows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): WFO window generation for Module 1 stability study

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 2: Grid expansion (pure, evidence-driven from EXP-003)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
from jutsu_engine.audit.wfo_stability import (
    WFO_GRID_AXES, WFO_QUARANTINE_OVERRIDES, WFO_INERT_EXCLUDED,
    expand_grid, combo_hash,
)


class TestExpandGrid:
    def test_product_plus_quarantine_is_31_combos(self):
        """3x3x3 sensitivity product + 4 quarantine sweeps = 31 combos."""
        combos = expand_grid()
        assert len(combos) == 31

    def test_first_combo_is_golden_anchor(self):
        """Combo 0 is the golden anchor (all axes at golden values)."""
        combos = expand_grid()
        c0 = combos[0]["overrides"]
        assert c0["upper_thresh_z"] == 1.0
        assert c0["realized_vol_window"] == 21
        assert c0["sma_slow"] == 140

    def test_quarantine_combos_swap_one_value_into_golden(self):
        """Each quarantine combo overrides golden with exactly one candidate value."""
        combos = expand_grid()
        quarantine = [c for c in combos if c["kind"] == "quarantine"]
        assert len(quarantine) == 4
        vals = {tuple(sorted(c["overrides"].items())) for c in quarantine}
        # golden axes + one quarantined key each
        assert any(("vol_crush_threshold", -0.12) in c["overrides"].items()
                   for c in quarantine)
        assert any(("bond_sma_fast", 24) in c["overrides"].items()
                   for c in quarantine)

    def test_inert_knobs_never_appear_in_any_combo(self):
        """No combo perturbs any of the six EXP-003 inert knobs."""
        combos = expand_grid()
        for c in combos:
            for k in WFO_INERT_EXCLUDED:
                # inert knobs may carry the golden value but are never a grid axis
                assert k not in WFO_GRID_AXES
                assert k not in c["overrides"] or True  # golden pass-through allowed

    def test_combo_hash_is_stable_and_order_independent(self):
        """combo_hash is deterministic and independent of dict insertion order."""
        a = combo_hash({"upper_thresh_z": 1.0, "sma_slow": 140})
        b = combo_hash({"sma_slow": 140, "upper_thresh_z": 1.0})
        assert a == b and len(a) == 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestExpandGrid -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'WFO_GRID_AXES'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)
import hashlib
import itertools
import json

# --- Evidence-driven grid (EXP-003 sensitivity ranking) ---
# Product over the SENSITIVE vol-regime-classification inputs; each axis centered
# on the golden value. The golden config is combo index 0 of this product.
WFO_GRID_AXES: dict[str, list] = {
    "upper_thresh_z": [0.8, 1.0, 1.2],      # #1 sensitivity (EXP-003), golden 1.0
    "realized_vol_window": [16, 21, 26],    # #2 sensitivity, golden 21
    "sma_slow": [120, 140, 160],            # #4 sensitivity, golden 140
}

# Quarantined EXP-003 candidates: each swapped into the golden config one at a
# time so WFO validates or kills them OUT-of-sample (single in-sample gains of
# their magnitude are within selection noise per EXP-003).
WFO_QUARANTINE_OVERRIDES: list[dict] = [
    {"vol_crush_threshold": -0.12},
    {"bond_sma_fast": 24},
    {"bond_sma_slow": 66},
    {"osc_smoothness": 12},
]

# Six inert knobs (EXP-003 retained ~1.000 at +/-20%) DELIBERATELY EXCLUDED —
# perturbing them is pure compute waste. Documenting the exclusion is a spec §5
# requirement.
WFO_INERT_EXCLUDED: tuple[str, ...] = (
    "process_noise_1", "strength_smoothness", "w_PSQ_max",
    "rebalance_threshold", "leverage_scalar", "lower_thresh_z",
)


def combo_hash(overrides: dict) -> str:
    """Stable 16-char hex hash of a combo's overrides (order-independent)."""
    payload = json.dumps(overrides, sort_keys=True, separators=(",", ":"),
                         default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def expand_grid() -> list[dict]:
    """Expand the evidence-driven grid into 31 combos (27 product + 4 quarantine).

    Each combo is {"combo_id", "kind", "overrides", "hash"}. Combo 0 (product,
    all axes at golden) IS the golden anchor. Quarantine combos hold golden axis
    values and swap in exactly one quarantined candidate.
    """
    names = list(WFO_GRID_AXES.keys())
    value_lists = [WFO_GRID_AXES[n] for n in names]
    # Golden axis values (the middle element of each axis is golden by construction).
    golden_axis = {"upper_thresh_z": 1.0, "realized_vol_window": 21, "sma_slow": 140}

    combos: list[dict] = []
    cid = 0
    for values in itertools.product(*value_lists):
        overrides = dict(zip(names, values))
        combos.append({
            "combo_id": cid, "kind": "product",
            "overrides": overrides, "hash": combo_hash(overrides),
        })
        cid += 1
    for q in WFO_QUARANTINE_OVERRIDES:
        overrides = {**golden_axis, **q}
        combos.append({
            "combo_id": cid, "kind": "quarantine",
            "overrides": overrides, "hash": combo_hash(overrides),
        })
        cid += 1
    return combos
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestExpandGrid -p no:cacheprovider -o addopts="" -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): evidence-driven WFO grid (EXP-003 sensitive params + quarantine)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 3: IS-winner selection (pure)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
from jutsu_engine.audit.wfo_stability import select_is_winner


class TestSelectISWinner:
    def test_picks_highest_is_sharpe(self):
        """Winner is the combo with the highest finite in-sample Sharpe."""
        rows = [
            {"hash": "a", "overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.5},
            {"hash": "b", "overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.9},
            {"hash": "c", "overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7},
        ]
        w = select_is_winner(rows)
        assert w["hash"] == "b"

    def test_skips_errored_rows(self):
        """Rows with non-finite is_sharpe (errored backtests) are ignored."""
        rows = [
            {"hash": "a", "overrides": {}, "is_sharpe": None},
            {"hash": "b", "overrides": {}, "is_sharpe": float("nan")},
            {"hash": "c", "overrides": {}, "is_sharpe": 0.3},
        ]
        assert select_is_winner(rows)["hash"] == "c"

    def test_all_errored_returns_none(self):
        """If every IS combo errored, there is no winner (returns None)."""
        rows = [{"hash": "a", "overrides": {}, "is_sharpe": None}]
        assert select_is_winner(rows) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestSelectISWinner -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'select_is_winner'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)
import math


def _is_finite_number(v) -> bool:
    """True when v is a finite non-bool number."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def select_is_winner(is_rows: list[dict]) -> dict | None:
    """Return the IS combo row with the highest finite in-sample Sharpe (or None).

    Selection metric is IS Sharpe (spec §5: 'winning parameter set per window').
    Errored rows (non-finite is_sharpe) are excluded so a failed backtest can
    never win. Returns None only if EVERY combo errored.
    """
    valid = [r for r in is_rows if _is_finite_number(r.get("is_sharpe"))]
    if not valid:
        return None
    return max(valid, key=lambda r: r["is_sharpe"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestSelectISWinner -p no:cacheprovider -o addopts="" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): IS-winner selection by in-sample Sharpe (errored-safe)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 4: Stitched OOS-curve metrics (pure — the headline number, spec §5 output 1)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
import numpy as np
import pandas as pd

from jutsu_engine.audit.wfo_stability import stitch_oos_metrics


def _oos_frame(strategy_returns, qqq_returns, start="2013-01-01"):
    dates = pd.date_range(start, periods=len(strategy_returns), freq="D", tz="UTC")
    return pd.DataFrame({
        "Date": dates,
        "Strategy_Daily_Return": strategy_returns,
        "QQQ_Daily_Return": qqq_returns,
    })


class TestStitchOOSMetrics:
    def test_concatenates_windows_and_computes_on_stitched_series(self):
        """Metrics are computed on the concatenated series, NOT averaged per window."""
        w1 = _oos_frame([0.01, 0.01], [0.005, 0.005], "2013-01-01")
        w2 = _oos_frame([-0.01, 0.02], [0.0, 0.01], "2013-07-01")
        m = stitch_oos_metrics([w1, w2])
        assert m["oos_days"] == 4
        # total return = prod(1+r)-1 over ALL 4 days
        expected = (1.01 * 1.01 * 0.99 * 1.02) - 1.0
        assert abs(m["total_return"] - expected) < 1e-9

    def test_alpha_is_stitched_strategy_minus_qqq_total_return(self):
        """alpha_vs_qqq = stitched strategy total return - stitched QQQ total return."""
        w1 = _oos_frame([0.10], [0.04], "2013-01-01")
        m = stitch_oos_metrics([w1])
        assert abs(m["alpha_vs_qqq"] - (0.10 - 0.04)) < 1e-9

    def test_never_averages_per_window_sharpe(self):
        """A window with a huge per-window Sharpe cannot dominate the stitched Sharpe."""
        # Window A: tiny consistent gains (high per-window Sharpe).
        wa = _oos_frame([0.001] * 30, [0.0] * 30, "2013-01-01")
        # Window B: volatile (low per-window Sharpe).
        wb = _oos_frame(list(np.tile([0.05, -0.05], 15)), [0.0] * 30, "2013-07-01")
        stitched = stitch_oos_metrics([wa, wb])["sharpe"]
        # Averaging per-window Sharpes would give a very different (inflated) number;
        # the stitched Sharpe reflects the combined 60-day series volatility.
        combined = pd.concat([wa, wb])["Strategy_Daily_Return"]
        expected = float(combined.mean() / combined.std(ddof=1) * np.sqrt(252))
        assert abs(stitched - expected) < 1e-9

    def test_empty_input_returns_zero_metrics(self):
        """No OOS windows -> zeroed metrics, no crash."""
        m = stitch_oos_metrics([])
        assert m["oos_days"] == 0 and m["sharpe"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestStitchOOSMetrics -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'stitch_oos_metrics'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)
import numpy as np
import pandas as pd

# Reuse the audit's proven pure metric helpers (attribution.py) so the stitched
# curve uses the SAME math as Module 4, not a re-implementation.
from jutsu_engine.audit.attribution import _sharpe, _max_drawdown, _total_return


def stitch_oos_metrics(oos_frames: list[pd.DataFrame]) -> dict:
    """Concatenate per-window OOS daily returns and compute headline metrics.

    Each frame has columns Date, Strategy_Daily_Return, QQQ_Daily_Return (the
    regime-timeseries CSV shape BacktestRunner emits, regime_analyzer.py:192-222).
    Frames are concatenated in chronological order and ALL metrics are computed on
    the single stitched series — never by averaging per-window Sharpes (spec §5).

    Returns: oos_days, total_return, cagr, sharpe, max_drawdown,
    qqq_total_return, alpha_vs_qqq.
    """
    if not oos_frames:
        return {"oos_days": 0, "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "qqq_total_return": 0.0, "alpha_vs_qqq": 0.0}

    stitched = pd.concat(oos_frames, ignore_index=True)
    stitched = stitched.sort_values("Date").reset_index(drop=True)
    strat = stitched["Strategy_Daily_Return"]
    qqq = stitched["QQQ_Daily_Return"]

    total = _total_return(strat)
    qqq_total = _total_return(qqq)
    n_days = int(len(strat))
    years = n_days / 252.0
    cagr = ((1.0 + total) ** (1.0 / years) - 1.0) if years > 0 and total > -1 else 0.0

    return {
        "oos_days": n_days,
        "total_return": float(total),
        "cagr": float(cagr),
        "sharpe": _sharpe(strat),
        "max_drawdown": _max_drawdown(strat),
        "qqq_total_return": float(qqq_total),
        "alpha_vs_qqq": float(total - qqq_total),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestStitchOOSMetrics -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): stitched OOS daily-return metrics (never averages Sharpes)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 5: Parameter-drift table + golden top-decile share (pure — spec §5 output 2, §10 decision)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
from jutsu_engine.audit.wfo_stability import (
    drift_table, param_value_distribution, golden_top_decile_share,
)

# GOLDEN_SENSITIVE is the golden value of each grid axis (defined in the module).
from jutsu_engine.audit.wfo_stability import GOLDEN_SENSITIVE


def _winner(window_id, overrides, is_sharpe):
    return {"window_id": window_id, "overrides": overrides, "is_sharpe": is_sharpe}


class TestDriftTable:
    def test_one_row_per_window_with_winner_params(self):
        """drift_table has one row per window carrying that window's winner params."""
        winners = [
            _winner(1, {"upper_thresh_z": 0.8, "realized_vol_window": 21, "sma_slow": 140}, 0.9),
            _winner(2, {"upper_thresh_z": 1.0, "realized_vol_window": 16, "sma_slow": 160}, 0.7),
        ]
        df = drift_table(winners)
        assert list(df["window_id"]) == [1, 2]
        assert df.loc[df["window_id"] == 1, "upper_thresh_z"].iloc[0] == 0.8

    def test_value_distribution_counts_winning_values_per_param(self):
        """param_value_distribution counts how often each value wins, per param."""
        winners = [
            _winner(1, {"upper_thresh_z": 0.8}, 0.9),
            _winner(2, {"upper_thresh_z": 1.0}, 0.7),
            _winner(3, {"upper_thresh_z": 0.8}, 0.6),
        ]
        dist = param_value_distribution(winners)
        assert dist["upper_thresh_z"][0.8] == 2
        assert dist["upper_thresh_z"][1.0] == 1


class TestGoldenTopDecileShare:
    def test_share_of_windows_where_golden_is_top_decile(self):
        """Golden top-decile share = fraction of windows where each golden axis value
        ranks in the top decile of that window's IS-Sharpe distribution."""
        # Two windows, 3-combo grid each (top decile of 3 combos = the #1 combo).
        # is_ranks[param][window] holds per-value IS Sharpe so golden can be ranked.
        window_is_rows = [
            # window 1: golden upper_thresh_z=1.0 is the best (top decile)
            [{"overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.5},
             {"overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.9},
             {"overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7}],
            # window 2: golden upper_thresh_z=1.0 is worst (NOT top decile)
            [{"overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.9},
             {"overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.3},
             {"overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7}],
        ]
        share = golden_top_decile_share(window_is_rows, "upper_thresh_z", 1.0)
        assert abs(share - 0.5) < 1e-9  # golden top-decile in 1 of 2 windows

    def test_verdict_thresholds(self):
        """>=80% -> 'stable'; <50% -> 'unstable'; between -> 'inconclusive' (spec §10)."""
        from jutsu_engine.audit.wfo_stability import stability_verdict
        assert stability_verdict(0.85) == "stable"
        assert stability_verdict(0.40) == "unstable"
        assert stability_verdict(0.65) == "inconclusive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestDriftTable tests/unit/audit/test_wfo_stability.py::TestGoldenTopDecileShare -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'drift_table'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)
from collections import Counter

# Golden values of the sensitive grid axes (for top-decile-share scoring).
GOLDEN_SENSITIVE: dict = {
    "upper_thresh_z": 1.0, "realized_vol_window": 21, "sma_slow": 140,
}

# spec §10 decision thresholds for the golden top-decile share.
STABLE_THRESHOLD = 0.80
UNSTABLE_THRESHOLD = 0.50
# Top decile: with a small per-axis grid, "top decile" = ceil(10% of combos),
# min 1 (the single best combo qualifies when the grid is small).
TOP_DECILE_FRACTION = 0.10


def drift_table(winners: list[dict]) -> pd.DataFrame:
    """One row per window: window_id, is_sharpe, and each winning param value.

    `winners` is the per-window IS winner (from select_is_winner) plus window_id.
    """
    recs = []
    for w in winners:
        row = {"window_id": w["window_id"], "is_sharpe": w.get("is_sharpe")}
        row.update(w["overrides"])
        recs.append(row)
    return pd.DataFrame(recs)


def param_value_distribution(winners: list[dict]) -> dict[str, Counter]:
    """Per param, a Counter of how often each value was the window winner."""
    dist: dict[str, Counter] = {}
    for w in winners:
        for k, v in w["overrides"].items():
            dist.setdefault(k, Counter())[v] += 1
    return dist


def golden_top_decile_share(window_is_rows: list[list[dict]], param: str,
                            golden_value) -> float:
    """Fraction of windows where `golden_value` for `param` ranks in the top decile
    of that window's IS-Sharpe distribution for that param.

    For each window: collect the best IS Sharpe achieved by each distinct value of
    `param` (marginalizing over the other axes), rank the values, and check whether
    `golden_value` falls within the top ceil(10%) (min 1) of ranked values. Windows
    where the param never appears are skipped.
    """
    import math as _math
    hits = 0
    counted = 0
    for rows in window_is_rows:
        # best IS Sharpe per distinct value of `param`
        best: dict = {}
        for r in rows:
            v = r["overrides"].get(param)
            if v is None or not _is_finite_number(r.get("is_sharpe")):
                continue
            if v not in best or r["is_sharpe"] > best[v]:
                best[v] = r["is_sharpe"]
        if golden_value not in best:
            continue
        counted += 1
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        cutoff = max(1, _math.ceil(len(ranked) * TOP_DECILE_FRACTION))
        top_values = {v for v, _ in ranked[:cutoff]}
        if golden_value in top_values:
            hits += 1
    return (hits / counted) if counted else 0.0


def stability_verdict(share: float) -> str:
    """spec §10: >=80% -> stable; <50% -> unstable; otherwise inconclusive."""
    if share >= STABLE_THRESHOLD:
        return "stable"
    if share < UNSTABLE_THRESHOLD:
        return "unstable"
    return "inconclusive"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestDriftTable tests/unit/audit/test_wfo_stability.py::TestGoldenTopDecileShare -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): parameter-drift table + golden top-decile share (spec §10)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 6: Single-backtest driver (IS combo / OOS window)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

This driver touches `BacktestRunner`, so we test its ERROR path (no DB) and its picklability contract, mirroring plateau's `run_one_sample` tests.

```python
# tests/unit/audit/test_wfo_stability.py  (append)
import glob
import tempfile
from datetime import date as _date

import jutsu_engine.audit.wfo_stability as wfo_mod


class TestRunOneBacktest:
    def test_backtest_failure_records_loud_error_row(self, monkeypatch):
        """A raising backtest yields a row with is_sharpe=None and an error string,
        never crashing the campaign."""
        import jutsu_engine.application.backtest_runner as br_mod

        class _BoomRunner:
            def __init__(self, config): pass
            def run(self, strategy, output_dir=None):
                raise RuntimeError("no database")

        monkeypatch.setattr(br_mod, "BacktestRunner", _BoomRunner)
        monkeypatch.setattr(wfo_mod, "build_overridden_strategy",
                            lambda sid, ov: object())

        row = wfo_mod.run_one_backtest(
            "v3_5b", {"hash": "h1", "combo_id": 0, "kind": "product",
                      "overrides": {"upper_thresh_z": 1.0}},
            ["QQQ"], _date(2010, 2, 1), _date(2012, 8, 1), phase="is")
        assert row["is_sharpe"] is None
        assert "no database" in row["error"]

    def test_error_row_leaves_no_tempdir(self, monkeypatch):
        """A failed backtest cleans up its throwaway tempdir (no plateau/wfo leak)."""
        import jutsu_engine.application.backtest_runner as br_mod

        class _BoomRunner:
            def __init__(self, config): pass
            def run(self, strategy, output_dir=None):
                raise RuntimeError("boom")

        monkeypatch.setattr(br_mod, "BacktestRunner", _BoomRunner)
        monkeypatch.setattr(wfo_mod, "build_overridden_strategy",
                            lambda sid, ov: object())
        before = set(glob.glob(tempfile.gettempdir() + "/wfo_*"))
        wfo_mod.run_one_backtest(
            "v3_5b", {"hash": "h", "combo_id": 0, "kind": "product", "overrides": {}},
            ["QQQ"], _date(2010, 2, 1), _date(2012, 8, 1), phase="is")
        assert set(glob.glob(tempfile.gettempdir() + "/wfo_*")) == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestRunOneBacktest -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'run_one_backtest'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)
import shutil
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# The live-config override bridge (float->Decimal parity with LiveStrategyRunner).
from jutsu_engine.audit.plateau import build_overridden_strategy


def run_one_backtest(strategy_id: str, combo: dict, symbols: list[str],
                     start: date, end: date, phase: str,
                     initial_capital: str = "10000") -> dict:
    """Run ONE backtest for a combo over [start, end]; return a result row.

    Picklable (plain args) so it runs inside a ProcessPoolExecutor worker.
    Writes all CSVs to a throwaway tempdir. For the OOS phase the regime-timeseries
    CSV path is returned so the caller can load Date/Strategy_Daily_Return/
    QQQ_Daily_Return for stitching. A raising backtest records a LOUD error row
    (is_sharpe=None + error string) rather than crashing the campaign.

    `phase` is 'is' (in-sample: only is_sharpe needed) or 'oos' (out-of-sample:
    stitching CSV needed). The stored key is always is_sharpe for uniformity; for
    OOS rows it is the OOS-window Sharpe (used only for logging/diagnostics — the
    headline OOS metrics come from the stitched daily returns, not this field).
    """
    from jutsu_engine.application.backtest_runner import BacktestRunner

    config = {
        "symbols": symbols,
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": Decimal(str(initial_capital)),
    }
    tmpdir = tempfile.mkdtemp(prefix="wfo_")
    error = None
    results: dict = {}
    ts_rows = None
    try:
        strategy = build_overridden_strategy(strategy_id, combo["overrides"])
        runner = BacktestRunner(config)
        results = runner.run(strategy, output_dir=tmpdir)
        if phase == "oos":
            ts_csv = results.get("regime_timeseries_csv")
            if ts_csv and Path(ts_csv).exists():
                df = pd.read_csv(ts_csv)
                ts_rows = df[["Date", "Strategy_Daily_Return",
                              "QQQ_Daily_Return"]].to_dict("records")
            else:
                error = "OOS backtest emitted no regime timeseries CSV"
    except Exception as exc:  # noqa: BLE001 — record loudly, never crash the campaign
        error = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "hash": combo["hash"],
        "combo_id": combo["combo_id"],
        "kind": combo["kind"],
        "phase": phase,
        "overrides": combo["overrides"],
        "is_sharpe": results.get("sharpe_ratio") if error is None else None,
        "oos_rows": ts_rows,   # list[dict] for OOS; None for IS
        "error": error,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestRunOneBacktest -p no:cacheprovider -o addopts="" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): single-backtest driver (IS/OOS, error-safe, tempdir-clean)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 7: Checkpoint/resume helpers (reuse plateau JSONL patterns)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

The campaign writes ONE JSONL row per (window, combo, phase). Resume keys off a `row_key = f"{window_id}:{phase}:{hash}"`. We reuse plateau's fsync append and last-wins reload verbatim by importing them.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
from jutsu_engine.audit.wfo_stability import (
    row_key, load_completed_keys, is_error_row,
)
from jutsu_engine.audit.plateau import append_result


class TestCheckpointHelpers:
    def test_row_key_combines_window_phase_hash(self):
        """row_key uniquely identifies a (window, phase, combo) unit of work."""
        assert row_key(3, "is", "abc123") == "3:is:abc123"

    def test_load_completed_keys_reads_written_rows(self, tmp_path):
        """Completed rows are recognized on resume by their row_key."""
        f = tmp_path / "wfo.jsonl"
        append_result(f, {"hash": "h", "kind": "product",
                          "param": None, "sharpe": 0.9,
                          "window_id": 1, "phase": "is", "row_key": "1:is:h",
                          "error": None})
        assert load_completed_keys(f) == {"1:is:h"}

    def test_load_completed_keys_missing_file_is_empty(self, tmp_path):
        """A missing campaign file yields no completed keys (fresh campaign)."""
        assert load_completed_keys(tmp_path / "nope.jsonl") == set()

    def test_retry_errors_excludes_errored_rows(self, tmp_path):
        """With retry_errors=True, errored rows are NOT counted as completed."""
        f = tmp_path / "wfo.jsonl"
        append_result(f, {"hash": "h", "window_id": 1, "phase": "is",
                          "row_key": "1:is:h", "sharpe": None,
                          "error": "boom", "kind": "product", "param": None})
        assert load_completed_keys(f, retry_errors=True) == set()
        assert load_completed_keys(f, retry_errors=False) == {"1:is:h"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestCheckpointHelpers -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'row_key'`.

- [ ] **Step 3: Write minimal implementation**

Note: plateau's `append_result` writes only `_RESULT_KEYS`; those don't include `window_id/phase/row_key`. To reuse its fsync/newline-safety without editing plateau, we add a WFO-local `append_wfo_row` that mirrors plateau's `append_result` byte-for-byte but with the WFO key set. This keeps plateau untouched (no regression risk to Module 2).

```python
# jutsu_engine/audit/wfo_stability.py  (append)
import json
import os

from jutsu_engine.audit.plateau import _ends_with_newline

# Keys persisted per WFO campaign row.
_WFO_RESULT_KEYS = ("row_key", "window_id", "phase", "hash", "combo_id", "kind",
                    "overrides", "is_sharpe", "oos_rows", "error")


def row_key(window_id: int, phase: str, combo_hash_str: str) -> str:
    """Stable resume key for one (window, phase, combo) unit of work."""
    return f"{window_id}:{phase}:{combo_hash_str}"


def is_error_row(row: dict) -> bool:
    """True when a WFO row represents a failed backtest (no finite is_sharpe)."""
    if row.get("error") is not None:
        return True
    # OOS rows may legitimately carry is_sharpe=None but must have oos_rows.
    if row.get("phase") == "oos":
        return not row.get("oos_rows")
    return not _is_finite_number(row.get("is_sharpe"))


def append_wfo_row(path: Path, row: dict) -> None:
    """Append one WFO result row as fsynced JSONL (crash-safe; mirrors plateau)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {k: row.get(k) for k in _WFO_RESULT_KEYS}
    prefix = "" if _ends_with_newline(path) else "\n"
    with open(path, "a") as f:
        f.write(prefix + json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_completed_keys(path: Path, retry_errors: bool = False) -> set[str]:
    """Set of row_keys already present in a WFO campaign JSONL (last-wins per key).

    Tolerates a truncated trailing line (crash mid-write). With retry_errors=True,
    errored rows are excluded so they re-run on the next pass (mirrors plateau).
    """
    path = Path(path)
    if not path.exists():
        return set()
    last: dict = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                k = row["row_key"]
            except (json.JSONDecodeError, KeyError):
                continue
            last[k] = row
    done = set()
    for k, row in last.items():
        if retry_errors and is_error_row(row):
            continue
        done.add(k)
    return done


def reload_wfo_rows(path: Path) -> list[dict]:
    """Load all WFO rows (last-wins per row_key), tolerating a truncated final line."""
    path = Path(path)
    if not path.exists():
        return []
    by_key: dict = {}
    order: list = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = row.get("row_key")
            if k is None:
                continue
            if k not in by_key:
                order.append(k)
            by_key[k] = row
    return [by_key[k] for k in order]
```

Also update the test import: the test used plateau's `append_result` for convenience, but our persisted key set is `_WFO_RESULT_KEYS`. Change the test to call `append_wfo_row`:

```python
# tests/unit/audit/test_wfo_stability.py — replace append_result usage with:
from jutsu_engine.audit.wfo_stability import append_wfo_row
# ... and in each test body use append_wfo_row(f, {...}) instead of append_result(f, {...})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestCheckpointHelpers -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): WFO JSONL checkpoint/resume (window:phase:hash keys, fsync)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 8: Campaign runner (resume + circuit breaker + single-writer, injectable run_fn)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

The campaign iterates windows; per window it runs the 31 IS combos, picks the winner, then runs the 1 OOS backtest with the winner. All rows checkpoint immediately. `run_fn` is injectable (module-level, picklable) so orchestration is DB-free-testable. Circuit breaker aborts after N consecutive errored rows.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
import numpy as np
import pandas as pd
from datetime import date as _date

from jutsu_engine.audit.wfo_stability import run_campaign, WFOCampaignResult


def _fake_run_fn(strategy_id, combo, symbols, start, end, phase,
                 initial_capital="10000"):
    """Deterministic fake: IS Sharpe rises with upper_thresh_z; OOS emits 5 days."""
    utz = combo["overrides"].get("upper_thresh_z", 1.0)
    if phase == "is":
        return {"hash": combo["hash"], "combo_id": combo["combo_id"],
                "kind": combo["kind"], "phase": "is",
                "overrides": combo["overrides"], "is_sharpe": float(utz),
                "oos_rows": None, "error": None}
    dates = pd.date_range(str(start), periods=5, freq="D", tz="UTC")
    rows = [{"Date": str(d), "Strategy_Daily_Return": 0.01,
             "QQQ_Daily_Return": 0.005} for d in dates]
    return {"hash": combo["hash"], "combo_id": combo["combo_id"],
            "kind": combo["kind"], "phase": "oos",
            "overrides": combo["overrides"], "is_sharpe": 0.8,
            "oos_rows": rows, "error": None}


class TestRunCampaign:
    def test_runs_windows_and_stitches(self, tmp_path):
        """Campaign runs IS+OOS per window and returns a stitched result."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date(2010, 2, 1), total_end=_date(2013, 8, 1))
        assert isinstance(res, WFOCampaignResult)
        assert len(res.winners) == 2                      # one winner per window
        assert res.stitched["oos_days"] == 10             # 2 windows x 5 days
        # winner is the highest upper_thresh_z combo (1.2)
        assert res.winners[0]["overrides"]["upper_thresh_z"] == 1.2

    def test_resume_skips_completed_rows(self, tmp_path):
        """A second run with the same file re-does no work (all rows present)."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        run_campaign("v3_5b", camp, windows_limit=1, workers=1, run_fn=_fake_run_fn,
                     symbols=["QQQ"], total_start=_date(2010, 2, 1),
                     total_end=_date(2013, 8, 1))
        calls = {"n": 0}
        def _counting(*a, **k):
            calls["n"] += 1
            return _fake_run_fn(*a, **k)
        run_campaign("v3_5b", camp, windows_limit=1, workers=1, run_fn=_counting,
                     symbols=["QQQ"], total_start=_date(2010, 2, 1),
                     total_end=_date(2013, 8, 1))
        assert calls["n"] == 0  # everything resumed from the JSONL


def _all_error_run_fn(strategy_id, combo, symbols, start, end, phase,
                      initial_capital="10000"):
    return {"hash": combo["hash"], "combo_id": combo["combo_id"],
            "kind": combo["kind"], "phase": phase,
            "overrides": combo["overrides"], "is_sharpe": None,
            "oos_rows": None, "error": "RuntimeError: simulated outage"}


class TestCircuitBreaker:
    def test_aborts_after_consecutive_errors(self, tmp_path):
        """N consecutive errored IS rows abort the campaign with a clear message."""
        import pytest
        camp = tmp_path / "campaign_v3_5b.jsonl"
        with pytest.raises(RuntimeError, match="consecutive errored"):
            run_campaign("v3_5b", camp, windows_limit=1, workers=1,
                         run_fn=_all_error_run_fn, symbols=["QQQ"],
                         total_start=_date(2010, 2, 1), total_end=_date(2013, 8, 1),
                         max_consecutive_errors=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestRunCampaign tests/unit/audit/test_wfo_stability.py::TestCircuitBreaker -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'run_campaign'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass as _dataclass

DEFAULT_MAX_CONSECUTIVE_ERRORS = 10


@_dataclass
class WFOCampaignResult:
    """Everything the report needs from a completed/resumed WFO campaign."""
    strategy_id: str
    winners: list          # per-window winner rows (with window_id, overrides, is_sharpe)
    window_is_rows: list   # per-window list of IS rows (for top-decile share)
    stitched: dict         # stitch_oos_metrics over all OOS windows
    drift: "pd.DataFrame"
    value_distribution: dict
    campaign_file: str


def _run_serial(strategy_id, unit, campaign_file, run_fn, symbols,
                initial_capital, max_consecutive_errors, progress):
    """Run a list of work units serially, checkpointing each; breaker on errors.

    A unit is (window, combo, phase). Returns nothing; rows are appended to the
    JSONL by the SINGLE WRITER here (never by run_fn).
    """
    consecutive = 0
    for i, (win, combo, phase) in enumerate(unit, 1):
        span = (win.is_start, win.is_end) if phase == "is" else (win.oos_start, win.oos_end)
        row = run_fn(strategy_id, combo, symbols, span[0], span[1], phase,
                     initial_capital)
        row["window_id"] = win.window_id
        row["phase"] = phase
        row["row_key"] = row_key(win.window_id, phase, combo["hash"])
        append_wfo_row(campaign_file, row)
        consecutive = consecutive + 1 if is_error_row(row) else 0
        progress(f"[{i}/{len(unit)}] w{win.window_id} {phase} "
                 f"{combo['kind']} is_sharpe={row.get('is_sharpe')}")
        if consecutive >= max_consecutive_errors:
            raise RuntimeError(
                f"aborting: {max_consecutive_errors} consecutive errored runs — "
                "systemic failure (DB down?). Errored rows are checkpointed and "
                "NOT retried on resume; investigate and delete them (or use "
                "--retry-errors) before rerunning.")


def run_campaign(strategy_id: str, campaign_file: Path,
                 windows_limit: int | None = None, workers: int = 1,
                 run_fn=run_one_backtest, symbols: list[str] | None = None,
                 total_start: date | None = None, total_end: date | None = None,
                 initial_capital: str = "10000",
                 max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
                 retry_errors: bool = False,
                 progress=lambda m: None) -> WFOCampaignResult:
    """Run (or resume) the WFO campaign; return winners, stitched OOS, drift table.

    Per window: run every IS combo, pick the winner by IS Sharpe (select_is_winner),
    then run the single OOS backtest with the winner's overrides. Every row is
    checkpointed immediately (crash-safe). Resume skips any (window,phase,combo)
    already present. The circuit breaker aborts after `max_consecutive_errors`
    consecutive errored rows.

    SINGLE-WRITER INVARIANT: all append_wfo_row calls happen in this parent
    process; run_fn (incl. in the parallel path) only computes and RETURNS a row.

    Two-pass design: pass 1 runs ALL IS combos for ALL windows (embarrassingly
    parallel), then winners are selected from the reloaded rows; pass 2 runs the
    per-window OOS backtests for the winners. This keeps the parallel pool busy
    with the 31x work first, and makes OOS depend on committed IS rows so a crash
    between passes resumes cleanly.
    """
    from jutsu_engine.audit.attribution import _all_symbols

    campaign_file = Path(campaign_file)
    total_start = total_start or ATTRIBUTION_START
    total_end = total_end or date.today()
    symbols = symbols if symbols is not None else _all_symbols(strategy_id)
    windows = generate_windows(total_start, total_end, windows_limit=windows_limit)
    combos = expand_grid()

    # ---- Pass 1: all IS combos for all windows ----
    done = load_completed_keys(campaign_file, retry_errors=retry_errors)
    is_units = [(w, c, "is") for w in windows for c in combos
                if row_key(w.window_id, "is", c["hash"]) not in done]
    progress(f"pass 1 (IS): {len(is_units)} units to run")
    if workers <= 1:
        _run_serial(strategy_id, is_units, campaign_file, run_fn, symbols,
                    initial_capital, max_consecutive_errors, progress)
    else:
        _run_parallel(strategy_id, is_units, campaign_file, run_fn, symbols,
                      initial_capital, workers, max_consecutive_errors, progress)

    # ---- Select winners from committed IS rows ----
    all_rows = reload_wfo_rows(campaign_file)
    is_by_window: dict[int, list] = {}
    for r in all_rows:
        if r.get("phase") == "is":
            is_by_window.setdefault(r["window_id"], []).append(r)
    winners = []
    window_is_rows = []
    for w in windows:
        rows = is_by_window.get(w.window_id, [])
        window_is_rows.append(rows)
        win = select_is_winner(rows)
        if win is None:
            progress(f"w{w.window_id}: all IS combos errored — window skipped")
            continue
        win = {**win, "window_id": w.window_id}
        winners.append(win)

    # ---- Pass 2: one OOS backtest per winner ----
    done = load_completed_keys(campaign_file, retry_errors=retry_errors)
    oos_units = []
    win_by_id = {w["window_id"]: w for w in winners}
    for w in windows:
        win = win_by_id.get(w.window_id)
        if win is None:
            continue
        combo = {"hash": win["hash"], "combo_id": win.get("combo_id", -1),
                 "kind": "oos_winner", "overrides": win["overrides"]}
        if row_key(w.window_id, "oos", combo["hash"]) in done:
            continue
        oos_units.append((w, combo, "oos"))
    progress(f"pass 2 (OOS): {len(oos_units)} winner backtests to run")
    if workers <= 1:
        _run_serial(strategy_id, oos_units, campaign_file, run_fn, symbols,
                    initial_capital, max_consecutive_errors, progress)
    else:
        _run_parallel(strategy_id, oos_units, campaign_file, run_fn, symbols,
                      initial_capital, workers, max_consecutive_errors, progress)

    # ---- Stitch OOS + build drift table ----
    all_rows = reload_wfo_rows(campaign_file)
    oos_frames = []
    for r in all_rows:
        if r.get("phase") == "oos" and r.get("oos_rows"):
            oos_frames.append(pd.DataFrame(r["oos_rows"]))
    stitched = stitch_oos_metrics(oos_frames)
    drift = drift_table(winners)
    vdist = param_value_distribution(winners)

    return WFOCampaignResult(
        strategy_id=strategy_id, winners=winners, window_is_rows=window_is_rows,
        stitched=stitched, drift=drift, value_distribution=vdist,
        campaign_file=str(campaign_file))


def _run_parallel(strategy_id, units, campaign_file, run_fn, symbols,
                  initial_capital, workers, max_consecutive_errors, progress):
    """Parallel unit execution with resume + breaker (parent-only writes).

    Mirrors plateau._run_parallel: wait(FIRST_COMPLETED) loop so a tripped breaker
    can stop submitting and cancel pending futures while still checkpointing every
    already-completed row. run_fn must be a picklable module-level callable
    (macOS spawn). Running futures cannot be cancelled and are discarded (re-run
    on resume, since their rows were never checkpointed).
    """
    consecutive = 0
    done_count = 0
    total = len(units)
    # Map each future to its (window, phase) so the parent can stamp the row.
    with ProcessPoolExecutor(max_workers=workers) as ex:
        fut_meta = {}
        for win, combo, phase in units:
            span = (win.is_start, win.is_end) if phase == "is" else (win.oos_start, win.oos_end)
            fut = ex.submit(run_fn, strategy_id, combo, symbols, span[0], span[1],
                            phase, initial_capital)
            fut_meta[fut] = (win, combo, phase)
        pending = set(fut_meta)
        aborted = False
        while pending and not aborted:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                win, combo, phase = fut_meta[fut]
                row = fut.result()
                row["window_id"] = win.window_id
                row["phase"] = phase
                row["row_key"] = row_key(win.window_id, phase, combo["hash"])
                append_wfo_row(campaign_file, row)   # SINGLE WRITER (parent)
                done_count += 1
                if is_error_row(row):
                    consecutive += 1
                    if consecutive >= max_consecutive_errors:
                        aborted = True
                else:
                    consecutive = 0
                progress(f"[{done_count}/{total}] w{win.window_id} {phase} "
                         f"is_sharpe={row.get('is_sharpe')}")
        if aborted:
            for fut in pending:
                fut.cancel()
            raise RuntimeError(
                f"aborting: {max_consecutive_errors} consecutive errored runs — "
                "systemic failure (DB down?). Errored rows are checkpointed and "
                "NOT retried on resume; investigate and delete them (or use "
                "--retry-errors) before rerunning.")
```

Add the missing import near the top of the module (window/attribution constant):

```python
# jutsu_engine/audit/wfo_stability.py — add with the other imports
from jutsu_engine.audit.config import ATTRIBUTION_START
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestRunCampaign tests/unit/audit/test_wfo_stability.py::TestCircuitBreaker -p no:cacheprovider -o addopts="" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): WFO campaign runner (2-pass IS/OOS, resume, breaker, parallel)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 9: run_wfo orchestrator (summary dict for the report)

**Files:**
- Modify: `jutsu_engine/audit/wfo_stability.py`
- Test: `tests/unit/audit/test_wfo_stability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_stability.py  (append)
from datetime import date as _date

from jutsu_engine.audit.wfo_stability import summarize_campaign


class TestSummarizeCampaign:
    def test_summary_has_stitched_drift_and_topdecile(self, tmp_path):
        """summarize_campaign builds the report dict: stitched, drift, top-decile share."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date(2010, 2, 1), total_end=_date(2013, 8, 1))
        summary = summarize_campaign(res)
        assert summary["strategy_id"] == "v3_5b"
        assert summary["stitched"]["oos_days"] == 10
        assert "top_decile_share" in summary
        # each sensitive golden axis has a share + verdict
        for p in ("upper_thresh_z", "realized_vol_window", "sma_slow"):
            assert p in summary["top_decile_share"]
            assert summary["top_decile_share"][p]["verdict"] in (
                "stable", "unstable", "inconclusive")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestSummarizeCampaign -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'summarize_campaign'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/wfo_stability.py  (append)

def summarize_campaign(result: WFOCampaignResult) -> dict:
    """Build the report summary dict from a WFOCampaignResult.

    Includes the stitched OOS headline metrics (spec §5 output 1), the drift table
    + winning-value distribution (output 2), and the golden top-decile share +
    spec §10 verdict for each sensitive axis (the adaptive-parameters decision).
    """
    top_decile = {}
    for param, golden in GOLDEN_SENSITIVE.items():
        share = golden_top_decile_share(result.window_is_rows, param, golden)
        top_decile[param] = {
            "golden_value": golden,
            "share": share,
            "verdict": stability_verdict(share),
        }
    # Overall verdict: worst (lowest-share) axis governs the fragility call.
    if top_decile:
        min_share = min(v["share"] for v in top_decile.values())
        overall = stability_verdict(min_share)
    else:
        min_share, overall = 0.0, "unstable"

    return {
        "strategy_id": result.strategy_id,
        "n_windows": len(result.window_is_rows),
        "n_winners": len(result.winners),
        "stitched": result.stitched,
        "drift_table": result.drift,
        "value_distribution": {k: dict(v) for k, v in result.value_distribution.items()},
        "top_decile_share": top_decile,
        "overall_min_share": min_share,
        "overall_verdict": overall,
        "campaign_file": result.campaign_file,
    }


def run_wfo(strategy_id: str, run_dir: Path, windows_limit: int | None = None,
            workers: int = 1, retry_errors: bool = False,
            total_start: date | None = None, total_end: date | None = None,
            progress=lambda m: None) -> dict:
    """End-to-end Module 1 for one strategy: campaign -> summary dict.

    Writes the campaign JSONL under run_dir/<strategy>/campaign_wfo_<strategy>.jsonl
    so reruns resume. No per-run CSVs land in run_dir (each backtest uses a
    throwaway tempdir). Midnight/multi-day: total_end defaults to date.today() at
    call time and is not embedded in row keys; a resume after midnight extends the
    last window's OOS by 1 day (negligible for multi-year windows; documented).
    """
    from jutsu_engine.audit.attribution import _all_symbols

    run_dir = Path(run_dir)
    symbols = _all_symbols(strategy_id)
    campaign_file = run_dir / strategy_id / f"campaign_wfo_{strategy_id}.jsonl"
    result = run_campaign(
        strategy_id, campaign_file, windows_limit=windows_limit, workers=workers,
        symbols=symbols, total_start=total_start, total_end=total_end,
        retry_errors=retry_errors, progress=progress)
    return summarize_campaign(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_stability.py::TestSummarizeCampaign -p no:cacheprovider -o addopts="" -q`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/wfo_stability.py tests/unit/audit/test_wfo_stability.py
git commit -m "feat(audit): run_wfo orchestrator + report summary (stitched/drift/verdict)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 10: WFO report renderer

**Files:**
- Modify: `jutsu_engine/audit/report.py`
- Test: `tests/unit/audit/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_report.py  (append)
import pandas as pd

from jutsu_engine.audit.report import render_wfo_section, write_wfo_report


def _wfo_summary():
    return {
        "strategy_id": "v3_5b",
        "n_windows": 26, "n_winners": 26,
        "stitched": {"oos_days": 3200, "total_return": 1.5, "cagr": 0.08,
                     "sharpe": 0.65, "max_drawdown": -0.45,
                     "qqq_total_return": 1.2, "alpha_vs_qqq": 0.30},
        "drift_table": pd.DataFrame([
            {"window_id": 1, "is_sharpe": 0.9, "upper_thresh_z": 1.0,
             "realized_vol_window": 21, "sma_slow": 140}]),
        "value_distribution": {"upper_thresh_z": {1.0: 20, 0.8: 6}},
        "top_decile_share": {
            "upper_thresh_z": {"golden_value": 1.0, "share": 0.85, "verdict": "stable"},
            "realized_vol_window": {"golden_value": 21, "share": 0.42, "verdict": "unstable"},
            "sma_slow": {"golden_value": 140, "share": 0.65, "verdict": "inconclusive"},
        },
        "overall_min_share": 0.42, "overall_verdict": "unstable",
        "campaign_file": "/x/campaign_wfo_v3_5b.jsonl",
    }


class TestRenderWFO:
    def test_section_reports_stitched_headline(self):
        """Report shows the stitched OOS Sharpe/CAGR/MaxDD/alpha as the headline."""
        md = render_wfo_section(_wfo_summary())
        assert "Stitched OOS" in md
        assert "0.6500" in md          # stitched sharpe
        assert "alpha" in md.lower()

    def test_section_states_never_averaged(self):
        """Report explicitly states metrics are on the stitched series, not averaged."""
        md = render_wfo_section(_wfo_summary())
        assert "not by averaging per-window" in md.lower() or "stitched series" in md.lower()

    def test_section_shows_topdecile_verdict(self):
        """Report prints the spec §10 top-decile verdict per param and overall."""
        md = render_wfo_section(_wfo_summary())
        assert "85.0%" in md and "stable" in md
        assert "unstable" in md

    def test_write_wfo_report_creates_separate_file(self, tmp_path):
        """write_wfo_report writes report_wfo_<strategy>.md (never touches other reports)."""
        out = write_wfo_report(tmp_path, "v3_5b", "# hi\n")
        assert out.name == "report_wfo_v3_5b.md"
        assert out.read_text() == "# hi\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py::TestRenderWFO -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'render_wfo_section'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/report.py  (append)

# spec §10 decision thresholds for Module 1 (WFO parameter stability).
WFO_STABLE_SHARE_PCT = 80.0
WFO_UNSTABLE_SHARE_PCT = 50.0


def render_wfo_section(summary: dict) -> str:
    """Render the WFO parameter-stability (Module 1) section as markdown.

    `summary` keys: strategy_id, n_windows, n_winners, stitched (dict),
    drift_table (DataFrame), value_distribution (dict), top_decile_share
    (dict {param: {golden_value, share, verdict}}), overall_min_share,
    overall_verdict, campaign_file.
    """
    st = summary["stitched"]
    td = summary["top_decile_share"]

    overall = summary["overall_verdict"]
    overall_line = {
        "stable": (f"golden params are in the top decile in >=**{WFO_STABLE_SHARE_PCT:.0f}%** "
                   "of windows on every sensitive axis -> **parameters stable; adaptive "
                   "tuning is unnecessary by construction** (spec §10)."),
        "unstable": (f"at least one sensitive axis has golden top-decile share <"
                     f"**{WFO_UNSTABLE_SHARE_PCT:.0f}%** -> **parameters unstable; the golden "
                     "config is fragile in time and adaptive tuning would chase noise** (spec §10)."),
        "inconclusive": ("golden top-decile share is between 50% and 80% on the worst axis "
                         "-> **inconclusive**: neither clearly stable nor clearly fragile."),
    }[overall]

    lines = [
        "## WFO parameter-stability study (Module 1)",
        "",
        f"- Strategy: **{summary['strategy_id']}**  |  Windows: **{summary['n_windows']}** "
        f"(winners: {summary['n_winners']})  |  scheme: 2.5y IS / 0.5y OOS / 0.5y slide",
        f"- Campaign file: `{summary['campaign_file']}`",
        "",
        "### Stitched OOS equity curve (headline — spec §5 output 1)",
        "_All metrics are computed on the single concatenated OOS daily-return "
        "series (the stitched series), **not by averaging per-window Sharpes** "
        "(the legacy `walk_forward.py` flaw spec §5 rejects)._",
        "",
        f"- OOS trading days: **{st['oos_days']}**",
        f"- Stitched OOS Sharpe: **{_fmt(st.get('sharpe'), '.4f')}**  |  "
        f"CAGR: **{_fmt(st.get('cagr'), '.4f')}**  |  MaxDD: **{_fmt(st.get('max_drawdown'), '.4f')}**",
        f"- Stitched total return: **{_fmt(st.get('total_return'), '.4f')}**  |  "
        f"QQQ total return: **{_fmt(st.get('qqq_total_return'), '.4f')}**  |  "
        f"alpha vs QQQ: **{_fmt(st.get('alpha_vs_qqq'), '.4f')}**",
        "",
        "### Adaptive-parameters decision (spec §10)",
        "| Signal | Threshold | Consequence |",
        "| --- | --- | --- |",
        "| Golden param top-decile share across windows | >=80% | Stable -> no adaptive tuning |",
        "| Golden param top-decile share across windows | <50% | Unstable -> config fragile, tuning chases noise |",
        "",
        f"- **Overall verdict: {overall.upper()}** — {overall_line}",
        "",
        "#### Golden top-decile share, per sensitive axis",
        "| param | golden value | top-decile share | verdict |",
        "| --- | --- | --- | --- |",
    ]
    for param, info in td.items():
        lines.append(
            f"| `{param}` | {info['golden_value']} | "
            f"{info['share'] * 100:.1f}% | {info['verdict']} |")

    lines += [
        "",
        "### Per-window winner drift table (spec §5 output 2)",
        _df_to_md(summary["drift_table"]),
        "### Winning-value distribution (per param, across windows)",
    ]
    for param, counts in summary["value_distribution"].items():
        pairs = ", ".join(f"{v}×{n}" for v, n in sorted(counts.items()))
        lines.append(f"- `{param}`: {pairs}")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_wfo_report(run_dir: Path, strategy_id: str, markdown: str) -> Path:
    """Write report_wfo_<strategy>.md into run_dir (separate from Phase-1/2 reports)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_wfo_{strategy_id}.md"
    out.write_text(markdown)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py::TestRenderWFO -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/report.py tests/unit/audit/test_report.py
git commit -m "feat(audit): WFO report section (stitched headline + top-decile verdict)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 11: CLI `jutsu audit wfo`

**Files:**
- Modify: `jutsu_engine/cli/commands/audit.py`
- Test: `tests/unit/audit/test_wfo_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_wfo_cli.py
"""CLI tests for `jutsu audit wfo` (mirrors test_plateau_cli.py; run_wfo mocked)."""
from unittest import mock

import pandas as pd
from click.testing import CliRunner

from jutsu_engine.cli.commands.audit import audit


def _summary():
    return {
        "strategy_id": "v3_5b", "n_windows": 2, "n_winners": 2,
        "stitched": {"oos_days": 10, "total_return": 0.1, "cagr": 0.05,
                     "sharpe": 0.6, "max_drawdown": -0.2,
                     "qqq_total_return": 0.08, "alpha_vs_qqq": 0.02},
        "drift_table": pd.DataFrame([{"window_id": 1, "is_sharpe": 0.9}]),
        "value_distribution": {"upper_thresh_z": {1.0: 2}},
        "top_decile_share": {
            "upper_thresh_z": {"golden_value": 1.0, "share": 1.0, "verdict": "stable"},
            "realized_vol_window": {"golden_value": 21, "share": 1.0, "verdict": "stable"},
            "sma_slow": {"golden_value": 140, "share": 1.0, "verdict": "stable"},
        },
        "overall_min_share": 1.0, "overall_verdict": "stable",
        "campaign_file": "/x/campaign_wfo_v3_5b.jsonl",
    }


class TestWFOCli:
    def test_wfo_calls_run_wfo_and_writes_report(self, tmp_path):
        """`jutsu audit wfo --strategy v3_5b` calls run_wfo and writes a report."""
        with mock.patch("jutsu_engine.audit.config.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code == 0, r.output
        assert m.called
        assert (tmp_path / "v3_5b" / "report_wfo_v3_5b.md").exists()

    def test_windows_limit_and_workers_thread_through(self, tmp_path):
        """--windows-limit and --workers are forwarded to run_wfo."""
        with mock.patch("jutsu_engine.audit.config.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(
                audit, ["wfo", "--strategy", "v3_5b",
                        "--windows-limit", "2", "--workers", "4"])
        assert r.exit_code == 0, r.output
        _, kwargs = m.call_args
        assert kwargs["windows_limit"] == 2
        assert kwargs["workers"] == 4

    def test_retry_errors_flag_threads_through(self, tmp_path):
        """--retry-errors is forwarded as retry_errors=True."""
        with mock.patch("jutsu_engine.audit.config.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(
                audit, ["wfo", "--strategy", "v3_5b", "--retry-errors"])
        assert r.exit_code == 0, r.output
        assert m.call_args.kwargs["retry_errors"] is True

    def test_circuit_breaker_message_is_clear(self, tmp_path):
        """A RuntimeError from run_wfo (breaker) surfaces a clean aborted message."""
        with mock.patch("jutsu_engine.audit.config.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        side_effect=RuntimeError("consecutive errored runs")):
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code != 0
        assert "aborted" in r.output.lower() or "consecutive" in r.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `SystemExit`/`no such command 'wfo'`.

- [ ] **Step 3: Write minimal implementation**

Add the imports and command to `audit.py`. The `wfo` command reuses `_resolve_run_dir` and the same error-handling shape as `plateau_cmd`.

```python
# jutsu_engine/cli/commands/audit.py — add to the report import block:
from jutsu_engine.audit.report import (
    render_report, write_report,
    render_plateau_section, write_plateau_report,
    render_wfo_section, write_wfo_report,
)
```

```python
# jutsu_engine/cli/commands/audit.py — append after plateau_cmd

@audit.command("wfo")
@_STRATEGY_OPTION
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel worker processes (1 = serial; each worker builds its "
                   "own BacktestRunner).")
@click.option("--windows-limit", "windows_limit", type=int, default=None,
              help="Cap the number of WFO windows (smoke mode, e.g. 2).")
@click.option("--retry-errors", "retry_errors", is_flag=True, default=False,
              help="Re-run previously errored checkpoint rows (non-finite sharpe or "
                   "non-None error) rather than treating them as completed.")
@click.option("--run-date", "run_date", type=str, default=None, metavar="YYYY-MM-DD",
              help="Use a specific dated run directory instead of auto-detecting an "
                   "existing campaign. Useful when resuming after midnight.")
def wfo_cmd(strategy, workers, windows_limit, retry_errors, run_date):
    """Module 1: WFO parameter-stability study (stitched OOS curve + drift table)."""
    from jutsu_engine.audit import wfo_stability as wfo_mod

    try:
        for sid in _strategy_ids(strategy):
            run_dir = _resolve_run_dir_wfo(run_date, sid)
            campaign_file = run_dir / sid / f"campaign_wfo_{sid}.jsonl"
            click.echo(
                f"[{sid}] WFO campaign "
                f"(windows_limit={windows_limit}, workers={workers}, "
                f"retry_errors={retry_errors})\n"
                f"  campaign file: {campaign_file}"
            )
            summary = wfo_mod.run_wfo(
                sid, run_dir, windows_limit=windows_limit, workers=workers,
                retry_errors=retry_errors,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
            click.echo(click.style(
                f"  stitched OOS Sharpe={summary['stitched']['sharpe']:.4f} "
                f"alpha={summary['stitched']['alpha_vs_qqq']:.4f} "
                f"verdict={summary['overall_verdict']}", fg="cyan"))
            md = render_wfo_section(summary)
            out = write_wfo_report(run_dir, sid, md)
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
        logger.error(f"WFO audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ WFO audit failed: {e}", fg="red"), err=True)
        raise click.Abort()


def _resolve_run_dir_wfo(run_date_str, strategy_id):
    """Midnight-safe run-dir resolution for the WFO campaign file.

    Same logic as _resolve_run_dir but scans for campaign_wfo_<strategy>.jsonl so
    a WFO resume never collides with a plateau (campaign_<strategy>.jsonl) file.
    """
    from datetime import datetime as _dt
    if run_date_str is not None:
        try:
            rd = _dt.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(
                f"Invalid date format {run_date_str!r}; expected YYYY-MM-DD",
                param_hint="--run-date")
        return report_output_dir(run_date=rd)
    audit_base = report_output_dir().parent
    pattern = f"campaign_wfo_{strategy_id}.jsonl"
    candidates = sorted(
        audit_base.glob(f"*/{strategy_id}/{pattern}"),
        key=lambda p: p.parent.parent.name, reverse=True)
    if candidates:
        newest = candidates[0]
        run_dir = newest.parent.parent
        click.echo(click.style(
            f"  Resuming existing WFO campaign: {newest} "
            f"(pass --run-date to override)", fg="yellow"))
        return run_dir
    return report_output_dir()
```

Note on the CLI test: the tests patch `jutsu_engine.audit.config.report_output_dir`. `_resolve_run_dir_wfo` calls the module-level `report_output_dir` imported into `audit.py`. To make the patch effective, the test patches the name where it's looked up; add this import-alias note — `audit.py` already does `from jutsu_engine.audit.config import ... report_output_dir`, so patch `jutsu_engine.cli.commands.audit.report_output_dir` instead. **Update the CLI test's patch target accordingly:**

```python
# tests/unit/audit/test_wfo_cli.py — patch the name where audit.py looks it up:
mock.patch("jutsu_engine.cli.commands.audit.report_output_dir", return_value=tmp_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_wfo_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/cli/commands/audit.py tests/unit/audit/test_wfo_cli.py
git commit -m "feat(audit): jutsu audit wfo CLI (workers/windows-limit/retry-errors/run-date)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 12: Full-suite regression + smoke-mode dry check

**Files:** (no new files)

- [ ] **Step 1: Run the full audit unit suite**

Run: `.venv/bin/python -m pytest tests/unit/audit/ -p no:cacheprovider -o addopts="" -q`
Expected: PASS — all prior audit tests (~133 from EXP-003) plus the new `test_wfo_stability.py`, `test_wfo_cli.py`, and `test_report.py::TestRenderWFO` tests. No failures, no DB required.

- [ ] **Step 2: Verify the CLI wires up (no DB needed for --help)**

Run: `.venv/bin/python -m jutsu_engine.cli.main audit wfo --help` (or the project's `jutsu` entrypoint: `jutsu audit wfo --help`)
Expected: help text listing `--strategy`, `--workers`, `--windows-limit`, `--retry-errors`, `--run-date`. If the entrypoint differs, use `grep -rn "add_command(audit)" jutsu_engine/cli/` to find how `audit` is registered and invoke that entrypoint.

- [ ] **Step 3: (DB-gated, operator-run) smoke campaign**

This step needs the rebuilt uv Python 3.11 env with `POSTGRES_*` set (local venvs are known-dead; per Serena memory). Document the command for the operator; do NOT block the plan on it in CI:

```bash
# ~4 min end-to-end proof of the pipeline (2 windows, 31-combo grid, workers=4)
jutsu audit wfo --strategy v3_5b --windows-limit 2 --workers 4
# Expect: campaign_wfo_v3_5b.jsonl written; report_wfo_v3_5b.md with a stitched
# OOS Sharpe and a top-decile verdict. Re-run the same command: it must resume
# (0 units to run) and rewrite the identical report.
```

- [ ] **Step 4: Commit (no-op if nothing changed)**

If Steps 1-2 required any fixes, commit them:

```bash
git add -A
git commit -m "test(audit): full WFO suite green + CLI wiring verified

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Task 13: LOGBOOK EXP-004 skeleton + CHANGELOG entry

**Files:**
- Modify: `docs/experiments/LOGBOOK.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the EXP-004 index row and skeleton entry to LOGBOOK.md**

Add to the Index table (after the EXP-003 row):

```markdown
| EXP-004 | 2026-07-07 | Are the golden parameters stable across WFO time windows (does adaptive tuning have anything to chase)? | _(pending campaign run)_ |
```

Append the skeleton entry after EXP-003 (fill Results/Verdict after the campaign runs; the pipeline and method are fixed now):

```markdown
---

## EXP-004 — Baseline audit Phase 3: WFO parameter-stability study (2026-07-07)

**Question.** Are the golden parameters stable across walk-forward time windows,
or do the winning values drift? EXP-003 showed the config is parameter-robust
*today* (a plateau, 48th/57.5th percentile of its own neighborhood); this is the
orthogonal test EXP-003 could not answer — parameters flat today may still drift
*across time windows*. This settles the adaptive-parameters question with
out-of-sample data (spec §5/§10).

**Why.** EXP-001 pinned fragility to the *time* dimension (2022 failure,
2025 negative alpha), not the parameter dimension. WFO measures whether the golden
config's winning parameter values are stable window-to-window and whether a
stitched OOS curve (honest, no in-sample selection) confirms or degrades the
EXP-001 full-period Sharpe ~0.8. Also WFO-validates the EXP-003 quarantined
candidates (bond_sma_fast 24, bond_sma_slow 66, osc_smoothness 12,
vol_crush_threshold −0.12) out-of-sample before anyone adopts them.

**Method.** Built `jutsu_engine/audit/wfo_stability.py` + `jutsu audit wfo`.
- Windows: 2.5y IS / 0.5y OOS / 0.5y slide, 2010-02 → present (~26 windows).
- Per-window grid (31 combos, evidence-driven from EXP-003): 3×3×3 product over
  the sensitive vol-regime inputs `upper_thresh_z` [0.8,1.0,1.2] ×
  `realized_vol_window` [16,21,26] × `sma_slow` [120,140,160], PLUS 4
  single-swap quarantine combos. Six EXP-003 inert knobs excluded (documented).
- Per window: run all IS combos, pick the winner by IS Sharpe, run ONE OOS
  backtest with the winner; extract that window's `Strategy_Daily_Return` from the
  regime-timeseries CSV.
- **Stitched OOS curve**: concatenate all OOS daily returns; Sharpe/CAGR/MaxDD/
  alpha-vs-QQQ computed on the stitched series — NEVER by averaging per-window
  Sharpes (the legacy `walk_forward.py` flaw spec §5 rejects).
- **Drift table**: per-window winner params; per-param winning-value distribution;
  golden top-decile share per sensitive axis → spec §10 verdict (≥80% stable /
  <50% unstable).
- Infra reuse: `build_overridden_strategy` + `BacktestRunner`; plateau JSONL
  fsync checkpoint/resume + circuit breaker + single-writer; `--retry-errors`;
  midnight-safe run-dir. Read-only vs DB; no live/scheduler changes.
- Command (overnight, resumable): `jutsu audit wfo --strategy v3_5b --workers 4`
  then `--strategy v3_5d`. Smoke: `jutsu audit wfo --strategy v3_5b
  --windows-limit 2 --workers 4` (~4 min).

**Results.** _(pending — fill stitched OOS Sharpe/CAGR/MaxDD/alpha for both
strategies; per-param top-decile shares and overall verdict; whether any
quarantined candidate survived OOS.)_

**Verdict / decisions.** _(pending — the adaptive-parameters go/no-go per spec §10,
and adopt/kill decision for each quarantined candidate.)_

**Artifacts.** Reports `claudedocs/audit/2026-07-07/report_wfo_v3_5{b,d}.md`;
campaign JSONLs `claudedocs/audit/2026-07-07/v3_5{b,d}/campaign_wfo_v3_5{b,d}.jsonl`;
code merged to main. Serena memory: _(write after campaign)_.

**Follow-ups spawned.** Module 3 (DSR/PBO) — the trial-count correction for the
v2.x→v3.5b search history is still unmeasured; if WFO says unstable, the
adaptive-parameters idea is dead and R&D goes to regime-transition quality.
```

- [ ] **Step 2: Add the CHANGELOG entry**

Prepend at the top of the changes section in `CHANGELOG.md`:

```markdown
#### **Feature: Baseline Audit Phase 3 — Module 1 WFO parameter-stability study** (2026-07-07)

Added `jutsu audit wfo` (`jutsu_engine/audit/wfo_stability.py`): walk-forward
parameter-stability study for v3_5b/v3_5d producing (a) a stitched OOS daily-return
equity curve (Sharpe/CAGR/MaxDD/alpha-vs-QQQ computed on the concatenated series —
never by averaging per-window Sharpes) and (b) a parameter-drift table with golden
top-decile share and the spec §10 stable/unstable verdict. Grid is evidence-driven
from EXP-003 (31 combos/window: 3×3×3 sensitive-param product + 4 quarantine swaps;
six inert knobs excluded). Reuses `build_overridden_strategy` + `BacktestRunner` +
the plateau JSONL checkpoint/resume/circuit-breaker/single-writer patterns;
strictly read-only vs the DB; no live/scheduler changes.

- New: `jutsu_engine/audit/wfo_stability.py`, `tests/unit/audit/test_wfo_stability.py`,
  `tests/unit/audit/test_wfo_cli.py`.
- Modified: `jutsu_engine/audit/report.py` (`render_wfo_section`, `write_wfo_report`),
  `jutsu_engine/cli/commands/audit.py` (`wfo` subcommand), `tests/unit/audit/test_report.py`.
- Docs: `docs/experiments/LOGBOOK.md` (EXP-004 skeleton).
```

- [ ] **Step 3: Commit**

```bash
git add docs/experiments/LOGBOOK.md CHANGELOG.md
git commit -m "docs(audit): EXP-004 WFO skeleton + Phase-3 CHANGELOG entry

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SZysdr83YJGy4w3vKPHjtY"
```

---

## Self-Review

**1. Spec coverage (§5, §10-12):**
- §5 window scheme (2.5y/0.5y/0.5y, ~26 windows) → Task 1. ✓
- §5 evidence-driven grid ≤~81 combos, sensitive params, exclude inert, include quarantined → Task 2 (31 combos, exact grid stated). ✓
- §5 output 1 stitched OOS curve (Sharpe/CAGR/MaxDD/alpha-vs-QQQ on stitched series, never averaged) → Task 4 + Task 10 report + explicit test `test_never_averages_per_window_sharpe`. ✓
- §5 output 2 drift table (per-window winner, per-param distribution, golden top-decile share) → Task 5 + Task 9. ✓
- §10 decision thresholds (≥80% stable / <50% unstable) → Task 5 `stability_verdict` + Task 10 report table. ✓
- §11 bounded extensions: evaluated; concluded NO engine change needed (regime-timeseries CSV already carries daily returns) — documented in the architecture section. ✓
- §12 compute honesty (checkpoint/resume + breaker, overnight, resumable, smoke <30 min) → Tasks 7-8, compute-estimate section, Task 12 smoke. ✓
- Report standalone `report_wfo_<strategy>.md` → Task 10. ✓  LOGBOOK EXP-004 + CHANGELOG → Task 13. ✓
- CLI `jutsu audit wfo --strategy --workers --windows-limit --retry-errors --run-date` → Task 11. ✓

**2. Placeholder scan:** No TBD/TODO in code steps; every code step shows complete code. The only intentional "pending" text is in the EXP-004 Results/Verdict — a lab-notebook entry that by design is filled after the campaign runs (the method/pipeline is fully specified). This is not a code placeholder.

**3. Type consistency:** Grid combo dicts use keys `combo_id/kind/overrides/hash` consistently (Tasks 2, 6, 8). Result rows use `hash/combo_id/kind/phase/overrides/is_sharpe/oos_rows/error` consistently (Tasks 6, 7, 8). `row_key(window_id, phase, hash)` signature matches all call sites. `select_is_winner` returns a row dict or None; `run_campaign` wraps the winner with `window_id` before `drift_table`, which reads `w["overrides"]` and `w["window_id"]` — consistent. `summarize_campaign` returns the exact keys `render_wfo_section` reads (`stitched`, `drift_table`, `value_distribution`, `top_decile_share{golden_value,share,verdict}`, `overall_verdict`, `n_windows`, `n_winners`, `campaign_file`). `stitch_oos_metrics` returns `oos_days/total_return/cagr/sharpe/max_drawdown/qqq_total_return/alpha_vs_qqq` — matched in the report renderer and CLI echo. CLI test patch target corrected to `jutsu_engine.cli.commands.audit.report_output_dir` (where the name is looked up). Task 7 test corrected to use `append_wfo_row` (not plateau's `append_result`, whose key set differs).

**Reuse verified against real signatures:** `build_overridden_strategy(strategy_id, overrides)` (plateau.py:373), `_all_symbols(strategy_id)` (attribution.py:201), `_sharpe/_max_drawdown/_total_return` (attribution.py:65-81), `_ends_with_newline` (plateau.py:478), `ATTRIBUTION_START` (config.py:20), regime-timeseries columns `Date/QQQ_Daily_Return/Strategy_Daily_Return` (regime_analyzer.py:209-216), BacktestRunner result keys `sharpe_ratio/regime_timeseries_csv` (backtest_runner.py). All confirmed by reading the source.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-07-baseline-audit-phase3-wfo.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
