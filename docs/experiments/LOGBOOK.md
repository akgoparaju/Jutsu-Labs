# Strategy Research Logbook

A chronological lab notebook for every experiment run against the live strategies
(v3_5b, v3_5d) and their successors. One entry per experiment. **Append-only;
never rewrite past entries** — if a conclusion turns out wrong, add a new entry
that corrects it and cross-reference both ways.

Each entry records: the **question** asked, the **method** (exact commands/configs
so it can be reproduced), the **numbers** found, the **verdict/decision** taken,
**artifacts** (reports, commits), and **follow-ups** spawned.

Context that predates this logbook: the strategy family evolved v2.x → v3.5b →
v3.5c/d → v4.0 → v5.0/5.1 through grid searches during Nov 2025–Jan 2026
(thousands of configurations; see `grid-configs/`, CHANGELOG, and Serena
memories). The v3.5b "golden config" came from a ~243-run grid
(`grid-configs/Gold-Configs/grid_search_hierarchical_adaptive_v3_5b.yaml`).
That history is why EXP-001 exists: selection over that many trials makes the
in-sample numbers optimistic by construction.

---

## Index

| ID | Date | Question | Verdict (one line) |
|----|------|----------|--------------------|
| EXP-001 | 2026-07-06 | What are the honest baseline numbers, and does live match backtest? | Full-period Sharpe ~0.8 (not 2.8); initial 8.6% fidelity alarm raised |
| EXP-002 | 2026-07-06 | Are the 8 logic-mismatch days a production bug? | No — audit artifact (information-set mismatch); true divergence 1.1% |
| EXP-003 | 2026-07-07 | How robust is the golden config to small parameter perturbations (plateau vs cliff)? | Plateau, no cliffs (both strategies); golden at 48th/57.5th pct of own neighborhood; vol-regime channel most sensitive |

---

## EXP-001 — Baseline audit Phase 1: live reconciliation + era/cell attribution (2026-07-06)

**Question.** (a) Does the live deployment faithfully reproduce the signals the
backtest engine produces from the same data? (b) What are the honest full-period
performance numbers of the live configs, sliced by era and regime cell — is the
edge concentrated, and does the defensive machinery pay for itself?

**Why.** The documented golden-config metrics (Sharpe ~2.8, MaxDD −18%) were
selected by grid search — in-sample by construction. Before any improvement work
(adaptive parameters, AI regime classification), we needed a trustworthy ruler.
Decision framework: spec `docs/superpowers/specs/2026-07-06-baseline-audit-design.md` §10.

**Method.** Built `jutsu_engine/audit/` (read-only analysis layer) + `jutsu audit` CLI.
- Module 5 (live recon): per-day fresh `LiveStrategyRunner` replay over `market_data`
  EOD bars (250-bar warmup, mirroring `scripts/backfill_regime.py`), diffed
  day-by-day against scheduler-authoritative `performance_snapshots`
  (`snapshot_source='scheduler'`). Diff categories: `logic` (categorical mismatch,
  zero tolerance), `timing` (z/t beyond ±0.25/±0.10 — intraday-vs-EOD noise),
  `data` (gaps/NaN). Window: 2025-12-01 → 2026-07-06.
- Module 4 (attribution): one full-period (2010-02 → 2026-07) `BacktestRunner`
  backtest per strategy using the exact live YAML (via `LiveStrategyRunner`'s
  param mapping); era metrics, per-cell P&L, episode-aware Treasury-sleeve estimate.
- Command: `jutsu audit all` (reports to `claudedocs/audit/2026-07-06/`).

**Results.**
- *Fidelity (initial):* v3_5b 93 scheduler days → 8 `logic` days (8.6%), 37 `timing`;
  v3_5d 118 days → 38.1% total mismatch. Both above the 5% gate → provisional P0.
  z/t timing drift systematic (~1/3 of days beyond tolerance) — the 2026-02-04
  z-score discrepancy is not a one-off.
- *Honest performance (live configs, 2010-02→2026-07):*
  | | Sharpe | MaxDD | Annualized | vs docs |
  |---|---|---|---|---|
  | v3_5b | 0.81 | −51.2% | +23.1% | docs claimed ~2.8 / −18% |
  | v3_5d | 0.79 | −51.4% | +22.8% | (2025-YTD, in-sample-selected) |
