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
from datetime import date


import calendar


def _add_years(d: date, years: float) -> date:
    """Add a fractional number of years using calendar-month arithmetic.

    Uses months = round(years * 12) so that 0.5y -> 6 months and 2.5y -> 30
    months, producing clean calendar boundaries (2010-02-01 + 2.5y = 2012-08-01,
    etc.). This matches the plan's specified window boundary dates exactly.

    NOTE: The plan's code draft used timedelta(days=round(365.25*years)), which
    gives dates 1-2 days off from the plan's own test assertions. We follow the
    test assertions (calendar-month arithmetic) as the authoritative spec.
    """
    months = round(years * 12)
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


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


# ---------------------------------------------------------------------------
# Task 2 — Evidence-driven grid (EXP-003 sensitivity ranking)
# ---------------------------------------------------------------------------
import hashlib
import itertools
import json

# Sensitive-parameter product (EXP-003 ranking); each axis centered on golden.
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
    # Generate all product combos; put the golden anchor (all axes at golden value)
    # first so combo_id 0 is always the baseline. Golden values are the middle
    # element of each axis by construction. Sort product so golden combo leads.
    all_product = list(itertools.product(*value_lists))
    golden_tuple = tuple(golden_axis[n] for n in names)
    all_product.sort(key=lambda t: (t != golden_tuple))  # golden first, rest unchanged
    for values in all_product:
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


