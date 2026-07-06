# Baseline Audit — Phase 1 (Live Reconciliation + Era/Cell Attribution) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `jutsu_engine/audit/` package + `jutsu audit` CLI group and implement two audit modules — Module 5 (live-vs-backtest reconciliation) and Module 4 (era/cell attribution) — that emit reproducible markdown reports to `claudedocs/audit/<YYYY-MM-DD>/`.

**Architecture:** Pure analysis layer on top of existing infrastructure. Reconciliation replays the two live strategies through `LiveStrategyRunner.calculate_signals` over EOD `market_data` bars (mirroring `scripts/backfill_regime.py`) and diffs against scheduler-authoritative `performance_snapshots` rows. Attribution runs one full-period backtest per strategy via `BacktestRunner`, then reads the emitted regime-timeseries + portfolio CSVs to bucket daily P&L by regime cell and isolate the Treasury overlay. All statistics are pure functions over synthetic-testable series; database reads are isolated behind thin, gracefully-degrading helpers.

**Tech Stack:** Python 3.11, click (CLI), pandas, SQLAlchemy (read-only), PyYAML, existing `BacktestRunner` / `PerformanceAnalyzer` / `LiveStrategyRunner` / `RegimePerformanceAnalyzer`. Env managed by `uv`.

---

## Ground Truth — Verified Integration Points (read before starting)

These were confirmed by reading the code. Use them exactly; do not re-derive.

**Live replay (Module 5) — canonical pattern is `scripts/backfill_regime.py`:**
- DB engine: `scripts/backfill_regime.py:62-67` — `create_engine(f"postgresql://{USER}:{quote_plus(PW)}@{HOST}:{PORT}/{DB}", connect_args={"connect_timeout": 15})` from env vars `POSTGRES_USER/PASSWORD/HOST/PORT/DATABASE`. `.env` is loaded with `load_dotenv(PROJECT_ROOT / ".env")`.
- Bar loader: `scripts/backfill_regime.py:83-99` — `SELECT timestamp, open, high, low, close, volume FROM market_data WHERE symbol=:s AND timeframe='1D' AND (timestamp)::date <= :d ORDER BY timestamp DESC LIMIT :n`, reversed to chronological; returns DataFrame columns `["date","open","high","low","close","volume"]`. `LOOKBACK = 250` (`:59`).
- Replay: `scripts/backfill_regime.py:102-122` — build a **fresh** `LiveStrategyRunner(strategy_class=..., config_path=...)` per day (clean warmup), load bars for `runner.get_signal_symbol()` and `runner.get_treasury_symbol()`, call `runner.calculate_signals({sym: df})`, read `signals["current_cell"]`, `signals["trend_state"]`, `signals["vol_state"]`.
- `calculate_signals` return keys: `jutsu_engine/live/strategy_runner.py:214-236,298-330` — `current_cell` (int 1–6), `trend_state` (str), `vol_state` (str), `t_norm` (float|None), `z_score` (float|None), plus `timestamp`.
- Strategy registry: `scripts/backfill_regime.py:53-58` — `STRATEGIES = {"v3_5b": ("jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b","Hierarchical_Adaptive_v3_5b","config/strategies/v3_5b.yaml"), "v3_5d": (...,"config/strategies/v3_5d.yaml")}`.

**`PerformanceSnapshot` model — `jutsu_engine/data/models.py:286-356`:**
- Columns: `id`, `timestamp` (DateTime tz), `total_equity` (Numeric), `cash`, `positions_value`, `daily_return`, `cumulative_return`, `drawdown`, `strategy_cell` (Integer 1–6), `trend_state` (String), `vol_state` (String), `snapshot_source` (String), `t_norm` (Numeric), `z_score` (Numeric), `sma_fast`, `sma_slow`, `positions_json` (Text), `baseline_value`, `baseline_return`, `mode` (String, e.g. `'online_live'`), `strategy_id` (String, e.g. `'v3_5b'`), `created_at`.
- `snapshot_source` values: `'scheduler'` (**authoritative for regime**), `'refresh'` (P&L only, regime NULL), `'backfill'` (categorical regime valid, z_score/t_norm NULL), `'manual'`. Authority filter confirmed at `jutsu_engine/api/routes/performance.py:331-337,475-478`: regime is written ONLY by scheduler.
- **Equity comparison uses `total_equity`** (real EOD equity written by the scheduler/reconstruction — NOT `market_data` closes). Uniqueness: `(mode, strategy_id, timestamp)`.

**Backtest (Module 4) — `jutsu_engine/application/backtest_runner.py`:**
- `BacktestRunner(config: Dict)` (`:66-102`). `config` keys: `symbols` (list), `timeframe`, `start_date` (datetime), `end_date` (datetime), `initial_capital` (Decimal), optional `commission_per_share`, `slippage_percent`.
- `runner.run(strategy: Strategy, output_dir="output") -> Dict[str, Any]` (`:284-331`). Result keys include `sharpe_ratio`, `max_drawdown`, `annualized_return`, `total_return`, `final_value`, `baseline` (dict with `alpha`, `beta_vs_QQQ`), and file paths: `regime_timeseries_csv`, `regime_summary_csv`, `portfolio_csv_path`.
- Regime timeseries CSV (`jutsu_engine/performance/regime_analyzer.py:192-222`) columns: `Date, Regime` (`Cell_N`), `Trend`, `Vol`, `QQQ_Close`, `QQQ_Daily_Return`, `Portfolio_Value`, `Strategy_Daily_Return`. Written only if strategy has `get_current_regime` — the Hierarchical strategies DO (`Hierarchical_Adaptive_v3_5b.py:1565`).
- Portfolio CSV (`jutsu_engine/performance/portfolio_exporter.py:297-338`) columns include `Date`, `Regime`/`Trend`/`Vol`, `Portfolio_Total_Value`, `Cash`, `BuyHold_QQQ_Value`, and per-ticker `TMF_Qty`/`TMF_Value`, `TMV_Qty`/`TMV_Value` (used to isolate Treasury-overlay P&L in cells 4–6).

**Building a Hierarchical strategy instance from a config YAML — `jutsu_engine/live/strategy_runner.py`:**
- `LiveStrategyRunner(strategy_class, config_path)` loads YAML (`config['strategy']['parameters']`), pops `EXCLUDED_PARAMS = {'name','trade_logger'}` (`:25`), converts float params to `Decimal`, validates `REQUIRED_PARAMS = {'signal_symbol','leveraged_long_symbol','sma_fast','sma_slow'}` (`:28-31`), then `strategy_class(**params)` and `strategy.init()`. The built instance is `runner.strategy`. Module 4 reuses this: build the runner, take `runner.strategy`, hand it to `BacktestRunner.run`.

**Metrics — `jutsu_engine/performance/analyzer.py`:** REUSE `PerformanceAnalyzer(fills, equity_curve, initial_capital).calculate_metrics()` → dict with `sharpe_ratio`, `max_drawdown`, `annualized_return`, etc. For era slices where we only have a returns Series (no fills), use `calculate_advanced_metrics(returns, benchmark_returns=None)` (`:776`) which accepts a `pd.Series` of returns. Do NOT reimplement Sharpe/MaxDD.

**CLI — `jutsu_engine/cli/main.py`:** top-level `@click.group()` `cli` (`:150-158`); external commands registered at end of file, e.g. `from jutsu_engine.cli.commands.monte_carlo import monte_carlo as monte_carlo_cmd; cli.add_command(monte_carlo_cmd, name='monte-carlo')` (`:2051-2053`). Entry point: `pyproject.toml:47` `jutsu = "jutsu_engine.cli.main:cli"`. Command modules live in `jutsu_engine/cli/commands/` and use `@click.command`/`@click.option`, `click.echo(click.style(...))`, `raise click.Abort()` on error (`wfo.py`, `monte_carlo.py`).

**Trading-day iteration — `jutsu_engine/live/market_calendar.py:31`** `is_trading_day(date) -> bool` (uses `pandas_market_calendars`).

**Tests — `tests/unit/<subpkg>/test_*.py`:** class `Test<Feature>`, methods `test_<scenario>`, `pytest` fixtures, synthetic data (no DB). `tests/conftest.py` has DB fixtures but our unit tests MUST NOT use them.

**Package layout to build now (spec §10), leaving room for Modules 1/2/3 later:**
```
jutsu_engine/audit/
    __init__.py
    config.py         # strategy registry + config/output path helpers (shared scaffolding)
    db.py             # read-only DB helpers (engine, snapshot & bar readers) — graceful degrade
    live_recon.py     # Module 5
    attribution.py    # Module 4
    report.py         # markdown report assembly for M4 + M5
jutsu_engine/cli/commands/audit.py   # `jutsu audit live-recon | attribution | all`
tests/unit/audit/    # pure-function tests on synthetic data
```

---

## Task 0: Environment setup and proof it works

**Files:** none created; this proves the toolchain.

- [ ] **Step 1: Rebuild the venv with uv (Python 3.11) and install the package + missing deps**

Run:
```bash
cd /Users/ankugo/dev/Jutsu-Labs
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[dev]" pandas-market-calendars fastapi
```
Expected: uv creates `.venv`, resolves and installs jutsu_engine (editable) plus `pandas-market-calendars` and `fastapi` (both are imported by the code but NOT declared in `pyproject.toml` — that is why they are installed explicitly here).

