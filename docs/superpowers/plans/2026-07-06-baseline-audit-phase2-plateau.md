# Baseline Audit Phase 2 — Parameter Plateau Map (Module 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `jutsu_engine/audit/plateau.py` (Module 2 of the baseline audit): a seeded perturbation-campaign driver plus DB-free analysis functions that measure how much of the golden config's Sharpe survives small parameter perturbations, with a checkpoint/resume campaign runner, optional multiprocessing, a standalone markdown report, and a `jutsu audit plateau` CLI subcommand.

**Architecture:** Pure/seeded functions generate a perturbation set (one-at-a-time ±10%/±20% and N=200 joint uniform samples in a ±15% box) from the live YAML's numeric parameters. A campaign runner runs each sample as a full-period backtest by reusing the Phase-1 bridge (`build_strategy_instance` extended with param overrides + `BacktestRunner`), appends each result as a JSONL row (resume by hash), and writes CSVs to a throwaway per-run tempdir so the report directory stays clean. Pure analysis functions (plateau score, degradation table, cliff list, joint-sample percentile) run over the collected results with no DB. A new `report_plateau_<strategy>.md` embeds the verdict. Everything is strictly READ-ONLY against the DB, mirroring Phase 1.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), click CLI, pandas/numpy, `concurrent.futures.ProcessPoolExecutor`, pytest. Reuses `BacktestRunner`, `LiveStrategyRunner`, `PerformanceAnalyzer` unchanged.

---

## Context the engineer needs before starting

**You are extending a merged Phase-1 audit package.** Read these first — they define every pattern you must follow:
- `jutsu_engine/audit/config.py` — `StrategySpec` registry, `resolve_strategy`, `report_output_dir`, `ATTRIBUTION_START = date(2010, 2, 1)`.
- `jutsu_engine/audit/attribution.py` — `build_strategy_instance(strategy_id)` (the Phase-1 bridge: builds a strategy from the live YAML via `LiveStrategyRunner`), `_all_symbols(strategy_id)`, and `run_attribution` (shows exactly how to configure and run one full-period `BacktestRunner`). **You will replicate `run_attribution`'s config-building and `.run()` call, adding param overrides and a tempdir output.**
- `jutsu_engine/audit/report.py` — `_fmt`, `_df_to_md`, section-renderer + `write_report` conventions.
- `jutsu_engine/cli/commands/audit.py` — the click group + `_dispatch`/`AuditDBUnavailable` graceful-degrade pattern.
- `jutsu_engine/live/strategy_runner.py` — `EXCLUDED_PARAMS = {'name', 'trade_logger'}`, `REQUIRED_PARAMS`, and `_convert_decimal_params` with its exact `decimal_params` set (the float→Decimal convention you must replicate).
- `tests/unit/audit/test_attribution.py` — test style: one-line docstrings on every test method, `pytest.raises(..., match=...)`, DB-free synthetic DataFrames.

**Verified integration facts (do not re-investigate):**
1. **Param-override mechanism.** `build_strategy_instance` uses `LiveStrategyRunner(strategy_class, config_path)` which reads `config['strategy']['parameters']`, drops `EXCLUDED_PARAMS`, converts a fixed set of keys to `Decimal` (`strategy_runner.py:124-137`), and calls `strategy_class(**params); strategy.init()`. The strategy takes all params as `**kwargs` (`Hierarchical_Adaptive_v3_5b.__init__` is a flat keyword signature). To override, you build the same params dict, apply overrides, re-run the float→Decimal conversion, and instantiate directly — replicated minimally in `plateau.py` (Task 5).
2. **`BacktestRunner.run(strategy, output_dir=...)`** writes ALL CSVs (trades, regime timeseries, portfolio, summary) into `output_dir` (`backtest_runner.py:680-833`). So a per-run tempdir fully isolates campaign runs from the report directory — no per-run regime/portfolio CSVs land in `claudedocs/audit/`.
3. **Multiprocessing.** `BacktestRunner.__init__` creates a fresh engine+session per instance (`backtest_runner.py:111-113`); `get_config()` is a per-process singleton that re-reads env in each spawned process; strategy classes hold only instance state. Verdict: **per-worker construction (each worker builds its own `BacktestRunner`+strategy from a params dict) is SAFE.** Caveat: macOS `ProcessPoolExecutor` uses the `spawn` start method, so the worker function and its arguments **must be picklable** — pass plain dicts (params + primitives), never live objects; build the strategy and runner INSIDE the worker. Logs fragment per worker (benign).

**Compute honesty (state this in the report, measure nothing):** one full-period backtest is ~2-3 min. The default campaign is 23 params × 4 OAT steps (≤92 runs after dedup) + 200 joint ≈ ~290 runs → **~10-15h serial**, hence checkpoint+resume and optional `--workers`. The overnight run itself is NOT a plan task (post-merge operational step); the final plan task runs only a 4-backtest SMOKE campaign.

**Constraints (violating any = plan failure):**
- Reuse `BacktestRunner`/`PerformanceAnalyzer`/`LiveStrategyRunner`; **no** changes to live/scheduler code, strategy classes, or existing audit files except the two additive edits called out (CLI subcommand registration in `audit.py`; nothing else in Phase-1 files).
- Audit stays strictly READ-ONLY vs the DB.
- `git add <explicit paths>` only — never `git add -A`/`.`.
- Tests are DB-free: pure functions + fakes only. One-line docstrings on test methods. `pytest.raises(match=...)`.
- **Focused-test command (use this exact form):** `.venv/bin/python -m pytest <path> -p no:cacheprovider -o addopts="" -q`
- Every commit is small and on the current branch `feature/audit-phase2-plateau` (already checked out).

**The exact perturbable parameter list (extracted from `config/strategies/v3_5b.yaml`).** These are the numeric strategy parameters, EXCLUDING symbols/strings, booleans (`allow_treasury`, `use_inverse_hedge`), and execution/infra (`execution_time`). 23 parameters. Type = how the golden value is stored / rounded; `is_decimal` = whether it is in `strategy_runner.py`'s `decimal_params` set:

| # | param | golden (v3_5b) | kind | is_decimal | validity floor |
|---|---|---|---|---|---|
| 1 | measurement_noise | 3000.0 | float | yes | > 0 |
| 2 | process_noise_1 | 0.01 | float | yes | > 0 |
| 3 | process_noise_2 | 0.01 | float | yes | > 0 |
| 4 | osc_smoothness | 15 | int | no | ≥ 2 (period) |
| 5 | strength_smoothness | 15 | int | no | ≥ 2 (period) |
| 6 | T_max | 50.0 | float | yes | > 0 |
| 7 | sma_fast | 40 | int | no | ≥ 5 (window) |
| 8 | sma_slow | 140 | int | no | ≥ 5 (window) |
| 9 | t_norm_bull_thresh | 0.05 | float | yes | keep sign (+) |
| 10 | t_norm_bear_thresh | -0.3 | float | yes | keep sign (−) |
| 11 | realized_vol_window | 21 | int | no | ≥ 5 (window) |
| 12 | vol_baseline_window | 200 | int | no | ≥ 5 (window) |
| 13 | upper_thresh_z | 1.0 | float | yes | > 0 |
| 14 | lower_thresh_z | 0.2 | float | yes | > 0 |
| 15 | vol_crush_threshold | -0.15 | float | yes | keep sign (−) |
| 16 | vol_crush_lookback | 5 | int | no | ≥ 2 (period) |
| 17 | leverage_scalar | 1.0 | float | yes | > 0 |
| 18 | w_PSQ_max | 0.5 | float | yes | > 0 |
| 19 | bond_sma_fast | 20 | int | no | ≥ 5 (window) |
| 20 | bond_sma_slow | 60 | int | no | ≥ 5 (window) |
| 21 | max_bond_weight | 0.4 | float | yes | > 0 |
| 22 | rebalance_threshold | 0.025 | float | yes | > 0 |

Note: that is 22 rows — plus **the golden value list is read from the live YAML at runtime, not hard-coded**, so v3_5d (which may add e.g. `cell1_exit_confirmation_enabled` as a boolean, correctly excluded) produces its own list. The perturbable set = every key in `strategy.parameters` whose value is `int`/`float` and is not a bool, minus the excluded infra keys. `PERTURBABLE_EXCLUDE` (Task 1) names the non-numeric infra keys explicitly; booleans are dropped by an `isinstance(v, bool)` guard (bools are ints in Python, so the guard must come first).

---

## File structure

- **Create:** `jutsu_engine/audit/plateau.py` — perturbation-set generation (pure), campaign runner (checkpoint/resume, optional workers), pure analysis functions.
- **Create:** `tests/unit/audit/test_plateau.py` — DB-free unit tests for the pure pieces.
- **Modify:** `jutsu_engine/audit/report.py` — add `render_plateau_section` + a `write_plateau_report` helper (new file `report_plateau_<strategy>.md`; does not touch the Phase-1 report path).
- **Modify:** `jutsu_engine/cli/commands/audit.py` — add the `plateau` subcommand.
- **Modify:** `CHANGELOG.md` — Phase-2 entry.
- **Modify:** `docs/experiments/LOGBOOK.md` — EXP-003 skeleton + index row.

---

## Task 1: Perturbable-parameter extraction (pure, no DB)

**Files:**
- Create: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/audit/test_plateau.py
import json
import math
from pathlib import Path

import pytest

from jutsu_engine.audit.plateau import (
    PERTURBABLE_EXCLUDE,
    load_golden_params,
    perturbable_params,
)


