"""CLI tests for `jutsu audit wfo` (mirrors test_plateau_cli.py; run_wfo mocked).

Patch target: `jutsu_engine.cli.commands.audit.report_output_dir` — the name
as it was imported into audit.py (`from jutsu_engine.audit.config import
... report_output_dir`). Patching the module-level name in audit.py ensures
_resolve_run_dir_wfo also sees the patched value.
"""
from unittest import mock

import pandas as pd
from click.testing import CliRunner

from jutsu_engine.cli.commands.audit import audit


def _summary():
    return {
        "strategy_id": "v3_5b", "n_windows": 2, "n_winners": 2,
        "stitched": {"oos_days": 10, "total_return": 0.1, "cagr": 0.05,
                     "sharpe": 0.6, "max_drawdown": -0.2,
                     "qqq_total_return": 0.08, "alpha_vs_qqq": 0.02},
        "drift_table": pd.DataFrame([{"window_id": 1, "is_sharpe": 0.9}]),
        "value_distribution": {"upper_thresh_z": {1.0: 2}},
        "top_decile_share": {
            "upper_thresh_z": {"golden_value": 1.0, "share": 1.0, "verdict": "stable"},
            "realized_vol_window": {"golden_value": 21, "share": 1.0, "verdict": "stable"},
            "sma_slow": {"golden_value": 140, "share": 1.0, "verdict": "stable"},
        },
        "overall_min_share": 1.0, "overall_verdict": "stable",
        "campaign_file": "/x/campaign_wfo_v3_5b.jsonl",
    }


class TestWFOCli:
    def test_wfo_calls_run_wfo_and_writes_report(self, tmp_path):
        """`jutsu audit wfo --strategy v3_5b` calls run_wfo and writes a report."""
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code == 0, r.output
        assert m.called
        assert (tmp_path / "report_wfo_v3_5b.md").exists()

    def test_windows_limit_and_workers_thread_through(self, tmp_path):
        """--windows-limit and --workers are forwarded to run_wfo."""
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(
                audit, ["wfo", "--strategy", "v3_5b",
                        "--windows-limit", "2", "--workers", "4"])
        assert r.exit_code == 0, r.output
        _, kwargs = m.call_args
        assert kwargs["windows_limit"] == 2
        assert kwargs["workers"] == 4

    def test_retry_errors_flag_threads_through(self, tmp_path):
        """--retry-errors is forwarded as retry_errors=True."""
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(
                audit, ["wfo", "--strategy", "v3_5b", "--retry-errors"])
        assert r.exit_code == 0, r.output
        assert m.call_args.kwargs["retry_errors"] is True

    def test_circuit_breaker_message_is_clear(self, tmp_path):
        """A RuntimeError from run_wfo (breaker) surfaces a clean aborted message."""
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        side_effect=RuntimeError("consecutive errored runs")):
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code != 0
        assert "aborted" in r.output.lower() or "consecutive" in r.output.lower()

    def test_wfo_db_unavailable_degrades_gracefully(self, tmp_path):
        """AuditDBUnavailable surfaces as a clean 'Database unavailable' message."""
        from jutsu_engine.audit.db import AuditDBUnavailable
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        side_effect=AuditDBUnavailable("Missing DB config env vars")):
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code != 0
        assert "Database unavailable" in r.output

    def test_wfo_prints_campaign_file_upfront(self, tmp_path):
        """Campaign file path echoed before long work (operator awareness)."""
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()):
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code == 0, r.output
        assert ".jsonl" in r.output
        assert "workers" in r.output

    def test_wfo_resume_detection_echo(self, tmp_path):
        """Existing WFO campaign file older date-dir => 'Resuming existing WFO campaign'."""
        old_date = "2026-07-05"
        today_date = "2026-07-07"
        old_run_dir = tmp_path / "claudedocs" / "audit" / old_date
        campaign_file = old_run_dir / "v3_5b" / "campaign_wfo_v3_5b.jsonl"
        campaign_file.parent.mkdir(parents=True, exist_ok=True)
        campaign_file.write_text('{"row_key":"1:is:abc"}\n')

        today_dir = tmp_path / "claudedocs" / "audit" / today_date
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=today_dir), \
             mock.patch("jutsu_engine.audit.wfo_stability.run_wfo",
                        return_value=_summary()) as m:
            r = CliRunner().invoke(audit, ["wfo", "--strategy", "v3_5b"])
        assert r.exit_code == 0, r.output
        assert "Resuming existing WFO campaign" in r.output
        # run_wfo must have been called with the OLD run_dir
        called_run_dir = m.call_args[0][1]
        assert old_date in str(called_run_dir)

    def test_wfo_help_lists_required_options(self):
        """--help output lists all plan-required options."""
        r = CliRunner().invoke(audit, ["wfo", "--help"])
        assert r.exit_code == 0, r.output
        for flag in ("--strategy", "--workers", "--windows-limit",
                     "--retry-errors", "--run-date"):
            assert flag in r.output, f"missing {flag} from --help"
