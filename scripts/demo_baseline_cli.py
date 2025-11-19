"""
Demo script to demonstrate CLI baseline display.

Shows what the CLI output looks like with baseline comparison.
"""
from jutsu_engine.cli.main import _display_baseline_section, _display_comparison_section
import click

# Sample results with baseline (outperformance)
results_outperformance = {
    'total_return': 0.50,  # 50%
    'annualized_return': 0.1587,
    'sharpe_ratio': 2.78,
    'max_drawdown': -0.125,
    'win_rate': 0.65,
    'total_trades': 42,
    'final_value': 150000,
    'config': {
        'initial_capital': 100000
    }
}

baseline_outperformance = {
    'baseline_symbol': 'QQQ',
    'baseline_final_value': 125000,
    'baseline_total_return': 0.25,  # 25%
    'baseline_annualized_return': 0.08,  # 8%
    'alpha': 2.00
}

# Sample results with underperformance
results_underperformance = {
    'total_return': 0.10,  # 10%
    'annualized_return': 0.03,
    'sharpe_ratio': 1.2,
    'max_drawdown': -0.15,
    'win_rate': 0.55,
    'total_trades': 30,
    'final_value': 110000,
    'config': {
        'initial_capital': 100000
    }
}

baseline_underperformance = {
    'baseline_symbol': 'QQQ',
    'baseline_final_value': 125000,
    'baseline_total_return': 0.25,  # 25%
    'baseline_annualized_return': 0.08,
    'alpha': 0.40
}

# Sample results with alpha = None (baseline return = 0)
results_alpha_none = {
    'total_return': 0.50,
    'annualized_return': 0.1587,
    'sharpe_ratio': 2.78,
    'max_drawdown': -0.125,
    'win_rate': 0.65,
    'total_trades': 42,
    'final_value': 150000,
    'config': {
        'initial_capital': 100000
    }
}

baseline_alpha_none = {
    'baseline_symbol': 'QQQ',
    'baseline_final_value': 100000,
    'baseline_total_return': 0.0,  # 0%
    'baseline_annualized_return': 0.0,
    'alpha': None,
    'alpha_note': 'Cannot calculate ratio (baseline return = 0)'
}


def demo_outperformance():
    """Demo outperformance scenario."""
    click.echo("\n" + "=" * 60)
    click.echo("SCENARIO 1: OUTPERFORMANCE (Alpha > 1)")
    click.echo("=" * 60 + "\n")

    _display_baseline_section(baseline_outperformance)
    click.echo("\n" + "-" * 60 + "\n")

    click.echo("STRATEGY (MACD_Trend_v6):")
    click.echo(f"  Initial Capital:    ${results_outperformance['config']['initial_capital']:,.2f}")
    click.echo(f"  Final Value:        ${results_outperformance['final_value']:,.2f}")
    click.echo(f"  Total Return:       {results_outperformance['total_return']:.2%}")
    click.echo(f"  Annualized Return:  {results_outperformance['annualized_return']:.2%}")
    click.echo(f"  Sharpe Ratio:       {results_outperformance['sharpe_ratio']:.2f}")
    click.echo(f"  Max Drawdown:       {results_outperformance['max_drawdown']:.2%}")
    click.echo(f"  Win Rate:           {results_outperformance['win_rate']:.2%}")
    click.echo(f"  Total Trades:       {results_outperformance['total_trades']}")

    click.echo("\n" + "-" * 60 + "\n")
    _display_comparison_section(results_outperformance, baseline_outperformance)
    click.echo("\n" + "=" * 60)


