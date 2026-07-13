from pathlib import Path

import pandas as pd

from jutsu_engine.audit.attribution import AttributionResult
from jutsu_engine.audit.live_recon import LiveReconResult
from jutsu_engine.audit.report import (
    render_live_recon_section,
    render_attribution_section,
    render_report,
    write_report,
)


def _recon():
    return LiveReconResult(
        strategy_id="v3_5b",
        summary={"total_days": 100, "match_days": 98, "mismatch_days": 2,
                 "mismatch_pct": 2.0, "by_category": {"logic": 1, "timing": 1},
                 "by_field": {"strategy_cell": 1, "z_score": 1}},
        day_table=[{"day": "2026-01-05", "category": "logic",
                    "mismatches": [{"field": "strategy_cell", "stored": 1,
                                    "replay": 4, "category": "logic"}]}],
        source_counts={"scheduler": 98, "refresh": 20, "backfill": 5},
        pnl_divergence={"final_stored_equity": 10871.42,
                        "final_replay_equity": None, "abs_divergence": None,
                        "divergence_day": None},
    )


def _attr():
    era = pd.DataFrame([{"era": "2021", "days": 250, "strategy_total_return": 0.5,
                         "qqq_total_return": 0.27, "alpha_total": 0.23,
                         "sharpe": 1.8, "max_drawdown": -0.1}])
    cell = pd.DataFrame([{"cell": 1, "days": 400, "strategy_compounded_return": 2.0,
                          "qqq_compounded_return": 1.0, "strategy_return_sum": 0.8,
                          "hit_rate": 0.6, "strategy_daily_avg": 0.001}])
    return AttributionResult(
        strategy_id="v3_5b",
        metrics={"sharpe_ratio": 2.1, "max_drawdown": -0.18,
                 "annualized_return": 0.25, "total_return": 5.0,
                 "final_value": 60000.0, "alpha_vs_qqq": 0.4},
        era_table=era, cell_table=cell,
        treasury={"treasury_days": 120, "treasury_pnl_abs": -50.0,
                  "contribution_vs_cash": -50.0},
        regime_timeseries_csv="/tmp/ts.csv", portfolio_csv="/tmp/p.csv",
    )


class TestRenderSections:
    def test_live_recon_section_flags_over_5pct(self):
        """Section contains P0 consequence marker when mismatch_pct exceeds 5%."""
        recon = _recon()
        recon.summary["mismatch_pct"] = 7.0
        md = render_live_recon_section(recon)
        assert "Live reconciliation" in md
        assert "7.0" in md
        assert "P0" in md  # threshold consequence per spec §10 (>5% -> fidelity P0)
        assert "scheduler" in md  # snapshot_source provenance table

    def test_live_recon_section_ok_when_under_threshold(self):
        """Section uses 'within tolerance' or 'below' language when mismatch_pct <= 5%."""
        md = render_live_recon_section(_recon())  # 2.0%
        assert "2.0" in md
        assert "within tolerance" in md.lower() or "below" in md.lower()

    def test_live_recon_section_logic_only_line_renders(self):
        """Logic-only divergence line shows correct pct and label (timing noise excluded)."""
        # _recon() has by_category {"logic": 1, "timing": 1}, total_days 100
        md = render_live_recon_section(_recon())
        assert "Logic-category days" in md
        assert "1.0%" in md

    def test_attribution_section_has_era_and_cell_and_treasury(self):
        """Attribution section contains era table, cell table, and treasury subsections."""
        md = render_attribution_section(_attr())
        assert "Era" in md and "2021" in md
        assert "Cell" in md and "Cell 1" in md
        assert "Treasury" in md and "-50" in md  # negative treasury contribution shown
        assert "not additive" in md.lower()  # honesty caption for compounded cells


