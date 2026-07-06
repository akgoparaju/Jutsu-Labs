import pytest
from datetime import date
from pathlib import Path

from jutsu_engine.audit.config import (
    AUDIT_STRATEGIES,
    StrategySpec,
    resolve_strategy,
    report_output_dir,
    LIVE_RECON_START,
    ATTRIBUTION_START,
)


class TestAuditConfig:
    def test_strategy_registry_has_both_live_strategies(self):
        """Registry contains exactly the two live strategy ids."""
        assert set(AUDIT_STRATEGIES.keys()) == {"v3_5b", "v3_5d"}

    def test_resolve_strategy_returns_spec(self):
        """resolve_strategy returns a fully-populated StrategySpec for a known id."""
        spec = resolve_strategy("v3_5b")
        assert isinstance(spec, StrategySpec)
        assert spec.strategy_id == "v3_5b"
        assert spec.class_name == "Hierarchical_Adaptive_v3_5b"
        assert spec.module_path == "jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b"
        assert spec.config_rel_path == "config/strategies/v3_5b.yaml"

    def test_resolve_strategy_unknown_raises(self):
        """Unknown strategy ids raise KeyError naming the bad id."""
        with pytest.raises(KeyError, match="nope"):
            resolve_strategy("nope")

    def test_report_output_dir_uses_date(self):
        """report_output_dir builds a date-stamped path under claudedocs/audit."""
        out = report_output_dir(base=Path("/tmp/x"), run_date=date(2026, 7, 6))
        assert out == Path("/tmp/x/claudedocs/audit/2026-07-06")

    def test_live_recon_start_is_dec_2025(self):
        """LIVE_RECON_START marks the beginning of the live-trading reconciliation window."""
        assert LIVE_RECON_START == date(2025, 12, 1)

    def test_attribution_start_is_tqqq_inception_bound(self):
        """ATTRIBUTION_START pins the spec's full-period start (TQQQ inception bound)."""
        assert ATTRIBUTION_START == date(2010, 2, 1)