class TestPerturbableParams:
    def test_perturbable_params_from_golden_dict(self):
        """perturbable_params keeps numeric non-bool keys and drops strings/bools/infra."""
        golden = {
            "sma_fast": 40, "t_norm_bear_thresh": -0.3, "measurement_noise": 3000.0,
            "allow_treasury": True, "use_inverse_hedge": False,
            "execution_time": "15min_after_open", "signal_symbol": "QQQ",
            "leveraged_long_symbol": "TQQQ",
        }
        p = perturbable_params(golden)
        assert set(p) == {"sma_fast", "t_norm_bear_thresh", "measurement_noise"}

    def test_bool_is_not_treated_as_numeric(self):
        """Booleans are excluded even though bool is a subclass of int in Python."""
        assert "allow_treasury" not in perturbable_params({"allow_treasury": True})

    def test_exclude_set_lists_infra_string_keys(self):
        """PERTURBABLE_EXCLUDE names the infra/symbol keys so they never perturb."""
        assert "execution_time" in PERTURBABLE_EXCLUDE
        assert "signal_symbol" in PERTURBABLE_EXCLUDE
        assert "treasury_trend_symbol" in PERTURBABLE_EXCLUDE

    def test_load_golden_params_reads_live_yaml(self):
        """load_golden_params reads the real v3_5b live YAML (no DB); golden spot-checks hold."""
        golden = load_golden_params("v3_5b")
        assert golden["sma_fast"] == 40
        assert golden["sma_slow"] == 140
        assert golden["t_norm_bear_thresh"] == -0.3
        # perturbable set is exactly the 22 numeric params (symbols/bools/exec excluded)
        assert len(perturbable_params(golden)) == 22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jutsu_engine.audit.plateau'`.

- [ ] **Step 3: Write minimal implementation**

```python
# jutsu_engine/audit/plateau.py
"""Module 2 — Parameter plateau map (spec §6).

Pure, seeded perturbation-set generation + a checkpoint/resume campaign runner
(reusing the Phase-1 BacktestRunner bridge) + DB-free analysis functions.

Design contract:
  - Perturbable parameters are the NUMERIC (int/float, non-bool) keys of the live
    YAML's strategy.parameters, minus infra/symbol keys (PERTURBABLE_EXCLUDE).
  - Golden values are READ FROM THE LIVE YAML at runtime, never hard-coded, so
    v3_5d gets its own list automatically.
  - The campaign writes NO per-run CSVs to the report dir: each backtest runs into
    a throwaway tempdir that is cleaned afterward.
  - Analysis functions (plateau_score, degradation_table, cliff_list, joint stats)
    are pure over the collected results and are unit-tested without a database.
"""
from __future__ import annotations

import yaml

from jutsu_engine.audit.config import resolve_strategy

# Infra / symbol / string keys that are numeric-looking or must never perturb.
# Booleans are dropped separately by an isinstance(v, bool) guard (bool is int).
PERTURBABLE_EXCLUDE: frozenset[str] = frozenset({
    "execution_time",
    "signal_symbol", "core_long_symbol", "leveraged_long_symbol",
    "inverse_hedge_symbol", "bull_bond_symbol", "bear_bond_symbol",
    "treasury_trend_symbol",
    "name", "trade_logger",  # LiveStrategyRunner EXCLUDED_PARAMS
})


def load_golden_params(strategy_id: str) -> dict:
    """Return strategy.parameters from the live YAML for a strategy (no DB)."""
    spec = resolve_strategy(strategy_id)
    with open(spec.config_path, "r") as f:
        config = yaml.safe_load(f)
    return dict(config["strategy"]["parameters"])


def perturbable_params(golden: dict) -> dict:
    """Numeric, non-bool, non-infra keys of a golden params dict -> {name: value}.

    bool is a subclass of int in Python, so the bool guard MUST precede the
    (int, float) check or True/False would leak in as 1/0.
    """
    out = {}
    for k, v in golden.items():
        if k in PERTURBABLE_EXCLUDE:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = v
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): plateau perturbable-parameter extraction from live YAML"
```

---

## Task 2: One-at-a-time (OAT) perturbation-set generation (pure, seeded)

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/audit/test_plateau.py`:

```python
from jutsu_engine.audit.plateau import (
    OAT_MULTIPLIERS,
    oat_samples,
    params_hash,
    _apply_validity,
)


class TestOATSamples:
    def test_multipliers_are_the_spec_steps(self):
        """OAT multipliers are x0.8, x0.9, x1.1, x1.2 (spec §6 +/-10% and +/-20%)."""
        assert OAT_MULTIPLIERS == (0.8, 0.9, 1.1, 1.2)

    def test_float_param_produces_four_multiplied_variants(self):
        """A float param yields one sample per multiplier, each overriding just that key."""
        golden = {"leverage_scalar": 1.0, "sma_fast": 40}
        samples = [s for s in oat_samples(golden) if s["param"] == "leverage_scalar"]
        overrides = sorted(s["overrides"]["leverage_scalar"] for s in samples)
        assert overrides == [0.8, 0.9, 1.1, 1.2]
        # each OAT sample overrides exactly one parameter
        assert all(list(s["overrides"]) == ["leverage_scalar"] for s in samples)

    def test_negative_threshold_preserves_sign(self):
        """Multiplicative perturbation of t_norm_bear_thresh (-0.3) keeps it negative."""
        golden = {"t_norm_bear_thresh": -0.3}
        vals = [s["overrides"]["t_norm_bear_thresh"] for s in oat_samples(golden)]
        assert all(v < 0 for v in vals)
        # x0.8 of -0.3 = -0.24 (closer to zero), x1.2 = -0.36 (further)
        assert min(vals) == pytest.approx(-0.36)
        assert max(vals) == pytest.approx(-0.24)

    def test_integer_param_is_rounded_and_deduped(self):
        """Integer window is rounded; multipliers that round to the golden value are dropped."""
        # sma_fast=5: x0.8=4, x0.9=4->clamped to 5 floor? 4<5 -> raised to 5 == golden -> dropped;
        # use sma_fast=40 for a clean rounding case instead.
        golden = {"sma_fast": 40}
        vals = sorted(s["overrides"]["sma_fast"] for s in oat_samples(golden))
        # 32, 36, 44, 48 — all ints, all != 40, all >= 5 window floor
        assert vals == [32, 36, 44, 48]
        assert all(isinstance(v, int) for v in vals)

    def test_integer_rounding_collapse_is_deduped(self):
        """When x0.9/x1.1 round back to the golden int, those samples are dropped."""
        # osc_smoothness=5 (period, floor 2): x0.9=4.5->4? round(4.5)=4 (banker's? use int floor rules below)
        golden = {"osc_smoothness": 10}
        vals = sorted(s["overrides"]["osc_smoothness"] for s in oat_samples(golden))
        # 8, 9, 11, 12 — none collapse to 10
        assert 10 not in vals
        assert vals == [8, 9, 11, 12]

    def test_window_validity_floor_applied(self):
        """A tiny window whose x0.8 falls below the floor is clamped, then deduped vs golden."""
        golden = {"sma_fast": 6}  # window floor 5
        vals = sorted(s["overrides"]["sma_fast"] for s in oat_samples(golden))
        # x0.8=4.8->5 (floor), x0.9=5.4->5, x1.1=6.6->7, x1.2=7.2->7
        # 5 (deduped), 7 (deduped) -> {5, 7}; golden 6 dropped
        assert vals == [5, 7]


class TestParamsHash:
    def test_hash_is_stable_and_order_independent(self):
        """params_hash is deterministic and independent of dict insertion order."""
        a = params_hash({"sma_fast": 40, "sma_slow": 140})
        b = params_hash({"sma_slow": 140, "sma_fast": 40})
        assert a == b and len(a) == 16

    def test_hash_differs_on_value_change(self):
        """A changed value changes the hash."""
        assert params_hash({"sma_fast": 40}) != params_hash({"sma_fast": 41})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'OAT_MULTIPLIERS'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py` (add `hashlib`, `json`, `math` imports at top):

```python
import hashlib
import json
import math

# Spec §6: one-at-a-time at +/-10% and +/-20% (multiplicative).
OAT_MULTIPLIERS: tuple[float, ...] = (0.8, 0.9, 1.1, 1.2)

# Validity floors by parameter family. Windows need >=5 bars; period-smoothers >=2.
_WINDOW_PARAMS = frozenset({
    "sma_fast", "sma_slow", "realized_vol_window", "vol_baseline_window",
    "bond_sma_fast", "bond_sma_slow",
})
_PERIOD_PARAMS = frozenset({
    "osc_smoothness", "strength_smoothness", "vol_crush_lookback",
})


def _is_int_param(name: str, golden_value) -> bool:
    """True if the parameter is integer-valued (stored as int in the YAML)."""
    return isinstance(golden_value, int) and not isinstance(golden_value, bool)


def _apply_validity(name: str, value: float, golden_value):
    """Clamp to validity floors and round integers.

    - Integer params (windows/periods) are rounded to nearest int and clamped to
      their floor (windows >=5, periods >=2).
    - Sign is preserved automatically by multiplicative perturbation (no clamp
      flips a negative threshold positive).
    """
    if _is_int_param(name, golden_value):
        v = int(round(value))
        if name in _WINDOW_PARAMS:
            v = max(v, 5)
        elif name in _PERIOD_PARAMS:
            v = max(v, 2)
        return v
    return value


def params_hash(overrides: dict) -> str:
    """Stable 16-char hex hash of an overrides dict (order-independent)."""
    payload = json.dumps(overrides, sort_keys=True, separators=(",", ":"),
                         default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def oat_samples(golden: dict) -> list[dict]:
    """One-at-a-time perturbation samples over the perturbable params of `golden`.

    Each sample: {"kind": "oat", "param": name, "overrides": {name: value},
                  "hash": <hash>}. Multiplier variants that (after integer
    rounding / floor clamping) collapse to the golden value are deduped away.
    """
    out = []
    per = perturbable_params(golden)
    for name, gval in per.items():
        seen: set = set()
        for mult in OAT_MULTIPLIERS:
            raw = gval * mult
            val = _apply_validity(name, raw, gval)
            if val == gval or val in seen:
                continue  # rounding/clamp collapsed to golden or a duplicate
            seen.add(val)
            overrides = {name: val}
            out.append({
                "kind": "oat",
                "param": name,
                "overrides": overrides,
                "hash": params_hash(overrides),
            })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): seeded one-at-a-time perturbation-set generation"
```

---

## Task 3: Joint random perturbation-set generation (pure, seeded)

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/audit/test_plateau.py`:

