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
# Fix 2 — OOS span-filter (strips BacktestRunner's pre-oos_start warmup rows)
# ---------------------------------------------------------------------------
from jutsu_engine.audit.wfo_stability import filter_oos_frame_to_span


def _oos_frame_dates(date_strings, strat_returns, qqq_returns):
    """OOS frame with explicit Date strings (to model warmup-prefixed CSV output)."""
    return pd.DataFrame({
        "Date": date_strings,
        "Strategy_Daily_Return": strat_returns,
        "QQQ_Daily_Return": qqq_returns,
    })


class TestFilterOOSFrameToSpan:
    def test_drops_warmup_rows_before_oos_start(self):
        """Rows dated before oos_start (warmup zeros) are removed; in-span rows kept."""
        # 3 warmup rows (dated before the OOS window) + 2 in-span rows.
        dates = ["2011-04-08", "2011-04-11", "2011-04-12",   # warmup (< oos_start)
                 "2012-08-01", "2012-08-02"]                 # in-span
        frame = _oos_frame_dates(dates, [0.0, 0.0, 0.0, 0.01, 0.02],
                                 [0.0, 0.0, 0.0, 0.005, 0.006])
        out = filter_oos_frame_to_span(frame, date(2012, 8, 1), date(2013, 2, 1))
        assert list(out["Date"]) == ["2012-08-01", "2012-08-02"]
        assert list(out["Strategy_Daily_Return"]) == [0.01, 0.02]

    def test_span_is_half_open_excludes_oos_end(self):
        """The span is [oos_start, oos_end): the oos_end boundary bar is excluded."""
        dates = ["2012-08-01", "2013-02-01"]   # oos_start, oos_end
        frame = _oos_frame_dates(dates, [0.01, 0.02], [0.0, 0.0])
        out = filter_oos_frame_to_span(frame, date(2012, 8, 1), date(2013, 2, 1))
        assert list(out["Date"]) == ["2012-08-01"]   # oos_end dropped (half-open)

    def test_handles_tz_suffixed_date_strings(self):
        """Date strings with a time/tz suffix compare on the YYYY-MM-DD prefix."""
        dates = ["2011-04-08 05:00:00-07:00", "2012-08-01 06:00:00-08:00"]
        frame = _oos_frame_dates(dates, [0.0, 0.01], [0.0, 0.0])
        out = filter_oos_frame_to_span(frame, date(2012, 8, 1), date(2013, 2, 1))
        assert list(out["Strategy_Daily_Return"]) == [0.01]


