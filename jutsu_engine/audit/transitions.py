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


# ---------------------------------------------------------------------------
# Task 3 — Portfolio-level transition scorer
# ---------------------------------------------------------------------------

from datetime import date as _date
from datetime import timedelta as _timedelta

import numpy as np
import pandas as pd


def trim_warmup(ts: pd.DataFrame, start: _date) -> pd.DataFrame:
    """Drop regime-timeseries rows dated before `start` (EXP-006 warmup pollution).

    Regime-timeseries CSVs prepend warmup rows dated before the backtest start with
    0.0 returns; computing any metric on them dilutes results (EXP-006). Trim to
    Date >= start BEFORE any scoring. Dates are compared in UTC.
    """
    df = ts.copy()
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    start_ts = pd.Timestamp(start, tz="UTC")
    return df[df["Date"] >= start_ts].reset_index(drop=True)


def _cell_of(regime) -> int:
    """'Cell_4' -> 4; -1 for unparseable (mirrors attribution._cell_from_regime)."""
    try:
        return int(str(regime).split("_")[1])
    except (IndexError, ValueError):
        return -1


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    if len(r) == 0:
        return 0.0
    equity = (1.0 + r).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def score_episode_portfolio(ts: pd.DataFrame, ep: Episode, start: _date) -> dict:
    """Portfolio-level transition metrics for one (arm, episode) pair.

    Consumes a regime timeseries (warmup-trimmed here defensively), scores:
      exit_lag_days   trading days peak -> first defensive cell (4/5/6); negative if
                      de-risked before peak; None if never defensive in [peak,trough].
      drawdown_capture  strat MaxDD / QQQ MaxDD within [peak,trough] (lower better;
                      1.0 = no protection); None if QQQ MaxDD is 0.
      reentry_lag_days  trading days trough -> first offensive cell (1/2/3) after
                      trough; None if never re-enters by recovery+120d.
      whipsaw_flips   count of vol-state flips within [peak, min(recovery, +120d)].
      days_defensive  count of defensive-cell days within [peak, trough].
    Returns a dict; skipped=True (all metrics None/0) when the episode span does not
    overlap the timeseries — surfaced loudly by the caller.
    """
    df = trim_warmup(ts, start)
    df = df.assign(cell=df["Regime"].map(_cell_of))
    df["d"] = df["Date"].dt.tz_convert("UTC").dt.date

    base = {"episode": ep.id, "exit_lag_days": None, "reentry_lag_days": None,
            "drawdown_capture": None, "whipsaw_flips": 0, "days_defensive": 0,
            "skipped": False}

    span = df[(df["d"] >= ep.peak) & (df["d"] <= ep.trough)]
    if df.empty or ep.trough < df["d"].min() or ep.peak > df["d"].max():
        return {**base, "skipped": True}

    # exit_lag: index the trading days; find first defensive at/after peak.
    at_or_after_peak = df[df["d"] >= ep.peak].reset_index(drop=True)
    defensive = at_or_after_peak[at_or_after_peak["cell"].isin(sorted(DEFENSIVE_CELLS))]
    if not defensive.empty:
        # position (0-based) of first defensive row relative to the peak row
        base["exit_lag_days"] = int(defensive.index[0])
    # (None already set if never defensive after peak)

    # days_defensive within [peak, trough]
    base["days_defensive"] = int(span["cell"].isin(sorted(DEFENSIVE_CELLS)).sum())

    # drawdown_capture within [peak, trough]
    if not span.empty:
        strat_dd = abs(_max_drawdown(span["Strategy_Daily_Return"]))
        qqq_dd = abs(_max_drawdown(span["QQQ_Daily_Return"]))
        base["drawdown_capture"] = float(strat_dd / qqq_dd) if qqq_dd > 0 else None

    # reentry_lag: first offensive cell after trough, capped at recovery+120d
    cap = min(ep.recovery + _timedelta(days=120),
              df["d"].max() + _timedelta(days=1))
    after_trough = df[(df["d"] >= ep.trough) & (df["d"] <= cap)].reset_index(drop=True)
    offensive = after_trough[after_trough["cell"].isin(sorted(OFFENSIVE_CELLS))]
    if not offensive.empty:
        base["reentry_lag_days"] = int(offensive.index[0])

    # whipsaw_flips: vol-state flips within [peak, min(recovery, peak+120d)]
    whip_cap = min(ep.recovery, ep.peak + _timedelta(days=120))
    whip = df[(df["d"] >= ep.peak) & (df["d"] <= whip_cap)]
    vol = whip["Vol"].tolist()
    base["whipsaw_flips"] = int(sum(1 for a, b in zip(vol, vol[1:]) if a != b))

    return base


# ---------------------------------------------------------------------------
# Task 4 — Signal-level transition helpers
# ---------------------------------------------------------------------------


def _count_flips(vol_states: list[str]) -> int:
    """Number of consecutive-day vol-state changes in a Low/High sequence."""
    return sum(1 for a, b in zip(vol_states, vol_states[1:]) if a != b)


def signal_flip_lead_lag(dates, vol_states, ep: Episode):
    """Trading days from an episode's peak to the first Low->High vol flip.

    Positive = the flip lags the peak (High-vol detected AFTER the peak). Negative =
    leads (detected before). None if no Low->High flip occurs in the series after the
    first row at/after peak. `dates` and `vol_states` are parallel lists ordered
    chronologically. dates may be strings or Timestamps.
    """
    ds = [pd.Timestamp(d).date() if not isinstance(d, _date) else d for d in dates]
    idx_peak = next((i for i, d in enumerate(ds) if d >= ep.peak), None)
    if idx_peak is None:
        return None
    for j in range(max(idx_peak, 1), len(vol_states)):
        if vol_states[j - 1] == "Low" and vol_states[j] == "High":
            return j - idx_peak
    return None


def flip_count_ratio(arm_vol: list[str], stock_vol: list[str]) -> float:
    """Ratio of an arm's vol-flip count to the stock arm's (inf if stock has 0)."""
    n_stock = _count_flips(stock_vol)
    n_arm = _count_flips(arm_vol)
    if n_stock == 0:
        return float("inf") if n_arm > 0 else 1.0
    return float(n_arm) / float(n_stock)


def auc_vol_state_forward(scores, labels) -> float:
    """AUC of a continuous score for a binary label (Mann-Whitney U form).

    scores and labels are parallel: labels[i] == 1 means vol-state@t+21 is High for
    row i (the caller aligns the +21 shift and drops the tail). Returns the rank-AUC
    (fraction of (positive, negative) pairs the score orders correctly, ties = 0.5).
    Returns nan for a single-class label vector (undefined AUC), mirroring the
    Kronos VER1 convention. This is compared against the raw-bar range 0.815-0.828.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # rank-based Mann-Whitney U / (n_pos * n_neg)
    combined = np.concatenate([pos, neg])
    sort_idx = np.argsort(combined, kind="mergesort")
    tie_ranks = np.empty(len(combined), dtype=float)
    srt = combined[sort_idx]
    i = 0
    pos_rank = 1
    while i < len(srt):
        j = i
        while j + 1 < len(srt) and srt[j + 1] == srt[i]:
            j += 1
        avg = (pos_rank + (pos_rank + (j - i))) / 2.0
        for k in range(i, j + 1):
            tie_ranks[sort_idx[k]] = avg
        pos_rank += (j - i + 1)
        i = j + 1
    rank_pos_sum = tie_ranks[:len(pos)].sum()
    n_pos, n_neg = len(pos), len(neg)
    u = rank_pos_sum - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))