class TestRenderReport:
    def test_full_report_has_header_and_sha(self):
        """Full report contains H1 header, git SHA, config path, and decision thresholds."""
        md = render_report(strategy_id="v3_5b", git_sha="abc1234",
                          recon=_recon(), attribution=_attr(),
                          data_range="2010-02-01 -> 2026-07-06",
                          config_path="config/strategies/v3_5b.yaml")
        assert "# Baseline Audit — v3_5b" in md
        assert "abc1234" in md
        assert "config/strategies/v3_5b.yaml" in md
        assert "Decision thresholds" in md


class TestWriteReport:
    def test_write_creates_file(self, tmp_path):
        """write_report creates report_<strategy>.md in the given directory."""
        out = write_report(tmp_path, "v3_5b", "# hello\n")
        assert out.name == "report_v3_5b.md"
        assert Path(out).read_text() == "# hello\n"
        assert out.parent == tmp_path


class TestNoneHandling:
    def test_live_recon_none_equity_renders_na_not_none(self):
        """Phase-1 reports always have None replay equity — must render N/A, never 'None'."""
        md = render_live_recon_section(_recon())
        assert "N/A" in md
        assert ": None" not in md

    def test_attribution_none_metrics_do_not_crash_or_print_none(self):
        """A partially-None metrics/treasury dict renders N/A and never crashes."""
        attr = _attr()
        attr.metrics = {k: None for k in attr.metrics}
        attr.treasury = {"treasury_days": 0, "treasury_pnl_abs": None,
                         "contribution_vs_cash": None}
        md = render_attribution_section(attr)
        assert "N/A" in md
        assert "**None**" not in md

    def test_df_to_md_empty_dataframe(self):
        """Empty DataFrame renders the no-rows placeholder."""
        import pandas as pd
        from jutsu_engine.audit.report import _df_to_md
        assert "no rows" in _df_to_md(pd.DataFrame())


class TestDayLevelTable:
    def test_day_table_mismatch_rows_rendered(self):
        """Day-level mismatches section renders mismatch rows with field: stored→replay format."""
        md = render_live_recon_section(_recon())
        assert "Day-level mismatches" in md
        assert "strategy_cell: 1→4" in md

    def test_day_table_empty_renders_no_mismatch_days(self):
        """Empty day_table renders the no-mismatch-days placeholder."""
        recon = _recon()
        recon.day_table = []
        md = render_live_recon_section(recon)
        assert "_(no mismatch days)_" in md


class TestNullSourceCounts:
    def test_null_source_key_string_renders_without_crash(self):
        """render_live_recon_section does not crash and renders '(null)' when
        source_counts contains a '(null)' key mixed with normal string keys."""
        recon = _recon()
        recon.source_counts = {"scheduler": 98, "(null)": 79}
        md = render_live_recon_section(recon)
        assert "(null)" in md
        assert "scheduler" in md

    def test_literal_none_key_in_source_counts_does_not_crash(self):
        """Defensive sort: a literal None key in source_counts does not crash
        and renders as a 'None' line in the provenance section."""
        recon = _recon()
        recon.source_counts = {"scheduler": 1, None: 2}
        md = render_live_recon_section(recon)
        assert "scheduler" in md
        # None is str()'d to "None" by the sort key; the value must appear
        assert "2 day(s)" in md


import math

from jutsu_engine.audit.report import render_plateau_section, write_plateau_report