- [ ] **Step 2: Prove imports of the components this plan reuses**

Run:
```bash
.venv/bin/python -c "import jutsu_engine.application.backtest_runner as b; import jutsu_engine.performance.analyzer as a; import jutsu_engine.live.strategy_runner as s; import jutsu_engine.live.market_calendar as m; import pandas_market_calendars, fastapi; print('imports OK')"
```
Expected: `imports OK` (no ImportError). If `pandas_market_calendars` or `fastapi` fail, re-run Step 1.

- [ ] **Step 3: Prove the focused-test invocation works (coverage gate + warnings-as-error bypass)**

The repo's `pyproject.toml` sets `addopts = ["--cov-fail-under=80", ...]` and `filterwarnings = ["error", ...]`. Focused runs MUST override addopts. Prove the incantation on an existing test:
```bash
.venv/bin/python -m pytest tests/unit/performance/test_regime_analyzer.py -p no:cacheprovider -o addopts="" -q
```
Expected: tests pass (or at least collect and run) WITHOUT a coverage-threshold failure. This exact invocation (`-p no:cacheprovider -o addopts="" -q`) is used for every focused test run in this plan.

- [ ] **Step 4: Confirm branch and .env presence**

Run:
```bash
cd /Users/ankugo/dev/Jutsu-Labs && git branch --show-current && ls -la .env 2>/dev/null | head -1 || echo "NO .env — DB modules will degrade gracefully"
```
Expected: `feature/baseline-audit`, and `.env` present (DB-backed modules will run) OR a clear "NO .env" note (DB modules will error cleanly; unit tests still pass because they never touch the DB).

*(No commit — Task 0 changes no tracked files.)*

---

## Task 1: Audit package scaffolding — `__init__.py` + `config.py`

**Files:**
- Create: `jutsu_engine/audit/__init__.py`
- Create: `jutsu_engine/audit/config.py`
- Create: `tests/unit/audit/__init__.py`
- Create: `tests/unit/audit/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/audit/__init__.py` (empty file) and `tests/unit/audit/test_config.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_config.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jutsu_engine.audit'`.

- [ ] **Step 3: Write the implementation**

Create `jutsu_engine/audit/__init__.py`:
```python
"""Read-only analysis layer for the baseline audit / Gauntlet v1.

This package adds ONLY analysis on top of existing infrastructure
(BacktestRunner, PerformanceAnalyzer, LiveStrategyRunner). It never
mutates the database and never touches live/scheduler code paths.
Outputs are files under claudedocs/audit/<YYYY-MM-DD>/.
"""
```

Create `jutsu_engine/audit/config.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_config.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/__init__.py jutsu_engine/audit/config.py tests/unit/audit/__init__.py tests/unit/audit/test_config.py
git commit -m "feat(audit): add audit package scaffolding and strategy registry"
```

---

## Task 2: Read-only DB helpers — `audit/db.py`

**Files:**
- Create: `jutsu_engine/audit/db.py`
- Create: `tests/unit/audit/test_db.py`

This module is the ONLY place that talks to PostgreSQL. All queries are `SELECT`. It degrades gracefully: if env vars are missing it raises a clear `AuditDBUnavailable`, never a cryptic KeyError. Unit tests exercise the pure row-shaping functions with fake rows — no live DB.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/audit/test_db.py`:
```python
from datetime import date, datetime, timezone

import pandas as pd

from jutsu_engine.audit.db import (
    AuditDBUnavailable,
    build_engine_url,
    rows_to_bars_df,
    scheduler_snapshots_to_records,
)


class TestBuildEngineUrl:
    def test_missing_env_raises_audit_db_unavailable(self):
        try:
            build_engine_url(env={})  # empty env -> no POSTGRES_* keys
            assert False, "expected AuditDBUnavailable"
        except AuditDBUnavailable as e:
            assert "POSTGRES" in str(e)

    def test_builds_url_and_quotes_password(self):
        env = {
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p@ss word",
            "POSTGRES_HOST": "h",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DATABASE": "db",
        }
        url = build_engine_url(env=env)
        # '@' and ' ' in password must be percent-encoded (%40, %20 / +).
        assert url.startswith("postgresql://u:")
        assert "@h:5432/db" in url
        assert "p@ss word" not in url  # raw password must not appear


class TestRowsToBarsDf:
    def test_reverses_to_chronological_and_types(self):
        # Rows arrive newest-first (DESC); loader must reverse to chronological.
        rows = [
            (datetime(2025, 12, 3, tzinfo=timezone.utc), 3.0, 3.0, 3.0, 3.0, 30),
            (datetime(2025, 12, 2, tzinfo=timezone.utc), 2.0, 2.0, 2.0, 2.0, 20),
            (datetime(2025, 12, 1, tzinfo=timezone.utc), 1.0, 1.0, 1.0, 1.0, 10),
        ]
        df = rows_to_bars_df(rows)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert df["close"].tolist() == [1.0, 2.0, 3.0]  # chronological
        assert str(df["close"].dtype) == "float64"
        assert str(df["volume"].dtype) == "int64"

    def test_empty_rows_return_empty_df_with_columns(self):
        df = rows_to_bars_df([])
        assert df.empty
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]


class TestSchedulerSnapshotsToRecords:
    def test_maps_columns_and_keeps_one_per_day(self):
        # Two rows for the same day; keep the LATEST timestamp (authoritative EOD).
        rows = [
            # (strategy_id, ts, dt, cell, trend, vol, t_norm, z_score, total_equity, snapshot_source)
            ("v3_5b", datetime(2025, 12, 1, 20, 5, tzinfo=timezone.utc), date(2025, 12, 1),
             1, "BullStrong", "Low", 0.4, -0.3, 10100.0, "scheduler"),
            ("v3_5b", datetime(2025, 12, 1, 16, 0, tzinfo=timezone.utc), date(2025, 12, 1),
             1, "BullStrong", "Low", 0.4, -0.3, 10050.0, "scheduler"),
        ]
        recs = scheduler_snapshots_to_records(rows)
        assert len(recs) == 1
        r = recs[0]
        assert r["day"] == date(2025, 12, 1)
        assert r["strategy_cell"] == 1
        assert r["trend_state"] == "BullStrong"
        assert r["vol_state"] == "Low"
        assert r["t_norm"] == 0.4
        assert r["z_score"] == -0.3
        assert r["total_equity"] == 10100.0  # latest ts wins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_db.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jutsu_engine.audit.db'`.

- [ ] **Step 3: Write the implementation**

Create `jutsu_engine/audit/db.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_db.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/db.py tests/unit/audit/test_db.py
git commit -m "feat(audit): add read-only DB helpers with graceful degradation"
```

---

## Task 3: Live-recon diff engine (pure functions) — `audit/live_recon.py` part 1

**Files:**
- Create: `jutsu_engine/audit/live_recon.py`
- Create: `tests/unit/audit/test_live_recon.py`

This task builds the categorization logic as pure functions (no DB, no replay), so the diff rules are fully unit-tested. Task 4 adds the DB-backed replay driver that feeds these functions.

**Categorization rules (spec §9 + gotchas):**
- Categorical fields (`strategy_cell`, `trend_state`, `vol_state`) must match EXACTLY. A mismatch is category `logic` (same EOD inputs, different output → candidate bug) — unless the day's snapshot has no categorical value, which is a `data` gap.
- Continuous fields (`z_score`, `t_norm`) were computed intraday by the scheduler, so an exact match is NOT expected. Diff them with a tolerance; label out-of-tolerance diffs as `timing`. If the stored value is NULL (e.g. `backfill` rows), skip (not a mismatch) and mark `missing`.
- Equity divergence uses `total_equity` (real EOD equity), never `market_data` closes.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/audit/test_live_recon.py`:
```python
from datetime import date

from jutsu_engine.audit.live_recon import (
    ZSCORE_TOLERANCE,
    TNORM_TOLERANCE,
    categorize_day,
    summarize_diffs,
)


def _stored(**kw):
    base = dict(day=date(2026, 1, 5), strategy_cell=1, trend_state="BullStrong",
                vol_state="Low", t_norm=0.40, z_score=-0.30, total_equity=10000.0,
                snapshot_source="scheduler")
    base.update(kw)
    return base


def _replay(**kw):
    base = dict(strategy_cell=1, trend_state="BullStrong", vol_state="Low",
                t_norm=0.41, z_score=-0.28)
    base.update(kw)
    return base


class TestCategorizeDay:
    def test_all_match_within_tolerance_is_clean(self):
        d = categorize_day(_stored(), _replay())
        assert d["categorical_match"] is True
        assert d["mismatches"] == []  # z/t within tolerance
        assert d["category"] == "match"

    def test_categorical_cell_mismatch_is_logic(self):
        d = categorize_day(_stored(), _replay(strategy_cell=4))
        assert d["categorical_match"] is False
        assert any(m["field"] == "strategy_cell" and m["category"] == "logic"
                   for m in d["mismatches"])
        assert d["category"] == "logic"

    def test_zscore_out_of_tolerance_is_timing(self):
        d = categorize_day(_stored(z_score=-0.30), _replay(z_score=-0.60))
        # categorical still matches; z diff 0.30 > tolerance -> timing
        assert d["categorical_match"] is True
        assert any(m["field"] == "z_score" and m["category"] == "timing"
                   for m in d["mismatches"])
        assert d["category"] == "timing"

    def test_null_stored_zscore_is_missing_not_mismatch(self):
        d = categorize_day(_stored(z_score=None, snapshot_source="backfill"),
                           _replay(z_score=-0.90))
        assert not any(m["field"] == "z_score" for m in d["mismatches"])
        # categorical still compared; here they match -> overall match
        assert d["category"] == "match"

    def test_tolerances_are_positive(self):
        assert ZSCORE_TOLERANCE > 0
        assert TNORM_TOLERANCE > 0


