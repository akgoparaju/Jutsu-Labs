"""Module — vol-input series builders (spec §6). Precomputed-series adapter arms.

One builder per non-stock arm -> identical CSV schema
(date, value, source, constructed_at). All windows TRAILING-ONLY (causal); every
series is T-1 aligned by the battery (the value for day D's decision comes from the
row stamped D-1). Pure functions here (z_ema5_pipeline, dedup_vix_daily, write_series)
are DB-free unit-tested; build_vix_series is the single read-only DB reader.

MARKET_DATA DATE-SHIFT CONVENTION (verified 2026-07-13): $VIX has ~1,879 duplicate-
date days (two rows per date, different close + created_at). On 2020-03-16 the real
CBOE peak close 82.69 is on the EARLIER intraday timestamp (05:00-07:00); 75.91 is on
the later (22:00-07:00). dedup_vix_daily keeps the earliest-timestamp row per date;
build_vix_series validates this choice against the 82.69 anchor and raises if the
convention ever changes, so a silent data re-shift cannot corrupt the vix arm.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SERIES_COLUMNS = ["date", "value", "source", "constructed_at"]

# Anchor: $VIX COVID peak close on its real date (CBOE). Validates the dedup choice.
VIX_ANCHOR_DATE = date(2020, 3, 16)
VIX_ANCHOR_CLOSE = 82.69
VIX_ANCHOR_TOL = 0.01

KRONOS_PARQUET_REL = "claudedocs/inputs/QQQ_kronos_base.parquet"
KRONOS_HORIZON = 5


def z_ema5_pipeline(values: pd.Series, window: int = 200,
                    ema_span: int = 5) -> pd.Series:
    """Trailing z-score (window, min_periods=window) then EMA(span) — causal.

    Mirrors the Kronos recipe steps 2-3 (handoff §1): z vs trailing `window`-bar
    mean/std (min_periods=window preserves leading warmup NaN, never forward-fills),
    then ewm(span, adjust=False). Trailing-only => a truncated input produces an
    identical value prefix (the T-1 causality guarantee). Returns a float Series
    indexed like `values` (leading NaN preserved).
    """
    v = pd.Series(values, dtype=float).reset_index(drop=True)
    mean = v.rolling(window=window, min_periods=window).mean()
    std = v.rolling(window=window, min_periods=window).std(ddof=0)
    z = (v - mean) / std
    z = z.where(std != 0, 0.0)          # zero-variance window -> z=0 (not inf)
    z = z.mask(mean.isna())             # keep warmup NaN where the window is short
    return z.ewm(span=ema_span, adjust=False).mean().where(z.notna())


def dedup_vix_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per calendar date: the EARLIEST intraday timestamp (real close).

    Input: DataFrame with tz-aware 'date' (full timestamp) and 'close'. $VIX stores
    two rows per date under different intraday timestamps; the earlier one carries the
    correct CBOE close (verified against the 2020-03-16 = 82.69 anchor). Returns a
    date-sorted DataFrame with one row per calendar day.
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"], utc=True)
    d["_cal"] = d["date"].dt.date
    d = d.sort_values("date")               # earliest timestamp first
    d = d.drop_duplicates(subset="_cal", keep="first")
    return d.drop(columns="_cal").sort_values("date").reset_index(drop=True)


def write_series(path: Path, df: pd.DataFrame, source: str,
                 provenance: str) -> Path:
    """Write a builder CSV (SERIES_COLUMNS) with a provenance header comment.

    df has columns date (tz-aware) and value (float, NaN allowed). source names the
    arm (e.g. 'vix'). The header comment records how the series was constructed so a
    reader can reproduce it. constructed_at is a UTC ISO timestamp per row.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], utc=True).dt.date.astype(str),
        "value": df["value"].astype(float),
        "source": source,
        "constructed_at": now,
    })[SERIES_COLUMNS]
    with open(path, "w") as f:
        f.write(f"# vol-input series | source={source} | {provenance}\n")
        out.to_csv(f, index=False)
    return path


