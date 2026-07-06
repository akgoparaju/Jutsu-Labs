"""Shared audit scaffolding: strategy registry and output-path helpers.

Kept deliberately small so Modules 1/2/3 (added later) can import the same
registry. Mirrors scripts/backfill_regime.py:STRATEGIES so the audit replays
the exact live strategies and configs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Project root = three parents up from this file (jutsu_engine/audit/config.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Live reconciliation window start (spec §9: "Dec 2025 -> present").
LIVE_RECON_START = date(2025, 12, 1)

# Full-period attribution start (spec §8/§5: TQQQ inception bounds ~2010-02).
ATTRIBUTION_START = date(2010, 2, 1)


@dataclass(frozen=True)
class StrategySpec:
    """One live strategy: how to import it and where its live config lives."""
    strategy_id: str          # e.g. "v3_5b"
    module_path: str          # importable module
    class_name: str           # Strategy subclass name inside that module
    config_rel_path: str      # path to the live YAML config, relative to PROJECT_ROOT

    @property
    def config_path(self) -> Path:
        return PROJECT_ROOT / self.config_rel_path


# Registry mirrors scripts/backfill_regime.py:53-58 exactly.
AUDIT_STRATEGIES: dict[str, StrategySpec] = {
    "v3_5b": StrategySpec(
        strategy_id="v3_5b",
        module_path="jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b",
        class_name="Hierarchical_Adaptive_v3_5b",
        config_rel_path="config/strategies/v3_5b.yaml",
    ),
    "v3_5d": StrategySpec(
        strategy_id="v3_5d",
        module_path="jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d",
        class_name="Hierarchical_Adaptive_v3_5d",
        config_rel_path="config/strategies/v3_5d.yaml",
    ),
}


def resolve_strategy(strategy_id: str) -> StrategySpec:
    """Return the StrategySpec for a strategy id, or raise KeyError."""
    if strategy_id not in AUDIT_STRATEGIES:
        raise KeyError(
            f"Unknown strategy id {strategy_id!r}; "
            f"known: {sorted(AUDIT_STRATEGIES)}"
        )
    return AUDIT_STRATEGIES[strategy_id]


def report_output_dir(base: Path = PROJECT_ROOT, run_date: date | None = None) -> Path:
    """Directory for a report run: <base>/claudedocs/audit/<YYYY-MM-DD>/.

    Does not create the directory (caller decides when to mkdir).
    """
    run_date = run_date or date.today()
    return base / "claudedocs" / "audit" / run_date.isoformat()
