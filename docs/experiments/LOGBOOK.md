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
| EXP-004 | 2026-07-07 | Are the golden parameters stable across WFO time windows (does adaptive tuning have anything to chase)? | Adaptive tuning CLOSED: winners are noise (golden top-decile 3.7%, below chance); chasing them OOS earns Sharpe 0.46 / CAGR 5.4% vs ~0.8 / ~23% fixed; all 4 quarantined candidates killed |

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

---

## XREF-001 — Cross-findings from the Kronos regime-detection research (2026-07-07)

A parallel research program (`~/dev/kronos-research/jutsu-kronos-research`,
logbook `experiments.md`) is testing whether the Kronos time-series foundation
model can detect regime change earlier than v3.5b's Kalman/vol-z indicators.
It has already ingested our EXP-001/002/003 (their XREF1): honest-baseline
Gate-2 recalibration, T-1 information-set constraint for live integration,
era-sliced evaluation, and a deflated-Sharpe/multiple-testing rule. This entry
records the reverse direction — their findings that bind on OUR roadmap.

1. **The bar for any regime-classifier upgrade is now quantified: raw current
   `vol_zscore` predicts vol-state@t+21 with AUC 0.828** (their VER1). Zero-shot
   Kronos embeddings encode regime (AUC 0.76) but add NOTHING over that single
   raw feature. Adopt as a gauntlet rule: any candidate regime input/classifier
   must beat the best single raw feature it would replace — not a strawman or
   trained-probe baseline.
2. **Adopt their VER1 measurement rules** into our gauntlet (Module 3 planning):
   (a) lead/lag claims must beat a crossing-density-matched null; (b) bounded
   signals must be centered before sign-based scoring; (c) single-raw-feature
   baselines mandatory (rule 1).
3. **n=1 crash-episode caution, independently confirmed:** all ~25 of their
   zero-shot overlay variants converge on clipping the SAME single drawdown
   episode (~+1.5pp MaxDD, never significant). Matches our EXP-001 finding that
   a handful of episodes decide the strategy's fate → backtest-only evidence for
   regime improvements is structurally underpowered; Module 3 (DSR/PBO) and live
   track record carry the real burden of proof.
4. **Candidate input for our future regime-upgrade phase:** their I2b
   `ema3/5_blend` of Kronos forward-vol z (50/50 with realized-vol z) passes all
   their deployment guards (flip ratio 1.12, ΔSharpe +0.09, ΔMaxDD +1.6pp — not
   significant, "strictly harmless"). Kronos forward-vol is genuinely
   forward-looking (corr 0.38 w/ fwd realized vol) where v3.5b's z is backward-
   looking. Queue it in the ablation battery alongside VIX term structure etc.,
   evaluated in OUR harness under rule 1.
5. **Port-fidelity risk (action for us):** their overlay sims run on
   `jutsu_ports.py` — a REIMPLEMENTATION of v3.5b's regime pipeline validated
   against a dashboard CSV oracle. Our audit infra can provide a stronger oracle:
   the engine-emitted regime_timeseries CSV (per-day cells, 2010→present) from
   `jutsu audit attribution` artifacts. Offer it; a silent port divergence would
   shift all their Gate-2 baselines.
6. **Their pivotal next step is I7 fine-tuning** (running on M4/MPS since
   2026-07-07, ~28.5h): removes the A-share bearish prior that RC1 identified as
   the binding constraint. When its overlay re-tests arrive, they should be
   scored era-sliced (2022 crash exit) — and the natural final gate is our audit
   gauntlet (honest baseline, stitched WFO OOS once Module 1 lands).

**Shared conclusion, reached from opposite directions:** the volatility-regime
classification channel is v3.5b's load-bearing subsystem — our EXP-003
sensitivity ranking (upper_thresh_z / vol windows, replicated on both
strategies) and their signal analysis (vol is the only real zero-shot Kronos
channel) point at the same place. The improvement program has a single
convergent target: **regime-transition quality, especially crash exit/re-entry,
via the vol channel.**

**Shared backlog item:** persist the scheduler's decision-time synthetic bar —
needed by our audit (3 residual unverifiable days) AND their Phase-2 live
integration (T-1 information-set constraint).

---

