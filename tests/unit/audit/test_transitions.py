"""Unit tests for the crash-episode registry loader/validator (DB-free)."""
from datetime import date

import pytest

from jutsu_engine.audit.transitions import (
    Episode,
    load_episodes,
    validate_episodes,
)


def test_load_episodes_returns_eight_ordered_episodes():
    """load_episodes parses the shipped registry into 8 chronological Episodes."""
    eps = load_episodes()
    assert [e.id for e in eps] == [
        "dotcom", "gfc", "euro2011", "china2015",
        "q4_2018", "covid2020", "bear2022", "spring2025",
    ]
    assert eps[5].id == "covid2020"
    assert eps[5].peak == date(2020, 2, 19)
    assert eps[5].trough == date(2020, 3, 16)  # verified against QQQ closes (Task 2)
    assert eps[5].portfolio_scored is True
    assert eps[0].portfolio_scored is False  # dotcom = signal-only


def test_validate_episodes_rejects_peak_after_trough():
    """validate_episodes raises when an episode's peak is not before its trough."""
    bad = [Episode(id="x", peak=date(2020, 5, 1), trough=date(2020, 1, 1),
                   recovery=date(2020, 6, 1), portfolio_scored=True)]
    with pytest.raises(ValueError, match="peak .* must be before trough"):
        validate_episodes(bad)


def test_validate_episodes_rejects_duplicate_ids():
    """validate_episodes raises on duplicate episode ids."""
    dup = [
        Episode(id="x", peak=date(2020, 1, 1), trough=date(2020, 2, 1),
                recovery=date(2020, 3, 1), portfolio_scored=True),
        Episode(id="x", peak=date(2021, 1, 1), trough=date(2021, 2, 1),
                recovery=date(2021, 3, 1), portfolio_scored=True),
    ]
    with pytest.raises(ValueError, match="duplicate episode id"):
        validate_episodes(dup)


def _qqq_close_on_or_before(engine, d):
    """Latest QQQ close on trading date <= d (float), or None."""
    from sqlalchemy import text
    q = text(
        "SELECT close FROM market_data "
        "WHERE symbol='QQQ' AND timeframe='1D' AND (timestamp)::date <= :d "
        "ORDER BY timestamp DESC LIMIT 1"
    )
    with engine.connect() as c:
        row = c.execute(q, {"d": d}).fetchone()
    return float(row[0]) if row else None


def test_episode_dates_match_qqq():
    """Each episode peak/trough is a local QQQ extreme within a +/-10-day window."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        import pytest
        pytest.skip("market_data DB unavailable (verification is DB-gated)")

    from datetime import timedelta
    from jutsu_engine.audit.transitions import load_episodes

    def window_closes(center):
        from sqlalchemy import text
        q = text(
            "SELECT (timestamp)::date, close FROM market_data "
            "WHERE symbol='QQQ' AND timeframe='1D' "
            "AND (timestamp)::date BETWEEN :lo AND :hi ORDER BY timestamp"
        )
        with engine.connect() as c:
            rows = list(c.execute(q, {"lo": center - timedelta(days=15),
                                      "hi": center + timedelta(days=15)}))
        return [(r[0], float(r[1])) for r in rows]

    problems = []
    for e in load_episodes():
        peak_rows = window_closes(e.peak)
        trough_rows = window_closes(e.trough)
        if not peak_rows or not trough_rows:
            problems.append(f"{e.id}: no QQQ data around peak/trough")
            continue
        max_close = max(c for _, c in peak_rows)
        min_close = min(c for _, c in trough_rows)
        peak_close = dict(peak_rows).get(e.peak)
        trough_close = dict(trough_rows).get(e.trough)
        # peak must be the max close in its +/-15d neighborhood (within 0.5%)
        if peak_close is None or peak_close < max_close * 0.995:
            problems.append(
                f"{e.id}: peak {e.peak} close={peak_close} not the local max "
                f"(neighborhood max={max_close}); correct the YAML to the data"
            )
        if trough_close is None or trough_close > min_close * 1.005:
            problems.append(
                f"{e.id}: trough {e.trough} close={trough_close} not the local min "
                f"(neighborhood min={min_close}); correct the YAML to the data"
            )
    assert not problems, "\n".join(problems)


import pandas as pd


def _synthetic_ts(dates, cells, qqq_closes, strat_returns):
    """Build a regime-timeseries DataFrame with the CSV's exact columns."""
    return pd.DataFrame({
        "Date": pd.to_datetime(dates, utc=True),
        "Regime": [f"Cell_{c}" for c in cells],
        "Trend": ["-"] * len(dates),
        "Vol": ["-"] * len(dates),
        "QQQ_Close": qqq_closes,
        "QQQ_Daily_Return": pd.Series(qqq_closes).pct_change().fillna(0.0).tolist(),
        "Portfolio_Value": [1.0] * len(dates),
        "Strategy_Daily_Return": strat_returns,
    })


