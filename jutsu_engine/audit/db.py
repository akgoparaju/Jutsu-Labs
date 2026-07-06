"""Read-only database access for the audit package.

STRICTLY READ-ONLY: only SELECT statements. No INSERT/UPDATE/DELETE anywhere.
Connection mirrors scripts/backfill_regime.py (env vars via .env). If the
environment is not configured, helpers raise AuditDBUnavailable with a clear
message so callers (CLI/report) can degrade gracefully.

Pure row-shaping functions (rows_to_bars_df, scheduler_snapshots_to_records)
are unit-tested on synthetic rows and require no database.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote_plus

import pandas as pd

_PG_KEYS = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST",
            "POSTGRES_PORT", "POSTGRES_DATABASE")


class AuditDBUnavailable(RuntimeError):
    """Raised when the database cannot be reached or is not configured."""


def build_engine_url(env: Optional[Mapping[str, str]] = None) -> str:
    """Build a read-only PostgreSQL URL from env vars (mirrors backfill_regime.py:62-67).

    Raises AuditDBUnavailable if any POSTGRES_* var is missing.
    """
    env = os.environ if env is None else env
    missing = [k for k in _PG_KEYS if not env.get(k)]
    if missing:
        raise AuditDBUnavailable(
            f"Missing DB config env vars: {missing}. "
            f"Set POSTGRES_USER/PASSWORD/HOST/PORT/DATABASE (see .env)."
        )
    pw = quote_plus(env["POSTGRES_PASSWORD"])
    return (f"postgresql://{env['POSTGRES_USER']}:{pw}@"
            f"{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/"
            f"{env['POSTGRES_DATABASE']}")


def get_engine():
    """Return a SQLAlchemy engine, or raise AuditDBUnavailable.

    Loads .env first (idempotent) so this works from a bare shell like the
    scripts do. connect_timeout keeps failures fast when the DB is unreachable
    from this machine.
    """
    try:
        from dotenv import load_dotenv
        from jutsu_engine.audit.config import PROJECT_ROOT
        load_dotenv(str(PROJECT_ROOT / ".env"))
    except Exception:
        pass  # dotenv is best-effort; env may already be populated
    url = build_engine_url()
    try:
        from sqlalchemy import create_engine
        return create_engine(url, connect_args={"connect_timeout": 15})
    except Exception as e:  # pragma: no cover - infra error path
        raise AuditDBUnavailable(f"Could not create DB engine: {e}") from e


def rows_to_bars_df(rows: Sequence[Any]) -> pd.DataFrame:
    """Shape market_data rows (newest-first) into a chronological OHLCV DataFrame.

    Mirrors scripts/backfill_regime.py:93-99. Input rows are
    (timestamp, open, high, low, close, volume), ordered DESC.
    """
    cols = ["date", "open", "high", "low", "close", "volume"]
    rows = list(rows)[::-1]  # reverse DESC -> chronological
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["volume"] = df["volume"].astype("int64")
    return df


def load_bars(engine, symbol: str, as_of: date, lookback: int = 250) -> pd.DataFrame:
    """Last `lookback` daily bars with trading date <= as_of (mirrors backfill_regime.py:83-99)."""
    from sqlalchemy import text
    q = text(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM market_data "
        "WHERE symbol = :s AND timeframe = '1D' AND (timestamp)::date <= :d "
        "ORDER BY timestamp DESC LIMIT :n"
    )
    with engine.connect() as c:
        rows = list(c.execute(q, {"s": symbol, "d": as_of, "n": lookback}))
    return rows_to_bars_df(rows)


def scheduler_snapshots_to_records(rows: Iterable[Any]) -> list[dict]:
    """Shape scheduler snapshot rows into one record per (strategy, day), latest ts wins.

    Input row layout (matches load_scheduler_snapshots query below):
    (strategy_id, timestamp, day, strategy_cell, trend_state, vol_state,
     t_norm, z_score, total_equity, snapshot_source).
    Returns dicts keyed by: day, strategy_id, strategy_cell, trend_state,
    vol_state, t_norm, z_score, total_equity, snapshot_source.
    Numeric DB values (Decimal) are coerced to float; None passes through.
    """
    def _f(v):
        return None if v is None else float(v)

    by_day: dict[tuple[str, date], dict] = {}
    for r in rows:
        strategy_id, ts, day, cell, trend, vol, t_norm, z, equity, src = r
        key = (strategy_id, day)
        prev = by_day.get(key)
        if prev is not None and prev["_ts"] >= ts:
            continue  # keep the later timestamp for the day
        by_day[key] = {
            "_ts": ts,
            "day": day,
            "strategy_id": strategy_id,
            "strategy_cell": cell,
            "trend_state": trend,
            "vol_state": vol,
            "t_norm": _f(t_norm),
            "z_score": _f(z),
            "total_equity": _f(equity),
            "snapshot_source": src,
        }
    out = [{k: v for k, v in rec.items() if k != "_ts"} for rec in by_day.values()]
    out.sort(key=lambda d: (d["day"], d["strategy_id"]))
    return out


def load_scheduler_snapshots(engine, strategy_id: str, start: date) -> list[dict]:
    """Read scheduler-authoritative snapshots for a strategy since `start` (inclusive).

    Only snapshot_source='scheduler' rows carry valid regime; that filter is the
    authority rule from jutsu_engine/api/routes/performance.py:331-337.
    One record per trading day (latest timestamp).
    """
    from sqlalchemy import text
    q = text(
        "SELECT strategy_id, timestamp, (timestamp)::date AS day, "
        "       strategy_cell, trend_state, vol_state, t_norm, z_score, "
        "       total_equity, snapshot_source "
        "FROM performance_snapshots "
        "WHERE strategy_id = :sid AND snapshot_source = 'scheduler' "
        "      AND (timestamp)::date >= :start "
        "ORDER BY (timestamp)::date, timestamp"
    )
    with engine.connect() as c:
        rows = list(c.execute(q, {"sid": strategy_id, "start": start}))
    return scheduler_snapshots_to_records(rows)


def load_snapshot_source_counts(engine, strategy_id: str, start: date) -> dict[str, int]:
    """Count snapshots by snapshot_source since `start` (for the report's provenance table)."""
    from sqlalchemy import text
    q = text(
        "SELECT snapshot_source, COUNT(DISTINCT (timestamp)::date) "
        "FROM performance_snapshots "
        "WHERE strategy_id = :sid AND (timestamp)::date >= :start "
        "GROUP BY snapshot_source"
    )
    with engine.connect() as c:
        return {src: int(n) for src, n in c.execute(q, {"sid": strategy_id, "start": start})}
