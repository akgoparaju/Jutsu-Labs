"""Tests for the `jutsu audit` CLI command group."""
from unittest.mock import patch

from click.testing import CliRunner

from jutsu_engine.cli.commands.audit import audit


class TestAuditCliWiring:
    def test_group_lists_subcommands(self):
        """Help output advertises live-recon, attribution, and all subcommands."""
        runner = CliRunner()
        result = runner.invoke(audit, ["--help"])
        assert result.exit_code == 0
        assert "live-recon" in result.output
        assert "attribution" in result.output
        assert "all" in result.output

    def test_live_recon_reports_db_unavailable_gracefully(self):
        """AuditDBUnavailable surfaces as a clean message, not a traceback."""
        runner = CliRunner()
        from jutsu_engine.audit.db import AuditDBUnavailable
        with patch("jutsu_engine.cli.commands.audit.run_live_recon",
                   side_effect=AuditDBUnavailable("no env")):
            result = runner.invoke(audit, ["live-recon", "--strategy", "v3_5b"])
        # Non-zero exit, but a clear message (not a traceback).
        assert result.exit_code != 0
        assert "database" in result.output.lower() or "no env" in result.output.lower()

    def test_live_recon_writes_report_on_success(self, tmp_path):
        """Successful live-recon writes report_<strategy>.md into the run directory."""
        runner = CliRunner()
        from jutsu_engine.audit.live_recon import LiveReconResult
        fake = LiveReconResult(
            strategy_id="v3_5b",
            summary={"total_days": 1, "match_days": 1, "mismatch_days": 0,
                     "mismatch_pct": 0.0, "by_category": {}, "by_field": {}},
            day_table=[], source_counts={"scheduler": 1},
            pnl_divergence={"final_stored_equity": 100.0,
                            "final_replay_equity": None, "abs_divergence": None,
                            "divergence_day": None},
        )
        with patch("jutsu_engine.cli.commands.audit.run_live_recon", return_value=fake), \
             patch("jutsu_engine.cli.commands.audit._git_sha", return_value="deadbee"), \
             patch("jutsu_engine.cli.commands.audit.report_output_dir",
                   return_value=tmp_path):
            result = runner.invoke(audit, ["live-recon", "--strategy", "v3_5b"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "report_v3_5b.md").exists()