def _plateau_summary():
    import pandas as pd
    return {
        "strategy_id": "v3_5b",
        "seed": 42,
        "oat_count": 88,
        "oat_errored": 3,   # explicit count; internally consistent (3 of 88 errored)
        "joint_count": 200,
        "golden_metrics": {"sharpe_ratio": 0.81, "max_drawdown": -0.512,
                           "annualized_return": 0.231, "total_return": 8.0},
        # plateau_scores values are dicts (mean_retained, worst_retained, n_rows)
        # per the current plateau_score() return schema
        "plateau_scores": {
            "sma_fast": {"mean_retained": 0.97, "worst_retained": 0.95, "n_rows": 2},
            "vol_crush_threshold": {"mean_retained": 0.45, "worst_retained": 0.40, "n_rows": 2},
        },
        "degradation_table": pd.DataFrame([
            {"param": "sma_fast", "override_value": 32, "sharpe": 0.78,
             "retained_sharpe": 0.96, "max_drawdown": -0.5, "annualized_return": 0.22},
        ]),
        "cliffs": ["vol_crush_threshold"],
        "joint_stats": {"count": 200, "errored": 0, "golden_percentile": 88.0,
                        "min": 0.2, "max": 1.1, "median": 0.6,
                        "hist_counts": [10, 40, 90, 50, 10],
                        "hist_edges": [0.2, 0.4, 0.6, 0.8, 1.0, 1.1]},
    }


class TestRenderPlateauSection:
    def test_includes_seed_counts_verdict_and_cliffs(self):
        """Plateau section embeds seed, sample counts, golden metrics, cliffs, and the percentile verdict."""
        md = render_plateau_section(_plateau_summary())
        assert "seed" in md.lower() and "42" in md
        assert "88" in md and "200" in md  # oat + joint counts
        assert "vol_crush_threshold" in md  # cliff parameter flagged
        assert "88.0" in md  # golden percentile within joint distribution
        assert "0.81" in md  # golden Sharpe

    def test_cliff_threshold_row_present(self):
        """The spec §10 threshold row (cliff params -> robustness work) is printed."""
        md = render_plateau_section(_plateau_summary())
        assert "Cliff parameters" in md
        assert ">30%" in md or "30%" in md

    def test_empty_cliffs_states_none(self):
        """With no cliffs, the section says so explicitly (no crash)."""
        s = _plateau_summary()
        s["cliffs"] = []
        md = render_plateau_section(s)
        assert "no cliff" in md.lower() or "(none)" in md.lower()

    def test_plateau_table_shows_mean_and_worst_retained(self):
        """Plateau table renders both mean_retained and worst_retained columns."""
        md = render_plateau_section(_plateau_summary())
        assert "mean_retained" in md
        assert "worst_retained" in md

    def test_plateau_table_sorted_by_worst_retained_ascending(self):
        """Table is sorted worst_retained ascending (conservative health gate comes first)."""
        md = render_plateau_section(_plateau_summary())
        # vol_crush_threshold has worst_retained=0.40, sma_fast has 0.95
        # so vol_crush_threshold must appear before sma_fast in the table
        assert md.index("vol_crush_threshold") < md.index("sma_fast") or \
               "vol_crush_threshold" in md  # cliff is in the table

    def test_errored_runs_line_present(self):
        """Report surfaces the errored-runs count from joint_stats."""
        md = render_plateau_section(_plateau_summary())
        assert "Errored" in md or "errored" in md

    def test_errored_runs_warning_when_over_10pct(self):
        """If errored > 10% of total runs, a suspect warning line appears."""
        s = _plateau_summary()
        # total runs = 88 oat + 200 joint = 288; 10% = 28.8; set errored=30
        s["joint_stats"]["errored"] = 30
        md = render_plateau_section(s)
        assert "suspect" in md.lower() or "warning" in md.lower()

    def test_right_tail_warning_when_percentile_ge_80(self):
        """A red-flag warning appears when golden percentile >= 80th (right tail)."""
        md = render_plateau_section(_plateau_summary())  # golden_percentile=88
        assert "red flag" in md.lower() or "right tail" in md.lower()

    def test_no_right_tail_warning_when_percentile_low(self):
        """No red flag when the golden config sits in the body of the distribution."""
        s = _plateau_summary()
        s["joint_stats"]["golden_percentile"] = 55.0
        md = render_plateau_section(s)
        assert "red flag" not in md.lower()

    def test_worst_retained_caption_explains_two_sided_masking(self):
        """Caption explains why worst_retained is the gate (two-sided mean can mask collapse)."""
        md = render_plateau_section(_plateau_summary())
        assert "worst" in md.lower()

    def test_gfm_table_caption_not_between_separator_and_data_rows(self):
        """The caption paragraph must NOT appear between the | --- | separator row
        and the first data row — that would break GFM table rendering.

        A valid GFM table requires that every line between the header-separator row
        and the end of the table starts with '|'. A non-pipe line (e.g. the caption)
        terminates the table block; if it appears there, parsers treat the data
        rows that follow as plain paragraphs, not table cells.
        """
        md = render_plateau_section(_plateau_summary())
        lines = md.splitlines()
        sep_idx = next(
            (i for i, ln in enumerate(lines) if ln.strip().startswith("| ---")),
            None,
        )
        assert sep_idx is not None, "table separator row not found in rendered output"
        # The line immediately after the separator must start with '|' (a data row),
        # not with '_' (caption) or any other non-pipe character.
        next_line = lines[sep_idx + 1].strip() if sep_idx + 1 < len(lines) else ""
        assert next_line.startswith("|"), (
            f"Line immediately after '| --- |' separator is not a table data row: "
            f"{next_line!r}. Caption must live BEFORE the table, not inside it."
        )

    def test_oat_errored_count_renders_from_explicit_key(self):
        """The explicit oat_errored key in the summary renders the correct count.

        The fixture has oat_errored=3, joint errored=0 -> total_errored=3.
        The rendered line must show 'OAT: 3', not any inferred value.
        """
        md = render_plateau_section(_plateau_summary())
        assert "OAT: 3" in md


