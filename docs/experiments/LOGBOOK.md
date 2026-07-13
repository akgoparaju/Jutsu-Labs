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
| EXP-005 | 2026-07-07 | Given the trial count, how likely is the golden Sharpe real (DSR + PBO)? | Edge is REAL (DSR ≥0.997 all N brackets, conservative; V-sensitivity bounded) but selection within the family is noise (PBO 0.85) — trust the structure, not the pick |
| EXP-006 | 2026-07-08 | Correction: warmup rows polluted timeseries consumers | EXP-004 stitched OOS corrected (Sharpe 0.46→0.83, CAGR 5.4%→19.9%): adaptive tuning adds NOTHING (not "destroys value"); closure stands; EXP-001 unknown-era explained |
| EXP-007 | 2026-07-13 | Does a forward-looking (Kronos/VIX) or smoothing-only vol-input leg improve transition quality enough for a shadow slot? | PENDING (battery built; results after Tier-1 run) |

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

---

## EXP-005 — Baseline audit Phase 4: selection-bias correction (DSR + PBO) (2026-07-07)

**Question.** After correcting for how many configurations were tried, how likely
is the golden config's Sharpe to be real rather than the luckiest draw of the
search? (a) Deflated Sharpe Ratio (Bailey & López de Prado) at bracketed trial
counts N = 243 / 1,000 / 5,000; (b) Probability of Backtest Overfitting (PBO) via
CSCV (S=16) over the historical 243-combo golden grid's per-combo daily returns.

**Why.** EXP-001 established honest Sharpe ~0.8 (not the in-sample ~2.8). EXP-003
lowered the parameter-overfit prior (48th percentile of its own neighborhood).
EXP-004 closed adaptive tuning. Module 3 is the last unmeasured piece: the
trial-count correction for the v2.x→v3.5b search history. XREF-001 (n=1
crash-episode caution) says backtest-only evidence is structurally underpowered,
so DSR/PBO carry the burden of proof. Decision framework: spec
`docs/superpowers/specs/2026-07-06-baseline-audit-design.md` §7/§10.

**Method.** Built `jutsu_engine/audit/{dsr,pbo,selection_bias}.py` + `jutsu audit dsr`.
- **DSR** (pure math, `dsr.py`): PSR(SR*) = Φ(((SR_obs−SR*)√(T−1)) / √(1 − γ₃·SR_obs
  + ((γ₄−1)/4)·SR_obs²)); SR* = √V·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))), γ =
  Euler–Mascheroni; DSR = PSR(SR*). Golden daily returns from the campaign's golden
  combo; V from the actual per-combo Sharpes; N bracketed. Non-excess kurtosis
  (scipy excess + 3); sample skew/kurtosis (bias=False). Guards: N≥2, T≥2, positive
  radicand, non-zero variance.
- **PBO** (pure math, `pbo.py`): CSCV S=16, all C(16,8)=12,870 IS/OOS partitions;
  per partition rank combos by IS Sharpe, take IS-best, compute its OOS relative
  rank ω̄; PBO = fraction with ω̄ < 0.5 (logit < 0). Plus logit distribution,
  IS-vs-OOS degradation slope, prob-of-OOS-loss for the IS-best.
- **Returns campaign** (`selection_bias.py`): one-time full-period (2010-02 →
  present) re-run of the 243-combo golden grid, capturing each combo's daily
  Strategy_Daily_Return series inline in fsync-JSONL (reusing the plateau/WFO
  checkpoint/resume/breaker/single-writer/tempdir machinery — NOT parquet:
  pyarrow uninstalled, JSONL is proven and ~10 MB). Combos enumerated from the
  historical grid axes (documented in the Gold-Configs YAML header, versioned in
  `grid-configs/audit/golden_grid_v3_5b_axes.yaml`): upper_thresh_z [0.8,1.0,1.2] ×
  lower_thresh_z [-0.2,0.0,0.2] × vol_crush_threshold [-0.15,-0.20,-0.25] × sma_fast
  [40,50,60] × sma_slow [180,200,220] = 243. Inert AND sensitive axes both retained
  (the historical search varied them — EXP-003 inertness does not change the trial
  count that was actually spent).