class TestSummarizeDiffs:
    def test_counts_by_field_and_category(self):
        days = [
            categorize_day(_stored(), _replay()),                         # match
            categorize_day(_stored(), _replay(strategy_cell=4)),          # logic
            categorize_day(_stored(z_score=-0.30), _replay(z_score=-0.9)),# timing
        ]
        s = summarize_diffs(days)
        assert s["total_days"] == 3
        assert s["match_days"] == 1
        assert s["by_category"]["logic"] == 1
        assert s["by_category"]["timing"] == 1
        assert s["by_field"]["strategy_cell"] == 1
        assert s["by_field"]["z_score"] == 1
        # mismatch_pct = non-match days / total
        assert abs(s["mismatch_pct"] - (2 / 3 * 100)) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_live_recon.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jutsu_engine.audit.live_recon'`.

- [ ] **Step 3: Write the implementation (pure-function portion)**

Create `jutsu_engine/audit/live_recon.py`:
```python
"""Module 5 — Live reconciliation (spec §9).

Replays each live strategy through LiveStrategyRunner.calculate_signals over
EOD market_data bars (mirroring scripts/backfill_regime.py) and diffs the result
day-by-day against scheduler-authoritative performance_snapshots.

Diff categorization (spec §9 + data gotchas):
  - Categorical fields (strategy_cell / trend_state / vol_state) MUST match
    exactly; a mismatch is 'logic' (same EOD inputs, different output -> bug).
  - Continuous fields (z_score / t_norm) were computed intraday by the scheduler,
    so exact EOD-replay match is NOT expected. Out-of-tolerance diffs are 'timing'.
    NULL stored values (e.g. 'backfill' rows) are 'missing', not mismatches.
  - Equity divergence uses total_equity (real EOD equity), never market_data close.

The categorize/summarize functions are pure and DB-free (this file's tested core).
The replay driver (run_live_recon) is DB-backed and degrades gracefully.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

# Tolerances for intraday-vs-EOD continuous fields. Categorical fields have NO
# tolerance (exact match required).
ZSCORE_TOLERANCE = 0.25
TNORM_TOLERANCE = 0.10

_CATEGORICAL = ("strategy_cell", "trend_state", "vol_state")
_CONTINUOUS = (("z_score", ZSCORE_TOLERANCE), ("t_norm", TNORM_TOLERANCE))


def categorize_day(stored: dict, replay: dict) -> dict:
    """Compare one day's stored snapshot vs replayed signals; categorize diffs.

    Args:
        stored: a record from db.load_scheduler_snapshots (has categorical +
            continuous fields, may contain None for continuous).
        replay: {'strategy_cell','trend_state','vol_state','z_score','t_norm'}
            from the strategy replay.

    Returns a dict:
        {day, categorical_match, mismatches: [{field, stored, replay, category}],
         category}  where category is one of 'match','logic','timing'
         (logic dominates timing when both present).
    """
    mismatches: list[dict] = []

    categorical_match = True
    for f in _CATEGORICAL:
        sv = stored.get(f)
        rv = replay.get(f)
        if sv is None:
            # No stored categorical value on this day -> data gap, not a logic bug.
            mismatches.append({"field": f, "stored": None, "replay": rv,
                               "category": "data"})
            categorical_match = False
            continue
        if sv != rv:
            mismatches.append({"field": f, "stored": sv, "replay": rv,
                               "category": "logic"})
            categorical_match = False

    for f, tol in _CONTINUOUS:
        sv = stored.get(f)
        rv = replay.get(f)
        if sv is None or rv is None:
            continue  # 'missing' — scheduler value not stored (e.g. backfill row)
        if abs(float(sv) - float(rv)) > tol:
            mismatches.append({"field": f, "stored": float(sv), "replay": float(rv),
                               "category": "timing"})

    if any(m["category"] in ("logic", "data") for m in mismatches):
        category = "logic" if any(m["category"] == "logic" for m in mismatches) else "data"
    elif any(m["category"] == "timing" for m in mismatches):
        category = "timing"
    else:
        category = "match"

    return {
        "day": stored.get("day"),
        "categorical_match": categorical_match,
        "mismatches": mismatches,
        "category": category,
    }


def summarize_diffs(days: list[dict]) -> dict:
    """Aggregate per-day categorizations into report-level counts."""
    total = len(days)
    match_days = sum(1 for d in days if d["category"] == "match")
    by_category: dict[str, int] = {}
    by_field: dict[str, int] = {}
    for d in days:
        if d["category"] != "match":
            by_category[d["category"]] = by_category.get(d["category"], 0) + 1
        for m in d["mismatches"]:
            by_field[m["field"]] = by_field.get(m["field"], 0) + 1
    return {
        "total_days": total,
        "match_days": match_days,
        "mismatch_days": total - match_days,
        "mismatch_pct": ((total - match_days) / total * 100.0) if total else 0.0,
        "by_category": by_category,
        "by_field": by_field,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_live_recon.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/live_recon.py tests/unit/audit/test_live_recon.py
git commit -m "feat(audit): add live-recon diff categorization (pure functions)"
```

---

## Task 4: Live-recon replay driver (DB-backed) — `audit/live_recon.py` part 2

**Files:**
- Modify: `jutsu_engine/audit/live_recon.py` (append replay driver + result container)
- Modify: `tests/unit/audit/test_live_recon.py` (add tests using a fake replay fn + fake snapshots — still no DB)

The replay reuses `scripts/backfill_regime.py`'s pattern (fresh `LiveStrategyRunner` per day, 250-bar warmup). We inject the "replay one day" and "load snapshots" callables so the orchestration is unit-testable without a database.

- [ ] **Step 1: Write the failing test (append to existing file)**

Append to `tests/unit/audit/test_live_recon.py`:
```python
from jutsu_engine.audit.live_recon import LiveReconResult, reconcile


class TestReconcileOrchestration:
    def test_reconcile_pairs_days_and_summarizes(self):
        # Two stored scheduler days for one strategy.
        snapshots = [
            dict(day=date(2026, 1, 5), strategy_cell=1, trend_state="BullStrong",
                 vol_state="Low", t_norm=0.40, z_score=-0.30, total_equity=10000.0,
                 snapshot_source="scheduler"),
            dict(day=date(2026, 1, 6), strategy_cell=4, trend_state="Sideways",
                 vol_state="High", t_norm=0.10, z_score=1.20, total_equity=9950.0,
                 snapshot_source="scheduler"),
        ]

        # Fake replay: day 1 matches; day 2 replays a different cell (logic mismatch)
        # and a different equity (for divergence).
        def fake_replay_day(strategy_id, day):
            if day == date(2026, 1, 5):
                return dict(strategy_cell=1, trend_state="BullStrong", vol_state="Low",
                            t_norm=0.41, z_score=-0.28, replay_equity=10000.0)
            return dict(strategy_cell=5, trend_state="BearStrong", vol_state="High",
                        t_norm=0.10, z_score=1.19, replay_equity=9900.0)

        result = reconcile(
            strategy_id="v3_5b",
            snapshots=snapshots,
            replay_day=fake_replay_day,
            source_counts={"scheduler": 2, "refresh": 3},
        )
        assert isinstance(result, LiveReconResult)
        assert result.strategy_id == "v3_5b"
        assert result.summary["total_days"] == 2
        assert result.summary["by_category"]["logic"] == 1
        assert result.summary["mismatch_days"] == 1
        assert result.source_counts == {"scheduler": 2, "refresh": 3}
        # Equity divergence: replay 9900 vs stored 9950 on day 2 -> abs diff tracked.
        assert result.pnl_divergence["final_stored_equity"] == 9950.0
        assert result.pnl_divergence["final_replay_equity"] == 9900.0
        assert result.day_table[1]["category"] == "logic"

    def test_reconcile_empty_snapshots_is_graceful(self):
        result = reconcile("v3_5b", snapshots=[], replay_day=lambda s, d: {},
                           source_counts={})
        assert result.summary["total_days"] == 0
        assert result.pnl_divergence["final_stored_equity"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_live_recon.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ImportError: cannot import name 'LiveReconResult'` (and `reconcile`).

- [ ] **Step 3: Write the implementation (append to live_recon.py)**

