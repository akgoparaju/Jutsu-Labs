#!/usr/bin/env python3
"""
Example script demonstrating grid search visualization usage.

This script shows how to generate all grid search analysis plots from
a grid search summary CSV file.

Usage:
    python scripts/example_grid_search_visualization.py <csv_path>

Example:
    python scripts/example_grid_search_visualization.py \
        output/grid_search_Hierarchical_Adaptive_v3_5b_*/tlt_summary_comparison.csv
"""
import sys
from pathlib import Path

from jutsu_engine.infrastructure.visualization import GridSearchPlotter


def main():
    """Generate all grid search visualization plots."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/example_grid_search_visualization.py <csv_path>")
        print()
        print("Example:")
        print("  python scripts/example_grid_search_visualization.py \\")
        print("    output/grid_search_*/tlt_summary_comparison.csv")
        sys.exit(1)

    csv_path = Path(sys.argv[1])

    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    print(f"Generating grid search visualizations from: {csv_path}")
    print()

    # Create plotter
    plotter = GridSearchPlotter(csv_path=csv_path)

    # Generate all plots
    plots = plotter.generate_all_plots(target_metric='Sharpe Ratio')

    # Report results
    print("Generated plots:")
    for plot_type, plot_path in plots.items():
        file_size_kb = plot_path.stat().st_size / 1024
        print(f"  {plot_type:25s} -> {plot_path.name:35s} ({file_size_kb:6.2f} KB)")

    print()
    print(f"All plots saved to: {plotter.plots_dir}")
    print()
    print("You can also generate individual plots:")
    print("  plotter.generate_metric_distributions()")
    print("  plotter.generate_parameter_sensitivity(target_metric='Alpha')")
    print("  plotter.generate_parameter_correlation_matrix(target_metric='Sortino Ratio')")
    print("  plotter.generate_top_runs_comparison(top_n=3, sort_by='Calmar Ratio')")


if __name__ == '__main__':
    main()