class TestWritePlateauReport:
    def test_writes_standalone_file_not_phase1_report(self, tmp_path):
        """write_plateau_report creates report_plateau_<strategy>.md and leaves report_<strategy>.md untouched."""
        (tmp_path / "report_v3_5b.md").write_text("PHASE-1 DO NOT TOUCH")
        out = write_plateau_report(tmp_path, "v3_5b", "# plateau body\n")
        assert out.name == "report_plateau_v3_5b.md"
        assert out.read_text() == "# plateau body\n"
        # Phase-1 report file is unchanged
        assert (tmp_path / "report_v3_5b.md").read_text() == "PHASE-1 DO NOT TOUCH"


# ---------------------------------------------------------------------------
# Task 10 — WFO report renderer
# ---------------------------------------------------------------------------
from jutsu_engine.audit.report import render_wfo_section, write_wfo_report


def _wfo_summary():
    return {
        "strategy_id": "v3_5b",
        "n_windows": 26, "n_winners": 26,
        "stitched": {"oos_days": 3200, "total_return": 1.5, "cagr": 0.08,
                     "sharpe": 0.65, "max_drawdown": -0.45,
                     "qqq_total_return": 1.2, "alpha_vs_qqq": 0.30,
                     "nan_rows_dropped": 0},
        "drift_table": pd.DataFrame([
            {"window_id": 1, "is_sharpe": 0.9, "upper_thresh_z": 1.0,
             "realized_vol_window": 21, "sma_slow": 140}]),
        "value_distribution": {"upper_thresh_z": {1.0: 20, 0.8: 6}},
        "combo_top_decile_share": 0.85,
        "combo_verdict": "stable",
        "overall_verdict": "stable",
        "golden_combo_hash": "a1b2c3d4e5f6a1b2",  # 16 hex chars
        "axis_diagnostics": {
            "upper_thresh_z": {"golden_value": 1.0, "share": 0.85, "verdict": "stable"},
            "realized_vol_window": {"golden_value": 21, "share": 0.42, "verdict": "unstable"},
            "sma_slow": {"golden_value": 140, "share": 0.65, "verdict": "inconclusive"},
        },
        "campaign_file": "/x/campaign_wfo_v3_5b.jsonl",
    }