def demo_underperformance():
    """Demo underperformance scenario."""
    click.echo("\n" + "=" * 60)
    click.echo("SCENARIO 2: UNDERPERFORMANCE (Alpha < 1)")
    click.echo("=" * 60 + "\n")

    _display_baseline_section(baseline_underperformance)
    click.echo("\n" + "-" * 60 + "\n")

    click.echo("STRATEGY (MACD_Trend_v6):")
    click.echo(f"  Initial Capital:    ${results_underperformance['config']['initial_capital']:,.2f}")
    click.echo(f"  Final Value:        ${results_underperformance['final_value']:,.2f}")
    click.echo(f"  Total Return:       {results_underperformance['total_return']:.2%}")
    click.echo(f"  Annualized Return:  {results_underperformance['annualized_return']:.2%}")
    click.echo(f"  Sharpe Ratio:       {results_underperformance['sharpe_ratio']:.2f}")
    click.echo(f"  Max Drawdown:       {results_underperformance['max_drawdown']:.2%}")
    click.echo(f"  Win Rate:           {results_underperformance['win_rate']:.2%}")
    click.echo(f"  Total Trades:       {results_underperformance['total_trades']}")

    click.echo("\n" + "-" * 60 + "\n")
    _display_comparison_section(results_underperformance, baseline_underperformance)
    click.echo("\n" + "=" * 60)


def demo_alpha_none():
    """Demo alpha = None scenario (baseline return = 0)."""
    click.echo("\n" + "=" * 60)
    click.echo("SCENARIO 3: ALPHA = None (Baseline Return = 0)")
    click.echo("=" * 60 + "\n")

    _display_baseline_section(baseline_alpha_none)
    click.echo("\n" + "-" * 60 + "\n")

    click.echo("STRATEGY (MACD_Trend_v6):")
    click.echo(f"  Initial Capital:    ${results_alpha_none['config']['initial_capital']:,.2f}")
    click.echo(f"  Final Value:        ${results_alpha_none['final_value']:,.2f}")
    click.echo(f"  Total Return:       {results_alpha_none['total_return']:.2%}")
    click.echo(f"  Annualized Return:  {results_alpha_none['annualized_return']:.2%}")
    click.echo(f"  Sharpe Ratio:       {results_alpha_none['sharpe_ratio']:.2f}")
    click.echo(f"  Max Drawdown:       {results_alpha_none['max_drawdown']:.2%}")
    click.echo(f"  Win Rate:           {results_alpha_none['win_rate']:.2%}")
    click.echo(f"  Total Trades:       {results_alpha_none['total_trades']}")

    click.echo("\n(No comparison section - alpha is None)")
    click.echo("\n" + "=" * 60)


def demo_no_baseline():
    """Demo scenario without baseline."""
    click.echo("\n" + "=" * 60)
    click.echo("SCENARIO 4: NO BASELINE AVAILABLE")
    click.echo("=" * 60 + "\n")

    click.echo("STRATEGY (MACD_Trend_v6):")
    click.echo(f"  Initial Capital:    ${results_outperformance['config']['initial_capital']:,.2f}")
    click.echo(f"  Final Value:        ${results_outperformance['final_value']:,.2f}")
    click.echo(f"  Total Return:       {results_outperformance['total_return']:.2%}")
    click.echo(f"  Annualized Return:  {results_outperformance['annualized_return']:.2%}")
    click.echo(f"  Sharpe Ratio:       {results_outperformance['sharpe_ratio']:.2f}")
    click.echo(f"  Max Drawdown:       {results_outperformance['max_drawdown']:.2%}")
    click.echo(f"  Win Rate:           {results_outperformance['win_rate']:.2%}")
    click.echo(f"  Total Trades:       {results_outperformance['total_trades']}")

    click.echo("\n(No baseline section - baseline not available)")
    click.echo("\n" + "=" * 60)


if __name__ == '__main__':
    click.echo("=" * 60)
    click.echo("CLI BASELINE DISPLAY DEMONSTRATION")
    click.echo("=" * 60)

    demo_outperformance()
    demo_underperformance()
    demo_alpha_none()
    demo_no_baseline()

    click.echo("\n" + "=" * 60)
    click.echo("DEMONSTRATION COMPLETE")
    click.echo("=" * 60)
