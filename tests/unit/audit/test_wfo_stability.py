"""DB-free unit tests for Module 1 WFO parameter-stability study."""
from datetime import date

from jutsu_engine.audit.wfo_stability import WFOWindow, generate_windows
from jutsu_engine.audit.wfo_stability import (
    WFO_GRID_AXES, WFO_QUARANTINE_OVERRIDES, WFO_INERT_EXCLUDED,
    expand_grid, combo_hash,
)


class TestGenerateWindows:
    def test_first_window_is_2p5y_is_then_0p5y_oos(self):
        """First window: 2.5y IS from start, then 0.5y OOS immediately after."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1))
        assert w[0].window_id == 1
        assert w[0].is_start == date(2010, 2, 1)
        assert w[0].is_end == date(2012, 8, 1)      # +2.5y
        assert w[0].oos_start == date(2012, 8, 1)
        assert w[0].oos_end == date(2013, 2, 1)     # +0.5y

    def test_windows_slide_by_half_year(self):
        """Consecutive windows slide their IS start by 0.5y."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1))
        assert w[1].is_start == date(2010, 8, 1)    # +0.5y slide

    def test_no_window_oos_exceeds_total_end(self):
        """The last window's OOS end never exceeds the total end date."""
        end = date(2026, 7, 1)
        w = generate_windows(date(2010, 2, 1), end)
        assert all(win.oos_end <= end for win in w)

    def test_window_count_is_about_26(self):
        """Full 2010-02 -> 2026-07 range yields ~26 windows."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1))
        assert 24 <= len(w) <= 28

    def test_windows_limit_truncates(self):
        """windows_limit caps the number of windows for smoke runs."""
        w = generate_windows(date(2010, 2, 1), date(2026, 7, 1), windows_limit=2)
        assert len(w) == 2


class TestExpandGrid:
    def test_product_plus_quarantine_is_31_combos(self):
        """3x3x3 sensitivity product + 4 quarantine sweeps = 31 combos."""
        combos = expand_grid()
        assert len(combos) == 31

    def test_first_combo_is_golden_anchor(self):
        """Combo 0 is the golden anchor (all axes at golden values)."""
        combos = expand_grid()
        c0 = combos[0]["overrides"]
        assert c0["upper_thresh_z"] == 1.0
        assert c0["realized_vol_window"] == 21
        assert c0["sma_slow"] == 140

    def test_quarantine_combos_swap_one_value_into_golden(self):
        """Each quarantine combo overrides golden with exactly one candidate value."""
        combos = expand_grid()
        quarantine = [c for c in combos if c["kind"] == "quarantine"]
        assert len(quarantine) == 4
        vals = {tuple(sorted(c["overrides"].items())) for c in quarantine}
        # golden axes + one quarantined key each
        assert any(("vol_crush_threshold", -0.12) in c["overrides"].items()
                   for c in quarantine)
        assert any(("bond_sma_fast", 24) in c["overrides"].items()
                   for c in quarantine)

    def test_inert_knobs_never_appear_in_any_combo(self):
        """No combo perturbs any of the six EXP-003 inert knobs."""
        combos = expand_grid()
        for c in combos:
            for k in WFO_INERT_EXCLUDED:
                # inert knobs may carry the golden value but are never a grid axis
                assert k not in WFO_GRID_AXES
                assert k not in c["overrides"], (
                    f"{k} is inert (EXP-003) but appears in combo {c['combo_id']}")

    def test_combo_hash_is_stable_and_order_independent(self):
        """combo_hash is deterministic and independent of dict insertion order."""
        a = combo_hash({"upper_thresh_z": 1.0, "sma_slow": 140})
        b = combo_hash({"sma_slow": 140, "upper_thresh_z": 1.0})
        assert a == b and len(a) == 16


from jutsu_engine.audit.wfo_stability import select_is_winner


class TestSelectISWinner:
    def test_picks_highest_is_sharpe(self):
        """Winner is the combo with the highest finite in-sample Sharpe."""
        rows = [
            {"hash": "a", "overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.5},
            {"hash": "b", "overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.9},
            {"hash": "c", "overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7},
        ]
        w = select_is_winner(rows)
        assert w["hash"] == "b"

    def test_skips_errored_rows(self):
        """Rows with non-finite is_sharpe (errored backtests) are ignored."""
        rows = [
            {"hash": "a", "overrides": {}, "is_sharpe": None},
            {"hash": "b", "overrides": {}, "is_sharpe": float("nan")},
            {"hash": "c", "overrides": {}, "is_sharpe": 0.3},
        ]
        assert select_is_winner(rows)["hash"] == "c"

    def test_all_errored_returns_none(self):
        """If every IS combo errored, there is no winner (returns None)."""
        rows = [{"hash": "a", "overrides": {}, "is_sharpe": None}]
        assert select_is_winner(rows) is None


# ---------------------------------------------------------------------------
# Task 4 — Stitched OOS-curve metrics
# ---------------------------------------------------------------------------
import numpy as np
import pandas as pd
import pytest

from jutsu_engine.audit.wfo_stability import stitch_oos_metrics


def _oos_frame(strategy_returns, qqq_returns, start="2013-01-01"):
    dates = pd.date_range(start, periods=len(strategy_returns), freq="D", tz="UTC")
    return pd.DataFrame({
        "Date": dates,
        "Strategy_Daily_Return": strategy_returns,
        "QQQ_Daily_Return": qqq_returns,
    })


class TestStitchOOSMetrics:
    def test_concatenates_windows_and_computes_on_stitched_series(self):
        """Metrics are computed on the concatenated series, NOT averaged per window."""
        w1 = _oos_frame([0.01, 0.01], [0.005, 0.005], "2013-01-01")
        w2 = _oos_frame([-0.01, 0.02], [0.0, 0.01], "2013-07-01")
        m = stitch_oos_metrics([w1, w2])
        assert m["oos_days"] == 4
        # total return = prod(1+r)-1 over ALL 4 days
        expected = (1.01 * 1.01 * 0.99 * 1.02) - 1.0
        assert abs(m["total_return"] - expected) < 1e-9

    def test_alpha_is_stitched_strategy_minus_qqq_total_return(self):
        """alpha_vs_qqq = stitched strategy total return - stitched QQQ total return."""
        w1 = _oos_frame([0.10], [0.04], "2013-01-01")
        m = stitch_oos_metrics([w1])
        assert abs(m["alpha_vs_qqq"] - (0.10 - 0.04)) < 1e-9

    def test_never_averages_per_window_sharpe(self):
        """A window with a huge per-window Sharpe cannot dominate the stitched Sharpe."""
        # Window A: tiny consistent gains (high per-window Sharpe).
        wa = _oos_frame([0.001] * 30, [0.0] * 30, "2013-01-01")
        # Window B: volatile (low per-window Sharpe).
        wb = _oos_frame(list(np.tile([0.05, -0.05], 15)), [0.0] * 30, "2013-07-01")
        stitched = stitch_oos_metrics([wa, wb])["sharpe"]
        # Averaging per-window Sharpes would give a very different (inflated) number;
        # the stitched Sharpe reflects the combined 60-day series volatility.
        combined = pd.concat([wa, wb])["Strategy_Daily_Return"]
        expected = float(combined.mean() / combined.std(ddof=1) * np.sqrt(252))
        assert abs(stitched - expected) < 1e-9

    def test_empty_input_returns_zero_metrics(self):
        """No OOS windows -> zeroed metrics, no crash."""
        m = stitch_oos_metrics([])
        assert m["oos_days"] == 0 and m["sharpe"] == 0.0

    def test_stitch_dedupes_shared_boundary_date(self):
        """Two frames sharing one boundary date count it once; metrics on deduped series."""
        # w1 covers 3 days; w2 starts on w1's last day (shared boundary bar).
        w1 = _oos_frame([0.01, 0.02, 0.03], [0.0, 0.0, 0.0], "2013-01-01")
        w2 = _oos_frame([0.03, 0.04], [0.0, 0.0], "2013-01-03")  # 2013-01-03 shared
        m = stitch_oos_metrics([w1, w2])
        # 3 + 2 = 5 rows, minus 1 duplicated boundary day = 4 unique days.
        assert m["oos_days"] == 4
        # total return uses each unique day once (boundary 0.03 counted once).
        expected = (1.01 * 1.02 * 1.03 * 1.04) - 1.0
        assert abs(m["total_return"] - expected) < 1e-9

    def test_stitch_drops_nan_rows_loudly(self):
        """One NaN return row → nan_rows_dropped==1, oos_days excludes it, one denominator."""
        w1 = _oos_frame([0.01, float("nan"), 0.02], [0.0, 0.0, 0.0], "2013-01-01")
        m = stitch_oos_metrics([w1])
        assert m["nan_rows_dropped"] == 1
        assert m["oos_days"] == 2
        # sharpe/total computed on the 2 surviving days only (shared denominator).
        surviving = pd.Series([0.01, 0.02])
        expected_total = (1.01 * 1.02) - 1.0
        assert abs(m["total_return"] - expected_total) < 1e-9
        expected_sharpe = float(
            surviving.mean() / surviving.std(ddof=1) * np.sqrt(252))
        assert abs(m["sharpe"] - expected_sharpe) < 1e-9

    def test_stitch_missing_column_raises(self):
        """A frame without QQQ_Daily_Return raises a ValueError naming the column."""
        bad = pd.DataFrame({
            "Date": pd.date_range("2013-01-01", periods=2, freq="D", tz="UTC"),
            "Strategy_Daily_Return": [0.01, 0.02],
        })
        with pytest.raises(ValueError, match="QQQ_Daily_Return"):
            stitch_oos_metrics([bad])

    def test_nan_rows_dropped_is_zero_normally(self):
        """Clean frames report nan_rows_dropped == 0."""
        w1 = _oos_frame([0.01, 0.02], [0.0, 0.0], "2013-01-01")
        assert stitch_oos_metrics([w1])["nan_rows_dropped"] == 0


# ---------------------------------------------------------------------------
# Task 5 — Parameter-drift table + golden top-decile share (spec §5/§10)
# ---------------------------------------------------------------------------
from jutsu_engine.audit.wfo_stability import (
    drift_table, param_value_distribution,
    golden_combo_top_decile_share, golden_axis_winner_share,
)
from jutsu_engine.audit.wfo_stability import GOLDEN_SENSITIVE, expand_grid


def _winner(window_id, overrides, is_sharpe):
    return {"window_id": window_id, "overrides": overrides, "is_sharpe": is_sharpe}


class TestDriftTable:
    def test_one_row_per_window_with_winner_params(self):
        """drift_table has one row per window carrying that window's winner params."""
        winners = [
            _winner(1, {"upper_thresh_z": 0.8, "realized_vol_window": 21, "sma_slow": 140}, 0.9),
            _winner(2, {"upper_thresh_z": 1.0, "realized_vol_window": 16, "sma_slow": 160}, 0.7),
        ]
        df = drift_table(winners)
        assert list(df["window_id"]) == [1, 2]
        assert df.loc[df["window_id"] == 1, "upper_thresh_z"].iloc[0] == 0.8

    def test_value_distribution_counts_winning_values_per_param(self):
        """param_value_distribution counts how often each value wins, per param."""
        winners = [
            _winner(1, {"upper_thresh_z": 0.8}, 0.9),
            _winner(2, {"upper_thresh_z": 1.0}, 0.7),
            _winner(3, {"upper_thresh_z": 0.8}, 0.6),
        ]
        dist = param_value_distribution(winners)
        assert dist["upper_thresh_z"][0.8] == 2
        assert dist["upper_thresh_z"][1.0] == 1