- **Scoping:** v3_5b PRIMARY (full grid + DSR + PBO). v3_5d DSR-ONLY using its
  golden full-period returns + a family-level N — no second grid re-run (its
  distinguishing grid was ~10 Cell-1-exit combos, too few for CSCV).
- Trial inventory: read-only SELECT over `optimization_results` (grouped by
  strategy/optimizer). Early history may be incomplete → DSR reported bracketed.
- Command (one-time, ~1.7h at 4 workers): `jutsu audit dsr --strategy v3_5b --workers 4`;
  then DSR-only `--strategy v3_5d`. Smoke: `jutsu audit dsr --strategy v3_5b
  --combos-limit 4` (minutes, proves pipeline end-to-end).

**Results (campaign complete 2026-07-08: 244/244 backtests, 0 errors; numbers
below are AFTER the warmup-row fix — see EXP-006, which this campaign's fill
guard triggered).**
- *Trial inventory:* the prod DB has **no `optimization_results` table** — the
  historical searches persisted to CSVs only. True trial count is unrecoverable;
  bracketed N carries the analysis (as designed).
- *DSR (v3_5b, golden_live returns, T=4125, V=1.41e-05 from the 243-combo grid):*
  | N | 243 | 1,000 | 5,000 |
  |---|---|---|---|
  | DSR | **0.9987** | **0.9982** | **0.9975** |
  The spec gate (≥95%) is CLEARED at every bracket — and DSR is conservative by
  construction (nominal N overstates effective independent trials; sample V is
  estimation-noise-inflated; both deflate DSR).
- *V-sensitivity (the honest caveat):* the 243-combo grid explored a NARROW
  parametric neighborhood (grid daily Sharpes 0.046–0.060), so its V understates
  the dispersion of the full STRUCTURAL search history (v2.x → v5.1). Sensitivity
  at N=5000: V×4 → DSR 0.973; V×10 → 0.819; V×25 → 0.243. Under plausible
  structural-search dispersion (~V×4–×10) the edge still clears or nearly clears
  the gate; only extreme assumptions kill it. Model-dependent certainty, honestly
  bounded.
- *PBO (v3_5b, 243 combos, S=16, 12,870 partitions):* **0.8506** — in 85% of
  partitions the IS-best combo lands in the bottom half OOS. prob_oos_loss and
  degradation details in the report. The spec's PBO>50% flag FIRES loudly.
- *v3_5d (run 2026-07-08):* the DSR-only path has no grid → V=0 → its printed
  "DSR 0.9999" is UNDEFLATED PSR, not a DSR — do not quote it. Its golden moments
  (SR 0.0573 daily, skew −0.43, kurt 6.7, T=4125) nearly match v3_5b's, so
  v3_5b's bracketed DSR numbers are the family read. Follow-up queued: the
  DSR-only path should borrow the family V (or warn loudly at V=0).

**Verdict / decisions.**
1. **The strategy's edge is statistically real; the selection process is not.**
   These two findings coexist and explain each other: DSR ≥99.7% says the golden
   config's Sharpe survives best-of-N deflation decisively; PBO 85% says picking
   "the best" config within the family is meaningless — because (EXP-003/004) the
   surface is a flat plateau where IS ranking is noise. The edge belongs to the
   STRUCTURE (the 6-cell regime framework), not to the specific parameter pick.
2. Spec-§10 nuance recorded: the PBO>50% consequence ("treat edge as unproven")
   was written expecting PBO and DSR to agree. They diverge here for a measured
   reason (plateau → near-equivalent combos → selection is noise even though the
   family edge is real). Action taken: trust the structure; never trust
   fine-grained config selection; any future config change must show OOS
   superiority, not IS ranking.
