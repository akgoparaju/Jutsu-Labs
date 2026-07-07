"""Tests for the `jutsu audit plateau` CLI subcommand (Task 10)."""
from unittest import mock

import pandas as pd
import pytest
from click.testing import CliRunner

from jutsu_engine.cli.commands.audit import audit


def _make_summary():
    """Return a minimal but structurally valid run_plateau summary dict."""
    return {
        "strategy_id": "v3_5b",
        "seed": 0,
        "oat_count": 4,
        "oat_errored": 0,
        "joint_count": 0,
        "golden_metrics": {
            "sharpe_ratio": 0.8,
            "max_drawdown": -0.5,
            "annualized_return": 0.2,
            "total_return": 5.0,
        },
        "plateau_scores": {"sma_fast": 0.95},
        "cliffs": [],
        "joint_stats": {
            "count": 0,
            "errored": 0,
            "golden_percentile": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
            "median": float("nan"),
            "hist_counts": [],
            "hist_edges": [],
        },
        "degradation_table": pd.DataFrame([{
            "param": "sma_fast",
            "override_value": 32,
            "sharpe": 0.78,
            "retained_sharpe": 0.96,
            "max_drawdown": -0.5,
            "annualized_return": 0.2,
        }]),
    }


class TestPlateauCLI:
    def test_plateau_calls_run_plateau_and_writes_report(self, tmp_path):
        """`jutsu audit plateau --strategy v3_5b` runs the driver and writes the plateau report."""
        summary = _make_summary()
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        return_value=summary) as m:
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b",
                                        "--oat-only", "--params", "sma_fast"])
        assert res.exit_code == 0, res.output
        m.assert_called_once()
        assert (tmp_path / "report_plateau_v3_5b.md").exists()
        # Phase-1 report path must NOT be created by the plateau command.
        assert not (tmp_path / "report_v3_5b.md").exists()

    def test_plateau_db_unavailable_degrades_gracefully(self, tmp_path):
        """A DB-unavailable driver surfaces a clean abort, not a traceback."""
        from jutsu_engine.audit.db import AuditDBUnavailable
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        side_effect=AuditDBUnavailable("Missing DB config env vars")):
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b"])
        assert res.exit_code != 0
        assert "Database unavailable" in res.output

    def test_plateau_prints_campaign_file_and_counts_upfront(self, tmp_path):
        """Campaign file path and sample counts are printed before long work starts."""
        summary = _make_summary()
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        return_value=summary):
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b",
                                        "--oat-only"])
        assert res.exit_code == 0, res.output
        # The campaign file path (jsonl) must appear in the output before the report line.
        assert ".jsonl" in res.output
        # Worker / joint / seed parameters must appear so an operator knows the run config.
        assert "workers" in res.output

    def test_plateau_circuit_breaker_message_is_clear(self, tmp_path):
        """RuntimeError (circuit breaker) surfaces as a clear, non-traceback message."""
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        side_effect=RuntimeError("aborting: 10 consecutive errored runs")):
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b"])
        assert res.exit_code != 0
        assert "aborting" in res.output or "circuit" in res.output.lower() or \
               "consecutive" in res.output

    def test_plateau_retry_errors_flag_threads_to_run_plateau(self, tmp_path):
        """--retry-errors is forwarded to run_plateau as retry_errors=True."""
        summary = _make_summary()
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        return_value=summary) as m:
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b",
                                        "--oat-only", "--retry-errors"])
        assert res.exit_code == 0, res.output
        _, kwargs = m.call_args
        assert kwargs.get("retry_errors") is True

    def test_plateau_retry_errors_default_is_false(self, tmp_path):
        """Without --retry-errors, retry_errors=False is passed to run_plateau."""
        summary = _make_summary()
        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=tmp_path), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        return_value=summary) as m:
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b",
                                        "--oat-only"])
        assert res.exit_code == 0, res.output
        _, kwargs = m.call_args
        assert kwargs.get("retry_errors") is False