def build_vix_series(engine, window: int = 200, ema_span: int = 5) -> pd.DataFrame:
    """READ-ONLY: $VIX daily close -> dedup -> z(window) -> EMA(span). Anchor-validated.

    Returns a DataFrame with columns date (tz-aware) and value (float, warmup NaN),
    date-sorted. Raises ValueError if the 2020-03-16 dedup does not recover the 82.69
    anchor close (guards against a silent market_data re-shift).
    """
    from sqlalchemy import text
    q = text(
        "SELECT timestamp, close FROM market_data "
        "WHERE symbol='$VIX' AND timeframe='1D' ORDER BY timestamp"
    )
    with engine.connect() as c:
        rows = list(c.execute(q))
    raw = pd.DataFrame(rows, columns=["date", "close"])
    raw["close"] = raw["close"].astype(float)
    daily = dedup_vix_daily(raw)

    anchor = daily[daily["date"].dt.date == VIX_ANCHOR_DATE]
    if anchor.empty or abs(float(anchor["close"].iloc[0]) - VIX_ANCHOR_CLOSE) > VIX_ANCHOR_TOL:
        got = None if anchor.empty else float(anchor["close"].iloc[0])
        raise ValueError(
            f"$VIX anchor validation failed: {VIX_ANCHOR_DATE} close={got}, "
            f"expected {VIX_ANCHOR_CLOSE}. The market_data date-shift convention "
            f"changed; re-verify dedup_vix_daily before trusting the vix arm."
        )
    value = z_ema5_pipeline(daily["close"], window=window, ema_span=ema_span)
    return pd.DataFrame({"date": daily["date"], "value": value.values})


def build_kronos_from_frame(frame: pd.DataFrame, window: int = 200,
                            ema_span: int = 5) -> pd.DataFrame:
    """Kronos forward-vol std_return @ horizon=5 -> z(window) -> EMA(span). Causal.

    Implements the handoff recipe (§1 steps 1-3): take std_return where horizon==5
    (this is 'std_return_5'), z-score vs its own trailing `window` rows (min_periods
    window), EMA(span). `frame` has columns timestamp, horizon, std_return. Returns a
    DataFrame with columns date (tz-aware) and value (float, warmup NaN). Trailing-
    only => causal (a truncated frame yields an identical value prefix).
    """
    h5 = frame[frame["horizon"] == KRONOS_HORIZON].copy()
    h5["timestamp"] = pd.to_datetime(h5["timestamp"], utc=True)
    h5 = h5.sort_values("timestamp").reset_index(drop=True)
    value = z_ema5_pipeline(h5["std_return"], window=window, ema_span=ema_span)
    return pd.DataFrame({"date": h5["timestamp"], "value": value.values})


def build_kronos_series(parquet_path: Path | None = None, window: int = 200,
                        ema_span: int = 5) -> pd.DataFrame:
    """Read the copied Kronos parquet and build the kronos vol-input series.

    Thin wrapper over build_kronos_from_frame. Uses the repo-local copy under
    claudedocs/inputs/ (checksummed; the source repo is NOT a dependency of ours).
    """
    from jutsu_engine.audit.config import PROJECT_ROOT
    parquet_path = Path(parquet_path) if parquet_path is not None \
        else PROJECT_ROOT / KRONOS_PARQUET_REL
    frame = pd.read_parquet(parquet_path)
    return build_kronos_from_frame(frame, window=window, ema_span=ema_span)


def build_smoothing_from_stream(stream: pd.DataFrame, ema_span: int = 5) -> pd.DataFrame:
    """EMA5 of the engine-truth vol-z stream (no external information; zero-info control).

    `stream` has columns date and z_score (from battery.replay_signal_stream). Returns
    a DataFrame with columns date, value = ewm(span, adjust=False) of z_score. Trailing-
    only (causal). This isolates the FILTER effect from any information content.
    """
    s = stream.copy()
    s["date"] = pd.to_datetime(s["date"], utc=True)
    s = s.sort_values("date").reset_index(drop=True)
    value = s["z_score"].astype(float).ewm(span=ema_span, adjust=False).mean()
    return pd.DataFrame({"date": s["date"], "value": value.values})
