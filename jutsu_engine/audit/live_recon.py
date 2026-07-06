"""Module 5 — Live reconciliation (spec §9).

Replays each live strategy through LiveStrategyRunner.calculate_signals over
EOD market_data bars (mirroring scripts/backfill_regime.py) and diffs the result
day-by-day against scheduler-authoritative performance_snapshots.

Diff categorization (spec §9 + data gotchas):
  - Categorical fields (strategy_cell / trend_state / vol_state) MUST match
    exactly; a mismatch is 'logic' (same EOD inputs, different output -> bug).
  - Continuous fields (z_score / t_norm) were computed intraday by the scheduler,
    so exact EOD-replay match is NOT expected. Out-of-tolerance diffs are 'timing'.
    NULL stored values (e.g. 'backfill' rows) are silently skipped (None has known
    benign provenance). NaN or non-numeric continuous values are data-quality
    anomalies and are flagged category 'data' — never silently matched.
  - Equity divergence uses total_equity (real EOD equity), never market_data close.

The categorize/summarize functions are pure and DB-free (this file's tested core).
The replay driver (run_live_recon) is DB-backed and degrades gracefully.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Tolerances for intraday-vs-EOD continuous fields. Categorical fields have NO
# tolerance (exact match required).
ZSCORE_TOLERANCE = 0.25
TNORM_TOLERANCE = 0.10

_CATEGORICAL = ("strategy_cell", "trend_state", "vol_state")
_CONTINUOUS = (("z_score", ZSCORE_TOLERANCE), ("t_norm", TNORM_TOLERANCE))


def categorize_day(stored: dict, replay: dict) -> dict:
    """Compare one day's stored snapshot vs replayed signals; categorize diffs.

    Args:
        stored: a record from db.load_scheduler_snapshots (has categorical +
            continuous fields, may contain None for continuous).
        replay: {'strategy_cell','trend_state','vol_state','z_score','t_norm'}
            from the strategy replay.

    Returns a dict:
        {day, categorical_match, mismatches: [{field, stored, replay, category}],
         category}  where category is one of 'match','logic','timing'
         (logic dominates timing when both present).
    """
    mismatches: list[dict] = []

    categorical_match = True
    for f in _CATEGORICAL:
        sv = stored.get(f)
        rv = replay.get(f)
        if sv is None:
            # No stored categorical value on this day -> data gap, not a logic bug.
            mismatches.append({"field": f, "stored": None, "replay": rv,
                               "category": "data"})
            categorical_match = False
            continue
        if sv != rv:
            mismatches.append({"field": f, "stored": sv, "replay": rv,
                               "category": "logic"})
            categorical_match = False

    for f, tol in _CONTINUOUS:
        sv = stored.get(f)
        rv = replay.get(f)
        if sv is None or rv is None:
            continue  # 'missing' — stored backfill row (sv) or replay gap (rv); known-benign
        try:
            sv_f, rv_f = float(sv), float(rv)
        except (TypeError, ValueError):
            sv_f = rv_f = float("nan")
        if math.isnan(sv_f) or math.isnan(rv_f):
            # NaN is a data-quality anomaly (unlike None) — surface it, never compare it.
            mismatches.append({"field": f, "stored": sv, "replay": rv,
                               "category": "data"})
            continue
        if abs(sv_f - rv_f) > tol:
            mismatches.append({"field": f, "stored": sv_f, "replay": rv_f,
                               "category": "timing"})

    if any(m["category"] in ("logic", "data") for m in mismatches):
        category = "logic" if any(m["category"] == "logic" for m in mismatches) else "data"
    elif any(m["category"] == "timing" for m in mismatches):
        category = "timing"
    else:
        category = "match"

    return {
        "day": stored.get("day"),
        "categorical_match": categorical_match,
        "mismatches": mismatches,
        "category": category,
    }


def summarize_diffs(days: list[dict]) -> dict:
    """Aggregate per-day categorizations into report-level counts."""
    total = len(days)
    match_days = sum(1 for d in days if d["category"] == "match")
    by_category: dict[str, int] = {}
    by_field: dict[str, int] = {}
    for d in days:
        if d["category"] != "match":
            by_category[d["category"]] = by_category.get(d["category"], 0) + 1
        for m in d["mismatches"]:
            by_field[m["field"]] = by_field.get(m["field"], 0) + 1
    return {
        "total_days": total,
        "match_days": match_days,
        "mismatch_days": total - match_days,
        "mismatch_pct": ((total - match_days) / total * 100.0) if total else 0.0,
        "by_category": by_category,
        "by_field": by_field,
    }


@dataclass
class LiveReconResult:
    """Everything the report needs for one strategy's reconciliation."""
    strategy_id: str
    summary: dict
    day_table: list[dict]
    source_counts: dict
    pnl_divergence: dict


