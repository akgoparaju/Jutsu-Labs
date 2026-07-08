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
    candidates = sorted(
        audit_base.glob(f"*/{strategy_id}/{campaign_pattern}"),
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