def _golden_hash():
    """Hash of the golden combo (combo_id 0) in the real 31-combo grid."""
    return expand_grid()[0]["hash"]


def _grid_window(golden_sharpe, other_sharpe=0.0, golden_rank=None):
    """Build a 31-combo IS window; optionally place golden at a target rank.

    If golden_rank is given, sharpes are assigned so the golden combo lands at
    exactly that 1-based rank (all non-golden combos get distinct descending
    sharpes and golden is inserted between them).
    """
    combos = expand_grid()
    golden_h = combos[0]["hash"]
    others = [c for c in combos if c["hash"] != golden_h]
    rows = []
    if golden_rank is None:
        rows.append({"hash": golden_h, "is_sharpe": golden_sharpe})
        for i, c in enumerate(others):
            rows.append({"hash": c["hash"], "is_sharpe": other_sharpe - i})
        return rows
    # Assign descending sharpes 30..1 to the 30 non-golden combos, then set the
    # golden combo's sharpe so it slots into `golden_rank` (1 = best).
    n_others = len(others)  # 30
    for i, c in enumerate(others):
        rows.append({"hash": c["hash"], "is_sharpe": float(n_others - i)})
    # rank r means (r-1) combos strictly above golden. Non-golden sharpes are
    # 30,29,...,1. Put golden between the (r-1)th and rth non-golden value.
    above = golden_rank - 1
    if above == 0:
        golden_s = float(n_others) + 0.5      # above the best
    else:
        golden_s = float(n_others - above) + 0.5  # between rank above & above+1
    rows.append({"hash": golden_h, "is_sharpe": golden_s})
    return rows


