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
#
# VERIFIED against grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml
# header (lines 58-84): axes and values match exactly. Total = 3^5 = 243. ✓
#
# NOTE: the live golden config's sma_slow=140 is OUTSIDE this historical grid
# [180,200,220]. The live value was tuned in a later phase. For DSR, the in-grid
# anchor uses sma_slow=200 (closest center value). This mismatch is documented in
# _golden_anchor_hash() (defined in this module, see below) and in the DSR report
# (report.py:render_dsr_section, written by write_dsr_report).
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


def enumerate_golden_grid(limit: int | None = None) -> list[dict]:
    """Expand GOLDEN_GRID_AXES into 243 combos (or the first `limit` for smoke runs).

    Each combo: {"combo_id": int, "overrides": {axis: value}, "hash": str}.
    combo_id is the enumeration index 0..242 (deterministic: itertools.product over
    the axes in GOLDEN_GRID_AXES insertion order). `limit` truncates to the first N
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


# ─── Task 7: Returns-campaign worker + JSONL persistence ──────────────────────

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


# ─── Task 8: Returns-campaign runner (resume, circuit breaker, workers) ───────

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


# ─── Task 9: Returns-matrix assembly + cross-trial variance V ─────────────────

import numpy as np
import pandas as pd


# Threshold: a combo with more than 0.1% of its cells zero-filled (i.e., its date
# coverage has gaps vs the union) is dropped. A typical combo missing 4 of 4,100
# dates = 0.098% (under threshold). Combos with material gaps (e.g., a crash mid-run
# whose CSV was truncated) are dropped with a LOUD warning.
_MAX_FILLED_FRACTION = 0.001   # 0.1%


def build_returns_matrix(rows: list[dict]):
    """Assemble a (T, N) returns matrix from campaign rows, aligned on date union.

    Only non-error rows (returns present) contribute a column. Each combo's series
    is reindexed onto the sorted union of all dates; missing dates are filled 0.0
    (a combo produces no return on a day it has no bar — treated as flat, not NaN,
    so every column shares one T for CSCV block splitting).

    CONTRACT: the returned matrix contains NO NaN values. Error rows are dropped as
    WHOLE COLUMNS before assembly. This satisfies compute_pbo's fail-fast contract
    ("matrix contains NaN — drop errored combos before compute_pbo"). The number of
    dropped combos is available from the caller via (len(rows) - len(good)).

    Fill-cell tracking (Task 9 follow-up):
      The union alignment may fill dates absent from a combo's own series with 0.0.
      We count those filled cells per combo, print a LOUD warning when any exist, and
      DROP any combo whose filled fraction > _MAX_FILLED_FRACTION (0.1%). This guards
      against silently including combos whose backtest CSV was truncated.

    Returns (matrix, col_hashes, dates, n_filled_cells):
      matrix         — np.ndarray shape (T, N), float64, zero NaN
      col_hashes     — list[str] combo hashes, column order matching the matrix
      dates          — list[str] the sorted union of dates (length T)
      n_filled_cells — int total zero-filled cells across all accepted combos
    """
    good = [r for r in rows if not is_error_row(r)]
    n_dropped_err = len(rows) - len(good)
    if n_dropped_err > 0:
        print(f"[build_returns_matrix] DROPPED {n_dropped_err} errored/incomplete combo(s) "
              f"from matrix ({len(good)} good combos remain)")
    if not good:
        return np.empty((0, 0), dtype=float), [], [], 0
    all_dates = sorted({d for r in good for d in r["dates"]})
    date_index = pd.Index(all_dates)
    T = len(all_dates)
    cols = []
    col_hashes = []
    total_filled = 0
    n_dropped_fill = 0
    for r in good:
        s = pd.Series(r["returns"], index=pd.Index([str(d) for d in r["dates"]]))
        s = s[~s.index.duplicated(keep="first")]       # guard duplicate dates
        aligned_series = s.reindex(date_index)
        n_filled = int(aligned_series.isna().sum())    # count NaN before fill
        filled_frac = n_filled / T if T > 0 else 0.0
        if n_filled > 0:
            print(
                f"[build_returns_matrix] WARNING: combo {r.get('hash', '?')!r} has "
                f"{n_filled}/{T} zero-filled cells ({filled_frac:.4%}) in date union."
            )
        if filled_frac > _MAX_FILLED_FRACTION:
            print(
                f"[build_returns_matrix] DROPPING combo {r.get('hash', '?')!r}: "
                f"filled fraction {filled_frac:.4%} > threshold {_MAX_FILLED_FRACTION:.1%}"
            )
            n_dropped_fill += 1
            continue
        total_filled += n_filled
        cols.append(aligned_series.fillna(0.0).to_numpy(dtype=float))
        col_hashes.append(r["hash"])
    if n_dropped_fill > 0:
        print(
            f"[build_returns_matrix] DROPPED {n_dropped_fill} combo(s) for "
            f"exceeding the {_MAX_FILLED_FRACTION:.1%} fill-fraction threshold "
            f"({len(col_hashes)} remain)"
        )
    if not cols:
        return np.empty((0, 0), dtype=float), [], [], 0
    matrix = np.column_stack(cols).astype(float)
    # Invariant: no NaN in the assembled matrix (fillna(0.0) guarantees this).
    assert not np.isnan(matrix).any(), (
        "build_returns_matrix produced NaN — this is a bug; all missing dates "
        "should be filled 0.0"
    )
    return matrix, col_hashes, all_dates, total_filled


def cross_trial_variance(matrix: np.ndarray) -> float:
    """Cross-trial Sharpe variance V: the sample variance of per-combo Sharpes.

    Per-period (daily) Sharpe per column (ddof=1), then Var (ddof=1) across columns.
    This is the V fed to expected_max_sharpe: how much the grid's Sharpes spread,
    which drives how high a Sharpe you'd expect as the best of N by luck.

    Statistical caveat (conservative): this is the sample variance of ESTIMATED
    per-combo Sharpes, not true Sharpes. Each per-combo Sharpe has estimation noise
    of order 1/T, so V is inflated by that noise. This inflates SR* → deflates DSR
    further, making the DSR conservative (will not over-claim the edge). This matches
    the documented caveat in dsr.py's module docstring, item (b).

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


