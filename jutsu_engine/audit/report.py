"""Markdown report assembly for Phase-1 audit modules (M4 + M5).

Section renderers are pure string builders over the result objects (unit-tested).
write_report writes report_<strategy>.md into a run directory. Every report embeds
the git SHA, data range, config path, and the spec §10 decision thresholds so any
number is reproducible.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# spec §10 decision thresholds (printed in every report).
FIDELITY_MISMATCH_THRESHOLD_PCT = 5.0


def _fmt(v, spec: str = ".2f") -> str:
    """Format a number for the report; None -> 'N/A' (never print literal None)."""
    if v is None:
        return "N/A"
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


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
    """Render the Live Reconciliation (Module 5) section as a markdown string."""
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

    logic_days = s["by_category"].get("logic", 0)
    data_days = s["by_category"].get("data", 0)
    logic_pct = (logic_days / s["total_days"] * 100.0) if s["total_days"] else 0.0

    lines = [
        "## Live reconciliation (Module 5)",
        "",
        f"- Days compared (scheduler-authoritative): **{s['total_days']}**",
        f"- Match days: **{s['match_days']}**  |  Mismatch days: **{s['mismatch_days']}**",
        f"- {verdict}",
        f"- Logic-category days (true divergence on same EOD inputs): **{logic_days}** "
        f"(**{logic_pct:.1f}%**)  |  Data-gap days: **{data_days}**. "
        f"The P0 threshold applies to logic+data fidelity; `timing` diffs "
        f"(intraday-vs-EOD z/t) are expected by design.",
        "",
        "### Mismatches by category",
    ]
    if s["by_category"]:
        for cat, n in sorted(s["by_category"].items(), key=lambda kv: str(kv[0])):
            lines.append(f"- {cat}: {n}")
    else:
        lines.append("- (none)")
    lines += ["", "### Mismatches by field"]
    if s["by_field"]:
        for f, n in sorted(s["by_field"].items(), key=lambda kv: str(kv[0])):
            lines.append(f"- {f}: {n}")
    else:
        lines.append("- (none)")

    mismatch_rows = [r for r in (recon.day_table or []) if r.get("category") != "match"]
    lines += ["", "### Day-level mismatches"]
    if not mismatch_rows:
        lines.append("_(no mismatch days)_")
    else:
        lines += ["| day | category | fields (stored→replay) |",
                  "| --- | --- | --- |"]
        for r in mismatch_rows[:40]:
            fields = "; ".join(
                f"{m['field']}: {m['stored']}→{m['replay']}" for m in r.get("mismatches", []))
            lines.append(f"| {r.get('day')} | {r.get('category')} | {fields} |")
        if len(mismatch_rows) > 40:
            lines.append(f"_(+{len(mismatch_rows) - 40} more mismatch days)_")

    lines += ["", "### Snapshot provenance (snapshot_source counts)",
              "Only `scheduler` rows carry valid regime; `backfill` rows have "
              "NULL z_score/t_norm; `refresh` rows carry no regime.", ""]
    for src, n in sorted(recon.source_counts.items(), key=lambda kv: str(kv[0])):
        lines.append(f"- `{src}`: {n} day(s)")

    d = recon.pnl_divergence
    lines += ["", "### P&L divergence (real EOD equity)",
              f"- Final live equity (total_equity): "
              f"{_fmt(d.get('final_stored_equity'))}",
              f"- Final replayed equity: {_fmt(d.get('final_replay_equity'))} "
              f"(positions-level equity replay is out of Phase-1 scope)",
              f"- Divergence day (last common): {d.get('divergence_day') or 'N/A'}",
              ""]

    # z-score discrepancy note (spec §9 acceptance): report continuous-field timing diffs.
    z_timing = s["by_field"].get("z_score", 0)
    lines += [
        "### 2026-02-04 z-score discrepancy",
        f"z_score timing-category diffs observed on **{z_timing}** day(s). "
        "z_score/t_norm are intraday-computed live vs EOD-replayed here, so exact "
        "match is not expected; these are categorized `timing`, not `logic`. "
        "Specific dates and values are in the day-level table above. Note: the ±0.25 z tolerance "
        "may absorb spreads of the magnitude seen in the 2026-02-04 investigation (~0.18–0.36); "
        "out-of-tolerance days listed above are the extreme cases.",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_attribution_section(attr) -> str:
    """Render the Era and Cell Attribution (Module 4) section as a markdown string."""
    m = attr.metrics
    t = attr.treasury
    treasury_verdict = (
        "the Treasury overlay **added** value net of whipsaw"
        if (t.get("contribution_vs_cash") or 0) > 0 else
        "the Treasury overlay **cost** money net of whipsaw (cells 4-6)"
    )
    lines = [
        "## Era and cell attribution (Module 4)",
        "",
        "### Headline (full-period backtest, live config)",
        f"- Sharpe: **{_fmt(m.get('sharpe_ratio'), '.4f')}**  |  MaxDD: **{_fmt(m.get('max_drawdown'), '.4f')}**",
        f"- Annualized return: **{_fmt(m.get('annualized_return'), '.4f')}**  |  "
        f"Total return: **{_fmt(m.get('total_return'), '.4f')}**",
        f"- Alpha vs QQQ: **{_fmt(m.get('alpha_vs_qqq'), '.4f')}**",
        "",
        "### Era table",
        _df_to_md(attr.era_table),
        "### Cell attribution",
        "_compounded returns are per-regime quality measures over non-contiguous "
        "days — NOT additive across cells; `strategy_return_sum` is the additive "
        "contribution column._",
        "",
        _df_to_md(attr.cell_table.assign(cell=attr.cell_table["cell"].map(lambda c: f"Cell {c}"))
                  if not attr.cell_table.empty else attr.cell_table),
        "### Treasury overlay contribution (cells 4-6 vs cash counterfactual)",
        "_position-value based; episode-aware (cross-episode allocation flows "
        "excluded); mid-episode rebalances can contaminate the diff._",
        "",
        f"- Treasury days: **{t['treasury_days']}**",
        f"- Treasury sleeve P&L (abs): **{_fmt(t.get('treasury_pnl_abs'))}**",
        f"- Contribution vs cash: **{_fmt(t.get('contribution_vs_cash'))}** — {treasury_verdict}.",
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


# spec §10 decision threshold for Module 2.
CLIFF_LOSS_THRESHOLD_PCT = 30.0


def render_plateau_section(summary: dict) -> str:
    """Render the Parameter Plateau (Module 2) section as a markdown string.

    ``summary`` keys:
      strategy_id, seed, oat_count, joint_count, golden_metrics,
      plateau_scores {param: {"mean_retained": float, "worst_retained": float, "n_rows": int}},
      degradation_table (DataFrame), cliffs (list[str]),
      joint_stats {count, errored, golden_percentile, min, max, median, ...}.

    Schema note: plateau_scores values are dicts (not plain floats). The table shows
    BOTH mean_retained and worst_retained columns, sorted worst_retained ascending.
    worst_retained is the conservative health gate — a two-sided mean can mask a
    one-sided collapse (e.g. sides 1.25 and 0.125 average to 0.688, hiding that one
    direction is nearly flat).
    """
    import math

    gm = summary["golden_metrics"]
    js = summary["joint_stats"]
    cliffs = summary["cliffs"]
    pct = js.get("golden_percentile")

    # --- joint distribution analysis ---
    errored_joint = js.get("errored", 0)
    total_runs = summary.get("oat_count", 0) + summary.get("joint_count", 0)
    # OAT errored count: read from summary (set explicitly in summarize_campaign).
    # Fall back to 0 so old summaries (without the key) don't crash the renderer.
    oat_errored = summary.get("oat_errored", 0)
    total_errored = oat_errored + errored_joint

    errored_line = (
        f"Errored runs excluded from analysis: **{total_errored}** "
        f"(OAT: {oat_errored}, joint: {errored_joint})"
    )
    suspect_warning = ""
    if total_runs > 0 and total_errored > total_runs * 0.10:
        suspect_warning = (
            "\n> **Warning:** errored runs exceed 10% of total samples — "
            "campaign conclusions are suspect. Investigate failures before acting on results."
        )

    # --- golden percentile verdict ---
    _pct_isnan = pct is None or (isinstance(pct, float) and math.isnan(pct))
    right_tail = (not _pct_isnan and pct >= 80.0)
    if _pct_isnan:
        percentile_verdict = "golden Sharpe percentile within joint distribution: N/A (no valid joint runs)."
    else:
        percentile_verdict = (
            f"golden Sharpe sits at the **{_fmt(pct, '.1f')}th percentile** of its own "
            f"+/-15% neighborhood — "
            + ("**far in the right tail (>=80th): a red flag that the golden config is "
               "a local peak fit to its neighborhood.**"
               if right_tail else
               "within the body of its neighborhood distribution (not an isolated peak).")
        )

    # --- cliff line ---
    cliff_line = (", ".join(f"`{c}`" for c in cliffs) if cliffs
                  else "_(none) — no parameter loses >30% of Sharpe at +/-10%_")

    # --- plateau-score table (both mean_retained and worst_retained), sorted worst-first ---
    ps = summary["plateau_scores"]

    def _worst(score_val):
        if isinstance(score_val, dict):
            v = score_val.get("worst_retained", float("nan"))
        else:
            v = score_val  # backward compat if plain float
        return v if (v is not None and not (isinstance(v, float) and math.isnan(v))) else 1e9

    ps_rows = sorted(ps.items(), key=lambda kv: _worst(kv[1]))
    # Caption lives BEFORE the table block so the GFM parser never sees a
    # non-pipe line between the header-separator row and the first data row.
    ps_caption = (
        "_Caption: sorted worst_retained ascending. "
        "worst_retained is the conservative health gate — "
        "a two-sided mean can mask a one-sided collapse (e.g. sides 1.25 and 0.125 "
        "average to 0.688 but one direction is nearly flat)._"
    )
    ps_lines = [
        "| param | mean_retained | worst_retained | n_rows |",
        "| --- | --- | --- | --- |",
    ]
    for name, score_val in ps_rows:
        if isinstance(score_val, dict):
            mean_r = score_val.get("mean_retained")
            worst_r = score_val.get("worst_retained")
            n_r = score_val.get("n_rows", 0)
        else:
            mean_r = worst_r = score_val
            n_r = "?"
        ps_lines.append(
            f"| `{name}` | {_fmt(mean_r, '.3f')} | {_fmt(worst_r, '.3f')} | {n_r} |"
        )

    lines = [
        "## Parameter plateau map (Module 2)",
        "",
        f"- Strategy: **{summary['strategy_id']}**  |  RNG seed: **{summary['seed']}**",
        f"- One-at-a-time samples: **{summary['oat_count']}**  |  "
        f"Joint (+/-15% box) samples: **{summary['joint_count']}**",
        f"- {errored_line}",
    ]
    if suspect_warning:
        lines.append(suspect_warning)
    lines += [
        "",
        "### Golden baseline (full-period backtest, live config)",
        f"- Sharpe: **{_fmt(gm.get('sharpe_ratio'), '.4f')}**  |  "
        f"MaxDD: **{_fmt(gm.get('max_drawdown'), '.4f')}**",
        f"- Annualized: **{_fmt(gm.get('annualized_return'), '.4f')}**  |  "
        f"Total: **{_fmt(gm.get('total_return'), '.4f')}**",
        "",
        "### Plateau scores (higher = flatter = more robust)",
        ps_caption,
        "",
        "\n".join(ps_lines),
        "",
        "### Cliff parameters (spec §10 threshold)",
        "| Signal | Threshold | Consequence |",
        "| --- | --- | --- |",
        f"| Cliff parameters (a +/-10% move loses >{CLIFF_LOSS_THRESHOLD_PCT:.0f}% "
        f"of Sharpe) | any | Flag for robustness work before further optimization "
        f"of those parameters |",
        "",
        f"- Cliff parameters: {cliff_line}",
        "",
        "### Joint-perturbation distribution",
        f"- Samples: **{js.get('count')}**  |  min/median/max Sharpe: "
        f"**{_fmt(js.get('min'), '.3f')}** / **{_fmt(js.get('median'), '.3f')}** / "
        f"**{_fmt(js.get('max'), '.3f')}**",
        f"- {percentile_verdict}",
        "",
        "### Per-parameter degradation table",
        _df_to_md(summary["degradation_table"]),
    ]
    return "\n".join(lines) + "\n"


def write_plateau_report(run_dir: Path, strategy_id: str, markdown: str) -> Path:
    """Write report_plateau_<strategy>.md into run_dir (created if missing).

    Deliberately a SEPARATE file from the Phase-1 report_<strategy>.md so the
    plateau run never touches or overwrites the recon/attribution report.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_plateau_{strategy_id}.md"
    out.write_text(markdown)
    return out