class TestMidnightSafeResume:
    def test_existing_campaign_file_older_date_dir_resumes_without_run_date(self, tmp_path):
        """Existing campaign file in an older date dir + no --run-date → output contains 'Resuming existing campaign' and uses that path."""
        summary = _make_summary()
        # Build a fake claudedocs/audit/<old-date>/v3_5b/campaign_v3_5b.jsonl structure.
        old_date = "2026-07-05"
        today_date = "2026-07-07"
        old_run_dir = tmp_path / "claudedocs" / "audit" / old_date
        old_campaign_file = old_run_dir / "v3_5b" / "campaign_v3_5b.jsonl"
        old_campaign_file.parent.mkdir(parents=True, exist_ok=True)
        old_campaign_file.write_text('{"hash":"abc","kind":"oat"}\n')

        # report_output_dir() must return a path whose .parent is the scan base.
        # Returning tmp_path/claudedocs/audit/<today>/ means .parent is
        # tmp_path/claudedocs/audit/, which contains our old_date dir → resume found.
        today_dir = tmp_path / "claudedocs" / "audit" / today_date

        with mock.patch("jutsu_engine.cli.commands.audit.report_output_dir",
                        return_value=today_dir), \
             mock.patch("jutsu_engine.audit.plateau.run_plateau",
                        return_value=summary) as m:
            runner = CliRunner()
            res = runner.invoke(audit, ["plateau", "--strategy", "v3_5b", "--oat-only"])

        assert res.exit_code == 0, res.output
        assert "Resuming existing campaign" in res.output
        # run_plateau must have been called with the OLD run_dir, not today's
        called_run_dir = m.call_args[0][1]
        assert old_date in str(called_run_dir)


class TestLoadCompletedHashesRetryErrors:
    """Unit tests for load_completed_hashes retry_errors parameter (plateau.py)."""

    def test_retry_errors_false_counts_all_rows(self, tmp_path):
        """Default (retry_errors=False): both valid and errored rows count as done."""
        import json
        from jutsu_engine.audit.plateau import load_completed_hashes

        jsonl = tmp_path / "camp.jsonl"
        # One valid row, one errored row (error non-None, sharpe=None)
        valid_row = {"hash": "abc123", "sharpe": 0.8, "error": None}
        error_row = {"hash": "def456", "sharpe": None, "error": "SomeError: boom"}
        with open(jsonl, "w") as f:
            f.write(json.dumps(valid_row) + "\n")
            f.write(json.dumps(error_row) + "\n")

        done = load_completed_hashes(jsonl, retry_errors=False)
        assert "abc123" in done
        assert "def456" in done

    def test_retry_errors_true_excludes_errored_rows(self, tmp_path):
        """retry_errors=True: errored rows (non-None error) are NOT counted as done."""
        import json
        from jutsu_engine.audit.plateau import load_completed_hashes

        jsonl = tmp_path / "camp.jsonl"
        valid_row = {"hash": "abc123", "sharpe": 0.8, "error": None}
        error_row = {"hash": "def456", "sharpe": None, "error": "SomeError: boom"}
        with open(jsonl, "w") as f:
            f.write(json.dumps(valid_row) + "\n")
            f.write(json.dumps(error_row) + "\n")

        done = load_completed_hashes(jsonl, retry_errors=True)
        assert "abc123" in done
        assert "def456" not in done

    def test_retry_errors_true_excludes_nonfinite_sharpe_rows(self, tmp_path):
        """retry_errors=True also excludes rows with non-finite sharpe (error=None but sharpe=nan)."""
        import json
        import math
        from jutsu_engine.audit.plateau import load_completed_hashes

        jsonl = tmp_path / "camp.jsonl"
        nan_row = {"hash": "nan111", "sharpe": float("nan"), "error": None}
        valid_row = {"hash": "ok222", "sharpe": 1.2, "error": None}
        with open(jsonl, "w") as f:
            f.write(json.dumps(nan_row) + "\n")
            f.write(json.dumps(valid_row) + "\n")

        done = load_completed_hashes(jsonl, retry_errors=True)
        assert "nan111" not in done
        assert "ok222" in done
