"""Unit tests for vol-input series builders (pure + DB-gated VIX anchor)."""
import math

import numpy as np
import pandas as pd
import pytest

from jutsu_engine.audit.input_series import (
    z_ema5_pipeline,
    dedup_vix_daily,
    SERIES_COLUMNS,
)


def test_z_ema5_pipeline_leading_warmup_is_nan():
    """z_ema5_pipeline preserves leading NaN for the first (window-1) rows."""
    values = pd.Series(np.arange(1, 260, dtype=float))
    out = z_ema5_pipeline(values, window=200, ema_span=5)
    assert out.isna().iloc[:199].all()      # first 199 are warmup NaN (need 200)
    assert not math.isnan(out.iloc[-1])      # a real value once warmed up


def test_z_ema5_pipeline_causality_prefix_identical():
    """Truncating the input at X yields an identical value prefix (T-1 causality)."""
    rng = np.random.default_rng(0)
    values = pd.Series(rng.normal(size=400))
    full = z_ema5_pipeline(values, window=200, ema_span=5)
    truncated = z_ema5_pipeline(values.iloc[:300], window=200, ema_span=5)
    # the first 300 values of `full` must equal `truncated` exactly (trailing-only)
    pd.testing.assert_series_equal(
        full.iloc[:300].reset_index(drop=True),
        truncated.reset_index(drop=True),
        check_names=False,
    )


def test_dedup_vix_keeps_deterministic_row_per_date():
    """dedup_vix_daily keeps the earliest-timestamp row per date (real close wins)."""
    df = pd.DataFrame({
        "date": pd.to_datetime(
            ["2020-03-16 05:00", "2020-03-16 22:00", "2020-03-17 05:00"], utc=True),
        "close": [82.69, 75.91, 76.45],
    })
    out = dedup_vix_daily(df)
    assert len(out) == 2
    # 2020-03-16 keeps the 05:00 row (real CBOE peak close 82.69)
    row = out[out["date"].dt.date == pd.Timestamp("2020-03-16").date()]
    assert float(row["close"].iloc[0]) == 82.69


def test_series_columns_schema():
    """SERIES_COLUMNS defines the shared CSV schema for all arms."""
    assert SERIES_COLUMNS == ["date", "value", "source", "constructed_at"]


def test_build_vix_series_anchor_and_causality_db_gated():
    """build_vix_series recovers the 82.69 anchor and is causal (DB-gated)."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable")

    from jutsu_engine.audit.input_series import build_vix_series
    ser = build_vix_series(engine)          # raises if the anchor is wrong
    assert "value" in ser.columns and len(ser) > 1000
    # value column has warmup NaN then finite values
    assert ser["value"].notna().sum() > 500


# ---------------------------------------------------------------------------
# Task 6: Kronos builder tests
# ---------------------------------------------------------------------------


def test_kronos_parquet_checksum_matches_sidecar():
    """The copied Kronos parquet matches its recorded .sha256 sidecar."""
    import hashlib
    from jutsu_engine.audit.config import PROJECT_ROOT
    pq = PROJECT_ROOT / "claudedocs" / "inputs" / "QQQ_kronos_base.parquet"
    sidecar = pq.with_suffix(".parquet.sha256")
    if not pq.exists() or not sidecar.exists():
        pytest.skip("kronos parquet not present in this checkout")
    digest = hashlib.sha256(pq.read_bytes()).hexdigest()
    recorded = sidecar.read_text().split()[0]
    assert digest == recorded, "kronos parquet checksum drifted from sidecar"


def test_build_kronos_series_selects_horizon_5_and_pipelines():
    """build_kronos_from_frame filters horizon==5, z-EMA5s std_return, T-1 causal."""
    from jutsu_engine.audit.input_series import build_kronos_from_frame
    n = 260
    dates = pd.date_range("2019-08-06", periods=n, freq="B")
    frame = pd.DataFrame({
        "timestamp": list(dates) * 2,
        "horizon": [5] * n + [20] * n,          # H=20 rows must be ignored
        "std_return": list(np.linspace(0.02, 0.05, n)) + [9.9] * n,
    })
    out = build_kronos_from_frame(frame, window=200, ema_span=5)
    assert list(out.columns) == ["date", "value"]
    assert len(out) == n                        # one row per H=5 timestamp
    assert out["value"].isna().iloc[:199].all() # warmup NaN preserved
    assert not math.isnan(out["value"].iloc[-1])


def test_build_kronos_from_frame_causality():
    """Truncating the kronos frame yields an identical value prefix (causal)."""
    from jutsu_engine.audit.input_series import build_kronos_from_frame
    n = 300
    dates = pd.date_range("2019-08-06", periods=n, freq="B")
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({
        "timestamp": dates, "horizon": 5,
        "std_return": np.abs(rng.normal(0.03, 0.01, n)),
    })
    full = build_kronos_from_frame(frame, window=200, ema_span=5)
    trunc = build_kronos_from_frame(frame.iloc[:250], window=200, ema_span=5)
    pd.testing.assert_series_equal(
        full["value"].iloc[:250].reset_index(drop=True),
        trunc["value"].reset_index(drop=True), check_names=False)