# ---------------------------------------------------------------------------
# Module 1 WFO — spec §5 / §10 report renderer
# ---------------------------------------------------------------------------

# spec §10 decision thresholds for Module 1 (WFO parameter stability).
WFO_STABLE_SHARE_PCT = 80.0
WFO_UNSTABLE_SHARE_PCT = 50.0


def render_wfo_section(summary: dict) -> str:
    """Render the WFO parameter-stability (Module 1) section as markdown.

    ``summary`` is the dict returned by summarize_campaign() / run_wfo():
      strategy_id, n_windows, n_winners
      stitched           — stitch_oos_metrics dict (includes nan_rows_dropped)
      combo_top_decile_share — float: spec §10 verdict input (golden COMBO in grid)
      combo_verdict      — "stable" / "unstable" / "inconclusive"
      overall_verdict    — alias for combo_verdict
      axis_diagnostics   — {param: {golden_value, share, verdict}} (diagnostic only)
      drift_table        — DataFrame: per-window winner params
      value_distribution — {param: {value: count}}
      campaign_file      — str

    The report explicitly answers the study question:
      "Adaptive parameter tuning: UNNECESSARY (stable) / JUSTIFIED-INVESTIGATE
      (unstable) / INCONCLUSIVE" — driven by combo_verdict (spec §10).

    The per-axis diagnostic table is clearly labeled "DIAGNOSTIC (not verdict input)"
    so readers know the verdict comes from the combo-level share only.

    Conventions from report.py:
      - _fmt() for every number (never literal None)
      - captions OUTSIDE GFM tables
      - standalone file report_wfo_<strategy>.md (write_wfo_report)
    """
    st = summary["stitched"]
    nan_dropped = st.get("nan_rows_dropped", 0) or 0
    overall = summary.get("overall_verdict", summary.get("combo_verdict", "inconclusive"))
    combo_share = summary.get("combo_top_decile_share", 0.0)

    # Study-question verdict line (required explicit answer, spec §10)
    _verdict_map = {
        "stable": "UNNECESSARY (stable)",
        "unstable": "JUSTIFIED-INVESTIGATE (unstable)",
        "inconclusive": "INCONCLUSIVE",
    }
    adaptive_verdict = _verdict_map.get(overall, "INCONCLUSIVE")

    # Overall consequence prose
    _consequence_map = {
        "stable": (
            f"The golden combo ranks in the top decile of its grid in "
            f"**{combo_share * 100:.1f}%** of windows "
            f"(>= {WFO_STABLE_SHARE_PCT:.0f}% threshold). "
            "Parameters are stable across walk-forward time windows; "
            "adaptive tuning is unnecessary by construction (spec §10)."
        ),
        "unstable": (
            f"The golden combo ranks in the top decile of its grid in only "
            f"**{combo_share * 100:.1f}%** of windows "
            f"(< {WFO_UNSTABLE_SHARE_PCT:.0f}% threshold). "
            "Parameters are fragile across time; adaptive tuning would chase "
            "noise — the config itself needs structural work (spec §10)."
        ),
        "inconclusive": (
            f"The golden combo top-decile share is "
            f"**{combo_share * 100:.1f}%** — between the "
            f"{WFO_UNSTABLE_SHARE_PCT:.0f}% and {WFO_STABLE_SHARE_PCT:.0f}% "
            "thresholds. Neither clearly stable nor clearly fragile; "
            "widen the study window or grid before deciding (spec §10)."
        ),
    }
    consequence = _consequence_map.get(overall, _consequence_map["inconclusive"])

    lines = [
        "## WFO parameter-stability study (Module 1)",
        "",
        f"- Strategy: **{summary['strategy_id']}**  |  "
        f"Windows: **{summary['n_windows']}** (winners: {summary['n_winners']})  |  "
        "scheme: 2.5y IS / 0.5y OOS / 0.5y slide",
        f"- Grid: 31 combos/window (3×3×3 sensitive-param product + 4 quarantine swaps; "
        "6 EXP-003 inert knobs excluded)",
        f"- Campaign file: `{summary['campaign_file']}`",
        "",
        "### Stitched OOS equity curve (headline — spec §5 output 1)",
        "_All metrics computed on the single concatenated OOS daily-return series "
        "(the **stitched series**), **not by averaging per-window Sharpes** "
        "(the legacy `walk_forward.py` flaw spec §5 rejects)._",
        "",
        f"- OOS trading days: **{st.get('oos_days', 0)}**",
        f"- Stitched OOS Sharpe: **{_fmt(st.get('sharpe'), '.4f')}**  |  "
        f"CAGR: **{_fmt(st.get('cagr'), '.4f')}**  |  "
        f"MaxDD: **{_fmt(st.get('max_drawdown'), '.4f')}**",
        f"- Stitched total return: **{_fmt(st.get('total_return'), '.4f')}**  |  "
        f"QQQ total return: **{_fmt(st.get('qqq_total_return'), '.4f')}**  |  "
        f"alpha vs QQQ: **{_fmt(st.get('alpha_vs_qqq'), '.4f')}**",
    ]

    # NaN-rows warning (surface when > 0; omit when 0 to keep the normal report clean)
    if nan_dropped > 0:
        lines.append(
            f"\n> **Warning:** {nan_dropped} OOS row(s) with NaN "
            "Strategy_Daily_Return were dropped before computing the stitched metrics. "
            "All metrics share one denominator (the surviving rows). "
            "Investigate the underlying backtests for regime-timeseries gaps."
        )

    lines += [
        "",
        "### Adaptive-parameters decision — study question answer (spec §10)",
        "",
        f"**Adaptive parameter tuning: {adaptive_verdict}**",
        "",
        f"_{consequence}_",
        "",
        "Decision thresholds (spec §10):",
        "| Top-decile share (golden COMBO across windows) | Threshold | Verdict |",
        "| --- | --- | --- |",
        f"| >= {WFO_STABLE_SHARE_PCT:.0f}% | stable | Adaptive tuning unnecessary |",
        f"| < {WFO_UNSTABLE_SHARE_PCT:.0f}% | unstable | Parameters fragile / config needs work |",
        f"| between | inconclusive | Widen study before deciding |",
        "",
        "#### Combo-level top-decile share (spec §10 verdict input)",
        f"- Golden combo hash: `{summary.get('golden_combo_hash', 'N/A')}`  |  "
        f"Top-decile share: **{combo_share * 100:.1f}%**  |  "
        f"Verdict: **{overall}**",
        "",
    ]

    # Per-axis diagnostic table (clearly labeled: NOT the verdict input)
    axis = summary.get("axis_diagnostics", {})
    if axis:
        lines += [
            "#### Per-axis golden winner share — DIAGNOSTIC (not verdict input)",
            "_Each axis value is the fraction of windows where the golden axis value "
            "is the outright per-axis winner (marginalised over other axes). "
            "With only 3 values per axis, 'top decile' = single best — so this is a "
            "strict outright-winner test, demoted to diagnostic. "
            "The spec §10 verdict is driven by the COMBO-level share above._",
            "",
            "| param | golden value | axis winner share | axis verdict |",
            "| --- | --- | --- | --- |",
        ]
        for param, info in axis.items():
            lines.append(
                f"| `{param}` | {info['golden_value']} | "
                f"{info['share'] * 100:.1f}% | {info['verdict']} |"
            )
        lines.append("")

    lines += [
        "### Per-window winner drift table (spec §5 output 2)",
        _df_to_md(summary.get("drift_table", pd.DataFrame())),
        "### Winning-value distribution (per param, across windows)",
    ]
    vdist = summary.get("value_distribution", {})
    if vdist:
        for param, counts in vdist.items():
            pairs = ", ".join(f"{v}×{n}" for v, n in sorted(counts.items()))
            lines.append(f"- `{param}`: {pairs}")
    else:
        lines.append("_(no winner data)_")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_wfo_report(run_dir: Path, strategy_id: str, markdown: str) -> Path:
    """Write report_wfo_<strategy>.md into run_dir (separate from Phase-1/2 reports).

    Deliberately a SEPARATE file so the WFO run never touches report_<strategy>.md
    (Phase-1 recon/attribution) or report_plateau_<strategy>.md (Module 2).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"report_wfo_{strategy_id}.md"
    out.write_text(markdown)
    return out
