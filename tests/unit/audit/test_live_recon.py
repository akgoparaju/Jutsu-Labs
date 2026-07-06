from datetime import date

from jutsu_engine.audit.live_recon import (
    ZSCORE_TOLERANCE,
    TNORM_TOLERANCE,
    LiveReconResult,
    categorize_day,
    reconcile,
    summarize_diffs,
)


def _stored(**kw):
    base = dict(day=date(2026, 1, 5), strategy_cell=1, trend_state="BullStrong",
                vol_state="Low", t_norm=0.40, z_score=-0.30, total_equity=10000.0,
                snapshot_source="scheduler")
    base.update(kw)
    return base


def _replay(**kw):
    base = dict(strategy_cell=1, trend_state="BullStrong", vol_state="Low",
                t_norm=0.41, z_score=-0.28)
    base.update(kw)
    return base


class TestCategorizeDay:
    def test_all_match_within_tolerance_is_clean(self):
        """All fields within tolerance → category is match with no mismatches."""
        d = categorize_day(_stored(), _replay())
        assert d["categorical_match"] is True
        assert d["mismatches"] == []  # z/t within tolerance
        assert d["category"] == "match"

    def test_categorical_cell_mismatch_is_logic(self):
        """Categorical field mismatch on strategy_cell → logic category."""
        d = categorize_day(_stored(), _replay(strategy_cell=4))
        assert d["categorical_match"] is False
        assert any(m["field"] == "strategy_cell" and m["category"] == "logic"
                   for m in d["mismatches"])
        assert d["category"] == "logic"

    def test_zscore_out_of_tolerance_is_timing(self):
        """z_score diff exceeding tolerance with matching categoricals → timing."""
        d = categorize_day(_stored(z_score=-0.30), _replay(z_score=-0.60))
        # categorical still matches; z diff 0.30 > tolerance -> timing
        assert d["categorical_match"] is True
        assert any(m["field"] == "z_score" and m["category"] == "timing"
                   for m in d["mismatches"])
        assert d["category"] == "timing"

    def test_null_stored_zscore_is_missing_not_mismatch(self):
        """NULL stored z_score (backfill row) is skipped, not counted as mismatch."""
        d = categorize_day(_stored(z_score=None, snapshot_source="backfill"),
                           _replay(z_score=-0.90))
        assert not any(m["field"] == "z_score" for m in d["mismatches"])
        # categorical still compared; here they match -> overall match
        assert d["category"] == "match"

    def test_tolerances_are_positive(self):
        """Both continuous-field tolerances are strictly positive constants."""
        assert ZSCORE_TOLERANCE > 0
        assert TNORM_TOLERANCE > 0

    def test_zscore_at_exact_tolerance_is_match(self):
        """Diff exactly equal to tolerance is in-tolerance (boundary is exclusive)."""
        d = categorize_day(_stored(z_score=0.00), _replay(z_score=ZSCORE_TOLERANCE))
        assert d["category"] == "match"

    def test_data_gap_dominates_timing(self):
        """A stored categorical NULL (data) outranks an out-of-tolerance z (timing)."""
        d = categorize_day(_stored(strategy_cell=None, z_score=-0.30),
                           _replay(z_score=-0.90))
        assert d["category"] == "data"

    def test_nan_stored_zscore_is_flagged_as_data(self):
        """A NaN stored z_score is surfaced as a data anomaly, never a silent match."""
        d = categorize_day(_stored(z_score=float("nan")), _replay(z_score=-0.30))
        assert any(m["field"] == "z_score" and m["category"] == "data"
                   for m in d["mismatches"])
        assert d["category"] == "data"


