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
    assert eps[5].trough == date(2020, 3, 23)
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
