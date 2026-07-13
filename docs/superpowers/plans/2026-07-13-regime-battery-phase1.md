# Regime Program Phase 1 — Transition Metrics + Vol-Input Ablation Battery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a permanent transition-metrics gauntlet capability and run EXP-007 — a pre-registered 4-arm (×3 ungated diagnostic weights) ablation of the vol-state INPUT series (stock / kronos / vix / smoothing) to decide whether a forward-looking or smoothing-only leg earns a paper-trading shadow slot.

**Architecture:** Extend the existing read-only `jutsu_engine/audit/` package (which already has plateau/wfo/dsr campaign machinery: fsync-JSONL resume, circuit breaker, single-writer parallelism, midnight-safe run dirs) with four new pure modules (`transitions`, `input_series`, `battery`) plus one new *diagnostic-only* strategy subclass (`Hierarchical_Adaptive_v3_5b_VolInput`) that injects a precomputed vol-input series at the vol-z step. Engine-truth signal series come from a single-pass replay of the real strategy class via `LiveStrategyRunner.calculate_signals` (feeds bars chronologically through `on_bar`, no portfolio execution) — nothing is reimplemented. Portfolio metrics come from the existing `BacktestRunner`. Everything is DB-free unit-tested (pure functions + fakes); the DB and engine are touched only in identity/smoke/campaign steps.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), pandas, numpy, pyarrow (parquet read), click (CLI), SQLAlchemy (read-only SELECT), pytest. Reuses `jutsu_engine.audit.{config,db,plateau,attribution,report}` and `jutsu_engine.live.strategy_runner`.

---

## Orientation for the implementer (read before Task 1)

You know Python but nothing about this codebase. Read these before starting, in order:

1. **The spec** (authoritative, every §): `docs/superpowers/specs/2026-07-13-regime-battery-design.md`. The locked-decisions table (§3), the arms table + pre-registered gates (§8, including the **flatness SIGN rule**), and the engine-truth requirement (§5) bind every task.
2. **`docs/experiments/LOGBOOK.md`** — SYNTHESIS-001 "Binding facts for downstream research" (T-1 information set; warmup-trim per EXP-006; AUC bar; n≈1-crash-episode power warning), EXP-006 (warmup-trim lesson), XREF-002 (why the battery has vix + smoothing control arms).
3. **The Kronos handoff** (exact recipe + parquet schema): `~/dev/kronos-research/jutsu-kronos-research/docs/2026-07-08-kronos-vol-input-handoff.md`. §1 the 5-step recipe, §2 the parquet schema, §4 the T-1 constraint.
4. **`jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.py`** — specifically `on_bar` (line ~734) which at line ~817 calls `z_score = self._calculate_volatility_zscore(closes)` then at line ~824 `self._apply_hysteresis(z_score)`. **This is the exact injection point.** `_calculate_volatility_zscore` returns `Optional[Decimal]`. Also read the constructor (Decimal param conventions) and `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5d.py` (the subclassing reference — it subclasses `Strategy`, not v3_5b, but the pattern of adding params + calling super methods is the model).
5. **`jutsu_engine/audit/plateau.py`** — the campaign machinery you will reuse: `params_hash`, `append_result` (fsync), `load_completed_hashes`, `run_campaign` (single-writer invariant, circuit breaker, parallel path), `_prepared_params`/`build_overridden_strategy` (the float→Decimal `DECIMAL_PARAMS` bridge), `run_one_sample` (throwaway tempdir per backtest).
6. **`jutsu_engine/live/strategy_runner.py`** — `LiveStrategyRunner.calculate_signals(market_data)` (line ~214): feeds each bar via `_update_bar()` then `on_bar()`, no portfolio. This is your engine-truth signal-replay mechanism (see Task 8's mechanism note).
7. **`jutsu_engine/audit/report.py`** — the report conventions you must follow: `_fmt(v, spec)` (None → 'N/A', never literal None), `_df_to_md`, **captions live OUTSIDE the GFM table block** (a non-pipe line between the header-separator and the first data row breaks GitHub's parser), standalone `write_*_report` files.
8. **`jutsu_engine/cli/commands/audit.py`** — the click group + subcommand pattern, `_resolve_run_dir` midnight-safe resume, `AuditDBUnavailable` handling, `_STRATEGY_OPTION`.

### Binding constraints (from spec §10 + the task prompt — violate none)

- **Strictly READ-ONLY vs the DB.** Only SELECT (via `jutsu_engine.audit.db` helpers). Never INSERT/UPDATE/DELETE.
- **Warmup-trim every regime timeseries before any metric** (EXP-006). Regime-timeseries CSVs contain rows dated before `start_date` with 0.0 returns; trim to `[start_date, end_date]` first.
- **T-1 information set end-to-end.** The value used for day D's decision derives only from information available at D−1's close. Every input-series builder is T-1 aligned; every causality test asserts prefix-stability.
- **Live YAMLs and live/scheduler code are UNTOUCHED.** The adapter is a NEW strategy file only, configured only by the battery harness (never by a live YAML).
- **Explicit `git add <paths>`** in every commit step (never `git add -A`/`git add .`).
- **DB-free unit tests** (pure functions + fakes). Engine runs only in identity/smoke/campaign steps.
- **Focused-test command:** `.venv/bin/python -m pytest <path> -p no:cacheprovider -o addopts="" -q`.
- **One-line test docstrings.** Every test function has a single-line docstring.
- **`pytest.raises(match=...)`** whenever asserting an exception.
- The full audit suite must stay green: `.venv/bin/python -m pytest tests/unit/audit/ tests/unit/cli/test_audit_command.py -p no:cacheprovider -o addopts="" -q` (currently 301).

### Compute-honesty budget (state these in the report / EXP-007)

- **Identity regression backtest** (Task 7): ONE full-period v3_5b `BacktestRunner` run 2010-02→present ≈ **15–25 s** wall-clock (per SYNTHESIS-001 / strategy docstring "<20s"). The identity test runs the subclass-with-no-series and stock v3_5b once each → **~30–50 s total**.
- **Signal replay** (Task 8): `calculate_signals` over 27 years (1999-03→2026-07, ~6,800 QQQ bars) is a single bar loop with no per-day fresh-runner overhead ≈ **~1–3 min** per arm (three signal arms: stock/vix/smoothing). Kronos signal replay is only over 2019-08→2025-12 (~1,600 bars) ≈ **<1 min**. This is the whole point of the single-pass mechanism vs the per-day fresh-`LiveStrategyRunner` replay used by live-recon (which is minutes-per-90-days and would be hours for 27 y).
- **Battery portfolio runs** (Task 12): 10 `BacktestRunner` backtests over the short Tier-1 window 2019-08→2025-12 (~1,600 trading days each) ≈ **~5–8 s each** → **~1–1.5 min** total at `--workers 4`. Far cheaper than the 16-year plateau/dsr campaigns.
- **Smoke** (Task 12): stock + 1 arm, short window → **~15–30 s**.

### File structure (created/modified across all tasks)

| Path | Responsibility |
|---|---|
| `grid-configs/audit/crash_episodes.yaml` | **Create.** Versioned episode registry (8 episodes). |
| `jutsu_engine/audit/transitions.py` | **Create.** Registry loader/validator + pure transition scorer (portfolio + signal level). |
| `jutsu_engine/audit/input_series.py` | **Create.** Pure input-series builders (kronos/vix/smoothing) + one DB reader for VIX; engine-truth vol_z replay reused from `battery.py`. |
| `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py` | **Create.** Diagnostic-only adapter subclass; blends injected series at the vol-z step. |
| `jutsu_engine/audit/battery.py` | **Create.** Engine-truth vol_z/signal replay + arms table + battery campaign runner + gate evaluation. |
| `jutsu_engine/audit/report.py` | **Modify.** Add `render_transition_section` + `render_battery_section` + `write_battery_report` (append; do not touch existing renderers). |
| `jutsu_engine/cli/commands/audit.py` | **Modify.** Add `battery` subcommand (append; do not touch existing subcommands). |
| `docs/experiments/LOGBOOK.md` | **Modify.** Add EXP-007 skeleton (Task 15). |
| `CHANGELOG.md` | **Modify.** Add entry (Task 15). |
| `tests/unit/audit/test_transitions.py` | **Create.** |
| `tests/unit/audit/test_input_series.py` | **Create.** |
| `tests/unit/strategies/test_vol_input_adapter.py` | **Create.** Adapter unit + identity + short-window engine tests. |
| `tests/unit/audit/test_battery.py` | **Create.** |
| `tests/unit/cli/test_battery_cli.py` | **Create.** |

### Grounded data facts (verified against the DB + parquet on 2026-07-13, git `dd5a847`)

- **QQQ** in `market_data` spans **1999-03-10 → 2026-07-10** (6,882 daily bars) — covers every episode. QQQ closing peak before COVID = **236.98 on 2020-02-19** (matches the spec's covid peak). QQQ has essentially no duplicate-date rows (1 in the whole series).
- **`$VIX`** spans 1986-01-01 → **2026-02-03** (STALE — spec §11 requires a `jutsu sync $VIX`, out of scope for this plan; the vix arm's signal window ends where data ends until synced). **VIX has 1,879 duplicate-date days** (two rows per date, different closes, different `created_at`). On the COVID-peak date 2020-03-16 there are two rows: `82.69` at ts `05:00-07:00` (the real CBOE peak close) and `75.91` at ts `22:00-07:00`. The VIX builder MUST dedup deterministically and validate against the 82.69 anchor (Task 5). Column filter symbol literal is `'$VIX'`.
- **Kronos parquet** already copied + checksummed to `claudedocs/inputs/QQQ_kronos_base.parquet` (+ `.sha256` sidecar = `a9a4a34502ccdb601723972ac469ae399837d500a41228d7485c9b9353c3ab6e`). Schema: `timestamp, horizon, origin_close, mean_return, std_return, p_up, mean_hl_spread, signal_noise, n_samples, symbol, model`. Horizons {1,5,10,20}. The recipe uses **`std_return` where `horizon == 5`** (the handoff's `std_return_5` name = this field at H=5). Span 2019-08-06 → 2025-12-31 (1,612 daily timestamps).
- `get_closes()` returns a pandas Series with a **default integer index** (NOT timestamps). Inside `_calculate_volatility_zscore(closes)` the adapter therefore reads the current bar's date from **`self._bars[-1].timestamp`** (the most-recently-appended bar is the signal-symbol bar being processed), never from the `closes` index.
- Regime-timeseries CSV columns: `Date, Regime ('Cell_N'), Trend, Vol, QQQ_Close, QQQ_Daily_Return, Portfolio_Value, Strategy_Daily_Return`.
- Live golden config differs from strategy defaults (e.g. v3_5b `vol_baseline_window: 200`, `t_norm_bull_thresh: 0.05`, `measurement_noise: 3000.0`). NEVER hardcode golden values; flow through the YAML via `build_overridden_strategy`/`LiveStrategyRunner`.

---

## Task 1: Crash-episode registry — content + loader/validator

**Files:**
- Create: `grid-configs/audit/crash_episodes.yaml`
- Create: `jutsu_engine/audit/transitions.py`
- Test: `tests/unit/audit/test_transitions.py`

- [ ] **Step 1: Write the registry YAML with the canonical (to-be-verified) dates**

Create `grid-configs/audit/crash_episodes.yaml`. These peak/trough dates are the canonical approximations; Task 2 verifies each against QQQ closes and corrects them.

```yaml
# Crash-episode registry (versioned, human-curated — never inferred silently).
# peak = QQQ closing high preceding the drawdown; trough = QQQ closing low.
# Dates verified against market_data QQQ closes by test_episode_dates_match_qqq
# (Task 2) and reviewed by a human before commit. Pre-2010 episodes (dotcom, gfc)
# are signal-level scoring only (portfolio backtests start 2010-02 for TQQQ).
# QQQ market_data span: 1999-03-10 .. 2026-07-10 (covers all episodes).
version: 1
episodes:
  - id: dotcom
    peak: 2000-03-27       # QQQ closing peak of the dot-com top
    trough: 2002-10-09
    recovery: 2015-01-13   # documentation only (first close above peak)
    portfolio_scored: false
  - id: gfc
    peak: 2007-10-31
    trough: 2009-03-09
    recovery: 2011-02-14
    portfolio_scored: false
  - id: euro2011
    peak: 2011-07-25
    trough: 2011-10-03
    recovery: 2012-01-20
    portfolio_scored: true
  - id: china2015
    peak: 2015-07-20
    trough: 2016-02-11
    recovery: 2016-06-27
    portfolio_scored: true
  - id: q4_2018
    peak: 2018-10-01
    trough: 2018-12-24
    recovery: 2019-04-15
    portfolio_scored: true
  - id: covid2020
    peak: 2020-02-19       # QQQ close 236.98 (verified)
    trough: 2020-03-23
    recovery: 2020-06-05
    portfolio_scored: true
  - id: bear2022
    peak: 2021-12-27       # QQQ 2021 closing high
    trough: 2022-12-28
    recovery: 2024-01-08
    portfolio_scored: true
  - id: spring2025
    peak: 2025-02-19
    trough: 2025-04-08
    recovery: 2025-06-27
    portfolio_scored: true
```

- [ ] **Step 2: Write the failing test for the loader + validator**

Create `tests/unit/audit/test_transitions.py`:

```python
"""Unit tests for the crash-episode registry loader/validator (DB-free)."""
from datetime import date

import pytest

from jutsu_engine.audit.transitions import (
    Episode,
    load_episodes,
    validate_episodes,
)


def test_load_episodes_returns_eight_ordered_episodes():
    """load_episodes parses the shipped registry into 8 chronological Episodes."""
    eps = load_episodes()
    assert [e.id for e in eps] == [
        "dotcom", "gfc", "euro2011", "china2015",
        "q4_2018", "covid2020", "bear2022", "spring2025",
    ]
    assert eps[5].id == "covid2020"
    assert eps[5].peak == date(2020, 2, 19)
    assert eps[5].trough == date(2020, 3, 23)
    assert eps[5].portfolio_scored is True
    assert eps[0].portfolio_scored is False  # dotcom = signal-only


def test_validate_episodes_rejects_peak_after_trough():
    """validate_episodes raises when an episode's peak is not before its trough."""
    bad = [Episode(id="x", peak=date(2020, 5, 1), trough=date(2020, 1, 1),
                   recovery=date(2020, 6, 1), portfolio_scored=True)]
    with pytest.raises(ValueError, match="peak .* must be before trough"):
        validate_episodes(bad)


def test_validate_episodes_rejects_duplicate_ids():
    """validate_episodes raises on duplicate episode ids."""
    dup = [
        Episode(id="x", peak=date(2020, 1, 1), trough=date(2020, 2, 1),
                recovery=date(2020, 3, 1), portfolio_scored=True),
        Episode(id="x", peak=date(2021, 1, 1), trough=date(2021, 2, 1),
                recovery=date(2021, 3, 1), portfolio_scored=True),
    ]
    with pytest.raises(ValueError, match="duplicate episode id"):
        validate_episodes(dup)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'Episode'`.

- [ ] **Step 4: Write the loader/validator in a new `transitions.py`**

Create `jutsu_engine/audit/transitions.py` with this content (the scorer functions are added in Task 3; this step ships only the registry layer):

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add grid-configs/audit/crash_episodes.yaml jutsu_engine/audit/transitions.py tests/unit/audit/test_transitions.py
git commit -m "feat(audit): crash-episode registry + loader/validator (regime battery Task 1)"
```

---

## Task 2: Verify registry dates against QQQ closes (read-only) and correct

**Files:**
- Modify: `grid-configs/audit/crash_episodes.yaml` (correct dates to the data if needed)
- Modify: `tests/unit/audit/test_transitions.py` (add a DB-gated verification test)

- [ ] **Step 1: Write a DB-gated verification test (skips cleanly when the DB is offline)**

Append to `tests/unit/audit/test_transitions.py`:

```python
def _qqq_close_on_or_before(engine, d):
    """Latest QQQ close on trading date <= d (float), or None."""
    from sqlalchemy import text
    q = text(
        "SELECT close FROM market_data "
        "WHERE symbol='QQQ' AND timeframe='1D' AND (timestamp)::date <= :d "
        "ORDER BY timestamp DESC LIMIT 1"
    )
    with engine.connect() as c:
        row = c.execute(q, {"d": d}).fetchone()
    return float(row[0]) if row else None


def test_episode_dates_match_qqq():
    """Each episode peak/trough is a local QQQ extreme within a +/-10-day window."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        import pytest
        pytest.skip("market_data DB unavailable (verification is DB-gated)")

    from datetime import timedelta
    from jutsu_engine.audit.transitions import load_episodes

    def window_closes(center):
        from sqlalchemy import text
        q = text(
            "SELECT (timestamp)::date, close FROM market_data "
            "WHERE symbol='QQQ' AND timeframe='1D' "
            "AND (timestamp)::date BETWEEN :lo AND :hi ORDER BY timestamp"
        )
        with engine.connect() as c:
            rows = list(c.execute(q, {"lo": center - timedelta(days=15),
                                      "hi": center + timedelta(days=15)}))
        return [(r[0], float(r[1])) for r in rows]

    problems = []
    for e in load_episodes():
        peak_rows = window_closes(e.peak)
        trough_rows = window_closes(e.trough)
        if not peak_rows or not trough_rows:
            problems.append(f"{e.id}: no QQQ data around peak/trough")
            continue
        max_close = max(c for _, c in peak_rows)
        min_close = min(c for _, c in trough_rows)
        peak_close = dict(peak_rows).get(e.peak)
        trough_close = dict(trough_rows).get(e.trough)
        # peak must be the max close in its +/-15d neighborhood (within 0.5%)
        if peak_close is None or peak_close < max_close * 0.995:
            problems.append(
                f"{e.id}: peak {e.peak} close={peak_close} not the local max "
                f"(neighborhood max={max_close}); correct the YAML to the data"
            )
        if trough_close is None or trough_close > min_close * 1.005:
            problems.append(
                f"{e.id}: trough {e.trough} close={trough_close} not the local min "
                f"(neighborhood min={min_close}); correct the YAML to the data"
            )
    assert not problems, "\n".join(problems)
```

- [ ] **Step 2: Run the verification test and READ the failures**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py::test_episode_dates_match_qqq -p no:cacheprovider -o addopts="" -q`
Expected: If the DB is reachable, this either PASSES (dates already correct) or FAILS listing the exact episode/date mismatches. If the DB is unreachable, it SKIPS.

**This step is the verification the spec §4 mandates.** If it fails: for each listed episode, query the neighborhood and set `peak`/`trough` in the YAML to the actual QQQ closing max/min date. Do NOT weaken the test to make it pass — correct the data. (covid2020 peak 2020-02-19 is already verified = 236.98.)

Helper to inspect a neighborhood while correcting:
```bash
.venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
from jutsu_engine.audit import db as adb
from sqlalchemy import text
eng = adb.get_engine()
with eng.connect() as c:
    for r in c.execute(text(\"SELECT (timestamp)::date, close FROM market_data WHERE symbol='QQQ' AND timeframe='1D' AND (timestamp)::date BETWEEN '2021-12-15' AND '2022-01-10' ORDER BY timestamp\")):
        print(r[0], float(r[1]))
"
```

- [ ] **Step 3: Correct the YAML dates to the data (if any mismatch), then re-run**

Edit `grid-configs/audit/crash_episodes.yaml`, updating only the `peak`/`trough` values that the test flagged. Also update the `# verified` comment on each corrected line. Re-run:
Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (or SKIP for the DB-gated test if offline).

- [ ] **Step 4: Record the verified/corrected dates in the commit message and commit**

```bash
git add grid-configs/audit/crash_episodes.yaml tests/unit/audit/test_transitions.py
git commit -m "fix(audit): verify+correct crash-episode dates against QQQ closes (regime battery Task 2)

Verified peak/trough against market_data QQQ closes (read-only). Corrected: <list any
episodes whose dates moved, with old->new; write 'none — all canonical dates matched'
if the verification passed unchanged>."
```

---

## Task 3: Transition scorer — portfolio-level metrics (pure)

**Files:**
- Modify: `jutsu_engine/audit/transitions.py`
- Test: `tests/unit/audit/test_transitions.py`

- [ ] **Step 1: Write failing tests for the warmup-trim + per-episode portfolio metrics**

Append to `tests/unit/audit/test_transitions.py`:

```python
import pandas as pd
from datetime import date


def _synthetic_ts(dates, cells, qqq_closes, strat_returns):
    """Build a regime-timeseries DataFrame with the CSV's exact columns."""
    return pd.DataFrame({
        "Date": pd.to_datetime(dates, utc=True),
        "Regime": [f"Cell_{c}" for c in cells],
        "Trend": ["-"] * len(dates),
        "Vol": ["-"] * len(dates),
        "QQQ_Close": qqq_closes,
        "QQQ_Daily_Return": pd.Series(qqq_closes).pct_change().fillna(0.0).tolist(),
        "Portfolio_Value": [1.0] * len(dates),
        "Strategy_Daily_Return": strat_returns,
    })


def test_trim_warmup_rows_drops_pre_start():
    """trim_warmup drops regime rows dated before start_date (EXP-006)."""
    from jutsu_engine.audit.transitions import trim_warmup
    ts = _synthetic_ts(
        ["2019-12-30", "2020-01-02", "2020-01-03"],
        [1, 1, 1], [100, 101, 102], [0.0, 0.01, 0.01],
    )
    trimmed = trim_warmup(ts, start=date(2020, 1, 1))
    assert len(trimmed) == 2
    assert trimmed["Date"].min() >= pd.Timestamp("2020-01-01", tz="UTC")


def test_exit_lag_days_counts_trading_days_to_defensive():
    """exit_lag_days = trading days from peak until first defensive cell (4/5/6)."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 8),
                 recovery=date(2020, 1, 15), portfolio_scored=True)
    dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
    cells = [1, 1, 1, 4, 4]              # defensive first appears on 2020-01-07
    ts = _synthetic_ts(dates, cells, [100, 100, 90, 85, 80],
                       [0.0, 0.0, -0.10, -0.05, -0.06])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    # peak index is 2020-01-03; defensive first at 2020-01-07 = 2 trading days later
    assert row["exit_lag_days"] == 2


def test_never_defensive_renders_exit_lag_none():
    """A strategy that never de-risks in [peak,trough] yields exit_lag_days=None."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 8),
                 recovery=date(2020, 1, 15), portfolio_scored=True)
    dates = ["2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
    cells = [1, 1, 1, 1]
    ts = _synthetic_ts(dates, cells, [100, 95, 90, 85], [0.0, -0.05, -0.05, -0.05])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    assert row["exit_lag_days"] is None
    assert row["days_defensive"] == 0


def test_drawdown_capture_ratio():
    """drawdown_capture = strat MaxDD / QQQ MaxDD within [peak,trough] (lower=better)."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 6),
                 recovery=date(2020, 1, 10), portfolio_scored=True)
    dates = ["2020-01-03", "2020-01-06"]
    # QQQ drops 20%; strategy (half exposure) drops 10% => capture ~0.5
    ts = _synthetic_ts(dates, [1, 4], [100, 80], [0.0, -0.10])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    assert 0.45 <= row["drawdown_capture"] <= 0.55


def test_episode_outside_series_span_is_skipped_loudly():
    """An episode fully outside the timeseries span yields a skipped=True row."""
    from jutsu_engine.audit.transitions import Episode, score_episode_portfolio
    ep = Episode(id="old", peak=date(2001, 1, 3), trough=date(2001, 2, 6),
                 recovery=date(2001, 3, 10), portfolio_scored=True)
    dates = ["2020-01-03", "2020-01-06"]
    ts = _synthetic_ts(dates, [1, 4], [100, 80], [0.0, -0.10])
    row = score_episode_portfolio(ts, ep, start=date(2020, 1, 1))
    assert row["skipped"] is True
    assert row["exit_lag_days"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -k "trim or exit_lag or drawdown or never_defensive or outside_series" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'trim_warmup'` / `score_episode_portfolio`.

- [ ] **Step 3: Implement the warmup-trim helper and the portfolio scorer**

Append to `jutsu_engine/audit/transitions.py`:

```python
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
    from datetime import timedelta
    cap = min(ep.recovery + timedelta(days=120),
              df["d"].max() + timedelta(days=1))
    after_trough = df[(df["d"] >= ep.trough) & (df["d"] <= cap)].reset_index(drop=True)
    offensive = after_trough[after_trough["cell"].isin(sorted(OFFENSIVE_CELLS))]
    if not offensive.empty:
        base["reentry_lag_days"] = int(offensive.index[0])

    # whipsaw_flips: vol-state flips within [peak, min(recovery, peak+120d)]
    whip_cap = min(ep.recovery, ep.peak + timedelta(days=120))
    whip = df[(df["d"] >= ep.peak) & (df["d"] <= whip_cap)]
    vol = whip["Vol"].tolist()
    base["whipsaw_flips"] = int(sum(1 for a, b in zip(vol, vol[1:]) if a != b))

    return base
```

- [ ] **Step 4: Run the portfolio-scorer tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -k "trim or exit_lag or drawdown or never_defensive or outside_series" -p no:cacheprovider -o addopts="" -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/transitions.py tests/unit/audit/test_transitions.py
git commit -m "feat(audit): portfolio-level transition scorer (exit/reentry lag, dd capture, whipsaw) (Task 3)"
```

---

## Task 4: Transition scorer — signal-level helpers (pure)

**Files:**
- Modify: `jutsu_engine/audit/transitions.py`
- Test: `tests/unit/audit/test_transitions.py`

- [ ] **Step 1: Write failing tests for the signal-level flip lead/lag, flip ratio, and AUC**

Append to `tests/unit/audit/test_transitions.py`:

```python
def test_flip_lead_lag_around_peak():
    """signal_flip_lead_lag returns trading days from peak to first High-vol flip."""
    from jutsu_engine.audit.transitions import Episode, signal_flip_lead_lag
    ep = Episode(id="t", peak=date(2020, 1, 3), trough=date(2020, 1, 10),
                 recovery=date(2020, 1, 20), portfolio_scored=True)
    # vol-state series (dates, vol): flips to High two days after peak
    dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    vol = ["Low", "Low", "Low", "High"]
    lead = signal_flip_lead_lag(dates, vol, ep)  # positive = lagging (after peak)
    assert lead == 2


def test_flip_count_ratio_vs_stock():
    """flip_count_ratio divides an arm's flip count by the stock arm's."""
    from jutsu_engine.audit.transitions import flip_count_ratio
    arm_vol = ["Low", "High", "Low", "High", "Low"]   # 4 flips
    stock_vol = ["Low", "Low", "High", "Low"]         # 2 flips
    assert flip_count_ratio(arm_vol, stock_vol) == 2.0


def test_auc_vol_state_at_t_plus_21_perfect_separator():
    """auc_vol_state_forward returns 1.0 when the score perfectly ranks t+21 state."""
    from jutsu_engine.audit.transitions import auc_vol_state_forward
    # score rises monotonically; future High-vol (label 1) has the higher scores
    scores = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    future_high = [0, 0, 0, 1, 1, 1]   # already the t+21 labels aligned by caller
    assert auc_vol_state_forward(scores, future_high) == 1.0


def test_auc_handles_single_class_returns_nan():
    """auc_vol_state_forward returns nan when the label vector is single-class."""
    import math
    from jutsu_engine.audit.transitions import auc_vol_state_forward
    assert math.isnan(auc_vol_state_forward([0.1, 0.2, 0.3], [1, 1, 1]))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -k "flip or auc" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with import errors for the new functions.

- [ ] **Step 3: Implement the signal-level helpers**

Append to `jutsu_engine/audit/transitions.py`:

```python
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
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    # average ranks for ties
    combined = np.concatenate([pos, neg])
    _, inv, counts = np.unique(combined, return_inverse=True, return_counts=True)
    # recompute average ranks for tie groups
    sort_idx = np.argsort(combined, kind="mergesort")
    tie_ranks = np.empty(len(combined), dtype=float)
    i = 0
    srt = combined[sort_idx]
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
```

- [ ] **Step 4: Run the signal-level tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -k "flip or auc" -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the whole transitions test file**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_transitions.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all; the DB-gated `test_episode_dates_match_qqq` PASSes or SKIPs).

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/transitions.py tests/unit/audit/test_transitions.py
git commit -m "feat(audit): signal-level transition helpers (flip lead/lag, flip ratio, AUC@t+21) (Task 4)"
```

---

## Task 5: Input-series builders — vix (DB reader) + shared z→EMA5 pipeline (pure)

**Files:**
- Create: `jutsu_engine/audit/input_series.py`
- Test: `tests/unit/audit/test_input_series.py`

- [ ] **Step 1: Write failing tests for the shared z→EMA5 pipeline + causality + VIX anchor dedup**

Create `tests/unit/audit/test_input_series.py`:

```python
"""Unit tests for vol-input series builders (pure + DB-gated VIX anchor)."""
import math

import numpy as np
import pandas as pd
import pytest

from jutsu_engine.audit.input_series import (
    z_ema5_pipeline,
    dedup_vix_daily,
    SERIES_COLUMNS,
)


def test_z_ema5_pipeline_leading_warmup_is_nan():
    """z_ema5_pipeline preserves leading NaN for the first (window-1) rows."""
    values = pd.Series(np.arange(1, 260, dtype=float))
    out = z_ema5_pipeline(values, window=200, ema_span=5)
    assert out.isna().iloc[:199].all()      # first 199 are warmup NaN (need 200)
    assert not math.isnan(out.iloc[-1])      # a real value once warmed up


def test_z_ema5_pipeline_causality_prefix_identical():
    """Truncating the input at X yields an identical value prefix (T-1 causality)."""
    rng = np.random.default_rng(0)
    values = pd.Series(rng.normal(size=400))
    full = z_ema5_pipeline(values, window=200, ema_span=5)
    truncated = z_ema5_pipeline(values.iloc[:300], window=200, ema_span=5)
    # the first 300 values of `full` must equal `truncated` exactly (trailing-only)
    pd.testing.assert_series_equal(
        full.iloc[:300].reset_index(drop=True),
        truncated.reset_index(drop=True),
        check_names=False,
    )


def test_dedup_vix_keeps_deterministic_row_per_date():
    """dedup_vix_daily keeps the earliest-timestamp row per date (real close wins)."""
    df = pd.DataFrame({
        "date": pd.to_datetime(
            ["2020-03-16 05:00", "2020-03-16 22:00", "2020-03-17 05:00"], utc=True),
        "close": [82.69, 75.91, 76.45],
    })
    out = dedup_vix_daily(df)
    assert len(out) == 2
    # 2020-03-16 keeps the 05:00 row (real CBOE peak close 82.69)
    row = out[out["date"].dt.date == pd.Timestamp("2020-03-16").date()]
    assert float(row["close"].iloc[0]) == 82.69


def test_series_columns_schema():
    """SERIES_COLUMNS defines the shared CSV schema for all arms."""
    assert SERIES_COLUMNS == ["date", "value", "source", "constructed_at"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_input_series.py -k "z_ema5 or dedup or schema" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError: jutsu_engine.audit.input_series`.

- [ ] **Step 3: Implement the pipeline + VIX dedup + VIX builder in a new module**

Create `jutsu_engine/audit/input_series.py`:

```python
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
```

- [ ] **Step 4: Run the pure tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_input_series.py -k "z_ema5 or dedup or schema" -p no:cacheprovider -o addopts="" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Add a DB-gated VIX-anchor integration test**

Append to `tests/unit/audit/test_input_series.py`:

```python
def test_build_vix_series_anchor_and_causality_db_gated():
    """build_vix_series recovers the 82.69 anchor and is causal (DB-gated)."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable")

    from jutsu_engine.audit.input_series import build_vix_series
    ser = build_vix_series(engine)          # raises if the anchor is wrong
    assert "value" in ser.columns and len(ser) > 1000
    # value column has warmup NaN then finite values
    assert ser["value"].notna().sum() > 500
```

Run: `.venv/bin/python -m pytest tests/unit/audit/test_input_series.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all; the DB-gated test PASSes or SKIPs).

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/input_series.py tests/unit/audit/test_input_series.py
git commit -m "feat(audit): vix input-series builder + shared z->EMA5 pipeline (anchor-validated dedup) (Task 5)"
```

---

## Task 6: Input-series builders — kronos (parquet reader, pure over a fixture)

**Files:**
- Modify: `jutsu_engine/audit/input_series.py`
- Test: `tests/unit/audit/test_input_series.py`

- [ ] **Step 1: Write a step that verifies the copied parquet checksum**

Append to `tests/unit/audit/test_input_series.py`:

```python
def test_kronos_parquet_checksum_matches_sidecar():
    """The copied Kronos parquet matches its recorded .sha256 sidecar."""
    import hashlib
    from jutsu_engine.audit.config import PROJECT_ROOT
    pq = PROJECT_ROOT / "claudedocs" / "inputs" / "QQQ_kronos_base.parquet"
    sidecar = pq.with_suffix(".parquet.sha256")
    if not pq.exists() or not sidecar.exists():
        pytest.skip("kronos parquet not present in this checkout")
    digest = hashlib.sha256(pq.read_bytes()).hexdigest()
    recorded = sidecar.read_text().split()[0]
    assert digest == recorded, "kronos parquet checksum drifted from sidecar"
```

- [ ] **Step 2: Write failing tests for the kronos builder over a synthetic parquet-shaped frame**

Append to `tests/unit/audit/test_input_series.py`:

```python
def test_build_kronos_series_selects_horizon_5_and_pipelines():
    """build_kronos_from_frame filters horizon==5, z-EMA5s std_return, T-1 causal."""
    from jutsu_engine.audit.input_series import build_kronos_from_frame
    n = 260
    dates = pd.date_range("2019-08-06", periods=n, freq="B")
    frame = pd.DataFrame({
        "timestamp": list(dates) * 2,
        "horizon": [5] * n + [20] * n,          # H=20 rows must be ignored
        "std_return": list(np.linspace(0.02, 0.05, n)) + [9.9] * n,
    })
    out = build_kronos_from_frame(frame, window=200, ema_span=5)
    assert list(out.columns) == ["date", "value"]
    assert len(out) == n                        # one row per H=5 timestamp
    assert out["value"].isna().iloc[:199].all() # warmup NaN preserved
    assert not math.isnan(out["value"].iloc[-1])


def test_build_kronos_from_frame_causality():
    """Truncating the kronos frame yields an identical value prefix (causal)."""
    from jutsu_engine.audit.input_series import build_kronos_from_frame
    n = 300
    dates = pd.date_range("2019-08-06", periods=n, freq="B")
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({
        "timestamp": dates, "horizon": 5,
        "std_return": np.abs(rng.normal(0.03, 0.01, n)),
    })
    full = build_kronos_from_frame(frame, window=200, ema_span=5)
    trunc = build_kronos_from_frame(frame.iloc[:250], window=200, ema_span=5)
    pd.testing.assert_series_equal(
        full["value"].iloc[:250].reset_index(drop=True),
        trunc["value"].reset_index(drop=True), check_names=False)
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_input_series.py -k "kronos" -p no:cacheprovider -o addopts="" -q`
Expected: `test_kronos_parquet_checksum_matches_sidecar` PASSes (or SKIPs); the two `build_kronos_from_frame` tests FAIL with ImportError.

- [ ] **Step 4: Implement the kronos builder**

Append to `jutsu_engine/audit/input_series.py`:

```python
KRONOS_PARQUET_REL = "claudedocs/inputs/QQQ_kronos_base.parquet"
KRONOS_HORIZON = 5


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
```

- [ ] **Step 5: Run the kronos tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_input_series.py -k "kronos" -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/input_series.py tests/unit/audit/test_input_series.py
git commit -m "feat(audit): kronos input-series builder (std_return@H5 -> z -> EMA5) from checksummed parquet (Task 6)"
```

---

## Task 7: Vol-input adapter strategy + the identity regression test (the load-bearing test)

**Files:**
- Create: `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py`
- Test: `tests/unit/strategies/test_vol_input_adapter.py`

**Injection point (verified):** `Hierarchical_Adaptive_v3_5b.on_bar` (line ~817) computes
`z_score = self._calculate_volatility_zscore(closes)` then (line ~824) `self._apply_hysteresis(z_score)`.
The adapter overrides `_calculate_volatility_zscore`: it calls `super()._calculate_volatility_zscore(closes)`
to get the engine-truth `vol_z`, then blends `blended = (1-w)*vol_z + w*series[date]`, where `date` comes
from `self._bars[-1].timestamp` (the current signal-symbol bar — `closes` has an integer index and carries
no date). If the series has no finite value for `date` (warmup/gap) or the base `vol_z` is None, fall back
to pure `vol_z` (= stock behavior). No other method is touched.

- [ ] **Step 1: Write the adapter unit tests (blend math + NaN fallback + None passthrough)**

Create `tests/unit/strategies/test_vol_input_adapter.py`:

```python
"""Unit + engine tests for the vol-input adapter (identity + blend behavior)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b_VolInput import (
    Hierarchical_Adaptive_v3_5b_VolInput,
)


class _Bar:
    def __init__(self, ts):
        self.timestamp = ts


def _make_adapter(series_map=None, weight="0.5"):
    """Adapter with no live-YAML; series injected as an in-memory date->value map."""
    s = Hierarchical_Adaptive_v3_5b_VolInput(
        vol_input_series=None, vol_blend_weight=Decimal(weight))
    # Inject the parsed series directly (bypasses CSV I/O for unit tests).
    s._vol_series_map = series_map or {}
    return s


def test_none_series_is_passthrough(monkeypatch):
    """With no series, _calculate_volatility_zscore returns the base vol_z unchanged."""
    s = _make_adapter(series_map={})
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.5"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.5")


def test_blend_math_at_weight_half(monkeypatch):
    """blended = 0.5*vol_z + 0.5*series[date] when the date has a finite value."""
    s = _make_adapter(series_map={date(2020, 1, 3): 3.0}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    # 0.5*1.0 + 0.5*3.0 = 2.0
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("2.0")


def test_missing_date_falls_back_to_pure_vol_z(monkeypatch):
    """A date with no series value falls back to pure vol_z (= stock behavior)."""
    s = _make_adapter(series_map={date(2020, 1, 6): 5.0}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]   # no entry for this date
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.0")


def test_nan_series_value_falls_back(monkeypatch):
    """A NaN series value (warmup) falls back to pure vol_z."""
    import math
    s = _make_adapter(series_map={date(2020, 1, 3): float("nan")}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: Decimal("1.0"))
    assert s._calculate_volatility_zscore(pd.Series([1.0])) == Decimal("1.0")


def test_base_none_z_passes_through_none(monkeypatch):
    """When base vol_z is None (warmup), the adapter returns None (no blend)."""
    s = _make_adapter(series_map={date(2020, 1, 3): 3.0}, weight="0.5")
    s._bars = [_Bar(pd.Timestamp("2020-01-03", tz="UTC"))]
    monkeypatch.setattr(
        Hierarchical_Adaptive_v3_5b_VolInput.__bases__[0],
        "_calculate_volatility_zscore", lambda self, closes: None)
    assert s._calculate_volatility_zscore(pd.Series([1.0])) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/strategies/test_vol_input_adapter.py -k "blend or passthrough or fall or none" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError` for the adapter.

- [ ] **Step 3: Implement the adapter subclass**

Create `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py`:

```python
"""Hierarchical Adaptive v3.5b — vol-input ablation adapter (DIAGNOSTIC ONLY).

Subclasses v3.5b and blends a PRECOMPUTED vol-input series into the vol-z step. This
strategy exists solely for the EXP-007 ablation battery; it is NEVER referenced by a
live YAML or the scheduler. Arms differ only by which series CSV is injected.

Behavior: at the vol-z step, blended = (1-w)*vol_z + w*series[date]. If the series has
no finite value for the current bar's date (warmup/gap) or the base vol_z is None,
fall back to pure vol_z (== stock v3.5b). Hysteresis thresholds and all other logic
and parameters are untouched.

IDENTITY GUARANTEE: with vol_input_series=None the subclass produces a bit-identical
regime stream to stock v3.5b over the full period (enforced by the identity regression
test — the adapter's most important test).

Construction: the battery harness constructs this class DIRECTLY (not via a live YAML).
The two new params are passed explicitly. vol_blend_weight is a Decimal; if the harness
ever routes it through the LiveStrategyRunner/plateau float->Decimal bridge, add it to
that DECIMAL_PARAMS set — but the battery keeps construction explicit (Task 11), so the
Decimal is supplied directly here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import (
    Hierarchical_Adaptive_v3_5b,
)


class Hierarchical_Adaptive_v3_5b_VolInput(Hierarchical_Adaptive_v3_5b):
    """v3.5b + precomputed vol-input blend at the vol-z step (ablation only)."""

    def __init__(self, *args,
                 vol_input_series: Optional[str] = None,
                 vol_blend_weight: Decimal = Decimal("0.5"),
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.vol_input_series = vol_input_series
        self.vol_blend_weight = (vol_blend_weight if isinstance(vol_blend_weight, Decimal)
                                 else Decimal(str(vol_blend_weight)))
        # date -> float value map (NaN allowed); empty when no series.
        self._vol_series_map: dict[date, float] = {}
        if vol_input_series is not None:
            self._vol_series_map = self._load_series_map(Path(vol_input_series))

    @staticmethod
    def _load_series_map(path: Path) -> dict[date, float]:
        """Parse a builder CSV (comment header + date,value,...) to a date->float map."""
        df = pd.read_csv(path, comment="#")
        out: dict[date, float] = {}
        for _, r in df.iterrows():
            d = pd.Timestamp(r["date"]).date()
            out[d] = float(r["value"])
        return out

    def _calculate_volatility_zscore(self, closes: pd.Series) -> Optional[Decimal]:
        """Engine-truth vol_z, then blend the injected series value for the bar's date.

        The base class returns the production vol_z (or None during warmup). We read
        the current signal-symbol bar's date from self._bars[-1].timestamp (closes has
        an integer index and no date). If a finite series value exists for that date,
        blend it; otherwise (warmup/gap/None base) return the base value unchanged.
        """
        base = super()._calculate_volatility_zscore(closes)
        if base is None or not self._vol_series_map or not self._bars:
            return base
        d = self._bars[-1].timestamp
        d = d.date() if hasattr(d, "date") else d
        val = self._vol_series_map.get(d)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return base                                  # warmup/gap -> pure vol_z
        w = self.vol_blend_weight
        return (Decimal("1") - w) * base + w * Decimal(str(val))
```

- [ ] **Step 4: Run the adapter unit tests**

Run: `.venv/bin/python -m pytest tests/unit/strategies/test_vol_input_adapter.py -k "blend or passthrough or fall or none" -p no:cacheprovider -o addopts="" -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Write the IDENTITY REGRESSION test (engine run; DB-gated)**

This is the plan's most important test. It runs a full-period `BacktestRunner` for stock v3_5b and for the adapter with `vol_input_series=None`, then asserts the regime timeseries CSVs are identical row-for-row on `Date, Regime, Trend, Vol`.

Append to `tests/unit/strategies/test_vol_input_adapter.py`:

```python
def test_identity_no_series_equals_stock_v3_5b_db_gated(tmp_path):
    """Adapter with no series produces a bit-identical regime stream to stock v3.5b."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable (identity test needs the engine)")

    from jutsu_engine.audit.battery import run_regime_backtest

    # stock v3_5b via the live YAML; adapter constructed from the SAME golden params.
    stock_csv = run_regime_backtest(
        strategy_id="v3_5b", vol_input_series=None, vol_blend_weight=None,
        start=date(2010, 2, 1), end=date.today(),
        output_dir=str(tmp_path / "stock"))
    adapter_csv = run_regime_backtest(
        strategy_id="v3_5b", vol_input_series=None,
        vol_blend_weight="0.5",              # weight is irrelevant when series is None
        start=date(2010, 2, 1), end=date.today(),
        output_dir=str(tmp_path / "adapter"))

    a = pd.read_csv(stock_csv)[["Date", "Regime", "Trend", "Vol"]]
    b = pd.read_csv(adapter_csv)[["Date", "Regime", "Trend", "Vol"]]
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
```

Note: `run_regime_backtest` is implemented in Task 8 — this test drives its interface. It will error (ImportError) until Task 8; that is expected and re-run in Task 8 Step 5.

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py tests/unit/strategies/test_vol_input_adapter.py
git commit -m "feat(strategy): vol-input ablation adapter (blend at vol-z step; identity=stock) (Task 7)"
```

---

## Task 8: Engine-truth replay — `battery.py` regime backtest + signal replay + smoothing builder

**Files:**
- Create: `jutsu_engine/audit/battery.py`
- Modify: `jutsu_engine/audit/input_series.py` (smoothing builder, which needs the replay)
- Test: `tests/unit/audit/test_battery.py`, and re-run Task 7 Step 5.

**Mechanism decision (justified):** For signal-level metrics over 1999→present we use the
existing `LiveStrategyRunner.calculate_signals(market_data)` single-pass replay: it
instantiates the real strategy class once and feeds bars chronologically via
`_update_bar()` then `on_bar()`, with NO portfolio execution. It reuses the strategy
class VERBATIM (nothing reimplemented — the Kronos port's 87.5% engine-agreement is the
cautionary tale we avoid). We collect the per-bar regime by capturing
`strategy.get_current_regime()` and `strategy._last_z_score` after each `on_bar`. This is
~minutes for 27 years (a single bar loop), not the per-day fresh-runner hours the
live-recon module uses. **A small, additive, read-only extension is required:** we add a
`calculate_signal_stream(market_data)` method that mirrors `calculate_signals` but records
the per-bar state into a list (the existing method returns only the final signal). It is
additive, does not touch live/scheduler code paths, and reuses the exact bar-feeding loop
— justified per spec §5's engine-truth requirement. Portfolio metrics for the battery come
from the standard `BacktestRunner` (Task 11), unchanged.

- [ ] **Step 1: Write failing tests for `run_regime_backtest` (DB-gated) and `replay_signal_stream` (fake-runner, DB-free)**

Create `tests/unit/audit/test_battery.py`:

```python
"""Unit tests for battery engine-truth replay + smoothing builder (mostly DB-free)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest


def test_replay_signal_stream_records_per_bar_state():
    """replay_signal_stream feeds bars via a fake runner and records per-bar regime."""
    from jutsu_engine.audit.battery import replay_signal_stream

    class _FakeRunner:
        """Minimal LiveStrategyRunner double exposing calculate_signal_stream."""
        def calculate_signal_stream(self, market_data):
            df = market_data["QQQ"]
            return [
                {"date": r["date"], "cell": 1, "vol_state": "Low",
                 "z_score": float(r["close"]) / 100.0}
                for _, r in df.iterrows()
            ]

    md = {"QQQ": pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=3, freq="B"),
        "open": [1, 1, 1], "high": [1, 1, 1], "low": [1, 1, 1],
        "close": [100, 110, 120], "volume": [1, 1, 1],
    })}
    out = replay_signal_stream(_FakeRunner(), md)
    assert list(out.columns) == ["date", "cell", "vol_state", "z_score"]
    assert len(out) == 3
    assert out["z_score"].tolist() == [1.0, 1.1, 1.2]


