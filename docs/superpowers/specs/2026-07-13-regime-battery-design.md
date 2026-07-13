# Regime Program Phase 1 — Transition Metrics + Vol-Input Ablation Battery

**Date:** 2026-07-13
**Status:** Draft for review
**Predecessors:** Baseline audit (all five modules complete — spec
`2026-07-06-baseline-audit-design.md`, results in `docs/experiments/LOGBOOK.md`
EXP-001..006 + SYNTHESIS-001), Kronos program handoff
(`~/dev/kronos-research/jutsu-kronos-research/docs/2026-07-08-kronos-vol-input-handoff.md`,
accepted in LOGBOOK XREF-002).

---

## 1. Summary

The audit closed every parametric improvement route and localized v3.5b's weakness
to regime-transition quality — specifically the volatility-state classifier's
behavior around crash exits and re-entries (LOGBOOK SYNTHESIS-001). This phase
builds the measurement layer for transitions and runs the first structural
experiment: a four-arm ablation of the vol-state INPUT series, testing whether a
forward-looking leg (Kronos forecast or implied vol) — or mere smoothing —
improves transition behavior enough to earn a paper-trading slot.

The experiment is logged as **EXP-007**.

## 2. Goals

1. **Transition metrics as a permanent gauntlet capability**: per-crash-episode
   exit lag, drawdown capture, re-entry lag, and whipsaw, computed from engine
   outputs against a versioned episode registry.
2. **A decisive verdict per arm** of the vol-input battery, with pre-registered
   gates: `stock` (baseline) / `kronos` (ema5_blend, the Kronos program's sole
   surviving deliverable) / `vix` (implied-vol control) / `smoothing`
   (zero-information filter control).
3. **A weight-robustness diagnostic** (not a weight optimization) around the
   pre-registered blend weight.
4. **A promotion contract**: what a winner earns (shadow configuration spec,
   Phase 2) — backtests nominate; only live-parallel evidence promotes.

### Non-goals

- No shadow-mode/scheduler implementation (Phase 2, only if there is a winner).
- No probabilistic regime sizing; no breadth/credit-spread candidates; no VIX3M
  term structure (no data); no fine-tuned Kronos artifacts (their I7 verdict: RED).
- No changes to the live v3.5b/v3.5d configs or live code paths.
- No parameter sweeps beyond the specified diagnostic (audit verdicts: EXP-003/004/005).

## 3. Decisions locked during brainstorm (2026-07-13)

| Decision | Choice |
|---|---|
| Scope | Phase 1 = transition metrics + 4-arm battery (classifier roadmap deferred) |
| Windows | Tiered: common Kronos window first; Kronos backfill only if it survives Tier 1 |
| Adoption path | Paper-trading (shadow) promotion — no direct live-config change from backtests |
| Injection | Precomputed-series adapter (one strategy subclass; arms differ only by data) |
| Blend weight | Frozen at the pre-registered 0.5 for gating; ±0.25 neighbors run as an ungated flatness diagnostic |

## 4. Component 1 — Crash-episode registry

`grid-configs/audit/crash_episodes.yaml` (versioned, human-curated; never inferred
silently from data). One entry per episode:

```yaml
episodes:
  - id: dotcom            # 2000-03 .. 2002-10
    peak: 2000-03-27      # QQQ closing peak
    trough: 2002-10-09
    recovery: 2015-01-13  # first close above peak (documentation only)
    qqq_peak_to_trough: -0.83
  - id: gfc               # 2007-10 .. 2009-03
  - id: euro2011
  - id: china2015         # 2015-08 .. 2016-02
  - id: q4_2018
  - id: covid2020
  - id: bear2022
  - id: spring2025
```

Exact dates are filled at implementation time from QQQ closes in `market_data`
(peak = highest close preceding the drawdown, trough = lowest close; both
verified by a unit test against the stored series and reviewed by a human before
commit). Pre-2010 episodes (dotcom, gfc) apply to signal-level scoring only.

## 5. Component 2 — Transition scorer

New module `jutsu_engine/audit/transitions.py` (pure functions, DB-free tested):

Inputs: a regime timeseries (engine-emitted; **warmup-trimmed to the backtest
span per EXP-006** before any computation), QQQ closes, and the episode registry.

Per (arm × episode), portfolio-level (2010+ episodes):
- **exit_lag_days**: trading days from `peak` until the strategy first enters a
  defensive cell (4, 5 or 6). Negative if it de-risked before the peak.
- **drawdown_capture**: strategy max drawdown within [peak, trough] ÷ QQQ max
  drawdown within the same span (lower is better; 1.0 = no protection).