- *Era:* 2022 bear −46% vs QQQ −33% (defense failed in its target regime);
  2025-present alpha negative (v3_5b −14.0%, v3_5d −18.2%); COVID-2020 was the
  best era (alpha +70-80%, vol-crush override worked).
- *Cells (return-sum, additive):* Cell 1 (+3.01 over 1511d) and Cell 3 (+1.50)
  produce everything; **Cell 4 (−0.36/548d) and Cell 6 (−0.14/129d) are net losers**.
- *Not trusted:* Treasury $ figure (+$711k) — contradicts cell return-sums;
  position-value diffs are contaminated by rebalance flows. Fix queued (prev_qty×Δprice).
- *Anomaly:* 312-day "unknown"-era bucket with zero strategy return (warmup-dated
  rows) — benign, visible, unexplained in detail.

**Verdict / decisions.**
1. The golden config's documented numbers do not survive out-of-sample scrutiny —
   treat Sharpe ~0.8 / MaxDD ~−51% as the honest full-period baseline.
2. Improvement effort should target **regime-transition quality** (crash exit and
   re-entry; cells 4/6 behavior), not parameter micro-tuning.
3. The 8.6% fidelity alarm was escalated per the decision gate → EXP-002.

**Artifacts.** Reports `claudedocs/audit/2026-07-06/report_v3_5{b,d}.md`; code merged
to main (`feature/baseline-audit`, 19 commits, HEAD then `15d5e9e`); 50 unit tests.
Serena: `baseline_audit_phase1_implementation_2026-07-06`.
*Provenance note (added 2026-07-07): the recon sections of those report files were
regenerated after the EXP-002 information-set fix and now show the corrected 1.1%
fidelity numbers; the initial 8.6%-alarm figures are preserved only in this entry
(claudedocs is not under version control).*

**Follow-ups spawned.** EXP-002 (root-cause); treasury qty×Δprice isolation;
warmup-row "unknown"-era investigation; Modules 2 (plateau), 1 (WFO stability),
3 (DSR/PBO) per spec §14.

---

## EXP-002 — Root-cause of the 8 logic-mismatch days (2026-07-06)

**Question.** Are the 8 days where the live scheduler's regime (cell/trend/vol)
differs from the audit replay evidence of a production bug, a data change, or an
audit artifact?

**Hypotheses.** H1 information-set mismatch (replay sees day D's own EOD bar;
scheduler decides ~15 min after the open of D); H2 market_data rewritten after
the fact; H3 hysteresis path-dependence propagating one flipped day; H4 systematic
intraday-vs-EOD lag.

**Method.** Read-only forensic replay: re-ran the replay per mismatch day with
bars strictly before D (`load_bars(sym, D-1, 250)`) and compared against stored
scheduler values; audited `market_data.created_at` provenance for the March/April
bars; checked date clustering and threshold proximity. Full analysis:
`claudedocs/audit/2026-07-06/logic_mismatch_rootcause.md`.

**Results.**
- Replay@T-1 reproduced the scheduler **exactly on 5/8 days** (z to ~0.01):
  3/19, 3/26, 4/08, 4/30, 6/11. Cleanest case 3/26: replay@D z=1.012 crossed the
  1.0 High-vol threshold; replay@T-1 z=0.771 → cell 5/Low = stored.
- Residual 3 days (3/20, 3/23, 3/27) are interior selloff days that require the
  scheduler's decision-time intraday quote, which was never persisted.
- H2 refuted: bar `created_at` timestamps are contemporaneous, single-row, `src=schwab`.
- Mismatches were identical across both strategies → shared-input cause confirmed.
- **Bonus:** this fully explains the long-standing 2026-02-04 z-score discrepancy —
  the three conflicting z-scores (−0.14 / −0.32 / −0.50) were three different
  information sets (full-history EOD / intraday quote / 221-bar window), not bugs.

**Verdict / decisions.**
1. **Audit artifact — production scheduler is faithful.** No P0.
2. Fixed the replay: `make_replay_day` now loads bars strictly before D;
   categorical flips whose continuous driver differs within tolerance are
   reclassified `logic` → `timing` (threshold-crossing artifacts).
3. Re-measured fidelity: **v3_5b 1/93 logic days (1.1%), v3_5d 1/118 (0.8%)** —
   both under the 5% gate. The remaining day (3/27) is borderline (z diff 0.26 vs
   0.25 tolerance).

