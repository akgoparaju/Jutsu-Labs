from datetime import date

from jutsu_engine.audit.live_recon import (
    ZSCORE_TOLERANCE,
    TNORM_TOLERANCE,
    categorize_day,
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