class TestGoldenComboTopDecileShare:
    def test_golden_combo_top_decile_share_ranks_within_grid(self):
        """Golden combo ranked 4th of 31 hits (cutoff 4); ranked 5th misses."""
        golden_h = _golden_hash()
        hit_window = _grid_window(None, golden_rank=4)      # rank 4 == cutoff
        miss_window = _grid_window(None, golden_rank=5)     # rank 5 > cutoff
        assert golden_combo_top_decile_share([hit_window], golden_h) == 1.0
        assert golden_combo_top_decile_share([miss_window], golden_h) == 0.0

    def test_golden_combo_tie_is_deterministic(self):
        """Golden tied with a rival at the cutoff boundary → same result any order."""
        golden_h = _golden_hash()
        combos = expand_grid()
        others = [c for c in combos if c["hash"] != golden_h]
        # Golden and one rival both sit at the rank-4 boundary sharpe; the two
        # combos ranked below the top-3 both have sharpe 5.0 (a tie). 3 combos
        # strictly above (sharpe 6,7,8) → golden shares the 4th/5th slots.
        rows = []
        top3 = others[:3]
        rival = others[3]
        fillers = others[4:]
        for i, c in enumerate(top3):
            rows.append({"hash": c["hash"], "is_sharpe": 8.0 - i})  # 8,7,6
        rows.append({"hash": golden_h, "is_sharpe": 5.0})           # tie
        rows.append({"hash": rival["hash"], "is_sharpe": 5.0})      # tie
        for c in fillers:
            rows.append({"hash": c["hash"], "is_sharpe": 1.0})
        import random
        forward = golden_combo_top_decile_share([list(rows)], golden_h)
        shuffled = list(rows)
        random.Random(7).shuffle(shuffled)
        reversed_rows = list(reversed(rows))
        assert forward == golden_combo_top_decile_share([shuffled], golden_h)
        assert forward == golden_combo_top_decile_share([reversed_rows], golden_h)

    def test_golden_combo_with_no_finite_sharpe_is_skipped(self):
        """A window where the golden combo errored is not counted (not a miss)."""
        golden_h = _golden_hash()
        errored = [{"hash": golden_h, "is_sharpe": None},
                   {"hash": "x", "is_sharpe": 0.5}]
        # Only skipped window → no counted windows → share 0.0 by convention.
        assert golden_combo_top_decile_share([errored], golden_h) == 0.0


