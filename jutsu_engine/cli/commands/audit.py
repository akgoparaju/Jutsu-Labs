"""`jutsu audit` command group (Phase 1: live-recon + attribution).

Follows the click pattern of jutsu_engine/cli/commands/wfo.py and monte_carlo.py.
Scaffolded so Modules 1/2/3 can add subcommands later without restructuring.
Read-only: never mutates the DB; outputs markdown to claudedocs/audit/<date>/.
"""
from __future__ import annotations

import subprocess
from datetime import date

import click

from jutsu_engine.audit.config import report_output_dir, resolve_strategy
from jutsu_engine.audit.db import AuditDBUnavailable
from jutsu_engine.audit.live_recon import run_live_recon
from jutsu_engine.audit.attribution import run_attribution
from jutsu_engine.audit.report import render_report, write_report
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