# ─── Task 11: run_dsr orchestrator + selection-bias summary dict ──────────────

from datetime import date as _date
from pathlib import Path as _Path

from jutsu_engine.audit.dsr import (
    deflated_sharpe_brackets, DEFAULT_N_BRACKETS, sample_moments,
)
from jutsu_engine.audit.pbo import compute_pbo

# S = 16 blocks for CSCV (spec §7).
CSCV_BLOCKS: int = 16

# Import _all_symbols at module level so smoke tests can monkeypatch it.
from jutsu_engine.audit.attribution import _all_symbols


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
    matrix, col_hashes, _dates, n_filled = build_returns_matrix(rows)
    V = cross_trial_variance(matrix) if matrix.size else 0.0

    # V is keyword-required in deflated_sharpe_brackets (prevents silent V=0 bug).
    dsr_brackets = deflated_sharpe_brackets(golden_series, N_values=family_N, V=V)
    golden_moments = sample_moments(golden_series)

    pbo_block = None
    # Guard: need >=2 combos AND each CSCV block must have >=2 rows (ddof=1 Sharpe).
    # T < 2*S means blocks have <2 rows → all-NaN Sharpes → skip PBO gracefully.
    pbo_eligible = (
        compute_pbo_block
        and matrix.size
        and matrix.shape[1] >= 2
        and matrix.shape[0] >= 2 * S
    )
    if pbo_eligible:
        try:
            raw_pbo = compute_pbo(matrix, S=S)
        except ValueError as exc:
            # compute_pbo fail-fast on NaN or < 2 combos: fail loud with context.
            raise ValueError(
                f"compute_pbo failed for strategy {strategy_id!r} "
                f"(matrix shape={matrix.shape}, S={S}, n_filled={n_filled}): {exc}"
            ) from exc
        # Drop the (large) per-partition logit list from the summary dict; the report
        # renders a compact histogram, not 12,870 raw values.
        logits = raw_pbo.pop("logits", [])
        pbo_block = dict(raw_pbo)
        pbo_block["logit_histogram"] = _logit_histogram(logits)

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
            combos_limit: int | None = None, cscv_blocks: int = CSCV_BLOCKS,
            progress=lambda m: None) -> dict:
    """End-to-end Module 3 for one strategy: campaign → matrix → DSR + PBO summary.

    v3_5b (primary): enumerate the 243-combo golden grid (or `combos_limit` for a
    smoke run), run the returns campaign (resumable JSONL under
    run_dir/<sid>/campaign_dsr_<sid>.jsonl), build the matrix, compute DSR brackets
    on the golden combo + PBO/CSCV over the full matrix.

    v3_5d: DSR-ONLY. Its distinguishing grid was ~10 combos (too few for CSCV), so
    we run a SINGLE golden backtest (as one combo) and report DSR at a family-level
    N estimate — no second grid, no PBO. This scoping is stated in the report.

    skip_campaign: if the campaign JSONL already has every combo, skip re-running
    (matrix rebuilt from the existing rows). Errors if rows are missing.

    combos_limit: truncate the grid for smoke runs (e.g. 4 combos).
    cscv_blocks: CSCV block count S (default 16 per spec; 2 for smoke runs).
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
        # v3_5d: single golden combo (no overrides = live golden config).
        combos = [{"combo_id": 0, "overrides": {}, "hash": combo_hash({})}]
        golden_hash = combos[0]["hash"]
        compute_pbo_block = False
        family_N = (1000, 5000)   # family-level estimate; documented in report

    if not skip_campaign:
        run_returns_campaign(strategy_id, combos, campaign_file,
                             run_fn=run_one_combo,
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


def _golden_anchor_hash(combos: list[dict]) -> str:
    """Hash of the combo whose axis values equal the live golden config's.

    The live golden values for the four SHARED axes are upper_thresh_z=1.0,
    lower_thresh_z=0.2, vol_crush_threshold=-0.15, sma_fast=40. The historical grid's
    sma_slow axis is [180,200,220] and does NOT include the live golden 140 — so the
    anchor uses the historical grid's CENTER sma_slow (200) as the closest in-grid
    representative. This mismatch is real (the live config's sma_slow was tuned in a
    LATER phase) and is stated in the DSR report (render_dsr_section); the DSR uses
    the golden combo's actual daily returns from the campaign regardless.

    Golden anchor caveat for the report: live sma_slow=140 is OUTSIDE the historical
    grid [180,200,220]; the in-grid anchor is sma_slow=200; DSR uses the LIVE golden
    returns (which differ from any in-grid combo). This is honest and reproducible.
    """
    anchor = {"upper_thresh_z": 1.0, "lower_thresh_z": 0.2,
              "vol_crush_threshold": -0.15, "sma_fast": 40, "sma_slow": 200}
    target = combo_hash(anchor)
    for c in combos:
        if c["hash"] == target:
            return target
    # Fallback: first combo (deterministic) if the anchor is somehow absent.
    return combos[0]["hash"]
