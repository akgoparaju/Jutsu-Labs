"""
Monte Carlo CLI command - Bootstrap resampling simulation for strategy robustness.

Implements Monte Carlo simulation to test if strategy performance is due to
skill or luck by shuffling trade order.

Author: Jutsu Labs
Date: 2025-11-10
"""

import click
import yaml
from pathlib import Path
from decimal import Decimal
from typing import Optional

from jutsu_engine.application.monte_carlo_simulator import (
    MonteCarloSimulator,
    MonteCarloConfig
)
from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('CLI.MONTE_CARLO', log_to_console=True)


@click.command()
@click.option(
    '--config',
    '-c',
    required=True,
    type=click.Path(exists=True),
    help='Path to Monte Carlo YAML configuration'
)
@click.option(
    '--input',
    '-i',
    type=click.Path(exists=True),
    help='Override input file path (monte_carlo_input.csv)'
)
@click.option(
    '--output',
    '-o',
    type=click.Path(),
    help='Override output directory'
)
@click.option(
    '--iterations',
    '-n',
    type=int,
    help='Override number of iterations (default: 10000)'
)
@click.option(
    '--verbose',
    '-v',
    is_flag=True,
    help='Enable debug logging'
)
def monte_carlo(
    config: str,
    input: Optional[str],
    output: Optional[str],
    iterations: Optional[int],
    verbose: bool
):
    """
    Run Monte Carlo simulation on WFO results.

    Tests strategy robustness by shuffling trade order to reveal if performance
    is due to skill (consistent across sequences) or luck (specific sequence).

    Example:
        # Basic usage
        jutsu monte-carlo --config config/examples/monte_carlo_config.yaml

        # Override iterations
        jutsu monte-carlo -c config.yaml --iterations 5000

        # Override input/output
        jutsu monte-carlo -c config.yaml --input wfo_output/monte_carlo_input.csv --output results/

        # Verbose logging
        jutsu monte-carlo -c config.yaml --verbose
    """
    # Set log level
    if verbose:
        import logging
        logger.setLevel(logging.DEBUG)

    click.echo("=" * 60)
    click.echo("Monte Carlo Simulation")
    click.echo("=" * 60)

    # Load configuration
    click.echo(f"\nLoading config: {config}")
    try:
        with open(config, 'r') as f:
            config_data = yaml.safe_load(f)

        # Extract monte_carlo section
        if 'monte_carlo' not in config_data:
            raise ValueError("Configuration must contain 'monte_carlo' section")

        mc_config = config_data['monte_carlo']

        # Build MonteCarloConfig
        input_file = Path(input) if input else Path(mc_config['input_file'])
        output_directory = Path(output) if output else Path(mc_config['output_directory'])
        num_iterations = iterations if iterations is not None else mc_config.get('iterations', 10000)
        initial_capital = Decimal(str(mc_config.get('initial_capital', 10000)))
        random_seed = mc_config.get('random_seed')

        # Analysis configuration
        analysis_config = mc_config.get('analysis', {})
        percentiles = analysis_config.get('percentiles', [5, 25, 50, 75, 95])
        confidence_level = analysis_config.get('confidence_level', 0.95)
        risk_thresholds = analysis_config.get('risk_of_ruin_thresholds', [30, 40, 50])

        # Performance configuration
        perf_config = mc_config.get('performance', {})
        parallel = perf_config.get('parallel', False)
        num_workers = perf_config.get('num_workers')

        # Create config object
        simulator_config = MonteCarloConfig(
            input_file=input_file,
            output_directory=output_directory,
            iterations=num_iterations,
            initial_capital=initial_capital,
            random_seed=random_seed,
            percentiles=percentiles,
            confidence_level=confidence_level,
            risk_thresholds=risk_thresholds,
            parallel=parallel,
            num_workers=num_workers
        )

    except Exception as e:
        click.echo(click.style(f"✗ Configuration error: {e}", fg='red'))
        logger.error(f"Failed to load config: {e}", exc_info=True)
        raise click.Abort()

    # Display configuration summary
    click.echo(f"\nInput File: {simulator_config.input_file}")
    click.echo(f"Output Directory: {simulator_config.output_directory}")
    click.echo(f"Iterations: {simulator_config.iterations:,}")
    click.echo(f"Initial Capital: ${simulator_config.initial_capital:,.2f}")
    if simulator_config.random_seed is not None:
        click.echo(f"Random Seed: {simulator_config.random_seed} (reproducible)")

    # Confirm if > 50000 iterations
    if simulator_config.iterations > 50000:
        click.echo(f"\n⚠  Warning: {simulator_config.iterations:,} iterations may take several minutes")
        if not click.confirm("Continue?"):
            click.echo("Aborted.")
            return

    # Run simulation
    click.echo("\n" + "=" * 60)
    click.echo("Running Bootstrap Simulation")
    click.echo("=" * 60)
    click.echo()  # Blank line before progress bar

    try:
        simulator = MonteCarloSimulator(simulator_config)
        results = simulator.run()
    except Exception as e:
        click.echo(click.style(f"\n✗ Simulation failed: {e}", fg='red'))
        logger.error(f"Monte Carlo execution failed: {e}", exc_info=True)
        raise click.Abort()

    # Display results
    click.echo("\n" + "=" * 60)
    click.echo(click.style("✓ Monte Carlo Simulation Complete!", fg='green'))
    click.echo("=" * 60)

    # Analysis summary
    analysis = results['analysis']

    click.echo("\nPercentile Analysis - Final Equity:")
    percentiles_equity = analysis['percentiles']['Final_Equity']
    for p in simulator_config.percentiles:
        value = percentiles_equity[p]
        click.echo(f"  {p:3d}th: ${value:>10,.2f}")

    click.echo("\nRisk of Ruin:")
    risk_of_ruin = analysis['risk_of_ruin']
    for threshold in simulator_config.risk_thresholds:
        risk_pct = risk_of_ruin[threshold]
        # Color code based on risk level
        if risk_pct < 5:
            color = 'green'
        elif risk_pct < 15:
            color = 'yellow'
        else:
            color = 'red'
        click.secho(f"  >{threshold}% loss: {risk_pct:>5.1f}% of simulations", fg=color)

    # Original result percentile
    if analysis.get('original_percentile') is not None:
        percentile = analysis['original_percentile']
        click.echo(f"\nOriginal Result Ranking: {percentile:.1f}th percentile")

        # Interpretation
        if percentile < 30:
            interp = "Below average - possible unlucky sequence"
        elif percentile < 60:
            interp = "Near median - likely reflects true strategy edge"
        elif percentile < 85:
            interp = "Above average - favorable sequence"
        else:
            interp = "Top tier - very lucky sequence"

        click.echo(f"Interpretation: {interp}")

    # Execution time
    duration = results['duration_seconds']
    iterations_per_sec = simulator_config.iterations / duration if duration > 0 else 0
    click.echo(f"\nExecution Time: {duration:.1f}s ({iterations_per_sec:.0f} iterations/sec)")

    # Output files
    click.echo(f"\nOutput Files:")
    click.echo(f"  Results CSV:  {results['results_file']}")
    click.echo(f"  Summary Text: {results['summary_file']}")

    click.echo("\n" + "=" * 60)
    click.echo("Next Steps:")
    click.echo("  1. Review monte_carlo_summary.txt for detailed interpretation")
    click.echo("  2. Analyze distribution in monte_carlo_results.csv")
    click.echo("  3. Consider live paper trading if risk is acceptable")
    click.echo("=" * 60)
