"""
Grid search analysis visualization for parameter optimization results.

Generates interactive Plotly charts for grid search analysis, including:
- Metric distributions (box plots)
- Parameter sensitivity analysis (scatter plots)
- Parameter correlation heatmaps
- Top runs comparison (radar charts)

Performance Targets:
    - Metric distributions: <1s for 100-run grid search
    - Parameter sensitivity: <2s for 100-run grid search with 12 parameters
    - Correlation matrix: <1s for 100-run grid search
    - Top runs comparison: <0.5s for top 5 runs
    - All plots: <5s total for 100-run grid search
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger('INFRA.VISUALIZATION.GRID_SEARCH')


class GridSearchPlotter:
    """
    Generate interactive Plotly charts for grid search analysis.

    Reads grid search CSV results and creates standalone HTML visualizations
    for parameter optimization analysis, including metric distributions,
    parameter sensitivity, correlations, and top runs comparison.

    Attributes:
        csv_path: Path to grid search summary CSV file
        plots_dir: Directory to save plot HTML files (defaults to csv_path/plots/)
        df: DataFrame with grid search results

    Example:
        >>> plotter = GridSearchPlotter(csv_path='output/grid_search_*/summary.csv')
        >>> plots = plotter.generate_all_plots()
        >>> # or individual plots:
        >>> plotter.generate_metric_distributions()
        >>> plotter.generate_parameter_sensitivity(target_metric='Sharpe Ratio')
    """

    # Default metrics for analysis
    DEFAULT_METRICS = [
        'Sharpe Ratio', 'Sortino Ratio', 'Calmar Ratio',
        'Annualized Return %', 'Max Drawdown', 'Win Rate %',
        'Profit Factor', 'Alpha'
    ]

    def __init__(
        self,
        csv_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None
    ):
        """
        Initialize grid search plotter.

        Args:
            csv_path: Path to grid search summary CSV file
            output_dir: Directory for output plots (default: same directory as CSV with plots/ subdir)

        Raises:
            FileNotFoundError: If csv_path does not exist
            ValueError: If CSV does not contain required columns
        """
        self.csv_path = Path(csv_path)

        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")

        # Default output directory: plots/ subdirectory alongside CSV
        if output_dir is None:
            self.plots_dir = self.csv_path.parent / 'plots'
        else:
            self.plots_dir = Path(output_dir)

        # Create output directory if it doesn't exist
        self.plots_dir.mkdir(parents=True, exist_ok=True)

        # Load data
        self.df = pd.read_csv(self.csv_path)

        # Validate required columns
        required_cols = ['Run ID']
        missing_cols = [col for col in required_cols if col not in self.df.columns]

        if missing_cols:
            raise ValueError(
                f"CSV missing required columns: {missing_cols}. "
                f"Available columns: {list(self.df.columns)}"
            )

        logger.info(
            f"Initialized GridSearchPlotter with {len(self.df)} runs from {self.csv_path}"
        )

    def generate_metric_distributions(
        self,
        metrics: Optional[List[str]] = None,
        output_filename: str = 'metric_distributions.html'
    ) -> Path:
        """
        Generate box plots for performance metric distributions.

        Shows distribution of key metrics (Sharpe, Sortino, Calmar, Drawdown, etc.)
        across all grid search runs using box plots.

        Args:
            metrics: List of metric column names to plot (default: key metrics)
            output_filename: Name for output HTML file

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <1s for 100-run grid search
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating metric distributions plot: {output_filename}")

        # Use default metrics if not specified
        if metrics is None:
            metrics = [m for m in self.DEFAULT_METRICS if m in self.df.columns]

        if not metrics:
            raise ValueError("No valid metrics found in CSV")

        # Calculate grid dimensions
        n_metrics = len(metrics)
        n_cols = 4
        n_rows = (n_metrics + n_cols - 1) // n_cols

        # Create subplots grid
        fig = make_subplots(
            rows=n_rows,
            cols=n_cols,
            subplot_titles=metrics,
            vertical_spacing=0.15,
            horizontal_spacing=0.1
        )

        # Filter out baseline run (Run ID = 0)
        data = self.df[self.df['Run ID'] != 0]

        # Add box plot for each metric
        for idx, metric in enumerate(metrics):
            row = (idx // n_cols) + 1
            col = (idx % n_cols) + 1

            metric_data = data[metric].dropna()

            fig.add_trace(
                go.Box(
                    y=metric_data,
                    name=metric,
                    boxmean='sd',  # Show mean and std dev
                    marker_color='lightblue',
                    showlegend=False,
                    hovertemplate='%{y:.3f}<extra></extra>'
                ),
                row=row, col=col
            )

            # Update y-axis title for leftmost column
            if col == 1:
                fig.update_yaxes(title_text=metric, row=row, col=col)

        # Update layout
        fig.update_layout(
            title_text='Grid Search Metric Distributions',
            height=200 * n_rows,
            template='plotly_white',
            showlegend=False
        )

        # Write to HTML
        output_path = self.plots_dir / output_filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Metric distributions plot saved to: {output_path}")
        return output_path

    def generate_parameter_sensitivity(
        self,
        target_metric: str = 'Sharpe Ratio',
        parameters: Optional[List[str]] = None,
        output_filename: str = 'parameter_sensitivity.html'
    ) -> Path:
        """
        Generate parameter sensitivity analysis plots.

        Shows scatter plots of each parameter vs. target metric to identify
        which parameters have the strongest influence on performance.

        Args:
            target_metric: Metric to optimize (default: 'Sharpe Ratio')
            parameters: List of parameter columns to analyze (default: key numeric parameters)
            output_filename: Name for output HTML file

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <2s for 100-run grid search with 12 parameters
            - File size: <200KB (using CDN Plotly.js)
        """
        logger.info(f"Generating parameter sensitivity plot: {output_filename}")

        # Validate target metric exists
        if target_metric not in self.df.columns:
            raise ValueError(f"Target metric '{target_metric}' not found in CSV")

        # Auto-detect numeric parameter columns if not specified
        if parameters is None:
            parameters = self._detect_numeric_parameters()

        if not parameters:
            raise ValueError("No numeric parameters found in CSV")

        # Limit to 12 parameters for readability
        if len(parameters) > 12:
            logger.warning(f"Limiting parameter analysis to first 12 of {len(parameters)} parameters")
            parameters = parameters[:12]

        # Calculate grid dimensions
        n_params = len(parameters)
        n_cols = 4
        n_rows = (n_params + n_cols - 1) // n_cols

        # Create subplots grid
        fig = make_subplots(
            rows=n_rows,
            cols=n_cols,
            subplot_titles=parameters,
            vertical_spacing=0.12,
            horizontal_spacing=0.1
        )

        # Filter out baseline run
        data = self.df[self.df['Run ID'] != 0]

        # Color scale based on target metric
        color_scale = 'Viridis'
        if 'Drawdown' in target_metric:
            color_scale = 'Viridis_r'  # Reverse for drawdown (lower is better)

        # Add scatter plot for each parameter
        for idx, param in enumerate(parameters):
            row = (idx // n_cols) + 1
            col = (idx % n_cols) + 1

            # Filter out missing values
            valid_mask = data[param].notna() & data[target_metric].notna()
            param_data = data[valid_mask][param]
            metric_data = data[valid_mask][target_metric]

            fig.add_trace(
                go.Scatter(
                    x=param_data,
                    y=metric_data,
                    mode='markers',
                    marker=dict(
                        size=8,
                        color=metric_data,
                        colorscale=color_scale,
                        showscale=(idx == 0),  # Show colorbar only once
                        colorbar=dict(
                            title=target_metric,
                            x=1.02,
                            len=0.3,
                            y=0.85
                        ) if idx == 0 else None
                    ),
                    hovertemplate=(
                        f'{param}: %{{x}}<br>'
                        f'{target_metric}: %{{y:.3f}}<extra></extra>'
                    ),
                    showlegend=False
                ),
                row=row, col=col
            )

            # Update axis labels
            fig.update_xaxes(title_text=param, row=row, col=col)
            if col == 1:
                fig.update_yaxes(title_text=target_metric, row=row, col=col)

        # Update layout
        fig.update_layout(
            title_text=f'Parameter Sensitivity Analysis (vs {target_metric})',
            height=200 * n_rows,
            template='plotly_white'
        )

        # Write to HTML
        output_path = self.plots_dir / output_filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Parameter sensitivity plot saved to: {output_path}")
        return output_path

    def generate_parameter_correlation_matrix(
        self,
        target_metric: str = 'Sharpe Ratio',
        output_filename: str = 'parameter_correlations.html'
    ) -> Path:
        """
        Generate correlation heatmap for parameters vs. target metric.

        Shows Pearson correlation coefficients between all numeric parameters
        and the target performance metric.

        Args:
            target_metric: Metric to analyze correlations against
            output_filename: Name for output HTML file

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <1s for 100-run grid search
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating parameter correlation matrix: {output_filename}")

        # Validate target metric exists
        if target_metric not in self.df.columns:
            raise ValueError(f"Target metric '{target_metric}' not found in CSV")

        # Filter out baseline run
        data = self.df[self.df['Run ID'] != 0]

        # Get numeric parameter columns
        param_cols = self._detect_numeric_parameters()

        if not param_cols:
            raise ValueError("No numeric parameters found in CSV")

        # Calculate correlations with target metric
        correlations = []
        for param in param_cols:
            valid_mask = data[param].notna() & data[target_metric].notna()
            if valid_mask.sum() > 1:  # Need at least 2 points for correlation
                # Check if there's variance in both variables (avoid constant values)
                param_data = data[valid_mask][param]
                metric_data = data[valid_mask][target_metric]

                if param_data.std() > 0 and metric_data.std() > 0:
                    corr = param_data.corr(metric_data)
                    # Handle NaN correlations (can occur with very small variance)
                    if not pd.isna(corr):
                        correlations.append({'Parameter': param, 'Correlation': corr})

        if not correlations:
            raise ValueError("No valid correlations could be calculated")

        corr_df = pd.DataFrame(correlations).sort_values('Correlation', ascending=False)

        # Create horizontal bar chart
        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=corr_df['Correlation'],
            y=corr_df['Parameter'],
            orientation='h',
            marker=dict(
                color=corr_df['Correlation'],
                colorscale='RdBu',
                cmin=-1,
                cmax=1,
                colorbar=dict(title='Correlation')
            ),
            hovertemplate='%{y}: %{x:.3f}<extra></extra>'
        ))

        # Update layout
        fig.update_layout(
            title=f'Parameter Correlations with {target_metric}',
            xaxis_title='Pearson Correlation Coefficient',
            yaxis_title='Parameter',
            template='plotly_white',
            height=max(400, len(param_cols) * 20),
            xaxis=dict(range=[-1, 1]),
            showlegend=False
        )

        # Write to HTML
        output_path = self.plots_dir / output_filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Parameter correlation matrix saved to: {output_path}")
        return output_path

    def generate_top_runs_comparison(
        self,
        top_n: int = 5,
        sort_by: str = 'Sharpe Ratio',
        output_filename: str = 'top_runs_comparison.html'
    ) -> Path:
        """
        Generate comparison chart for top performing runs.

        Shows radar/spider chart comparing top N runs across multiple metrics.

        Args:
            top_n: Number of top runs to compare
            sort_by: Metric to sort by for selecting top runs
            output_filename: Name for output HTML file

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <0.5s for top 5 runs
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating top runs comparison: {output_filename}")

        # Validate sort_by metric exists
        if sort_by not in self.df.columns:
            raise ValueError(f"Sort metric '{sort_by}' not found in CSV")

        # Get top N runs (exclude baseline)
        data = self.df[self.df['Run ID'] != 0].copy()

        if len(data) < top_n:
            logger.warning(f"Only {len(data)} runs available, showing all")
            top_n = len(data)

        # Sort by metric (handle drawdown which is negative)
        if 'Drawdown' in sort_by:
            top_runs = data.nsmallest(top_n, sort_by)  # Smaller drawdown is better
        else:
            top_runs = data.nlargest(top_n, sort_by)

        # Metrics for radar chart (use available metrics)
        metrics = [m for m in self.DEFAULT_METRICS if m in self.df.columns]

        if len(metrics) < 3:
            raise ValueError("Need at least 3 metrics for radar chart")

        # Normalize metrics to 0-1 scale for radar chart
        normalized = pd.DataFrame(index=top_runs.index)
        for col in metrics:
            min_val = data[col].min()
            max_val = data[col].max()

            if max_val > min_val:
                # For drawdown (negative), reverse normalization
                if 'Drawdown' in col:
                    # More negative = worse, so reverse the scale
                    normalized[col] = 1 - ((top_runs[col] - min_val) / (max_val - min_val))
                else:
                    normalized[col] = (top_runs[col] - min_val) / (max_val - min_val)
            else:
                normalized[col] = 0.5  # All values same, neutral

        # Create radar chart
        fig = go.Figure()

        # Color palette for runs
        colors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
        ]

        for idx, (run_idx, row) in enumerate(top_runs.iterrows()):
            run_id = row['Run ID']
            values = normalized.loc[run_idx, metrics].tolist()
            values.append(values[0])  # Close the radar chart

            color = colors[idx % len(colors)]

            fig.add_trace(go.Scatterpolar(
                r=values,
                theta=metrics + [metrics[0]],
                name=f'Run {run_id}',
                fill='toself',
                line=dict(color=color),
                marker=dict(color=color),
                hovertemplate='%{theta}: %{r:.2f}<extra></extra>'
            ))

        # Update layout
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 1],
                    tickformat='.1f'
                )
            ),
            title=f'Top {top_n} Runs Comparison (by {sort_by})',
            template='plotly_white',
            height=600,
            legend=dict(
                x=1.1,
                y=0.5
            )
        )

        # Write to HTML
        output_path = self.plots_dir / output_filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Top runs comparison saved to: {output_path}")
        return output_path

    def generate_all_plots(self, target_metric: str = 'Sharpe Ratio') -> Dict[str, Path]:
        """
        Generate all grid search visualization plots.

        Args:
            target_metric: Metric to use for sensitivity/correlation analysis

        Returns:
            Dictionary mapping plot type to file path:
            - 'metric_distributions': Metric distribution box plots
            - 'parameter_sensitivity': Parameter sensitivity scatter plots
            - 'parameter_correlations': Parameter correlation heatmap
            - 'top_runs': Top runs comparison radar chart

        Performance:
            - Target: <5s total for 100-run grid search
        """
        logger.info("Generating all grid search visualization plots...")

        plots = {
            'metric_distributions': self.generate_metric_distributions(),
            'parameter_sensitivity': self.generate_parameter_sensitivity(target_metric),
            'parameter_correlations': self.generate_parameter_correlation_matrix(target_metric),
            'top_runs': self.generate_top_runs_comparison(sort_by=target_metric)
        }

        logger.info(f"All grid search plots generated successfully in {self.plots_dir}")
        return plots

    def _detect_numeric_parameters(self) -> List[str]:
        """
        Auto-detect numeric parameter columns from DataFrame.

        Returns:
            List of numeric parameter column names (excluding metadata and metrics)
        """
        # Metadata columns to exclude
        metadata_cols = [
            'Run ID', 'Symbol Set', 'Portfolio Balance',
            'Treasury Trend Symbol', 'Bull Bond Symbol', 'Bear Bond Symbol'
        ]

        # Performance metrics to exclude
        metric_cols = self.DEFAULT_METRICS + [
            'Total Return %', 'Total Trades', 'Avg Win ($)', 'Avg Loss ($)'
        ]

        # Stress test columns to exclude
        stress_cols = [col for col in self.df.columns if 'stress' in col.lower()]

        # Combine exclusions
        exclude_cols = set(metadata_cols + metric_cols + stress_cols)

        # Get numeric columns
        numeric_params = []
        for col in self.df.columns:
            if col in exclude_cols:
                continue

            # Check if numeric
            if pd.api.types.is_numeric_dtype(self.df[col]):
                numeric_params.append(col)

        return numeric_params
