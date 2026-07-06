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