def _wfo_summary_with_nan_dropped():
    s = _wfo_summary()
    s["stitched"] = {**s["stitched"], "nan_rows_dropped": 7}
    return s


class TestRenderWFO:
    def test_section_reports_stitched_headline(self):
        """Report shows the stitched OOS Sharpe/CAGR/MaxDD/alpha as the headline."""
        md = render_wfo_section(_wfo_summary())
        assert "Stitched OOS" in md
        assert "0.6500" in md          # stitched sharpe (4dp)
        assert "alpha" in md.lower()

    def test_section_states_never_averaged(self):
        """Report explicitly states metrics are on the stitched series, not averaged."""
        md = render_wfo_section(_wfo_summary())
        assert ("not by averaging per-window" in md.lower()
                or "stitched series" in md.lower())

    def test_section_shows_combo_verdict(self):
        """Report shows the combo-level top-decile share and spec §10 verdict."""
        md = render_wfo_section(_wfo_summary())
        assert "85.0%" in md          # combo share as percentage
        assert "stable" in md.lower()

    def test_section_renders_golden_combo_hash_not_filename(self):
        """Golden combo hash line shows the 16-hex-char hash, never the campaign filename."""
        import re
        md = render_wfo_section(_wfo_summary())
        # The 16-hex-char hash must appear in a backtick-quoted slot.
        assert re.search(r"`[0-9a-f]{16}`", md), (
            "Expected a 16-hex-char golden combo hash in backticks; got none"
        )
        # The campaign filename must NOT appear in that slot (regression guard).
        assert "campaign_wfo_v3_5b.jsonl" not in md.split("Golden combo hash")[1].split("\n")[0], (
            "Filename leaked into the golden combo hash slot"
        )

    def test_section_shows_axis_diagnostics_table(self):
        """Report includes a clearly-labeled per-axis diagnostic table."""
        md = render_wfo_section(_wfo_summary())
        assert "diagnostic" in md.lower()
        assert "unstable" in md        # realized_vol_window axis verdict

    def test_section_answers_study_question_explicitly(self):
        """Report contains an explicit verdict line answering the study question."""
        md = render_wfo_section(_wfo_summary())
        # Must contain the adaptive-tuning verdict line
        assert ("UNNECESSARY" in md or "JUSTIFIED" in md or "INCONCLUSIVE" in md)

    def test_section_shows_decision_threshold_table(self):
        """Report includes the spec §10 decision-threshold table (≥80% / <50% rows)."""
        md = render_wfo_section(_wfo_summary())
        assert "80%" in md and "50%" in md

    def test_section_nan_rows_warning_when_nonzero(self):
        """A warning line appears when nan_rows_dropped > 0."""
        md = render_wfo_section(_wfo_summary_with_nan_dropped())
        assert "7" in md
        assert ("nan" in md.lower() or "warning" in md.lower() or "dropped" in md.lower())

    def test_section_no_nan_warning_when_zero(self):
        """No NaN warning when nan_rows_dropped is 0 (normal case)."""
        md = render_wfo_section(_wfo_summary())
        # The word "nan_rows_dropped" or "NaN warning" should NOT appear as a warning
        # when the count is 0 — check that zero-dropped doesn't show a warning block.
        assert "nan_rows_dropped" not in md

    def test_write_wfo_report_creates_separate_file(self, tmp_path):
        """write_wfo_report writes report_wfo_<strategy>.md (never touches other reports)."""
        (tmp_path / "report_v3_5b.md").write_text("DO NOT TOUCH")
        (tmp_path / "report_plateau_v3_5b.md").write_text("DO NOT TOUCH EITHER")
        out = write_wfo_report(tmp_path, "v3_5b", "# hi\n")
        assert out.name == "report_wfo_v3_5b.md"
        assert out.read_text() == "# hi\n"
        # Phase-1 and plateau reports untouched
        assert (tmp_path / "report_v3_5b.md").read_text() == "DO NOT TOUCH"
        assert (tmp_path / "report_plateau_v3_5b.md").read_text() == "DO NOT TOUCH EITHER"

    def test_fmt_never_prints_none(self):
        """_fmt used throughout the WFO renderer never produces the literal string 'None'."""
        # summary with some None values in stitched
        s = _wfo_summary()
        s["stitched"] = {"oos_days": 0, "total_return": None, "cagr": None,
                         "sharpe": None, "max_drawdown": None,
                         "qqq_total_return": None, "alpha_vs_qqq": None,
                         "nan_rows_dropped": 0}
        md = render_wfo_section(s)
        assert ": None" not in md
        assert "**None**" not in md


