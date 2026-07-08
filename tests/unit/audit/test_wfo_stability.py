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