3. DSR's certainty is conditional on the V model (see sensitivity) — recorded as
   a permanent caveat; do not quote "99.9%" without the V-sensitivity line.
4. **The audit spec is now COMPLETE: Modules 1-5 all measured.** The full gauntlet
   (fidelity + attribution + plateau + WFO + DSR/PBO) is a permanent, re-runnable
   fitness function.

**Artifacts.** Reports `claudedocs/audit/2026-07-07/report_dsr_v3_5b.md` (regenerated
post-fix); campaign JSONL `claudedocs/audit/2026-07-07/v3_5b/campaign_dsr_v3_5b.jsonl`
(244 rows); code merged to main @ `b0a08a3` + fix @ `d2d4123` (301 unit tests).
Serena: `dsr_phase4_shipped_campaign_running_2026-07-07` + results memory.

**Follow-ups spawned.** EXP-006 (warmup-row correction — spawned by this campaign's
fill guard); v3_5d DSR-only run; regime-classifier upgrade program with the full
gauntlet as fitness function; Kronos I7 overlays final-gated in this harness.

---

## EXP-006 — Correction: warmup-row pollution in regime-timeseries consumers (2026-07-08)

**What happened.** EXP-005's campaign fill-guard fired loudly (162/244 combos
dropped), which forced the investigation the guard exists for. Root cause: the
engine's regime-timeseries CSV includes **warmup-era rows dated before
start_date** (~331-345 rows of 0.0 returns, head varying with sma_slow's warmup
length). Three consumers were affected:
1. *EXP-005 (fixed pre-publication):* union alignment dropped 162 combos; all
   moments were zero-diluted. Fix: trim to the analysis span, then
   intersection-align → 243/243 combos retained; EXP-005's published numbers are
   post-fix.
2. **EXP-004's stitched OOS curve was materially wrong.** Worse than head-padding:
   later windows' warmup frames OVERLAPPED earlier windows' real OOS spans, and
   the keep-first dedup silently sourced **2,232 of 3,391 in-span days from
   warmup zeros**. Corrected stitched OOS (re-summarized from checkpoints, zero
   re-runs): v3_5b Sharpe 0.455 → **0.829**, CAGR 5.4% → **19.9%**, MaxDD −29.5%
   → **−54.4%**; v3_5d 0.464 → **0.806**, 5.4% → **19.3%**, −33.9% → **−54.5%**;
   oos_days 3737 → 3391.
3. *EXP-001's "unknown era" bucket* (312 zero-return days) is now fully explained:
   those were these warmup rows, already visible-but-benign there (assign_era
   quarantined them).

**What changes in EXP-004's conclusions (cross-reference both ways).**
- WRONG (retracted): "an adaptive agent would have destroyed ~3/4 of the return
  (CAGR 5.4%)". That number was the zero-pollution artifact.
- CORRECTED: adaptive 6-month re-optimization earns **Sharpe 0.83 / CAGR 19.9% /
  MaxDD −54%** — statistically indistinguishable from holding the fixed golden
  config (~0.81 / ~23% / −51% full-period). **The closure of the adaptive-tuning
  idea STANDS, for the corrected reason: it adds NOTHING** (same performance,
  plus re-optimization complexity and turnover), not "it destroys value".
- UNCHANGED: the top-decile share (3.7%, winners-are-noise) — IS ranking used
  scalar Sharpes computed at run time; warmup dilution is ~uniform within a
  window and preserves ranking (≤~3% relative distortion; documented in code).
  All four quarantined candidates remain killed. The corrected MaxDD −54%
  (2022 bear) independently re-confirms EXP-001's structural finding.

**Method note (lesson).** The loud-guard design paid for itself: a silent
implementation would have published EXP-005 on 81 combos and left EXP-004's
artifact standing. Rule reinforced: every alignment/drop/fill in an analysis
pipeline must be loud, and any fired guard is an investigation, not a nuisance.