class TestGoldenAxisWinnerShare:
    def test_share_of_windows_where_golden_is_axis_winner(self):
        """Diagnostic: fraction of windows where golden is the outright per-axis best."""
        window_is_rows = [
            # window 1: golden upper_thresh_z=1.0 is the best
            [{"overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.5},
             {"overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.9},
             {"overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7}],
            # window 2: golden upper_thresh_z=1.0 is worst
            [{"overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.9},
             {"overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.3},
             {"overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7}],
        ]
        share = golden_axis_winner_share(window_is_rows, "upper_thresh_z", 1.0)
        assert abs(share - 0.5) < 1e-9  # golden outright best in 1 of 2 windows

    def test_axis_winner_share_tie_counts_for_golden(self):
        """A tie between golden and a rival at the top counts as a golden win."""
        window_is_rows = [
            # golden tied with 0.8 for best → golden-favorable tie counts as a win
            [{"overrides": {"upper_thresh_z": 0.8}, "is_sharpe": 0.9},
             {"overrides": {"upper_thresh_z": 1.0}, "is_sharpe": 0.9},
             {"overrides": {"upper_thresh_z": 1.2}, "is_sharpe": 0.7}],
        ]
        assert golden_axis_winner_share(window_is_rows, "upper_thresh_z", 1.0) == 1.0

    def test_verdict_thresholds(self):
        """>=80% -> 'stable'; <50% -> 'unstable'; between -> 'inconclusive' (spec §10)."""
        from jutsu_engine.audit.wfo_stability import stability_verdict
        assert stability_verdict(0.85) == "stable"
        assert stability_verdict(0.40) == "unstable"
        assert stability_verdict(0.65) == "inconclusive"


# ---------------------------------------------------------------------------
# Task 6 — Single-backtest driver (IS combo / OOS window)
# ---------------------------------------------------------------------------
import glob
import tempfile
from datetime import date as _date

import jutsu_engine.audit.wfo_stability as wfo_mod


class TestRunOneBacktest:
    def test_backtest_failure_records_loud_error_row(self, monkeypatch):
        """A raising backtest yields a row with is_sharpe=None and an error string,
        never crashing the campaign."""
        import jutsu_engine.application.backtest_runner as br_mod

        class _BoomRunner:
            def __init__(self, config): pass
            def run(self, strategy, output_dir=None):
                raise RuntimeError("no database")

        monkeypatch.setattr(br_mod, "BacktestRunner", _BoomRunner)
        monkeypatch.setattr(wfo_mod, "build_overridden_strategy",
                            lambda sid, ov: object())

        row = wfo_mod.run_one_backtest(
            "v3_5b", {"hash": "h1", "combo_id": 0, "kind": "product",
                      "overrides": {"upper_thresh_z": 1.0}},
            ["QQQ"], _date(2010, 2, 1), _date(2012, 8, 1), phase="is")
        assert row["is_sharpe"] is None
        assert "no database" in row["error"]

    def test_error_row_leaves_no_tempdir(self, monkeypatch):
        """A failed backtest cleans up its throwaway tempdir (no plateau/wfo leak)."""
        import jutsu_engine.application.backtest_runner as br_mod

        class _BoomRunner:
            def __init__(self, config): pass
            def run(self, strategy, output_dir=None):
                raise RuntimeError("boom")

        monkeypatch.setattr(br_mod, "BacktestRunner", _BoomRunner)
        monkeypatch.setattr(wfo_mod, "build_overridden_strategy",
                            lambda sid, ov: object())
        before = set(glob.glob(tempfile.gettempdir() + "/wfo_*"))
        wfo_mod.run_one_backtest(
            "v3_5b", {"hash": "h", "combo_id": 0, "kind": "product", "overrides": {}},
            ["QQQ"], _date(2010, 2, 1), _date(2012, 8, 1), phase="is")
        assert set(glob.glob(tempfile.gettempdir() + "/wfo_*")) == before


# ---------------------------------------------------------------------------
# Task 7 — Checkpoint/resume helpers (WFO JSONL, row_key, fsync)
# ---------------------------------------------------------------------------
from jutsu_engine.audit.wfo_stability import (
    row_key, load_completed_keys, is_error_row, append_wfo_row,
)


class TestCheckpointHelpers:
    def test_row_key_combines_window_phase_hash(self):
        """row_key uniquely identifies a (window, phase, combo) unit of work."""
        assert row_key(3, "is", "abc123") == "3:is:abc123"

    def test_load_completed_keys_reads_written_rows(self, tmp_path):
        """Completed rows are recognized on resume by their row_key."""
        f = tmp_path / "wfo.jsonl"
        append_wfo_row(f, {"hash": "h", "combo_id": 0, "kind": "product",
                           "overrides": {}, "is_sharpe": 0.9, "oos_rows": None,
                           "window_id": 1, "phase": "is", "row_key": "1:is:h",
                           "error": None})
        assert load_completed_keys(f) == {"1:is:h"}

    def test_load_completed_keys_missing_file_is_empty(self, tmp_path):
        """A missing campaign file yields no completed keys (fresh campaign)."""
        assert load_completed_keys(tmp_path / "nope.jsonl") == set()

    def test_retry_errors_excludes_errored_rows(self, tmp_path):
        """With retry_errors=True, errored rows are NOT counted as completed."""
        f = tmp_path / "wfo.jsonl"
        append_wfo_row(f, {"hash": "h", "combo_id": 0, "kind": "product",
                           "overrides": {}, "is_sharpe": None, "oos_rows": None,
                           "window_id": 1, "phase": "is", "row_key": "1:is:h",
                           "error": "boom"})
        assert load_completed_keys(f, retry_errors=True) == set()
        assert load_completed_keys(f, retry_errors=False) == {"1:is:h"}