- **reentry_lag_days**: trading days from `trough` until the strategy first
  re-enters an offensive cell (1, 2 or 3).
- **whipsaw_flips**: vol-state flips within [peak, recovery-capped-at-+120d].
- **days_defensive**: days in cells 4-6 within [peak, trough].

Signal-level (all episodes, 1999→present for arms that do not require Kronos
data): vol-state flip lead/lag around each episode's peak, flip-count ratio vs
stock, and AUC of the blended input series for vol-state@t+21 — the raw
`vol_zscore` bar is **0.815–0.828** (Kronos program VER1; alignment-dependent).

**Engine-truth requirement:** signal-level series must be produced by the
engine's own code path — a single-pass replay that instantiates the real
strategy class and feeds bars chronologically (the mechanism is the plan's
choice: `calculate_signals`-style replay or a signal-only backtest run), never a
reimplementation of the classifier (the Kronos port's 87.5% engine agreement is
the cautionary tale).

Report rendering: a per-episode table section added to `report.py`, reusable by
every future gauntlet report.

## 6. Component 3 — Input-series builders

One builder per non-stock arm → identical CSV schema
(`date, value, source, constructed_at` with provenance in a header comment).
All windows trailing-only (causal); all series **T-1 aligned**: the value used
for day D's decision derives exclusively from information available at D−1's
close (for Kronos, the parquet row stamped D−1; for VIX, the close of D−1; for
smoothing, vol_z through D−1).

1. **kronos**: from `~/dev/kronos-research/jutsu-kronos-research/artifacts/forecasts/exp1/QQQ_kronos_base.parquet`
   (NOT the i7ft file): `std_return_5` at horizon 5 → z vs trailing 200 rows
   (min_periods 200) → `ewm(span=5, adjust=False)`. Coverage 2019-08→2025-12.
   The parquet is copied into this repo's `claudedocs/` inputs area with a
   recorded checksum (their repo is not a dependency of ours).
2. **vix**: `$VIX` daily close from `market_data` → identical z(200) → EMA5
   pipeline. Prerequisite: one `jutsu sync` of `$VIX` (stale since 2026-02-03).
3. **smoothing**: the production vol z-series itself → EMA5 (no external
   information). Note: the production vol z is computed by the engine at run
   time; this builder replays it via the same engine-truth mechanism as
   Component 2 and emits the smoothed copy.

Unit tests: causality (a builder given data truncated at date X produces
identical values ≤ X), NaN policy (leading warmup NaNs preserved, not filled),
schema.

## 7. Component 4 — Vol-input strategy adapter

`jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py`, subclassing
v3.5b with two new optional constructor params:

- `vol_input_series: str | None = None` — path to a builder CSV.
- `vol_blend_weight: Decimal = 0.5` — fixed by config, never optimized in-engine.

Behavior: at the vol-z step, `blended = (1−w)·vol_z + w·series[date]`; if the
series has no value for `date` (warmup, gap), fall back to pure `vol_z` (= stock
behavior). Hysteresis thresholds, all other logic, and all other parameters
remain untouched.

**Identity guarantee:** with `vol_input_series=None` the subclass must produce a
bit-identical regime stream to stock v3.5b over the full period — enforced by a
regression test (engine run comparison), which is the adapter's most important
test. Live YAMLs are not modified; the adapter is configured only by the battery
harness.

## 8. Component 5 — Battery runner, arms, and report

### Arms (Tier 1, common window 2019-08 → 2025-12; portfolio runs 2019-08+)

| Arm | Series | w | Gated? |
|---|---|---|---|
| stock | — | — | baseline |
| kronos | kronos CSV | 0.50 | **yes** |
| vix | vix CSV | 0.50 | **yes** |
| smoothing | smoothing CSV | 0.50 | **yes** |
| kronos ±, vix ±, smoothing ± | same CSVs | 0.25 / 0.75 | **no — diagnostic only** |

Ten portfolio backtests (v3_5b base; v3_5d variant deferred — the vol channel is
shared, one strategy decides the concept) + signal-level replays over
1999→present for stock/vix/smoothing and 2019-08→2025-12 for kronos. Campaign
runs reuse the audit checkpoint machinery (fsync JSONL, resume, breaker,
tempdirs) though the battery is small.

### Pre-registered gates (evaluated ONLY at w=0.5; no variant selection)

An arm **survives Tier 1** iff, vs stock:
1. **Signal gate:** improves episode exit lag or whipsaw ratio without dropping
   its input-series AUC below the raw-bar range (0.815–0.828) *when measured on
   the same alignment*; and
