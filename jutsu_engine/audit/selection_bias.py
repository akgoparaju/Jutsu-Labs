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
# _golden_anchor_hash() and in the report.
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
