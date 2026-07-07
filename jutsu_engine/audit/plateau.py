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

import hashlib
import importlib
import json
import math
import os
import random
import shutil
import tempfile
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

import numpy as np
import pandas as pd

from jutsu_engine.audit.config import ATTRIBUTION_START, resolve_strategy

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


# Spec §6: a param losing >30% of Sharpe at a +/-10% move is a "cliff".
CLIFF_LOSS_FRACTION: float = 0.30
# Steps counted as "+/-20%" for plateau_score (multiplicative x0.8 / x1.2).
_PLATEAU_MULTIPLIERS = (0.8, 1.2)
_TEN_PCT_MULTIPLIERS = (0.9, 1.1)


def _valid_sharpe(r: dict) -> bool:
    """True when the row carries a finite numeric sharpe (errored runs don't)."""
    s = r.get("sharpe")
    return isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s)


def _rows_for_param(rows: list[dict], param: str) -> list[dict]:
    return [r for r in rows if r.get("param") == param]


def _override_matches_multiplier(row: dict, golden: dict, param: str,
                                 mult: float) -> bool:
    """True if this OAT row's override for `param` equals golden*mult after validity.

    Uses golden.get(param) so callers with partial golden dicts don't KeyError.
    """
    gval = golden.get(param)
    if gval is None:
        return False
    want = _apply_validity(param, gval * mult, gval)
    return row["overrides"].get(param) == want


def plateau_score(rows: list[dict], golden: dict, golden_sharpe: float,
                  param: str) -> dict:
    """Retained Sharpe fractions at +/-20% (x0.8, x1.2) for one parameter.

    Returns a dict with keys:
      - ``mean_retained``: mean of (perturbed_sharpe / golden_sharpe) over the
        two +/-20% steps.
      - ``worst_retained``: min of the same fractions — the conservative signal.
        Two-sided mean can mask a one-sided collapse (e.g. sides 1.25 and 0.125
        average to 0.688, hiding that one direction is nearly flat). Use
        ``worst_retained`` as the gate; ``cliff_list`` adds per-step granularity.
      - ``n_rows``: number of valid +/-20% rows used.

    Returns ``{"mean_retained": nan, "worst_retained": nan, "n_rows": 0}`` when
    no +/-20% rows with finite Sharpe were collected for this parameter.

    Note: retained-fraction semantics are fragile when golden Sharpe is near
    zero/sub-1 (ours is ~0.8): a negative perturbed Sharpe yields retained < 0,
    which is directionally correct for cliff detection but not a clean
    "percentage".  Rows whose Sharpe is None or NaN are excluded before
    computing fractions.
    """
    prows = _rows_for_param(rows, param)
    fracs = []
    for mult in _PLATEAU_MULTIPLIERS:
        for r in prows:
            if _override_matches_multiplier(r, golden, param, mult):
                if not _valid_sharpe(r):
                    continue
                if golden_sharpe not in (0, 0.0):
                    fracs.append(r["sharpe"] / golden_sharpe)
    if not fracs:
        return {"mean_retained": float("nan"), "worst_retained": float("nan"),
                "n_rows": 0}
    return {
        "mean_retained": float(np.mean(fracs)),
        "worst_retained": float(np.min(fracs)),
        "n_rows": len(fracs),
    }


def degradation_table(rows: list[dict], golden: dict,
                      golden_sharpe: float) -> pd.DataFrame:
    """Per-param, per-step degradation: retained Sharpe fraction for each OAT row.

    Columns: param, override_value, sharpe, retained_sharpe, max_drawdown,
    annualized_return. Only OAT rows (param is not None) are included.
    Rows whose Sharpe is None or NaN (errored runs) are silently skipped so
    division by golden_sharpe never operates on bad values.
    """
    recs = []
    for r in rows:
        p = r.get("param")
        if p is None:
            continue
        if not _valid_sharpe(r):
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
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    return df.sort_values(["param", "override_value"]).reset_index(drop=True)


