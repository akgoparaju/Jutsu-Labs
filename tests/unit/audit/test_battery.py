"""Unit tests for battery engine-truth replay + smoothing builder (mostly DB-free)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest


def test_replay_signal_stream_records_per_bar_state():
    """replay_signal_stream feeds bars via a fake runner and records per-bar regime."""
    from jutsu_engine.audit.battery import replay_signal_stream

    class _FakeRunner:
        """Minimal LiveStrategyRunner double exposing calculate_signal_stream."""
        def calculate_signal_stream(self, market_data):
            df = market_data["QQQ"]
            return [
                {"date": r["date"], "cell": 1, "vol_state": "Low",
                 "z_score": float(r["close"]) / 100.0}
                for _, r in df.iterrows()
            ]

    md = {"QQQ": pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=3, freq="B"),
        "open": [1, 1, 1], "high": [1, 1, 1], "low": [1, 1, 1],
        "close": [100, 110, 120], "volume": [1, 1, 1],
    })}
    out = replay_signal_stream(_FakeRunner(), md)
    assert list(out.columns) == ["date", "cell", "vol_state", "z_score"]
    assert len(out) == 3
    assert out["z_score"].tolist() == [1.0, 1.1, 1.2]


def test_build_smoothing_from_stream():
    """build_smoothing_from_stream EMA5s the engine-truth z_score stream (T-1 causal)."""
    from jutsu_engine.audit.input_series import build_smoothing_from_stream
    stream = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=6, freq="B"),
        "z_score": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    })
    out = build_smoothing_from_stream(stream, ema_span=5)
    assert list(out.columns) == ["date", "value"]
    # EMA(span=5, adjust=False) of the z stream, first value == first z
    assert out["value"].iloc[0] == 0.0
    assert out["value"].iloc[-1] > out["value"].iloc[0]


def test_battery_arms_table():
    """battery_arms yields stock + 3 gated @0.5 + 6 ungated diagnostic @0.25/0.75."""
    from jutsu_engine.audit.battery import battery_arms
    arms = battery_arms()
    ids = [a["id"] for a in arms]
    assert "stock" in ids
    gated = [a for a in arms if a["gated"]]
    assert {a["id"] for a in gated} == {"kronos", "vix", "smoothing"}
    assert all(a["weight"] == 0.5 for a in gated)
    diag = [a for a in arms if a["id"].endswith(("_lo", "_hi"))]
    assert len(diag) == 6
    assert {a["weight"] for a in diag} == {0.25, 0.75}


def test_signal_gate_requires_improvement_without_auc_drop():
    """signal_gate passes only if exit-lag OR whipsaw improves AND AUC stays >= 0.815."""
    from jutsu_engine.audit.battery import signal_gate
    # improves whipsaw ratio (<1) and AUC within bar -> pass
    assert signal_gate(exit_lag_delta=0.0, whipsaw_ratio=0.9, auc=0.82) is True
    # AUC below the raw-bar range -> fail regardless of improvement
    assert signal_gate(exit_lag_delta=-1.0, whipsaw_ratio=0.8, auc=0.80) is False
    # no improvement (worse exit lag, whipsaw ratio >=1) -> fail
    assert signal_gate(exit_lag_delta=1.0, whipsaw_ratio=1.1, auc=0.82) is False


def test_portfolio_gate_bootstrap_ci_rule():
    """portfolio_gate passes if 2022 improves and Sharpe CI is not a CI-excluding-zero drop."""
    from jutsu_engine.audit.battery import portfolio_gate
    # 2022 dd_capture improves (lower), Sharpe delta CI overlaps zero -> pass
    assert portfolio_gate(dd_capture_delta=-0.05, ret2022_delta=0.0,
                          sharpe_ci=(-0.02, 0.03)) is True
    # 2022 improves but Sharpe CI excludes zero on the negative side -> fail
    assert portfolio_gate(dd_capture_delta=-0.05, ret2022_delta=0.0,
                          sharpe_ci=(-0.10, -0.02)) is False
    # no 2022 improvement -> fail
    assert portfolio_gate(dd_capture_delta=0.05, ret2022_delta=-0.01,
                          sharpe_ci=(-0.01, 0.01)) is False


def test_flatness_sign_rule():
    """flatness_diagnostic passes only if every gate-delta keeps its sign at 0.25/0.75."""
    from jutsu_engine.audit.battery import flatness_diagnostic
    # all three deltas negative at 0.5 and both neighbors -> same sign -> pass
    at50 = {"exit_lag": -1.0, "whipsaw_ratio": -0.1, "dd_capture": -0.05}
    lo = {"exit_lag": -0.5, "whipsaw_ratio": -0.2, "dd_capture": -0.02}
    hi = {"exit_lag": -1.5, "whipsaw_ratio": -0.05, "dd_capture": -0.08}
    assert flatness_diagnostic(at50, lo, hi) is True
    # a sign flip at the hi neighbor (dd_capture positive) -> fragile -> fail
    hi_flip = {"exit_lag": -1.5, "whipsaw_ratio": -0.05, "dd_capture": 0.02}
    assert flatness_diagnostic(at50, lo, hi_flip) is False


def test_flatness_none_delta_excluded_counted_loudly():
    """flatness_diagnostic excludes metrics with None on either side; report_excluded != 0."""
    from jutsu_engine.audit.battery import flatness_diagnostic
    # exit_lag=None at w=0.5 -> excluded (its sign cannot be checked)
    at50 = {"exit_lag": None, "whipsaw_ratio": -0.1, "dd_capture": -0.05}
    lo   = {"exit_lag": None, "whipsaw_ratio": -0.2, "dd_capture": -0.02}
    hi   = {"exit_lag": None, "whipsaw_ratio": -0.05, "dd_capture": -0.08}
    result, n_excluded = flatness_diagnostic(at50, lo, hi, return_excluded=True)
    assert result is True          # remaining two metrics both consistent
    assert n_excluded == 1         # exit_lag was excluded


def test_flatness_inf_whipsaw_excluded_counted_loudly():
    """flatness_diagnostic excludes +inf whipsaw_ratio (stock had 0 flips); n_excluded > 0."""
    from jutsu_engine.audit.battery import flatness_diagnostic
    at50 = {"exit_lag": -1.0, "whipsaw_ratio": float("inf"), "dd_capture": -0.05}
    lo   = {"exit_lag": -0.5, "whipsaw_ratio": float("inf"), "dd_capture": -0.02}
    hi   = {"exit_lag": -1.5, "whipsaw_ratio": float("inf"), "dd_capture": -0.08}
    result, n_excluded = flatness_diagnostic(at50, lo, hi, return_excluded=True)
    assert result is True          # exit_lag and dd_capture are both consistent
    assert n_excluded == 1         # whipsaw_ratio excluded (all inf, not just one side)


def test_bootstrap_sharpe_delta_ci_zero_when_identical():
    """bootstrap_sharpe_delta_ci returns a CI tightly around 0 for identical return series."""
    from jutsu_engine.audit.battery import bootstrap_sharpe_delta_ci
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 500)
    lo, hi = bootstrap_sharpe_delta_ci(r, r.copy(), n_boot=200, seed=7)
    assert lo <= 0.0 <= hi
    assert abs(hi - lo) < 0.05          # identical series -> near-zero spread


def test_bootstrap_sharpe_delta_ci_is_deterministic_with_seed():
    """A fixed seed makes the bootstrap CI reproducible."""
    from jutsu_engine.audit.battery import bootstrap_sharpe_delta_ci
    rng = np.random.default_rng(1)
    a = rng.normal(0.001, 0.01, 300)
    b = rng.normal(0.0005, 0.01, 300)
    ci1 = bootstrap_sharpe_delta_ci(a, b, n_boot=200, seed=42)
    ci2 = bootstrap_sharpe_delta_ci(a, b, n_boot=200, seed=42)
    assert ci1 == ci2


def test_run_battery_checkpoints_and_resumes(tmp_path):
    """run_battery records one row per arm and skips arms already in the JSONL."""
    from jutsu_engine.audit.battery import run_battery, battery_arms

    calls = {"n": 0}

    def fake_arm_fn(arm, run_dir):
        """Fake per-arm evaluator: returns a minimal result row without the engine."""
        calls["n"] += 1
        return {
            "arm": arm["id"], "weight": arm["weight"],
            "exit_lag_2022": 3, "whipsaw_ratio": 0.9, "auc": 0.82,
            "dd_capture_2022": 0.7, "ret2022": -0.13,
            "sharpe_ci_lo": -0.02, "sharpe_ci_hi": 0.03,
            "error": None,
        }

    campaign = tmp_path / "campaign_battery_v3_5b.jsonl"
    res1 = run_battery("v3_5b", tmp_path, arm_fn=fake_arm_fn,
                       campaign_file=campaign)
    n_arms = len(battery_arms())
    assert calls["n"] == n_arms
    assert len(res1["rows"]) == n_arms

    # Resume: no arm should be re-run.
    calls["n"] = 0
    res2 = run_battery("v3_5b", tmp_path, arm_fn=fake_arm_fn,
                       campaign_file=campaign)
    assert calls["n"] == 0
    assert len(res2["rows"]) == n_arms


def test_signal_stream_final_bar_matches_calculate_signals_db_gated():
    """calculate_signal_stream's last record equals calculate_signals' final signal."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable")

    from jutsu_engine.audit.battery import _build_live_runner, replay_signal_stream

    # Load a common history window (well past warmup) for signal + treasury symbols.
    as_of = date(2021, 6, 30)
    signal_df = audit_db.load_bars(engine, "QQQ", as_of, lookback=600)
    treasury_df = audit_db.load_bars(engine, "TLT", as_of, lookback=600)
    assert len(signal_df) > 400 and len(treasury_df) > 400
    md = {"QQQ": signal_df, "TLT": treasury_df}

    # Two independent runners (each mutates its strategy in place feeding all bars).
    r_signals = _build_live_runner("v3_5b", None, None)
    r_stream = _build_live_runner("v3_5b", None, None)

    final_signals = r_signals.calculate_signals(md)
    stream = replay_signal_stream(r_stream, md)
    last = stream.iloc[-1]

    # Engine-truth consistency: same final cell + vol_state from both code paths.
    assert int(last["cell"]) == int(final_signals["current_cell"])
    assert last["vol_state"] == final_signals["vol_state"]
    # z_score matches the final calculate_signals z (float compare, tight tolerance).
    assert abs(float(last["z_score"]) - float(final_signals["z_score"])) < 1e-9