```python
from jutsu_engine.audit.plateau import JOINT_BOX_FRACTION, joint_samples


class TestJointSamples:
    def test_default_count_and_seed_reproducibility(self):
        """joint_samples(N, seed) yields N reproducible samples for a fixed seed."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0, "signal_symbol": "QQQ"}
        a = joint_samples(golden, n=10, seed=7)
        b = joint_samples(golden, n=10, seed=7)
        assert len(a) == 10
        assert [s["overrides"] for s in a] == [s["overrides"] for s in b]

    def test_different_seed_gives_different_samples(self):
        """A different seed produces a different sample sequence."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        a = joint_samples(golden, n=10, seed=1)
        b = joint_samples(golden, n=10, seed=2)
        assert [s["overrides"] for s in a] != [s["overrides"] for s in b]

    def test_every_sample_perturbs_all_params_within_box(self):
        """Each joint sample perturbs every perturbable param within +/-15% (integers rounded)."""
        golden = {"leverage_scalar": 1.0, "sma_fast": 40, "signal_symbol": "QQQ"}
        s = joint_samples(golden, n=50, seed=3)[0]
        assert set(s["overrides"]) == {"leverage_scalar", "sma_fast"}
        lo, hi = 1.0 * (1 - JOINT_BOX_FRACTION), 1.0 * (1 + JOINT_BOX_FRACTION)
        assert lo <= s["overrides"]["leverage_scalar"] <= hi
        assert isinstance(s["overrides"]["sma_fast"], int)

    def test_negative_param_stays_negative_in_box(self):
        """A negative threshold stays negative across the whole +/-15% box."""
        golden = {"t_norm_bear_thresh": -0.3}
        samples = joint_samples(golden, n=100, seed=5)
        assert all(s["overrides"]["t_norm_bear_thresh"] < 0 for s in samples)

    def test_sample_kind_and_hash_present(self):
        """Joint samples are tagged kind='joint' and carry a params hash."""
        s = joint_samples({"sma_fast": 40}, n=1, seed=9)[0]
        assert s["kind"] == "joint"
        assert len(s["hash"]) == 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'JOINT_BOX_FRACTION'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py` (add `import random` at top):

```python
import random

# Spec §6: joint samples inside a +/-15% box around golden.
JOINT_BOX_FRACTION: float = 0.15
DEFAULT_JOINT_SAMPLES: int = 200


def joint_samples(golden: dict, n: int = DEFAULT_JOINT_SAMPLES,
                  seed: int = 0) -> list[dict]:
    """N seeded uniform samples in the +/-15% box over all perturbable params.

    Every perturbable parameter is independently drawn uniformly in
    [g*(1-0.15), g*(1+0.15)]; integers are rounded and floor-clamped via
    _apply_validity; sign is preserved by construction. RNG is a per-call
    random.Random(seed) so results are reproducible and the seed is recorded
    in the campaign output.
    """
    rng = random.Random(seed)
    per = perturbable_params(golden)
    out = []
    for i in range(n):
        overrides = {}
        for name, gval in per.items():
            lo = gval * (1.0 - JOINT_BOX_FRACTION)
            hi = gval * (1.0 + JOINT_BOX_FRACTION)
            if lo > hi:  # negative golden: bounds are swapped, fix ordering
                lo, hi = hi, lo
            raw = rng.uniform(lo, hi)
            overrides[name] = _apply_validity(name, raw, gval)
        out.append({
            "kind": "joint",
            "param": None,
            "overrides": overrides,
            "hash": params_hash(overrides),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): seeded joint uniform perturbation samples (+/-15% box)"
```

---

## Task 4: Pure analysis functions (plateau score, degradation, cliffs, joint stats)

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

These operate over a list of "result rows" — the schema the campaign runner (Task 6) writes to JSONL. A result row is a dict:
`{"hash": str, "kind": "oat"|"joint", "param": str|None, "overrides": dict, "sharpe": float, "max_drawdown": float, "annualized_return": float, "total_return": float}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/audit/test_plateau.py`:

```python
from jutsu_engine.audit.plateau import (
    CLIFF_LOSS_FRACTION,
    cliff_list,
    degradation_table,
    joint_stats,
    plateau_score,
)


def _oat_row(param, override_val, sharpe):
    ov = {param: override_val}
    return {"hash": params_hash(ov), "kind": "oat", "param": param,
            "overrides": ov, "sharpe": sharpe, "max_drawdown": -0.2,
            "annualized_return": 0.1, "total_return": 1.0}


class TestPlateauScore:
    def test_mean_retained_sharpe_fraction_at_20pct(self):
        """plateau_score = mean(perturbed sharpe / golden sharpe) over the +/-20% (x0.8, x1.2) rows."""
        golden = {"sma_fast": 40}
        golden_sharpe = 1.0
        # x0.8 -> sma 32 retains 0.9; x1.2 -> sma 48 retains 0.7; +/-10% ignored for the score
        rows = [
            _oat_row("sma_fast", 32, 0.9),
            _oat_row("sma_fast", 36, 0.95),  # x0.9, ignored by the +/-20% score
            _oat_row("sma_fast", 44, 0.99),  # x1.1, ignored
            _oat_row("sma_fast", 48, 0.7),
        ]
        score = plateau_score(rows, golden, golden_sharpe, "sma_fast")
        assert score == pytest.approx((0.9 + 0.7) / 2)

    def test_missing_rows_return_nan(self):
        """A parameter with no +/-20% rows collected yields NaN (not a crash)."""
        assert math.isnan(plateau_score([], {"sma_fast": 40}, 1.0, "sma_fast"))


class TestDegradationTable:
    def test_one_row_per_param_step_with_retained_fraction(self):
        """degradation_table returns per-param, per-step retained Sharpe and MAR fractions."""
        golden = {"sma_fast": 40}
        rows = [_oat_row("sma_fast", 32, 0.5), _oat_row("sma_fast", 48, 1.0)]
        tbl = degradation_table(rows, golden, golden_sharpe=1.0)
        assert set(tbl["param"]) == {"sma_fast"}
        # retained_sharpe for the sma_fast=32 row = 0.5 / 1.0
        r = tbl[tbl["override_value"] == 32].iloc[0]
        assert r["retained_sharpe"] == pytest.approx(0.5)


class TestCliffList:
    def test_flags_params_losing_more_than_30pct_at_10pct(self):
        """cliff_list flags params whose +/-10% (x0.9 or x1.1) move loses > 30% of Sharpe."""
        golden = {"sma_fast": 40, "sma_slow": 140}
        rows = [
            _oat_row("sma_fast", 36, 0.5),   # x0.9 of 40 -> retains 0.5 -> cliff (>30% loss)
            _oat_row("sma_fast", 44, 0.95),
            _oat_row("sma_slow", 126, 0.98), # x0.9 of 140
            _oat_row("sma_slow", 154, 0.99),
        ]
        cliffs = cliff_list(rows, golden, golden_sharpe=1.0)
        assert "sma_fast" in cliffs
        assert "sma_slow" not in cliffs

    def test_cliff_threshold_constant(self):
        """The cliff loss threshold is 30% (spec §6)."""
        assert CLIFF_LOSS_FRACTION == 0.30


class TestJointStats:
    def test_histogram_and_golden_percentile(self):
        """joint_stats returns histogram bins and the golden Sharpe's percentile in the joint sample."""
        rows = [{"hash": str(i), "kind": "joint", "param": None, "overrides": {},
                 "sharpe": s, "max_drawdown": -0.2, "annualized_return": 0.1,
                 "total_return": 1.0}
                for i, s in enumerate([0.2, 0.4, 0.6, 0.8, 1.0])]
        stats = joint_stats(rows, golden_sharpe=0.6, bins=5)
        assert stats["count"] == 5
        # golden 0.6: two of five samples (0.2, 0.4) are strictly below -> 40th pct
        assert stats["golden_percentile"] == pytest.approx(40.0)
        assert len(stats["hist_counts"]) == 5
        assert len(stats["hist_edges"]) == 6

    def test_empty_joint_returns_nan_percentile(self):
        """No joint rows -> count 0 and NaN percentile (graceful)."""
        stats = joint_stats([], golden_sharpe=0.6)
        assert stats["count"] == 0
        assert math.isnan(stats["golden_percentile"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'CLIFF_LOSS_FRACTION'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py` (add `import numpy as np` and `import pandas as pd` at top):

```python
import numpy as np
import pandas as pd

# Spec §6: a param losing >30% of Sharpe at a +/-10% move is a "cliff".
CLIFF_LOSS_FRACTION: float = 0.30
# Steps counted as "+/-20%" for plateau_score (multiplicative x0.8 / x1.2).
_PLATEAU_MULTIPLIERS = (0.8, 1.2)
_TEN_PCT_MULTIPLIERS = (0.9, 1.1)


def _rows_for_param(rows: list[dict], param: str) -> list[dict]:
    return [r for r in rows if r.get("param") == param]


def _override_matches_multiplier(row: dict, golden: dict, param: str,
                                 mult: float) -> bool:
    """True if this OAT row's override for `param` equals golden*mult after validity."""
    gval = golden[param]
    want = _apply_validity(param, gval * mult, gval)
    return row["overrides"].get(param) == want


def plateau_score(rows: list[dict], golden: dict, golden_sharpe: float,
                  param: str) -> float:
    """Mean retained Sharpe fraction at +/-20% (x0.8, x1.2) for one parameter.

    Retained fraction = perturbed_sharpe / golden_sharpe. Returns NaN if no
    +/-20% rows were collected for the parameter.
    """
    prows = _rows_for_param(rows, param)
    fracs = []
    for mult in _PLATEAU_MULTIPLIERS:
        for r in prows:
            if _override_matches_multiplier(r, golden, param, mult):
                if golden_sharpe not in (0, 0.0):
                    fracs.append(r["sharpe"] / golden_sharpe)
    return float(np.mean(fracs)) if fracs else float("nan")


def degradation_table(rows: list[dict], golden: dict,
                      golden_sharpe: float) -> pd.DataFrame:
    """Per-param, per-step degradation: retained Sharpe fraction for each OAT row.

    Columns: param, override_value, sharpe, retained_sharpe, max_drawdown,
    annualized_return. Only OAT rows (param is not None) are included.
    """
    recs = []
    for r in rows:
        p = r.get("param")
        if p is None:
            continue
        recs.append({
            "param": p,
            "override_value": r["overrides"].get(p),
            "sharpe": r["sharpe"],
            "retained_sharpe": (r["sharpe"] / golden_sharpe
                                if golden_sharpe not in (0, 0.0) else float("nan")),
            "max_drawdown": r["max_drawdown"],
            "annualized_return": r["annualized_return"],
        })
    return pd.DataFrame(recs).sort_values(["param", "override_value"]).reset_index(drop=True)


def cliff_list(rows: list[dict], golden: dict, golden_sharpe: float) -> list[str]:
    """Params whose +/-10% (x0.9 or x1.1) move loses > CLIFF_LOSS_FRACTION of Sharpe."""
    cliffs = set()
    for param, gval in perturbable_params(golden).items():
        for mult in _TEN_PCT_MULTIPLIERS:
            for r in _rows_for_param(rows, param):
                if _override_matches_multiplier(r, golden, param, mult):
                    if golden_sharpe in (0, 0.0):
                        continue
                    retained = r["sharpe"] / golden_sharpe
                    if retained < (1.0 - CLIFF_LOSS_FRACTION):
                        cliffs.add(param)
    return sorted(cliffs)


def joint_stats(rows: list[dict], golden_sharpe: float, bins: int = 20) -> dict:
    """Histogram of joint-sample Sharpe + golden config's percentile within it.

    golden_percentile = fraction of joint samples with Sharpe strictly below the
    golden Sharpe, as a percentage. NaN percentile when no joint rows exist.
    """
    sharpes = [r["sharpe"] for r in rows if r.get("kind") == "joint"]
    if not sharpes:
        return {"count": 0, "golden_percentile": float("nan"),
                "hist_counts": [], "hist_edges": [],
                "min": float("nan"), "max": float("nan"), "median": float("nan")}
    arr = np.asarray(sharpes, dtype=float)
    below = float(np.sum(arr < golden_sharpe))
    pct = below / len(arr) * 100.0
    counts, edges = np.histogram(arr, bins=bins)
    return {
        "count": len(arr),
        "golden_percentile": pct,
        "hist_counts": counts.tolist(),
        "hist_edges": edges.tolist(),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "median": float(np.median(arr)),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): pure plateau analysis (score, degradation, cliffs, joint stats)"
```