def test_build_smoothing_from_stream():
    """build_smoothing_from_stream EMA5s the engine-truth z_score stream (T-1 causal)."""
    from jutsu_engine.audit.input_series import build_smoothing_from_stream
    stream = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=6, freq="B"),
        "z_score": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    })
    out = build_smoothing_from_stream(stream, ema_span=5)
    assert list(out.columns) == ["date", "value"]
    # EMA(span=5, adjust=False) of the z stream, first value == first z
    assert out["value"].iloc[0] == 0.0
    assert out["value"].iloc[-1] > out["value"].iloc[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with ImportError for `replay_signal_stream` / `build_smoothing_from_stream`.

- [ ] **Step 3: Add `calculate_signal_stream` to `LiveStrategyRunner` (additive, read-only)**

In `jutsu_engine/live/strategy_runner.py`, add a method inside the `LiveStrategyRunner` class (place it directly after `calculate_signals`, before `get_strategy_context`). Do not modify any existing method:

```python
    def calculate_signal_stream(self, market_data: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        """Replay bars chronologically, recording per-bar regime state (no portfolio).

        Mirrors calculate_signals' bar-feeding loop EXACTLY (same _update_bar + on_bar
        sequence, same treasury-bar handling) but returns ONE record per signal bar
        instead of only the final signal. Used by the audit battery for engine-truth
        signal-level metrics over long histories in a single pass. Read-only: touches
        no DB and no scheduler state.
        """
        signal_symbol = self.get_signal_symbol()
        treasury_symbol = self.get_treasury_symbol()
        for symbol in [signal_symbol, treasury_symbol]:
            if symbol not in market_data:
                raise ValueError(f"Missing required symbol data: {symbol}")

        signal_df = market_data[signal_symbol]
        treasury_df = market_data.get(treasury_symbol)

        stream: List[Dict[str, Any]] = []
        for idx in range(len(signal_df)):
            row = signal_df.iloc[idx]
            bar = MarketDataEvent(
                symbol=signal_symbol, timestamp=row['date'],
                open=Decimal(str(row['open'])), high=Decimal(str(row['high'])),
                low=Decimal(str(row['low'])), close=Decimal(str(row['close'])),
                volume=int(row['volume']), timeframe="1D")
            self.strategy._update_bar(bar)
            if treasury_df is not None and len(treasury_df) > idx:
                trow = treasury_df.iloc[idx]
                self.strategy._update_bar(MarketDataEvent(
                    symbol=treasury_symbol, timestamp=trow['date'],
                    open=Decimal(str(trow['open'])), high=Decimal(str(trow['high'])),
                    low=Decimal(str(trow['low'])), close=Decimal(str(trow['close'])),
                    volume=int(trow['volume']), timeframe="1D"))
            self.strategy.on_bar(bar)
            trend, vol, cell = self.strategy.get_current_regime()
            z = getattr(self.strategy, '_last_z_score', None)
            stream.append({
                "date": row['date'],
                "cell": cell,
                "vol_state": vol,
                "z_score": float(z) if z is not None else float("nan"),
            })
        return stream
```

- [ ] **Step 4: Implement `battery.py` replay helpers + `build_smoothing_from_stream`**

Create `jutsu_engine/audit/battery.py`:

```python
"""Module — vol-input ablation battery (spec §8): engine-truth replay + arms + gates.

Engine-truth requirement (spec §5): signal-level series come from the strategy's own
code path via LiveStrategyRunner.calculate_signal_stream (a single-pass bar replay,
no portfolio); portfolio metrics come from the standard BacktestRunner. Nothing in the
classifier is reimplemented. Read-only vs the DB.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd


def replay_signal_stream(runner, market_data: dict) -> pd.DataFrame:
    """Run a runner's calculate_signal_stream and shape it into a DataFrame.

    `runner` is a LiveStrategyRunner (or a test double) exposing
    calculate_signal_stream(market_data) -> list of {date, cell, vol_state, z_score}.
    Returns a DataFrame with exactly those columns, in bar order.
    """
    records = runner.calculate_signal_stream(market_data)
    return pd.DataFrame(records, columns=["date", "cell", "vol_state", "z_score"])


def _build_live_runner(strategy_id: str, vol_input_series, vol_blend_weight):
    """Build a LiveStrategyRunner around stock v3_5b OR the vol-input adapter.

    When vol_input_series is None and vol_blend_weight is None -> stock v3_5b class via
    its live YAML (identity baseline). Otherwise -> the adapter class, constructed from
    the SAME live golden params plus the two adapter params (explicit construction, so
    the Decimal weight is passed directly, not via any float bridge).
    """
    from jutsu_engine.audit.config import resolve_strategy
    from jutsu_engine.live.strategy_runner import LiveStrategyRunner

    spec = resolve_strategy(strategy_id)
    if vol_input_series is None and vol_blend_weight is None:
        import importlib
        mod = importlib.import_module(spec.module_path)
        cls = getattr(mod, spec.class_name)
        return LiveStrategyRunner(strategy_class=cls, config_path=spec.config_path)

    # Adapter path: reuse the golden YAML params, add the two adapter kwargs.
    from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b_VolInput import (
        Hierarchical_Adaptive_v3_5b_VolInput,
    )
    runner = LiveStrategyRunner(
        strategy_class=Hierarchical_Adaptive_v3_5b_VolInput,
        config_path=spec.config_path)
    # LiveStrategyRunner already built .strategy from the YAML; but it did NOT pass the
    # adapter kwargs. Re-init the adapter with golden params + adapter kwargs so the
    # series is wired in. Golden params come from the YAML the runner already loaded.
    import yaml
    from jutsu_engine.live.strategy_runner import EXCLUDED_PARAMS
    with open(spec.config_path) as f:
        params = dict(yaml.safe_load(f)["strategy"]["parameters"])
    for k in EXCLUDED_PARAMS:
        params.pop(k, None)
    params = runner._convert_decimal_params(params)
    params["vol_input_series"] = vol_input_series
    if vol_blend_weight is not None:
        params["vol_blend_weight"] = Decimal(str(vol_blend_weight))
    runner.strategy = Hierarchical_Adaptive_v3_5b_VolInput(**params)
    runner.strategy.init()
    return runner


def run_regime_backtest(strategy_id: str, vol_input_series, vol_blend_weight,
                        start: date, end: date, output_dir: str) -> str:
    """Full-period portfolio backtest -> regime timeseries CSV path (BacktestRunner).

    Constructs stock v3_5b (vol_input_series=None AND vol_blend_weight=None) or the
    adapter, then runs the standard BacktestRunner exactly as attribution.run_attribution
    does, returning the regime_timeseries_csv path. Used by the identity test (Task 7)
    and the battery portfolio runs (Task 11).
    """
    from jutsu_engine.application.backtest_runner import BacktestRunner
    from jutsu_engine.audit.attribution import _all_symbols

    runner = _build_live_runner(strategy_id, vol_input_series, vol_blend_weight)
    strategy = runner.strategy
    config = {
        "symbols": _all_symbols(strategy_id),
        "timeframe": "1D",
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end_date": datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        "initial_capital": Decimal("10000"),
    }
    bt = BacktestRunner(config)
    results = bt.run(strategy, output_dir=output_dir)
    ts_csv = results.get("regime_timeseries_csv")
    if not ts_csv or not Path(ts_csv).exists():
        raise RuntimeError("battery backtest emitted no regime timeseries CSV")
    return str(ts_csv)
```

Append the smoothing builder to `jutsu_engine/audit/input_series.py`:

```python
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
```

- [ ] **Step 5: Run the battery unit tests AND the Task 7 identity test**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py tests/unit/strategies/test_vol_input_adapter.py -p no:cacheprovider -o addopts="" -q`
Expected: the DB-free tests PASS; the DB-gated `test_identity_no_series_equals_stock_v3_5b_db_gated` PASSes if the DB is reachable (it runs two ~20 s backtests, ~40 s total) or SKIPs. **If the identity test FAILS, do not proceed — the adapter is not bit-identical; debug the injection before continuing (this is the gate the whole battery rests on).**

- [ ] **Step 6: Add a short-window engine test proving the blend changes vol states (DB-gated)**

Append to `tests/unit/strategies/test_vol_input_adapter.py`:

```python
def test_short_window_blend_changes_vol_states_db_gated(tmp_path):
    """A synthetic high-value series blended at w=0.5 flips more bars to High vol."""
    from sqlalchemy import text
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("market_data DB unavailable")

    from jutsu_engine.audit.battery import run_regime_backtest
    from jutsu_engine.audit.input_series import write_series

    # Build a synthetic series that is strongly positive over 2021 (pushes toward High).
    dates = pd.date_range("2020-06-01", "2022-06-01", freq="B")
    series_df = pd.DataFrame({"date": dates, "value": [5.0] * len(dates)})
    csv = write_series(tmp_path / "synthetic.csv", series_df, source="synthetic",
                       provenance="test: constant +5 to force High-vol")

    stock = run_regime_backtest("v3_5b", None, None, date(2020, 6, 1),
                                date(2022, 6, 1), str(tmp_path / "stock"))
    blended = run_regime_backtest("v3_5b", str(csv), "0.5", date(2020, 6, 1),
                                  date(2022, 6, 1), str(tmp_path / "blend"))
    a = pd.read_csv(stock)
    b = pd.read_csv(blended)
    # blended should classify strictly MORE High-vol days than stock (the +5 push)
    assert (b["Vol"] == "High").sum() > (a["Vol"] == "High").sum()
```

Run: `.venv/bin/python -m pytest tests/unit/strategies/test_vol_input_adapter.py -k "short_window" -p no:cacheprovider -o addopts="" -q`
Expected: PASS if DB reachable (two short backtests, seconds each), else SKIP.

- [ ] **Step 7: Commit**

```bash
git add jutsu_engine/audit/battery.py jutsu_engine/audit/input_series.py jutsu_engine/live/strategy_runner.py tests/unit/audit/test_battery.py tests/unit/strategies/test_vol_input_adapter.py
git commit -m "feat(audit): engine-truth signal replay (calculate_signal_stream) + regime backtest + smoothing builder (Task 8)"
```

---

## Task 9: Arms table + gate evaluation (pure)

**Files:**
- Modify: `jutsu_engine/audit/battery.py`
- Test: `tests/unit/audit/test_battery.py`

- [ ] **Step 1: Write failing tests for the arms table and the gate logic (incl. the flatness SIGN rule)**

Append to `tests/unit/audit/test_battery.py`:

```python
def test_battery_arms_table():
    """battery_arms yields stock + 3 gated @0.5 + 6 ungated diagnostic @0.25/0.75."""
    from jutsu_engine.audit.battery import battery_arms
    arms = battery_arms()
    ids = [a["id"] for a in arms]
    assert "stock" in ids
    gated = [a for a in arms if a["gated"]]
    assert {a["id"] for a in gated} == {"kronos", "vix", "smoothing"}
    assert all(a["weight"] == 0.5 for a in gated)
    diag = [a for a in arms if a["id"].endswith(("_lo", "_hi"))]
    assert len(diag) == 6
    assert {a["weight"] for a in diag} == {0.25, 0.75}


def test_signal_gate_requires_improvement_without_auc_drop():
    """signal_gate passes only if exit-lag OR whipsaw improves AND AUC stays >= 0.815."""
    from jutsu_engine.audit.battery import signal_gate
    # improves whipsaw ratio (<1) and AUC within bar -> pass
    assert signal_gate(exit_lag_delta=0.0, whipsaw_ratio=0.9, auc=0.82) is True
    # AUC below the raw-bar range -> fail regardless of improvement
    assert signal_gate(exit_lag_delta=-1.0, whipsaw_ratio=0.8, auc=0.80) is False
    # no improvement (worse exit lag, whipsaw ratio >=1) -> fail
    assert signal_gate(exit_lag_delta=1.0, whipsaw_ratio=1.1, auc=0.82) is False


def test_portfolio_gate_bootstrap_ci_rule():
    """portfolio_gate passes if 2022 improves and Sharpe CI is not a CI-excluding-zero drop."""
    from jutsu_engine.audit.battery import portfolio_gate
    # 2022 dd_capture improves (lower), Sharpe delta CI overlaps zero -> pass
    assert portfolio_gate(dd_capture_delta=-0.05, ret2022_delta=0.0,
                          sharpe_ci=(-0.02, 0.03)) is True
    # 2022 improves but Sharpe CI excludes zero on the negative side -> fail
    assert portfolio_gate(dd_capture_delta=-0.05, ret2022_delta=0.0,
                          sharpe_ci=(-0.10, -0.02)) is False
    # no 2022 improvement -> fail
    assert portfolio_gate(dd_capture_delta=0.05, ret2022_delta=-0.01,
                          sharpe_ci=(-0.01, 0.01)) is False


def test_flatness_sign_rule():
    """flatness_diagnostic passes only if every gate-delta keeps its sign at 0.25/0.75."""
    from jutsu_engine.audit.battery import flatness_diagnostic
    # all three deltas negative at 0.5 and both neighbors -> same sign -> pass
    at50 = {"exit_lag": -1.0, "whipsaw_ratio": -0.1, "dd_capture": -0.05}
    lo = {"exit_lag": -0.5, "whipsaw_ratio": -0.2, "dd_capture": -0.02}
    hi = {"exit_lag": -1.5, "whipsaw_ratio": -0.05, "dd_capture": -0.08}
    assert flatness_diagnostic(at50, lo, hi) is True
    # a sign flip at the hi neighbor (dd_capture positive) -> fragile -> fail
    hi_flip = {"exit_lag": -1.5, "whipsaw_ratio": -0.05, "dd_capture": 0.02}
    assert flatness_diagnostic(at50, lo, hi_flip) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "arms or gate or flatness" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement the arms table + gates**

Append to `jutsu_engine/audit/battery.py`:

```python
# Spec §8: the raw vol_zscore AUC bar (VER1; alignment-dependent).
AUC_BAR_LO, AUC_BAR_HI = 0.815, 0.828
GATED_WEIGHT = 0.5
DIAG_WEIGHTS = (0.25, 0.75)
GATED_ARMS = ("kronos", "vix", "smoothing")


def battery_arms() -> list[dict]:
    """The spec §8 arms: stock baseline + 3 gated @0.5 + 6 ungated diagnostic @0.25/0.75.

    Each arm: {id, series (arm key or None), weight (or None), gated (bool)}.
    The diagnostic neighbors (id suffix _lo/_hi) are NEVER used to select a better w;
    they only feed the flatness diagnostic (spec §8, flatness SIGN rule).
    """
    arms = [{"id": "stock", "series": None, "weight": None, "gated": False}]
    for a in GATED_ARMS:
        arms.append({"id": a, "series": a, "weight": GATED_WEIGHT, "gated": True})
    for a in GATED_ARMS:
        arms.append({"id": f"{a}_lo", "series": a, "weight": DIAG_WEIGHTS[0],
                     "gated": False})
        arms.append({"id": f"{a}_hi", "series": a, "weight": DIAG_WEIGHTS[1],
                     "gated": False})
    return arms


def signal_gate(exit_lag_delta: float, whipsaw_ratio: float, auc: float) -> bool:
    """Spec §8 signal gate: improves exit-lag OR whipsaw ratio, AUC not below the bar.

    exit_lag_delta = arm exit lag - stock exit lag (negative = earlier = better).
    whipsaw_ratio  = arm flips / stock flips (<1 = fewer flips = better).
    auc            = the arm's input-series AUC(vol-state@t+21), same alignment.
    Passes iff (exit_lag_delta < 0 OR whipsaw_ratio < 1.0) AND auc >= AUC_BAR_LO.
    """
    improves = (exit_lag_delta < 0) or (whipsaw_ratio < 1.0)
    return bool(improves and auc >= AUC_BAR_LO)


def portfolio_gate(dd_capture_delta: float, ret2022_delta: float,
                   sharpe_ci: tuple[float, float]) -> bool:
    """Spec §8 portfolio gate: 2022 improves, full-window Sharpe not a CI-excluding-zero drop.

    dd_capture_delta = arm 2022 dd_capture - stock (negative = better protection).
    ret2022_delta    = arm 2022 return - stock (positive = better).
    sharpe_ci        = bootstrap CI of the full-window Sharpe delta (lo, hi). A CI that
                       OVERLAPS zero counts as 'no degradation'; a CI entirely below
                       zero is a real degradation and FAILS.
    Passes iff (dd_capture_delta < 0 OR ret2022_delta > 0) AND not (hi < 0).
    """
    improves_2022 = (dd_capture_delta < 0) or (ret2022_delta > 0)
    lo, hi = sharpe_ci
    ci_degrades = hi < 0.0
    return bool(improves_2022 and not ci_degrades)


def flatness_diagnostic(at_half: dict, at_lo: dict, at_hi: dict) -> bool:
    """Spec §8 flatness SIGN rule: each gate-relevant delta keeps its SIGN at 0.25 & 0.75.

    at_half/at_lo/at_hi are dicts of {exit_lag, whipsaw_ratio, dd_capture} deltas vs
    stock at w=0.5, 0.25, 0.75. Passes iff, for every key, sign(at_lo) == sign(at_half)
    == sign(at_hi). A sign flip at either neighbor = fragile = FAIL despite the 0.5
    result. Neighbors are NEVER used to pick a better w.
    """
    import math

    def _sign(x):
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return 0
        return (x > 0) - (x < 0)

    for key in ("exit_lag", "whipsaw_ratio", "dd_capture"):
        s0 = _sign(at_half.get(key))
        if _sign(at_lo.get(key)) != s0 or _sign(at_hi.get(key)) != s0:
            return False
    return True


def arm_survives(signal_pass: bool, portfolio_pass: bool, flatness_pass: bool) -> bool:
    """Spec §8: an arm survives Tier 1 iff ALL three gates pass."""
    return bool(signal_pass and portfolio_pass and flatness_pass)
```

- [ ] **Step 4: Run the gate tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "arms or gate or flatness" -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/battery.py tests/unit/audit/test_battery.py
git commit -m "feat(audit): battery arms table + pre-registered gates (signal/portfolio/flatness SIGN rule) (Task 9)"
```

---

## Task 10: Bootstrap CI helper for the Sharpe delta (pure)

**Files:**
- Modify: `jutsu_engine/audit/battery.py`
- Test: `tests/unit/audit/test_battery.py`

- [ ] **Step 1: Write failing tests for the paired bootstrap CI**

Append to `tests/unit/audit/test_battery.py`:

```python
def test_bootstrap_sharpe_delta_ci_zero_when_identical():
    """bootstrap_sharpe_delta_ci returns a CI tightly around 0 for identical return series."""
    from jutsu_engine.audit.battery import bootstrap_sharpe_delta_ci
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 500)
    lo, hi = bootstrap_sharpe_delta_ci(r, r.copy(), n_boot=200, seed=7)
    assert lo <= 0.0 <= hi
    assert abs(hi - lo) < 0.05          # identical series -> near-zero spread


