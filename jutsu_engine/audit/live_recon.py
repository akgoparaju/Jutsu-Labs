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
