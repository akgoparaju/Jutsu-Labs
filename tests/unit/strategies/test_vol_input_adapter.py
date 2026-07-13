"""Unit + engine tests for the vol-input adapter (identity + blend behavior)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b_VolInput import (
    Hierarchical_Adaptive_v3_5b_VolInput,
)


class _Bar:
    def __init__(self, ts):
        self.timestamp = ts


def _make_adapter(series_map=None, weight="0.5"):
    """Adapter with no live-YAML; series injected as an in-memory date->value map."""
    s = Hierarchical_Adaptive_v3_5b_VolInput(
        vol_input_series=None, vol_blend_weight=Decimal(weight))
    # Inject the parsed series directly (bypasses CSV I/O for unit tests).
    s._vol_series_map = series_map or {}
    return s


def test_none_series_is_passthrough(monkeypatch):
    """With no series, _calculate_volatility_zscore returns the base vol_z unchanged."""
    s = _make_adapter(series_map={})
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.5"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.5")


def test_blend_math_at_weight_half(monkeypatch):
    """blended = 0.5*vol_z + 0.5*series[date] when the date has a finite value."""
    s = _make_adapter(series_map={date(2020, 1, 3): 3.0}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    # 0.5*1.0 + 0.5*3.0 = 2.0
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("2.0")


def test_missing_date_falls_back_to_pure_vol_z(monkeypatch):
    """A date with no series value falls back to pure vol_z (= stock behavior)."""
    s = _make_adapter(series_map={date(2020, 1, 6): 5.0}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]   # no entry for this date
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.0")


def test_nan_series_value_falls_back(monkeypatch):
    """A NaN series value (warmup) falls back to pure vol_z."""
    import math
    s = _make_adapter(series_map={date(2020, 1, 3): float("nan")}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.0")


def test_base_none_z_passes_through_none(monkeypatch):
    """When base vol_z is None (warmup), the adapter returns None (no blend)."""
    s = _make_adapter(series_map={date(2020, 1, 3): 3.0}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: None)
    assert s._calculate_volatility_zscore(pd.Series([1.0])) is None


def test_load_series_map_parses_iso_dates_from_csv(tmp_path):
    """_load_series_map parses a builder CSV (comment header + ISO dates) to date keys."""
    from jutsu_engine.audit.input_series import write_series
    df = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-03", "2020-01-06"], utc=True),
        "value": [3.0, 4.0]})
    csv = write_series(tmp_path / "iso.csv", df, source="t", provenance="tz test")
    mp = Hierarchical_Adaptive_v3_5b_VolInput._load_series_map(csv)
    assert mp == {date(2020, 1, 3): 3.0, date(2020, 1, 6): 4.0}


def test_tz_aware_bar_timestamp_normalizes_to_iso_series_date(monkeypatch):
    """A tz-aware bar timestamp matches an ISO series date after .date() normalization."""
    s = _make_adapter(series_map={date(2020, 1, 3): 3.0}, weight="0.5")
    # US/Eastern close 16:00 on 2020-01-03 stays on 2020-01-03 after .date().
    s._bars = [_Bar(pd.Timestamp("2020-01-03 16:00", tz="US/Eastern"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    # matched -> blended 0.5*1.0 + 0.5*3.0 = 2.0 (date normalization consistent)
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("2.0")


def test_tz_date_mismatch_falls_back_to_pure_vol_z(monkeypatch):
    """A bar whose local date differs from every series key falls back to pure vol_z."""
    s = _make_adapter(series_map={date(2020, 1, 3): 3.0}, weight="0.5")
    # A 2020-01-02 bar has no series entry -> no blend (mismatch is safe, not silent skew).
    s._bars = [_Bar(pd.Timestamp("2020-01-02 16:00", tz="US/Eastern"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.0")


def test_identity_no_series_equals_stock_v3_5b_db_gated(tmp_path):
    """Adapter with no series produces a bit-identical regime stream to stock v3.5b."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable (identity test needs the engine)")

    from jutsu_engine.audit.battery import run_regime_backtest

    # stock v3_5b via the live YAML; adapter constructed from the SAME golden params.
    stock_csv = run_regime_backtest(
        strategy_id="v3_5b", vol_input_series=None, vol_blend_weight=None,
        start=date(2010, 2, 1), end=date.today(),
        output_dir=str(tmp_path / "stock"))
    adapter_csv = run_regime_backtest(
        strategy_id="v3_5b", vol_input_series=None,
        vol_blend_weight="0.5",              # weight is irrelevant when series is None
        start=date(2010, 2, 1), end=date.today(),
        output_dir=str(tmp_path / "adapter"))

    a = pd.read_csv(stock_csv)[["Date", "Regime", "Trend", "Vol"]]
    b = pd.read_csv(adapter_csv)[["Date", "Regime", "Trend", "Vol"]]
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_short_window_blend_changes_vol_states_db_gated(tmp_path):
    """A synthetic high-value series blended at w=0.5 flips more bars to High vol."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable")

    from jutsu_engine.audit.battery import run_regime_backtest
    from jutsu_engine.audit.input_series import write_series

    # Build a synthetic series that is strongly positive over 2021 (pushes toward High).
    dates = pd.date_range("2020-06-01", "2022-06-01", freq="B")
    series_df = pd.DataFrame({"date": dates, "value": [5.0] * len(dates)})
    csv = write_series(tmp_path / "synthetic.csv", series_df, source="synthetic",
                       provenance="test: constant +5 to force High-vol")

    stock = run_regime_backtest("v3_5b", None, None, date(2020, 6, 1),
                                date(2022, 6, 1), str(tmp_path / "stock"))
    blended = run_regime_backtest("v3_5b", str(csv), "0.5", date(2020, 6, 1),
                                  date(2022, 6, 1), str(tmp_path / "blend"))
    a = pd.read_csv(stock)
    b = pd.read_csv(blended)
    # blended should classify strictly MORE High-vol days than stock (the +5 push)
    assert (b["Vol"] == "High").sum() > (a["Vol"] == "High").sum()
