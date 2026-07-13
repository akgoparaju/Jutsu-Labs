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
