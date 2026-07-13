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


def test_summarize_battery_assigns_verdicts_and_tier2():
    """summarize_battery runs the gates over arm rows and sets per-arm verdicts + Tier-2."""
    from jutsu_engine.audit.battery import summarize_battery
    # stock baseline + a surviving smoothing arm + its two neighbors (same-sign deltas)
    rows = [
        {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
         "whipsaw_2022": 6, "dd_capture_2022": 0.9, "ret2022": -0.30},
        {"arm": "smoothing", "weight": 0.5, "auc": 0.82, "exit_lag_2022": 3,
         "whipsaw_2022": 4, "dd_capture_2022": 0.7, "ret2022": -0.13},
        {"arm": "smoothing_lo", "weight": 0.25, "auc": 0.82, "exit_lag_2022": 4,
         "whipsaw_2022": 5, "dd_capture_2022": 0.8, "ret2022": -0.20},
        {"arm": "smoothing_hi", "weight": 0.75, "auc": 0.82, "exit_lag_2022": 2,
         "whipsaw_2022": 3, "dd_capture_2022": 0.6, "ret2022": -0.10},
    ]
    # deterministic bootstrap CI stub (overlaps zero -> no degradation)
    def fake_ci(arm_id):
        return (-0.02, 0.05)
    summary = summarize_battery("v3_5b", rows, sharpe_ci_fn=fake_ci)
    verdicts = {r["arm"]: r["verdict"] for r in summary["arm_rows"]}
    assert verdicts["stock"] == "baseline"
    assert verdicts["smoothing"] == "SURVIVES"
    assert "kronos did not survive" in summary["tier2_trigger"] or \
           "Tier 2 NOT triggered" in summary["tier2_trigger"]


# ---------------------------------------------------------------------------
# Fix 2: skipped-arm verdict semantics
# ---------------------------------------------------------------------------

def _make_skipped_rows():
    """Minimal row set: stock evaluated; kronos and vix skipped; smoothing evaluated."""
    return [
        {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
         "whipsaw_2022": 6, "dd_capture_2022": 0.9, "ret2022": -0.30},
        # kronos and vix are skipped (e.g. --smoke or --arms smoothing)
        {"arm": "kronos", "weight": 0.5, "skipped_arm": True, "error": None},
        {"arm": "vix", "weight": 0.5, "skipped_arm": True, "error": None},
        # smoothing + neighbors evaluated
        {"arm": "smoothing", "weight": 0.5, "auc": 0.82, "exit_lag_2022": 3,
         "whipsaw_2022": 4, "dd_capture_2022": 0.7, "ret2022": -0.13},
        {"arm": "smoothing_lo", "weight": 0.25, "auc": 0.82, "exit_lag_2022": 4,
         "whipsaw_2022": 5, "dd_capture_2022": 0.8, "ret2022": -0.20},
        {"arm": "smoothing_hi", "weight": 0.75, "auc": 0.82, "exit_lag_2022": 2,
         "whipsaw_2022": 3, "dd_capture_2022": 0.6, "ret2022": -0.10},
        # diagnostic neighbors of skipped kronos/vix are also absent (skipped)
        {"arm": "kronos_lo", "weight": 0.25, "skipped_arm": True, "error": None},
        {"arm": "kronos_hi", "weight": 0.75, "skipped_arm": True, "error": None},
        {"arm": "vix_lo", "weight": 0.25, "skipped_arm": True, "error": None},
        {"arm": "vix_hi", "weight": 0.75, "skipped_arm": True, "error": None},
    ]


def test_skipped_arms_get_skipped_verdict():
    """Skipped arms (skipped_arm=True) receive verdict 'skipped (not evaluated)'."""
    from jutsu_engine.audit.battery import summarize_battery
    rows = _make_skipped_rows()
    summary = summarize_battery("v3_5b", rows, sharpe_ci_fn=lambda _: (-0.02, 0.05))
    verdicts = {r["arm"]: r["verdict"] for r in summary["arm_rows"]}
    assert verdicts["kronos"] == "skipped (not evaluated)"
    assert verdicts["vix"] == "skipped (not evaluated)"


def test_skipped_arms_do_not_affect_surviving_arms():
    """Skipped kronos/vix do not contaminate smoothing's verdict or the flatness table."""
    from jutsu_engine.audit.battery import summarize_battery
    rows = _make_skipped_rows()
    summary = summarize_battery("v3_5b", rows, sharpe_ci_fn=lambda _: (-0.02, 0.05))
    verdicts = {r["arm"]: r["verdict"] for r in summary["arm_rows"]}
    assert verdicts["smoothing"] == "SURVIVES"
    assert verdicts["stock"] == "baseline"
    # Flatness table must only contain smoothing (not kronos or vix which were skipped)
    flatness_arm_ids = {r["arm"] for r in summary["flatness_rows"]}
    assert "kronos" not in flatness_arm_ids
    assert "vix" not in flatness_arm_ids
    assert "smoothing" in flatness_arm_ids


def test_skipped_arms_excluded_from_flatness_table():
    """Skipped gated arms produce no flatness row — they are excluded, not scored."""
    from jutsu_engine.audit.battery import summarize_battery
    rows = _make_skipped_rows()
    summary = summarize_battery("v3_5b", rows, sharpe_ci_fn=lambda _: (-0.02, 0.05))
    flatness_arm_ids = [r["arm"] for r in summary["flatness_rows"]]
    # kronos and vix were skipped — must not appear
    assert "kronos" not in flatness_arm_ids
    assert "vix" not in flatness_arm_ids