**Artifacts.** `claudedocs/audit/2026-07-06/logic_mismatch_rootcause.md`; fix merged
to main (`73b50df`); 54 unit tests. Serena:
`audit_p0_resolved_recon_information_set_fix_2026-07-06`.

**Follow-ups spawned.** Persist the scheduler's decision-time synthetic bar so
audits can replay the exact information set (residual diffs then = true bugs);
use T-1 semantics in future `backfill_regime.py` backfills.

**Lesson.** An audit can indict itself: before treating a fidelity alarm as a
production bug, prove the replay's information set matches the decision-maker's.
Also: tolerances defined for continuous fields must be honored when their
threshold-crossings surface as categorical flips, or the same noise gets counted
twice under two names.

---

## EXP-003 — Baseline audit Phase 2: parameter plateau map (2026-07-07)

**Question.** Does the golden config sit on a robustness *plateau* (small parameter
perturbations barely move Sharpe) or on a *cliff* (a +/-10% move on some parameter
collapses Sharpe)? Where in its own +/-15% neighborhood distribution does the
golden Sharpe sit — is it an isolated peak (right-tail = overfit red flag) or in
the body?

**Why.** EXP-001 established the honest full-period baseline (Sharpe ~0.8, not the
in-sample ~2.8) and pointed improvement effort at regime-transition quality over
parameter micro-tuning. Module 2 quantifies *how fragile* the golden parameters
are: cliff parameters are the ones most likely fit to noise and are flagged for
robustness work (spec §6, §10). Decision framework: spec
`docs/superpowers/specs/2026-07-06-baseline-audit-design.md` §6/§10.

**Method.** Built `jutsu_engine/audit/plateau.py` (perturbation-set generation +
checkpoint/resume campaign runner + pure analysis) and `jutsu audit plateau`.
- Perturbable params: 22 numeric non-bool strategy params from the live YAML
  (symbols/booleans/execution excluded), derived per strategy.
- One-at-a-time: each param at x0.8/x0.9/x1.1/x1.2 (integers rounded/deduped,
  windows >=5, periods >=2, negative thresholds keep sign); worst-side Sharpe
  retained (min of OAT pair) so plateau scores are conservative.
- Joint: 200 seeded uniform samples in a +/-15% box (seed 42, recorded in report).
- Each sample = one full-period (2010-02 -> 2026-07) `BacktestRunner` run via
  `build_overridden_strategy` (Phase-1 bridge + param overrides, same float->Decimal
  conventions as `LiveStrategyRunner`). Results checkpointed to JSONL (resume by
  params-hash); CSVs to a throwaway tempdir (reduced output).
- **Hardening (review-driven):** errored-run rows excluded from analysis with loud
  per-run counts logged; consecutive-error circuit breaker (default 10 consecutive
  errors aborts campaign, any success resets counter); fsync checkpoint writes
  (durable append before next sample starts); `--retry-errors` flag re-runs
  previously errored hashes on resume.
- Command (overnight): `jutsu audit plateau --strategy v3_5b --workers 4`
  then `--strategy v3_5d`. Smoke validation:
  `jutsu audit plateau --strategy v3_5b --oat-only --params sma_fast`.

**Results (v3_5b — 286 runs: golden + 86 OAT + 200 joint (some joint draws
collapse to duplicates and dedup by hash), 0 errored, campaign 2026-07-07
09:26→11:55 PT, workers=4).**
- **No cliff parameters.** Nothing loses >30% of Sharpe at ±10% (cliff list empty).
- **Golden Sharpe 0.8051 sits at the 48th percentile of its own ±15% joint
  neighborhood** (200 samples: min 0.578 / median 0.809 / max 0.991) — squarely in
  the body of the distribution, not an isolated peak. Grid-search selection did
  NOT overfit to a sharp parameter optimum.
- **The volatility-regime classification channel is the most sensitive subsystem.**
  Worst-side retention ranking (worst_retained at ±20%): `upper_thresh_z` 0.79
  (Sharpe 0.636 when 1.0→0.8 — the deadband narrows and High-vol triggers early),
  `realized_vol_window` 0.83, `vol_baseline_window` 0.89, `sma_slow` 0.92. The
  top four sensitivity slots are all regime-classification inputs.
