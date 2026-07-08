from datetime import date, datetime, timezone

import pandas as pd
import pytest

from jutsu_engine.audit.db import (
    AuditDBUnavailable,
    build_engine_url,
    rows_to_bars_df,
    scheduler_snapshots_to_records,
)


class TestBuildEngineUrl:
    def test_missing_env_raises_audit_db_unavailable(self):
        """Missing POSTGRES_* vars raise AuditDBUnavailable mentioning POSTGRES."""
        with pytest.raises(AuditDBUnavailable, match="POSTGRES"):
            build_engine_url(env={})

    def test_builds_url_and_quotes_password(self):
        """Special chars in password are percent-encoded and raw password is absent."""
        env = {
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p@ss word",
            "POSTGRES_HOST": "h",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DATABASE": "db",
        }
        url = build_engine_url(env=env)
        # '@' and ' ' in password must be percent-encoded (%40, %20 / +).
        assert url.startswith("postgresql://u:")
        assert "@h:5432/db" in url
        assert "p@ss word" not in url  # raw password must not appear


class TestRowsToBarsDf:
    def test_reverses_to_chronological_and_types(self):
        """Rows arriving newest-first (DESC) are reversed to chronological order."""
        # Rows arrive newest-first (DESC); loader must reverse to chronological.
        rows = [
            (datetime(2025, 12, 3, tzinfo=timezone.utc), 3.0, 3.0, 3.0, 3.0, 30),
            (datetime(2025, 12, 2, tzinfo=timezone.utc), 2.0, 2.0, 2.0, 2.0, 20),
            (datetime(2025, 12, 1, tzinfo=timezone.utc), 1.0, 1.0, 1.0, 1.0, 10),
        ]
        df = rows_to_bars_df(rows)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert df["close"].tolist() == [1.0, 2.0, 3.0]  # chronological
        assert str(df["close"].dtype) == "float64"
        assert str(df["volume"].dtype) == "int64"

    def test_empty_rows_return_empty_df_with_columns(self):
        """Empty input yields an empty DataFrame with the correct column names."""
        df = rows_to_bars_df([])
        assert df.empty
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]


class TestSchedulerSnapshotsToRecords:
    def test_maps_columns_and_keeps_one_per_day(self):
        """Two rows for the same day keep the record with the latest timestamp."""
        # Two rows for the same day; keep the LATEST timestamp (authoritative EOD).
        rows = [
            # (strategy_id, ts, dt, cell, trend, vol, t_norm, z_score, total_equity, snapshot_source)
            ("v3_5b", datetime(2025, 12, 1, 20, 5, tzinfo=timezone.utc), date(2025, 12, 1),
             1, "BullStrong", "Low", 0.4, -0.3, 10100.0, "scheduler"),
            ("v3_5b", datetime(2025, 12, 1, 16, 0, tzinfo=timezone.utc), date(2025, 12, 1),
             1, "BullStrong", "Low", 0.4, -0.3, 10050.0, "scheduler"),
        ]
        recs = scheduler_snapshots_to_records(rows)
        assert len(recs) == 1
        r = recs[0]
        assert r["day"] == date(2025, 12, 1)
        assert r["strategy_cell"] == 1
        assert r["trend_state"] == "BullStrong"
        assert r["vol_state"] == "Low"
        assert r["t_norm"] == 0.4
        assert r["z_score"] == -0.3
        assert r["total_equity"] == 10100.0  # latest ts wins


# ---------------------------------------------------------------------------
# Task 10 — Trial-count inventory (pure shaper, no DB)
# ---------------------------------------------------------------------------
from jutsu_engine.audit.db import trial_count_records


class TestTrialCountRecords:
    def test_shapes_grouped_counts(self):
        """trial_count_records turns (strategy, optimizer, count) rows into dicts."""
        rows = [
            ("Hierarchical_Adaptive_v3_5b", "grid_search", 243),
            ("Hierarchical_Adaptive_v3_5b", "bayesian", 57),
            ("Hierarchical_Adaptive_v2_8", "grid_search", 400),
        ]
        recs = trial_count_records(rows)
        assert recs == [
            {"strategy_name": "Hierarchical_Adaptive_v2_8",
             "optimizer_type": "grid_search", "trials": 400},
            {"strategy_name": "Hierarchical_Adaptive_v3_5b",
             "optimizer_type": "bayesian", "trials": 57},
            {"strategy_name": "Hierarchical_Adaptive_v3_5b",
             "optimizer_type": "grid_search", "trials": 243},
        ]

    def test_none_optimizer_labeled(self):
        """A NULL optimizer_type is labeled '(unknown)', not dropped."""
        recs = trial_count_records([("S", None, 10)])
        assert recs[0]["optimizer_type"] == "(unknown)"

    def test_empty_rows(self):
        """No rows → empty list (no crash)."""
        assert trial_count_records([]) == []
