# Baseline Audit / Robustness Gauntlet v1 — Design

**Date:** 2026-07-06
**Status:** Draft for review
**Scope:** Hierarchical_Adaptive_v3_5b + v3_5d (both live strategies)

---

## 1. Summary

A re-runnable audit pipeline that establishes the honest, out-of-sample performance
baseline for the two live strategies, quantifies how much of the golden config's
reported Sharpe (~2.79) survives selection-bias correction, and verifies that the
live deployment actually produces the signals the backtest validated.

The audit doubles as **Gauntlet v1**: the deterministic fitness function that any
future automated strategy-research loop must score candidates against. Building the
measurement layer first de-risks every later improvement project (adaptive
parameters, AI regime classification, new sleeves).

## 2. Goals

1. Produce a stitched walk-forward OOS equity curve per strategy → the honest
   baseline Sharpe / CAGR / MaxDD / alpha vs QQQ.
2. Measure golden-config parameter stability across WFO windows → answers whether
   adaptive parameter tuning could add value at all.
3. Correct the headline Sharpe for selection bias (Deflated Sharpe Ratio, PBO).
4. Attribute performance by era and by regime cell → shows whether the edge is
   concentrated in one lucky period and whether the defensive cells pay for
   themselves.
5. Reconcile live scheduler behavior (Dec 2025 → present) against a backtest replay
   of the same period → quantifies the live/backtest fidelity gap (open z-score
   discrepancy).

### Non-goals

- No changes to live strategy configs or trading behavior.
- No new strategies, signals, or regime-classifier changes.
- No agent/LLM components — this layer is deterministic by design.
- No UI/dashboard work; output is markdown reports + charts.

## 3. Context

- Golden config was selected by a ~243-run grid search (`grid-configs/Gold-Configs/
  grid_search_hierarchical_adaptive_v3_5b.yaml`), on top of earlier v2.5/v2.6/v2.8
  search phases — cumulative trials number in the thousands. Reported metrics
  (Sharpe 2.79, MaxDD -18.4%) are therefore in-sample-selected and optimistic by
  construction.
- WFO infrastructure exists and is maintained: `jutsu wfo` → `WFORunner`
  (`jutsu_engine/application/wfo_runner.py`), composing `GridSearchRunner`,
  `BacktestRunner`, `PerformanceAnalyzer`. The older
  `jutsu_engine/optimization/walk_forward.py` averages per-window Sharpe ratios in
  `_aggregate_results()` — a methodological weakness this audit does not inherit
  (metrics are computed on the stitched OOS curve instead).
- An unresolved live/backtest discrepancy exists: three systems produced three
  different z-scores for 2026-02-04 (-0.14 independent / -0.32 scheduler / -0.50
  backtest). `scripts/verify_indicators.py` and `JUTSU_ZSCORE_DEBUG=1` logging
  already exist as investigation tools.
- Known data gotchas that Module 5 must respect: regime fields are
  scheduler-authoritative only (`snapshot_source` separation, 2026-01-14 decision);
  `market_data` daily bars are 1-day date-shifted, so equity comparisons must use
  real closes.

## 4. Reuse policy (explicit)

**All backtests, grid searches, and WFO runs go through existing infrastructure.**
The audit package adds only analysis on top.

| Capability | Existing component (reused) | New code |
|---|---|---|
| Single backtest | `BacktestRunner` | — |
| Grid search | `GridSearchRunner` | — |
| Walk-forward windows | `WFORunner` (`jutsu wfo`) | — |
| Performance metrics | `PerformanceAnalyzer` | — |
| Parallel execution | `jutsu_engine/optimization/parallel.py` | — |
| Trial-count history | `optimization_results` table | — |
| Live signal verification | `scripts/verify_indicators.py` | — |
| Stitched OOS aggregation | — | `audit/wfo_stability.py` |
| Perturbation driver | — | `audit/plateau.py` |
| DSR / PBO math | — | `audit/selection_bias.py` |
| Era/cell attribution | — | `audit/attribution.py` |
| Live reconciliation | — | `audit/live_recon.py` |
| Report generation | plotting via existing visualizer patterns | `audit/report.py` |

Two bounded extensions to existing components are permitted if needed (see §11):
persisting per-window OOS daily equity from `WFORunner`, and an optional flag on
`GridSearchRunner` to persist per-combination daily return series.

## 5. Module 1 — WFO parameter-stability study

**Method**
- Strategies: v3_5b and v3_5d, each with its live config as the anchor.
- Period: 2010-02-01 → present (TQQQ inception bounds the start).
- Window scheme (matches the established v5.1 WFO convention): 2.5y in-sample /
  0.5y out-of-sample, 0.5y slide → ~26 windows.
- Per-window parameter grid: the regime-boundary core of the golden grid
  (z-score thresholds, SMA periods, t_norm thresholds, vol-crush) — target ≤ ~81
  combinations per window so a full run completes overnight with `parallel.py`.
  Allocation parameters stay fixed at golden values.

