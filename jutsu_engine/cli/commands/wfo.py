"""
WFO CLI Command.

Provides walk-forward optimization command for rigorous strategy testing.

Example:
    jutsu wfo --config grid-configs/examples/wfo_macd_v6.yaml
    jutsu wfo --config wfo_config.yaml --output-dir custom/path
    jutsu wfo --config wfo_config.yaml --dry-run
"""
import click
from pathlib import Path

from jutsu_engine.application.wfo_runner import WFORunner, WFOConfigError


@click.command('wfo')
@click.option(
    '--config', '-c',
    required=True,
    type=click.Path(exists=True),
    help='Path to WFO configuration YAML file'
)
@click.option(
    '--output-dir', '-o',
    type=click.Path(),
    help='Custom output directory (default: output/wfo_<strategy>_<timestamp>)'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Calculate windows without running (show plan)'
)
def wfo_command(config: str, output_dir: str, dry_run: bool):
    """
    Walk-Forward Optimization - defeat curve-fitting through periodic re-optimization.

    The WFO process:
      1. Sliding Windows: Divide date range into overlapping IS/OOS periods
      2. Optimize: Run grid search on IS period, select best parameters
      3. Test: Run backtest with best params on OOS period
      4. Slide: Move window forward and repeat
      5. Analyze: Stitch OOS trades, generate equity curve, assess robustness

    Example:

        \b
        # Run full WFO
        jutsu wfo --config grid-configs/examples/wfo_macd_v6.yaml

        \b
        # Preview window plan
        jutsu wfo --config wfo_config.yaml --dry-run

        \b
        # Custom output directory
        jutsu wfo --config wfo_config.yaml --output-dir results/wfo_test

    Configuration File:

        The WFO config extends grid search format with a 'walk_forward' section:

        \b
        strategy: "MACD_Trend_v6"
        symbol_sets: [...]       # Same as grid search
        base_config: {...}       # Same as grid search
        parameters: {...}        # Same as grid search
        walk_forward:            # NEW - WFO settings
          total_start_date: "2010-01-01"
          total_end_date: "2024-12-31"
          window_size_years: 3.0
          in_sample_years: 2.5
          out_of_sample_years: 0.5
          slide_years: 0.5
          selection_metric: "sharpe_ratio"

    Output Files:

        \b
        output/wfo_<strategy>_<timestamp>/
        ├── wfo_trades_master.csv     # All OOS trades (chronological)
        ├── wfo_parameter_log.csv     # Best params per window
        ├── wfo_equity_curve.csv      # Trade-by-trade equity
        ├── wfo_summary.txt           # Performance report
        ├── wfo_config.yaml           # Copy of config used
        └── window_XXX/               # Individual window results
            ├── is_grid_search/       # Grid search outputs
            └── oos_backtest/         # Backtest outputs
    """
    click.echo("🔄 Initializing Walk-Forward Optimization...")
    click.echo()

    try:
        # Initialize WFO runner
        runner = WFORunner(config_path=config, output_dir=output_dir)

        if dry_run:
            # Show window plan without running
            click.echo("📊 WFO Window Plan")
            click.echo("=" * 60)

            windows = runner.calculate_windows()

            click.echo(f"Total Windows: {len(windows)}")
            click.echo()

            for w in windows:
                click.echo(
                    f"Window {w.window_id:3d}: "
                    f"IS {w.is_start.date()} to {w.is_end.date()} → "
                    f"OOS {w.oos_start.date()} to {w.oos_end.date()}"
                )

            click.echo()
            click.echo("Note: --dry-run mode. Use without flag to execute WFO.")
            return

        # Run WFO
        click.echo("Starting WFO execution...")
        click.echo("This may take 30 minutes to several hours depending on:")
        click.echo("  - Number of windows")
        click.echo("  - Grid search size (parameter combinations)")
        click.echo("  - Data volume")
        click.echo()

        results = runner.run()

        # Report results
        click.echo()
        click.echo("=" * 60)
        click.echo("✅ Walk-Forward Optimization Complete!")
        click.echo("=" * 60)
        click.echo()

        click.echo("Summary:")
        click.echo(f"  Total Windows: {results['num_windows']}")
        click.echo(f"  OOS Trades: {results['total_oos_trades']}")
        click.echo(f"  Final Equity: ${results['final_equity']:,.2f}")
        click.echo(f"  OOS Return: {results['oos_return_pct']:.2%}")
        click.echo()

        click.echo("Output Files:")
        for name, path in results['output_files'].items():
            click.echo(f"  {name}: {path}")
        click.echo()

        click.echo(f"📁 Output Directory: {results['output_dir']}")
        click.echo()
        click.echo("Next Steps:")
        click.echo("  1. Review wfo_equity_curve.csv for consistency")
        click.echo("  2. Check wfo_parameter_log.csv for stability")
        click.echo("  3. Analyze wfo_summary.txt for insights")
        click.echo("  4. Compare OOS performance to baseline")

    except WFOConfigError as e:
        click.echo(f"❌ Configuration Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ WFO Failed: {e}", err=True)
        raise
