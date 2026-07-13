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