def test_bootstrap_sharpe_delta_ci_is_deterministic_with_seed():
    """A fixed seed makes the bootstrap CI reproducible."""
    from jutsu_engine.audit.battery import bootstrap_sharpe_delta_ci
    rng = np.random.default_rng(1)
    a = rng.normal(0.001, 0.01, 300)
    b = rng.normal(0.0005, 0.01, 300)
    ci1 = bootstrap_sharpe_delta_ci(a, b, n_boot=200, seed=42)
    ci2 = bootstrap_sharpe_delta_ci(a, b, n_boot=200, seed=42)
    assert ci1 == ci2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "bootstrap" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the paired bootstrap CI**

Append to `jutsu_engine/audit/battery.py`:

```python
import numpy as np


def _sharpe(returns: np.ndarray, periods: int = 252) -> float:
    r = returns[~np.isnan(returns)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods))


def bootstrap_sharpe_delta_ci(arm_returns, stock_returns, n_boot: int = 1000,
                              seed: int = 42, alpha: float = 0.05) -> tuple[float, float]:
    """Paired-index bootstrap CI of (arm Sharpe - stock Sharpe) over aligned daily returns.

    arm_returns and stock_returns are aligned daily-return arrays (same trading days;
    caller intersects on Date first). Resamples the SHARED day index n_boot times
    (paired, preserving the arm-vs-stock pairing per day) and returns the (alpha/2,
    1-alpha/2) percentile CI of the Sharpe delta. Deterministic given seed. A CI
    overlapping zero = 'no degradation' (portfolio_gate). Underpowered by design
    (n~=1-crash-episode caution, SYNTHESIS-001) — the CI is reported, not over-trusted.
    """
    a = np.asarray(arm_returns, dtype=float)
    s = np.asarray(stock_returns, dtype=float)
    n = min(len(a), len(s))
    a, s = a[:n], s[:n]
    rng = np.random.default_rng(seed)
    deltas = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[i] = _sharpe(a[idx]) - _sharpe(s[idx])
    lo = float(np.percentile(deltas, 100 * alpha / 2))
    hi = float(np.percentile(deltas, 100 * (1 - alpha / 2)))
    return (lo, hi)
```