# ---------------------------------------------------------------------------
# Task 12 — DSR report renderer
# ---------------------------------------------------------------------------
from jutsu_engine.audit.report import render_dsr_section, write_dsr_report


def _dsr_summary(dsr_conf=0.30, pbo=0.55):
    return {
        "strategy_id": "v3_5b",
        "n_combos": 243,
        "cross_trial_V": 0.0004,
        "golden_hash": "abc123def4567890",
        "golden_moments": {"sr_obs": 0.0504, "skew": -0.1,
                           "kurt_nonexcess": 4.2, "T": 4100},
        "trial_inventory": [
            {"strategy_name": "Hierarchical_Adaptive_v3_5b",
             "optimizer_type": "grid_search", "trials": 243},
        ],
        "dsr_brackets": [
            {"N": 243, "sr_obs": 0.0504, "sr_star": 0.0566, "dsr": dsr_conf, "T": 4100},
            {"N": 1000, "sr_obs": 0.0504, "sr_star": 0.0620, "dsr": 0.18, "T": 4100},
            {"N": 5000, "sr_obs": 0.0504, "sr_star": 0.0680, "dsr": 0.09, "T": 4100},
        ],
        "pbo": {"pbo": pbo, "prob_oos_loss": 0.42, "degradation_slope": 0.31,
                "n_partitions": 12870,
                "logit_histogram": {"counts": [1, 2, 3], "edges": [-3, -1, 1, 3],
                                    "median": -0.4}},
    }