def cliff_list(rows: list[dict], golden: dict, golden_sharpe: float) -> list[str]:
    """Params whose +/-10% (x0.9 or x1.1) move loses > CLIFF_LOSS_FRACTION of Sharpe.

    Rows whose Sharpe is None or NaN (errored runs) are excluded before computing
    the retained fraction so division is never attempted on bad values.

    Note: retained-fraction semantics are fragile when golden Sharpe is near
    zero/sub-1 (ours is ~0.8): a negative perturbed Sharpe yields retained < 0,
    which is directionally correct for cliff detection but not a clean
    "percentage".
    """
    cliffs = set()
    for param, gval in perturbable_params(golden).items():
        for mult in _TEN_PCT_MULTIPLIERS:
            for r in _rows_for_param(rows, param):
                if _override_matches_multiplier(r, golden, param, mult):
                    if golden_sharpe in (0, 0.0):
                        continue
                    if not _valid_sharpe(r):
                        continue
                    retained = r["sharpe"] / golden_sharpe
                    if retained < (1.0 - CLIFF_LOSS_FRACTION):
                        cliffs.add(param)
    return sorted(cliffs)


def joint_stats(rows: list[dict], golden_sharpe: float, bins: int = 20) -> dict:
    """Histogram of joint-sample Sharpe + golden config's percentile within it.

    golden_percentile = fraction of joint samples with Sharpe strictly below the
    golden Sharpe, as a percentage. NaN percentile when no valid joint rows exist.

    ``count`` is the number of valid (finite Sharpe) rows used; ``errored`` is
    the number of joint rows that were excluded due to None/NaN Sharpe — a
    non-zero errored count means the campaign had failures that would silently
    skew the distribution if not excluded.
    """
    joint_rows = [r for r in rows if r.get("kind") == "joint"]
    valid_rows = [r for r in joint_rows if _valid_sharpe(r)]
    errored = len(joint_rows) - len(valid_rows)
    sharpes = [r["sharpe"] for r in valid_rows]
    if not sharpes:
        return {"count": 0, "errored": errored, "golden_percentile": float("nan"),
                "hist_counts": [], "hist_edges": [],
                "min": float("nan"), "max": float("nan"), "median": float("nan")}
    arr = np.asarray(sharpes, dtype=float)
    below = float(np.sum(arr < golden_sharpe))
    pct = below / len(arr) * 100.0
    counts, edges = np.histogram(arr, bins=bins)
    return {
        "count": len(arr),
        "errored": errored,
        "golden_percentile": pct,
        "hist_counts": counts.tolist(),
        "hist_edges": edges.tolist(),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "median": float(np.median(arr)),
    }


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


# Keys written to (and read back from) the campaign JSONL. `error` is included
# so a failed run's diagnostic string survives the round-trip; it is None for
# successful rows (the analysis layer keys off `sharpe`, not `error`).
_RESULT_KEYS = ("hash", "kind", "param", "overrides",
                "sharpe", "max_drawdown", "annualized_return", "total_return",
                "error")


def build_campaign_samples(golden: dict, joint_n: int = DEFAULT_JOINT_SAMPLES,
                           seed: int = 0, oat_only: bool = False,
                           params: list[str] | None = None) -> list[dict]:
    """Assemble the full perturbation set: OAT (optionally filtered) + joint.

    `params` restricts the OAT set to the named parameters (used by the smoke
    run). Duplicate hashes across OAT/joint are dropped, first occurrence wins.

    The golden (unperturbed) baseline is NOT part of this list: it is run
    separately by run_golden_baseline (Task 9) so its Sharpe is available as the
    plateau reference before/independently of the perturbation campaign.
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
    """Set of params-hashes already present in a campaign JSONL file (empty if missing).

    Tolerates a truncated/corrupt final line: a process killed mid-write leaves a
    partial JSON fragment, which is silently skipped so a crash never poisons
    resume. Only well-formed rows carrying a `hash` are counted.
    """
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


def _ends_with_newline(path: Path) -> bool:
    """True if the file's final byte is a newline (or the file is empty/absent)."""
    if not path.exists() or path.stat().st_size == 0:
        return True
    with open(path, "rb") as f:
        f.seek(-1, 2)  # last byte
        return f.read(1) == b"\n"