def _warmup_polluted_oos_run_fn(strategy_id, combo, symbols, start, end, phase,
                                initial_capital="10000"):
    """Fake worker whose OOS CSV includes warmup-zero rows dated BEFORE `start`.

    Models BacktestRunner: for the OOS phase it emits ~330 leading warmup rows
    (Strategy_Daily_Return == 0.0, dated 2 years before oos_start) followed by the
    in-span daily returns. IS rows are ranked by upper_thresh_z as in _fake_run_fn.
    Module-level (picklable) for spawn safety.
    """
    utz = combo["overrides"].get("upper_thresh_z", 1.0)
    if phase == "is":
        return {"hash": combo["hash"], "combo_id": combo["combo_id"],
                "kind": combo["kind"], "phase": "is",
                "overrides": combo["overrides"], "is_sharpe": float(utz),
                "oos_rows": None, "error": None}
    # Warmup: 10 zero-return rows dated well before `start` (the oos_start), exactly
    # as BacktestRunner prepends warmup history to the emitted CSV.
    warm_dates = pd.date_range("2000-01-01", periods=10, freq="D", tz="UTC")
    warm = [{"Date": str(d), "Strategy_Daily_Return": 0.0,
             "QQQ_Daily_Return": 0.0} for d in warm_dates]
    # In-span: 5 real return days starting at oos_start.
    span_dates = pd.date_range(str(start), periods=5, freq="D", tz="UTC")
    span = [{"Date": str(d), "Strategy_Daily_Return": 0.01,
             "QQQ_Daily_Return": 0.005} for d in span_dates]
    return {"hash": combo["hash"], "combo_id": combo["combo_id"],
            "kind": combo["kind"], "phase": "oos",
            "overrides": combo["overrides"], "is_sharpe": 0.8,
            "oos_rows": warm + span, "error": None}


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

    def test_oos_extraction_trims_warmup_rows_at_source(self, monkeypatch, tmp_path):
        """Belt-and-braces: run_one_backtest trims warmup rows from the OOS CSV so
        freshly captured oos_rows carry only the window's [oos_start, oos_end) span."""
        import jutsu_engine.application.backtest_runner as br_mod

        # Emit a regime-timeseries CSV with 3 warmup rows (before oos_start) + 2 in-span.
        csv_path = tmp_path / "regime_ts.csv"
        pd.DataFrame({
            "Date": ["2011-04-08 05:00:00-07:00", "2011-04-11 05:00:00-07:00",
                     "2011-04-12 05:00:00-07:00",                       # warmup
                     "2012-08-01 06:00:00-08:00", "2012-08-02 06:00:00-08:00"],  # in-span
            "Strategy_Daily_Return": [0.0, 0.0, 0.0, 0.01, 0.02],
            "QQQ_Daily_Return": [0.0, 0.0, 0.0, 0.005, 0.006],
        }).to_csv(csv_path, index=False)

        class _CSVRunner:
            def __init__(self, config): pass
            def run(self, strategy, output_dir=None):
                return {"sharpe_ratio": 0.9,
                        "regime_timeseries_csv": str(csv_path)}

        monkeypatch.setattr(br_mod, "BacktestRunner", _CSVRunner)
        monkeypatch.setattr(wfo_mod, "build_overridden_strategy",
                            lambda sid, ov: object())

        row = wfo_mod.run_one_backtest(
            "v3_5b", {"hash": "h", "combo_id": 0, "kind": "oos_winner",
                      "overrides": {}},
            ["QQQ"], _date(2012, 8, 1), _date(2013, 2, 1), phase="oos")
        assert row["error"] is None
        dates = [r["Date"][:10] for r in row["oos_rows"]]
        assert dates == ["2012-08-01", "2012-08-02"]   # warmup rows trimmed at source


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


# ---------------------------------------------------------------------------
# Task 8 — Campaign runner (2-pass IS/OOS, resume, circuit breaker, single-writer)
# ---------------------------------------------------------------------------
import json
from datetime import date as _date2

from jutsu_engine.audit.wfo_stability import (
    run_campaign, WFOCampaignResult, reload_wfo_rows as _reload_wfo_rows,
)


def _fake_run_fn(strategy_id, combo, symbols, start, end, phase,
                 initial_capital="10000"):
    """Deterministic fake: IS Sharpe rises with upper_thresh_z; OOS emits 5 days.

    Module-level (picklable) so it is spawn-safe for the parallel path too.
    """
    utz = combo["overrides"].get("upper_thresh_z", 1.0)
    if phase == "is":
        return {"hash": combo["hash"], "combo_id": combo["combo_id"],
                "kind": combo["kind"], "phase": "is",
                "overrides": combo["overrides"], "is_sharpe": float(utz),
                "oos_rows": None, "error": None}
    dates = pd.date_range(str(start), periods=5, freq="D", tz="UTC")
    rows = [{"Date": str(d), "Strategy_Daily_Return": 0.01,
             "QQQ_Daily_Return": 0.005} for d in dates]
    return {"hash": combo["hash"], "combo_id": combo["combo_id"],
            "kind": combo["kind"], "phase": "oos",
            "overrides": combo["overrides"], "is_sharpe": 0.8,
            "oos_rows": rows, "error": None}