---

## Task 5: Param-override strategy builder (extends the Phase-1 bridge)

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

This is the minimal replication of `LiveStrategyRunner`'s float→Decimal conversion (`strategy_runner.py:124-137`) applied on top of param overrides. It builds a strategy instance directly (no DB), so it is unit-testable against the real YAML.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/audit/test_plateau.py`:

```python
from decimal import Decimal

from jutsu_engine.audit.plateau import (
    DECIMAL_PARAMS,
    build_overridden_strategy,
)


class TestBuildOverriddenStrategy:
    def test_decimal_params_match_strategy_runner(self):
        """DECIMAL_PARAMS mirrors LiveStrategyRunner._convert_decimal_params exactly."""
        assert "measurement_noise" in DECIMAL_PARAMS
        assert "t_norm_bear_thresh" in DECIMAL_PARAMS
        assert "rebalance_threshold" in DECIMAL_PARAMS
        # integer window params are NOT decimal
        assert "sma_fast" not in DECIMAL_PARAMS

    def test_override_applies_and_converts_to_decimal(self):
        """Overriding a decimal param yields a strategy whose attribute is the Decimal override."""
        strat = build_overridden_strategy("v3_5b", {"leverage_scalar": 1.2})
        assert strat.leverage_scalar == Decimal("1.2")
        # a non-overridden decimal param keeps its golden Decimal value
        assert strat.max_bond_weight == Decimal("0.4")

    def test_override_integer_param_stays_int(self):
        """Overriding an integer window keeps it an int on the built strategy."""
        strat = build_overridden_strategy("v3_5b", {"sma_fast": 32})
        assert int(strat.sma_fast) == 32
        assert strat.__class__.__name__ == "Hierarchical_Adaptive_v3_5b"

    def test_no_overrides_reproduces_golden(self):
        """With no overrides, the built strategy matches build_strategy_instance's golden values."""
        strat = build_overridden_strategy("v3_5b", {})
        assert int(strat.sma_fast) == 40
        assert int(strat.sma_slow) == 140
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'DECIMAL_PARAMS'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py` (add `import importlib` and `from decimal import Decimal` at top):

```python
import importlib
from decimal import Decimal

# Mirrors LiveStrategyRunner._convert_decimal_params (strategy_runner.py:124-137).
# Kept as its own constant so a drift between the two is caught by a unit test.
DECIMAL_PARAMS: frozenset[str] = frozenset({
    "measurement_noise", "process_noise_1", "process_noise_2",
    "T_max", "t_norm_bull_thresh", "t_norm_bear_thresh",
    "upper_thresh_z", "lower_thresh_z", "vol_crush_threshold",
    "leverage_scalar", "w_PSQ_max", "max_bond_weight",
    "rebalance_threshold",
})

# Metadata keys never passed to the strategy __init__ (LiveStrategyRunner EXCLUDED_PARAMS).
_INIT_EXCLUDE = frozenset({"name", "trade_logger"})


def _prepared_params(golden: dict, overrides: dict) -> dict:
    """Golden params with overrides applied and floats->Decimal per DECIMAL_PARAMS.

    Replicates LiveStrategyRunner: drop metadata keys, apply overrides, convert
    the decimal set to Decimal(str(value)). Non-decimal numerics/strings/bools
    pass through unchanged.
    """
    params = {k: v for k, v in golden.items() if k not in _INIT_EXCLUDE}
    params.update(overrides)
    for key in DECIMAL_PARAMS:
        if key in params and not isinstance(params[key], Decimal):
            params[key] = Decimal(str(params[key]))
    return params


def build_overridden_strategy(strategy_id: str, overrides: dict):
    """Build a live strategy instance with param overrides applied (no DB).

    Reads golden params from the live YAML, applies overrides, converts to the
    same Decimal conventions LiveStrategyRunner uses, instantiates the strategy
    class directly, and calls .init() — identical to the live construction path
    except for the overrides.
    """
    spec = resolve_strategy(strategy_id)
    mod = importlib.import_module(spec.module_path)
    strategy_class = getattr(mod, spec.class_name)
    golden = load_golden_params(strategy_id)
    params = _prepared_params(golden, overrides)
    strategy = strategy_class(**params)
    strategy.init()
    return strategy
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Add a drift-guard test tying DECIMAL_PARAMS to the live source**

Append to `tests/unit/audit/test_plateau.py`:

```python
class TestDecimalParamsDriftGuard:
    def test_matches_live_strategy_runner_set(self):
        """DECIMAL_PARAMS stays in sync with LiveStrategyRunner's decimal_params."""
        import inspect
        from jutsu_engine.live import strategy_runner
        src = inspect.getsource(strategy_runner.LiveStrategyRunner._convert_decimal_params)
        for name in DECIMAL_PARAMS:
            assert f"'{name}'" in src, f"{name} missing from live decimal set"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): param-override strategy builder replicating live Decimal conv"
```

---

## Task 6: Campaign runner — single backtest + JSONL checkpoint/resume

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

This adds: (a) `run_one_sample` — a picklable worker that builds an overridden strategy, runs one full-period backtest into a throwaway tempdir, and returns a result row; (b) `load_completed_hashes` / `append_result` — the JSONL checkpoint I/O (pure, DB-free, unit-tested); (c) `build_campaign_samples` — assembles OAT + joint into one deduped list.

- [ ] **Step 1: Write the failing test (checkpoint I/O + sample assembly are pure)**

Append to `tests/unit/audit/test_plateau.py`:

```python
from jutsu_engine.audit.plateau import (
    append_result,
    build_campaign_samples,
    load_completed_hashes,
)


class TestCheckpointIO:
    def test_append_and_reload_hashes(self, tmp_path):
        """append_result writes a JSONL row; load_completed_hashes reads back its hash."""
        f = tmp_path / "campaign.jsonl"
        row = {"hash": "abc123", "kind": "oat", "param": "sma_fast",
               "overrides": {"sma_fast": 32}, "sharpe": 0.5,
               "max_drawdown": -0.2, "annualized_return": 0.1, "total_return": 1.0}
        append_result(f, row)
        assert load_completed_hashes(f) == {"abc123"}

    def test_missing_file_is_empty_set(self, tmp_path):
        """load_completed_hashes on a nonexistent file returns an empty set (fresh start)."""
        assert load_completed_hashes(tmp_path / "nope.jsonl") == set()

    def test_two_rows_two_hashes(self, tmp_path):
        """Multiple appended rows all resume-skippable by hash."""
        f = tmp_path / "c.jsonl"
        append_result(f, {"hash": "h1", "overrides": {}, "sharpe": 1.0,
                          "max_drawdown": -0.1, "annualized_return": 0.1,
                          "total_return": 1.0, "kind": "joint", "param": None})
        append_result(f, {"hash": "h2", "overrides": {}, "sharpe": 1.0,
                          "max_drawdown": -0.1, "annualized_return": 0.1,
                          "total_return": 1.0, "kind": "joint", "param": None})
        assert load_completed_hashes(f) == {"h1", "h2"}


class TestBuildCampaignSamples:
    def test_combines_oat_and_joint_deduped(self):
        """build_campaign_samples concatenates OAT + joint and drops duplicate hashes."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        samples = build_campaign_samples(golden, joint_n=5, seed=1)
        hashes = [s["hash"] for s in samples]
        assert len(hashes) == len(set(hashes))  # no dup hashes
        kinds = {s["kind"] for s in samples}
        assert kinds == {"oat", "joint"}

    def test_oat_only_flag_skips_joint(self):
        """oat_only=True yields only one-at-a-time samples."""
        golden = {"sma_fast": 40}
        samples = build_campaign_samples(golden, joint_n=5, seed=1, oat_only=True)
        assert {s["kind"] for s in samples} == {"oat"}

    def test_params_filter_restricts_oat(self):
        """params filter restricts OAT samples to the named parameters (for the smoke run)."""
        golden = {"sma_fast": 40, "sma_slow": 140}
        samples = build_campaign_samples(golden, joint_n=0, seed=1, oat_only=True,
                                         params=["sma_fast"])
        assert {s["param"] for s in samples} == {"sma_fast"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'append_result'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py` (add `import tempfile`, `import shutil`, `from datetime import date, datetime, timezone`, `from pathlib import Path` at top):

```python
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

_RESULT_KEYS = ("hash", "kind", "param", "overrides",
                "sharpe", "max_drawdown", "annualized_return", "total_return")


def build_campaign_samples(golden: dict, joint_n: int = DEFAULT_JOINT_SAMPLES,
                           seed: int = 0, oat_only: bool = False,
                           params: list[str] | None = None) -> list[dict]:
    """Assemble the full perturbation set: OAT (optionally filtered) + joint.

    `params` restricts the OAT set to the named parameters (used by the smoke
    run). Duplicate hashes across OAT/joint are dropped, first occurrence wins.
    """
    oat = oat_samples(golden)
    if params is not None:
        oat = [s for s in oat if s["param"] in set(params)]
    joint = [] if oat_only or joint_n <= 0 else joint_samples(golden, n=joint_n, seed=seed)
    seen: set = set()
    out = []
    for s in oat + joint:
        if s["hash"] in seen:
            continue
        seen.add(s["hash"])
        out.append(s)
    return out


def load_completed_hashes(path: Path) -> set[str]:
    """Set of params-hashes already present in a campaign JSONL file (empty if missing)."""
    path = Path(path)
    if not path.exists():
        return set()
    done = set()
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["hash"])
            except (json.JSONDecodeError, KeyError):
                continue  # tolerate a partially-written trailing line
    return done


def append_result(path: Path, row: dict) -> None:
    """Append one result row as a JSONL line (created if missing). Flushed to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {k: row.get(k) for k in _RESULT_KEYS}
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()


