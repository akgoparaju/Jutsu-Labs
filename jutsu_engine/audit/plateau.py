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

import hashlib
import json
import math
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


# Spec §6: one-at-a-time at +/-10% and +/-20% (multiplicative).
OAT_MULTIPLIERS: tuple[float, ...] = (0.8, 0.9, 1.1, 1.2)

# Validity floors by parameter family. Windows need >=5 bars; period-smoothers >=2.
_WINDOW_PARAMS = frozenset({
    "sma_fast", "sma_slow", "realized_vol_window", "vol_baseline_window",
    "bond_sma_fast", "bond_sma_slow",
})
_PERIOD_PARAMS = frozenset({
    "osc_smoothness", "strength_smoothness", "vol_crush_lookback",
})


def _is_int_param(name: str, golden_value) -> bool:
    """True if the parameter is integer-valued (stored as int in the YAML)."""
    return isinstance(golden_value, int) and not isinstance(golden_value, bool)


def _apply_validity(name: str, value: float, golden_value):
    """Clamp to validity floors and round integers.

    - Integer params (windows/periods) are rounded to nearest int and clamped to
      their floor (windows >=5, periods >=2).
    - Sign is preserved automatically by multiplicative perturbation (no clamp
      flips a negative threshold positive).
    """
    if _is_int_param(name, golden_value):
        v = int(round(value))
        if name in _WINDOW_PARAMS:
            v = max(v, 5)
        elif name in _PERIOD_PARAMS:
            v = max(v, 2)
        return v
    return value


def params_hash(overrides: dict) -> str:
    """Stable 16-char hex hash of an overrides dict (order-independent)."""
    payload = json.dumps(overrides, sort_keys=True, separators=(",", ":"),
                         default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def oat_samples(golden: dict) -> list[dict]:
    """One-at-a-time perturbation samples over the perturbable params of `golden`.

    Each sample: {"kind": "oat", "param": name, "overrides": {name: value},
                  "hash": <hash>}. Multiplier variants that (after integer
    rounding / floor clamping) collapse to the golden value are deduped away.
    """
    out = []
    per = perturbable_params(golden)
    for name, gval in per.items():
        seen: set = set()
        for mult in OAT_MULTIPLIERS:
            raw = gval * mult
            val = _apply_validity(name, raw, gval)
            if val == gval or val in seen:
                continue  # rounding/clamp collapsed to golden or a duplicate
            seen.add(val)
            overrides = {name: val}
            out.append({
                "kind": "oat",
                "param": name,
                "overrides": overrides,
                "hash": params_hash(overrides),
            })
    return out
