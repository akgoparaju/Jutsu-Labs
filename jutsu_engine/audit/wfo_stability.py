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
