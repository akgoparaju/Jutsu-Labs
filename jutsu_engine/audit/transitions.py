"""Module — crash-episode registry + transition scorer (spec §4/§5).

Pure, DB-free functions. The registry (grid-configs/audit/crash_episodes.yaml) is
human-curated and versioned; load_episodes/validate_episodes parse and sanity-check
it. Task 2 verifies each peak/trough against QQQ closes in market_data (read-only)
and corrects the YAML to the data. The transition-scorer functions (Task 3) consume
a WARMUP-TRIMMED regime timeseries (EXP-006), QQQ closes, and the registry.

Conventions (verbatim for downstream consumers, e.g. Task-12 gate renderer):
  * Trading-row positioning: all lags/caps are measured in POSITIONS within the
    warmup-trimmed trading-day series, never in calendar (timedelta) days. The
    +120-day whipsaw/reentry cap therefore means 120 TRADING days (rows), not 120
    calendar days.
  * Span boundary: the episode span is the INCLUSIVE range [peak, trough] on
    trading rows — a trading row whose date equals the peak or the trough is inside
    the span.
  * Peak anchoring: the exit-lag anchor is the first trading row on-or-after the
    episode peak (resolves holiday/weekend peaks by snapping forward to the next
    trading day).
  * flip_count_ratio may return +inf (stock arm has 0 flips but the arm has >0);
    the Task-12 gate consumer must special-case inf when differencing ratios
    (e.g. inf - inf is NaN and must be handled explicitly, not treated as 0).
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

    Consumes a regime timeseries (warmup-trimmed here defensively). All lags/caps
    are measured in POSITIONS within the trimmed trading-day series, never calendar
    days. The episode span is the INCLUSIVE trading-row range [peak, trough].

    Metrics:
      exit_lag_days     SIGNED trading-row lag from the peak anchor to the strategy's
                        defensive transition (see below); None if the strategy is
                        offensive at the anchor and never de-risks in-span.
      drawdown_capture  strat MaxDD / QQQ MaxDD within [peak,trough] (lower better;
                        1.0 = no protection); None if QQQ MaxDD is 0.
      reentry_lag_days  trading-row lag from the trough row to the first offensive
                        cell (1/2/3) on-or-after the trough; None if never re-enters
                        within the cap (trough + 120 TRADING rows, clipped to series).
      whipsaw_flips     count of vol-state flips within [peak, cap], where cap is the
                        earlier of the recovery row and peak + 120 TRADING rows.
      days_defensive    count of defensive-cell trading rows within [peak, trough].

    exit_lag_days semantics (signed, run-start based):
      anchor = the first trading row on-or-after the episode peak (its integer
      position in the trimmed series). This snaps a holiday/weekend peak forward to
      the next trading day.
        * If the strategy is DEFENSIVE (cell 4/5/6) AT the anchor row:
          exit_lag_days = (start position of the CONTIGUOUS defensive run that
          contains the anchor) - anchor_position. This is <= 0 and credits the
          strategy from when that particular defensive run began — a run that began
          BEFORE the peak yields a NEGATIVE lag ("de-risked before the peak"). Only
          the run containing the anchor earns credit: a brief defensive dip that
          ENDED before the peak (offensive again at the anchor) earns NO negative
          credit.
        * Otherwise (offensive at the anchor):
          exit_lag_days = (position of the first defensive row strictly after the
          anchor and still within the span [peak, trough]) - anchor_position. This
          is > 0. If no defensive row exists in-span after the anchor -> None.

    Returns a dict; skipped=True (all metrics None/0) when the episode span does not
    overlap the timeseries — surfaced loudly by the caller.
    """
    df = trim_warmup(ts, start)
    df = df.assign(cell=df["Regime"].map(_cell_of))
    df["d"] = df["Date"].dt.tz_convert("UTC").dt.date

    base = {"episode": ep.id, "exit_lag_days": None, "reentry_lag_days": None,
            "drawdown_capture": None, "whipsaw_flips": 0, "days_defensive": 0,
            "skipped": False}

    if df.empty or ep.trough < df["d"].min() or ep.peak > df["d"].max():
        return {**base, "skipped": True}

    cells = df["cell"].tolist()
    dates = df["d"].tolist()
    n = len(df)
    defensive_set = set(DEFENSIVE_CELLS)
    offensive_set = set(OFFENSIVE_CELLS)

    # positional span [peak, trough] inclusive on trading rows
    span_mask = (df["d"] >= ep.peak) & (df["d"] <= ep.trough)
    span = df[span_mask]

    # anchor = position of first trading row on-or-after the peak
    anchor = next((i for i, d in enumerate(dates) if d >= ep.peak), None)

    # exit_lag: signed, run-start based (see docstring)
    if anchor is not None:
        if cells[anchor] in defensive_set:
            # walk backward to the start of the contiguous defensive run @ anchor
            run_start = anchor
            while run_start - 1 >= 0 and cells[run_start - 1] in defensive_set:
                run_start -= 1
            base["exit_lag_days"] = run_start - anchor  # <= 0
        else:
            # first defensive row strictly after anchor, within span [peak, trough]
            first_def = None
            for i in range(anchor + 1, n):
                if dates[i] > ep.trough:
                    break
                if cells[i] in defensive_set:
                    first_def = i
                    break
            if first_def is not None:
                base["exit_lag_days"] = first_def - anchor  # > 0
            # else None (never defensive in-span after the anchor)

    # days_defensive within [peak, trough]
    base["days_defensive"] = int(span["cell"].isin(sorted(DEFENSIVE_CELLS)).sum())

    # drawdown_capture within [peak, trough]
    if not span.empty:
        strat_dd = abs(_max_drawdown(span["Strategy_Daily_Return"]))
        qqq_dd = abs(_max_drawdown(span["QQQ_Daily_Return"]))
        base["drawdown_capture"] = float(strat_dd / qqq_dd) if qqq_dd > 0 else None

    # reentry_lag: first offensive cell on-or-after trough, capped at trough + 120
    # TRADING rows (positional), clipped to the series. Lag is relative to the trough
    # row position.
    trough_pos = next((i for i, d in enumerate(dates) if d >= ep.trough), None)
    if trough_pos is not None:
        reentry_cap_pos = min(trough_pos + 120, n - 1)
        for i in range(trough_pos, reentry_cap_pos + 1):
            if cells[i] in offensive_set:
                base["reentry_lag_days"] = i - trough_pos
                break

    # whipsaw_flips: vol-state flips within [peak, cap], cap = earlier of the
    # recovery row and peak + 120 TRADING rows (positional).
    if anchor is not None:
        recovery_pos = next(
            (i for i in range(n - 1, -1, -1) if dates[i] <= ep.recovery), None
        )
        whip_cap_pos = anchor + 120
        if recovery_pos is not None:
            whip_cap_pos = min(whip_cap_pos, recovery_pos)
        whip_cap_pos = min(whip_cap_pos, n - 1)
        vol = df["Vol"].tolist()[anchor:whip_cap_pos + 1]
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
    """Ratio of an arm's vol-flip count to the stock arm's.

    Returns +inf when the stock arm has 0 flips but the arm has >0 (undefined ratio,
    surfaced as inf rather than clipped), and 1.0 when both have 0. Downstream
    consumers (the Task-12 gate) MUST handle inf explicitly: differencing two ratios
    where both are inf yields NaN (inf - inf), which must not be silently treated as
    a zero delta.
    """
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

    NaN policy: non-finite scores are dropped PAIRWISE (score+label together) before
    ranking. A NaN score would otherwise sort last under mergesort and bias the AUC
    toward 1.0; dropping it is the neutral choice. Returns nan if fewer than 2 finite
    pairs remain, or if the surviving labels are single-class.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    # drop non-finite scores pairwise (score+label) before ranking
    finite = np.isfinite(s)
    s = s[finite]
    y = y[finite]
    if len(s) < 2:
        return float("nan")
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