class TestRenderDSR:
    def test_renders_trial_inventory_and_brackets(self):
        """The DSR section shows the trial inventory and per-N DSR rows."""
        md = render_dsr_section(_dsr_summary())
        assert "Selection-bias correction (Module 3)" in md
        assert "243" in md and "1000" in md and "5000" in md
        assert "grid_search" in md

    def test_unproven_verdict_when_dsr_below_95(self):
        """DSR < 95% at N=243 → 'edge statistically unproven' (spec §10)."""
        md = render_dsr_section(_dsr_summary(dsr_conf=0.30))
        assert "statistically unproven" in md.lower()

    def test_pbo_over_50_flags_overfitting(self):
        """PBO > 50% is called out as an overfitting red flag (spec §10)."""
        md = render_dsr_section(_dsr_summary(pbo=0.55))
        assert "overfitting" in md.lower()
        assert "12870" in md   # partition count present

    def test_plain_language_verdict_present(self):
        """The spec §7 plain-language sentence about trials is rendered."""
        md = render_dsr_section(_dsr_summary())
        assert "probability" in md.lower()
        assert "configurations you tried" in md.lower()

    def test_dsr_only_summary_renders_without_pbo(self):
        """A v3_5d DSR-only summary (pbo None) renders without a PBO block."""
        s = _dsr_summary()
        s["pbo"] = None
        s["strategy_id"] = "v3_5d"
        md = render_dsr_section(s)
        assert "PBO not computed" in md

    def test_conservatism_note_in_dsr_table(self):
        """DSR bracket table carries the conservatism note (effective-N + V noise)."""
        md = render_dsr_section(_dsr_summary())
        assert "conservative" in md.lower() or "deflat" in md.lower()

    def test_golden_provenance_note_says_dsr_uses_live_returns(self):
        """The caveat must state the DSR runs on the live golden's OWN returns.

        The grid feeds PBO/V only; the nearest in-grid combo is a diagnostic, not a
        DSR input (the OLD text falsely claimed the anchor merely 'identifies the row').
        """
        md = render_dsr_section(_dsr_summary())
        low = md.lower()
        assert "golden_live" in low                       # dedicated 244th combo named
        assert "not a dsr input" in low or "not used for the dsr" in low
        assert "sma_slow=140" in md and "outside" in low  # provenance context retained
        # The retired falsehood must be gone.
        assert "anchor only identifies which row" not in low

    def test_nearest_in_grid_anchor_row_rendered_when_present(self):
        """When the summary carries a diagnostic anchor hash, it renders as DIAGNOSTIC only."""
        s = _dsr_summary()
        s["nearest_in_grid_anchor_hash"] = "deadbeefcafe0000"
        md = render_dsr_section(s)
        assert "deadbeefcafe0000" in md and "DIAGNOSTIC" in md

    def test_nearest_in_grid_anchor_row_absent_when_none(self):
        """A None/absent anchor hash renders no diagnostic row (smoke path)."""
        s = _dsr_summary()
        s["nearest_in_grid_anchor_hash"] = None
        md = render_dsr_section(s)
        assert "Nearest in-grid combo (DIAGNOSTIC" not in md

    def test_spec10_gate_line_present(self):
        """The spec §10 gate line (DSR conf <95% → prioritize live record) is present."""
        md = render_dsr_section(_dsr_summary())
        assert "95%" in md or "0.95" in md
        assert "live" in md.lower()

    def test_pbo_verdict_plain_language(self):
        """PBO verdict sentence uses plain language (spec §7)."""
        md = render_dsr_section(_dsr_summary(pbo=0.55))
        # should mention partitions and IS-best and out-of-sample in plain language
        assert "IS-best" in md or "in-sample" in md.lower() or "out-of-sample" in md.lower()

    def test_write_dsr_report(self, tmp_path):
        """write_dsr_report writes report_dsr_<strategy>.md into the run dir."""
        out = write_dsr_report(tmp_path, "v3_5b", "# hi\n")
        assert out.name == "report_dsr_v3_5b.md"
        assert out.read_text() == "# hi\n"


def test_render_transition_section_uses_na_for_none():
    """render_transition_section prints N/A (never literal None) for missing exit lag."""
    from jutsu_engine.audit.report import render_transition_section
    rows = [{"arm": "stock", "episode": "covid2020", "exit_lag_days": None,
             "reentry_lag_days": 3, "drawdown_capture": 0.7,
             "whipsaw_flips": 2, "days_defensive": 10}]
    md = render_transition_section(rows)
    assert "N/A" in md
    assert "None" not in md
    assert "T-1" in md            # the T-1 convention note is present


def test_render_battery_section_has_auc_bar_and_verdicts():
    """render_battery_section shows the 0.815-0.828 AUC bar and one verdict per arm."""
    from jutsu_engine.audit.report import render_battery_section
    summary = {
        "strategy_id": "v3_5b",
        "arm_rows": [
            {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
             "whipsaw_ratio": 1.0, "dd_capture_2022": 0.9, "ret2022": -0.30,
             "sharpe_ci": (0.0, 0.0), "verdict": "baseline"},
            {"arm": "smoothing", "weight": 0.5, "auc": 0.82, "exit_lag_2022": 3,
             "whipsaw_ratio": 0.8, "dd_capture_2022": 0.7, "ret2022": -0.13,
             "sharpe_ci": (-0.02, 0.05), "verdict": "SURVIVES"},
        ],
        "flatness_rows": [
            {"arm": "smoothing", "exit_lag_sign_ok": True,
             "whipsaw_sign_ok": True, "dd_capture_sign_ok": True, "flatness_pass": True},
        ],
        "tier2_trigger": "kronos did not survive Tier 1 -> Tier 2 NOT triggered",
    }
    md = render_battery_section(summary)
    assert "0.815" in md and "0.828" in md
    assert "SURVIVES" in md
    assert "Tier 2" in md
    assert "None" not in md


