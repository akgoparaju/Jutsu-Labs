"""
Visualization tools for optimization results.

Generates heatmaps, convergence plots, and walk-forward performance charts.
"""
from typing import Dict, List, Any, Optional
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd

from jutsu_engine.utils.logging_config import setup_logger

logger = setup_logger('APP.OPTIMIZATION.VIZ')


class OptimizationVisualizer:
    """
    Visualization tools for optimization analysis.

    Provides methods for creating:
    - Heatmaps for grid search results
    - Convergence plots for genetic algorithms
    - Walk-forward performance charts
    - Parameter sensitivity analysis

    Example:
        >>> viz = OptimizationVisualizer()
        >>>
        >>> # Plot grid search heatmap
        >>> viz.plot_grid_heatmap(
        ...     grid_results,
        ...     param_x='short_period',
        ...     param_y='long_period'
        ... )
        >>>
        >>> # Plot genetic algorithm convergence
        >>> viz.plot_convergence(genetic_results['convergence_history'])
    """

    def __init__(self, style: str = 'seaborn-v0_8-darkgrid'):
        """
        Initialize visualizer.

        Args:
            style: Matplotlib style to use
        """
        try:
            plt.style.use(style)
        except:
            logger.warning(f"Style '{style}' not available, using default")

        self.style = style
        sns.set_palette("husl")

    def plot_grid_heatmap(
        self,
        heatmap_data: Dict[str, Any],
        title: Optional[str] = None,
        figsize: tuple = (10, 8),
        cmap: str = 'RdYlGn',
        save_path: Optional[str] = None
    ) -> plt.Figure:
        """
        Plot heatmap for 2D grid search results.

        Args:
            heatmap_data: Data from GridSearchOptimizer.get_heatmap_data()
            title: Plot title
            figsize: Figure size (width, height)
            cmap: Colormap name
            save_path: Path to save figure (optional)

        Returns:
            Matplotlib figure

        Example:
            >>> heatmap_data = optimizer.get_heatmap_data('short_period', 'long_period')
            >>> viz.plot_grid_heatmap(heatmap_data)
        """
        x_values = heatmap_data['x_values']
        y_values = heatmap_data['y_values']
        z_values = np.array(heatmap_data['z_values'])

        fig, ax = plt.subplots(figsize=figsize)

        # Create heatmap
        sns.heatmap(
            z_values,
            xticklabels=x_values,
            yticklabels=y_values,
            cmap=cmap,
            annot=True,
            fmt='.2f',
            cbar_kws={'label': heatmap_data['z_label']},
            ax=ax
        )

        ax.set_xlabel(heatmap_data['x_label'])
        ax.set_ylabel(heatmap_data['y_label'])

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"{heatmap_data['z_label']} by Parameters")

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Saved heatmap to {save_path}")

        return fig

    def plot_convergence(
        self,
        logbook: Any,
        title: str = "Genetic Algorithm Convergence",
        figsize: tuple = (12, 6),
        save_path: Optional[str] = None
    ) -> plt.Figure:
        """
        Plot convergence history for genetic algorithm.

        Args:
            logbook: DEAP logbook from genetic algorithm
            title: Plot title
            figsize: Figure size
            save_path: Path to save figure

        Returns:
            Matplotlib figure
        """
        # Extract statistics from logbook
        gen = [record['gen'] for record in logbook]
        avg = [record['avg'] for record in logbook]
        max_vals = [record['max'] for record in logbook]
        min_vals = [record['min'] for record in logbook]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize)

        # Plot fitness over generations
        ax1.plot(gen, avg, 'b-', label='Average', linewidth=2)
        ax1.plot(gen, max_vals, 'g-', label='Best', linewidth=2)
        ax1.plot(gen, min_vals, 'r--', label='Worst', alpha=0.5)
        ax1.fill_between(gen, min_vals, max_vals, alpha=0.1)
        ax1.set_xlabel('Generation')
        ax1.set_ylabel('Fitness')
        ax1.set_title(title)
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Plot improvement rate
        improvements = [max_vals[i] - max_vals[i-1] for i in range(1, len(max_vals))]
        ax2.plot(gen[1:], improvements, 'purple', linewidth=2)
        ax2.axhline(y=0, color='black', linestyle='--', alpha=0.3)
        ax2.set_xlabel('Generation')
        ax2.set_ylabel('Improvement from Previous Generation')
        ax2.set_title('Generation-to-Generation Improvement')
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Saved convergence plot to {save_path}")

        return fig

    def plot_walk_forward(
        self,
        wf_results: Dict[str, Any],
        metric: str = 'sharpe_ratio',
        title: Optional[str] = None,
        figsize: tuple = (14, 6),
        save_path: Optional[str] = None
    ) -> plt.Figure:
        """
        Plot walk-forward analysis results.

        Args:
            wf_results: Results from WalkForwardAnalyzer.analyze()
            metric: Metric to plot ('sharpe_ratio', 'total_return', etc.)
            title: Plot title
            figsize: Figure size
            save_path: Path to save figure

        Returns:
            Matplotlib figure
        """
        oos_results = wf_results['out_sample_results']

        # Extract data
        window_nums = list(range(1, len(oos_results) + 1))
        metric_values = [r['metrics'][metric] for r in oos_results]
        window_labels = [
            f"{r['window_start'].strftime('%Y-%m')} to {r['window_end'].strftime('%Y-%m')}"
            for r in oos_results
        ]

        fig, ax = plt.subplots(figsize=figsize)

        # Plot bars
        bars = ax.bar(window_nums, metric_values, alpha=0.7)

        # Color bars based on value
        colors = ['green' if v > 0 else 'red' for v in metric_values]
        for bar, color in zip(bars, colors):
            bar.set_color(color)

        # Add average line
        avg_value = sum(metric_values) / len(metric_values)
        ax.axhline(y=avg_value, color='blue', linestyle='--', linewidth=2,
                   label=f'Average: {avg_value:.2f}')

        ax.set_xlabel('Window Number')
        ax.set_ylabel(metric.replace('_', ' ').title())
        ax.set_xticks(window_nums)
        ax.set_xticklabels(window_labels, rotation=45, ha='right')

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f'Walk-Forward Out-of-Sample {metric.replace("_", " ").title()}')

        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Saved walk-forward plot to {save_path}")

        return fig

    def plot_parameter_sensitivity(
        self,
        results: List[Dict[str, Any]],
        parameter: str,
        objective: str = 'sharpe_ratio',
        title: Optional[str] = None,
        figsize: tuple = (10, 6),
        save_path: Optional[str] = None
    ) -> plt.Figure:
        """
        Plot parameter sensitivity analysis.

        Shows how objective varies with a single parameter.

        Args:
            results: List of optimization results
            parameter: Parameter name to analyze
            objective: Objective metric name
            title: Plot title
            figsize: Figure size
            save_path: Path to save figure

        Returns:
            Matplotlib figure
        """
        # Extract data
        param_values = [r['parameters'][parameter] for r in results]
        obj_values = [r['objective'] for r in results]

        # Create DataFrame for easier grouping
        df = pd.DataFrame({
            'parameter': param_values,
            'objective': obj_values
        })

        # Group by parameter value and calculate statistics
        grouped = df.groupby('parameter')['objective'].agg(['mean', 'std', 'count'])

        fig, ax = plt.subplots(figsize=figsize)

        # Plot mean with error bars
        ax.errorbar(
            grouped.index,
            grouped['mean'],
            yerr=grouped['std'],
            fmt='o-',
            linewidth=2,
            markersize=8,
            capsize=5,
            label='Mean ± Std'
        )

        # Scatter all points with transparency
        ax.scatter(
            param_values,
            obj_values,
            alpha=0.3,
            s=30,
            label='Individual Results'
        )

        ax.set_xlabel(parameter.replace('_', ' ').title())
        ax.set_ylabel(objective.replace('_', ' ').title())

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f'{objective.replace("_", " ").title()} vs {parameter.replace("_", " ").title()}')

        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Saved sensitivity plot to {save_path}")

        return fig

    def plot_comparison(
        self,
        results_dict: Dict[str, List[Dict[str, Any]]],
        objective: str = 'sharpe_ratio',
        title: str = "Optimization Results Comparison",
        figsize: tuple = (10, 6),
        save_path: Optional[str] = None
    ) -> plt.Figure:
        """
        Plot comparison of multiple optimization runs.

        Args:
            results_dict: Dict mapping run names to result lists
            objective: Objective metric to compare
            title: Plot title
            figsize: Figure size
            save_path: Path to save figure

        Returns:
            Matplotlib figure
        """
        fig, ax = plt.subplots(figsize=figsize)

        # Create box plot data
        data = []
        labels = []

        for name, results in results_dict.items():
            obj_values = [r['objective'] for r in results]
            data.append(obj_values)
            labels.append(name)

        bp = ax.boxplot(data, labels=labels, patch_artist=True)

        # Color boxes
        colors = sns.color_palette("husl", len(data))
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.set_ylabel(objective.replace('_', ' ').title())
        ax.set_title(title)
        ax.grid(True, alpha=0.3, axis='y')

        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Saved comparison plot to {save_path}")

        return fig
