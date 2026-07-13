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