Append to `jutsu_engine/audit/live_recon.py`:
```python
from dataclasses import dataclass, field


@dataclass
class LiveReconResult:
    """Everything the report needs for one strategy's reconciliation."""
    strategy_id: str
    summary: dict
    day_table: list[dict]
    source_counts: dict
    pnl_divergence: dict


def reconcile(
    strategy_id: str,
    snapshots: list[dict],
    replay_day,
    source_counts: dict,
) -> LiveReconResult:
    """Diff stored scheduler snapshots against a per-day replay.

    Args:
        strategy_id: e.g. "v3_5b".
        snapshots: records from db.load_scheduler_snapshots (one per trading day),
            each with categorical + continuous fields + total_equity.
        replay_day: callable(strategy_id, day) -> dict with keys
            strategy_cell/trend_state/vol_state/t_norm/z_score and optional
            replay_equity. Injected so this is unit-testable without a DB.
        source_counts: {snapshot_source: distinct_day_count} for the provenance table.

    Returns a LiveReconResult. Equity divergence compares the last day's stored
    total_equity against the last day's replay_equity (both real-EOD-based).
    """
    day_rows: list[dict] = []
    stored_equity_series: list[tuple[date, float]] = []
    replay_equity_series: list[tuple[date, float]] = []

    for snap in snapshots:
        day = snap["day"]
        rep = replay_day(strategy_id, day) or {}
        diff = categorize_day(snap, rep)
        diff["stored_equity"] = snap.get("total_equity")
        diff["replay_equity"] = rep.get("replay_equity")
        day_rows.append(diff)
        if snap.get("total_equity") is not None:
            stored_equity_series.append((day, float(snap["total_equity"])))
        if rep.get("replay_equity") is not None:
            replay_equity_series.append((day, float(rep["replay_equity"])))

    summary = summarize_diffs(day_rows)

    pnl_divergence = {
        "final_stored_equity": stored_equity_series[-1][1] if stored_equity_series else None,
        "final_replay_equity": replay_equity_series[-1][1] if replay_equity_series else None,
    }
    if pnl_divergence["final_stored_equity"] is not None and \
       pnl_divergence["final_replay_equity"] is not None:
        pnl_divergence["abs_divergence"] = abs(
            pnl_divergence["final_replay_equity"] - pnl_divergence["final_stored_equity"]
        )
    else:
        pnl_divergence["abs_divergence"] = None

    return LiveReconResult(
        strategy_id=strategy_id,
        summary=summary,
        day_table=day_rows,
        source_counts=source_counts,
        pnl_divergence=pnl_divergence,
    )


def make_replay_day(engine, strategy_id: str, lookback: int = 250):
    """Build a replay_day(strategy_id, day) callable backed by the live engine.

    Mirrors scripts/backfill_regime.py:102-122 exactly: a FRESH LiveStrategyRunner
    per day (clean 250-bar warmup, matching the scheduler cold-start), signal +
    treasury symbols loaded from market_data, calculate_signals invoked.

    The returned callable does not compute replay equity (positions-level equity
    replay is out of scope for Phase 1); pnl_divergence therefore reports the
    stored live equity endpoints and leaves replay equity None unless a caller
    supplies it. This is intentional and documented in the report.
    """
    import importlib
    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.audit.db import load_bars

    spec = resolve_strategy(strategy_id)

    def _replay(_sid: str, day) -> Optional[dict]:
        from jutsu_engine.live.strategy_runner import LiveStrategyRunner
        mod = importlib.import_module(spec.module_path)
        strategy_class = getattr(mod, spec.class_name)
        runner = LiveStrategyRunner(strategy_class=strategy_class,
                                    config_path=spec.config_path)
        md = {}
        for sym in (runner.get_signal_symbol(), runner.get_treasury_symbol()):
            bars = load_bars(engine, sym, day, lookback)
            if bars.empty:
                return None
            md[sym] = bars
        signals = runner.calculate_signals(md)
        return {
            "strategy_cell": signals.get("current_cell"),
            "trend_state": signals.get("trend_state"),
            "vol_state": signals.get("vol_state"),
            "t_norm": signals.get("t_norm"),
            "z_score": signals.get("z_score"),
        }

    return _replay


def run_live_recon(strategy_id: str, start=None) -> LiveReconResult:
    """DB-backed entry point used by the CLI. Reads scheduler snapshots, replays,
    returns a LiveReconResult. Raises AuditDBUnavailable if the DB is not reachable.
    """
    from jutsu_engine.audit.config import LIVE_RECON_START
    from jutsu_engine.audit.db import (
        get_engine, load_scheduler_snapshots, load_snapshot_source_counts,
    )
    start = start or LIVE_RECON_START
    engine = get_engine()
    snapshots = load_scheduler_snapshots(engine, strategy_id, start)
    source_counts = load_snapshot_source_counts(engine, strategy_id, start)
    replay_day = make_replay_day(engine, strategy_id)
    return reconcile(strategy_id, snapshots, replay_day, source_counts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_live_recon.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (8 tests total in the file).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/live_recon.py tests/unit/audit/test_live_recon.py
git commit -m "feat(audit): add DB-backed live-recon replay driver"
```

---

## Task 5: Attribution — era slicing + cell bucketing (pure functions) — `audit/attribution.py` part 1

**Files:**
- Create: `jutsu_engine/audit/attribution.py`
- Create: `tests/unit/audit/test_attribution.py`

Module 4 reads the regime-timeseries CSV that `BacktestRunner` already emits (columns `Date, Regime, Trend, Vol, QQQ_Daily_Return, Strategy_Daily_Return`) and the portfolio CSV (per-ticker `TMF_Value`/`TMV_Value`). This task builds the pure analysis over those DataFrames; Task 6 adds the backtest driver.

**Eras (spec §8):** 2010–2014, 2015–2019, 2020 (COVID), 2021, 2022 bear, 2023–2024 bull, 2025–present.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/audit/test_attribution.py`:
```python
from datetime import date

import pandas as pd

from jutsu_engine.audit.attribution import (
    ERAS,
    assign_era,
    era_metrics,
    cell_attribution,
    treasury_overlay_contribution,
)


class TestEras:
    def test_eras_cover_expected_labels(self):
        labels = [e.label for e in ERAS]
        assert "2020 (COVID)" in labels
        assert "2022 bear" in labels
        assert "2025-present" in labels

    def test_assign_era_boundaries(self):
        assert assign_era(date(2012, 6, 1)) == "2010-2014"
        assert assign_era(date(2020, 3, 15)) == "2020 (COVID)"
        assert assign_era(date(2022, 10, 1)) == "2022 bear"
        assert assign_era(date(2026, 7, 6)) == "2025-present"


def _ts_df():
    # 4 days: 2 in cell 1, 2 in cell 4; simple returns.
    return pd.DataFrame({
        "Date": pd.to_datetime(
            ["2021-01-04", "2021-01-05", "2022-06-01", "2022-06-02"], utc=True),
        "Regime": ["Cell_1", "Cell_1", "Cell_4", "Cell_4"],
        "QQQ_Daily_Return": [0.01, -0.02, 0.00, 0.01],
        "Strategy_Daily_Return": [0.02, -0.01, 0.005, -0.03],
    })


class TestEraMetrics:
    def test_returns_one_row_per_populated_era_with_metrics(self):
        df = era_metrics(_ts_df())
        # 2021 and 2022 bear are the two populated eras.
        eras = set(df["era"])
        assert "2021" in eras and "2022 bear" in eras
        row = df[df["era"] == "2021"].iloc[0]
        # total strategy return for 2021 = (1.02)*(0.99)-1
        assert abs(row["strategy_total_return"] - ((1.02 * 0.99) - 1)) < 1e-9
        assert "sharpe" in df.columns and "max_drawdown" in df.columns


class TestCellAttribution:
    def test_buckets_pnl_by_cell(self):
        df = cell_attribution(_ts_df())
        cell1 = df[df["cell"] == 1].iloc[0]
        assert cell1["days"] == 2
        # cell 1 strategy total = (1.02)*(0.99)-1
        assert abs(cell1["strategy_total_return"] - ((1.02 * 0.99) - 1)) < 1e-9
        cell4 = df[df["cell"] == 4].iloc[0]
        assert cell4["days"] == 2


class TestTreasuryOverlayContribution:
    def test_cash_counterfactual_isolates_treasury(self):
        # Portfolio CSV: on cells 4-6 days, TMF held; measure treasury pnl vs
        # a cash counterfactual (0% return on that sleeve).
        port = pd.DataFrame({
            "Date": pd.to_datetime(["2022-06-01", "2022-06-02"], utc=True),
            "Regime": ["Cell_4", "Cell_4"],
            "Portfolio_Total_Value": [10000.0, 10200.0],
            "TMF_Value": [4000.0, 4300.0],  # +300 on the treasury sleeve
            "TMV_Value": [0.0, 0.0],
        })
        res = treasury_overlay_contribution(port)
        # Treasury sleeve grew from 4000 to 4300 => +300 absolute contribution.
        assert abs(res["treasury_pnl_abs"] - 300.0) < 1e-6
        assert res["treasury_days"] == 2
        # Cash counterfactual for the same sleeve = 0 growth => contribution vs cash = +300.
        assert abs(res["contribution_vs_cash"] - 300.0) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_attribution.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jutsu_engine.audit.attribution'`.

- [ ] **Step 3: Write the implementation (pure-function portion)**

