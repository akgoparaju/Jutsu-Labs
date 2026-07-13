"""`jutsu audit` command group (Phase 1: live-recon + attribution).

Follows the click pattern of jutsu_engine/cli/commands/wfo.py and monte_carlo.py.
Scaffolded so Modules 1/2/3 can add subcommands later without restructuring.
Read-only: never mutates the DB; outputs markdown to claudedocs/audit/<date>/.
"""
from __future__ import annotations

import subprocess
from datetime import date, datetime
from pathlib import Path

import click

from jutsu_engine.audit.config import PROJECT_ROOT, report_output_dir, resolve_strategy
from jutsu_engine.audit.db import AuditDBUnavailable
from jutsu_engine.audit.live_recon import run_live_recon
from jutsu_engine.audit.attribution import run_attribution
from jutsu_engine.audit.report import (
    render_report, write_report,
    render_plateau_section, write_plateau_report,
    render_wfo_section, write_wfo_report,
    render_dsr_section, write_dsr_report,
)
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('CLI.AUDIT', log_to_console=True)


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
    run_dir = report_output_dir()
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
        attribution = run_attribution(strategy_id, output_dir=str(run_dir / strategy_id))
        click.echo(click.style(
            f"  sharpe={attribution.metrics.get('sharpe_ratio')} "
            f"maxdd={attribution.metrics.get('max_drawdown')}", fg="cyan"))

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
    out = write_report(run_dir, strategy_id, md)
    click.echo(click.style(f"  report: {out}", fg="green"))


def _strategy_ids(strategy: str | None) -> list[str]:
    """Return a list of strategy IDs to process (one or both defaults)."""
    return [strategy] if strategy else ["v3_5b", "v3_5d"]