**Outputs**
1. **Stitched OOS equity curve**: concatenate all OOS window daily returns into one
   series; compute Sharpe, CAGR, MaxDD, alpha vs QQQ buy-hold and TQQQ buy-hold on
   the stitched series. This is the audit's headline number.
2. **Parameter-drift table**: winning parameter set per window; per parameter, the
   distribution of winning values across windows; fraction of windows where the
   golden value is in the top decile of that window's grid.

**Interpretation contract**
- Golden params in top decile in ≥80% of windows → parameters stable; adaptive
  tuning is unnecessary by construction.
- <50% of windows → parameters unstable; the golden config is fragile and adaptive
  tuning would chase noise. Either way the adaptive-parameters question is settled
  empirically.

## 6. Module 2 — Parameter plateau map

**Method**
- Anchor: golden config, full period, both strategies.
- One-at-a-time perturbations: each active numeric parameter at ±10% and ±20%
  (integer parameters rounded, ordinal parameters stepped to neighbors).
- Joint perturbations: ~200 uniform random samples inside a ±15% box around the
  golden config (seeded RNG for reproducibility).
- Each sample = one full-period backtest via `BacktestRunner`.

**Outputs**
- Per-parameter degradation curve (Sharpe and MAR vs perturbation size).
- Plateau score per parameter: mean retained Sharpe fraction at ±20%.
- Cliff list: parameters where a ±10% move loses >30% of Sharpe — the places most
  likely fit to noise.
- Joint-perturbation distribution: histogram of Sharpe across the 200 samples;
  golden config's percentile within it (a golden config far in the right tail of
  its own neighborhood is a red flag).

## 7. Module 3 — Selection-bias correction

**Method**
- **Deflated Sharpe Ratio** (Bailey & López de Prado): compute for the golden
  config's full-period backtest. Trial count N pulled from the
  `optimization_results` table plus documented grid-config run counts; where
  history is incomplete, use a conservative (higher) estimate and report the
  sensitivity of DSR to N (e.g., N = 243 / 1,000 / 5,000).
- **PBO** via combinatorially symmetric cross-validation (CSCV, S=16 blocks) over
  the per-combination daily return series of the 243-run golden grid. If historical
  runs did not persist per-combo daily returns, re-run the golden grid once with
  the persistence flag (§11) to capture them.

**Outputs**
- DSR with confidence level, per strategy.
- PBO probability.
- Plain-language verdict in the report: e.g. "after accounting for ~N trials, the
  probability that the observed Sharpe is indistinguishable from zero-skill
  selection is X%."

## 8. Module 4 — Era and cell attribution

**Method**
- Full-period golden-config backtest per strategy (single run, reused for both
  analyses).
- Era slices: 2010–2014, 2015–2019, 2020 (COVID), 2021, 2022 bear, 2023–2024 bull,
  2025–present. Per era: return, Sharpe, MaxDD, alpha vs QQQ.
- Cell attribution: daily P&L bucketed by the active cell (1–6); per cell: total
  contribution, hit rate, contribution of the Treasury overlay specifically
  (TMF/TMV P&L in cells 4–6) vs a cash-only counterfactual for the same days.

**Outputs**
- Era table + cumulative-alpha-by-era chart.
- Cell contribution table; explicit answer to "do cells 4–6 + Treasury overlay add
  net value after their whipsaw costs, and in which eras?"

## 9. Module 5 — Live reconciliation (Dec 2025 → present)

**Method**
- Replay each strategy through the backtest engine over the live period using the
  exact live configs (`config/strategies/v3_5b.yaml`, `v3_5d.yaml`) and warmup data
  fetched the same way the live runner fetches it (`LiveStrategyRunner` conventions,
  per `scripts/backfill_regime.py`).
- Compare day-by-day against `performance_snapshots` rows where
  `snapshot_source` is scheduler-authoritative: `strategy_cell`, `trend_state`,
  `vol_state`, and (where stored) `t_norm` / `z_score`; equity compared using real
  closes (not date-shifted `market_data` values).
- Categorize each mismatch: data difference (different bars seen), timing
  difference (intraday quote vs EOD bar — expected for z_score/t_norm), or logic
  difference (same inputs, different output — a bug).

**Outputs**
- Mismatch counts by field and category; day-level diff table.
- P&L divergence between live equity and replayed equity over the same period.
- Closure (or a precise root-cause statement) for the 2026-02-04 z-score
  discrepancy investigation.

## 10. Package structure, CLI, reporting

```
jutsu_engine/audit/
    __init__.py
    wfo_stability.py      # Module 1 (drives WFORunner, stitches OOS, drift table)
    plateau.py            # Module 2
    selection_bias.py     # Module 3 (DSR, PBO/CSCV)
    attribution.py        # Module 4
    live_recon.py         # Module 5
    report.py             # markdown + charts assembly
jutsu_engine/cli/commands/audit.py   # `jutsu audit <module>|all --strategy ... --config ...`
tests/unit/audit/                    # unit tests per module (math on synthetic series)
grid-configs/audit/                  # WFO + grid configs used by the audit (versioned)
```