# ---------------------------------------------------------------------------
# Task 3 — IS-winner selection
# ---------------------------------------------------------------------------
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
    Ties resolve to the first occurrence in reload/combo order — deterministic given fixed input order.
    """
    valid = [r for r in is_rows if _is_finite_number(r.get("is_sharpe"))]
    if not valid:
        return None
    return max(valid, key=lambda r: r["is_sharpe"])


# ---------------------------------------------------------------------------
# Task 4 — Stitched OOS-curve metrics (spec §5 output 1)
# ---------------------------------------------------------------------------
import numpy as np
import pandas as pd

# Reuse the audit's proven pure metric helpers (attribution.py) so the stitched
# curve uses the SAME math as Module 4, not a re-implementation.
from jutsu_engine.audit.attribution import _sharpe, _max_drawdown, _total_return


_STITCH_REQUIRED_COLUMNS = ("Date", "Strategy_Daily_Return", "QQQ_Daily_Return")


def filter_oos_frame_to_span(frame: pd.DataFrame, oos_start: date,
                             oos_end: date) -> pd.DataFrame:
    """Keep only the rows of one OOS frame that fall in [oos_start, oos_end).

    BacktestRunner emits the regime-timeseries CSV with WARMUP-era rows dated BEFORE
    the requested backtest start (it fetches extra history to warm SMAs/vol windows;
    those rows carry Strategy_Daily_Return == 0.0). For an OOS window the backtest is
    run over [oos_start, oos_end], so the emitted CSV begins ~1.5–2y before oos_start
    (the warmup fetch window). Left in, window 1's warmup zeros survive the stitch
    dedup (their dates precede every other window's span) and PAD the stitched OOS
    series head with hundreds of zero-return days — diluting the stitched Sharpe/CAGR
    and inflating oos_days by the warmup length.

    Filtering each frame to its window's own OOS span at CONSUMPTION heals existing
    checkpoints (no backtest re-run needed): the daily-return values are already
    correct inside the span; only the pre-span warmup rows must be dropped. The span
    is half-open [oos_start, oos_end) so consecutive windows (oos_end(N) ==
    oos_start(N+1)) do not double-count the shared boundary bar — the dedup in
    stitch_oos_metrics remains the second line of defence.

    The frame's Date column may be ISO strings with a time/tz suffix (e.g.
    "2012-08-01 06:00:00-08:00"); we compare on the leading "YYYY-MM-DD" prefix.
    A frame missing the Date column is returned unchanged (stitch_oos_metrics then
    raises its own clear error on the missing required column).
    """
    if frame is None or frame.empty or "Date" not in frame.columns:
        return frame
    day = frame["Date"].astype(str).str[:10]
    mask = (day >= oos_start.isoformat()) & (day < oos_end.isoformat())
    return frame[mask]


def stitch_oos_metrics(oos_frames: list[pd.DataFrame]) -> dict:
    """Concatenate per-window OOS daily returns and compute headline metrics.

    Each frame has columns Date, Strategy_Daily_Return, QQQ_Daily_Return (the
    regime-timeseries CSV shape BacktestRunner emits, regime_analyzer.py:192-222).
    Frames are concatenated in chronological order and ALL metrics are computed on
    the single stitched series — never by averaging per-window Sharpes (spec §5).

    Consecutive OOS windows share their boundary bar (oos_end(N) == oos_start(N+1)
    and the DB date bounds are inclusive), so that bar appears in BOTH frames. We
    DROP the duplicate boundary day (keep first) so each calendar day is counted
    exactly once — otherwise ~25 days over 26 windows are silently double-counted,
    inflating every headline metric.

    Contamination handling: rows whose Strategy_Daily_Return is NaN are dropped
    entirely (loudly, via nan_rows_dropped) so every metric shares one denominator.

    Returns dict: oos_days, total_return, cagr, sharpe, max_drawdown,
    qqq_total_return, alpha_vs_qqq, nan_rows_dropped.
    """
    oos_frames = [f for f in oos_frames if f is not None and not f.empty]
    if not oos_frames:
        return {"oos_days": 0, "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "qqq_total_return": 0.0, "alpha_vs_qqq": 0.0,
                "nan_rows_dropped": 0}

    stitched = pd.concat(oos_frames, ignore_index=True)

    missing = [c for c in _STITCH_REQUIRED_COLUMNS if c not in stitched.columns]
    if missing:
        raise ValueError(
            f"stitch_oos_metrics: stitched OOS frame is missing required "
            f"column(s): {', '.join(missing)}")

    stitched = stitched.sort_values("Date").reset_index(drop=True)
    # Dedupe boundary bars shared by consecutive windows (keep first occurrence).
    stitched = stitched.drop_duplicates(subset="Date", keep="first").reset_index(
        drop=True)

    # Drop NaN-contaminated return rows entirely so every metric shares one
    # denominator; report the count loudly (0 normally).
    nan_mask = stitched["Strategy_Daily_Return"].isna()
    nan_rows_dropped = int(nan_mask.sum())
    if nan_rows_dropped:
        stitched = stitched[~nan_mask].reset_index(drop=True)

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
        "nan_rows_dropped": nan_rows_dropped,
    }


# ---------------------------------------------------------------------------
# Task 5 — Parameter-drift table + golden top-decile share (spec §5/§10)
# ---------------------------------------------------------------------------
from collections import Counter

# Golden values of the sensitive grid axes (for top-decile-share scoring).
GOLDEN_SENSITIVE: dict = {
    "upper_thresh_z": 1.0, "realized_vol_window": 21, "sma_slow": 140,
}

# spec §10 decision thresholds for the golden top-decile share.
STABLE_THRESHOLD = 0.80
UNSTABLE_THRESHOLD = 0.50
# Top decile: with a small per-axis grid, "top decile" = ceil(10% of distinct
# values), min 1 (the single best value qualifies when the grid is small).
TOP_DECILE_FRACTION = 0.10


def drift_table(winners: list[dict]) -> pd.DataFrame:
    """One row per window: window_id, is_sharpe, and each winning param value.

    `winners` is the list of per-window IS winner dicts (from select_is_winner)
    each augmented with window_id.
    """
    recs = []
    for w in winners:
        row = {"window_id": w["window_id"], "is_sharpe": w.get("is_sharpe")}
        row.update(w["overrides"])
        recs.append(row)
    return pd.DataFrame(recs)


def param_value_distribution(winners: list[dict]) -> dict[str, Counter]:
    """Per param, a Counter of how often each value was the IS winner across windows."""
    dist: dict[str, Counter] = {}
    for w in winners:
        for k, v in w["overrides"].items():
            dist.setdefault(k, Counter())[v] += 1
    return dist


def golden_combo_top_decile_share(window_is_rows: list[list[dict]],
                                  golden_hash: str) -> float:
    """Fraction of windows where the golden COMBO ranks in the top decile of that
    window's grid by IS sharpe (cutoff = ceil(0.10 * n_valid_combos), >= 1).

    This is the spec §5/§10 VERDICT input: "the golden value is in the top decile
    of that window's grid" — grid = the 31 combos, so a true decile (cutoff 4)
    exists. Feed the result to stability_verdict().

    Windows where the golden combo has no finite IS sharpe are skipped (not
    counted). Ties: ranking is by (-sharpe, combo_hash) so ordering is
    deterministic and a tie cannot silently demote the golden combo based on
    iteration order.
    """
    hits = counted = 0
    for rows in window_is_rows:
        ranked = sorted(
            (r for r in rows if _is_finite_number(r.get("is_sharpe"))),
            key=lambda r: (-r["is_sharpe"], r.get("hash", "")))
        hashes = [r.get("hash") for r in ranked]
        if golden_hash not in hashes:
            continue
        counted += 1
        cutoff = max(1, math.ceil(len(ranked) * TOP_DECILE_FRACTION))
        if golden_hash in hashes[:cutoff]:
            hits += 1
    return hits / counted if counted else 0.0


def golden_axis_winner_share(window_is_rows: list[list[dict]], param: str,
                             golden_value) -> float:
    """Fraction of windows where the golden value is the OUTRIGHT best per-axis value.

    STRICT DIAGNOSTIC, NOT the spec §10 verdict input: for each window this
    marginalises over the other axes (best IS Sharpe per distinct value of
    `param`) and checks whether `golden_value` sits in the top ceil(10%) bucket.
    With 3-value axes a true decile is impossible — ceil(0.10*3)=1 — so this is
    effectively an "is golden the outright per-axis winner?" test, which is why it
    is demoted to a diagnostic. Use golden_combo_top_decile_share() for the verdict.

    Tie handling is deterministic AND golden-favorable: a tie with the golden
    value counts as a win (the golden value is compared into its rank bucket with
    `>=`), so an unlucky iteration order can never demote golden on a tie.
    Windows where `param` never appears are skipped.
    """
    hits = 0
    counted = 0
    for rows in window_is_rows:
        # best IS Sharpe per distinct value of `param` in this window
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
        golden_score = best[golden_value]
        cutoff = max(1, math.ceil(len(best) * TOP_DECILE_FRACTION))
        # Golden-favorable: count values STRICTLY better than golden. If fewer than
        # `cutoff` values beat golden, golden lands within the top bucket (ties with
        # golden do not push it out).
        strictly_better = sum(1 for s in best.values() if s > golden_score)
        if strictly_better < cutoff:
            hits += 1
    return (hits / counted) if counted else 0.0


def stability_verdict(share: float) -> str:
    """spec §10: >=80% -> stable; <50% -> unstable; otherwise inconclusive.

    `share` is the spec §5/§10 verdict input — feed it the output of
    golden_combo_top_decile_share() (golden COMBO ranked among the window's
    31-combo grid), NOT the per-axis diagnostic golden_axis_winner_share().
    """
    if share >= STABLE_THRESHOLD:
        return "stable"
    if share < UNSTABLE_THRESHOLD:
        return "unstable"
    return "inconclusive"


# ---------------------------------------------------------------------------
# Task 6 — Single-backtest driver (IS combo / OOS window)
# ---------------------------------------------------------------------------
import shutil
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# The live-config override bridge (float->Decimal parity with LiveStrategyRunner).
# Imported at module level so monkeypatch can intercept it via wfo_mod attribute.
from jutsu_engine.audit.plateau import build_overridden_strategy


def run_one_backtest(strategy_id: str, combo: dict, symbols: list[str],
                     start: date, end: date, phase: str,
                     initial_capital: str = "10000") -> dict:
    """Run ONE backtest for a combo over [start, end]; return a result row.

    Picklable (plain args — no closures, no captured state) so it runs inside a
    ProcessPoolExecutor worker on macOS spawn. All BacktestRunner CSVs write to a
    throwaway tempdir (prefix wfo_) that is cleaned in a finally block — no output
    lands in the report dir and no tempdirs leak on error.

    For IS phase: only is_sharpe is consumed. For OOS phase: the regime-timeseries
    CSV (Date / Strategy_Daily_Return / QQQ_Daily_Return columns — regime_analyzer.py
    lines 200-216) is loaded; its rows are stored as oos_rows for stitching. Column
    names come directly from the CSV and match the required columns exactly.

    A raising backtest returns a LOUD error row (is_sharpe=None, oos_rows=None,
    error=<exception string>) rather than propagating the exception, so a single
    failed run never aborts the campaign.

    `is_sharpe` stores the per-window Sharpe for both phases: for IS it is the
    selection metric; for OOS it is diagnostic-only (the headline metrics come from
    stitch_oos_metrics over the full oos_rows set, not from per-window Sharpes).
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
                # Columns from regime_analyzer.py generate_timeseries():
                #   Date, Regime, Trend, Vol, QQQ_Close, QQQ_Daily_Return,
                #   Portfolio_Value, Strategy_Daily_Return
                # stitch_oos_metrics requires exactly:
                #   Date, Strategy_Daily_Return, QQQ_Daily_Return  — all present.
                # Belt-and-braces: BacktestRunner prepends warmup rows dated BEFORE
                # `start` (== oos_start for the OOS phase); drop them here so freshly
                # captured rows carry only the window's own [start, end) span. The
                # consumption-side filter in run_campaign heals existing checkpoints;
                # this keeps NEW checkpoints clean at the source.
                df = filter_oos_frame_to_span(df, start, end)
                ts_rows = df[["Date", "Strategy_Daily_Return",
                              "QQQ_Daily_Return"]].to_dict("records")
            else:
                error = "OOS backtest emitted no regime timeseries CSV"
    except Exception as exc:  # noqa: BLE001 — loud row, never crash the campaign
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
        "oos_rows": ts_rows,    # list[dict] for OOS success; None otherwise
        "error": error,
    }