class TestRunCampaign:
    def test_runs_windows_and_stitches(self, tmp_path):
        """Campaign runs IS+OOS per window and returns a stitched result."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date2(2010, 2, 1),
            total_end=_date2(2013, 8, 1))
        assert isinstance(res, WFOCampaignResult)
        assert len(res.winners) == 2                      # one winner per window
        assert res.stitched["oos_days"] == 10             # 2 windows x 5 days
        # winner is the highest upper_thresh_z combo (1.2)
        assert res.winners[0]["overrides"]["upper_thresh_z"] == 1.2

    def test_resume_skips_completed_rows(self, tmp_path):
        """A second run with the same file re-does no work (all rows present)."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        run_campaign("v3_5b", camp, windows_limit=1, workers=1, run_fn=_fake_run_fn,
                     symbols=["QQQ"], total_start=_date2(2010, 2, 1),
                     total_end=_date2(2013, 8, 1))
        calls = {"n": 0}

        def _counting(*a, **k):
            calls["n"] += 1
            return _fake_run_fn(*a, **k)

        run_campaign("v3_5b", camp, windows_limit=1, workers=1, run_fn=_counting,
                     symbols=["QQQ"], total_start=_date2(2010, 2, 1),
                     total_end=_date2(2013, 8, 1))
        assert calls["n"] == 0  # everything resumed from the JSONL

    def test_single_writer_run_fn_never_writes_jsonl(self, tmp_path):
        """SINGLE-WRITER INVARIANT: run_fn only returns rows; the parent writes.

        A run_fn that itself tried to append would produce duplicate/interleaved
        rows. We assert the JSONL contains exactly the rows the parent wrote:
        (31 IS + 1 OOS) per window == 32 rows for a 1-window campaign.
        """
        camp = tmp_path / "campaign_v3_5b.jsonl"
        run_campaign("v3_5b", camp, windows_limit=1, workers=1, run_fn=_fake_run_fn,
                     symbols=["QQQ"], total_start=_date2(2010, 2, 1),
                     total_end=_date2(2013, 8, 1))
        rows = _reload_wfo_rows(camp)
        is_rows = [r for r in rows if r["phase"] == "is"]
        oos_rows = [r for r in rows if r["phase"] == "oos"]
        assert len(is_rows) == 31   # full grid, one row each, no duplicates
        assert len(oos_rows) == 1   # one OOS winner backtest

    def test_stitched_oos_excludes_warmup_prefixed_rows(self, tmp_path):
        """Warmup-zero OOS rows dated before oos_start are excluded from the stitch.

        Each window's OOS CSV carries 10 leading zero-return warmup rows (dated 2000,
        long before any window's oos_start) + 5 in-span days. The span filter must
        drop the warmup rows so the stitched series contains ONLY in-span days:
        oos_days == 2 windows x 5 in-span days == 10 (not 10 + warmup).
        """
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1,
            run_fn=_warmup_polluted_oos_run_fn, symbols=["QQQ"],
            total_start=_date2(2010, 2, 1), total_end=_date2(2013, 8, 1))
        # 2 windows x 5 in-span days = 10; the 2 x 10 warmup-zero rows are excluded.
        assert res.stitched["oos_days"] == 10
        # With warmup zeros left in, total_return would be diluted toward 0; here every
        # counted day is a real +1% return.
        expected_total = (1.01 ** 10) - 1.0
        assert abs(res.stitched["total_return"] - expected_total) < 1e-9

    def test_resume_mid_oos_rederives_same_winner_deterministically(self, tmp_path):
        """Killed mid-OOS: winners are re-derived from checkpointed IS rows, and the
        deterministic tie-break means the SAME winner is chosen on resume.

        Pass 1 (all IS) completes and is checkpointed. We simulate a crash before
        pass 2 by NOT running OOS (windows_limit run then inspect), then resume and
        confirm the OOS winner combo matches the winner select_is_winner derives
        from the committed IS rows.
        """
        camp = tmp_path / "campaign_v3_5b.jsonl"
        # First full run establishes the ground-truth winner + OOS row.
        res1 = run_campaign(
            "v3_5b", camp, windows_limit=1, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date2(2010, 2, 1),
            total_end=_date2(2013, 8, 1))
        winner_hash = res1.winners[0]["hash"]

        # Simulate "crashed mid-OOS": delete the OOS row from the JSONL, keep all IS.
        rows = _reload_wfo_rows(camp)
        kept = [r for r in rows if r["phase"] == "is"]
        with open(camp, "w") as f:
            for r in kept:
                f.write(json.dumps(r, default=str) + "\n")

        # Resume: IS is all present (no IS re-run), winner re-derived from committed
        # IS rows, and the single OOS backtest re-runs for that same winner.
        res2 = run_campaign(
            "v3_5b", camp, windows_limit=1, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date2(2010, 2, 1),
            total_end=_date2(2013, 8, 1))
        assert res2.winners[0]["hash"] == winner_hash
        # exactly one OOS row again (the re-derived winner's OOS backtest)
        oos = [r for r in _reload_wfo_rows(camp) if r["phase"] == "oos"]
        assert len(oos) == 1
        assert oos[0]["row_key"] == f"1:oos:{winner_hash}"

    def test_progress_callback_reports_each_run(self, tmp_path):
        """The progress callback fires per completed run with window/phase labels."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        msgs = []
        run_campaign("v3_5b", camp, windows_limit=1, workers=1, run_fn=_fake_run_fn,
                     symbols=["QQQ"], total_start=_date2(2010, 2, 1),
                     total_end=_date2(2013, 8, 1), progress=msgs.append)
        # at least one per-run [i/n] line for IS and one for OOS
        run_lines = [m for m in msgs if "] w1 " in m]
        assert any(" is " in m for m in run_lines)
        assert any(" oos " in m for m in run_lines)


def _all_error_run_fn(strategy_id, combo, symbols, start, end, phase,
                      initial_capital="10000"):
    return {"hash": combo["hash"], "combo_id": combo["combo_id"],
            "kind": combo["kind"], "phase": phase,
            "overrides": combo["overrides"], "is_sharpe": None,
            "oos_rows": None, "error": "RuntimeError: simulated outage"}


class TestCircuitBreaker:
    def test_aborts_after_consecutive_errors_serial(self, tmp_path):
        """N consecutive errored IS rows abort the campaign with a clear message."""
        import pytest
        camp = tmp_path / "campaign_v3_5b.jsonl"
        with pytest.raises(RuntimeError, match="consecutive errored"):
            run_campaign("v3_5b", camp, windows_limit=1, workers=1,
                         run_fn=_all_error_run_fn, symbols=["QQQ"],
                         total_start=_date2(2010, 2, 1),
                         total_end=_date2(2013, 8, 1),
                         max_consecutive_errors=5)

    def test_breaker_success_resets_counter(self, tmp_path):
        """A success between errors resets the consecutive counter (no false abort).

        With upper_thresh_z-driven IS Sharpe every product combo succeeds, so a
        breaker of 5 never trips for the all-success fake even across 31 combos.
        """
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign("v3_5b", camp, windows_limit=1, workers=1,
                           run_fn=_fake_run_fn, symbols=["QQQ"],
                           total_start=_date2(2010, 2, 1),
                           total_end=_date2(2013, 8, 1),
                           max_consecutive_errors=5)
        assert len(res.winners) == 1

    def test_aborts_after_consecutive_errors_parallel(self, tmp_path):
        """Parallel path: RuntimeError raised AND at least max_consecutive_errors rows
        are checkpointed before the abort (drain-before-abort proof).

        workers=2, module-level picklable _all_error_run_fn (spawn-safe), small
        max_consecutive_errors=3 so the breaker trips quickly. We assert:
          - RuntimeError with the circuit-breaker message is raised.
          - At least max_consecutive_errors rows exist in the JSONL (i.e., the
            completed work that triggered the breaker was flushed before abort).
        """
        camp = tmp_path / "campaign_v3_5b.jsonl"
        import pytest
        with pytest.raises(RuntimeError, match="consecutive errored"):
            run_campaign("v3_5b", camp, windows_limit=1, workers=2,
                         run_fn=_all_error_run_fn, symbols=["QQQ"],
                         total_start=_date2(2010, 2, 1),
                         total_end=_date2(2013, 8, 1),
                         max_consecutive_errors=3)
        # Drain-before-abort: every row whose future finished before the breaker
        # tripped must be in the JSONL (≥ max_consecutive_errors rows).
        rows = _reload_wfo_rows(camp)
        assert len(rows) >= 3, (
            f"drain-before-abort violated: only {len(rows)} rows checkpointed; "
            "expected >= 3 (max_consecutive_errors)"
        )


# ---------------------------------------------------------------------------
# Task 9 — run_wfo orchestrator + summarize_campaign
# ---------------------------------------------------------------------------
from jutsu_engine.audit.wfo_stability import (
    summarize_campaign, run_wfo,
    golden_combo_top_decile_share, golden_axis_winner_share,
)


class TestSummarizeCampaign:
    def test_summary_has_stitched_combo_verdict_and_axis_diagnostics(self, tmp_path):
        """summarize_campaign builds the full report dict:
        - stitched OOS metrics (spec §5 output 1)
        - combo_top_decile_share: single combo-level verdict (spec §10)
        - axis_diagnostics: per-axis golden_axis_winner_share values (diagnostic table)
        - overall_verdict derived from combo-level share
        """
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date2(2010, 2, 1),
            total_end=_date2(2013, 8, 1))
        summary = summarize_campaign(res)
        assert summary["strategy_id"] == "v3_5b"
        assert summary["stitched"]["oos_days"] == 10
        # combo-level verdict
        assert "combo_top_decile_share" in summary
        assert "combo_verdict" in summary
        assert summary["combo_verdict"] in ("stable", "unstable", "inconclusive")
        # per-axis diagnostics (three sensitive axes)
        assert "axis_diagnostics" in summary
        for p in ("upper_thresh_z", "realized_vol_window", "sma_slow"):
            assert p in summary["axis_diagnostics"]
            assert "share" in summary["axis_diagnostics"][p]
            assert "verdict" in summary["axis_diagnostics"][p]

    def test_summary_overall_verdict_matches_combo_verdict(self, tmp_path):
        """overall_verdict is the combo-level verdict (not per-axis min)."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date2(2010, 2, 1),
            total_end=_date2(2013, 8, 1))
        summary = summarize_campaign(res)
        assert summary["overall_verdict"] == summary["combo_verdict"]

    def test_summary_includes_nan_rows_dropped(self, tmp_path):
        """summary always exposes nan_rows_dropped from stitch_oos_metrics."""
        camp = tmp_path / "campaign_v3_5b.jsonl"
        res = run_campaign(
            "v3_5b", camp, windows_limit=2, workers=1, run_fn=_fake_run_fn,
            symbols=["QQQ"], total_start=_date2(2010, 2, 1),
            total_end=_date2(2013, 8, 1))
        summary = summarize_campaign(res)
        assert "nan_rows_dropped" in summary["stitched"]

    def test_run_wfo_returns_summary_dict(self, tmp_path):
        """run_wfo orchestrates campaign + summarize and returns the summary dict."""
        from unittest import mock
        with mock.patch("jutsu_engine.audit.wfo_stability.run_campaign") as m_camp, \
             mock.patch("jutsu_engine.audit.wfo_stability.summarize_campaign") as m_sum:
            # run_campaign returns a WFOCampaignResult-shaped mock; summarize returns a dict
            m_camp.return_value = object()
            m_sum.return_value = {"strategy_id": "v3_5b", "stitched": {}, "overall_verdict": "stable"}
            result = run_wfo("v3_5b", tmp_path, windows_limit=2, workers=1)
        assert m_camp.called
        assert m_sum.called
        assert result["strategy_id"] == "v3_5b"