def run_one_sample(strategy_id: str, sample: dict, symbols: list[str],
                   start: date, end: date,
                   initial_capital: str = "10000") -> dict:
    """Run ONE full-period backtest for a perturbation sample; return a result row.

    Picklable (plain args only) so it can run inside a ProcessPoolExecutor worker.
    Writes ALL CSVs to a throwaway tempdir that is removed afterward, so no per-run
    regime/portfolio CSVs land in the report directory (spec §6 reduced-output).
    Reuses BacktestRunner exactly as run_attribution does (attribution.py:234-251).
    """
    from jutsu_engine.application.backtest_runner import BacktestRunner

    config = {
        "symbols": symbols,
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": Decimal(str(initial_capital)),
    }
    strategy = build_overridden_strategy(strategy_id, sample["overrides"])
    tmpdir = tempfile.mkdtemp(prefix="plateau_")
    try:
        runner = BacktestRunner(config)
        results = runner.run(strategy, output_dir=tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "hash": sample["hash"],
        "kind": sample["kind"],
        "param": sample["param"],
        "overrides": sample["overrides"],
        "sharpe": results.get("sharpe_ratio"),
        "max_drawdown": results.get("max_drawdown"),
        "annualized_return": results.get("annualized_return"),
        "total_return": results.get("total_return"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (checkpoint I/O + sample assembly; `run_one_sample` is exercised later by the smoke run, not unit-tested since it needs the DB).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): campaign sample assembly + JSONL checkpoint/resume + worker"
```

---

## Task 7: Campaign orchestrator (serial + optional workers, resume)

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

`run_campaign` ties it together: it computes the sample list, skips already-completed hashes, runs each sample (serially with `--workers 1`, or via `ProcessPoolExecutor` for K>1), appends each result to the JSONL as it lands, and returns the collected rows + campaign metadata. The DB-touching path is not unit-tested; instead the orchestration logic is tested by **injecting a fake `run_fn`** so no backtest/DB runs.

- [ ] **Step 1: Write the failing test (fake run_fn — no DB)**

Append to `tests/unit/audit/test_plateau.py`:

```python
from jutsu_engine.audit.plateau import CampaignResult, run_campaign


def _fake_run_fn(strategy_id, sample, symbols, start, end, initial_capital="10000"):
    # deterministic fake: sharpe = 1.0 minus a small penalty per override delta
    return {
        "hash": sample["hash"], "kind": sample["kind"], "param": sample["param"],
        "overrides": sample["overrides"], "sharpe": 0.8,
        "max_drawdown": -0.5, "annualized_return": 0.23, "total_return": 5.0,
    }


class TestRunCampaign:
    def test_runs_all_samples_and_checkpoints(self, tmp_path):
        """run_campaign executes every sample once, appends to JSONL, returns rows."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        camp_file = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", golden, camp_file, joint_n=3, seed=1, workers=1,
            run_fn=_fake_run_fn, symbols=["QQQ"], start=date(2010, 2, 1),
            end=date(2026, 7, 6),
        )
        assert isinstance(res, CampaignResult)
        assert len(res.rows) == len(res.samples)
        assert load_completed_hashes(camp_file) == {s["hash"] for s in res.samples}
        assert res.seed == 1

    def test_resume_skips_completed(self, tmp_path):
        """A second run over the same file skips already-completed samples (no re-run)."""
        golden = {"sma_fast": 40}
        camp_file = tmp_path / "c.jsonl"
        calls = {"n": 0}

        def counting_run_fn(*a, **k):
            calls["n"] += 1
            return _fake_run_fn(*a, **k)

        run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                     run_fn=counting_run_fn, symbols=["QQQ"], oat_only=True,
                     start=date(2010, 2, 1), end=date(2026, 7, 6))
        first = calls["n"]
        # second invocation: everything already in the file -> zero new run_fn calls
        run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                     run_fn=counting_run_fn, symbols=["QQQ"], oat_only=True,
                     start=date(2010, 2, 1), end=date(2026, 7, 6))
        assert calls["n"] == first  # no new work

    def test_params_filter_limits_to_smoke_set(self, tmp_path):
        """params filter + oat_only runs only the named parameter's four OAT samples."""
        golden = {"sma_fast": 40, "sma_slow": 140}
        camp_file = tmp_path / "smoke.jsonl"
        res = run_campaign("v3_5b", golden, camp_file, joint_n=0, seed=1, workers=1,
                           run_fn=_fake_run_fn, symbols=["QQQ"], oat_only=True,
                           params=["sma_fast"], start=date(2010, 2, 1),
                           end=date(2026, 7, 6))
        assert {r["param"] for r in res.rows} == {"sma_fast"}
        assert len(res.rows) == 4  # x0.8/x0.9/x1.1/x1.2, none collapse for sma_fast=40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'CampaignResult'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py` (add `import os`, `from concurrent.futures import ProcessPoolExecutor, as_completed`, `from dataclasses import dataclass`, `from jutsu_engine.audit.config import ATTRIBUTION_START` at top):

```python
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

from jutsu_engine.audit.config import ATTRIBUTION_START


def default_workers() -> int:
    """Default worker count: min(4, cpu_count). Parallelism is opt-in via --workers."""
    return min(4, os.cpu_count() or 1)


@dataclass
class CampaignResult:
    """Everything the report needs from a completed (or resumed) campaign."""
    strategy_id: str
    seed: int
    samples: list          # the full sample list (post-filter)
    rows: list             # result rows collected THIS run + reloaded from file
    campaign_file: str
    golden: dict


def _reload_rows(path: Path) -> list[dict]:
    """Load all result rows from a campaign JSONL (for resume + report)."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def run_campaign(strategy_id: str, golden: dict, campaign_file: Path,
                 joint_n: int = DEFAULT_JOINT_SAMPLES, seed: int = 0,
                 workers: int = 1, oat_only: bool = False,
                 params: list[str] | None = None,
                 run_fn=run_one_sample, symbols: list[str] | None = None,
                 start: date | None = None, end: date | None = None,
                 initial_capital: str = "10000",
                 progress=lambda msg: None) -> CampaignResult:
    """Run (or resume) a perturbation campaign, checkpointing each result to JSONL.

    - Samples already present in `campaign_file` (by hash) are skipped (resume).
    - workers == 1 runs serially; workers > 1 uses ProcessPoolExecutor (each
      worker builds its own BacktestRunner + strategy — verified safe).
    - run_fn is injectable so orchestration is unit-testable without a DB.
    - Every completed sample is appended immediately so a crash loses at most the
      in-flight backtests.
    """
    campaign_file = Path(campaign_file)
    start = start or ATTRIBUTION_START
    end = end or date.today()
    samples = build_campaign_samples(golden, joint_n=joint_n, seed=seed,
                                     oat_only=oat_only, params=params)
    done = load_completed_hashes(campaign_file)
    todo = [s for s in samples if s["hash"] not in done]
    progress(f"{len(samples)} samples, {len(done)} already done, {len(todo)} to run")

    def _do(sample):
        return run_fn(strategy_id, sample, symbols or [], start, end, initial_capital)

    if workers <= 1:
        for i, sample in enumerate(todo, 1):
            row = _do(sample)
            append_result(campaign_file, row)
            progress(f"[{i}/{len(todo)}] {sample['kind']} "
                     f"{sample['param'] or 'joint'} sharpe={row.get('sharpe')}")
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_do, s): s for s in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                row = fut.result()
                append_result(campaign_file, row)
                progress(f"[{i}/{len(todo)}] done sharpe={row.get('sharpe')}")

    rows = _reload_rows(campaign_file)
    return CampaignResult(strategy_id=strategy_id, seed=seed, samples=samples,
                          rows=rows, campaign_file=str(campaign_file), golden=golden)
```

Note on the `workers > 1` path: `ProcessPoolExecutor` on macOS uses `spawn`, so the submitted callable must be picklable. `_do` is a closure and is NOT picklable — for the parallel path, submit the module-level `run_fn` directly with its args instead. Replace the `else` branch body with:

```python
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(run_fn, strategy_id, s, symbols or [], start, end,
                          initial_capital): s
                for s in todo
            }
            for i, fut in enumerate(as_completed(futs), 1):
                row = fut.result()
                append_result(campaign_file, row)
                progress(f"[{i}/{len(todo)}] done sharpe={row.get('sharpe')}")
```

(The injected fake `run_fn` in tests always runs with `workers=1`, so the pickling constraint only applies to the real `run_one_sample`, which is module-level and picklable.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): campaign orchestrator with resume + opt-in workers"
```

---

## Task 8: Plateau report section + standalone report file

**Files:**
- Modify: `jutsu_engine/audit/report.py`
- Test: `tests/unit/audit/test_report.py`

`render_plateau_section` builds the markdown; `write_plateau_report` writes `report_plateau_<strategy>.md` (a NEW file — it does NOT call `write_report` and never touches `report_<strategy>.md`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/audit/test_report.py`:

```python
import math

from jutsu_engine.audit.report import render_plateau_section, write_plateau_report


def _plateau_summary():
    import pandas as pd
    return {
        "strategy_id": "v3_5b",
        "seed": 42,
        "oat_count": 88,
        "joint_count": 200,
        "golden_metrics": {"sharpe_ratio": 0.81, "max_drawdown": -0.512,
                           "annualized_return": 0.231, "total_return": 8.0},
        "plateau_scores": {"sma_fast": 0.95, "vol_crush_threshold": 0.40},
        "degradation_table": pd.DataFrame([
            {"param": "sma_fast", "override_value": 32, "sharpe": 0.78,
             "retained_sharpe": 0.96, "max_drawdown": -0.5, "annualized_return": 0.22},
        ]),
        "cliffs": ["vol_crush_threshold"],
        "joint_stats": {"count": 200, "golden_percentile": 88.0,
                        "min": 0.2, "max": 1.1, "median": 0.6,
                        "hist_counts": [10, 40, 90, 50, 10],
                        "hist_edges": [0.2, 0.4, 0.6, 0.8, 1.0, 1.1]},
    }


class TestRenderPlateauSection:
    def test_includes_seed_counts_verdict_and_cliffs(self):
        """Plateau section embeds seed, sample counts, golden metrics, cliffs, and the percentile verdict."""
        md = render_plateau_section(_plateau_summary())
        assert "seed" in md.lower() and "42" in md
        assert "88" in md and "200" in md  # oat + joint counts
        assert "vol_crush_threshold" in md  # cliff parameter flagged
        assert "88.0" in md  # golden percentile within joint distribution
        assert "0.81" in md  # golden Sharpe

    def test_cliff_threshold_row_present(self):
        """The spec §10 threshold row (cliff params -> robustness work) is printed."""
        md = render_plateau_section(_plateau_summary())
        assert "Cliff parameters" in md
        assert ">30%" in md or "30%" in md

    def test_empty_cliffs_states_none(self):
        """With no cliffs, the section says so explicitly (no crash)."""
        s = _plateau_summary()
        s["cliffs"] = []
        md = render_plateau_section(s)
        assert "no cliff" in md.lower() or "(none)" in md.lower()


class TestWritePlateauReport:
    def test_writes_standalone_file_not_phase1_report(self, tmp_path):
        """write_plateau_report creates report_plateau_<strategy>.md and leaves report_<strategy>.md untouched."""
        (tmp_path / "report_v3_5b.md").write_text("PHASE-1 DO NOT TOUCH")
        out = write_plateau_report(tmp_path, "v3_5b", "# plateau body\n")
        assert out.name == "report_plateau_v3_5b.md"
        assert out.read_text() == "# plateau body\n"
        # Phase-1 report file is unchanged
        assert (tmp_path / "report_v3_5b.md").read_text() == "PHASE-1 DO NOT TOUCH"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'render_plateau_section'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/report.py`:

```python
# spec §10 decision threshold for Module 2.
CLIFF_LOSS_THRESHOLD_PCT = 30.0


def render_plateau_section(summary: dict) -> str:
    """Render the Parameter Plateau (Module 2) section as a markdown string.

    `summary` keys: strategy_id, seed, oat_count, joint_count, golden_metrics,
    plateau_scores {param: fraction}, degradation_table (DataFrame), cliffs
    (list[str]), joint_stats {count, golden_percentile, min, max, median, ...}.
    """
    gm = summary["golden_metrics"]
    js = summary["joint_stats"]
    cliffs = summary["cliffs"]
    pct = js.get("golden_percentile")

    right_tail = (pct is not None and not (isinstance(pct, float) and pct != pct)
                  and pct >= 80.0)
    percentile_verdict = (
        f"golden Sharpe sits at the **{_fmt(pct, '.1f')}th percentile** of its own "
        f"+/-15% neighborhood — "
        + ("**far in the right tail (>=80th): a red flag that the golden config is "
           "a local peak fit to its neighborhood.**" if right_tail else
           "within the body of its neighborhood distribution (not an isolated peak).")
    )

    cliff_line = (", ".join(f"`{c}`" for c in cliffs) if cliffs
                  else "_(none — no parameter loses >30% of Sharpe at +/-10%)_")

    # Plateau-score table (retained Sharpe fraction at +/-20%), sorted worst-first.
    ps = summary["plateau_scores"]
    ps_rows = sorted(ps.items(), key=lambda kv: (kv[1] if kv[1] == kv[1] else 1e9))
    ps_lines = ["| param | plateau score (retained Sharpe @ +/-20%) |",
                "| --- | --- |"]
    for name, score in ps_rows:
        ps_lines.append(f"| `{name}` | {_fmt(score, '.3f')} |")

    lines = [
        "## Parameter plateau map (Module 2)",
        "",
        f"- Strategy: **{summary['strategy_id']}**  |  RNG seed: **{summary['seed']}**",
        f"- One-at-a-time samples: **{summary['oat_count']}**  |  "
        f"Joint (+/-15% box) samples: **{summary['joint_count']}**",
        "",
        "### Golden baseline (full-period backtest, live config)",
        f"- Sharpe: **{_fmt(gm.get('sharpe_ratio'), '.4f')}**  |  "
        f"MaxDD: **{_fmt(gm.get('max_drawdown'), '.4f')}**",
        f"- Annualized: **{_fmt(gm.get('annualized_return'), '.4f')}**  |  "
        f"Total: **{_fmt(gm.get('total_return'), '.4f')}**",
        "",
        "### Plateau scores (higher = flatter = more robust)",
        "\n".join(ps_lines),
        "",
        "### Cliff parameters (spec §10 threshold)",
        "| Signal | Threshold | Consequence |",
        "| --- | --- | --- |",
        "| Cliff parameters (a +/-10% move loses >30% of Sharpe) | any | Flag for "
        "robustness work before further optimization of those parameters |",
        "",
        f"- Cliff parameters: {cliff_line}",
        "",
        "### Joint-perturbation distribution",
        f"- Samples: **{js.get('count')}**  |  min/median/max Sharpe: "
        f"**{_fmt(js.get('min'), '.3f')}** / **{_fmt(js.get('median'), '.3f')}** / "
        f"**{_fmt(js.get('max'), '.3f')}**",
        f"- {percentile_verdict}",
        "",
        "### Per-parameter degradation table",
        _df_to_md(summary["degradation_table"]),
    ]
    return "\n".join(lines) + "\n"


def write_plateau_report(run_dir: Path, strategy_id: str, markdown: str) -> Path:
    """Write report_plateau_<strategy>.md into run_dir (created if missing).

    Deliberately a SEPARATE file from the Phase-1 report_<strategy>.md so the
    plateau run never touches or overwrites the recon/attribution report.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_plateau_{strategy_id}.md"
    out.write_text(markdown)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/report.py tests/unit/audit/test_report.py
git commit -m "feat(audit): plateau report section + standalone report file"
```

---

## Task 9: `run_plateau` driver (glue: campaign -> analysis -> report summary)

**Files:**
- Modify: `jutsu_engine/audit/plateau.py`
- Test: `tests/unit/audit/test_plateau.py`

`run_plateau` is the single entry point the CLI calls: it loads golden params, runs the golden baseline backtest once (via the Phase-1 bridge for the reference Sharpe), runs the campaign, then computes all analysis into the `summary` dict `render_plateau_section` expects. The DB path is exercised by the smoke run; the pure assembly of the summary from a `CampaignResult` + a golden metrics dict is unit-tested with a fake.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/audit/test_plateau.py`:

```python
from jutsu_engine.audit.plateau import summarize_campaign


class TestSummarizeCampaign:
    def test_builds_report_summary_from_rows(self):
        """summarize_campaign turns a CampaignResult + golden metrics into the report summary dict."""
        golden = {"sma_fast": 40, "leverage_scalar": 1.0}
        rows = [
            _oat_row("sma_fast", 32, 0.8), _oat_row("sma_fast", 48, 0.6),
            _oat_row("sma_fast", 36, 0.5), _oat_row("sma_fast", 44, 0.9),
            {"hash": "j1", "kind": "joint", "param": None, "overrides": {},
             "sharpe": 0.4, "max_drawdown": -0.5, "annualized_return": 0.1,
             "total_return": 1.0},
        ]
        res = CampaignResult("v3_5b", 42, samples=rows, rows=rows,
                             campaign_file="x.jsonl", golden=golden)
        summary = summarize_campaign(res, golden_sharpe=1.0,
                                     golden_metrics={"sharpe_ratio": 1.0,
                                                     "max_drawdown": -0.5,
                                                     "annualized_return": 0.2,
                                                     "total_return": 5.0})
        assert summary["strategy_id"] == "v3_5b"
        assert summary["seed"] == 42
        assert summary["oat_count"] == 4 and summary["joint_count"] == 1
        # sma_fast x0.9 (36) retains 0.5 -> >30% loss -> cliff
        assert "sma_fast" in summary["cliffs"]
        assert "sma_fast" in summary["plateau_scores"]
        assert not summary["degradation_table"].empty
        assert summary["joint_stats"]["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'summarize_campaign'`.

- [ ] **Step 3: Write minimal implementation**

Append to `jutsu_engine/audit/plateau.py`:

```python
def summarize_campaign(result: CampaignResult, golden_sharpe: float,
                       golden_metrics: dict) -> dict:
    """Compute the report summary dict from a CampaignResult + golden metrics."""
    rows = result.rows
    oat_rows = [r for r in rows if r.get("param") is not None]
    joint_rows = [r for r in rows if r.get("kind") == "joint"]
    per = perturbable_params(result.golden)
    scores = {name: plateau_score(rows, result.golden, golden_sharpe, name)
              for name in per}
    return {
        "strategy_id": result.strategy_id,
        "seed": result.seed,
        "oat_count": len(oat_rows),
        "joint_count": len(joint_rows),
        "golden_metrics": golden_metrics,
        "plateau_scores": scores,
        "degradation_table": degradation_table(rows, result.golden, golden_sharpe),
        "cliffs": cliff_list(rows, result.golden, golden_sharpe),
        "joint_stats": joint_stats(rows, golden_sharpe),
    }


def run_golden_baseline(strategy_id: str, symbols: list[str],
                        start: date, end: date,
                        initial_capital: str = "10000") -> dict:
    """Run the unperturbed golden config once; return its headline metrics.

    Uses run_one_sample with empty overrides so the reference Sharpe comes from
    the identical code path the campaign uses.
    """
    row = run_one_sample(
        strategy_id,
        {"hash": "golden", "kind": "golden", "param": None, "overrides": {}},
        symbols, start, end, initial_capital)
    return {
        "sharpe_ratio": row["sharpe"],
        "max_drawdown": row["max_drawdown"],
        "annualized_return": row["annualized_return"],
        "total_return": row["total_return"],
    }


def run_plateau(strategy_id: str, run_dir: Path,
                joint_n: int = DEFAULT_JOINT_SAMPLES, seed: int = 0,
                workers: int = 1, oat_only: bool = False,
                params: list[str] | None = None,
                progress=lambda msg: None) -> dict:
    """End-to-end Module 2 for one strategy: baseline -> campaign -> analysis summary.

    Returns the report summary dict (render it with report.render_plateau_section).
    Writes the campaign JSONL under run_dir/<strategy>/campaign_<strategy>.jsonl so
    reruns resume. No per-run CSVs are written to run_dir (each backtest uses a
    throwaway tempdir).
    """
    from jutsu_engine.audit.attribution import _all_symbols

    run_dir = Path(run_dir)
    start, end = ATTRIBUTION_START, date.today()
    symbols = _all_symbols(strategy_id)
    golden = load_golden_params(strategy_id)

    progress(f"[{strategy_id}] golden baseline backtest...")
    golden_metrics = run_golden_baseline(strategy_id, symbols, start, end)
    golden_sharpe = golden_metrics.get("sharpe_ratio") or 0.0

    campaign_file = run_dir / strategy_id / f"campaign_{strategy_id}.jsonl"
    result = run_campaign(
        strategy_id, golden, campaign_file, joint_n=joint_n, seed=seed,
        workers=workers, oat_only=oat_only, params=params,
        symbols=symbols, start=start, end=end, progress=progress)

    return summarize_campaign(result, golden_sharpe, golden_metrics)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Run the FULL audit unit suite (nothing regressed)**

Run: `.venv/bin/python -m pytest tests/unit/audit/ -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all Phase-1 tests + new plateau tests).

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/plateau.py tests/unit/audit/test_plateau.py
git commit -m "feat(audit): run_plateau end-to-end driver (baseline + campaign + summary)"
```

---

## Task 10: CLI subcommand `jutsu audit plateau`

**Files:**
- Modify: `jutsu_engine/cli/commands/audit.py`
- Test: `tests/unit/audit/test_plateau_cli.py` (create)

Follows the existing `_dispatch`/`AuditDBUnavailable` pattern. Adds options: `--strategy`, `--joint-samples N`, `--workers K`, `--oat-only`, `--params` (repeatable, for the smoke run), `--seed`.

- [ ] **Step 1: Write the failing test (CLI wiring via click's test runner, DB-free)**

```python
# tests/unit/audit/test_plateau_cli.py
from unittest import mock

from click.testing import CliRunner

from jutsu_engine.cli.commands.audit import audit


class TestPlateauCLI:
    def test_plateau_calls_run_plateau_and_writes_report(self, tmp_path):
        """`jutsu audit plateau --strategy v3_5b` runs the driver and writes the standalone report."""
        summary = {
            "strategy_id": "v3_5b", "seed": 0, "oat_count": 4, "joint_count": 0,
            "golden_metrics": {"sharpe_ratio": 0.8, "max_drawdown": -0.5,
                               "annualized_return": 0.2, "total_return": 5.0},
            "plateau_scores": {"sma_fast": 0.95}, "cliffs": [],
            "joint_stats": {"count": 0, "golden_percentile": float("nan"),
                            "min": float("nan"), "max": float("nan"),
                            "median": float("nan"), "hist_counts": [], "hist_edges": []},
        }
        import pandas as pd
        summary["degradation_table"] = pd.DataFrame([{"param": "sma_fast",
            "override_value": 32, "sharpe": 0.78, "retained_sharpe": 0.96,
            "max_drawdown": -0.5, "annualized_return": 0.2}])

        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        return_value=summary) as m:
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b",
                                        "--oat-only", "--params", "sma_fast"])
        assert res.exit_code == 0, res.output
        m.assert_called_once()
        assert (tmp_path / "report_plateau_v3_5b.md").exists()
        # Phase-1 report path must NOT be created by the plateau command
        assert not (tmp_path / "report_v3_5b.md").exists()

    def test_plateau_db_unavailable_degrades_gracefully(self, tmp_path):
        """A DB-unavailable driver surfaces a clean abort, not a traceback."""
        from jutsu_engine.audit.db import AuditDBUnavailable
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        side_effect=AuditDBUnavailable("Missing DB config env vars")):
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b"])
        assert res.exit_code != 0
        assert "Database unavailable" in res.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `SystemExit`/no such command `plateau` (`res.exit_code != 0` for the wrong reason — "No such command").