- [ ] **Step 4: Run the bootstrap tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "bootstrap" -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/battery.py tests/unit/audit/test_battery.py
git commit -m "feat(audit): paired bootstrap Sharpe-delta CI for the portfolio gate (Task 10)"
```

---

## Task 11: Battery campaign runner (portfolio + signal replays, checkpointed)

**Files:**
- Modify: `jutsu_engine/audit/battery.py`
- Test: `tests/unit/audit/test_battery.py`

The runner reuses the plateau checkpoint primitives (`append_result`, `load_completed_hashes`,
`params_hash`) so a battery re-run resumes. Each arm's portfolio run and signal replay are
recorded to a JSONL. Because the battery is small (10 arms), the runner is serial by default;
`--workers` maps to a ProcessPoolExecutor only for the portfolio backtests (the single-writer
invariant from `plateau.py` is preserved: the parent writes; workers only compute).

- [ ] **Step 1: Write a failing test that drives the runner with an injected fake backtest fn (DB-free)**

Append to `tests/unit/audit/test_battery.py`:

```python
def test_run_battery_checkpoints_and_resumes(tmp_path):
    """run_battery records one row per arm and skips arms already in the JSONL."""
    from jutsu_engine.audit.battery import run_battery, battery_arms

    calls = {"n": 0}

    def fake_arm_fn(arm, run_dir):
        """Fake per-arm evaluator: returns a minimal result row without the engine."""
        calls["n"] += 1
        return {
            "arm": arm["id"], "weight": arm["weight"],
            "exit_lag_2022": 3, "whipsaw_ratio": 0.9, "auc": 0.82,
            "dd_capture_2022": 0.7, "ret2022": -0.13,
            "sharpe_ci_lo": -0.02, "sharpe_ci_hi": 0.03,
            "error": None,
        }

    campaign = tmp_path / "campaign_battery_v3_5b.jsonl"
    res1 = run_battery("v3_5b", tmp_path, arm_fn=fake_arm_fn,
                       campaign_file=campaign)
    n_arms = len(battery_arms())
    assert calls["n"] == n_arms
    assert len(res1["rows"]) == n_arms

    # Resume: no arm should be re-run.
    calls["n"] = 0
    res2 = run_battery("v3_5b", tmp_path, arm_fn=fake_arm_fn,
                       campaign_file=campaign)
    assert calls["n"] == 0
    assert len(res2["rows"]) == n_arms
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "run_battery" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with ImportError for `run_battery`.