- Reports written to `claudedocs/audit/<YYYY-MM-DD>/report_<strategy>.md` with
  charts alongside; every report embeds the exact configs, git SHA, data range, and
  seeds used, so any number is reproducible.
- Statistical helpers (DSR, PBO, stitching) are pure functions over return series —
  unit-testable without a database and reusable later as the agent-loop fitness
  function.

**Decision thresholds (printed in every report)**

| Signal | Threshold | Consequence |
|---|---|---|
| Golden params top-decile share across WFO windows | <50% | Parameters unstable → no adaptive tuning; treat config as fragile |
| DSR confidence | <95% | Edge statistically unproven → prioritize accumulating live record over further tuning |
| PBO | >50% | Same as above |
| Live regime mismatch days | >5% | Fidelity fixes become P0 before any strategy changes |
| Cliff parameters (Module 2) | any | Flag for robustness work before further optimization of those parameters |

## 11. Bounded implementation decisions

Resolved during implementation, without expanding scope:

1. **WFO output plumbing**: if `WFORunner` does not already persist per-window OOS
   daily equity series, add an opt-in output (no behavior change to existing runs).
2. **Per-combo return persistence**: add an optional flag to `GridSearchRunner` to
   write each combination's daily return series (needed once, for PBO).
3. **Grid trimming**: the exact ≤81-combo regime-boundary subset is chosen from the
   golden grid config at implementation time and versioned in
   `grid-configs/audit/`.

## 12. Risks and mitigations

- **Compute time** (~26 windows × ≤81 combos × 2 strategies ≈ ≤4,200 backtests):
  trimmed grid, `parallel.py`, overnight runs; modules are independently runnable
  so partial results land early (Module 5 and Module 4 are cheap; Module 1 is the
  long pole).
- **Missing per-combo history** for PBO: one-time grid re-run (already budgeted).
- **Environment**: local venvs are known-dead; run under a rebuilt `uv` Python 3.11
  environment.
- **Warmup correctness**: strategies need 150+ bars of warmup; audit runs reuse the
  engine's existing warmup handling (grid-search warmup bugs were fixed 2026-02-04;
  the audit inherits those fixes by reusing the runners).

## 13. Acceptance criteria

The audit is complete when, for each of v3_5b and v3_5d, a single report answers:

1. What is the stitched walk-forward OOS Sharpe / CAGR / MaxDD, and how does it
   compare to QQQ and to the in-sample golden numbers?
2. Are the golden parameters stable across time windows (top-decile share)?
3. What are DSR and PBO, i.e., how likely is the edge real given trials performed?
4. Which eras and which cells produce the edge; does the defensive machinery pay?
5. How faithfully does the live deployment reproduce backtest signals, with the
   z-score discrepancy either closed or root-caused?

All five modules re-runnable via `jutsu audit`, unit tests passing.

## 14. Next steps

**Immediate (this project)**

1. User reviews this spec; revisions folded in.
2. Write the implementation plan (phased; suggested build order below).
3. Implement and run the audit; publish reports to `claudedocs/audit/`.

**Suggested build order** (cheap answers first, long pole last):

| Phase | Module | Why this order |
|---|---|---|
| 1 | Module 5 (live recon) | Cheapest, highest urgency: closes the z-score discrepancy and validates the engine every other module depends on |
| 2 | Module 4 (attribution) | One backtest per strategy; immediately informative about where the edge lives |
| 3 | Module 2 (plateau map) | Moderate compute; independent of WFO plumbing |
| 4 | Module 1 (WFO stability) | Long pole (overnight runs); needs the §11 output plumbing |
| 5 | Module 3 (DSR/PBO) | Depends on per-combo return persistence (§11) and trial-count inventory |

**After the audit (decision gates, in priority order)**

The audit's results select the next project — this ordering was agreed during
brainstorming (2026-07-06):

1. **If live fidelity fails** (>5% mismatch days): fix the live/backtest signal
   pipeline before any strategy work. Nothing else is trustworthy until then.
2. **If DSR/PBO says the edge is unproven**: pause tuning; accumulate live track
   record and consider whether position sizing should reflect the weaker evidence.
3. **Regime-classifier upgrades** (the more promising improvement axis): add
   confirming inputs ablation-style (VIX term structure, credit spreads, breadth),
   prioritized by Module 4's finding of where cells lose money; optionally
   probabilistic regime confidence for position sizing. Every candidate must pass
   this gauntlet.
4. **Agent research loop (Version B)**: automate hypothesis → implement → gauntlet
   → human-review using this audit pipeline as the fitness function. Explicitly
   NOT an agent that adapts live parameters to recent data (Version A) — Module 1's
   parameter-drift table provides the empirical justification either way.
5. **Longer term**: additional uncorrelated sleeves (new signals/assets) as the
   realistic route to materially higher compounding at fixed risk — parameter
   tuning alone cannot deliver step-change returns.