# ---------------------------------------------------------------------------
# Task 7 — Checkpoint / resume helpers (WFO JSONL, fsync, last-wins dedup)
# ---------------------------------------------------------------------------
import json
import os

# Reuse plateau's torn-line guard directly (no duplication).
from jutsu_engine.audit.plateau import _ends_with_newline

# Keys persisted per WFO campaign row. oos_rows is stored inline as a list of
# dicts; for large windows this is acceptable (5 OOS rows × 3 columns × ~26
# windows ≈ negligible JSONL size). Task 8 (campaign runner) will load and
# reconstruct DataFrames from these records for stitching.
_WFO_RESULT_KEYS = (
    "row_key", "window_id", "phase",
    "hash", "combo_id", "kind", "overrides",
    "is_sharpe", "oos_rows", "error",
)


def row_key(window_id: int, phase: str, combo_hash_str: str) -> str:
    """Stable resume key for one (window, phase, combo) unit of work.

    Format: "<window_id>:<phase>:<hash>" — e.g. "3:is:abc123def456789a".
    Uniquely identifies a (window, phase, combo) triplet across the campaign.
    """
    return f"{window_id}:{phase}:{combo_hash_str}"


def is_error_row(row: dict) -> bool:
    """True when a WFO row represents a failed backtest.

    A row is an error when:
    - it carries a non-None `error` string, OR
    - its `is_sharpe` is not a finite number AND (for OOS rows) `oos_rows` is
      absent/empty. OOS rows may legitimately carry is_sharpe=None when the
      regime-timeseries CSV was not emitted — that is itself an error.

    Mirrors plateau._is_error_row semantics so the circuit breaker counts the
    same kinds of failures in both modules.
    """
    if row.get("error") is not None:
        return True
    # OOS rows: success requires oos_rows (the daily-return list for stitching).
    if row.get("phase") == "oos":
        return not row.get("oos_rows")
    # IS rows: success requires a finite is_sharpe.
    return not _is_finite_number(row.get("is_sharpe"))