**Artifacts.** Fix merged to main @ `d2d4123` (301 tests; consumption-side span
filters heal existing checkpoints — no backtests re-run). Corrected reports
regenerated: `report_wfo_v3_5{b,d}.md`, `report_dsr_v3_5b.md`.

---

## SYNTHESIS-001 — Where the program stands after the baseline audit (2026-07-08)

*This section interprets EXP-001…006 as a whole. It is written to be readable
cold — including by the Kronos research agent, which should treat the
"Binding facts for downstream research" list as constraints on its experiments.*

### The complete honest picture of v3.5b / v3.5d

| Question | Answer | Evidence |
|---|---|---|
| Does live trading match the backtest engine? | Yes — 1.1% true divergence (1 borderline day / 93) | EXP-002 |
| What does the strategy actually earn (fixed golden, 2010→2026)? | Sharpe ~0.81, CAGR ~23%, MaxDD **−51%** | EXP-001, reproduced twice |
| What would adaptive 6-month re-optimization earn? | Sharpe ~0.83, CAGR ~19.9%, MaxDD −54% — **the same** | EXP-004 as corrected by EXP-006 |
| Are the golden parameters overfit? | No — plateau, 48th/57.5th pct of own neighborhood, no cliffs | EXP-003 |
| Is the edge statistically real given the search history? | Yes — DSR ≥0.997 at N≤5000 (conservative); 0.82–0.97 under wider structural-search V | EXP-005 |
| Can grid search pick "the best" config? | No — PBO 0.85; IS winners are noise draws (3.7% top-decile, below chance) | EXP-005, EXP-004 |
| Where does the strategy fail? | Regime transitions: 2022 bear −46% vs QQQ −33%; cells 4/6 net losers; 2025-present alpha negative | EXP-001 |
| Where is it most sensitive? | The vol-regime classification inputs (upper_thresh_z, vol windows, sma_slow) — identically on both strategies | EXP-003, replicated |

### Interpretation of the final outcome

1. **The strategy family has a real edge, and it lives in the structure.** DSR
   says the edge survives selection-deflation decisively; PBO says selecting
   among configs is meaningless. Both are true because the parameter surface is
   a flat plateau (EXP-003): every nearby config is nearly the same strategy.
   The 6-cell regime framework earns the returns; the exact parameter values do
   not matter within ±15-20%.
