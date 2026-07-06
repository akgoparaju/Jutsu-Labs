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
