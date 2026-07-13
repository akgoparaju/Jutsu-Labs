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