def reconcile(
    strategy_id: str,
    snapshots: list[dict],
    replay_day,
    source_counts: dict,
) -> LiveReconResult:
    """Diff stored scheduler snapshots against a per-day replay.

    Args:
        strategy_id: e.g. "v3_5b".
        snapshots: records from db.load_scheduler_snapshots (one per trading day),
            each with categorical + continuous fields + total_equity.
        replay_day: callable(strategy_id, day) -> dict with keys
            strategy_cell/trend_state/vol_state/t_norm/z_score and optional
            replay_equity. Injected so this is unit-testable without a DB.
        source_counts: {snapshot_source: distinct_day_count} for the provenance table.

    Returns a LiveReconResult. Equity divergence compares the last day's stored
    total_equity against the last day's replay_equity (both real-EOD-based).
    """
    day_rows: list[dict] = []
    stored_equity_series: list[tuple[date, float]] = []
    replay_equity_series: list[tuple[date, float]] = []

    for snap in snapshots:
        day = snap["day"]
        rep = replay_day(strategy_id, day) or {}
        diff = categorize_day(snap, rep)
        diff["stored_equity"] = snap.get("total_equity")
        diff["replay_equity"] = rep.get("replay_equity")
        day_rows.append(diff)
        if snap.get("total_equity") is not None:
            stored_equity_series.append((day, float(snap["total_equity"])))
        if rep.get("replay_equity") is not None:
            replay_equity_series.append((day, float(rep["replay_equity"])))

    summary = summarize_diffs(day_rows)

    pnl_divergence = {
        "final_stored_equity": stored_equity_series[-1][1] if stored_equity_series else None,
        "final_replay_equity": replay_equity_series[-1][1] if replay_equity_series else None,
    }
    if pnl_divergence["final_stored_equity"] is not None and \
       pnl_divergence["final_replay_equity"] is not None:
        pnl_divergence["abs_divergence"] = abs(
            pnl_divergence["final_replay_equity"] - pnl_divergence["final_stored_equity"]
        )
    else:
        pnl_divergence["abs_divergence"] = None

    return LiveReconResult(
        strategy_id=strategy_id,
        summary=summary,
        day_table=day_rows,
        source_counts=source_counts,
        pnl_divergence=pnl_divergence,
    )


def make_replay_day(engine, strategy_id: str, lookback: int = 250):
    """Build a replay_day(strategy_id, day) callable backed by the live engine.

    Mirrors scripts/backfill_regime.py:102-122 exactly: a FRESH LiveStrategyRunner
    per day (clean 250-bar warmup, matching the scheduler cold-start), signal +
    treasury symbols loaded from market_data, calculate_signals invoked.

    The returned callable does not compute replay equity (positions-level equity
    replay is out of scope for Phase 1); pnl_divergence therefore reports the
    stored live equity endpoints and leaves replay equity None unless a caller
    supplies it. This is intentional and documented in the report.
    """
    import importlib

    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.audit.db import load_bars

    spec = resolve_strategy(strategy_id)

    def _replay(_sid: str, day) -> Optional[dict]:
        from jutsu_engine.live.strategy_runner import LiveStrategyRunner
        mod = importlib.import_module(spec.module_path)
        strategy_class = getattr(mod, spec.class_name)
        runner = LiveStrategyRunner(strategy_class=strategy_class,
                                    config_path=spec.config_path)
        md = {}
        for sym in (runner.get_signal_symbol(), runner.get_treasury_symbol()):
            bars = load_bars(engine, sym, day, lookback)
            if bars.empty:
                return None
            md[sym] = bars
        signals = runner.calculate_signals(md)
        return {
            "strategy_cell": signals.get("current_cell"),
            "trend_state": signals.get("trend_state"),
            "vol_state": signals.get("vol_state"),
            "t_norm": signals.get("t_norm"),
            "z_score": signals.get("z_score"),
        }

    return _replay


def run_live_recon(strategy_id: str, start=None) -> LiveReconResult:
    """DB-backed entry point used by the CLI. Reads scheduler snapshots, replays,
    returns a LiveReconResult. Raises AuditDBUnavailable if the DB is not reachable.
    """
    from jutsu_engine.audit.config import LIVE_RECON_START
    from jutsu_engine.audit.db import (
        get_engine,
        load_scheduler_snapshots,
        load_snapshot_source_counts,
    )
    start = start or LIVE_RECON_START
    engine = get_engine()
    snapshots = load_scheduler_snapshots(engine, strategy_id, start)
    source_counts = load_snapshot_source_counts(engine, strategy_id, start)
    replay_day = make_replay_day(engine, strategy_id)
    return reconcile(strategy_id, snapshots, replay_day, source_counts)