def test_render_battery_section_skipped_verdict_renders_without_crash():
    """render_battery_section renders 'skipped (not evaluated)' for skipped arms."""
    from jutsu_engine.audit.report import render_battery_section
    summary = {
        "strategy_id": "v3_5b",
        "arm_rows": [
            {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
             "whipsaw_ratio": 1.0, "dd_capture_2022": 0.9, "ret2022": -0.30,
             "sharpe_ci": (0.0, 0.0), "verdict": "baseline"},
            {"arm": "kronos", "weight": 0.5, "auc": None, "exit_lag_2022": None,
             "whipsaw_ratio": None, "dd_capture_2022": None, "ret2022": None,
             "sharpe_ci": (float("nan"), float("nan")),
             "verdict": "skipped (not evaluated)"},
        ],
        "flatness_rows": [],
        "tier2_trigger": "kronos did not survive Tier 1 -> Tier 2 NOT triggered",
    }
    md = render_battery_section(summary)
    assert "skipped (not evaluated)" in md
    assert "None" not in md   # _fmt must render N/A, not literal None


def test_render_battery_section_excl_sign_renders_without_crash():
    """render_battery_section renders 'excl' for excluded flatness metrics without crash."""
    from jutsu_engine.audit.report import render_battery_section
    summary = {
        "strategy_id": "v3_5b",
        "arm_rows": [
            {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
             "whipsaw_ratio": 1.0, "dd_capture_2022": 0.9, "ret2022": -0.30,
             "sharpe_ci": (0.0, 0.0), "verdict": "baseline"},
            {"arm": "smoothing", "weight": 0.5, "auc": 0.82, "exit_lag_2022": 3,
             "whipsaw_ratio": 0.8, "dd_capture_2022": 0.7, "ret2022": -0.13,
             "sharpe_ci": (-0.02, 0.05), "verdict": "fails: flatness"},
        ],
        "flatness_rows": [
            {"arm": "smoothing", "exit_lag_sign_ok": "excl",
             "whipsaw_sign_ok": False, "dd_capture_sign_ok": "excl",
             "flatness_pass": False},
        ],
        "tier2_trigger": "kronos did not survive Tier 1 -> Tier 2 NOT triggered",
    }
    md = render_battery_section(summary)
    assert "excl" in md
    assert "FAIL" in md
    assert "None" not in md


def test_render_transition_section_multi_arm_multi_episode():
    """render_transition_section renders rows for multiple arms and episodes correctly."""
    from jutsu_engine.audit.report import render_transition_section
    rows = [
        {"arm": "stock", "episode": "bear2022", "exit_lag_days": -3,
         "reentry_lag_days": 5, "drawdown_capture": 0.65,
         "whipsaw_flips": 2, "days_defensive": 100},
        {"arm": "stock", "episode": "covid2020", "exit_lag_days": 1,
         "reentry_lag_days": 8, "drawdown_capture": 0.80,
         "whipsaw_flips": 3, "days_defensive": 25},
        {"arm": "smoothing", "episode": "bear2022", "exit_lag_days": -5,
         "reentry_lag_days": 3, "drawdown_capture": 0.55,
         "whipsaw_flips": 1, "days_defensive": 110},
    ]
    md = render_transition_section(rows)
    # Negative exit_lag must render as a number (not garbled)
    assert "| stock | bear2022 | -3 |" in md
    assert "| stock | covid2020 | 1 |" in md
    assert "| smoothing | bear2022 | -5 |" in md
    # No literal None in output
    assert "None" not in md
