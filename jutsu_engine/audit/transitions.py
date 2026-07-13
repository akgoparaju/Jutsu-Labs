"""Module — crash-episode registry + transition scorer (spec §4/§5).

Pure, DB-free functions. The registry (grid-configs/audit/crash_episodes.yaml) is
human-curated and versioned; load_episodes/validate_episodes parse and sanity-check
it. Task 2 verifies each peak/trough against QQQ closes in market_data (read-only)
and corrects the YAML to the data. The transition-scorer functions (Task 3) consume
a WARMUP-TRIMMED regime timeseries (EXP-006), QQQ closes, and the registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from jutsu_engine.audit.config import PROJECT_ROOT

REGISTRY_PATH = PROJECT_ROOT / "grid-configs" / "audit" / "crash_episodes.yaml"

# Defensive cells (strategy is "out"/de-risked); offensive cells (strategy is "in").
DEFENSIVE_CELLS: frozenset[int] = frozenset({4, 5, 6})
OFFENSIVE_CELLS: frozenset[int] = frozenset({1, 2, 3})


@dataclass(frozen=True)
class Episode:
    """One crash episode with QQQ-verified peak/trough (recovery = documentation)."""
    id: str
    peak: date
    trough: date
    recovery: date
    portfolio_scored: bool


def _as_date(v) -> date:
    """Coerce a YAML scalar (date or ISO string) to a datetime.date."""
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load_episodes(path: Path | None = None) -> list[Episode]:
    """Parse the registry YAML into a validated, chronological list of Episodes."""
    path = Path(path) if path is not None else REGISTRY_PATH
    with open(path, "r") as f:
        doc = yaml.safe_load(f)
    eps = [
        Episode(
            id=str(e["id"]),
            peak=_as_date(e["peak"]),
            trough=_as_date(e["trough"]),
            recovery=_as_date(e["recovery"]),
            portfolio_scored=bool(e["portfolio_scored"]),
        )
        for e in doc["episodes"]
    ]
    validate_episodes(eps)
    return eps


def validate_episodes(eps: list[Episode]) -> None:
    """Raise ValueError if any episode is malformed or ids are not unique."""
    seen: set[str] = set()
    for e in eps:
        if e.id in seen:
            raise ValueError(f"duplicate episode id: {e.id!r}")
        seen.add(e.id)
        if not (e.peak < e.trough):
            raise ValueError(
                f"episode {e.id!r}: peak {e.peak} must be before trough {e.trough}"
            )
        if not (e.trough <= e.recovery):
            raise ValueError(
                f"episode {e.id!r}: trough {e.trough} must be <= recovery {e.recovery}"
            )