def test_trim_warmup_rows_drops_pre_start():
    """trim_warmup drops regime rows dated before start_date (EXP-006)."""
    from jutsu_engine.audit.transitions import trim_warmup
    ts = _synthetic_ts(
        ["2019-12-30", "2020-01-02", "2020-01-03"],
        [1, 1, 1], [100, 101, 102], [0.0, 0.01, 0.01],
    )
    trimmed = trim_warmup(ts, start=date(2020, 1, 1))
    assert len(trimmed) == 2
    assert trimmed["Date"].min() >= pd.Timestamp("2020-01-01", tz="UTC")


def test_exit_lag_days_counts_trading_days_to_defensive():
    """exit_lag_days = trading days from peak until first defensive cell (4/5/6)."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 8),
                 recovery=date(2020, 1, 15), portfolio_scored=True)
    dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
    cells = [1, 1, 1, 4, 4]              # defensive first appears on 2020-01-07
    ts = _synthetic_ts(dates, cells, [100, 100, 90, 85, 80],
                       [0.0, 0.0, -0.10, -0.05, -0.06])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    # peak index is 2020-01-03; defensive first at 2020-01-07 = 2 trading days later
    assert row["exit_lag_days"] == 2


def test_never_defensive_renders_exit_lag_none():
    """A strategy that never de-risks in [peak,trough] yields exit_lag_days=None."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 8),
                 recovery=date(2020, 1, 15), portfolio_scored=True)
    dates = ["2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
    cells = [1, 1, 1, 1]
    ts = _synthetic_ts(dates, cells, [100, 95, 90, 85], [0.0, -0.05, -0.05, -0.05])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    assert row["exit_lag_days"] is None
    assert row["days_defensive"] == 0


def test_drawdown_capture_ratio():
    """drawdown_capture = strat MaxDD / QQQ MaxDD within [peak,trough] (lower=better)."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 6),
                 recovery=date(2020, 1, 10), portfolio_scored=True)
    dates = ["2020-01-03", "2020-01-06"]
    # QQQ drops 20%; strategy (half exposure) drops 10% => capture ~0.5
    ts = _synthetic_ts(dates, [1, 4], [100, 80], [0.0, -0.10])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    assert 0.45 <= row["drawdown_capture"] <= 0.55


def test_episode_outside_series_span_is_skipped_loudly():
    """An episode fully outside the timeseries span yields a skipped=True row."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="old", peak=date(2001, 1, 3), trough=date(2001, 2, 6),
                 recovery=date(2001, 3, 10), portfolio_scored=True)
    dates = ["2020-01-03", "2020-01-06"]
    ts = _synthetic_ts(dates, [1, 4], [100, 80], [0.0, -0.10])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    assert row["skipped"] is True
    assert row["exit_lag_days"] is None


def test_flip_lead_lag_around_peak():
    """signal_flip_lead_lag returns trading days from peak to first High-vol flip."""
    from jutsu_engine.audit.transitions import Episode, signal_flip_lead_lag
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 10),
                 recovery=date(2020, 1, 20), portfolio_scored=True)
    # vol-state series (dates, vol): flips to High two days after peak
    dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    vol = ["Low", "Low", "Low", "High"]
    lead = signal_flip_lead_lag(dates, vol, ep)  # positive = lagging (after peak)
    assert lead == 2


def test_flip_count_ratio_vs_stock():
    """flip_count_ratio divides an arm's flip count by the stock arm's."""
    from jutsu_engine.audit.transitions import flip_count_ratio
    arm_vol = ["Low", "High", "Low", "High", "Low"]   # 4 flips
    stock_vol = ["Low", "Low", "High", "Low"]         # 2 flips
    assert flip_count_ratio(arm_vol, stock_vol) == 2.0


def test_auc_vol_state_at_t_plus_21_perfect_separator():
    """auc_vol_state_forward returns 1.0 when the score perfectly ranks t+21 state."""
    from jutsu_engine.audit.transitions import auc_vol_state_forward
    # score rises monotonically; future High-vol (label 1) has the higher scores
    scores = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    future_high = [0, 0, 0, 1, 1, 1]   # already the t+21 labels aligned by caller
    assert auc_vol_state_forward(scores, future_high) == 1.0


def test_auc_handles_single_class_returns_nan():
    """auc_vol_state_forward returns nan when the label vector is single-class."""
    import math
    from jutsu_engine.audit.transitions import auc_vol_state_forward
    assert math.isnan(auc_vol_state_forward([0.1, 0.2, 0.3], [1, 1, 1]))
