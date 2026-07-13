"""CLI tests for `jutsu audit battery` (stubbed runner; DB-free)."""
from click.testing import CliRunner


def test_battery_help_lists_options():
    """`jutsu audit battery --help` lists --strategy, --arms, --workers, --smoke."""
    from jutsu_engine.cli.commands.audit import audit
    result = CliRunner().invoke(audit, ["battery", "--help"])
    assert result.exit_code == 0
    for opt in ("--strategy", "--arms", "--workers", "--smoke"):
        assert opt in result.output


def test_battery_smoke_invokes_runner(monkeypatch, tmp_path):
    """`--smoke` runs stock + one arm and writes a report (runner stubbed)."""
    import jutsu_engine.cli.commands.audit as audit_cli
    from jutsu_engine.cli.commands.audit import audit

    calls = {}

    def fake_run_battery_and_report(strategy_id, arms, workers, smoke, run_dir):
        calls["args"] = (strategy_id, tuple(arms or ()), workers, smoke)
        return tmp_path / f"report_regime_battery_{strategy_id}.md"

    monkeypatch.setattr(audit_cli, "_run_battery_and_report",
                        fake_run_battery_and_report)
    result = CliRunner().invoke(audit, ["battery", "--strategy", "v3_5b", "--smoke"])
    assert result.exit_code == 0, result.output
    assert calls["args"][0] == "v3_5b"
    assert calls["args"][3] is True        # smoke=True
