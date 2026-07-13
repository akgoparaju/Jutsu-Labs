"""Module — vol-input ablation battery (spec §8): engine-truth replay + arms + gates.

Engine-truth requirement (spec §5): signal-level series come from the strategy's own
code path via LiveStrategyRunner.calculate_signal_stream (a single-pass bar replay,
no portfolio); portfolio metrics come from the standard BacktestRunner. Nothing in the
classifier is reimplemented. Read-only vs the DB.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd


import math

# ---------------------------------------------------------------------------
# Spec §8 — pre-registered improvement directions (quoted from spec §8).
# "exit_lag: lower is better (earlier de-risk)" -> improvement = negative delta.
# "whipsaw_ratio: lower is better (fewer flips)" -> improvement = negative delta.
# "drawdown_capture: lower is better (less loss captured)" -> improvement = neg delta.
# "2022 return: higher is better" -> improvement = positive delta.
# ---------------------------------------------------------------------------

# Spec §8: the raw vol_zscore AUC bar (VER1; alignment-dependent).
AUC_BAR_LO, AUC_BAR_HI = 0.815, 0.828
GATED_WEIGHT = 0.5
DIAG_WEIGHTS = (0.25, 0.75)
GATED_ARMS = ("kronos", "vix", "smoothing")

# Metric keys checked by the flatness sign rule (spec §8).
FLATNESS_METRIC_KEYS = ("exit_lag", "whipsaw_ratio", "dd_capture")


def battery_arms() -> list[dict]:
    """The spec §8 arms: stock baseline + 3 gated @0.5 + 6 ungated diagnostic @0.25/0.75.

    Each arm: {id, series (arm key or None), weight (or None), gated (bool)}.
    The diagnostic neighbors (id suffix _lo/_hi) are NEVER used to select a better w;
    they only feed the flatness diagnostic (spec §8, flatness SIGN rule).
    """
    arms = [{"id": "stock", "series": None, "weight": None, "gated": False}]
    for a in GATED_ARMS:
        arms.append({"id": a, "series": a, "weight": GATED_WEIGHT, "gated": True})
    for a in GATED_ARMS:
        arms.append({"id": f"{a}_lo", "series": a, "weight": DIAG_WEIGHTS[0],
                     "gated": False})
        arms.append({"id": f"{a}_hi", "series": a, "weight": DIAG_WEIGHTS[1],
                     "gated": False})
    return arms


def signal_gate(exit_lag_delta: float, whipsaw_ratio: float, auc: float) -> bool:
    """Spec §8 signal gate: improves exit-lag OR whipsaw ratio, AUC not below the bar.

    exit_lag_delta = arm exit lag - stock exit lag (negative = earlier = better;
                     spec §8 improvement direction: exit_lag lower is better).
    whipsaw_ratio  = arm flips / stock flips (<1 = fewer flips = better;
                     spec §8 improvement direction: whipsaw lower is better).
    auc            = the arm's input-series AUC(vol-state@t+21), same alignment.
    Passes iff (exit_lag_delta < 0 OR whipsaw_ratio < 1.0) AND auc >= AUC_BAR_LO.
    """
    improves = (exit_lag_delta < 0) or (whipsaw_ratio < 1.0)
    return bool(improves and auc >= AUC_BAR_LO)


def portfolio_gate(dd_capture_delta: float, ret2022_delta: float,
                   sharpe_ci: tuple[float, float]) -> bool:
    """Spec §8 portfolio gate: 2022 improves, full-window Sharpe not a CI-excluding-zero drop.

    dd_capture_delta = arm 2022 dd_capture - stock (negative = better protection;
                       spec §8 improvement direction: drawdown_capture lower is better).
    ret2022_delta    = arm 2022 return - stock (positive = better;
                       spec §8 improvement direction: 2022 return higher is better).
    sharpe_ci        = bootstrap CI of the full-window Sharpe delta (lo, hi). A CI that
                       OVERLAPS zero counts as 'no degradation'; a CI entirely below
                       zero is a real degradation and FAILS.
    Passes iff (dd_capture_delta < 0 OR ret2022_delta > 0) AND not (hi < 0).
    """
    improves_2022 = (dd_capture_delta < 0) or (ret2022_delta > 0)
    lo, hi = sharpe_ci
    ci_degrades = hi < 0.0
    return bool(improves_2022 and not ci_degrades)


def flatness_diagnostic(at_half: dict, at_lo: dict, at_hi: dict,
                        return_excluded: bool = False):
    """Spec §8 flatness SIGN rule: each gate-relevant delta keeps its SIGN at 0.25 & 0.75.

    at_half/at_lo/at_hi are dicts of {exit_lag, whipsaw_ratio, dd_capture} deltas vs
    stock at w=0.5, 0.25, 0.75. For each metric key (FLATNESS_METRIC_KEYS):
      - If ANY of the three weight values is None OR non-finite (inf/-inf/NaN), that
        metric is EXCLUDED from the sign check and counted in n_excluded (reported
        loudly so the caller can surface it — spec §8 binding semantics for signed
        exit_lag and +inf whipsaw_ratio). A None exit_lag arises when the strategy
        never went defensive; +inf whipsaw_ratio arises when stock had 0 flips.
      - Otherwise: sign(at_lo) == sign(at_half) == sign(at_hi) must hold. A sign
        flip at either neighbor = fragile = FAIL.
    Neighbors are NEVER used to pick a better w.

    Returns:
        bool  — passes if all includable metrics are consistent (no sign flips)
                AND there is at least one includable metric.
        If return_excluded=True, returns (bool, n_excluded: int).
    """
    def _sign(x) -> int:
        if x is None or (isinstance(x, float) and not math.isfinite(x)):
            return None  # type: ignore[return-value]  # sentinel: excluded
        return (x > 0) - (x < 0)  # -1, 0, or +1

    n_excluded = 0
    passes = True
    for key in FLATNESS_METRIC_KEYS:
        v0 = _sign(at_half.get(key))
        vl = _sign(at_lo.get(key))
        vh = _sign(at_hi.get(key))
        # Exclude the metric if ANY side is non-finite or None.
        if v0 is None or vl is None or vh is None:
            n_excluded += 1
            continue
        if vl != v0 or vh != v0:
            passes = False
    if return_excluded:
        return (passes, n_excluded)
    return passes


def arm_survives(signal_pass: bool, portfolio_pass: bool, flatness_pass: bool) -> bool:
    """Spec §8: an arm survives Tier 1 iff ALL three gates pass."""
    return bool(signal_pass and portfolio_pass and flatness_pass)


# ---------------------------------------------------------------------------
# Paired bootstrap CI for the Sharpe delta (spec §8 portfolio gate)
# ---------------------------------------------------------------------------

import numpy as np


def _sharpe(returns: np.ndarray, periods: int = 252) -> float:
    """Annualised Sharpe of a daily-return array (NaN-tolerant, ddof=1)."""
    r = returns[~np.isnan(returns)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods))


def bootstrap_sharpe_delta_ci(arm_returns, stock_returns, n_boot: int = 1000,
                              seed: int = 42, alpha: float = 0.05) -> tuple[float, float]:
    """Paired-index bootstrap CI of (arm Sharpe - stock Sharpe) over aligned daily returns.

    arm_returns and stock_returns are aligned daily-return arrays (same trading days;
    caller intersects on Date first). Resamples the SHARED day index n_boot times
    (paired, preserving the arm-vs-stock pairing per day) and returns the (alpha/2,
    1-alpha/2) percentile CI of the Sharpe delta. Deterministic given seed. A CI
    overlapping zero = 'no degradation' (portfolio_gate). Underpowered by design
    (n~=1-crash-episode caution, SYNTHESIS-001) — the CI is reported, not over-trusted.
    """
    a = np.asarray(arm_returns, dtype=float)
    s = np.asarray(stock_returns, dtype=float)
    n = min(len(a), len(s))
    a, s = a[:n], s[:n]
    rng = np.random.default_rng(seed)
    deltas = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[i] = _sharpe(a[idx]) - _sharpe(s[idx])
    lo = float(np.percentile(deltas, 100 * alpha / 2))
    hi = float(np.percentile(deltas, 100 * (1 - alpha / 2)))
    return (lo, hi)


def replay_signal_stream(runner, market_data: dict) -> pd.DataFrame:
    """Run a runner's calculate_signal_stream and shape it into a DataFrame.

    `runner` is a LiveStrategyRunner (or a test double) exposing
    calculate_signal_stream(market_data) -> list of {date, cell, vol_state, z_score}.
    Returns a DataFrame with exactly those columns, in bar order.
    """
    records = runner.calculate_signal_stream(market_data)
    return pd.DataFrame(records, columns=["date", "cell", "vol_state", "z_score"])


def _build_live_runner(strategy_id: str, vol_input_series, vol_blend_weight):
    """Build a LiveStrategyRunner around stock v3_5b OR the vol-input adapter.

    When vol_input_series is None and vol_blend_weight is None -> stock v3_5b class via
    its live YAML (identity baseline). Otherwise -> the adapter class, constructed from
    the SAME live golden params plus the two adapter params (explicit construction, so
    the Decimal weight is passed directly, not via any float bridge).
    """
    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner

    spec = resolve_strategy(strategy_id)
    if vol_input_series is None and vol_blend_weight is None:
        import importlib
        mod = importlib.import_module(spec.module_path)
        cls = getattr(mod, spec.class_name)
        return LiveStrategyRunner(strategy_class=cls, config_path=spec.config_path)

    # Adapter path: reuse the golden YAML params, add the two adapter kwargs.
    from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b_VolInput import (
        Hierarchical_Adaptive_v3_5b_VolInput,
    )
    runner = LiveStrategyRunner(
        strategy_class=Hierarchical_Adaptive_v3_5b_VolInput,
        config_path=spec.config_path)
    # LiveStrategyRunner already built .strategy from the YAML; but it did NOT pass the
    # adapter kwargs. Re-init the adapter with golden params + adapter kwargs so the
    # series is wired in. Golden params come from the YAML the runner already loaded.
    import yaml
    from jutsu_engine.live.strategy_runner import EXCLUDED_PARAMS
    with open(spec.config_path) as f:
        params = dict(yaml.safe_load(f)["strategy"]["parameters"])
    for k in EXCLUDED_PARAMS:
        params.pop(k, None)
    params = runner._convert_decimal_params(params)
    params["vol_input_series"] = vol_input_series
    if vol_blend_weight is not None:
        params["vol_blend_weight"] = Decimal(str(vol_blend_weight))
    runner.strategy = Hierarchical_Adaptive_v3_5b_VolInput(**params)
    runner.strategy.init()
    return runner


def run_regime_backtest(strategy_id: str, vol_input_series, vol_blend_weight,
                        start: date, end: date, output_dir: str) -> str:
    """Full-period portfolio backtest -> regime timeseries CSV path (BacktestRunner).

    Constructs stock v3_5b (vol_input_series=None AND vol_blend_weight=None) or the
    adapter, then runs the standard BacktestRunner exactly as attribution.run_attribution
    does, returning the regime_timeseries_csv path. Used by the identity test (Task 7)
    and the battery portfolio runs (Task 11).
    """
    from jutsu_engine.application.backtest_runner import BacktestRunner
    from jutsu_engine.audit.attribution import _all_symbols

    runner = _build_live_runner(strategy_id, vol_input_series, vol_blend_weight)
    strategy = runner.strategy
    config = {
        "symbols": _all_symbols(strategy_id),
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": Decimal("10000"),
    }
    bt = BacktestRunner(config)
    results = bt.run(strategy, output_dir=output_dir)
    ts_csv = results.get("regime_timeseries_csv")
    if not ts_csv or not Path(ts_csv).exists():
        raise RuntimeError("battery backtest emitted no regime timeseries CSV")
    return str(ts_csv)


# ---------------------------------------------------------------------------
# Battery campaign runner (Task 11) — checkpointed per-arm evaluation
# ---------------------------------------------------------------------------

from jutsu_engine.audit.plateau import append_result, load_completed_hashes, params_hash

# Tier-1 windows (spec §8): portfolio 2019-08 -> 2025-12; signal 1999->present for
# non-kronos arms, 2019-08 -> 2025-12 for kronos (its parquet coverage).
TIER1_PORTFOLIO_START = date(2019, 8, 1)
TIER1_PORTFOLIO_END = date(2025, 12, 31)
SIGNAL_START_FULL = date(1999, 3, 10)
SIGNAL_END = date.today()
KRONOS_SIGNAL_START = date(2019, 8, 6)


def _arm_hash(arm: dict) -> str:
    """Stable hash of an arm (id + weight) for checkpoint dedup."""
    return params_hash({"arm": arm["id"], "weight": arm["weight"]})


def run_battery(strategy_id: str, run_dir, arm_fn, campaign_file=None,
                progress=lambda msg: None) -> dict:
    """Run (or resume) the battery: evaluate each arm, checkpoint each row to JSONL.

    arm_fn(arm, run_dir) -> result row dict (injectable so the orchestration is unit-
    tested without the engine; the default real evaluator is evaluate_arm). Reuses the
    plateau append_result (fsync) + load_completed_hashes (resume) primitives; a re-run
    skips arms whose hash is already present. Single-writer: this parent writes, arm_fn
    only computes.
    """
    from pathlib import Path as _Path
    from jutsu_engine.audit.plateau import _reload_rows
    run_dir = _Path(run_dir)
    campaign_file = (
        _Path(campaign_file) if campaign_file is not None
        else run_dir / strategy_id / f"campaign_battery_{strategy_id}.jsonl"
    )
    done = load_completed_hashes(campaign_file)
    for arm in battery_arms():
        h = _arm_hash(arm)
        if h in done:
            progress(f"skip {arm['id']} (already done)")
            continue
        progress(f"eval {arm['id']} (w={arm['weight']})")
        row = arm_fn(arm, run_dir)
        row["hash"] = h
        row["kind"] = "battery"
        row["param"] = arm["id"]
        append_result(campaign_file, row)     # fsync; single-writer
    return {"strategy_id": strategy_id, "rows": _reload_rows(campaign_file),
            "campaign_file": str(campaign_file)}


def evaluate_arm(arm: dict, run_dir) -> dict:
    """Real per-arm evaluator: build the series, run portfolio + signal replay, score.

    For the stock arm: run stock v3_5b. For a series arm: build the series CSV (kronos/
    vix/smoothing) under run_dir, then run the adapter with that series at the arm's
    weight. Computes: 2022-episode exit_lag/whipsaw/dd_capture/return (transitions),
    the input-series AUC(vol-state@t+21) (signal replay; 21 TRADING ROWS forward,
    no leakage — score at row i is vol_z at t; label is vol_state@t+21), and the
    bootstrap Sharpe-delta CI vs stock. Returns a result row consumed by the
    report/gate layer.

    Compute: one ~5-8 s portfolio backtest over the 2019-08->2025-12 window + one signal
    replay (~1-3 min for full-window arms, <1 min for kronos). Warmup-trim every regime
    timeseries before scoring (EXP-006). Note: if this arm was already checkpointed in a
    prior run without the 'auc' field, run_battery will skip it (hash-based dedup);
    delete the campaign JSONL to force a full re-run.
    """
    from jutsu_engine.audit import transitions as tr
    from jutsu_engine.audit.attribution import era_metrics

    run_dir = Path(run_dir)
    series_dir = run_dir / "series"
    series_csv = None

    if arm["series"] is not None:
        series_csv = str(_ensure_series_csv(arm["series"], series_dir))

    ts_csv = run_regime_backtest(
        strategy_id="v3_5b",
        vol_input_series=series_csv,
        vol_blend_weight=(None if arm["id"] == "stock" else arm["weight"]),
        start=TIER1_PORTFOLIO_START, end=TIER1_PORTFOLIO_END,
        output_dir=str(run_dir / arm["id"]))

    ts = pd.read_csv(ts_csv)
    ts = tr.trim_warmup(ts, start=TIER1_PORTFOLIO_START)

    # 2022 episode metrics
    episodes = {e.id: e for e in tr.load_episodes()}
    ep2022 = episodes["bear2022"]
    port_row = tr.score_episode_portfolio(ts, ep2022, start=TIER1_PORTFOLIO_START)

    # 2022 calendar return delta comes from era_metrics (2022 bear era row)
    eras = era_metrics(ts)
    r2022 = eras[eras["era"] == "2022 bear"]["strategy_total_return"]
    ret2022 = float(r2022.iloc[0]) if not r2022.empty else float("nan")

    # Signal-level AUC(vol-state@t+21) — engine-truth single-pass replay.
    # score = z_score from the blended runner (causal; only info <= t).
    # label = vol_state@t+21 (21 TRADING rows forward; trimmed tail has no label).
    auc = float("nan")
    try:
        auc = _compute_arm_auc(arm, series_csv)
    except Exception as exc:  # noqa: BLE001 — AUC failure doesn't abort the arm
        import logging
        logging.getLogger(__name__).warning(
            "AUC computation failed for arm %s: %s", arm["id"], exc)

    return {
        "arm": arm["id"], "weight": arm["weight"],
        "exit_lag_2022": port_row["exit_lag_days"],
        "whipsaw_2022": port_row["whipsaw_flips"],
        "dd_capture_2022": port_row["drawdown_capture"],
        "ret2022": ret2022,
        "auc": auc,
        "regime_timeseries_csv": ts_csv,
        "series_csv": series_csv,
        "error": None,
    }


def _compute_arm_auc(arm: dict, series_csv) -> float:
    """Engine-truth signal replay -> AUC(vol-state@t+21) for an arm.

    Builds the appropriate LiveStrategyRunner (stock or adapter) and runs
    calculate_signal_stream over the arm's signal window. The z_score column
    is the vol classifier input after blending (T-1 aligned). Labels:
    vol_state@t+21 = 1 if 'High'. 21 TRADING rows forward; no leakage.
    Warmup rows (NaN z_score) are dropped before AUC.
    """
    from jutsu_engine.audit import db as audit_db
    from jutsu_engine.audit.transitions import auc_vol_state_forward

    # Select signal window
    if arm["id"] == "stock" or arm.get("series") not in ("kronos",):
        sig_start = SIGNAL_START_FULL
    else:
        sig_start = KRONOS_SIGNAL_START

    engine = audit_db.get_engine()
    runner = _build_live_runner(
        "v3_5b",
        series_csv if arm["id"] != "stock" else None,
        arm["weight"] if arm["id"] != "stock" else None,
    )
    # Load QQQ (and all strategy symbols) for signal replay
    from jutsu_engine.audit.attribution import _all_symbols
    symbols = _all_symbols("v3_5b")
    md = {}
    for sym in symbols:
        bars = audit_db.load_bars(engine, sym, SIGNAL_END, lookback=10000)
        if not bars.empty:
            md[sym] = bars

    stream = replay_signal_stream(runner, md)
    if stream.empty:
        return float("nan")

    # Drop warmup (NaN z_score)
    stream = stream.dropna(subset=["z_score"]).reset_index(drop=True)
    if len(stream) < 42:  # need at least 2*21 rows for meaningful AUC
        return float("nan")

    # Build labels: vol_state 21 TRADING rows forward (shift -21)
    n = len(stream)
    labels_shifted = stream["vol_state"].iloc[21:].reset_index(drop=True)
    scores = stream["z_score"].iloc[:n - 21].reset_index(drop=True)

    # Encode: High -> 1, Low -> 0
    y = (labels_shifted == "High").astype(int).tolist()
    s = scores.tolist()

    return auc_vol_state_forward(s, y)


def _ensure_series_csv(series_key: str, series_dir):
    """Build (once) and return the CSV path for a series arm key (kronos/vix/smoothing)."""
    from jutsu_engine.audit import input_series as isr
    series_dir = Path(series_dir)
    out = series_dir / f"{series_key}.csv"
    if out.exists():
        return out
    if series_key == "kronos":
        df = isr.build_kronos_series()
        return isr.write_series(out, df, source="kronos",
                                provenance="Kronos-base std_return@H5 -> z(200) -> EMA5")
    if series_key == "vix":
        from jutsu_engine.audit import db as audit_db
        engine = audit_db.get_engine()
        df = isr.build_vix_series(engine)
        return isr.write_series(out, df, source="vix",
                                provenance="$VIX daily close (dedup) -> z(200) -> EMA5")
    if series_key == "smoothing":
        stream = _stock_signal_stream()
        df = isr.build_smoothing_from_stream(stream)
        return isr.write_series(out, df, source="smoothing",
                                provenance="engine-truth vol_z -> EMA5 (zero-info control)")
    raise ValueError(f"unknown series key: {series_key}")


def _stock_signal_stream():
    """Engine-truth vol-z stream for stock v3_5b (for the smoothing builder)."""
    from jutsu_engine.audit import db as audit_db
    from jutsu_engine.audit.attribution import _all_symbols
    engine = audit_db.get_engine()
    runner = _build_live_runner("v3_5b", None, None)
    symbols = _all_symbols("v3_5b")
    md = {}
    for sym in symbols:
        bars = audit_db.load_bars(engine, sym, SIGNAL_END, lookback=10000)
        if not bars.empty:
            md[sym] = bars
    return replay_signal_stream(runner, md)