## EXP-004 — Baseline audit Phase 3: WFO parameter-stability study (2026-07-07)

**Question.** Are the golden parameters stable across walk-forward time windows,
or do the winning values drift? EXP-003 showed the config is parameter-robust
*today* (a plateau, 48th/57.5th percentile of its own neighborhood); this is the
orthogonal test EXP-003 could not answer — parameters flat today may still drift
*across time windows*. This settles the adaptive-parameters question with
out-of-sample data (spec §5/§10).

**Why.** EXP-001 pinned fragility to the *time* dimension (2022 failure, 2025
negative alpha), not the parameter dimension. EXP-003 showed the parameter
surface is flat in cross-section; WFO answers whether the golden config's winning
parameter values are stable window-to-window and whether a stitched OOS curve
confirms or degrades the EXP-001 full-period Sharpe ~0.8. Also WFO-validates the
EXP-003 quarantined candidates (bond_sma_fast 24, bond_sma_slow 66,
osc_smoothness 12, vol_crush_threshold −0.12) out-of-sample before anyone adopts
them. Decision framework: spec `docs/superpowers/specs/2026-07-06-baseline-audit-design.md`
§5/§10.

**Method.** Built `jutsu_engine/audit/wfo_stability.py` + `jutsu audit wfo`.
Architecture: thin per-window IS grid search + OOS stitching built on the audit
package's own infra (`build_overridden_strategy` + `BacktestRunner` + plateau JSONL
checkpoint/resume/circuit-breaker/single-writer patterns). WFORunner explicitly
rejected: it stitches trades, has no checkpoint/resume, and cannot produce a
stitched daily-return curve (spec §5 output 1). Strictly read-only vs the DB; no
live/scheduler changes.

- Windows: 2.5y IS / 0.5y OOS / 0.5y slide, 2010-02 → present (~26–27 windows).
  Boundary-day dedup applied (last day of window N excluded from window N+1 OOS
  concatenation to prevent double-counting).
- Per-window grid (31 combos, evidence-driven from EXP-003): 3×3×3 product over
  the sensitive vol-regime inputs `upper_thresh_z` [0.8, 1.0, 1.2] ×
  `realized_vol_window` [16, 21, 26] × `sma_slow` [120, 140, 160], PLUS 4
  single-swap quarantine combos (`vol_crush_threshold` −0.12, `bond_sma_fast` 24,
  `bond_sma_slow` 66, `osc_smoothness` 12). Six EXP-003 inert knobs explicitly
  excluded (documented in `WFO_INERT_EXCLUDED`).
- Per window: run all 31 IS combos → pick winner by IS Sharpe → run ONE OOS
  backtest with the winner → extract `Strategy_Daily_Return` from regime-timeseries
  CSV. Quarantined candidates validated only if they WIN a window AND their OOS
  daily-return contribution holds up in the stitched series.
- **Stitched OOS curve**: concatenate all window OOS daily-return series; compute
  Sharpe/CAGR/MaxDD/alpha-vs-QQQ on the single stitched series — NEVER by
  averaging per-window Sharpes (the legacy `walk_forward.py` flaw spec §5 rejects).
  NaN rows counted and surfaced loudly; nan_rows_dropped reported.
- Spec §10 verdict driven by golden COMBO top-decile share across windows
  (deterministic tie-breaking by sorted hash). Per-axis shares included as
  diagnostic only, not verdict inputs.
- Infra: `--retry-errors`, midnight-safe run-dir, parallel circuit-breaker drains
  in-flight workers cleanly on abort.
- Command (overnight, resumable): `jutsu audit wfo --strategy v3_5b --workers 4`
  then `--strategy v3_5d`. Smoke: `jutsu audit wfo --strategy v3_5b --windows-limit 2
  --workers 4` (~4 min, proves pipeline end-to-end).

**Results (both campaigns complete 2026-07-07, 864/864 rows each, 0 errors,
~1h/strategy at workers=4).**

*Stitched OOS equity curve (3,737 OOS trading days ≈ 14.8y, 2012-08 → 2026-07) —
this is what an adaptive re-optimizing agent (re-tune every 6 months on trailing
2.5y, trade the winner) would actually have earned:*