def append_result(path: Path, row: dict) -> None:
    """Append one result row as a JSONL line (created if missing). fsynced to disk.

    fsyncing per line makes resume crash-safe: a completed backtest is durable
    the moment its row is written, surviving both process crashes and power loss,
    so a later failure loses at most the in-flight runs, never a finished one.

    If a prior process was killed mid-write and left a partial line with no
    trailing newline, a leading newline is inserted before the new row so the new
    (good) row is never concatenated onto — and corrupted by — the dangling
    fragment. The fragment itself is still dropped on read by load_completed_hashes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {k: row.get(k) for k in _RESULT_KEYS}
    prefix = "" if _ends_with_newline(path) else "\n"
    with open(path, "a") as f:
        f.write(prefix + json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run_one_sample(strategy_id: str, sample: dict, symbols: list[str],
                   start: date, end: date,
                   initial_capital: str = "10000") -> dict:
    """Run ONE full-period backtest for a perturbation sample; return a result row.

    Picklable (plain args only) so it can run inside a ProcessPoolExecutor worker.
    Writes ALL CSVs to a throwaway tempdir that is removed afterward, so no per-run
    regime/portfolio CSVs land in the report directory (spec §6 reduced-output).
    Reuses BacktestRunner exactly as run_attribution does (attribution.py:234-251).

    A backtest that raises does NOT crash the campaign: the error is recorded
    LOUDLY as a row with sharpe=None and an `error` string. The analysis layer's
    _valid_sharpe guard then excludes it and joint_stats counts it as errored,
    rather than silently skewing the distribution.
    """
    from jutsu_engine.application.backtest_runner import BacktestRunner

    config = {
        "symbols": symbols,
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": Decimal(str(initial_capital)),
    }
    tmpdir = tempfile.mkdtemp(prefix="plateau_")
    error = None
    results: dict = {}
    try:
        strategy = build_overridden_strategy(strategy_id, sample["overrides"])
        runner = BacktestRunner(config)
        results = runner.run(strategy, output_dir=tmpdir)
    except Exception as exc:  # noqa: BLE001 — record loudly, never crash the campaign
        error = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "hash": sample["hash"],
        "kind": sample["kind"],
        "param": sample["param"],
        "overrides": sample["overrides"],
        "sharpe": results.get("sharpe_ratio") if error is None else None,
        "max_drawdown": results.get("max_drawdown") if error is None else None,
        "annualized_return": results.get("annualized_return") if error is None else None,
        "total_return": results.get("total_return") if error is None else None,
        "error": error,
    }


def default_workers() -> int:
    """Default worker count: min(4, cpu_count). Parallelism is opt-in via --workers."""
    return min(4, os.cpu_count() or 1)


# Consecutive errored-row limit before the campaign aborts. A DB outage (or any
# systemic failure) makes EVERY sample error out; without this breaker a run
# would burn through all 400+ samples in minutes, checkpointing them all as
# errored rows that resume would then treat as "completed" and never retry.
DEFAULT_MAX_CONSECUTIVE_ERRORS: int = 10


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
    """Load all result rows from a campaign JSONL (for resume + report).

    Tolerates a truncated/corrupt final line (crash mid-write): malformed lines
    are silently skipped, mirroring load_completed_hashes.
    """
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


def _is_error_row(row: dict) -> bool:
    """True if a result row represents a failed run (no finite Sharpe).

    A row is an error when it carries a non-null `error` string OR its `sharpe`
    is not a finite number — either way the analysis layer excludes it, and the
    circuit breaker counts it toward the consecutive-error limit.
    """
    if row.get("error") is not None:
        return True
    return not _valid_sharpe(row)


def run_campaign(strategy_id: str, golden: dict, campaign_file: Path,
                 joint_n: int = DEFAULT_JOINT_SAMPLES, seed: int = 0,
                 workers: int = 1, oat_only: bool = False,
                 params: list[str] | None = None,
                 run_fn=run_one_sample, symbols: list[str] | None = None,
                 start: date | None = None, end: date | None = None,
                 initial_capital: str = "10000",
                 max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
                 progress=lambda msg: None) -> CampaignResult:
    """Run (or resume) a perturbation campaign, checkpointing each result to JSONL.

    Behaviour:
      - Samples already present in `campaign_file` (by hash) are skipped (resume),
        in BOTH the serial and parallel paths, before any work is submitted.
      - workers <= 1 runs serially; workers > 1 uses a ProcessPoolExecutor (each
        worker builds its own BacktestRunner + strategy — verified safe).
      - Every completed sample is appended immediately so a crash loses at most
        the in-flight backtests, never a finished one.

    Circuit breaker (systemic-failure guard):
      - If `max_consecutive_errors` samples come back as errored rows in a row
        (e.g. the market-data DB is down), the campaign ABORTS with a RuntimeError
        instead of quietly checkpointing every remaining sample as an error. A
        single success resets the counter. The breaker applies to both paths; in
        the parallel path it stops submitting new work and cancels pending futures,
        while still writing every already-completed row before raising. Note:
        errored rows that DID get checkpointed are treated as completed on resume
        (they are not retried) — investigate and delete them before rerunning.

    SINGLE-WRITER INVARIANT (do not move into workers):
      - ALL append_result calls happen here, in the parent/orchestrator process.
        Workers (and the injected run_fn) ONLY compute and RETURN a row; they must
        never write the JSONL themselves. A single writer is what makes the
        concurrent parallel path's appends safe (no interleaved partial lines from
        competing processes). Moving append_result into a worker would break this.

    run_fn injectability & the spawn boundary:
      - run_fn is injectable so the orchestration logic is unit-testable without a
        DB. In the parallel path (workers > 1) the callable is submitted across a
        process boundary, which on macOS uses `spawn` and therefore requires a
        PICKLABLE callable. The default `run_one_sample` is module-level and
        picklable; a test/closure run_fn is only spawn-safe if it too is a
        module-level function. Non-picklable closures must use workers == 1.
    """
    campaign_file = Path(campaign_file)
    start = start or ATTRIBUTION_START
    end = end or date.today()
    samples = build_campaign_samples(golden, joint_n=joint_n, seed=seed,
                                     oat_only=oat_only, params=params)
    done = load_completed_hashes(campaign_file)
    todo = [s for s in samples if s["hash"] not in done]
    progress(f"{len(samples)} samples, {len(done)} already done, "
             f"{len(todo)} to run")

    breaker_msg = (
        f"aborting: {max_consecutive_errors} consecutive errored runs — "
        "systemic failure (DB down?). Completed-as-error rows are checkpointed "
        "and will NOT be retried on resume; investigate (and delete them) before "
        "rerunning."
    )

    if workers <= 1:
        consecutive_errors = 0
        for i, sample in enumerate(todo, 1):
            row = run_fn(strategy_id, sample, symbols or [], start, end,
                         initial_capital)
            # SINGLE-WRITER INVARIANT: the parent appends; run_fn never writes.
            append_result(campaign_file, row)
            if _is_error_row(row):
                consecutive_errors += 1
            else:
                consecutive_errors = 0
            progress(f"[{i}/{len(todo)}] {sample['kind']} "
                     f"{sample['param'] or 'joint'} sharpe={row.get('sharpe')}")
            if consecutive_errors >= max_consecutive_errors:
                raise RuntimeError(breaker_msg)
    else:
        _run_parallel(strategy_id, todo, campaign_file, run_fn, symbols or [],
                      start, end, initial_capital, workers,
                      max_consecutive_errors, breaker_msg, progress)

    rows = _reload_rows(campaign_file)
    return CampaignResult(strategy_id=strategy_id, seed=seed, samples=samples,
                          rows=rows, campaign_file=str(campaign_file),
                          golden=golden)


def summarize_campaign(result: CampaignResult, golden_sharpe: float,
                       golden_metrics: dict) -> dict:
    """Compute the report summary dict from a CampaignResult + golden metrics.

    ``plateau_scores`` values are dicts (``mean_retained``, ``worst_retained``,
    ``n_rows``) — not plain floats — because ``plateau_score()`` now returns a dict
    so the report can show both columns and sort by the conservative ``worst_retained``
    gate.  ``joint_stats`` carries an ``errored`` key from Task 8's adaptation.
    """
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

    Raises RuntimeError if the baseline backtest itself errors (sharpe is None) —
    there is no reference Sharpe without a working baseline, so no retained
    fractions can be computed and the plateau analysis is meaningless.
    """
    row = run_one_sample(
        strategy_id,
        {"hash": "golden", "kind": "golden", "param": None, "overrides": {}},
        symbols, start, end, initial_capital)
    if row.get("sharpe") is None:
        err = row.get("error", "unknown error")
        raise RuntimeError(
            f"[{strategy_id}] golden baseline backtest failed — no reference Sharpe "
            f"available; retained fractions cannot be computed. "
            f"Fix the golden config before running the plateau campaign. "
            f"Backtest error: {err}"
        )
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

    Raises RuntimeError if the golden baseline backtest itself fails — no baseline
    means no retained fractions means no analysis (see run_golden_baseline).
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


