"""Module 2 — Parameter plateau map (spec §6).

Pure, seeded perturbation-set generation + a checkpoint/resume campaign runner
(reusing the Phase-1 BacktestRunner bridge) + DB-free analysis functions.

Design contract:
  - Perturbable parameters are the NUMERIC (int/float, non-bool) keys of the live
    YAML's strategy.parameters, minus infra/symbol keys (PERTURBABLE_EXCLUDE).
  - Golden values are READ FROM THE LIVE YAML at runtime, never hard-coded, so
    v3_5d gets its own list automatically.
  - The campaign writes NO per-run CSVs to the report dir: each backtest runs into
    a throwaway tempdir that is cleaned afterward.
  - Analysis functions (plateau_score, degradation_table, cliff_list, joint stats)
    are pure over the collected results and are unit-tested without a database.
"""
from __future__ import annotations

import yaml

from jutsu_engine.audit.config import resolve_strategy

# Infra / symbol / string keys that are numeric-looking or must never perturb.
# Booleans are dropped separately by an isinstance(v, bool) guard (bool is int).
PERTURBABLE_EXCLUDE: frozenset[str] = frozenset({
    "execution_time",
    "signal_symbol", "core_long_symbol", "leveraged_long_symbol",
    "inverse_hedge_symbol", "bull_bond_symbol", "bear_bond_symbol",
    "treasury_trend_symbol",
    "name", "trade_logger",  # LiveStrategyRunner EXCLUDED_PARAMS
})


def load_golden_params(strategy_id: str) -> dict:
    """Return strategy.parameters from the live YAML for a strategy (no DB)."""
    spec = resolve_strategy(strategy_id)
    with open(spec.config_path, "r") as f:
        config = yaml.safe_load(f)
    return dict(config["strategy"]["parameters"])


def perturbable_params(golden: dict) -> dict:
    """Numeric, non-bool, non-infra keys of a golden params dict -> {name: value}.

    bool is a subclass of int in Python, so the bool guard MUST precede the
    (int, float) check or True/False would leak in as 1/0.
    """
    out = {}
    for k, v in golden.items():
        if k in PERTURBABLE_EXCLUDE:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = v
    return out
