"""DB-free CLI wiring tests for `jutsu audit dsr` (run_dsr monkeypatched)."""
from click.testing import CliRunner

from jutsu_engine.cli.commands import audit as audit_cli


def _fake_summary(sid):
    return {
        "strategy_id": sid, "n_combos": 243, "cross_trial_V": 0.0004,
        "golden_hash": "abc123def4567890",
        "golden_moments": {"sr_obs": 0.05, "skew": 0.0, "kurt_nonexcess": 3.0, "T": 4000},
        "trial_inventory": [],
        "dsr_brackets": [
            {"N": 243, "sr_obs": 0.05, "sr_star": 0.056, "dsr": 0.30, "T": 4000},
            {"N": 1000, "sr_obs": 0.05, "sr_star": 0.062, "dsr": 0.18, "T": 4000},
            {"N": 5000, "sr_obs": 0.05, "sr_star": 0.068, "dsr": 0.09, "T": 4000},
        ],
        "pbo": {"pbo": 0.55, "prob_oos_loss": 0.4, "degradation_slope": 0.3,
                "n_partitions": 12870,
                "logit_histogram": {"counts": [1], "edges": [-1, 1], "median": -0.3}},
    }


def test_dsr_cmd_runs_and_writes_report(tmp_path, monkeypatch):
    """`jutsu audit dsr --strategy v3_5b` runs run_dsr and writes report_dsr_v3_5b.md."""
    monkeypatch.setattr(audit_cli, "report_output_dir", lambda **k: tmp_path)

    def fake_run_dsr(strategy_id, run_dir, **kwargs):
        return _fake_summary(strategy_id)

    monkeypatch.setattr("jutsu_engine.audit.selection_bias.run_dsr", fake_run_dsr)
    # Inventory query is best-effort; make it return [] without touching a DB.
    monkeypatch.setattr(audit_cli, "_load_trial_inventory", lambda sid: [])

    result = CliRunner().invoke(audit_cli.audit, ["dsr", "--strategy", "v3_5b"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "report_dsr_v3_5b.md").exists()


def test_dsr_cmd_skip_campaign_flag(tmp_path, monkeypatch):
    """--skip-campaign is threaded into run_dsr."""
    monkeypatch.setattr(audit_cli, "report_output_dir", lambda **k: tmp_path)
    seen = {}

    def fake_run_dsr(strategy_id, run_dir, **kwargs):
        seen.update(kwargs)
        return _fake_summary(strategy_id)

    monkeypatch.setattr("jutsu_engine.audit.selection_bias.run_dsr", fake_run_dsr)
    monkeypatch.setattr(audit_cli, "_load_trial_inventory", lambda sid: [])

    result = CliRunner().invoke(
        audit_cli.audit, ["dsr", "--strategy", "v3_5b", "--skip-campaign"])
    assert result.exit_code == 0, result.output
    assert seen.get("skip_campaign") is True