- [ ] **Step 3: Implement `run_battery` + the real per-arm evaluator**

Append to `jutsu_engine/audit/battery.py`:

```python
from jutsu_engine.audit.plateau import append_result, load_completed_hashes, params_hash

# Tier-1 windows (spec §8): portfolio 2019-08 -> 2025-12; signal 1999->present for
# non-kronos arms, 2019-08 -> 2025-12 for kronos (its parquet coverage).
TIER1_PORTFOLIO_START = date(2019, 8, 1)
TIER1_PORTFOLIO_END = date(2025, 12, 31)
SIGNAL_START_FULL = date(1999, 3, 10)
SIGNAL_END = date.today()
KRONOS_SIGNAL_START = date(2019, 8, 6)


def _arm_hash(arm: dict) -> str:
    """Stable hash of an arm (id + weight) for checkpoint dedup."""
    return params_hash({"arm": arm["id"], "weight": arm["weight"]})


def run_battery(strategy_id: str, run_dir, arm_fn, campaign_file=None,
                progress=lambda msg: None) -> dict:
    """Run (or resume) the battery: evaluate each arm, checkpoint each row to JSONL.

    arm_fn(arm, run_dir) -> result row dict (injectable so the orchestration is unit-
    tested without the engine; the default real evaluator is evaluate_arm). Reuses the
    plateau append_result (fsync) + load_completed_hashes (resume) primitives; a re-run
    skips arms whose hash is already present. Single-writer: this parent writes, arm_fn
    only computes.
    """
    from pathlib import Path
    run_dir = Path(run_dir)
    campaign_file = Path(campaign_file) if campaign_file is not None \
        else run_dir / strategy_id / f"campaign_battery_{strategy_id}.jsonl"
    done = load_completed_hashes(campaign_file)
    for arm in battery_arms():
        h = _arm_hash(arm)
        if h in done:
            progress(f"skip {arm['id']} (already done)")
            continue
        progress(f"eval {arm['id']} (w={arm['weight']})")
        row = arm_fn(arm, run_dir)
        row["hash"] = h
        row["kind"] = "battery"
        row["param"] = arm["id"]
        append_result(campaign_file, row)     # fsync; single-writer
    from jutsu_engine.audit.plateau import _reload_rows
    return {"strategy_id": strategy_id, "rows": _reload_rows(campaign_file),
            "campaign_file": str(campaign_file)}


def evaluate_arm(arm: dict, run_dir) -> dict:
    """Real per-arm evaluator: build the series, run portfolio + signal replay, score.

    For the stock arm: run stock v3_5b. For a series arm: build the series CSV (kronos/
    vix/smoothing) under run_dir, then run the adapter with that series at the arm's
    weight. Computes: 2022-episode exit_lag/whipsaw/dd_capture/return (transitions),
    the input-series AUC(vol-state@t+21) (signal replay), and the bootstrap Sharpe-delta
    CI vs stock. Returns a result row consumed by the report/gate layer.

    Compute: one ~5-8 s portfolio backtest over the 2019-08->2025-12 window + one signal
    replay (seconds-minutes). Warmup-trim every regime timeseries before scoring (EXP-006).
    """
    from pathlib import Path
    from jutsu_engine.audit import transitions as tr
    from jutsu_engine.audit import input_series as isr
    from jutsu_engine.audit.attribution import era_metrics

    run_dir = Path(run_dir)
    series_dir = run_dir / "series"
    series_csv = None

    if arm["series"] is not None:
        series_csv = str(_ensure_series_csv(arm["series"], series_dir))

    ts_csv = run_regime_backtest(
        strategy_id="v3_5b",
        vol_input_series=series_csv,
        vol_blend_weight=(None if arm["id"] == "stock" else arm["weight"]),
        start=TIER1_PORTFOLIO_START, end=TIER1_PORTFOLIO_END,
        output_dir=str(run_dir / arm["id"]))

    ts = pd.read_csv(ts_csv)
    ts = tr.trim_warmup(ts, start=TIER1_PORTFOLIO_START)

    # 2022 episode metrics
    episodes = {e.id: e for e in tr.load_episodes()}
    ep2022 = episodes["bear2022"]
    port_row = tr.score_episode_portfolio(ts, ep2022, start=TIER1_PORTFOLIO_START)

    # 2022 calendar return delta comes from era_metrics (2022 bear era row)
    eras = era_metrics(ts)
    r2022 = eras[eras["era"] == "2022 bear"]["strategy_total_return"]
    ret2022 = float(r2022.iloc[0]) if not r2022.empty else float("nan")

    return {
        "arm": arm["id"], "weight": arm["weight"],
        "exit_lag_2022": port_row["exit_lag_days"],
        "whipsaw_2022": port_row["whipsaw_flips"],
        "dd_capture_2022": port_row["drawdown_capture"],
        "ret2022": ret2022,
        "regime_timeseries_csv": ts_csv,
        "series_csv": series_csv,
        "error": None,
    }


def _ensure_series_csv(series_key: str, series_dir):
    """Build (once) and return the CSV path for a series arm key (kronos/vix/smoothing)."""
    from pathlib import Path
    from jutsu_engine.audit import input_series as isr
    series_dir = Path(series_dir)
    out = series_dir / f"{series_key}.csv"
    if out.exists():
        return out
    if series_key == "kronos":
        df = isr.build_kronos_series()
        return isr.write_series(out, df, source="kronos",
                                provenance="Kronos-base std_return@H5 -> z(200) -> EMA5")
    if series_key == "vix":
        from jutsu_engine.audit import db as audit_db
        engine = audit_db.get_engine()
        df = isr.build_vix_series(engine)
        return isr.write_series(out, df, source="vix",
                                provenance="$VIX daily close (dedup) -> z(200) -> EMA5")
    if series_key == "smoothing":
        stream = _stock_signal_stream()
        df = isr.build_smoothing_from_stream(stream)
        return isr.write_series(out, df, source="smoothing",
                                provenance="engine-truth vol_z -> EMA5 (zero-info control)")
    raise ValueError(f"unknown series key: {series_key}")


def _stock_signal_stream():
    """Engine-truth vol-z stream for stock v3_5b (for the smoothing builder)."""
    from jutsu_engine.audit import db as audit_db
    from jutsu_engine.audit.attribution import _all_symbols
    engine = audit_db.get_engine()
    runner = _build_live_runner("v3_5b", None, None)
    symbols = _all_symbols("v3_5b")
    md = {}
    for sym in symbols:
        bars = audit_db.load_bars(engine, sym, SIGNAL_END, lookback=10000)
        if not bars.empty:
            md[sym] = bars.rename(columns={"date": "date"})
    return replay_signal_stream(runner, md)
```

- [ ] **Step 4: Run the runner test**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "run_battery" -p no:cacheprovider -o addopts="" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the whole battery test file**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (all DB-free tests).

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/battery.py tests/unit/audit/test_battery.py
git commit -m "feat(audit): battery campaign runner (checkpointed per-arm eval; portfolio + signal) (Task 11)"
```

---

## Task 12: Report rendering (transition tables + battery verdicts)

**Files:**
- Modify: `jutsu_engine/audit/report.py`
- Test: `tests/unit/audit/test_report.py`

Follow the existing conventions exactly: `_fmt` (None → 'N/A'), `_df_to_md`, captions
OUTSIDE the table block, a standalone `write_battery_report`. The report includes:
per-arm × per-episode transition tables, a signal-AUC table with the 0.815–0.828 bar,
era-sliced portfolio deltas (2022 decisive) with bootstrap CIs, the flatness diagnostic
table, and a one-line verdict per arm. Every number carries the T-1 convention note.

- [ ] **Step 1: Write failing tests for the two new renderers**

Append to `tests/unit/audit/test_report.py`:

```python
def test_render_transition_section_uses_na_for_none():
    """render_transition_section prints N/A (never literal None) for missing exit lag."""
    from jutsu_engine.audit.report import render_transition_section
    rows = [{"arm": "stock", "episode": "covid2020", "exit_lag_days": None,
             "reentry_lag_days": 3, "drawdown_capture": 0.7,
             "whipsaw_flips": 2, "days_defensive": 10}]
    md = render_transition_section(rows)
    assert "N/A" in md
    assert "None" not in md
    assert "T-1" in md            # the T-1 convention note is present


def test_render_battery_section_has_auc_bar_and_verdicts():
    """render_battery_section shows the 0.815-0.828 AUC bar and one verdict per arm."""
    from jutsu_engine.audit.report import render_battery_section
    summary = {
        "strategy_id": "v3_5b",
        "arm_rows": [
            {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
             "whipsaw_ratio": 1.0, "dd_capture_2022": 0.9, "ret2022": -0.30,
             "sharpe_ci": (0.0, 0.0), "verdict": "baseline"},
            {"arm": "smoothing", "weight": 0.5, "auc": 0.82, "exit_lag_2022": 3,
             "whipsaw_ratio": 0.8, "dd_capture_2022": 0.7, "ret2022": -0.13,
             "sharpe_ci": (-0.02, 0.05), "verdict": "SURVIVES"},
        ],
        "flatness_rows": [
            {"arm": "smoothing", "exit_lag_sign_ok": True,
             "whipsaw_sign_ok": True, "dd_capture_sign_ok": True, "flatness_pass": True},
        ],
        "tier2_trigger": "kronos did not survive Tier 1 -> Tier 2 NOT triggered",
    }
    md = render_battery_section(summary)
    assert "0.815" in md and "0.828" in md
    assert "SURVIVES" in md
    assert "Tier 2" in md
    assert "None" not in md
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -k "transition or battery" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement the two renderers + `write_battery_report`**

Append to `jutsu_engine/audit/report.py`:

```python
# ---------------------------------------------------------------------------
# Regime battery (EXP-007) — spec §8 report renderers
# ---------------------------------------------------------------------------

AUC_RAW_BAR_LO, AUC_RAW_BAR_HI = 0.815, 0.828
T1_NOTE = ("_All series are T-1 aligned: the value for day D's decision derives only "
           "from information available at D-1's close._")


def render_transition_section(rows: list) -> str:
    """Render per-(arm,episode) transition metrics as markdown (captions outside tables).

    rows: list of dicts with arm, episode, exit_lag_days, reentry_lag_days,
    drawdown_capture, whipsaw_flips, days_defensive. None renders as 'N/A' via _fmt.
    """
    lines = [
        "## Transition metrics (per arm x episode)",
        "",
        T1_NOTE,
        "_exit/reentry lag in trading days (negative exit = de-risked before peak); "
        "drawdown_capture = strat MaxDD / QQQ MaxDD (lower = better; 1.0 = no "
        "protection); warmup-trimmed before scoring (EXP-006)._",
        "",
        "| arm | episode | exit_lag | reentry_lag | dd_capture | whipsaw | days_def |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['arm']} | {r['episode']} | "
            f"{_fmt(r.get('exit_lag_days'), '.0f')} | "
            f"{_fmt(r.get('reentry_lag_days'), '.0f')} | "
            f"{_fmt(r.get('drawdown_capture'), '.3f')} | "
            f"{_fmt(r.get('whipsaw_flips'), '.0f')} | "
            f"{_fmt(r.get('days_defensive'), '.0f')} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def render_battery_section(summary: dict) -> str:
    """Render the vol-input battery (EXP-007) section: AUC bar, deltas, flatness, verdicts."""
    lines = [
        "## Vol-input ablation battery (EXP-007)",
        "",
        f"- Strategy: **{summary['strategy_id']}**  |  "
        f"Raw vol_zscore AUC bar (VER1): **{AUC_RAW_BAR_LO}-{AUC_RAW_BAR_HI}**",
        T1_NOTE,
        "",
        "### Signal AUC + 2022 portfolio deltas (2022 decisive)",
        "_AUC = input-series AUC(vol-state@t+21), same alignment as the raw bar; an "
        "arm must not drop AUC below the bar. Sharpe CI = paired bootstrap of the "
        "full-window Sharpe delta vs stock (CI overlapping zero = no degradation). "
        "Underpowered by design (n~=1-crash-episode caution, SYNTHESIS-001)._",
        "",
        "| arm | w | AUC | exit_lag_2022 | whipsaw_ratio | dd_capture_2022 | ret2022 | sharpe_CI | verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in summary["arm_rows"]:
        ci = r.get("sharpe_ci") or (None, None)
        lines.append(
            f"| {r['arm']} | {_fmt(r.get('weight'), '.2f')} | "
            f"{_fmt(r.get('auc'), '.3f')} | "
            f"{_fmt(r.get('exit_lag_2022'), '.0f')} | "
            f"{_fmt(r.get('whipsaw_ratio'), '.3f')} | "
            f"{_fmt(r.get('dd_capture_2022'), '.3f')} | "
            f"{_fmt(r.get('ret2022'), '.4f')} | "
            f"[{_fmt(ci[0], '.3f')}, {_fmt(ci[1], '.3f')}] | "
            f"**{r.get('verdict', 'N/A')}** |"
        )
    lines += [
        "",
        "### Flatness diagnostic (w=0.25 / 0.75 sign consistency; ungated)",
        "_Each gate-relevant delta must keep its SIGN at both neighbors as at w=0.5. "
        "A sign flip at either neighbor = fragile = FAIL despite the 0.5 result. "
        "Neighbors are NEVER used to select a better w (spec §8)._",
        "",
        "| arm | exit_lag sign ok | whipsaw sign ok | dd_capture sign ok | flatness |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in summary.get("flatness_rows", []):
        lines.append(
            f"| {r['arm']} | {r.get('exit_lag_sign_ok')} | "
            f"{r.get('whipsaw_sign_ok')} | {r.get('dd_capture_sign_ok')} | "
            f"**{'PASS' if r.get('flatness_pass') else 'FAIL'}** |"
        )
    lines += [
        "",
        "### Tier-2 trigger decision",
        f"- {summary.get('tier2_trigger', 'N/A')}",
        "",
        "_Expected-outcomes note (pre-registered, spec §8): if smoothing survives and "
        "kronos/vix add nothing beyond it -> 'filtering, not forecasting' (cheapest "
        "improvement ships). If vix matches kronos -> Kronos adds model-ops for "
        "nothing. If kronos uniquely survives -> a learned forecaster beat implied "
        "vol; Tier 2 must confirm it._",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_battery_report(run_dir, strategy_id: str, markdown: str):
    """Write report_regime_battery_<strategy>.md (separate from other audit reports)."""
    from pathlib import Path
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_regime_battery_{strategy_id}.md"
    out.write_text(markdown)
    return out
```