Create `jutsu_engine/audit/attribution.py`:
```python
"""Module 4 — Era and cell attribution (spec §8).

Consumes artifacts that BacktestRunner already emits:
  - regime timeseries CSV (regime_analyzer.py:192-222): columns
    Date, Regime ('Cell_N'), Trend, Vol, QQQ_Daily_Return, Strategy_Daily_Return.
  - portfolio CSV (portfolio_exporter.py): Date, Regime, Portfolio_Total_Value,
    per-ticker TMF_Value / TMV_Value (Treasury overlay lives in cells 4-6 only).

Pure analysis functions here (era/cell/treasury) are unit-tested on synthetic
DataFrames. Task 6 adds the backtest driver that produces the real CSVs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Era:
    label: str
    start: date
    end: date  # inclusive


# Era slices from spec §8. 2025-present end-bounded far in the future.
ERAS: list[Era] = [
    Era("2010-2014", date(2010, 1, 1), date(2014, 12, 31)),
    Era("2015-2019", date(2015, 1, 1), date(2019, 12, 31)),
    Era("2020 (COVID)", date(2020, 1, 1), date(2020, 12, 31)),
    Era("2021", date(2021, 1, 1), date(2021, 12, 31)),
    Era("2022 bear", date(2022, 1, 1), date(2022, 12, 31)),
    Era("2023-2024 bull", date(2023, 1, 1), date(2024, 12, 31)),
    Era("2025-present", date(2025, 1, 1), date(2100, 12, 31)),
]


def assign_era(d: date) -> str:
    """Return the era label for a date, or 'unknown' if before the first era."""
    for era in ERAS:
        if era.start <= d <= era.end:
            return era.label
    return "unknown"


def _cell_from_regime(regime: str) -> int:
    """'Cell_4' -> 4."""
    return int(str(regime).split("_")[1])


def _sharpe(returns: pd.Series, periods: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods))


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    equity = (1.0 + r).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min()) if len(dd) else 0.0


def _total_return(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def era_metrics(ts: pd.DataFrame) -> pd.DataFrame:
    """Per-era metrics from a regime timeseries DataFrame.

    Expects columns: Date, QQQ_Daily_Return, Strategy_Daily_Return.
    Returns one row per populated era: era, days, strategy_total_return,
    qqq_total_return, alpha_total, sharpe, max_drawdown.
    """
    df = ts.copy()
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df["era"] = df["Date"].dt.date.map(assign_era)

    rows = []
    for era_label, g in df.groupby("era", sort=False):
        strat_tot = _total_return(g["Strategy_Daily_Return"])
        qqq_tot = _total_return(g["QQQ_Daily_Return"])
        rows.append({
            "era": era_label,
            "days": int(len(g)),
            "strategy_total_return": strat_tot,
            "qqq_total_return": qqq_tot,
            "alpha_total": strat_tot - qqq_tot,
            "sharpe": _sharpe(g["Strategy_Daily_Return"]),
            "max_drawdown": _max_drawdown(g["Strategy_Daily_Return"]),
        })
    out = pd.DataFrame(rows)
    # Order by era definition for stable reports.
    order = {e.label: i for i, e in enumerate(ERAS)}
    out["_o"] = out["era"].map(lambda x: order.get(x, 999))
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def cell_attribution(ts: pd.DataFrame) -> pd.DataFrame:
    """Per-cell P&L attribution (cells 1-6) from a regime timeseries DataFrame.

    Expects columns: Regime ('Cell_N'), QQQ_Daily_Return, Strategy_Daily_Return.
    Returns one row per observed cell: cell, days, strategy_total_return,
    qqq_total_return, hit_rate (fraction of days with strategy return > 0),
    strategy_daily_avg.
    """
    df = ts.copy()
    df["cell"] = df["Regime"].map(_cell_from_regime)
    rows = []
    for cell, g in df.groupby("cell"):
        sr = g["Strategy_Daily_Return"].fillna(0.0)
        rows.append({
            "cell": int(cell),
            "days": int(len(g)),
            "strategy_total_return": _total_return(sr),
            "qqq_total_return": _total_return(g["QQQ_Daily_Return"]),
            "hit_rate": float((sr > 0).mean()) if len(sr) else 0.0,
            "strategy_daily_avg": float(sr.mean()) if len(sr) else 0.0,
        })
    return pd.DataFrame(rows).sort_values("cell").reset_index(drop=True)


def treasury_overlay_contribution(portfolio: pd.DataFrame) -> dict:
    """Isolate the Treasury-overlay (TMF/TMV) P&L in cells 4-6 vs a cash counterfactual.

    Expects portfolio CSV columns: Regime, TMF_Value, TMV_Value.
    Treasury overlay is active only in cells 4-6 (Hierarchical_Adaptive_v3_5b.py:876).

    Contribution = absolute change in the (TMF_Value + TMV_Value) sleeve across the
    cell-4-6 days. Cash counterfactual assumes that sleeve earned 0 over the same
    days, so contribution_vs_cash == treasury_pnl_abs here (a positive number means
    the overlay beat holding cash; negative means it cost money net of whipsaw).
    """
    df = portfolio.copy()
    df["cell"] = df["Regime"].map(_cell_from_regime)
    mask = df["cell"].isin([4, 5, 6])
    treas = df.loc[mask].copy()
    if treas.empty:
        return {"treasury_days": 0, "treasury_pnl_abs": 0.0, "contribution_vs_cash": 0.0}

    sleeve = treas.get("TMF_Value", 0.0).fillna(0.0) + treas.get("TMV_Value", 0.0).fillna(0.0)
    pnl_abs = float(sleeve.iloc[-1] - sleeve.iloc[0])
    return {
        "treasury_days": int(len(treas)),
        "treasury_pnl_abs": pnl_abs,
        # Cash counterfactual: same sleeve earning 0 -> contribution vs cash = pnl_abs.
        "contribution_vs_cash": pnl_abs,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_attribution.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/attribution.py tests/unit/audit/test_attribution.py
git commit -m "feat(audit): add era/cell/treasury attribution (pure functions)"
```

---

## Task 6: Attribution backtest driver — `audit/attribution.py` part 2

**Files:**
- Modify: `jutsu_engine/audit/attribution.py` (append strategy builder + backtest driver)
- Modify: `tests/unit/audit/test_attribution.py` (add tests for the config→kwargs mapping using the real YAML, no DB)

The driver builds a full-period backtest per strategy. It reuses `LiveStrategyRunner`'s config→strategy mapping (so the audit runs the EXACT live config) by constructing a `LiveStrategyRunner` and taking `runner.strategy`, then hands that instance to `BacktestRunner`. Reading the two live YAMLs is DB-free, so the mapping is unit-tested.

- [ ] **Step 1: Write the failing test (append to existing file)**

Append to `tests/unit/audit/test_attribution.py`:
```python
from jutsu_engine.audit.attribution import build_strategy_instance


class TestBuildStrategyInstance:
    def test_builds_v3_5b_from_live_config(self):
        # Uses the real config/strategies/v3_5b.yaml (no DB). Confirms the audit
        # replays the exact live config via LiveStrategyRunner's mapping.
        strategy = build_strategy_instance("v3_5b")
        assert strategy.__class__.__name__ == "Hierarchical_Adaptive_v3_5b"
        # Golden param spot-checks (from v3_5b.yaml).
        assert int(strategy.sma_fast) == 40
        assert int(strategy.sma_slow) == 140
        assert strategy.signal_symbol == "QQQ"
        assert strategy.leveraged_long_symbol == "TQQQ"
        assert bool(strategy.allow_treasury) is True

    def test_builds_v3_5d_and_has_regime_hook(self):
        strategy = build_strategy_instance("v3_5d")
        assert strategy.__class__.__name__ == "Hierarchical_Adaptive_v3_5d"
        # get_current_regime is required for BacktestRunner to emit regime CSVs.
        assert hasattr(strategy, "get_current_regime")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_attribution.py::TestBuildStrategyInstance -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ImportError: cannot import name 'build_strategy_instance'`.

- [ ] **Step 3: Write the implementation (append to attribution.py)**