def _dispatch(strategy: str | None, do_recon: bool, do_attr: bool) -> None:
    """Dispatch audit run(s) and surface errors cleanly."""
    try:
        for sid in _strategy_ids(strategy):
            _run_and_report(sid, do_recon, do_attr)
    except AuditDBUnavailable as e:
        click.echo(click.style(
            f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.", fg="yellow"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001 - surface a clean message, not a traceback
        logger.error(f"Audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ Audit failed: {e}", fg="red"), err=True)
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


def _resolve_run_dir(run_date_str: str | None, strategy_id: str) -> Path:
    """Resolve the campaign run directory with midnight-safe resume logic.

    Resolution order:
      (a) If --run-date is given, use that dated directory unconditionally.
      (b) If any existing campaign_<strategy>.jsonl files exist under
          PROJECT_ROOT/claudedocs/audit/*/, pick the NEWEST by date-dir name
          (lexicographic ISO-8601 ordering is correct for dates) and reuse its
          directory — loud echo so the operator knows which campaign is resuming.
      (c) Otherwise use today's directory (fresh campaign).

    This prevents an overnight crash-resume from silently creating a new empty
    directory (date.today() after midnight) and restarting the 400+-sample
    campaign from scratch.

    The audit scan base is derived from ``report_output_dir()`` so that test
    patches of that function also control which directory is scanned — preventing
    the scan from hitting real campaign files in PROJECT_ROOT during unit tests.
    """
    if run_date_str is not None:
        # (a) Explicit --run-date: parse and use directly.
        try:
            run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(
                f"Invalid date format {run_date_str!r}; expected YYYY-MM-DD",
                param_hint="--run-date",
            )
        return report_output_dir(run_date=run_date)

    # (b) Scan for existing campaign files; pick the newest date-dir.
    # Derive the scan base from report_output_dir() so test mocks of that function
    # also redirect the scan, preventing tests from hitting real campaign files.
    # In production: report_output_dir() returns PROJECT_ROOT/claudedocs/audit/<date>/,
    # so .parent gives PROJECT_ROOT/claudedocs/audit/ — the correct scan root.
    audit_base = report_output_dir().parent
    campaign_pattern = f"campaign_{strategy_id}.jsonl"
    candidates = sorted(
        audit_base.glob(f"*/{strategy_id}/{campaign_pattern}"),
        key=lambda p: p.parent.parent.name,  # sort by date-dir name (ISO-8601)
        reverse=True,
    )
    if candidates:
        newest = candidates[0]
        run_dir = newest.parent.parent  # .../claudedocs/audit/<date>/
        click.echo(click.style(
            f"  Resuming existing campaign: {newest} "
            f"(pass --run-date to override)",
            fg="yellow",
        ))
        return run_dir

    # (c) Fresh campaign — use today's directory.
    return report_output_dir()


@audit.command("plateau")
@_STRATEGY_OPTION
@click.option("--joint-samples", "joint_samples", type=int, default=200,
              show_default=True, help="Number of joint +/-15% random samples.")
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel worker processes (1 = serial; each worker builds its "
                   "own BacktestRunner).")
@click.option("--oat-only", is_flag=True, default=False,
              help="Run only one-at-a-time perturbations (skip joint samples).")
@click.option("--params", multiple=True, default=(),
              help="Restrict OAT perturbations to these parameter name(s). "
                   "Repeatable; used for the smoke campaign.")
@click.option("--seed", type=int, default=42, show_default=True,
              help="RNG seed for the joint samples (recorded in the report).")
@click.option("--retry-errors", "retry_errors", is_flag=True, default=False,
              help="Re-run previously errored checkpoint rows (non-finite sharpe or "
                   "non-None error) rather than treating them as completed. Use after "
                   "a transient failure (e.g. DB blip) without deleting the JSONL.")
@click.option("--run-date", "run_date", type=str, default=None, metavar="YYYY-MM-DD",
              help="Use a specific dated run directory (YYYY-MM-DD) instead of "
                   "auto-detecting an existing campaign. Useful when resuming after "
                   "midnight without accidentally creating a new campaign in today's dir.")
def plateau_cmd(strategy, joint_samples, workers, oat_only, params, seed,
                retry_errors, run_date):
    """Module 2: parameter plateau map (perturbation campaign + robustness report)."""
    from jutsu_engine.audit import plateau as plateau_mod

    param_list = list(params) or None
    try:
        for sid in _strategy_ids(strategy):
            run_dir = _resolve_run_dir(run_date, sid)
            campaign_file = run_dir / sid / f"campaign_{sid}.jsonl"
            click.echo(
                f"[{sid}] plateau campaign "
                f"(joint={0 if oat_only else joint_samples}, workers={workers}, "
                f"seed={seed}, retry_errors={retry_errors})\n"
                f"  campaign file: {campaign_file}"
            )
            summary = plateau_mod.run_plateau(
                sid, run_dir, joint_n=joint_samples, seed=seed, workers=workers,
                oat_only=oat_only, params=param_list,
                retry_errors=retry_errors,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
            md = render_plateau_section(summary)
            out = write_plateau_report(run_dir, sid, md)
            click.echo(click.style(f"  report: {out}", fg="green"))
    except AuditDBUnavailable as e:
        click.echo(click.style(f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.",
            fg="yellow"), err=True)
        raise click.Abort()
    except RuntimeError as e:
        click.echo(click.style(f"✗ Campaign aborted: {e}", fg="red"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Plateau audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ Plateau audit failed: {e}", fg="red"), err=True)
        raise click.Abort()


def _resolve_run_dir_wfo(run_date_str: str | None, strategy_id: str) -> "Path":
    """Midnight-safe run-dir resolution for WFO campaign files.

    Mirrors _resolve_run_dir but scans for campaign_wfo_<strategy>.jsonl so a
    WFO resume never collides with a plateau (campaign_<strategy>.jsonl) file.

    Resolution order:
      (a) --run-date given → use that dated directory unconditionally.
      (b) Existing campaign_wfo_<strategy>.jsonl found → resume newest date-dir.
      (c) Fresh campaign → use today's directory.
    """
    if run_date_str is not None:
        try:
            run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(
                f"Invalid date format {run_date_str!r}; expected YYYY-MM-DD",
                param_hint="--run-date",
            )
        return report_output_dir(run_date=run_date)

    audit_base = report_output_dir().parent
    campaign_pattern = f"campaign_wfo_{strategy_id}.jsonl"
    candidates = sorted(
        audit_base.glob(f"*/{strategy_id}/{campaign_pattern}"),
        key=lambda p: p.parent.parent.name,
        reverse=True,
    )
    if candidates:
        newest = candidates[0]
        run_dir = newest.parent.parent
        click.echo(click.style(
            f"  Resuming existing WFO campaign: {newest} "
            f"(pass --run-date to override)",
            fg="yellow",
        ))
        return run_dir

    return report_output_dir()


@audit.command("wfo")
@_STRATEGY_OPTION
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel worker processes (1 = serial; each worker builds its "
                   "own BacktestRunner).")
@click.option("--windows-limit", "windows_limit", type=int, default=None,
              help="Cap the number of WFO windows (smoke mode, e.g. 2).")
@click.option("--retry-errors", "retry_errors", is_flag=True, default=False,
              help="Re-run previously errored checkpoint rows (non-finite sharpe or "
                   "non-None error) rather than treating them as completed. Use after "
                   "a transient failure (e.g. DB blip) without deleting the JSONL.")
@click.option("--run-date", "run_date", type=str, default=None, metavar="YYYY-MM-DD",
              help="Use a specific dated run directory (YYYY-MM-DD) instead of "
                   "auto-detecting an existing campaign. Useful when resuming after "
                   "midnight without accidentally creating a new campaign in today's dir.")
def wfo_cmd(strategy, workers, windows_limit, retry_errors, run_date):
    """Module 1: WFO parameter-stability study (stitched OOS curve + drift table)."""
    from jutsu_engine.audit import wfo_stability as wfo_mod

    try:
        for sid in _strategy_ids(strategy):
            run_dir = _resolve_run_dir_wfo(run_date, sid)
            campaign_file = run_dir / sid / f"campaign_wfo_{sid}.jsonl"
            click.echo(
                f"[{sid}] WFO campaign "
                f"(windows_limit={windows_limit}, workers={workers}, "
                f"retry_errors={retry_errors})\n"
                f"  campaign file: {campaign_file}"
            )
            summary = wfo_mod.run_wfo(
                sid, run_dir, windows_limit=windows_limit, workers=workers,
                retry_errors=retry_errors,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
            click.echo(click.style(
                f"  stitched OOS Sharpe={summary['stitched']['sharpe']:.4f} "
                f"alpha={summary['stitched']['alpha_vs_qqq']:.4f} "
                f"verdict={summary['overall_verdict']}",
                fg="cyan"))
            md = render_wfo_section(summary)
            out = write_wfo_report(run_dir, sid, md)
            click.echo(click.style(f"  report: {out}", fg="green"))
    except AuditDBUnavailable as e:
        click.echo(click.style(f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.",
            fg="yellow"), err=True)
        raise click.Abort()
    except RuntimeError as e:
        click.echo(click.style(f"✗ Campaign aborted: {e}", fg="red"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001
        logger.error(f"WFO audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ WFO audit failed: {e}", fg="red"), err=True)
        raise click.Abort()


def _resolve_run_dir_dsr(run_date_str: str | None, strategy_id: str) -> "Path":
    """Midnight-safe run-dir resolution for DSR campaign files.

    Mirrors _resolve_run_dir_wfo but scans campaign_dsr_<strategy>.jsonl so a DSR
    resume never collides with a plateau or WFO campaign file. Resolution order:
      (a) --run-date given → that dated directory unconditionally.
      (b) Existing campaign_dsr_<strategy>.jsonl → resume newest date-dir.
      (c) Fresh campaign → today's directory.
    """
    if run_date_str is not None:
        try:
            run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(
                f"Invalid date format {run_date_str!r}; expected YYYY-MM-DD",
                param_hint="--run-date",
            )
        return report_output_dir(run_date=run_date)

    audit_base = report_output_dir().parent
    campaign_pattern = f"campaign_dsr_{strategy_id}.jsonl"
    # Only consider directories that look like ISO date directories (YYYY-MM-DD).
    # This prevents test tmp_path siblings from being picked up as campaign dirs.
    import re as _re
    _DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
    candidates = sorted(
        (p for p in audit_base.glob(f"*/{strategy_id}/{campaign_pattern}")
         if _DATE_RE.match(p.parent.parent.name)),
        key=lambda p: p.parent.parent.name,
        reverse=True,
    )
    if candidates:
        newest = candidates[0]
        run_dir = newest.parent.parent
        click.echo(click.style(
            f"  Resuming existing DSR campaign: {newest} "
            f"(pass --run-date to override)", fg="yellow"))
        return run_dir
    return report_output_dir()


def _load_trial_inventory(strategy_id: str) -> list:
    """Read-only optimization_results inventory for a strategy (best-effort).

    Returns [] (not an error) if the DB is unavailable — the DSR campaign runs on
    the returns matrix regardless; only the inventory table is empty in that case.
    """
    from jutsu_engine.audit import db as audit_db
    try:
        engine = audit_db.get_engine()
        return audit_db.load_trial_counts(engine, strategy_like=f"%{strategy_id}%")
    except AuditDBUnavailable:
        click.echo(click.style(
            "  (optimization_results unavailable — inventory table will be empty)",
            fg="yellow"))
        return []


@audit.command("dsr")
@_STRATEGY_OPTION
@click.option("--workers", type=int, default=1, show_default=True,
              help="Parallel worker processes (1 = serial; each worker builds its "
                   "own BacktestRunner). ~243 v3_5b backtests → 4 workers ≈ ~1.7h.")
@click.option("--retry-errors", "retry_errors", is_flag=True, default=False,
              help="Re-run previously errored checkpoint rows rather than treating "
                   "them as completed. Use after a transient failure (DB blip).")
@click.option("--run-date", "run_date", type=str, default=None, metavar="YYYY-MM-DD",
              help="Use a specific dated run directory instead of auto-detecting an "
                   "existing campaign (midnight-safe resume).")
@click.option("--skip-campaign", "skip_campaign", is_flag=True, default=False,
              help="Skip the returns campaign and compute DSR/PBO from an existing "
                   "campaign JSONL (errors if rows are missing).")
@click.option("--combos-limit", "combos_limit", type=int, default=None,
              help="Cap the number of grid combos (smoke mode, e.g. 4).")
def dsr_cmd(strategy, workers, retry_errors, run_date, skip_campaign, combos_limit):
    """Module 3: selection-bias correction (DSR + PBO). v3_5b: full grid + PBO; \
v3_5d: DSR-only (family-level N)."""
    from jutsu_engine.audit import selection_bias as sb_mod

    try:
        for sid in _strategy_ids(strategy):
            run_dir = _resolve_run_dir_dsr(run_date, sid)
            campaign_file = run_dir / sid / f"campaign_dsr_{sid}.jsonl"
            click.echo(
                f"[{sid}] DSR/PBO "
                f"(workers={workers}, retry_errors={retry_errors}, "
                f"skip_campaign={skip_campaign})\n"
                f"  campaign file: {campaign_file}"
            )
            inventory = _load_trial_inventory(sid)
            summary = sb_mod.run_dsr(
                sid, run_dir, workers=workers, retry_errors=retry_errors,
                skip_campaign=skip_campaign, trial_inventory=inventory,
                combos_limit=combos_limit,
                progress=lambda msg: click.echo(click.style(f"  {msg}", fg="cyan")))
            dsr0 = summary["dsr_brackets"][0]
            click.echo(click.style(
                f"  DSR(N={dsr0['N']})={dsr0['dsr']:.4f}  "
                f"PBO={summary['pbo']['pbo']:.4f}" if summary["pbo"] is not None
                else f"  DSR(N={dsr0['N']})={dsr0['dsr']:.4f}  (DSR-only)",
                fg="cyan"))
            md = render_dsr_section(summary)
            out = write_dsr_report(run_dir, sid, md)
            click.echo(click.style(f"  report: {out}", fg="green"))
    except AuditDBUnavailable as e:
        click.echo(click.style(f"✗ Database unavailable: {e}", fg="red"), err=True)
        click.echo(click.style(
            "  The audit is read-only and needs POSTGRES_* env vars (see .env). "
            "Unit tests run without a DB; this command needs live data.",
            fg="yellow"), err=True)
        raise click.Abort()
    except RuntimeError as e:
        click.echo(click.style(f"✗ Campaign aborted: {e}", fg="red"), err=True)
        raise click.Abort()
    except Exception as e:  # noqa: BLE001
        logger.error(f"DSR audit failed: {e}", exc_info=True)
        click.echo(click.style(f"✗ DSR audit failed: {e}", fg="red"), err=True)
        raise click.Abort()


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
    import pandas as pd
    from jutsu_engine.audit.battery import (
        run_battery, evaluate_arm, summarize_battery, bootstrap_sharpe_delta_ci,
        TIER1_PORTFOLIO_START,
    )
    from jutsu_engine.audit.report import (
        render_battery_section, render_transition_section, write_battery_report,
    )
    from jutsu_engine.audit import transitions as tr

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

    # Per-episode transition profile (spec §13 / Fix 3): for each gated arm that has
    # a regime CSV (not skipped), score ALL portfolio_scored=True episodes and render
    # via render_transition_section. Stock arm first (baseline transition profile).
    # bear2022 is the only GATING episode; others are profile/diagnostic.
    transition_md = _build_transition_section(result["rows"], tr, TIER1_PORTFOLIO_START)

    md = transition_md + render_battery_section(summary)
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


def _build_transition_section(rows: list, tr, portfolio_start) -> str:
    """Build the per-episode transition profile markdown section for the battery report.

    For each arm that has a regime timeseries CSV (i.e. was not skipped), scores ALL
    episodes with portfolio_scored=True via score_episode_portfolio. Stock arm is
    emitted first (spec §13 baseline transition profile). Skipped arms and arms without
    a CSV are silently omitted from the table. bear2022 is the only GATING episode;
    the others are profile/diagnostic — they are all rendered but never drive verdict.

    The regime CSV already contains QQQ_Daily_Return (BacktestRunner output contract);
    score_episode_portfolio reads it directly alongside Strategy_Daily_Return and Vol.
    """
    import pandas as pd
    from jutsu_engine.audit.report import render_transition_section

    all_episodes = [ep for ep in tr.load_episodes() if ep.portfolio_scored]
    by_arm = {r.get("arm"): r for r in rows}

    # Stock arm first, then other non-diagnostic arms in battery order (gated only).
    from jutsu_engine.audit.battery import battery_arms
    ordered_arm_ids = (
        ["stock"]
        + [a["id"] for a in battery_arms()
           if a["gated"] and a["id"] != "stock"]
    )

    transition_rows = []
    for arm_id in ordered_arm_ids:
        row = by_arm.get(arm_id)
        if not row or row.get("skipped_arm") or not row.get("regime_timeseries_csv"):
            continue
        csv_path = row["regime_timeseries_csv"]
        try:
            ts = pd.read_csv(csv_path)
        except Exception:  # noqa: BLE001
            continue
        ts_trimmed = tr.trim_warmup(ts, portfolio_start)
        for ep in all_episodes:
            try:
                scored = tr.score_episode_portfolio(ts_trimmed, ep,
                                                    start=portfolio_start)
            except Exception:  # noqa: BLE001
                scored = {"exit_lag_days": None, "reentry_lag_days": None,
                          "drawdown_capture": None, "whipsaw_flips": 0,
                          "days_defensive": 0}
            transition_rows.append({
                "arm": arm_id,
                "episode": ep.id,
                "exit_lag_days": scored.get("exit_lag_days"),
                "reentry_lag_days": scored.get("reentry_lag_days"),
                "drawdown_capture": scored.get("drawdown_capture"),
                "whipsaw_flips": scored.get("whipsaw_flips"),
                "days_defensive": scored.get("days_defensive"),
            })

    if not transition_rows:
        return ""
    return render_transition_section(transition_rows) + "\n---\n\n"


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