def _run_parallel(strategy_id: str, todo: list[dict], campaign_file: Path,
                  run_fn, symbols: list[str], start: date, end: date,
                  initial_capital: str, workers: int,
                  max_consecutive_errors: int, breaker_msg: str,
                  progress) -> None:
    """Parallel campaign execution with resume + circuit breaker (parent-only writes).

    Uses an explicit wait(FIRST_COMPLETED) loop rather than as_completed so that
    when the breaker trips we can stop submitting and cancel not-yet-started
    futures — every already-completed row in the current batch is still appended
    by the parent before the RuntimeError propagates (single-writer invariant
    preserved).

    Abort / ordering semantics (for operators and callers):

    (a) When the breaker trips, up to `workers` still-RUNNING backtests cannot be
        cancelled — ProcessPoolExecutor.shutdown() (implicit at context-manager
        exit) waits for them to finish, but their results are silently discarded
        and those samples are treated as un-run (they will be re-submitted on
        resume, since their rows were never checkpointed).

    (b) "Consecutive" errors are counted in COMPLETION order in this path
        (submission order in the serial path). Under systemic failure every run
        errors, so the ordering distinction vanishes and the breaker trips after
        exactly max_consecutive_errors completions. Under flaky failures a
        completion-order run of N consecutive errors is itself a meaningful signal
        worth aborting on, even if the submission order would look interleaved.
    """
    consecutive_errors = 0
    done_count = 0
    total = len(todo)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        # run_fn is submitted directly (picklable module-level callable, plain-dict
        # args) so it is macOS-spawn-safe. append_result is NOT submitted — the
        # parent is the sole writer.
        pending = {
            ex.submit(run_fn, strategy_id, s, symbols, start, end,
                      initial_capital)
            for s in todo
        }
        aborted = False
        while pending and not aborted:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            # Process every future in this batch before checking aborted.
            # This ensures all rows that are already complete are checkpointed
            # even when the breaker trips mid-batch — contradicting the docstring
            # claim would otherwise silently discard completed work.
            for fut in finished:
                row = fut.result()
                # SINGLE-WRITER INVARIANT: the parent appends; workers never write.
                append_result(campaign_file, row)
                done_count += 1
                if _is_error_row(row):
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        aborted = True
                        # Do NOT break: continue draining the rest of `finished`
                        # so every completed row in this batch is checkpointed.
                else:
                    consecutive_errors = 0
                progress(f"[{done_count}/{total}] done "
                         f"sharpe={row.get('sharpe')}")
        if aborted:
            # Cancel not-yet-started futures; running futures cannot be stopped
            # (see docstring note (a) above).
            for fut in pending:
                fut.cancel()
            raise RuntimeError(breaker_msg)