| | OOS Sharpe | OOS CAGR | OOS MaxDD | total return | QQQ total | alpha |
|---|---|---|---|---|---|---|
| v3_5b | **0.455** | **5.4%** | −29.5% | +119% | +992% | **−873pp** |
| v3_5d | **0.464** | **5.4%** | −33.9% | +117% | +979% | **−862pp** |

- **Golden combo top-decile share: 3.7% (1/27 windows) — both strategies.**
  Formally "unstable" per the spec §10 gate. But note what 3.7% means on a flat
  surface: with 31 near-equivalent combos racing, golden would land top-4 ~13% of
  the time by pure chance; 3.7% is *below* chance — per-window winners are noise
  draws, not signal.
- **Winner values are noise, not drift**: golden values remain the MODES of the
  winner distribution on every axis (upper_thresh_z 1.0 wins 20/27; realized_vol_window
  21 wins 12-13/27; sma_slow 140 wins 12/27) with no temporal trend — winners
  bounce between adjacent values window to window.
- **All four quarantined candidates KILLED.** They won only scattered windows
  (v3_5b: vol_crush_threshold −0.12 ×4, osc_smoothness 12 ×4, bond_sma_fast 24 ×1,
  bond_sma_slow 66 ×1 — same pattern v3_5d) with no persistence, and the stitched
  OOS curve containing their wins is poor. The in-sample improvements from EXP-003
  did not transfer; do not adopt any of them.

**Verdict / decisions.**
1. **The adaptive-parameter-tuning idea is now CLOSED, empirically.** This is the
   experiment the whole audit was scoped to reach. The two-sided proof: (a) the
   spec gate says parameters are "unstable" — but EXP-003 showed the surface is
   flat, so the instability is *noise* instability; (b) the stitched OOS curve
   directly measures what chasing per-window winners earns: **Sharpe 0.46 / CAGR
   5.4%**, versus ~0.8 / ~23% for simply holding the fixed golden config over the
   same era, and +992% for QQQ buy-hold. An adaptive agent re-optimizing these
   parameters would have destroyed roughly three-quarters of the strategy's
   return. Selection on 2.5y in-sample Sharpe does not transfer 6 months forward.
2. Read together, EXP-003 + EXP-004 say: the golden config's parameter choices
   are fine (modal, central, plateau) — **the config's weakness is structural,
   not parametric**. Fourth consecutive experiment pointing improvement effort at
   the regime classifier (crash exit/re-entry), now with the parametric
   alternative affirmatively eliminated rather than merely disfavored.
3. Spec-§10 label caveat: the report prints "JUSTIFIED-INVESTIGATE (unstable)"
   per the pre-committed threshold contract; the investigation is this study
   itself — the adaptive route was investigated and empirically fails. No
   follow-up adaptive experiment is warranted.
4. Method note for future WFO reads: each OOS window trades cold-start (fresh
   warmup, no position carryover), and this tested ONE adaptive protocol
   (6-month re-opt, 2.5y lookback, Sharpe selection). Alternate protocols would
   likely fare similarly given the noise diagnosis, but the claim is strictly
   about this class.

**Artifacts.** Reports `claudedocs/audit/2026-07-07/report_wfo_v3_5{b,d}.md`;
campaign JSONLs `claudedocs/audit/2026-07-07/v3_5{b,d}/campaign_wfo_v3_5{b,d}.jsonl`
(864 fsync'd rows each); code merged to main @ `223a1c8` (199 unit tests).
Serena: `wfo_phase3_shipped_campaign_running_2026-07-07` (+ results memory).

**Follow-ups spawned.** Module 3 (DSR/PBO) — the last unmeasured piece: trial-count
correction for the family's search history (EXP-003's 48th-percentile finding
lowered the parameter-overfit prior; DSR/PBO quantifies it). The stitched WFO OOS
curve is now the honest benchmark for the Kronos program's Gate-2 overlays
(XREF-001). Regime-classifier upgrade program (vol channel) is next after
Module 3, with the full gauntlet (plateau + WFO + DSR) as its fitness function.

**Follow-ups spawned.** Module 3 DSR/PBO (spec §14) — the trial-count correction for
the v2.x→v3.5b search history is still unmeasured. If WFO says unstable, the
adaptive-parameters idea is dead and R&D moves entirely to regime-transition quality.
