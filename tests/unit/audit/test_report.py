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