def append_wfo_row(path: Path, row: dict) -> None:
    """Append one WFO result row as a fsynced JSONL line (crash-safe).

    Mirrors plateau.append_result byte-for-byte except it uses _WFO_RESULT_KEYS
    instead of _RESULT_KEYS, keeping plateau untouched (no regression risk to
    Module 2). The single-writer invariant (only the parent process appends)
    makes concurrent parallel writes safe.

    Crash-safety: fsyncing per line means a completed backtest is durable the
    moment its row is written, surviving process crashes and power loss.

    Torn-line tolerance: if a prior process was killed mid-write and left a
    partial line without a trailing newline, a leading newline is inserted before
    the new row so the good row is never concatenated onto the dangling fragment.
    The fragment itself is skipped on read by load_completed_keys.
    """
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

    Tolerates a truncated trailing line (crash mid-write): a process killed
    mid-write leaves a partial JSON fragment which is silently skipped so a crash
    never poisons resume. Only well-formed rows carrying a `row_key` are counted.

    Last-wins dedup (mirrors plateau.load_completed_hashes):
        append_wfo_row only ever appends; after --retry-errors a retried row
        produces two rows (old error + new success). load_completed_keys keeps
        the LAST occurrence of each row_key, then applies retry_errors. This means:
          - error then success → last row is success → always counts as done.
          - success then error → last row is error → retry_errors=True: NOT done.

    retry_errors:
        False (default): ALL rows present are counted as done (standard resume).
        True: errored rows are excluded so they re-run on the next pass.
        Use --retry-errors at the CLI when a transient failure (DB blip) produced
        error rows that should be retried without deleting the JSONL.
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
                k = row["row_key"]
            except (json.JSONDecodeError, KeyError):
                continue  # tolerate a partially-written trailing line
            last[k] = row   # last-wins: overwrite prior row for this key
    done: set[str] = set()
    for k, row in last.items():
        if retry_errors and is_error_row(row):
            continue   # last occurrence is an error → treat as not-yet-done
        done.add(k)
    return done