Append to `jutsu_engine/audit/attribution.py`:
```python
import importlib
from dataclasses import dataclass as _dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def build_strategy_instance(strategy_id: str):
    """Instantiate a live strategy from its exact live YAML config.

    Reuses LiveStrategyRunner's config->strategy mapping (strategy_runner.py:
    _initialize_strategy), which reads config['strategy']['parameters'], drops
    EXCLUDED_PARAMS, converts floats to Decimal, and calls strategy_class(**params)
    then strategy.init(). Returning runner.strategy guarantees the audit backtest
    uses the identical parameters the live deployment uses.
    """
    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner

    spec = resolve_strategy(strategy_id)
    mod = importlib.import_module(spec.module_path)
    strategy_class = getattr(mod, spec.class_name)
    runner = LiveStrategyRunner(strategy_class=strategy_class, config_path=spec.config_path)
    return runner.strategy


def _all_symbols(strategy_id: str) -> list[str]:
    """All trading symbols the strategy touches (signal, leveraged, hedge, bonds)."""
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner
    from jutsu_engine.audit.config import resolve_strategy
    spec = resolve_strategy(strategy_id)
    mod = importlib.import_module(spec.module_path)
    strategy_class = getattr(mod, spec.class_name)
    runner = LiveStrategyRunner(strategy_class=strategy_class, config_path=spec.config_path)
    return runner.get_all_symbols()


@_dataclass
class AttributionResult:
    """Everything the report needs for one strategy's era/cell attribution."""
    strategy_id: str
    metrics: dict            # headline backtest metrics (sharpe, max_drawdown, ...)
    era_table: "pd.DataFrame"
    cell_table: "pd.DataFrame"
    treasury: dict
    regime_timeseries_csv: str
    portfolio_csv: str


def run_attribution(strategy_id: str, start=None, end=None,
                    initial_capital: Decimal = Decimal("10000"),
                    output_dir: str = "output") -> AttributionResult:
    """Run one full-period backtest and produce era + cell + treasury attribution.

    Reuses BacktestRunner (backtest_runner.py:66-102,284-331). The Hierarchical
    strategy exposes get_current_regime, so BacktestRunner emits the regime
    timeseries CSV and portfolio CSV that the pure functions consume.

    Raises AuditDBUnavailable-compatible errors from BacktestRunner if the DB is
    unreachable (BacktestRunner reads market_data). The CLI catches and reports.
    """
    from datetime import date as _date
    from jutsu_engine.audit.config import ATTRIBUTION_START
    from jutsu_engine.application.backtest_runner import BacktestRunner

    start = start or ATTRIBUTION_START
    end = end or _date.today()

    config = {
        "symbols": _all_symbols(strategy_id),
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": initial_capital,
    }
    strategy = build_strategy_instance(strategy_id)

    runner = BacktestRunner(config)
    results = runner.run(strategy, output_dir=output_dir)

    ts_csv = results.get("regime_timeseries_csv")
    port_csv = results.get("portfolio_csv_path")
    if not ts_csv or not Path(ts_csv).exists():
        raise RuntimeError(
            "Backtest did not emit a regime timeseries CSV; cannot attribute by cell. "
            "Confirm the strategy exposes get_current_regime."
        )

    ts = pd.read_csv(ts_csv)
    era_table = era_metrics(ts)
    cell_table = cell_attribution(ts)

    treasury = {"treasury_days": 0, "treasury_pnl_abs": 0.0, "contribution_vs_cash": 0.0}
    if port_csv and Path(port_csv).exists():
        port = pd.read_csv(port_csv)
        if "Regime" in port.columns:
            treasury = treasury_overlay_contribution(port)

    metrics = {
        "sharpe_ratio": results.get("sharpe_ratio"),
        "max_drawdown": results.get("max_drawdown"),
        "annualized_return": results.get("annualized_return"),
        "total_return": results.get("total_return"),
        "final_value": results.get("final_value"),
        "alpha_vs_qqq": (results.get("baseline") or {}).get("alpha"),
    }

    return AttributionResult(
        strategy_id=strategy_id,
        metrics=metrics,
        era_table=era_table,
        cell_table=cell_table,
        treasury=treasury,
        regime_timeseries_csv=str(ts_csv),
        portfolio_csv=str(port_csv) if port_csv else "",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_attribution.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (8 tests total in the file).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/attribution.py tests/unit/audit/test_attribution.py
git commit -m "feat(audit): add attribution backtest driver (full-period, live config)"
```

---

## Task 7: Markdown report generation — `audit/report.py`

**Files:**
- Create: `jutsu_engine/audit/report.py`
- Create: `tests/unit/audit/test_report.py`

Reports are pure string builders over the result objects (so fully unit-testable), plus a thin writer that creates `claudedocs/audit/<YYYY-MM-DD>/report_<strategy>.md`. Every report embeds the git SHA, data range, config path, and the decision thresholds from spec §10.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/audit/test_report.py`:
```python
from pathlib import Path

import pandas as pd

from jutsu_engine.audit.attribution import AttributionResult
from jutsu_engine.audit.live_recon import LiveReconResult
from jutsu_engine.audit.report import (
    render_live_recon_section,
    render_attribution_section,
    render_report,
    write_report,
)


def _recon():
    return LiveReconResult(
        strategy_id="v3_5b",
        summary={"total_days": 100, "match_days": 98, "mismatch_days": 2,
                 "mismatch_pct": 2.0, "by_category": {"logic": 1, "timing": 1},
                 "by_field": {"strategy_cell": 1, "z_score": 1}},
        day_table=[{"day": "2026-01-05", "category": "logic",
                    "mismatches": [{"field": "strategy_cell", "stored": 1,
                                    "replay": 4, "category": "logic"}]}],
        source_counts={"scheduler": 98, "refresh": 20, "backfill": 5},
        pnl_divergence={"final_stored_equity": 10871.42,
                        "final_replay_equity": None, "abs_divergence": None},
    )


def _attr():
    era = pd.DataFrame([{"era": "2021", "days": 250, "strategy_total_return": 0.5,
                         "qqq_total_return": 0.27, "alpha_total": 0.23,
                         "sharpe": 1.8, "max_drawdown": -0.1}])
    cell = pd.DataFrame([{"cell": 1, "days": 400, "strategy_total_return": 2.0,
                          "qqq_total_return": 1.0, "hit_rate": 0.6,
                          "strategy_daily_avg": 0.001}])
    return AttributionResult(
        strategy_id="v3_5b",
        metrics={"sharpe_ratio": 2.1, "max_drawdown": -0.18,
                 "annualized_return": 0.25, "total_return": 5.0,
                 "final_value": 60000.0, "alpha_vs_qqq": 0.4},
        era_table=era, cell_table=cell,
        treasury={"treasury_days": 120, "treasury_pnl_abs": -50.0,
                  "contribution_vs_cash": -50.0},
        regime_timeseries_csv="/tmp/ts.csv", portfolio_csv="/tmp/p.csv",
    )


class TestRenderSections:
    def test_live_recon_section_flags_over_5pct(self):
        recon = _recon()
        recon.summary["mismatch_pct"] = 7.0
        md = render_live_recon_section(recon)
        assert "Live reconciliation" in md
        assert "7.0" in md
        assert "P0" in md  # threshold consequence per spec §10 (>5% -> fidelity P0)
        assert "scheduler" in md  # snapshot_source provenance table

    def test_live_recon_section_ok_when_under_threshold(self):
        md = render_live_recon_section(_recon())  # 2.0%
        assert "2.0" in md
        assert "within tolerance" in md.lower() or "below" in md.lower()

    def test_attribution_section_has_era_and_cell_and_treasury(self):
        md = render_attribution_section(_attr())
        assert "Era" in md and "2021" in md
        assert "Cell" in md and "Cell 1" in md
        assert "Treasury" in md and "-50" in md  # negative treasury contribution shown


class TestRenderReport:
    def test_full_report_has_header_and_sha(self):
        md = render_report(strategy_id="v3_5b", git_sha="abc1234",
                          recon=_recon(), attribution=_attr(),
                          data_range="2010-02-01 -> 2026-07-06",
                          config_path="config/strategies/v3_5b.yaml")
        assert "# Baseline Audit — v3_5b" in md
        assert "abc1234" in md
        assert "config/strategies/v3_5b.yaml" in md
        assert "Decision thresholds" in md


class TestWriteReport:
    def test_write_creates_file(self, tmp_path):
        out = write_report(tmp_path, "v3_5b", "# hello\n")
        assert out.name == "report_v3_5b.md"
        assert Path(out).read_text() == "# hello\n"
        assert out.parent == tmp_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jutsu_engine.audit.report'`.

- [ ] **Step 3: Write the implementation**