- [ ] **Step 3: Write minimal implementation**

Add to `jutsu_engine/cli/commands/audit.py`. First add the import near the other audit imports (top of file):

```python
from jutsu_engine.audit.report import (
    render_report, write_report,
    render_plateau_section, write_plateau_report,
)
```

(Replace the existing `from jutsu_engine.audit.report import render_report, write_report` line with the combined import above.)

Then append the subcommand at the end of the file:

```python
@audit.command("plateau")
@_STRATEGY_OPTION
@click.option("--joint-samples", "joint_samples", type=int, default=200,
              show_default=True, help="Number of joint +/-15% random samples.")
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel worker processes (1 = serial; each worker builds its "
                   "own BacktestRunner).")
@click.option("--oat-only", is_flag=True, default=False,
              help="Run only one-at-a-time perturbations (skip joint samples).")
@click.option("--params", multiple=True, default=(),
              help="Restrict OAT perturbations to these parameter name(s). "
                   "Repeatable; used for the smoke campaign.")
@click.option("--seed", type=int, default=42, show_default=True,
              help="RNG seed for the joint samples (recorded in the report).")
def plateau_cmd(strategy, joint_samples, workers, oat_only, params, seed):
    """Module 2: parameter plateau map (perturbation campaign + robustness report)."""
    from jutsu_engine.audit import plateau as plateau_mod

    run_dir = report_output_dir()
    param_list = list(params) or None
    try:
        for sid in _strategy_ids(strategy):
            click.echo(f"[{sid}] plateau campaign "
                       f"(joint={0 if oat_only else joint_samples}, workers={workers}, "
                       f"seed={seed})...")
            summary = plateau_mod.run_plateau(
                sid, run_dir, joint_n=joint_samples, seed=seed, workers=workers,
                oat_only=oat_only, params=param_list,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
            md = render_plateau_section(summary)
            out = write_plateau_report(run_dir, sid, md)
            click.echo(click.style(f"  report: {out}", fg="green"))
    except AuditDBUnavailable as e:
        click.echo(click.style(f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.",
            fg="yellow"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Plateau audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ Plateau audit failed: {e}", fg="red"), err=True)
        raise click.Abort()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_plateau_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Verify the command is wired into the real CLI**

Run: `.venv/bin/python -c "from jutsu_engine.cli.commands.audit import audit; print([c for c in audit.commands])"`
Expected output includes: `plateau` (alongside `live-recon`, `attribution`, `all`).

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/cli/commands/audit.py tests/unit/audit/test_plateau_cli.py
git commit -m "feat(audit): jutsu audit plateau CLI subcommand"
```