def reload_wfo_rows(path: Path) -> list[dict]:
    """Load all WFO rows from a campaign JSONL (last-wins per row_key).

    Tolerates a truncated final line (crash mid-write). Used by the campaign
    runner to reconstruct IS rows for winner selection and OOS rows for stitching
    after a resume. Ordering is insertion-order of FIRST occurrence (later rows
    overwrite earlier but do not change position), matching plateau._reload_rows.
    """
    path = Path(path)
    if not path.exists():
        return []
    by_key: dict[str, dict] = {}
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
            k = row.get("row_key")
            if k is None:
                continue
            if k not in by_key:
                order.append(k)
            by_key[k] = row   # last-wins
    return [by_key[k] for k in order]


# ---------------------------------------------------------------------------
# Task 8 — Campaign runner (2-pass IS/OOS, resume, circuit breaker, single-writer)
# ---------------------------------------------------------------------------
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass as _dataclass

from jutsu_engine.audit.config import ATTRIBUTION_START

DEFAULT_MAX_CONSECUTIVE_ERRORS = 10

# One operator-actionable message, shared by the serial and parallel paths.
_BREAKER_MSG = (
    "aborting: {n} consecutive errored runs — systemic failure (DB down?). "
    "Errored rows are checkpointed and NOT retried on resume; investigate and "
    "delete them (or rerun with --retry-errors) before rerunning."
)


@_dataclass
class WFOCampaignResult:
    """Everything the report needs from a completed/resumed WFO campaign.

    winners: per-window IS-winner rows (each augmented with window_id), in window
        order, for the drift table and winning-value distribution.
    window_is_rows: per-window list of ALL IS rows (for the golden top-decile
        share verdict; parallel to `windows`, includes windows whose combos all
        errored as empty/short lists).
    stitched: stitch_oos_metrics over every committed OOS window.
    """
    strategy_id: str
    winners: list
    window_is_rows: list
    stitched: dict
    drift: "pd.DataFrame"
    value_distribution: dict
    campaign_file: str


def _span_for(win: WFOWindow, phase: str) -> tuple[date, date]:
    """[start, end] for a work unit: the IS span for 'is', the OOS span for 'oos'."""
    if phase == "is":
        return win.is_start, win.is_end
    return win.oos_start, win.oos_end


def _stamp_row(row: dict, win: WFOWindow, combo: dict, phase: str) -> dict:
    """Stamp a run_fn result with its window/phase/row_key identity (parent-side).

    run_fn returns a raw result row; the PARENT (never the worker) stamps the
    resume-identity keys so the single-writer append is authoritative even if a
    worker returns a row missing these fields.
    """
    row["window_id"] = win.window_id
    row["phase"] = phase
    row["row_key"] = row_key(win.window_id, phase, combo["hash"])
    return row


def _run_serial(strategy_id, units, campaign_file, run_fn, symbols,
                initial_capital, max_consecutive_errors, progress) -> None:
    """Run work units serially, checkpointing each; circuit-breaker on errors.

    A unit is (window, combo, phase). Rows are appended by the SINGLE WRITER here
    (the parent); run_fn only computes and returns a row. A success resets the
    consecutive-error counter; `max_consecutive_errors` in a row aborts.
    """
    consecutive = 0
    total = len(units)
    for i, (win, combo, phase) in enumerate(units, 1):
        start, end = _span_for(win, phase)
        row = run_fn(strategy_id, combo, symbols, start, end, phase,
                     initial_capital)
        _stamp_row(row, win, combo, phase)
        append_wfo_row(campaign_file, row)   # SINGLE WRITER (parent)
        consecutive = consecutive + 1 if is_error_row(row) else 0
        progress(f"[{i}/{total}] w{win.window_id} {phase} {combo['kind']} "
                 f"is_sharpe={row.get('is_sharpe')}")
        if consecutive >= max_consecutive_errors:
            raise RuntimeError(_BREAKER_MSG.format(n=max_consecutive_errors))