class TestSummarizeDiffs:
    def test_counts_by_field_and_category(self):
        """summarize_diffs aggregates total, match, by_category, by_field, and mismatch_pct."""
        days = [
            categorize_day(_stored(), _replay()),                         # match
            categorize_day(_stored(), _replay(strategy_cell=4)),          # logic
            categorize_day(_stored(z_score=-0.30), _replay(z_score=-0.9)),# timing
        ]
        s = summarize_diffs(days)
        assert s["total_days"] == 3
        assert s["match_days"] == 1
        assert s["by_category"]["logic"] == 1
        assert s["by_category"]["timing"] == 1
        assert s["by_field"]["strategy_cell"] == 1
        assert s["by_field"]["z_score"] == 1
        # mismatch_pct = non-match days / total
        assert abs(s["mismatch_pct"] - (2 / 3 * 100)) < 1e-9


class TestReconcileOrchestration:
    def test_reconcile_pairs_days_and_summarizes(self):
        """reconcile pairs each stored day with its replay, summarizes, and tracks equity."""
        # Two stored scheduler days for one strategy.
        snapshots = [
            dict(day=date(2026, 1, 5), strategy_cell=1, trend_state="BullStrong",
                 vol_state="Low", t_norm=0.40, z_score=-0.30, total_equity=10000.0,
                 snapshot_source="scheduler"),
            dict(day=date(2026, 1, 6), strategy_cell=4, trend_state="Sideways",
                 vol_state="High", t_norm=0.10, z_score=1.20, total_equity=9950.0,
                 snapshot_source="scheduler"),
        ]

        # Fake replay: day 1 matches; day 2 replays a different cell (logic mismatch)
        # and a different equity (for divergence).
        def fake_replay_day(strategy_id, day):
            if day == date(2026, 1, 5):
                return dict(strategy_cell=1, trend_state="BullStrong", vol_state="Low",
                            t_norm=0.41, z_score=-0.28, replay_equity=10000.0)
            return dict(strategy_cell=5, trend_state="BearStrong", vol_state="High",
                        t_norm=0.10, z_score=1.19, replay_equity=9900.0)

        result = reconcile(
            strategy_id="v3_5b",
            snapshots=snapshots,
            replay_day=fake_replay_day,
            source_counts={"scheduler": 2, "refresh": 3},
        )
        assert isinstance(result, LiveReconResult)
        assert result.strategy_id == "v3_5b"
        assert result.summary["total_days"] == 2
        assert result.summary["by_category"]["logic"] == 1
        assert result.summary["mismatch_days"] == 1
        assert result.source_counts == {"scheduler": 2, "refresh": 3}
        # Equity divergence: replay 9900 vs stored 9950 on day 2 -> abs diff tracked.
        assert result.pnl_divergence["final_stored_equity"] == 9950.0
        assert result.pnl_divergence["final_replay_equity"] == 9900.0
        assert result.day_table[1]["category"] == "logic"
        # divergence computed on last common day (day 2: stored 9950, replay 9900)
        assert result.pnl_divergence["divergence_day"] == date(2026, 1, 6)
        assert result.pnl_divergence["abs_divergence"] == 50.0

    def test_reconcile_empty_snapshots_is_graceful(self):
        """reconcile with no snapshots returns zeroed summary and None equity endpoints."""
        result = reconcile("v3_5b", snapshots=[], replay_day=lambda s, d: {},
                           source_counts={})
        assert result.summary["total_days"] == 0
        assert result.pnl_divergence["final_stored_equity"] is None

    def test_replay_gap_is_data_not_logic(self):
        """A day the replay cannot reproduce (None) is a data gap, not a logic mismatch."""
        snapshots = [dict(day=date(2026, 1, 5), strategy_cell=1, trend_state="BullStrong",
                          vol_state="Low", t_norm=0.40, z_score=-0.30,
                          total_equity=10000.0, snapshot_source="scheduler")]
        result = reconcile("v3_5b", snapshots=snapshots,
                           replay_day=lambda s, d: None, source_counts={})
        assert result.summary["by_category"].get("logic") is None
        assert result.summary["by_category"]["data"] == 1
        assert result.day_table[0]["category"] == "data"