---

## Task 11: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the entry at the TOP of the file (above the most recent entry)**

Insert this block as the new first entry (repo format: `#### **Type: Title** (YYYY-MM-DD)`):

```markdown
#### **Feature: Baseline audit Phase 2 — parameter plateau map (Module 2)** (2026-07-06)

Added `jutsu_engine/audit/plateau.py` and the `jutsu audit plateau` CLI subcommand
implementing Module 2 of the baseline audit (spec §6:
`docs/superpowers/specs/2026-07-06-baseline-audit-design.md`). Strictly READ-ONLY
against the DB; reuses `BacktestRunner`/`LiveStrategyRunner` unchanged. No live,
scheduler, or strategy-config changes.

- **Perturbation-set generation (pure, seeded):** one-at-a-time (each perturbable
  numeric parameter at x0.8/x0.9/x1.1/x1.2, integers rounded + deduped, windows
  clamped >=5, periods >=2, negative thresholds keep sign) and N joint uniform
  samples (default 200) in a +/-15% box (seeded `random.Random`, seed recorded in
  output). Perturbable = numeric non-bool strategy params from the live YAML,
  excluding symbols/strings, booleans, and execution/infra keys (22 params for
  v3_5b; derived per-strategy from the YAML).
- **Campaign runner:** each sample = one full-period backtest (2010-02 -> present)
  via a param-override extension of the Phase-1 bridge (`build_overridden_strategy`,
  replicating `LiveStrategyRunner`'s float->Decimal conversion). Mandatory
  checkpoint/resume: each result appended as a JSONL row keyed by params-hash;
  reruns skip completed hashes. Opt-in parallelism via `ProcessPoolExecutor`
  (`--workers`, default 1 serial; each worker builds its own runner). Reduced
  output: each backtest writes CSVs to a throwaway tempdir (no per-run regime/
  portfolio CSVs in the report dir).
- **Pure analysis (DB-free, unit-tested):** plateau score (mean retained Sharpe
  fraction at +/-20%), per-param degradation table, cliff list (params losing
  >30% Sharpe at +/-10%), joint-sample stats (histogram + golden Sharpe percentile).
- **Report:** `render_plateau_section` + `write_plateau_report` -> NEW
  `report_plateau_<strategy>.md` (does not touch the Phase-1 report); embeds seed,
  sample counts, golden baseline, plateau/cliff tables, percentile verdict, and the
  spec §10 cliff-threshold row.
- **CLI:** `jutsu audit plateau --strategy v3_5b|v3_5d [--joint-samples N]
  [--workers K] [--oat-only] [--params NAME ...] [--seed S]`; graceful
  `AuditDBUnavailable` degrade.
- Compute note: ~290 backtests/strategy default (~2-3 min each) => ~10-15h serial;
  hence checkpoint/resume + workers. The overnight campaign is a post-merge
  operational step, not part of this change; a 4-backtest smoke campaign
  (`--oat-only --params sma_fast`) validated the pipeline end-to-end.
- Tests: <N> new unit tests (perturbation generation, analysis math, checkpoint
  I/O, campaign orchestration via injected run_fn, report rendering, CLI wiring),
  all DB-free.
```