def _run_parallel(strategy_id, units, campaign_file, run_fn, symbols,
                  initial_capital, workers, max_consecutive_errors,
                  progress) -> None:
    """Parallel unit execution with resume + breaker (parent-only writes).

    Mirrors plateau._run_parallel: an explicit wait(FIRST_COMPLETED) loop so a
    tripped breaker can stop and cancel not-yet-started futures. When the breaker
    trips mid-batch we DRAIN the entire finished batch first — every already
    completed row is appended by the parent before the RuntimeError propagates —
    so no completed work is silently discarded (single-writer invariant preserved).

    run_fn must be a picklable module-level callable (macOS spawn). Still-RUNNING
    futures at abort cannot be cancelled; their results are discarded and those
    units re-run on resume (their rows were never checkpointed). "Consecutive" is
    counted in COMPLETION order here (submission order in the serial path); under
    systemic failure every run errors so the distinction vanishes.
    """
    consecutive = 0
    done_count = 0
    total = len(units)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        # Submit each unit; map its future to (window, combo, phase) so the parent
        # can stamp the returned row. run_fn is submitted directly (picklable,
        # plain-dict args); append_wfo_row is NEVER submitted — parent is sole writer.
        fut_meta = {}
        for win, combo, phase in units:
            start, end = _span_for(win, phase)
            fut = ex.submit(run_fn, strategy_id, combo, symbols, start, end,
                            phase, initial_capital)
            fut_meta[fut] = (win, combo, phase)
        pending = set(fut_meta)
        aborted = False
        while pending and not aborted:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            # Drain the ENTIRE finished batch before honouring `aborted` so every
            # completed row is checkpointed even when the breaker trips mid-batch.
            for fut in finished:
                win, combo, phase = fut_meta[fut]
                row = fut.result()
                _stamp_row(row, win, combo, phase)
                append_wfo_row(campaign_file, row)   # SINGLE WRITER (parent)
                done_count += 1
                if is_error_row(row):
                    consecutive += 1
                    if consecutive >= max_consecutive_errors:
                        aborted = True
                        # Do NOT break: keep draining `finished` to checkpoint the rest.
                else:
                    consecutive = 0
                progress(f"[{done_count}/{total}] w{win.window_id} {phase} "
                         f"{combo['kind']} is_sharpe={row.get('is_sharpe')}")
        if aborted:
            for fut in pending:
                fut.cancel()   # not-yet-started only; running futures finish + discard
            raise RuntimeError(_BREAKER_MSG.format(n=max_consecutive_errors))


def _dispatch(strategy_id, units, campaign_file, run_fn, symbols,
              initial_capital, workers, max_consecutive_errors, progress) -> None:
    """Route a work-unit batch to the serial or parallel executor by `workers`."""
    if not units:
        return
    if workers <= 1:
        _run_serial(strategy_id, units, campaign_file, run_fn, symbols,
                    initial_capital, max_consecutive_errors, progress)
    else:
        _run_parallel(strategy_id, units, campaign_file, run_fn, symbols,
                      initial_capital, workers, max_consecutive_errors, progress)


def _select_winners(windows, campaign_file, progress):
    """Re-derive per-window winners + IS-row lists from the committed JSONL.

    Deterministic across resume: winners come ONLY from checkpointed IS rows via
    reload_wfo_rows + select_is_winner (whose documented tie-break resolves to the
    highest finite IS Sharpe, first occurrence on ties). A campaign killed mid-OOS
    re-derives the IDENTICAL winner it would have picked before the crash — the
    winner is never recomputed differently on resume.

    Returns (winners, window_is_rows) parallel to `windows`. Windows whose combos
    all errored yield no winner (skipped, logged) but still contribute their (empty)
    IS-row list so the top-decile denominator stays correct.
    """
    all_rows = reload_wfo_rows(campaign_file)
    is_by_window: dict[int, list] = {}
    for r in all_rows:
        if r.get("phase") == "is":
            is_by_window.setdefault(r["window_id"], []).append(r)
    winners: list[dict] = []
    window_is_rows: list[list[dict]] = []
    for w in windows:
        rows = is_by_window.get(w.window_id, [])
        window_is_rows.append(rows)
        win = select_is_winner(rows)
        if win is None:
            progress(f"w{w.window_id}: all IS combos errored — window skipped")
            continue
        winners.append({**win, "window_id": w.window_id})
    return winners, window_is_rows


