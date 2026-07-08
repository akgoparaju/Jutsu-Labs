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
    Ties resolve to the first occurrence in combo order (lowest combo_id) — deterministic given fixed input order.
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