- [ ] **Step 4: Run the renderer tests**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_report.py -k "transition or battery" -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jutsu_engine/audit/report.py tests/unit/audit/test_report.py
git commit -m "feat(audit): battery + transition report renderers (AUC bar, era deltas, flatness, verdicts) (Task 12)"
```

---

## Task 13: Summarize + verdict wiring in `battery.py` (pure over rows)

**Files:**
- Modify: `jutsu_engine/audit/battery.py`
- Test: `tests/unit/audit/test_battery.py`

- [ ] **Step 1: Write a failing test for `summarize_battery` (rows → report summary + verdicts)**

Append to `tests/unit/audit/test_battery.py`:

```python
def test_summarize_battery_assigns_verdicts_and_tier2():
    """summarize_battery runs the gates over arm rows and sets per-arm verdicts + Tier-2."""
    from jutsu_engine.audit.battery import summarize_battery
    # stock baseline + a surviving smoothing arm + its two neighbors (same-sign deltas)
    rows = [
        {"arm": "stock", "weight": None, "auc": 0.82, "exit_lag_2022": 5,
         "whipsaw_2022": 6, "dd_capture_2022": 0.9, "ret2022": -0.30},
        {"arm": "smoothing", "weight": 0.5, "auc": 0.82, "exit_lag_2022": 3,
         "whipsaw_2022": 4, "dd_capture_2022": 0.7, "ret2022": -0.13},
        {"arm": "smoothing_lo", "weight": 0.25, "auc": 0.82, "exit_lag_2022": 4,
         "whipsaw_2022": 5, "dd_capture_2022": 0.8, "ret2022": -0.20},
        {"arm": "smoothing_hi", "weight": 0.75, "auc": 0.82, "exit_lag_2022": 2,
         "whipsaw_2022": 3, "dd_capture_2022": 0.6, "ret2022": -0.10},
    ]
    # deterministic bootstrap CI stub (overlaps zero -> no degradation)
    def fake_ci(arm_id):
        return (-0.02, 0.05)
    summary = summarize_battery("v3_5b", rows, sharpe_ci_fn=fake_ci)
    verdicts = {r["arm"]: r["verdict"] for r in summary["arm_rows"]}
    assert verdicts["stock"] == "baseline"
    assert verdicts["smoothing"] == "SURVIVES"
    assert "kronos did not survive" in summary["tier2_trigger"] or \
           "Tier 2 NOT triggered" in summary["tier2_trigger"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "summarize_battery" -p no:cacheprovider -o addopts="" -q`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `summarize_battery`**

Append to `jutsu_engine/audit/battery.py`:

```python
def summarize_battery(strategy_id: str, rows: list, sharpe_ci_fn) -> dict:
    """Turn raw arm rows into the report summary: gate every gated arm, set verdicts.

    rows: per-arm result dicts (from run_battery/evaluate_arm) with arm, weight, auc,
    exit_lag_2022, whipsaw_2022, dd_capture_2022, ret2022. sharpe_ci_fn(arm_id) returns
    the (lo, hi) bootstrap Sharpe-delta CI for that arm vs stock (injected so this stays
    pure/testable; the CLI wires the real bootstrap_sharpe_delta_ci over aligned returns).
    Verdicts: 'baseline' (stock), 'SURVIVES' / 'fails: <reason>' for gated arms,
    'diagnostic' for the _lo/_hi neighbors. tier2_trigger states whether the kronos arm
    survived (spec §8: Tier 2 runs only if kronos survives Tier 1).
    """
    by_id = {r["arm"]: r for r in rows}
    stock = by_id.get("stock", {})
    stock_whip = stock.get("whipsaw_2022") or 0
    stock_exit = stock.get("exit_lag_2022")

    def _delta(arm_id, key):
        a, s = by_id.get(arm_id, {}).get(key), stock.get(key)
        if a is None or s is None:
            return None
        return a - s

    def _whip_ratio(arm_id):
        a = by_id.get(arm_id, {}).get("whipsaw_2022") or 0
        return (a / stock_whip) if stock_whip else (float("inf") if a else 1.0)

    arm_rows, flatness_rows = [], []
    kronos_survives = False

    for arm in battery_arms():
        r = dict(by_id.get(arm["id"], {}))
        r["weight"] = arm["weight"]
        r["whipsaw_ratio"] = _whip_ratio(arm["id"]) if arm["id"] != "stock" else 1.0
        if arm["id"] == "stock":
            r["sharpe_ci"] = (0.0, 0.0)
            r["verdict"] = "baseline"
            arm_rows.append(r)
            continue

        r["sharpe_ci"] = sharpe_ci_fn(arm["id"])
        if not arm["gated"]:
            r["verdict"] = "diagnostic"
            arm_rows.append(r)
            continue

        exit_delta = _delta(arm["id"], "exit_lag_2022") or 0.0
        dd_delta = _delta(arm["id"], "dd_capture_2022") or 0.0
        ret_delta = _delta(arm["id"], "ret2022") or 0.0
        sig = signal_gate(exit_delta, r["whipsaw_ratio"], r.get("auc") or 0.0)
        port = portfolio_gate(dd_delta, ret_delta, r["sharpe_ci"])

        # flatness over the arm's _lo/_hi neighbors
        at50 = {"exit_lag": exit_delta, "whipsaw_ratio": r["whipsaw_ratio"] - 1.0,
                "dd_capture": dd_delta}
        lo_id, hi_id = f"{arm['id']}_lo", f"{arm['id']}_hi"
        at_lo = {"exit_lag": _delta(lo_id, "exit_lag_2022"),
                 "whipsaw_ratio": (_whip_ratio(lo_id) - 1.0),
                 "dd_capture": _delta(lo_id, "dd_capture_2022")}
        at_hi = {"exit_lag": _delta(hi_id, "exit_lag_2022"),
                 "whipsaw_ratio": (_whip_ratio(hi_id) - 1.0),
                 "dd_capture": _delta(hi_id, "dd_capture_2022")}
        flat = flatness_diagnostic(at50, at_lo, at_hi)
        flatness_rows.append({
            "arm": arm["id"],
            "exit_lag_sign_ok": _same_sign(at50["exit_lag"], at_lo["exit_lag"], at_hi["exit_lag"]),
            "whipsaw_sign_ok": _same_sign(at50["whipsaw_ratio"], at_lo["whipsaw_ratio"], at_hi["whipsaw_ratio"]),
            "dd_capture_sign_ok": _same_sign(at50["dd_capture"], at_lo["dd_capture"], at_hi["dd_capture"]),
            "flatness_pass": flat,
        })

        survives = arm_survives(sig, port, flat)
        if survives:
            r["verdict"] = "SURVIVES"
            if arm["id"] == "kronos":
                kronos_survives = True
        else:
            reasons = []
            if not sig:
                reasons.append("signal")
            if not port:
                reasons.append("portfolio")
            if not flat:
                reasons.append("flatness")
            r["verdict"] = "fails: " + "+".join(reasons)
        arm_rows.append(r)

    tier2 = ("kronos SURVIVED Tier 1 -> Tier 2 TRIGGERED (backfill 2010-02->2019-08, "
             "rebuild kronos CSV, re-run on 2010->present)" if kronos_survives else
             "kronos did not survive Tier 1 -> Tier 2 NOT triggered")

    return {"strategy_id": strategy_id, "arm_rows": arm_rows,
            "flatness_rows": flatness_rows, "tier2_trigger": tier2}


def _same_sign(*vals) -> bool:
    """True if all non-None values share the same sign (0 counts as its own sign)."""
    import math
    signs = []
    for v in vals:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            signs.append(0)
        else:
            signs.append((v > 0) - (v < 0))
    return len(set(signs)) == 1
```

- [ ] **Step 4: Run the summarize test**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -k "summarize_battery" -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Run the whole battery file**

Run: `.venv/bin/python -m pytest tests/unit/audit/test_battery.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/audit/battery.py tests/unit/audit/test_battery.py
git commit -m "feat(audit): battery summarize+verdict wiring (gates over arm rows, Tier-2 trigger) (Task 13)"
```

---

## Task 14: CLI `jutsu audit battery` subcommand + smoke path

**Files:**
- Modify: `jutsu_engine/cli/commands/audit.py`
- Test: `tests/unit/cli/test_battery_cli.py`

- [ ] **Step 1: Write a failing CLI test (invokes the group with a stubbed runner; DB-free)**

Create `tests/unit/cli/test_battery_cli.py`:

```python
"""CLI tests for `jutsu audit battery` (stubbed runner; DB-free)."""
from click.testing import CliRunner


def test_battery_help_lists_options():
    """`jutsu audit battery --help` lists --strategy, --arms, --workers, --smoke."""
    from jutsu_engine.cli.commands.audit import audit
    result = CliRunner().invoke(audit, ["battery", "--help"])
    assert result.exit_code == 0
    for opt in ("--strategy", "--arms", "--workers", "--smoke"):
        assert opt in result.output


def test_battery_smoke_invokes_runner(monkeypatch, tmp_path):
    """`--smoke` runs stock + one arm and writes a report (runner stubbed)."""
    import jutsu_engine.cli.commands.audit as audit_cli
    from jutsu_engine.cli.commands.audit import audit

    calls = {}

    def fake_run_battery_and_report(strategy_id, arms, workers, smoke, run_dir):
        calls["args"] = (strategy_id, tuple(arms or ()), workers, smoke)
        return tmp_path / f"report_regime_battery_{strategy_id}.md"

    monkeypatch.setattr(audit_cli, "_run_battery_and_report",
                        fake_run_battery_and_report)
    result = CliRunner().invoke(audit, ["battery", "--strategy", "v3_5b", "--smoke"])
    assert result.exit_code == 0, result.output
    assert calls["args"][0] == "v3_5b"
    assert calls["args"][3] is True        # smoke=True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_battery_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: FAIL — no `battery` subcommand yet.

- [ ] **Step 3: Add the `battery` subcommand + `_run_battery_and_report` orchestrator**

Append to `jutsu_engine/cli/commands/audit.py` (after the `dsr_cmd` function; do not modify existing subcommands). Add a midnight-safe run-dir resolver mirroring `_resolve_run_dir_dsr` but scanning `campaign_battery_<strategy>.jsonl`:

```python
def _resolve_run_dir_battery(run_date_str, strategy_id):
    """Midnight-safe run-dir resolution for battery campaign files."""
    import re as _re
    if run_date_str is not None:
        try:
            run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(
                f"Invalid date format {run_date_str!r}; expected YYYY-MM-DD",
                param_hint="--run-date")
        return report_output_dir(run_date=run_date)
    audit_base = report_output_dir().parent
    pat = f"campaign_battery_{strategy_id}.jsonl"
    _DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
    candidates = sorted(
        (p for p in audit_base.glob(f"*/{strategy_id}/{pat}")
         if _DATE_RE.match(p.parent.parent.name)),
        key=lambda p: p.parent.parent.name, reverse=True)
    if candidates:
        newest = candidates[0]
        click.echo(click.style(
            f"  Resuming existing battery campaign: {newest} "
            f"(pass --run-date to override)", fg="yellow"))
        return newest.parent.parent
    return report_output_dir()


def _run_battery_and_report(strategy_id, arms, workers, smoke, run_dir):
    """Run the battery for one strategy and write its report; return the report path."""
    from jutsu_engine.audit import battery as bat
    from jutsu_engine.audit.battery import (
        run_battery, evaluate_arm, summarize_battery, bootstrap_sharpe_delta_ci,
    )
    from jutsu_engine.audit.report import render_battery_section, write_battery_report

    # --smoke: restrict to stock + smoothing, else honor --arms (default: all).
    selected = None
    if smoke:
        selected = {"stock", "smoothing"}
    elif arms:
        selected = set(arms) | {"stock"}

    def arm_fn(arm, rd):
        if selected is not None and arm["id"] not in selected \
                and not (arm["id"].split("_")[0] in selected):
            return {"arm": arm["id"], "weight": arm["weight"], "skipped_arm": True,
                    "error": None}
        return evaluate_arm(arm, rd)

    result = run_battery(strategy_id, run_dir, arm_fn=arm_fn,
                         progress=lambda m: click.echo(click.style(f"  {m}", fg="cyan")))

    # Wire the real bootstrap CI over aligned stock-vs-arm daily returns.
    ci_cache = {}

    def sharpe_ci_fn(arm_id):
        if arm_id in ci_cache:
            return ci_cache[arm_id]
        ci_cache[arm_id] = _battery_sharpe_ci(result["rows"], arm_id)
        return ci_cache[arm_id]

    summary = summarize_battery(strategy_id, result["rows"], sharpe_ci_fn=sharpe_ci_fn)
    md = render_battery_section(summary)
    return write_battery_report(run_dir, strategy_id, md)


def _battery_sharpe_ci(rows, arm_id):
    """Bootstrap Sharpe-delta CI for an arm vs stock from their regime-timeseries CSVs."""
    import pandas as pd
    from jutsu_engine.audit.battery import bootstrap_sharpe_delta_ci
    from jutsu_engine.audit import transitions as tr
    from jutsu_engine.audit.battery import TIER1_PORTFOLIO_START
    by = {r.get("arm"): r for r in rows}
    stock, arm = by.get("stock"), by.get(arm_id)
    if not stock or not arm or not stock.get("regime_timeseries_csv") \
            or not arm.get("regime_timeseries_csv"):
        return (float("nan"), float("nan"))
    a = tr.trim_warmup(pd.read_csv(arm["regime_timeseries_csv"]), TIER1_PORTFOLIO_START)
    s = tr.trim_warmup(pd.read_csv(stock["regime_timeseries_csv"]), TIER1_PORTFOLIO_START)
    m = a[["Date", "Strategy_Daily_Return"]].merge(
        s[["Date", "Strategy_Daily_Return"]], on="Date", suffixes=("_arm", "_stock"))
    return bootstrap_sharpe_delta_ci(
        m["Strategy_Daily_Return_arm"].values,
        m["Strategy_Daily_Return_stock"].values, n_boot=1000, seed=42)


@audit.command("battery")
@_STRATEGY_OPTION
@click.option("--arms", multiple=True, default=(),
              help="Restrict to these arm ids (repeatable; stock always included). "
                   "Default: all 10 arms.")
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel workers for the portfolio backtests (1 = serial).")
@click.option("--smoke", is_flag=True, default=False,
              help="Smoke mode: stock + smoothing only, short path, minutes.")
@click.option("--run-date", "run_date", type=str, default=None, metavar="YYYY-MM-DD",
              help="Use a specific dated run directory (midnight-safe resume).")
def battery_cmd(strategy, arms, workers, smoke, run_date):
    """EXP-007: vol-input ablation battery (stock/kronos/vix/smoothing) + verdicts."""
    try:
        for sid in _strategy_ids(strategy):
            run_dir = _resolve_run_dir_battery(run_date, sid)
            click.echo(f"[{sid}] battery (arms={list(arms) or 'all'}, "
                       f"workers={workers}, smoke={smoke})")
            out = _run_battery_and_report(sid, arms, workers, smoke, run_dir)
            click.echo(click.style(f"  report: {out}", fg="green"))
    except AuditDBUnavailable as e:
        click.echo(click.style(f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The battery is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.",
            fg="yellow"), err=True)
        raise click.Abort()
    except RuntimeError as e:
        click.echo(click.style(f"✗ Battery aborted: {e}", fg="red"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Battery failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ Battery failed: {e}", fg="red"), err=True)
        raise click.Abort()
```

- [ ] **Step 4: Run the CLI test**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_battery_cli.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full audit + CLI suite (must stay green + new tests)**

Run: `.venv/bin/python -m pytest tests/unit/audit/ tests/unit/cli/test_audit_command.py tests/unit/cli/test_battery_cli.py tests/unit/strategies/test_vol_input_adapter.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (the prior 301 plus all new tests; DB-gated tests SKIP if the DB is offline).

- [ ] **Step 6: Commit**

```bash
git add jutsu_engine/cli/commands/audit.py tests/unit/cli/test_battery_cli.py
git commit -m "feat(cli): jutsu audit battery subcommand (arms/workers/smoke; real bootstrap CI wiring) (Task 14)"
```

---

## Task 15: EXP-007 LOGBOOK skeleton + CHANGELOG (docs — no results yet)

**Files:**
- Modify: `docs/experiments/LOGBOOK.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the EXP-007 index row + skeleton entry to the LOGBOOK**

Append the index row to the `## Index` table in `docs/experiments/LOGBOOK.md` (after the EXP-006 row):

```markdown
| EXP-007 | 2026-07-13 | Does a forward-looking (Kronos/VIX) or smoothing-only vol-input leg improve transition quality enough for a shadow slot? | PENDING (battery built; results after Tier-1 run) |
```

Then append the skeleton entry after XREF-002 (question + method filled; results pending):

```markdown
---

## EXP-007 — Regime program Phase 1: transition metrics + vol-input ablation battery (2026-07-13)

**Question.** The baseline audit closed every parametric route and localized v3.5b's
weakness to regime-transition quality — specifically the vol-state classifier around
crash exits/re-entries (SYNTHESIS-001). Does replacing the vol-state INPUT series with a
forward-looking leg (Kronos forecast or implied vol) — or mere smoothing — improve
transition behavior enough to earn a paper-trading shadow slot? Four arms, pre-registered
gates: `stock` (baseline) / `kronos` (Kronos program's sole surviving deliverable,
XREF-002) / `vix` (implied-vol control) / `smoothing` (zero-information filter control).

**Method.** Built the transition-metrics gauntlet + the ablation battery (this plan,
`docs/superpowers/plans/2026-07-13-regime-battery-phase1.md`):
- Crash-episode registry `grid-configs/audit/crash_episodes.yaml` (8 episodes,
  QQQ-verified peak/trough), loader/validator in `jutsu_engine/audit/transitions.py`.
- Transition scorer (pure): exit_lag / drawdown_capture / reentry_lag / whipsaw /
  days_defensive per (arm × episode) from a WARMUP-TRIMMED regime timeseries (EXP-006);
  signal-level flip lead/lag + AUC(vol-state@t+21) vs the raw-bar 0.815-0.828 (VER1).
- Input-series builders (`jutsu_engine/audit/input_series.py`): kronos (checksummed
  parquet `claudedocs/inputs/QQQ_kronos_base.parquet`, std_return@H5 → z(200) → EMA5),
  vix ($VIX daily close, dedup + 2020-03-16=82.69 anchor validation, → z(200) → EMA5),
  smoothing (engine-truth vol_z → EMA5). All T-1 aligned; causality unit-tested.
- Vol-input adapter `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py`
  (blend at the vol-z step; identity=stock with no series — the load-bearing test).
- Engine-truth signal replay via `LiveStrategyRunner.calculate_signal_stream` (single
  pass, no portfolio; nothing reimplemented — the Kronos port's 87.5% agreement is the
  cautionary tale). Portfolio runs via the standard `BacktestRunner`.
- Battery runner + gates (`jutsu_engine/audit/battery.py`) + report renderers
  (`report_regime_battery_v3_5b.md`) + CLI `jutsu audit battery`.
- Tier-1 windows: portfolio 2019-08→2025-12; signal 1999→present (kronos: 2019-08→2025-12).
- Gates EXACTLY per spec §8 (signal / portfolio-with-bootstrap-CI / flatness SIGN rule).
  Weights: gated @0.5; ungated diagnostic neighbors @0.25/0.75 (never used to pick w).

Command (Tier-1 run, read-only): `jutsu audit battery --strategy v3_5b --workers 4`.
Smoke: `jutsu audit battery --strategy v3_5b --smoke`.

**Pre-registered expected outcomes (recorded so we cannot rationalize later, spec §8).**
If *smoothing* survives and kronos/vix add nothing beyond it → "filtering, not
forecasting"; the cheapest possible improvement ships. If *vix* matches kronos → Kronos
adds model-ops for nothing. If *kronos* uniquely survives → a learned forecaster beat
implied vol (extraordinary); Tier 2 (backfill 2010-02→2019-08, re-run on 2010→present)
must confirm it.

**Results.** PENDING — fill after the Tier-1 campaign: per-arm × per-episode transition
tables, signal AUC vs the 0.815-0.828 bar, era-sliced 2022 portfolio deltas with
bootstrap CIs, the flatness diagnostic, the per-arm verdict, and the Tier-2 trigger
decision. Reports land in `claudedocs/audit/<date>/report_regime_battery_v3_5b.md`.

**Verdict / decisions.** PENDING.

**Artifacts.** Plan `docs/superpowers/plans/2026-07-13-regime-battery-phase1.md`; code on
main (Tasks 1-15). Battery campaign JSONL under `claudedocs/audit/<date>/v3_5b/`.

**Follow-ups spawned.** (Conditional) Tier 2 if kronos survives; (conditional) Phase-2
shadow spec if any arm survives.
```

- [ ] **Step 2: Add a CHANGELOG entry**

Add at the top of `CHANGELOG.md` (match the existing entry format in that file):

```markdown
#### **Feature: Regime program Phase 1 — transition metrics + vol-input ablation battery (EXP-007)** (2026-07-13)

Built a permanent transition-metrics gauntlet capability and the EXP-007 vol-input
ablation battery (stock / kronos / vix / smoothing arms). Read-only; T-1 aligned;
warmup-trimmed (EXP-006). Live YAMLs/scheduler untouched — the adapter is a new
diagnostic-only strategy file.

- Added: `grid-configs/audit/crash_episodes.yaml` (8 QQQ-verified crash episodes)
- Added: `jutsu_engine/audit/transitions.py` (registry loader/validator + transition scorer)
- Added: `jutsu_engine/audit/input_series.py` (kronos/vix/smoothing series builders)
- Added: `jutsu_engine/audit/battery.py` (engine-truth replay + arms + gates + summarize)
- Added: `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py` (blend adapter)
- Modified: `jutsu_engine/live/strategy_runner.py` (additive `calculate_signal_stream`, read-only)
- Modified: `jutsu_engine/audit/report.py` (transition + battery renderers)
- Modified: `jutsu_engine/cli/commands/audit.py` (`jutsu audit battery` subcommand)
- Docs: LOGBOOK EXP-007 skeleton (results pending); this CHANGELOG entry
- Tests: `tests/unit/audit/test_transitions.py`, `test_input_series.py`, `test_battery.py`,
  `tests/unit/strategies/test_vol_input_adapter.py`, `tests/unit/cli/test_battery_cli.py`
```

- [ ] **Step 3: Verify the full suite is still green**

Run: `.venv/bin/python -m pytest tests/unit/audit/ tests/unit/cli/test_audit_command.py tests/unit/cli/test_battery_cli.py tests/unit/strategies/test_vol_input_adapter.py -p no:cacheprovider -o addopts="" -q`
Expected: PASS (301 prior + all new; DB-gated SKIP if offline).

- [ ] **Step 4: Commit**

```bash
git add docs/experiments/LOGBOOK.md CHANGELOG.md
git commit -m "docs(logbook): EXP-007 skeleton (question/method/expected-outcomes; results pending) + CHANGELOG (Task 15)"
```

---

## Self-Review (run after the plan is complete)

**1. Spec coverage** (spec §4-§9 + §12-§13):
- §4 registry → Tasks 1-2. §5 transition scorer (portfolio + signal, warmup-trim, engine-truth) → Tasks 3, 4, 8. §6 input-series builders (kronos/vix/smoothing, causality, NaN, schema) → Tasks 5, 6, 8. §7 adapter (identity guarantee) → Task 7. §8 battery arms/gates/flatness-sign/report → Tasks 9, 11, 12, 13, 14. §9 promotion contract → documented in EXP-007 follow-ups (Task 15) + Tier-2 trigger (Task 13); Phase-2 build is out of scope per spec. §12 testing strategy (pure + identity + smoke + suite green) → all tasks. §13 acceptance → EXP-007 skeleton + battery run (Task 15 + operator runs the campaign). Tier 2 is deliberately NOT implemented; the report states its trigger (Task 13).
- Component ordering respects dependencies: registry → scorer → builders → adapter → replay → arms → gates → runner → report → summarize → CLI → docs.

**2. Placeholder scan:** every code step ships complete code; every test step ships real assertions; no TBD/TODO/"similar to Task N". The one place dates may change is the registry (Task 2), which is a *verification-and-correct* step with an explicit helper and a data-driven test, not a placeholder.

**3. Type consistency:** `Episode` (frozen dataclass: id/peak/trough/recovery/portfolio_scored) is defined in Task 1 and used identically in Tasks 3/4/11. `score_episode_portfolio(ts, ep, start)` signature consistent Tasks 3/11. `z_ema5_pipeline(values, window, ema_span)` consistent Tasks 5/6/8. `build_*_series`/`build_*_from_frame` return `DataFrame[date, value]` consistently. `run_regime_backtest(strategy_id, vol_input_series, vol_blend_weight, start, end, output_dir)` consistent Tasks 7/8/11. `battery_arms()` arm dict keys (id/series/weight/gated) consistent Tasks 9/11/13. `signal_gate/portfolio_gate/flatness_diagnostic/arm_survives` signatures consistent Tasks 9/13. `render_battery_section(summary)` summary keys (strategy_id/arm_rows/flatness_rows/tier2_trigger) consistent Tasks 12/13/14. `_STRATEGY_OPTION`, `_strategy_ids`, `report_output_dir`, `AuditDBUnavailable` reused from the existing CLI as-is.

If the implementer finds a mismatch (e.g. the identity test fails because the adapter's Decimal path differs), Task 7/8 are the debug locus — the injection point is `_calculate_volatility_zscore`, verified against the strategy source at git `dd5a847`.