def run_campaign(strategy_id: str, campaign_file: Path,
                 windows_limit: int | None = None, workers: int = 1,
                 run_fn=run_one_backtest, symbols: list[str] | None = None,
                 total_start: date | None = None, total_end: date | None = None,
                 initial_capital: str = "10000",
                 max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
                 retry_errors: bool = False,
                 progress=lambda m: None) -> WFOCampaignResult:
    """Run (or resume) the 2-pass WFO campaign; return winners, stitched OOS, drift.

    Two-pass dependency handling (OOS for window N needs window N's IS winner):

      Pass 1 — run EVERY IS combo for EVERY window (embarrassingly parallel: 31x
        work keeps the pool busy). Each row checkpoints immediately.
      Winner selection — re-derive each window's winner from the committed IS rows
        (reload_wfo_rows + select_is_winner). This is done from the JSONL, NOT from
        in-memory pass-1 results, so a resume produces the SAME winners.
      Pass 2 — run the ONE OOS backtest per winner (with kind='oos_winner').

    Resume works ACROSS passes: a crash mid-IS resumes IS (uncommitted IS combos
    re-run); a crash mid-OOS finds all IS rows present (no IS re-run), re-derives
    the identical winners deterministically, and re-runs only the missing OOS
    backtests. Resume is applied BEFORE submitting either pass via
    load_completed_keys.

    SINGLE-WRITER INVARIANT: every append_wfo_row happens in THIS parent process
    (in _run_serial / _run_parallel); run_fn — including across the process-pool
    boundary — only computes and RETURNS a row. A single writer is what makes the
    concurrent parallel appends safe (no interleaved partial lines).

    Circuit breaker: `max_consecutive_errors` consecutive errored rows abort with
    an operator-actionable RuntimeError; a single success resets the counter. The
    breaker applies to BOTH passes and both execution paths.

    Midnight / multi-day note: `total_end` defaults to date.today() at call time and
    is NOT embedded in row keys. A resume after midnight extends the last window's
    OOS by 1 day (negligible for multi-year windows; documented and accepted).

    WARMUP-ZERO NOTE (OOS healed here; IS NOT recomputable — documented, not fixed):
      BacktestRunner prepends warmup rows dated before each backtest's start (zero
      Strategy_Daily_Return, count varying with sma_slow). For OOS we heal this at
      consumption by filtering each frame to its window's [oos_start, oos_end) span
      (see filter_oos_frame_to_span), so the stitched OOS curve is warmup-free even
      for pre-existing checkpoints.

      The IS Sharpes stored in existing checkpoints, however, were computed by
      BacktestRunner AT RUN TIME on the warmup-polluted daily series (they are scalar
      `sharpe_ratio` values, not a recomputable return series), so they cannot be
      corrected without re-running the IS backtests. The dilution is ~uniform within
      a window (the same warmup length applies to every combo of that window), so it
      shifts every combo's IS Sharpe by roughly the same factor (<=~3% relative) and
      does NOT change the WITHIN-window RANKING that drives winner selection or the
      top-decile verdict. It does not overturn EXP-004's noise verdict. A logbook
      correction note (handled by the orchestrator) records this; future re-runs get
      clean IS Sharpes because run_one_backtest now trims OOS at the source and the
      warmup rows never entered IS selection's ranking in the first place.
    """
    from jutsu_engine.audit.attribution import _all_symbols

    campaign_file = Path(campaign_file)
    total_start = total_start or ATTRIBUTION_START
    total_end = total_end or date.today()
    symbols = symbols if symbols is not None else _all_symbols(strategy_id)
    windows = generate_windows(total_start, total_end, windows_limit=windows_limit)
    combos = expand_grid()

    # ---- Pass 1: all IS combos for all windows (resume-before-submit) ----
    done = load_completed_keys(campaign_file, retry_errors=retry_errors)
    is_units = [(w, c, "is") for w in windows for c in combos
                if row_key(w.window_id, "is", c["hash"]) not in done]
    progress(f"pass 1 (IS): {len(is_units)} of {len(windows) * len(combos)} "
             "units to run")
    _dispatch(strategy_id, is_units, campaign_file, run_fn, symbols,
              initial_capital, workers, max_consecutive_errors, progress)

    # ---- Winner selection from committed IS rows (deterministic on resume) ----
    winners, window_is_rows = _select_winners(windows, campaign_file, progress)
    win_by_id = {w["window_id"]: w for w in winners}

    # ---- Pass 2: one OOS backtest per winner (resume-before-submit) ----
    done = load_completed_keys(campaign_file, retry_errors=retry_errors)
    oos_units = []
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
    _dispatch(strategy_id, oos_units, campaign_file, run_fn, symbols,
              initial_capital, workers, max_consecutive_errors, progress)

    # ---- Stitch OOS + build drift table from committed rows ----
    # Each OOS row's CSV includes warmup rows dated BEFORE the window's oos_start
    # (BacktestRunner prepends warmup history). Filter every frame to its window's own
    # [oos_start, oos_end) span at CONSUMPTION so existing checkpoints are healed
    # without re-running any backtest. Window bounds are re-derived from the same
    # `windows` list; rows carry window_id.
    win_by_id = {w.window_id: w for w in windows}
    all_rows = reload_wfo_rows(campaign_file)
    oos_frames = []
    for r in all_rows:
        if r.get("phase") != "oos" or not r.get("oos_rows"):
            continue
        frame = pd.DataFrame(r["oos_rows"])
        win = win_by_id.get(r.get("window_id"))
        if win is not None:
            frame = filter_oos_frame_to_span(frame, win.oos_start, win.oos_end)
        oos_frames.append(frame)
    stitched = stitch_oos_metrics(oos_frames)
    drift = drift_table(winners)
    vdist = param_value_distribution(winners)

    return WFOCampaignResult(
        strategy_id=strategy_id, winners=winners, window_is_rows=window_is_rows,
        stitched=stitched, drift=drift, value_distribution=vdist,
        campaign_file=str(campaign_file))


