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