- **Six knobs are inert** (retained ≈ 1.000 across ±20%): `process_noise_1`,
  `strength_smoothness`, `w_PSQ_max` (PSQ is disabled), `rebalance_threshold`,
  `leverage_scalar`, `lower_thresh_z` — dead dimensions in every past grid search.
- **Several single perturbations improve in-sample Sharpe modestly (+3–9%)** and
  some also cut MaxDD: `bond_sma_fast` 24 (Sharpe 0.857, MaxDD −0.42 vs golden
  −0.51), `bond_sma_slow` 66 (0.875), `osc_smoothness` 12 (0.852),
  `vol_crush_threshold` −0.12 (0.856). **Quarantined**: single full-period
  in-sample runs of this magnitude are within selection noise — adopting them
  would repeat the exact mistake EXP-001 exposed. They are candidates for
  Module-1 WFO validation only.
**Results (v3_5d — appended 2026-07-07 after the second campaign: 286 runs, 0
errored, ~12:05→14:59 PT, workers=4).** Same verdict as v3_5b:
- **No cliff parameters**; golden Sharpe 0.7872 at the **57.5th percentile** of
  its own ±15% neighborhood (200 samples: 0.583 / 0.770 / 0.966) — body, not peak.
- **Identical sensitivity ranking**: `upper_thresh_z` 0.77, `realized_vol_window`
  0.81, `vol_baseline_window` 0.88, `sma_slow` 0.91 — the same four
  vol-regime-classification inputs lead on both strategies, independently
  confirming the load-bearing-subsystem finding.
- Same bond-SMA/osc_smoothness in-sample improvements appear (bond_sma_fast
  worst_retained 1.026, i.e. both ±20% sides beat golden) — quarantined, as above.
- **Measurement gap:** `cell1_exit_confirmation_days` (v3_5d's distinguishing
  parameter, golden value 2) received ZERO OAT samples — every ±10/20%
  multiplicative step of an integer at 2 rounds back to 2. This is the known
  small-integer degeneracy of the multiplicative OAT scheme (flagged in review);
  measuring it needs explicit step values (1, 3), which the original v3_5d grid
  search already covered ([1..5]). Noted for any future small-integer parameter.

**Verdict / decisions.**
1. **The golden config is parameter-robust: a plateau, not a cliff.** In the
   parameter dimension, grid-search did not fit noise (48th percentile of its own
   neighborhood). The config's fragility, established in EXP-001, lives in the
   time dimension (era dependence), not the parameter dimension.
2. **Parameter tuning upside is small and bounded** — the best config in the
   entire ±15% neighborhood reaches Sharpe 0.99 vs golden 0.81, and that gap is
   partly noise. Confirms EXP-001 decision: R&D effort belongs in
   regime-transition quality, not parameter search. An adaptive parameter-tuning
   agent has even less to chase than previously argued: the local surface is flat.
3. **The sensitivity ranking independently re-identifies the volatility
   classifier as the load-bearing subsystem** (upper_thresh_z and the vol windows
   dominate). This is the third independent signal (after EXP-001's cell-4/6
   losses and 2022 failure) pointing at regime classification as the improvement
   target.
4. Drop the six inert knobs from any future grid search (pure compute waste).
5. Interpretation caveat carried from the report: retained-fraction semantics are
   fragile at sub-1 golden Sharpe; the cliff gate and percentile verdicts are the
   robust reads.

**Artifacts.** Reports `claudedocs/audit/2026-07-07/report_plateau_v3_5{b,d}.md`;
campaign JSONLs `claudedocs/audit/2026-07-07/v3_5{b,d}/campaign_v3_5{b,d}.jsonl`
(286 fsync'd rows each, seed 42); code merged to main @ `7b4b684` (133 unit
tests). Serena: `plateau_campaign_phase2_shipped_running_2026-07-07`,
`plateau_campaign_v3_5b_results_2026-07-07`.

**Follow-ups spawned.**
Module 1 WFO stability — the orthogonal question this experiment cannot answer
(parameters flat *today* may still drift *across time windows*; that is the test
that finally settles the adaptive-parameters idea); Module 3 DSR/PBO (the 48th
percentile lowers the prior of parameter overfit, but the trial-count correction
for the v2.x→v3.5b search history is still unmeasured); WFO-validate the
quarantined bond-SMA / vol-crush / osc_smoothness candidates before anyone is
tempted to adopt them.