# ---------------------------------------------------------------------------
# Fix 4: _sign_display exclusion semantics
# ---------------------------------------------------------------------------

def test_sign_display_returns_excl_for_none():
    """_sign_display returns 'excl' when any value is None (mirrors flatness exclusion)."""
    from jutsu_engine.audit.battery import _sign_display
    assert _sign_display(None, -1.0, -0.5) == "excl"
    assert _sign_display(-1.0, None, -0.5) == "excl"
    assert _sign_display(-1.0, -0.5, None) == "excl"


def test_sign_display_returns_excl_for_inf():
    """_sign_display returns 'excl' when any value is ±inf (mirrors flatness exclusion)."""
    from jutsu_engine.audit.battery import _sign_display
    assert _sign_display(float("inf"), -1.0, -0.5) == "excl"
    assert _sign_display(-1.0, float("-inf"), -0.5) == "excl"
    assert _sign_display(-1.0, -0.5, float("nan")) == "excl"


def test_sign_display_returns_true_when_all_same_sign():
    """_sign_display returns True when all three finite values share the same sign."""
    from jutsu_engine.audit.battery import _sign_display
    assert _sign_display(-1.0, -2.0, -0.5) is True
    assert _sign_display(0.1, 0.2, 0.3) is True
    assert _sign_display(0.0, 0.0, 0.0) is True


def test_sign_display_returns_false_on_sign_flip():
    """_sign_display returns False when a sign flip is present."""
    from jutsu_engine.audit.battery import _sign_display
    assert _sign_display(-1.0, -2.0, 0.5) is False   # hi flips positive
    assert _sign_display(1.0, -0.5, 0.3) is False     # lo flips negative


# ---------------------------------------------------------------------------
# Fix 3: per-episode transition section in the battery report (smoke-style)
# ---------------------------------------------------------------------------

def _make_fake_ts_csv(tmp_path, arm_id: str, episodes_dates: list) -> str:
    """Write a minimal regime timeseries CSV that covers the given episode date ranges."""
    import pandas as pd
    from datetime import date, timedelta
    # Build a daily series spanning 2019-08-01 to 2025-12-31 covering all episodes.
    start = date(2019, 8, 1)
    end = date(2025, 12, 31)
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    n = len(days)
    # Defensive in first half (cells 4-6), offensive in second half (cells 1-3)
    cells = [f"Cell_{4 if i < n // 2 else 1}" for i in range(n)]
    dates_str = [f"{d} 00:00:00-08:00" for d in days]
    df = pd.DataFrame({
        "Date": dates_str,
        "Regime": cells,
        "Trend": ["Sideways"] * n,
        "Vol": (["High"] * (n // 2) + ["Low"] * (n - n // 2)),
        "QQQ_Close": [300.0] * n,
        "QQQ_Daily_Return": [-0.005 if i < n // 2 else 0.002 for i in range(n)],
        "Portfolio_Value": [10000.0] * n,
        "Strategy_Daily_Return": [-0.003 if i < n // 2 else 0.001 for i in range(n)],
    })
    out = tmp_path / f"regime_{arm_id}.csv"
    df.to_csv(out, index=False)
    return str(out)


def test_build_transition_section_includes_stock_arm_first(tmp_path, monkeypatch):
    """_build_transition_section emits stock arm rows first with all portfolio_scored episodes."""
    import jutsu_engine.cli.commands.audit as audit_cli
    from jutsu_engine.audit import transitions as tr

    stock_csv = _make_fake_ts_csv(tmp_path, "stock", [])
    smoothing_csv = _make_fake_ts_csv(tmp_path, "smoothing", [])

    rows = [
        {"arm": "stock", "weight": None, "regime_timeseries_csv": stock_csv},
        {"arm": "smoothing", "weight": 0.5, "regime_timeseries_csv": smoothing_csv},
        # skipped arms
        {"arm": "kronos", "weight": 0.5, "skipped_arm": True, "error": None},
        {"arm": "vix", "weight": 0.5, "skipped_arm": True, "error": None},
    ]

    from jutsu_engine.audit.battery import TIER1_PORTFOLIO_START
    md = audit_cli._build_transition_section(rows, tr, TIER1_PORTFOLIO_START)

    # Must contain the transition-metrics header
    assert "Transition metrics" in md
    # Stock rows must appear before smoothing rows
    stock_pos = md.index("| stock |")
    smooth_pos = md.index("| smoothing |")
    assert stock_pos < smooth_pos, "stock arm must appear before smoothing in transition section"
    # At least one portfolio_scored episode must appear
    all_episodes = [ep for ep in tr.load_episodes() if ep.portfolio_scored]
    for ep in all_episodes:
        assert ep.id in md, f"episode {ep.id} missing from transition section"
    # Skipped arms must not appear in the transition section
    assert "| kronos |" not in md
    assert "| vix |" not in md


def test_build_transition_section_empty_when_no_csvs(tmp_path):
    """_build_transition_section returns empty string when no arm has a regime CSV."""
    import jutsu_engine.cli.commands.audit as audit_cli
    from jutsu_engine.audit import transitions as tr
    from jutsu_engine.audit.battery import TIER1_PORTFOLIO_START

    rows = [
        {"arm": "stock", "weight": None, "skipped_arm": False},  # no regime_timeseries_csv
        {"arm": "kronos", "weight": 0.5, "skipped_arm": True},
    ]
    md = audit_cli._build_transition_section(rows, tr, TIER1_PORTFOLIO_START)
    assert md == ""