Create `jutsu_engine/audit/report.py`:
```python
"""Markdown report assembly for Phase-1 audit modules (M4 + M5).

Section renderers are pure string builders over the result objects (unit-tested).
write_report writes report_<strategy>.md into a run directory. Every report embeds
the git SHA, data range, config path, and the spec §10 decision thresholds so any
number is reproducible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

# spec §10 decision thresholds (printed in every report).
FIDELITY_MISMATCH_THRESHOLD_PCT = 5.0


def _df_to_md(df: pd.DataFrame) -> str:
    """Render a DataFrame as a GitHub-flavored markdown table (no external deps)."""
    if df is None or df.empty:
        return "_(no rows)_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            cells.append(f"{v:.4f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_live_recon_section(recon) -> str:
    s = recon.summary
    pct = s["mismatch_pct"]
    over = pct > FIDELITY_MISMATCH_THRESHOLD_PCT
    verdict = (
        f"**{pct:.1f}%** mismatch days > {FIDELITY_MISMATCH_THRESHOLD_PCT:.0f}% threshold "
        f"→ live-fidelity fixes are **P0** before any strategy changes (spec §10)."
        if over else
        f"**{pct:.1f}%** mismatch days, below the {FIDELITY_MISMATCH_THRESHOLD_PCT:.0f}% "
        f"threshold — categorical fidelity is within tolerance."
    )

    lines = [
        "## Live reconciliation (Module 5)",
        "",
        f"- Days compared (scheduler-authoritative): **{s['total_days']}**",
        f"- Match days: **{s['match_days']}**  |  Mismatch days: **{s['mismatch_days']}**",
        f"- {verdict}",
        "",
        "### Mismatches by category",
    ]
    if s["by_category"]:
        for cat, n in sorted(s["by_category"].items()):
            lines.append(f"- {cat}: {n}")
    else:
        lines.append("- (none)")
    lines += ["", "### Mismatches by field"]
    if s["by_field"]:
        for f, n in sorted(s["by_field"].items()):
            lines.append(f"- {f}: {n}")
    else:
        lines.append("- (none)")

    lines += ["", "### Snapshot provenance (snapshot_source counts)",
              "Only `scheduler` rows carry valid regime; `backfill` rows have "
              "NULL z_score/t_norm; `refresh` rows carry no regime.", ""]
    for src, n in sorted(recon.source_counts.items()):
        lines.append(f"- `{src}`: {n} day(s)")

    d = recon.pnl_divergence
    lines += ["", "### P&L divergence (real EOD equity)",
              f"- Final live equity (total_equity): "
              f"{d.get('final_stored_equity')}",
              f"- Final replayed equity: {d.get('final_replay_equity')} "
              f"(positions-level equity replay is out of Phase-1 scope)",
              ""]

    # z-score discrepancy note (spec §9 acceptance): report continuous-field timing diffs.
    z_timing = s["by_field"].get("z_score", 0)
    lines += [
        "### 2026-02-04 z-score discrepancy",
        f"z_score timing-category diffs observed on **{z_timing}** day(s). "
        "z_score/t_norm are intraday-computed live vs EOD-replayed here, so exact "
        "match is not expected; these are categorized `timing`, not `logic`. See the "
        "day-level table for the specific dates.",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_attribution_section(attr) -> str:
    m = attr.metrics
    t = attr.treasury
    treasury_verdict = (
        "the Treasury overlay **added** value net of whipsaw"
        if t["contribution_vs_cash"] > 0 else
        "the Treasury overlay **cost** money net of whipsaw (cells 4-6)"
    )
    lines = [
        "## Era and cell attribution (Module 4)",
        "",
        "### Headline (full-period backtest, live config)",
        f"- Sharpe: **{m.get('sharpe_ratio')}**  |  MaxDD: **{m.get('max_drawdown')}**",
        f"- Annualized return: **{m.get('annualized_return')}**  |  "
        f"Total return: **{m.get('total_return')}**",
        f"- Alpha vs QQQ: **{m.get('alpha_vs_qqq')}**",
        "",
        "### Era table",
        _df_to_md(attr.era_table),
        "### Cell attribution",
        _df_to_md(attr.cell_table.assign(cell=attr.cell_table["cell"].map(lambda c: f"Cell {c}"))
                  if not attr.cell_table.empty else attr.cell_table),
        "### Treasury overlay contribution (cells 4-6 vs cash counterfactual)",
        f"- Treasury days: **{t['treasury_days']}**",
        f"- Treasury sleeve P&L (abs): **{t['treasury_pnl_abs']}**",
        f"- Contribution vs cash: **{t['contribution_vs_cash']}** — {treasury_verdict}.",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_report(strategy_id: str, git_sha: str, recon, attribution,
                  data_range: str, config_path: str) -> str:
    """Assemble the full markdown report for one strategy (M4 + M5)."""
    header = [
        f"# Baseline Audit — {strategy_id} (Phase 1: Live Recon + Attribution)",
        "",
        f"- Git SHA: `{git_sha}`",
        f"- Data range: {data_range}",
        f"- Live config: `{config_path}`",
        "",
        "### Decision thresholds (spec §10)",
        "| Signal | Threshold | Consequence |",
        "| --- | --- | --- |",
        "| Live regime mismatch days | >5% | Fidelity fixes become P0 before strategy changes |",
        "| Treasury overlay contribution | <0 | Defensive machinery does not pay for its whipsaw |",
        "",
        "---",
        "",
    ]
    body = ""
    if recon is not None:
        body += render_live_recon_section(recon) + "\n---\n\n"
    if attribution is not None:
        body += render_attribution_section(attribution) + "\n"
    return "\n".join(header) + body


def write_report(run_dir: Path, strategy_id: str, markdown: str) -> Path:
    """Write report_<strategy>.md into run_dir (created if missing). Returns the path."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_{strategy_id}.md"
    out.write_text(markdown)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/report.py tests/unit/audit/test_report.py
git commit -m "feat(audit): add markdown report generation for M4 + M5"
```

---

## Task 8: CLI command group — `jutsu audit ...`

**Files:**
- Create: `jutsu_engine/cli/commands/audit.py`
- Modify: `jutsu_engine/cli/main.py` (register the group near the other `cli.add_command(...)` calls)
- Create: `tests/unit/cli/test_audit_command.py`

The command group has `live-recon`, `attribution`, and `all` subcommands, each taking `--strategy` (default runs both). It orchestrates the module drivers, renders reports via `report.py`, and degrades gracefully when the DB is unavailable (`AuditDBUnavailable` → clear message, non-zero exit). Follows the click pattern from `wfo.py`/`monte_carlo.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/cli/test_audit_command.py`:
```python
from unittest.mock import patch

from click.testing import CliRunner

from jutsu_engine.cli.commands.audit import audit


class TestAuditCliWiring:
    def test_group_lists_subcommands(self):
        runner = CliRunner()
        result = runner.invoke(audit, ["--help"])
        assert result.exit_code == 0
        assert "live-recon" in result.output
        assert "attribution" in result.output
        assert "all" in result.output

    def test_live_recon_reports_db_unavailable_gracefully(self):
        runner = CliRunner()
        from jutsu_engine.audit.db import AuditDBUnavailable
        with patch("jutsu_engine.cli.commands.audit.run_live_recon",
                   side_effect=AuditDBUnavailable("no env")):
            result = runner.invoke(audit, ["live-recon", "--strategy", "v3_5b"])
        # Non-zero exit, but a clear message (not a traceback).
        assert result.exit_code != 0
        assert "database" in result.output.lower() or "no env" in result.output.lower()

    def test_live_recon_writes_report_on_success(self, tmp_path):
        runner = CliRunner()
        from jutsu_engine.audit.live_recon import LiveReconResult
        fake = LiveReconResult(
            strategy_id="v3_5b",
            summary={"total_days": 1, "match_days": 1, "mismatch_days": 0,
                     "mismatch_pct": 0.0, "by_category": {}, "by_field": {}},
            day_table=[], source_counts={"scheduler": 1},
            pnl_divergence={"final_stored_equity": 100.0,
                            "final_replay_equity": None, "abs_divergence": None},
        )
        with patch("jutsu_engine.cli.commands.audit.run_live_recon", return_value=fake), \
             patch("jutsu_engine.cli.commands.audit._git_sha", return_value="deadbee"), \
             patch("jutsu_engine.cli.commands.audit.report_output_dir",
                   return_value=tmp_path):
            result = runner.invoke(audit, ["live-recon", "--strategy", "v3_5b"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "report_v3_5b.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_audit_command.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jutsu_engine.cli.commands.audit'`.

- [ ] **Step 3: Write the implementation**

Create `jutsu_engine/cli/commands/audit.py`:
```python
"""`jutsu audit` command group (Phase 1: live-recon + attribution).

Follows the click pattern of jutsu_engine/cli/commands/wfo.py and monte_carlo.py.
Scaffolded so Modules 1/2/3 can add subcommands later without restructuring.
Read-only: never mutates the DB; outputs markdown to claudedocs/audit/<date>/.
"""
from __future__ import annotations

import subprocess
from datetime import date

import click

from jutsu_engine.audit.config import report_output_dir
from jutsu_engine.audit.db import AuditDBUnavailable
from jutsu_engine.audit.live_recon import run_live_recon
from jutsu_engine.audit.attribution import run_attribution
from jutsu_engine.audit.report import render_report, write_report


def _git_sha() -> str:
    """Short git SHA for report provenance ('unknown' if unavailable)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


@click.group()
def audit():
    """Baseline audit / Gauntlet v1 (read-only analysis on top of the engine)."""


def _run_and_report(strategy_id: str, do_recon: bool, do_attr: bool) -> None:
    """Run the requested modules for one strategy and write its report."""
    recon = None
    attribution = None

    if do_recon:
        click.echo(f"[{strategy_id}] live reconciliation...")
        recon = run_live_recon(strategy_id)
        click.echo(click.style(
            f"  mismatch days: {recon.summary['mismatch_days']} "
            f"({recon.summary['mismatch_pct']:.1f}%)", fg="cyan"))

    if do_attr:
        click.echo(f"[{strategy_id}] era/cell attribution (full-period backtest)...")
        attribution = run_attribution(strategy_id)
        click.echo(click.style(
            f"  sharpe={attribution.metrics.get('sharpe_ratio')} "
            f"maxdd={attribution.metrics.get('max_drawdown')}", fg="cyan"))

    from jutsu_engine.audit.config import resolve_strategy
    spec = resolve_strategy(strategy_id)
    md = render_report(
        strategy_id=strategy_id,
        git_sha=_git_sha(),
        recon=recon,
        attribution=attribution,
        data_range=f"live-recon since 2025-12-01 / attribution since 2010-02-01 "
                   f"through {date.today().isoformat()}",
        config_path=spec.config_rel_path,
    )
    run_dir = report_output_dir()
    out = write_report(run_dir, strategy_id, md)
    click.echo(click.style(f"  report: {out}", fg="green"))


def _strategy_ids(strategy: str | None) -> list[str]:
    return [strategy] if strategy else ["v3_5b", "v3_5d"]


def _dispatch(strategy: str | None, do_recon: bool, do_attr: bool) -> None:
    try:
        for sid in _strategy_ids(strategy):
            _run_and_report(sid, do_recon, do_attr)
    except AuditDBUnavailable as e:
        click.echo(click.style(
            f"✗ Database unavailable: {e}", fg="red"))
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.", fg="yellow"))
        raise click.Abort()
    except Exception as e:  # noqa: BLE001 - surface a clean message, not a traceback
        click.echo(click.style(f"✗ Audit failed: {e}", fg="red"))
        raise click.Abort()


_STRATEGY_OPTION = click.option(
    "--strategy", type=click.Choice(["v3_5b", "v3_5d"]), default=None,
    help="Strategy id (omit to run both).")


@audit.command("live-recon")
@_STRATEGY_OPTION
def live_recon_cmd(strategy):
    """Module 5: reconcile live scheduler snapshots vs backtest replay."""
    _dispatch(strategy, do_recon=True, do_attr=False)


@audit.command("attribution")
@_STRATEGY_OPTION
def attribution_cmd(strategy):
    """Module 4: era and regime-cell P&L attribution (full-period backtest)."""
    _dispatch(strategy, do_recon=False, do_attr=True)


@audit.command("all")
@_STRATEGY_OPTION
def all_cmd(strategy):
    """Run all Phase-1 modules (live-recon + attribution) and write reports."""
    _dispatch(strategy, do_recon=True, do_attr=True)
```