# ---------------------------------------------------------------------------
# Task 9 — run_wfo orchestrator + report summary dict
# ---------------------------------------------------------------------------


def summarize_campaign(result: WFOCampaignResult) -> dict:
    """Build the report summary dict from a WFOCampaignResult (spec §5/§10).

    The spec §10 VERDICT is driven by the golden COMBO's top-decile rank across
    the full 31-combo grid per window (golden_combo_top_decile_share), NOT by any
    per-axis marginalisation. Feed the combo-level share to stability_verdict().

    The per-axis golden_axis_winner_share values are included as a diagnostic table
    (axis_diagnostics) for the report but do NOT feed the overall_verdict.

    Keys returned:
      strategy_id, n_windows, n_winners
      stitched         — stitch_oos_metrics dict (includes nan_rows_dropped)
      combo_top_decile_share  — float: golden COMBO's top-decile share across windows
      combo_verdict    — "stable" / "unstable" / "inconclusive" (spec §10)
      overall_verdict  — alias for combo_verdict (the CLI study-question answer)
      axis_diagnostics — {param: {"golden_value": v, "share": f, "verdict": s}}
                          three entries for the sensitive grid axes (diagnostic only)
      drift_table      — DataFrame: per-window winner params (spec §5 output 2)
      value_distribution — {param: {value: count}}
      campaign_file    — str path to the JSONL
    """
    # --- Combo-level verdict (spec §10 primary) ---
    golden_hash = expand_grid()[0]["hash"]   # combo 0 is always the golden anchor
    combo_share = golden_combo_top_decile_share(result.window_is_rows, golden_hash)
    combo_verd = stability_verdict(combo_share)

    # --- Per-axis diagnostics (labeled clearly as diagnostic, not verdict) ---
    axis_diag: dict = {}
    for param, golden_val in GOLDEN_SENSITIVE.items():
        share = golden_axis_winner_share(result.window_is_rows, param, golden_val)
        axis_diag[param] = {
            "golden_value": golden_val,
            "share": share,
            "verdict": stability_verdict(share),
        }

    return {
        "strategy_id": result.strategy_id,
        "n_windows": len(result.window_is_rows),
        "n_winners": len(result.winners),
        "stitched": result.stitched,                      # includes nan_rows_dropped
        "combo_top_decile_share": combo_share,
        "combo_verdict": combo_verd,
        "overall_verdict": combo_verd,                    # study-question answer
        "golden_combo_hash": golden_hash,                 # 16-char hex; rendered in report
        "axis_diagnostics": axis_diag,
        "drift_table": result.drift,
        "value_distribution": {k: dict(v) for k, v in result.value_distribution.items()},
        "campaign_file": result.campaign_file,
    }


def run_wfo(strategy_id: str, run_dir: Path,
            windows_limit: int | None = None, workers: int = 1,
            retry_errors: bool = False,
            total_start: date | None = None, total_end: date | None = None,
            progress=lambda m: None) -> dict:
    """End-to-end Module 1 for one strategy: campaign → summarize → summary dict.

    The campaign JSONL is written under run_dir/<strategy_id>/campaign_wfo_<strategy_id>.jsonl
    so reruns resume from the last checkpointed row. Per-window backtests use a
    throwaway tempdir (never landing in run_dir). The summary dict returned is the
    exact shape render_wfo_section(summary) expects.

    Midnight / multi-day: total_end defaults to date.today() at call time and is
    NOT embedded in row keys; a resume after midnight extends the last window's OOS
    by 1 day (negligible for multi-year windows; documented and accepted).
    """
    run_dir = Path(run_dir)
    campaign_file = run_dir / strategy_id / f"campaign_wfo_{strategy_id}.jsonl"
    result = run_campaign(
        strategy_id, campaign_file,
        windows_limit=windows_limit, workers=workers,
        total_start=total_start, total_end=total_end,
        retry_errors=retry_errors, progress=progress)
    return summarize_campaign(result)