(Replace `<N>` with the actual new-test count reported by the final `pytest tests/unit/audit/ -q` run.)

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): baseline audit Phase 2 plateau map"
```

---

## Task 12: LOGBOOK EXP-003 skeleton + index row

**Files:**
- Modify: `docs/experiments/LOGBOOK.md`

Match the existing entry format exactly (read EXP-001/EXP-002 first). Results are marked "campaign pending".

- [ ] **Step 1: Add the index row**

In the `## Index` table (after the EXP-002 row), add:

```markdown
| EXP-003 | 2026-07-06 | How robust is the golden config to small parameter perturbations (plateau vs cliff)? | Campaign pending — filled in after the overnight run |
```

- [ ] **Step 2: Append the EXP-003 skeleton at the end of the file**

```markdown
---

## EXP-003 — Baseline audit Phase 2: parameter plateau map (2026-07-06)

**Question.** Does the golden config sit on a robustness *plateau* (small parameter
perturbations barely move Sharpe) or on a *cliff* (a +/-10% move on some parameter
collapses Sharpe)? Where in its own +/-15% neighborhood distribution does the
golden Sharpe sit — is it an isolated peak (right-tail = overfit red flag) or in
the body?

**Why.** EXP-001 established the honest full-period baseline (Sharpe ~0.8, not the
in-sample ~2.8) and pointed improvement effort at regime-transition quality over
parameter micro-tuning. Module 2 quantifies *how fragile* the golden parameters
are: cliff parameters are the ones most likely fit to noise and are flagged for
robustness work (spec §6, §10). Decision framework: spec
`docs/superpowers/specs/2026-07-06-baseline-audit-design.md` §6/§10.

**Method.** Built `jutsu_engine/audit/plateau.py` (perturbation-set generation +
checkpoint/resume campaign runner + pure analysis) and `jutsu audit plateau`.
- Perturbable params: 22 numeric non-bool strategy params from the live YAML
  (symbols/booleans/execution excluded), derived per strategy.
- One-at-a-time: each param at x0.8/x0.9/x1.1/x1.2 (integers rounded/deduped,
  windows >=5, periods >=2, negative thresholds keep sign).
- Joint: 200 seeded uniform samples in a +/-15% box (seed 42, recorded in report).
- Each sample = one full-period (2010-02 -> 2026-07) `BacktestRunner` run via
  `build_overridden_strategy` (Phase-1 bridge + param overrides, same float->Decimal
  conventions as `LiveStrategyRunner`). Results checkpointed to JSONL (resume by
  params-hash); CSVs to a throwaway tempdir (reduced output).
- Command (overnight): `jutsu audit plateau --strategy v3_5b --workers 4`
  then `--strategy v3_5d`. Smoke validation:
  `jutsu audit plateau --strategy v3_5b --oat-only --params sma_fast`.

**Results.** _Campaign pending — filled in after the overnight run._
(Expected fields once run: per-parameter plateau scores; cliff list; joint-sample
Sharpe histogram; golden Sharpe percentile within the joint distribution; the
plateau-vs-cliff verdict per strategy.)

**Verdict / decisions.** _Pending campaign results._ (Interpretation contract:
cliff parameters -> flag for robustness work before further optimization of those
parameters, spec §10; a golden Sharpe far in the right tail of its own neighborhood
-> treat the config as a fragile local peak.)

**Artifacts.** Code on `feature/audit-phase2-plateau`; reports (once run)
`claudedocs/audit/2026-07-06/report_plateau_v3_5{b,d}.md`; campaign JSONL
`claudedocs/audit/2026-07-06/v3_5{b,d}/campaign_v3_5{b,d}.jsonl`.

**Follow-ups spawned.** _TBD after results._ (Anticipated: Module 1 WFO stability,
Module 3 DSR/PBO per spec §14.)
```

- [ ] **Step 3: Commit**

```bash
git add docs/experiments/LOGBOOK.md
git commit -m "docs(logbook): EXP-003 skeleton for plateau map (campaign pending)"
```

---

## Task 13: Final validation — full test suite + SMOKE campaign

**Files:** none (validation only).

- [ ] **Step 1: Run the full audit unit suite**

Run: `.venv/bin/python -m pytest tests/unit/audit/ -p no:cacheprovider -o addopts="" -q`
Expected: PASS. Record the count of NEW plateau/report/CLI tests and update `<N>` in the CHANGELOG entry (Task 11) if still a placeholder, then amend:

```bash
git add CHANGELOG.md
git commit --amend --no-edit
```

(Only amend if the CHANGELOG commit is the most recent; otherwise make a tiny follow-up commit `docs(changelog): fill plateau test count`.)

- [ ] **Step 2: SMOKE campaign against the real DB (proves the end-to-end pipeline)**

This runs ONE real mini-campaign: golden baseline + the 4 `sma_fast` OAT backtests + report. It touches the DB (read-only) and takes ~10-15 min (5 backtests).

Run (console script — installed as `jutsu = jutsu_engine.cli.main:cli`, verified in `pyproject.toml`/`setup.py`; the `audit` group is registered via `cli.add_command(audit_cmd, name='audit')` in `jutsu_engine/cli/main.py:2056-2057`):
```bash
.venv/bin/jutsu audit plateau --strategy v3_5b --oat-only --params sma_fast --workers 1
```

Fallback if the console script is not on PATH (invoke the `cli` group object directly):
```bash
.venv/bin/python -c "from jutsu_engine.cli.main import cli; cli()" audit plateau --strategy v3_5b --oat-only --params sma_fast --workers 1
```

Expected (DB available):
- Console shows `[v3_5b] plateau campaign (joint=0, workers=1, seed=42)...`, a golden-baseline line, `5 samples, 0 already done, 5 to run` (1 golden is separate; the 4 OAT samples are the campaign — expect `4 samples ... 4 to run`), per-sample `sharpe=...` lines, and `report: .../report_plateau_v3_5b.md`.
- File `claudedocs/audit/<today>/report_plateau_v3_5b.md` exists and contains the plateau section (seed 42, sma_fast degradation rows).
- File `claudedocs/audit/<today>/v3_5b/campaign_v3_5b.jsonl` exists with 4 JSONL rows.
- `claudedocs/audit/<today>/report_v3_5b.md` (Phase-1) is NOT created/modified by this run.

- [ ] **Step 3: Prove resume works**

Re-run the exact same command.
Expected: `4 samples, 4 already done, 0 to run` — no backtests re-run; the report is regenerated from the existing JSONL.

- [ ] **Step 4: Prove graceful degradation when the DB is unavailable**

Run (unset DB env to force a DB error inside `run_one_sample` -> `BacktestRunner` engine, or if the DB is simply unreachable from this machine):
```bash
env -u POSTGRES_HOST .venv/bin/jutsu audit plateau --strategy v3_5b --oat-only --params sma_fast
```
Expected: a clean `✗ ...` message and non-zero exit — no raw traceback. (If `BacktestRunner` raises a generic DB error rather than `AuditDBUnavailable`, it is caught by the generic handler and printed as `✗ Plateau audit failed: ...` — still graceful. Note this in the smoke output; the CLI degrades either way.)

- [ ] **Step 5: Clean up smoke artifacts (do NOT commit generated reports/campaign files)**

The report and campaign JSONL are run artifacts, not source. Confirm they are not staged:

Run: `git status --porcelain claudedocs/`
Expected: the `claudedocs/audit/<today>/` files show as untracked and are NOT added in any commit. Leave them on disk for inspection but never `git add` them. (The real overnight campaign, run post-merge, produces the committed-to-`claudedocs` reports per the operational step.)

- [ ] **Step 6: Final commit check**

Run: `git log --oneline feature/audit-phase2-plateau -13`
Expected: the 12 feature/docs commits from Tasks 1-12 (plus any amend). No `claudedocs/` artifacts committed. Do NOT push or open a PR (out of scope).

---

## Self-Review (completed by plan author)

**Spec coverage (§6 + §10-12):**
- OAT ±10%/±20% multiplicative, integer rounding, sign preservation, validity floors → Tasks 2. ✓
- Joint 200 seeded ±15% samples, seed recorded → Task 3. ✓
- Perturbable = numeric non-bool, excluding symbols/bools/execution → Task 1 (`perturbable_params` + `PERTURBABLE_EXCLUDE`); exact 22-param list enumerated above. ✓
- Each sample = full-period BacktestRunner via param-override bridge → Tasks 5-6. ✓
- Mandatory checkpoint/resume (JSONL by hash) → Task 6. ✓
- Opt-in parallelism, per-worker runner (multiprocessing verified safe; workers default 1) → Task 7. ✓
- Reduced output (throwaway tempdir per run) → Task 6 `run_one_sample`. ✓
- Pure analysis: plateau_score, degradation_table, cliff_list, joint_stats → Task 4. ✓
- Report: `render_plateau_section` + standalone `report_plateau_<strategy>.md`, embeds seed/counts/baseline/tables/percentile/spec-§10 row → Task 8. ✓
- CLI `jutsu audit plateau` with `--strategy/--joint-samples/--workers/--oat-only/--params/--seed`, graceful AuditDBUnavailable → Task 10. ✓
- CHANGELOG + LOGBOOK EXP-003 skeleton + index row → Tasks 11-12. ✓
- Smoke campaign with `--params sma_fast` + graceful-degrade proof → Task 13. ✓
- Compute-duration estimate stated → Context section + CHANGELOG. ✓

**Type consistency:** result-row schema (`hash/kind/param/overrides/sharpe/max_drawdown/annualized_return/total_return`) is defined once (`_RESULT_KEYS`, Task 6) and used identically in `run_one_sample`, `append_result`, `summarize_campaign`, and every test helper (`_oat_row`). `plateau_score`/`cliff_list`/`degradation_table`/`joint_stats` signatures match their call sites in `summarize_campaign`. `CampaignResult` fields match `run_campaign`'s return and `summarize_campaign`'s reads. `DECIMAL_PARAMS` is guarded against drift from the live source (Task 5, Step 5). `render_plateau_section`'s summary keys match `summarize_campaign`'s output.

**Placeholder scan:** every code step contains complete code; no TBD/TODO in implementation. The only literal placeholder is `<N>` (test count) in the CHANGELOG, explicitly resolved in Task 13 Step 1.