2. **Portfolio gate:** improves 2022-episode drawdown_capture or 2022 return,
   without degrading full-window Sharpe by more than noise (bootstrap CI
   overlapping zero counts as "no degradation"; a CI-excluding-zero degradation
   fails); and
3. **Flatness diagnostic:** the w=0.25/0.75 neighbors tell the same qualitative
   story — precisely: each gate-relevant delta vs stock (exit lag, whipsaw
   ratio, 2022 drawdown_capture) keeps the same SIGN at both neighbors as at
   0.5. A sign flip at either neighbor = fragile = **fail**, despite the 0.5
   result. Neighbors are never used to select a better w.

Expected-outcomes note (recorded so we cannot rationalize later): if *smoothing*
survives and kronos/vix add nothing beyond it, the finding is "filtering, not
forecasting" — the cheapest possible improvement ships. If *vix* matches kronos,
Kronos adds model-ops for nothing. If *kronos* uniquely survives, a learned
forecaster beat implied vol — extraordinary, and Tier 2 must confirm it.

### Tier 2 (only if the kronos arm survives Tier 1)

Backfill Kronos-base forecasts 2010-02→2019-08 (~2,400 trading days × 13s ≈ 9h
on the M4, batchable/resumable), rebuild the kronos CSV, re-run the battery on
2010→present for an equal-footing comparison including the 2011/2015/2018
episodes. Same gates.

### Report

`report_regime_battery_v3_5b.md`: per-arm × per-episode transition tables,
signal AUC table with the raw bar, era-sliced portfolio deltas (2022 decisive),
flatness diagnostic table, and a one-line verdict per arm. Every number carries
the T-1 convention note. Rendered via `report.py` conventions (`_fmt`, captions
outside tables).

## 9. Promotion contract (Phase 2 — specified now, built only on a win)

A surviving arm earns a **shadow configuration**: the adapter strategy with the
winning series runs in the scheduler alongside live v3.5b — signals computed and
logged daily to `performance_snapshots` under a distinct `strategy_id`
(e.g. `v3_5b_shadow_vix`), **zero capital** — for a pre-committed 2–3 month
window, after which live-parallel divergence data (via the existing live-recon
tooling) informs the capital decision. Prerequisite for the kronos arm: daily
inference ops (13s/day on the M4) and the shared backlog item (persist the
scheduler's decision-time bar). Phase 2 gets its own spec; nothing scheduler-side
is built in Phase 1.

## 10. Constraints (inherited, binding)

Strictly READ-ONLY vs the DB; engine-side evaluation only; T-1 information set
end-to-end; warmup-trim before any metric (EXP-006); no IS-ranking acceptance
(PBO 0.85); frozen recipes — any sweep beyond the specified diagnostic requires
DSR/PBO correction and is out of scope; explicit `git add <paths>`; DB-free unit
tests (pure functions + fakes; engine runs only in smoke/campaign); focused-test
command `.venv/bin/python -m pytest <path> -p no:cacheprovider -o addopts="" -q`;
one-line test docstrings; `pytest.raises(match=...)`.

## 11. Data prerequisites

1. `jutsu sync` for `$VIX` (2026-02-04 → present). Verify post-sync freshness.
2. Copy + checksum the Kronos parquet into this repo's inputs area.
3. QQQ/TLT already current; no other syncs required for Tier 1.

## 12. Testing strategy

- Pure layers (registry parsing, transition metrics, series builders, blend
  math) — synthetic-data unit tests, including causality tests.
- Adapter identity regression (subclass with no series ≡ stock v3.5b regime
  stream) — the one engine-level test that gates everything.
- Battery smoke: stock + one arm, one short window, end-to-end to a rendered
  report, minutes.
- Full audit suite must stay green (currently 301).

## 13. Acceptance criteria (Phase 1 done when)

1. Transition metrics render for all registry episodes on the stock arm
   (baseline transition profile of v3.5b — a deliverable in itself).
2. All four gated arms scored on Tier 1 with verdicts; flatness diagnostics
   reported; Tier 2 executed iff triggered.
3. LOGBOOK EXP-007 filled (results + verdict + follow-ups); CHANGELOG updated;
   reports in `claudedocs/audit/<date>/`.
4. A clear answer to: "does anything earn a shadow slot, and why?"

## 14. Next steps after this spec

User review → implementation plan (Opus planner) → subagent-driven execution →
Tier-1 campaign → EXP-007 verdict → (conditional) Tier 2 → (conditional)
Phase-2 shadow spec.
