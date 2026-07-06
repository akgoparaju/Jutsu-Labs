from datetime import date
from pathlib import Path

from jutsu_engine.audit.config import (
    AUDIT_STRATEGIES,
    StrategySpec,
    resolve_strategy,
    report_output_dir,
    LIVE_RECON_START,
)


class TestAuditConfig:
    def test_strategy_registry_has_both_live_strategies(self):
        assert set(AUDIT_STRATEGIES.keys()) == {"v3_5b", "v3_5d"}

    def test_resolve_strategy_returns_spec(self):
        spec = resolve_strategy("v3_5b")
        assert isinstance(spec, StrategySpec)
        assert spec.strategy_id == "v3_5b"
        assert spec.class_name == "Hierarchical_Adaptive_v3_5b"
        assert spec.module_path == "jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b"
        assert spec.config_rel_path == "config/strategies/v3_5b.yaml"

    def test_resolve_strategy_unknown_raises(self):
        try:
            resolve_strategy("nope")
            assert False, "expected KeyError"
        except KeyError as e:
            assert "nope" in str(e)

    def test_report_output_dir_uses_date(self):
        out = report_output_dir(base=Path("/tmp/x"), run_date=date(2026, 7, 6))
        assert out == Path("/tmp/x/claudedocs/audit/2026-07-06")

    def test_live_recon_start_is_dec_2025(self):
        assert LIVE_RECON_START == date(2025, 12, 1)