2. **Every parametric improvement route is now closed with data, not opinion.**
   Parameter tuning (EXP-003: flat), adaptive re-tuning (EXP-004/006: equals
   fixed, at higher complexity), candidate swaps (EXP-004: all four quarantined
   candidates killed OOS), finer selection (EXP-005: PBO 0.85). This was the
   original 2026-07-06 question ("agent that modifies parameters to make it
   better?") — answered: **no such agent can help this strategy.**
3. **The only open improvement route is structural: regime-transition quality.**
   Five independent lines point at the same subsystem — the volatility-regime
   classifier and the crash exit/re-entry path: (a) 2022 era loss exceeding
   QQQ's; (b) defensive cells losing money over 16 years; (c) EXP-003
   sensitivity ranking (vol-channel inputs on top, both strategies); (d) the
   Kronos program's independent finding that the vol channel is the only real
   zero-shot signal channel; (e) 2025-present negative alpha during choppy
   transitions.
4. **Risk framing changed materially.** The documented MaxDD −18% is wrong; the
   honest number is −51% (fixed) / −54% (walk-forward). Anyone sizing positions
   or leverage on the documented number is carrying ~3x the believed drawdown
   risk. This is an open operational decision, not an experiment.
5. **The measurement infrastructure is now the asset.** The gauntlet — live
   fidelity recon, era/cell attribution, plateau map, WFO with stitched OOS,
   DSR/PBO — is re-runnable (`jutsu audit all|plateau|wfo|dsr`), checkpointed,
   and reviewed. Every future candidate change must pass through it. Its loud-
   guard philosophy already paid for itself twice (EXP-002, EXP-006).

### Binding facts for downstream research (Kronos agent: read this list)

- **Honest benchmarks to evaluate overlays against:** fixed golden full-period
  (Sharpe 0.81 / CAGR 23.1% / MaxDD −51.2%, 2010-02→2026-07) and the corrected
  walk-forward OOS curve (Sharpe 0.83 / CAGR 19.9% / MaxDD −54.4%, 2012-08→
  2026-07, 3,391 days). Do NOT use the documented Sharpe 2.79 / MaxDD −18%
  anywhere; do NOT use EXP-004's retracted pre-correction numbers (Sharpe 0.46).
- **Any regime classifier/input must beat the best single raw feature it would
  replace** — for the vol state, that bar is raw vol_zscore at AUC 0.828
  (t+21 vol-state prediction; the Kronos program's own VER1 finding).
- **Selection discipline:** IS ranking is inadmissible as evidence (PBO 0.85);
  acceptance requires OOS superiority in the gauntlet, plus DSR/PBO-style
  multiple-testing correction for however many overlay variants were tried.
- **Information set:** live decisions happen ~15 min after the open of day D
  (bars ≤ D−1 + an unpersisted intraday quote). Any signal computed on day D's
  close and "traded" on day D in a backtest is look-ahead (EXP-002).
- **Engine data gotcha:** regime-timeseries CSVs contain warmup rows dated
  before the backtest start (0.0 returns, length varies with config). Trim to
  the analysis span before computing anything (EXP-006).
- **Statistical power warning:** the whole 16-year record contains ~6 crash
  episodes, and every drawdown-protection overlay tested so far (ours and
  Kronos's ~25 variants) ends up clipping the same single episode. Backtest
  evidence for transition improvements is structurally underpowered — design
  experiments accordingly (era-sliced, null-matched, and humble).

### Program state

- Audit spec (docs/superpowers/specs/2026-07-06-baseline-audit-design.md):
  **all five modules complete.** Code on main @ `9acb696`, 301 audit tests.
- Kronos program: zero-shot iteration exhausted (their logbook); I7 fine-tune
  trained on the M4; its overlay re-tests should be final-gated in this
  gauntlet (era-sliced, 2022 crash exit focus).
- Next arc: regime-classifier upgrade program — candidate confirming inputs
  (VIX term structure, credit spreads, breadth, Kronos ema-blend fwd-vol)
  evaluated ablation-style in the gauntlet against the AUC-0.828 bar and OOS
  acceptance rules. The plateau/WFO/DSR machinery is its fitness function.

---

## XREF-002 — Kronos program concluded; ema5_blend handoff accepted into the ablation queue (2026-07-08)

The Kronos regime-detection program is **concluded** (their `experiments.md`
PROGRAM ANSWER + `docs/2026-07-08-kronos-vol-input-handoff.md`). Summary of their
ending: the I7 fine-tune (25.8h on the M4, clean pre-registered evaluation) went
**RED on all four gates** — it halved the bearish prior but *degraded* the rank
signal (ρ 0.19→0.14, DA 0.56→0.52) and the vol channel (AUC 0.793→0.767); the one
genuine gain (embeddings probe 0.76→0.797) still sits under the raw vol_zscore
bar (0.815–0.828). Final answer to their central question: **Kronos is not a
leading regime detector for v3.5b, zero-shot or fine-tuned.**

**Surviving deliverable, accepted here as ONE pre-registered candidate:**
`kronos_vol_blend` (zero-shot Kronos-base fwd-vol → trailing-200 z → EMA5 →
50/50 blend with production vol z → unchanged hysteresis). Evidence on OUR
engine's decision stream (their exp10): Sharpe +0.09, MaxDD −36.1%→−29.0%,
**2022 return −30.2%→−13.2%** — the effect sits exactly on our identified
failure mode. Honest limits: never statistically significant (all CIs include
zero; shared n≈1-crash-episode problem); the Kronos leg ALONE is worse than raw
vol_zscore (0.793 vs 0.815–0.828) — the entire claim is forward+backward
**complementarity**, untested; same-close convention optimistic (T-1 numbers
were path noise); their port agrees with our engine on only 87.5% of days →
acceptance runs must be engine-side (their own instruction).

**Ablation-battery design decision (recorded now, binding on the upcoming
regime program):** the battery must contain two control arms that their program
could not provide:
1. **`vix_blend`** — the identical 5-step recipe with an implied-vol z-score
   (VIX or VIX3M/VIX structure) as the forward-looking leg. The market already
   publishes a forward vol forecast; if it captures the same 2022 improvement,
   Kronos adds model-ops for nothing. If Kronos beats it, that is a genuinely
   remarkable finding. This is the decisive comparison.
2. **`smoothing-only` control** — blend the production vol z with its own EMA5
   (no external information at all). I2b's improvement may be partly "smoother
   input → less whipsaw", which needs no forecaster. This isolates the
   information content from the filter effect.
Plus the stock baseline. All arms: engine-side, T-1 information set, era-sliced
(2022 decisive), gauntlet OOS acceptance, no variant sweeping without DSR/PBO
correction. Precomputed Kronos forecasts cover 2019-08→2025-12 (two stress
episodes: 2020, 2022) — the evaluable window for arms needing the Kronos leg.

---

## EXP-007 — Regime program Phase 1: transition metrics + vol-input ablation battery (2026-07-13)

**Question.** The baseline audit closed every parametric route and localized v3.5b's
weakness to regime-transition quality — specifically the vol-state classifier around
crash exits/re-entries (SYNTHESIS-001). Does replacing the vol-state INPUT series with a
forward-looking leg (Kronos forecast or implied vol) — or mere smoothing — improve
transition behavior enough to earn a paper-trading shadow slot? Four arms, pre-registered
gates: `stock` (baseline) / `kronos` (Kronos program's sole surviving deliverable,
XREF-002) / `vix` (implied-vol control) / `smoothing` (zero-information filter control).

**Why.** SYNTHESIS-001 identified the vol-regime classification channel as the
load-bearing failure mode, confirmed by five independent lines of evidence (EXP-001
cell 4/6 losses, EXP-003 sensitivity ranking replicated on both strategies, XREF-001
Kronos independent signal analysis, 2022 bear underperformance, 2025-present negative
alpha). XREF-002 accepted the Kronos program's sole surviving deliverable
(`kronos_vol_blend`) but mandated two control arms to isolate whether the improvement
is from forward-looking information or merely smoother inputs — the battery delivers
both controls and a rigorous engine-side harness the Kronos port could not provide
(their port agreed with our engine on only 87.5% of days).

**Method.** Built the transition-metrics gauntlet + the ablation battery (this plan,
`docs/superpowers/plans/2026-07-13-regime-battery-phase1.md`). Code commit `dd5a847`
(spec) + this plan; data facts verified against DB + parquet on 2026-07-13.

*Registry (Task 1-2).* `grid-configs/audit/crash_episodes.yaml`: 8 crash episodes
(dotcom/gfc/euro2011/china2015/q4_2018/covid2020/bear2022/spring2025). Peak/trough
dates QQQ-verified against `market_data` closes (read-only). Two corrections applied
during verification (Task 2): `bear2022` peak 2021-12-27→**2021-12-27** (confirmed)
and `spring2025` dates confirmed. Each episode's `portfolio_scored` flag controls
whether portfolio-level metrics are computed (pre-2010 episodes: signal-only, since
TQQQ backtests start 2010-02). Loader/validator in
`jutsu_engine/audit/transitions.py`.

*Transition scorer (Tasks 3-4).* Pure functions over a WARMUP-TRIMMED regime
timeseries (EXP-006 lesson — trim to `[start_date, end_date]` before any metric):
exit_lag_days / drawdown_capture / reentry_lag_days / whipsaw_flips /
days_defensive per (arm × episode) at portfolio level; signal-level: flip
lead/lag relative to episode peak, flip_count_ratio vs stock arm, AUC(vol-state@t+21)
vs the raw-bar VER1 bar of 0.815–0.828.

*Exit-lag semantics (SIGNED — critical correctness note).* `exit_lag_days` is the
count of trading days from the episode peak row to the first row with a defensive
cell (4/5/6) in the `at_or_after_peak` slice — measured as the 0-based index of
that row, so 0 means the peak day itself was defensive, 1 means one trading day
later, etc. A strategy that de-risks BEFORE the peak would show 0 (defensiveness
had already started). `None` if the strategy never enters a defensive cell from
peak through trough. This semantics was revised during review: earlier drafts defined
exit_lag relative to the run-start date; the signed/index definition is the
as-built engine truth.

*Input-series builders (Tasks 5-6, 8 for smoothing via replay).*
- **`kronos`**: checksummed parquet `claudedocs/inputs/QQQ_kronos_base.parquet`
  (sha256 `a9a4a34502ccdb601723972ac469ae399837d500a41228d7485c9b9353c3ab6e`); uses
  `std_return` at `horizon==5`; span 2019-08-06→2025-12-31 (1,612 timestamps).
  Pipeline: trailing z(200) → EMA5 (T-1 aligned). Signal window: 2019-08→2025-12.
- **`vix`**: `$VIX` daily close from `market_data` (read-only SELECT), deduped
  deterministically (earliest intraday timestamp per date keeps the real CBOE close;
  validated against 2020-03-16=82.69 anchor). Data span ends 2026-02-03 (STALE —
  `jutsu sync $VIX` is out-of-scope; the vix arm's signal window ends at the data
  boundary). Pipeline: trailing z(200) → EMA5 (T-1 aligned). Note: `$VIX` has 1,879
  duplicate-date days in market_data; the dedup policy is anchor-validated and raises
  on drift. VIX bounded at its 2026-02-03 data end for signal window; portfolio
  window 2019-08→2025-12 unaffected (the data covers through 2026-02-03).
- **`smoothing`**: engine-truth vol_z series (from `calculate_signal_stream` replay)
  → EMA5. No external information — isolates filter effect from forecasting.
- **`stock`** (baseline): unmodified production vol_z series from engine replay.
All series T-1 aligned; causality guaranteed by trailing-only pipeline (prefix-stability
unit-tested). Max trading-row cap: 120 rows from episode peak for whipsaw counting
(prevents the score from wandering into unrelated market events).

*Vol-input adapter (Task 7).* `jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b_VolInput.py`
— diagnostic-only subclass. Blends the precomputed series at the vol-z step:
`blended_z = weight * series_value + (1 - weight) * engine_vol_z`. Decimal
conventions consistent with the live strategy. **Identity guarantee**: with no
injected series (`vol_input_series=None`) the adapter's output matches stock v3_5b
exactly over 2010-02→2026-07 on all daily regimes (tested via full BacktestRunner
run, ~30–50 s, PASS on main). Live YAMLs and live/scheduler code UNTOUCHED.

*Engine-truth signal replay (Task 8).* Via `LiveStrategyRunner.calculate_signal_stream`
(additive method, single bar-loop pass, no portfolio execution). Replay cost: ~1–3 min
for the stock/vix/smoothing arms (6,800 QQQ bars, 1999-03→2026-07); <1 min for kronos
(1,600 bars, 2019-08→2025-12). This single-pass mechanism is the lesson from the
Kronos port's 87.5% day-agreement: nothing is reimplemented.

*Battery arms (Task 9).* Four gated arms at blend weight `w=0.5`; six ungated
flatness-diagnostic neighbors at `w=0.25` and `w=0.75` (one pair per non-stock arm).
The SIGN rule (spec §8 flatness gate): a diagnostic neighbor at the same w=0.5 verdict
that flips sign vs the gated arm (positive ↔ negative) counts as flatness evidence even
if both are within noise — the direction of effect is unreliable at that weight.
Ungated diagnostics never used to pick `w`; they are read-only evidence of weight
sensitivity.

*AUC NaN policy.* `auc_vol_state_forward` returns `float('nan')` when the label
vector is single-class (undefined AUC), mirroring the Kronos VER1 convention.
NaN rows are dropped cleanly from the AUC gap threading in the report (not
forward-filled or imputed).

*Battery runner (Tasks 11-12).* 10 `BacktestRunner` backtests over the Tier-1
portfolio window 2019-08→2025-12 (~1,600 trading days each); ~1–1.5 min total at
`--workers 4`. Campaign JSONL: fsync-append checkpoint/resume, single-writer
invariant, circuit breaker (from the plateau/DSR machinery). Smoke test: stock arm
only, short window, ~15–30 s.

*Gates (Tasks 9, 13) — pre-registered per spec §8.*
- **Signal gate** (per arm): AUC > 0.815 AND flip lead/lag improves vs stock.
- **Portfolio gate** (per arm): era-sliced 2022 Sharpe delta ≥ +0.05 with bootstrap
  CI entirely above zero; drawdown_capture improvement vs stock in covid2020 + bear2022.
- **Flatness SIGN rule**: if the w=0.25 and w=0.75 neighbors bracket sign changes,
  the arm is flagged for weight sensitivity.
- **Tier-2 trigger**: only if exactly `kronos` survives and vix does NOT — confirms
  that the Kronos leg is the specific informational contribution, not just filter
  smoothing. Trigger runs extended window 2010-02→2019-08 backfill + 2010→present
  portfolio run.

*Identity regression gate.* Before any battery run: the adapter subclass (no injected
series) must reproduce stock v3_5b daily regimes exactly over 2010-02→2026-07. This
ran on main; **result: PASS** (zero divergent days, full 16-year period).

*Tier-1 windows.*
- Portfolio: 2019-08→2025-12 (two stress episodes: covid2020 and bear2022).
- Signal: 1999-03→present for stock/vix/smoothing (non-kronos); 2019-08→2025-12
  for kronos (parquet span). VIX signal window bounded at 2026-02-03 (data end).

*Pre-registered expected outcomes (spec §8 — recorded so we cannot rationalize later).*
- If **smoothing** survives and kronos/vix add nothing beyond it → "filtering, not
  forecasting"; the cheapest possible improvement ships.
- If **vix** matches kronos → Kronos adds model-ops for nothing.
- If **kronos** uniquely survives → a learned forecaster beat implied vol
  (extraordinary); Tier 2 must confirm.

Command (Tier-1 run, read-only): `jutsu audit battery --strategy v3_5b --workers 4`.
Smoke: `jutsu audit battery --strategy v3_5b --smoke`.

**Results.** PENDING — fill after the Tier-1 campaign: per-arm × per-episode
transition tables, signal AUC vs the 0.815-0.828 bar, era-sliced 2022 portfolio
deltas with bootstrap CIs, the flatness SIGN diagnostic, the per-arm verdict, and
the Tier-2 trigger decision. Reports land in
`claudedocs/audit/<date>/report_regime_battery_v3_5b.md`.

**Verdict / decisions.** PENDING (battery pending — filled after the Tier-1 run).

**Artifacts.**
- Spec: `docs/superpowers/specs/2026-07-13-regime-battery-design.md` (commit `dd5a847`).
- Plan: `docs/superpowers/plans/2026-07-13-regime-battery-phase1.md`.
- Report path (post-run): `claudedocs/audit/<date>/report_regime_battery_v3_5b.md`.
- Campaign JSONL (post-run): `claudedocs/audit/<date>/v3_5b/` (battery arm JSONL).

**Follow-ups spawned.** (Conditional) Tier 2 if kronos uniquely survives and vix does
not; (conditional) Phase-2 shadow spec if any arm survives all gates.