- [ ] **Step 4: Register the group in `main.py`**

In `jutsu_engine/cli/main.py`, find the existing external-command registration block (near line 2051, where monte-carlo is registered):
```python
# Import and register Monte Carlo command
from jutsu_engine.cli.commands.monte_carlo import monte_carlo as monte_carlo_cmd
cli.add_command(monte_carlo_cmd, name='monte-carlo')
```
Add immediately after it:
```python
# Import and register audit command group (baseline audit / Gauntlet v1)
from jutsu_engine.cli.commands.audit import audit as audit_cmd
cli.add_command(audit_cmd, name='audit')
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
.venv/bin/python -m pytest tests/unit/cli/test_audit_command.py -p no:cacheprovider -o addopts="" -q
```
Expected: PASS (3 tests).

Then verify the command is wired into the real CLI:
```bash
.venv/bin/python -c "from jutsu_engine.cli.main import cli; print('audit' in cli.commands)"
```
Expected: `True`.

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/cli/commands/audit.py jutsu_engine/cli/main.py tests/unit/cli/test_audit_command.py
git commit -m "feat(audit): add jutsu audit CLI group (live-recon, attribution, all)"
```

---

## Task 9: Full audit-suite regression + CLI smoke check

**Files:** none created; this is validation.

- [ ] **Step 1: Run the whole audit unit suite together**

Run:
```bash
.venv/bin/python -m pytest tests/unit/audit/ tests/unit/cli/test_audit_command.py -p no:cacheprovider -o addopts="" -q
```
Expected: all tests PASS (Task 1: 5, Task 2: 6, Task 3+4: 8, Task 5+6: 8, Task 7: 6, Task 8: 3 = 36 tests), no warnings-as-error failures.

- [ ] **Step 2: Confirm the CLI help renders end-to-end**

Run:
```bash
.venv/bin/python -m jutsu_engine.cli.main audit --help
```
Expected: help text listing `live-recon`, `attribution`, `all`. (This exercises the real registration in `main.py`, not the isolated group.)

- [ ] **Step 3: DB-dependent smoke check (only if `.env` + DB reachable; otherwise confirm graceful failure)**

If the database is reachable from this machine, run a real reconciliation:
```bash
.venv/bin/python -m jutsu_engine.cli.main audit live-recon --strategy v3_5b
```
Expected: prints mismatch counts and writes `claudedocs/audit/<today>/report_v3_5b.md`. Inspect it:
```bash
ls claudedocs/audit/ && head -40 claudedocs/audit/$(date +%F)/report_v3_5b.md
```

If the DB is NOT reachable, confirm the graceful path instead:
```bash
.venv/bin/python -m jutsu_engine.cli.main audit live-recon --strategy v3_5b; echo "exit=$?"
```
Expected: a red "Database unavailable" message and non-zero exit — NOT a Python traceback. This proves the read-only/degrade constraint. (No commit — validation only.)

---

## Task 10: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md` (prepend a new entry at the very top)

- [ ] **Step 1: Read the current top of the changelog to match the format**

Run: `head -5 CHANGELOG.md`
Expected: the newest entry begins with `#### **Type: Title** (YYYY-MM-DD)`.

- [ ] **Step 2: Prepend the new entry**

Insert this block at the very top of `CHANGELOG.md`, above the current first line:
```markdown
#### **Feature: Baseline audit Phase 1 — live reconciliation + era/cell attribution** (2026-07-06)

Added the read-only `jutsu_engine/audit/` analysis package and `jutsu audit` CLI
group implementing Phase 1 of the baseline audit (spec:
`docs/superpowers/specs/2026-07-06-baseline-audit-design.md`). No live/scheduler
or strategy-config changes; the audit is strictly READ-ONLY against the database
and writes markdown reports to `claudedocs/audit/<YYYY-MM-DD>/`.

- **Module 5 — Live reconciliation** (`audit/live_recon.py`): replays each live
  strategy (v3_5b, v3_5d) through `LiveStrategyRunner.calculate_signals` over EOD
  `market_data` bars (250-bar warmup, fresh runner per day — mirrors
  `scripts/backfill_regime.py`) and diffs day-by-day against
  scheduler-authoritative `performance_snapshots`. Categorical fields
  (strategy_cell/trend_state/vol_state) require exact match (`logic` category);
  z_score/t_norm are compared with tolerance (`timing` category, since the
  scheduler computed them intraday); equity uses real EOD `total_equity`, never
  the 1-day-shifted `market_data` closes. Reports snapshot_source provenance counts.
- **Module 4 — Era and cell attribution** (`audit/attribution.py`): one
  full-period (2010-02 → present) backtest per strategy via `BacktestRunner` using
  the exact live config (built through `LiveStrategyRunner`'s param mapping);
  per-era metrics and per-cell P&L, including Treasury-overlay (TMF/TMV, cells 4-6)
  contribution vs a cash counterfactual.
- **Reuse**: `BacktestRunner`, `PerformanceAnalyzer`, `LiveStrategyRunner`,
  `RegimePerformanceAnalyzer` (regime timeseries + portfolio CSVs). New code is
  analysis-only.
- **CLI**: `jutsu audit live-recon|attribution|all --strategy v3_5b|v3_5d`
  (omit `--strategy` to run both). Degrades gracefully with a clear message when
  the database is unavailable.
- **Tests**: 36 DB-free unit tests in `tests/unit/audit/` + `tests/unit/cli/`
  (pure functions on synthetic series; config→strategy mapping tested against the
  real live YAMLs).
- Modified/added: `jutsu_engine/audit/{__init__,config,db,live_recon,attribution,report}.py`,
  `jutsu_engine/cli/commands/audit.py`, `jutsu_engine/cli/main.py`,
  `tests/unit/audit/*`, `tests/unit/cli/test_audit_command.py`.

Modules 1 (WFO stability), 2 (plateau map), 3 (DSR/PBO) are deferred to later plans
(spec build order); the package/CLI scaffolding accommodates them.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for baseline audit Phase 1 (M4 + M5)"
```

---

## Self-Review (run by plan author)

**1. Spec coverage (scoped to Phase 1):**
- Package scaffolding + `jutsu audit` CLI (spec §10) → Tasks 1, 8. ✓
- Module 5 live reconciliation (spec §9): replay via LiveStrategyRunner over EOD bars → Task 4; day-by-day compare on cell/trend/vol/t_norm/z_score/equity → Task 3 `categorize_day`; mismatch categories data/timing/logic → Task 3; P&L divergence → Task 4; snapshot_source authority + counts → Task 2 (`load_scheduler_snapshots`, `load_snapshot_source_counts`) + Task 7 provenance table; 2026-02-04 z-score note → Task 7. ✓
- Module 4 attribution (spec §8): one full-period golden backtest per strategy → Task 6; era slices → Task 5 `ERAS`/`era_metrics`; per-cell P&L → Task 5 `cell_attribution`; Treasury-overlay vs cash counterfactual → Task 5 `treasury_overlay_contribution`. ✓
- Report to `claudedocs/audit/<date>/` with SHA/config/thresholds → Task 7 + Task 8. ✓
- CHANGELOG (repo convention) → Task 10. ✓
- Read-only DB constraint → Task 2 (SELECT-only, `AuditDBUnavailable`) + Task 8 graceful degrade + Task 9 Step 3 proof. ✓
- Explicit `git add <paths>` in every commit (never `-A`/`.`) → all commit steps. ✓
- Env rebuild + missing deps + focused-test incantation → Task 0. ✓
- Data gotchas baked in with comments: 1-day shift → `db.py`/`live_recon.py`/`attribution.py` comments + equity uses `total_equity`; snapshot_source separation → `db.py` filter + report; intraday-vs-EOD tolerance → `live_recon.py`; 250-bar warmup → `db.load_bars`/`make_replay_day`. ✓
- Out of scope (Modules 1/2/3): not implemented; scaffolding noted for later. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". Every code step contains full code; every test step contains full test code. ✓

**3. Type consistency:** `StrategySpec` fields (`strategy_id`, `module_path`, `class_name`, `config_rel_path`, `config_path`) consistent across config.py/attribution.py/report CLI. `LiveReconResult` / `AttributionResult` field names consistent between their defining tasks (3/4, 6) and consumers (report Task 7, CLI Task 8). `categorize_day`/`summarize_diffs`/`reconcile`/`run_live_recon` signatures consistent between live_recon.py and its tests + CLI. `era_metrics`/`cell_attribution`/`treasury_overlay_contribution`/`run_attribution`/`build_strategy_instance` consistent between attribution.py and tests + CLI + report. Report functions `render_live_recon_section`/`render_attribution_section`/`render_report`/`write_report` consistent between report.py, its tests, and the CLI. ✓
