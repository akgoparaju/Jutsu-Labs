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
