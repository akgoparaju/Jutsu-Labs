"""
Equity curve and drawdown plotting for backtest results.

Generates interactive Plotly charts for portfolio performance visualization,
including equity curves with baseline comparison, drawdown analysis, position
allocation tracking, and returns distribution.

Performance Targets:
    - Equity curve generation: <1s for 4000-bar backtest
    - Drawdown generation: <1s for 4000-bar backtest
    - Position allocation: <1s for 4000-bar backtest
    - Returns distribution: <0.5s for 4000-bar backtest
    - Dashboard: <2s for 4000-bar backtest
    - File size: <100KB per HTML (using CDN Plotly.js)
"""
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger('INFRA.VISUALIZATION')


class EquityPlotter:
    """
    Generate interactive Plotly charts for backtest equity curves and drawdowns.

    Reads CSV backtest results and creates standalone HTML visualizations
    with hover tooltips, zoom, and trace selection capabilities.

    Attributes:
        csv_path: Path to backtest CSV file
        output_dir: Directory to save plot HTML files (defaults to csv_path/plots/)

    Example:
        >>> plotter = EquityPlotter(csv_path='output/backtest_STRATEGY/results.csv')
        >>> equity_path = plotter.generate_equity_curve()
        >>> drawdown_path = plotter.generate_drawdown()
    """

    def __init__(
        self,
        csv_path: Path,
        output_dir: Optional[Path] = None
    ):
        """
        Initialize equity plotter with CSV data path.

        Args:
            csv_path: Path to backtest CSV results file
            output_dir: Optional custom output directory for plots
                       (defaults to csv_path.parent / 'plots')

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

        # Maintain backward compatibility
        self.output_dir = self.plots_dir

        # Create output directory if it doesn't exist
        self.plots_dir.mkdir(parents=True, exist_ok=True)

        # Load data and validate columns
        self.df = self._load_and_validate_data()
        self._df = self.df  # Backward compatibility

        logger.info(
            f"Initialized EquityPlotter with {len(self.df)} bars from {self.csv_path}"
        )

    def _load_and_validate_data(self) -> pd.DataFrame:
        """
        Load CSV data and validate required columns exist.

        Returns:
            DataFrame with parsed dates and validated columns

        Raises:
            ValueError: If required columns are missing
        """
        df = pd.read_csv(self.csv_path)

        # Required columns for equity curve
        required_cols = ['Date', 'Portfolio_Total_Value']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            raise ValueError(
                f"CSV missing required columns: {missing_cols}. "
                f"Available columns: {list(df.columns)}"
            )

        # Parse dates
        df['Date'] = pd.to_datetime(df['Date'])

        # Log available baseline columns
        baseline_cols = [col for col in df.columns if 'Baseline' in col or 'BuyHold' in col]
        if baseline_cols:
            logger.info(f"Found baseline columns: {baseline_cols}")
        else:
            logger.warning("No baseline columns found in CSV")

        # Detect baseline columns dynamically for configurable baseline_symbol support
        baseline_value_cols = [col for col in df.columns
                               if col.startswith('Baseline_') and col.endswith('_Value')]
        baseline_return_cols = [col for col in df.columns
                                if col.startswith('Baseline_') and col.endswith('_Return_Pct')]

        # Store baseline column names as instance attributes
        self.baseline_value_col = baseline_value_cols[0] if baseline_value_cols else None
        self.baseline_return_col = baseline_return_cols[0] if baseline_return_cols else None

        # Extract baseline symbol name from column (e.g., "Baseline_QQQ_Value" → "QQQ")
        if self.baseline_value_col:
            self.baseline_symbol = self.baseline_value_col.replace('Baseline_', '').replace('_Value', '')
            logger.info(f"Detected baseline symbol: {self.baseline_symbol}")
        else:
            self.baseline_symbol = None

        return df

    def _calculate_drawdown(self, series: pd.Series) -> pd.Series:
        """
        Calculate drawdown series from portfolio values.

        Drawdown is the percentage decline from the running maximum (peak).

        Args:
            series: Series of portfolio values

        Returns:
            Series of drawdown percentages (negative values)

        Example:
            >>> values = pd.Series([100, 110, 105, 115])
            >>> drawdowns = plotter._calculate_drawdown(values)
            >>> # Returns: [0.0, 0.0, -4.55, 0.0] (% from peak)
        """
        # Running maximum (peak)
        peak = series.cummax()

        # Drawdown as percentage from peak
        drawdown = ((series - peak) / peak * 100).fillna(0)

        return drawdown

    def generate_equity_curve(
        self,
        filename: str = 'equity_curve.html',
        include_baseline: bool = True
    ) -> Path:
        """
        Generate interactive equity curve plot with portfolio vs. baseline.

        Creates a time-series line chart showing portfolio value evolution
        compared to baseline (Buy & Hold) performance.

        Args:
            filename: Output filename for HTML plot
            include_baseline: Whether to include baseline comparison traces

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <1s for 4000-bar backtest
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating equity curve plot: {filename}")

        fig = go.Figure()

        # Add portfolio equity trace
        fig.add_trace(go.Scatter(
            x=self._df['Date'],
            y=self._df['Portfolio_Total_Value'],
            mode='lines',
            name='Portfolio',
            line=dict(color='#1f77b4', width=2),
            hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Portfolio: $%{y:,.2f}<extra></extra>'
        ))

        # Add baseline traces if available and requested
        if include_baseline:
            # Use dynamically detected baseline column (supports configurable baseline_symbol)
            if self.baseline_value_col:
                fig.add_trace(go.Scatter(
                    x=self._df['Date'],
                    y=self._df[self.baseline_value_col],
                    mode='lines',
                    name=f'Baseline ({self.baseline_symbol})',
                    line=dict(color='#ff7f0e', width=1.5, dash='dot'),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Baseline: $%{y:,.2f}<extra></extra>'
                ))

            # Legacy BuyHold column support (if exists)
            if 'BuyHold_QQQ_Value' in self._df.columns:
                fig.add_trace(go.Scatter(
                    x=self._df['Date'],
                    y=self._df['BuyHold_QQQ_Value'],
                    mode='lines',
                    name='Buy & Hold (QQQ)',
                    line=dict(color='#2ca02c', width=1.5, dash='dash'),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Buy & Hold: $%{y:,.2f}<extra></extra>'
                ))

        # Configure layout with interactivity
        fig.update_layout(
            title='Portfolio Equity Curve',
            xaxis_title='Date',
            yaxis_title='Portfolio Value ($)',
            hovermode='x unified',
            template='plotly_white',
            legend=dict(
                x=0.01,
                y=0.99,
                bgcolor='rgba(255, 255, 255, 0.8)',
                bordercolor='rgba(0, 0, 0, 0.2)',
                borderwidth=1
            ),
            xaxis=dict(
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="YTD", step="year", stepmode="todate"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(step="all", label="All")
                    ])
                )
            )
        )

        # Write to HTML with CDN Plotly.js for small file size
        output_path = self.output_dir / filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Equity curve plot saved to: {output_path}")
        return output_path

    def generate_drawdown(
        self,
        filename: str = 'drawdown.html',
        include_baseline: bool = True
    ) -> Path:
        """
        Generate underwater drawdown plot showing peak-to-trough declines.

        Creates an area chart displaying drawdown percentages over time,
        showing periods when portfolio is below its peak value.

        Args:
            filename: Output filename for HTML plot
            include_baseline: Whether to include baseline drawdown comparison

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <1s for 4000-bar backtest
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating drawdown plot: {filename}")

        # Calculate drawdowns
        portfolio_dd = self._calculate_drawdown(self._df['Portfolio_Total_Value'])

        fig = go.Figure()

        # Add portfolio drawdown trace (filled area)
        fig.add_trace(go.Scatter(
            x=self._df['Date'],
            y=portfolio_dd,
            mode='lines',
            name='Portfolio Drawdown',
            fill='tozeroy',
            line=dict(color='#d62728', width=1.5),
            fillcolor='rgba(214, 39, 40, 0.3)',
            hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Drawdown: %{y:.2f}%<extra></extra>'
        ))

        # Add baseline drawdowns if available and requested
        if include_baseline:
            # Use dynamically detected baseline column (supports configurable baseline_symbol)
            if self.baseline_value_col:
                baseline_dd = self._calculate_drawdown(self._df[self.baseline_value_col])
                fig.add_trace(go.Scatter(
                    x=self._df['Date'],
                    y=baseline_dd,
                    mode='lines',
                    name=f'Baseline ({self.baseline_symbol}) Drawdown',
                    line=dict(color='#ff7f0e', width=1, dash='dot'),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Baseline DD: %{y:.2f}%<extra></extra>'
                ))

            # Legacy BuyHold column support (if exists)
            if 'BuyHold_QQQ_Value' in self._df.columns:
                buyhold_dd = self._calculate_drawdown(self._df['BuyHold_QQQ_Value'])
                fig.add_trace(go.Scatter(
                    x=self._df['Date'],
                    y=buyhold_dd,
                    mode='lines',
                    name='Buy & Hold (QQQ) Drawdown',
                    line=dict(color='#2ca02c', width=1, dash='dash'),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Buy & Hold DD: %{y:.2f}%<extra></extra>'
                ))

        # Configure layout
        fig.update_layout(
            title='Portfolio Drawdown (Underwater Chart)',
            xaxis_title='Date',
            yaxis_title='Drawdown (%)',
            hovermode='x unified',
            template='plotly_white',
            legend=dict(
                x=0.01,
                y=0.01,
                bgcolor='rgba(255, 255, 255, 0.8)',
                bordercolor='rgba(0, 0, 0, 0.2)',
                borderwidth=1
            ),
            xaxis=dict(
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="YTD", step="year", stepmode="todate"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(step="all", label="All")
                    ])
                )
            ),
            yaxis=dict(
                zeroline=True,
                zerolinecolor='rgba(0, 0, 0, 0.3)',
                zerolinewidth=1
            )
        )

        # Write to HTML
        output_path = self.output_dir / filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Drawdown plot saved to: {output_path}")
        return output_path

    def generate_positions(
        self,
        filename: str = 'position_allocation.html'
    ) -> Path:
        """
        Generate position allocation stacked area chart.

        Creates a stacked area chart showing position values over time,
        enabling visualization of portfolio composition changes.

        Args:
            filename: Output filename for HTML plot

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <1s for 4000-bar backtest
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating position allocation plot: {filename}")

        # Extract position value columns (ends with '_Value')
        # Exclude portfolio total and any baseline columns (dynamic for configurable baseline_symbol)
        exclude_cols = ['Portfolio_Total_Value']
        if self.baseline_value_col:
            exclude_cols.append(self.baseline_value_col)
        # Legacy BuyHold support
        if 'BuyHold_QQQ_Value' in self.df.columns:
            exclude_cols.append('BuyHold_QQQ_Value')

        position_cols = [
            col for col in self.df.columns
            if col.endswith('_Value')
            and col not in exclude_cols
        ]

        if not position_cols:
            logger.warning("No position columns found in CSV")
            # Create empty plot with message
            fig = go.Figure()
            fig.add_annotation(
                text="No position data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=20)
            )
        else:
            fig = go.Figure()

            # Color palette for positions
            colors = [
                '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
            ]

            for idx, col in enumerate(position_cols):
                # Extract symbol name (remove '_Value' suffix)
                symbol = col.replace('_Value', '')

                # Get color from palette (cycle if needed)
                color = colors[idx % len(colors)]

                fig.add_trace(go.Scatter(
                    x=self.df['Date'],
                    y=self.df[col],
                    name=symbol,
                    mode='lines',
                    stackgroup='one',  # Stack areas
                    fillcolor=color,
                    line=dict(width=0.5, color=color),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>' +
                                  f'{symbol}: $%{{y:,.2f}}<extra></extra>'
                ))

        # Configure layout
        fig.update_layout(
            title='Position Allocation Over Time',
            xaxis_title='Date',
            yaxis_title='Position Value ($)',
            hovermode='x unified',
            template='plotly_white',
            legend=dict(
                x=1.02,
                y=1,
                bgcolor='rgba(255, 255, 255, 0.8)',
                bordercolor='rgba(0, 0, 0, 0.2)',
                borderwidth=1
            ),
            xaxis=dict(
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="YTD", step="year", stepmode="todate"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(step="all", label="All")
                    ])
                )
            )
        )

        # Write to HTML
        output_path = self.plots_dir / filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Position allocation plot saved to: {output_path}")
        return output_path

    def generate_returns_distribution(
        self,
        filename: str = 'returns_distribution.html'
    ) -> Path:
        """
        Generate returns distribution histogram with statistics.

        Creates a histogram showing the distribution of daily returns
        with overlaid statistics (mean, median, std dev).

        Args:
            filename: Output filename for HTML plot

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <0.5s for 4000-bar backtest
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating returns distribution plot: {filename}")

        # Calculate daily returns (percentage)
        returns = self.df['Portfolio_Total_Value'].pct_change() * 100
        returns = returns.dropna()

        fig = go.Figure()

        # Histogram
        fig.add_trace(go.Histogram(
            x=returns,
            name='Daily Returns',
            nbinsx=50,
            histnorm='probability density',
            marker_color='lightblue',
            opacity=0.7,
            hovertemplate='Return: %{x:.2f}%<br>Density: %{y:.4f}<extra></extra>'
        ))

        # Calculate statistics
        mean_return = returns.mean()
        median_return = returns.median()
        std_return = returns.std()

        # Add statistics annotation
        stats_text = (
            f"Mean: {mean_return:.2f}%<br>"
            f"Median: {median_return:.2f}%<br>"
            f"Std Dev: {std_return:.2f}%"
        )

        fig.update_layout(
            title='Daily Returns Distribution',
            xaxis_title='Daily Return (%)',
            yaxis_title='Density',
            template='plotly_white',
            showlegend=False,
            annotations=[dict(
                text=stats_text,
                xref='paper', yref='paper',
                x=0.98, y=0.98,
                xanchor='right', yanchor='top',
                showarrow=False,
                bordercolor='black',
                borderwidth=1,
                borderpad=4,
                bgcolor='rgba(255, 255, 255, 0.9)',
                font=dict(size=12)
            )]
        )

        # Write to HTML
        output_path = self.plots_dir / filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Returns distribution plot saved to: {output_path}")
        return output_path

    def generate_dashboard(
        self,
        filename: str = 'dashboard.html'
    ) -> Path:
        """
        Generate multi-panel dashboard combining all charts.

        Creates a 2x2 grid layout with:
        - Top-left: Equity curve
        - Top-right: Drawdown
        - Bottom-left: Position allocation
        - Bottom-right: Returns distribution

        Args:
            filename: Output filename for HTML plot

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <2s for 4000-bar backtest
            - File size: <500KB (using CDN Plotly.js)
        """
        logger.info(f"Generating dashboard plot: {filename}")

        # Create 2x2 subplot grid
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Equity Curve',
                'Drawdown',
                'Position Allocation',
                'Returns Distribution'
            ),
            specs=[
                [{'type': 'scatter'}, {'type': 'scatter'}],
                [{'type': 'scatter'}, {'type': 'histogram'}]
            ],
            vertical_spacing=0.12,
            horizontal_spacing=0.1
        )

        # Top-left: Equity curve
        fig.add_trace(
            go.Scatter(
                x=self.df['Date'],
                y=self.df['Portfolio_Total_Value'],
                mode='lines',
                name='Portfolio',
                line=dict(color='#1f77b4', width=2),
                hovertemplate='$%{y:,.2f}<extra></extra>',
                showlegend=True
            ),
            row=1, col=1
        )

        # Add baselines if available
        if 'Baseline_QQQ_Value' in self.df.columns:
            fig.add_trace(
                go.Scatter(
                    x=self.df['Date'],
                    y=self.df['Baseline_QQQ_Value'],
                    mode='lines',
                    name='Baseline (QQQ)',
                    line=dict(color='#ff7f0e', width=1.5, dash='dot'),
                    hovertemplate='$%{y:,.2f}<extra></extra>',
                    showlegend=True
                ),
                row=1, col=1
            )

        # Top-right: Drawdown
        portfolio_dd = self._calculate_drawdown(self.df['Portfolio_Total_Value'])
        fig.add_trace(
            go.Scatter(
                x=self.df['Date'],
                y=portfolio_dd,
                mode='lines',
                name='Portfolio DD',
                fill='tozeroy',
                line=dict(color='#d62728', width=1.5),
                fillcolor='rgba(214, 39, 40, 0.3)',
                hovertemplate='%{y:.2f}%<extra></extra>',
                showlegend=True
            ),
            row=1, col=2
        )

        # Bottom-left: Position allocation
        position_cols = [
            col for col in self.df.columns
            if col.endswith('_Value')
            and col not in ['Portfolio_Total_Value', 'Baseline_QQQ_Value', 'BuyHold_QQQ_Value']
        ]

        colors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
        ]

        for idx, col in enumerate(position_cols[:5]):  # Limit to 5 for dashboard clarity
            symbol = col.replace('_Value', '')
            color = colors[idx % len(colors)]

            fig.add_trace(
                go.Scatter(
                    x=self.df['Date'],
                    y=self.df[col],
                    name=symbol,
                    mode='lines',
                    stackgroup='one',
                    fillcolor=color,
                    line=dict(width=0.5, color=color),
                    hovertemplate=f'{symbol}: $%{{y:,.2f}}<extra></extra>',
                    showlegend=True
                ),
                row=2, col=1
            )

        # Bottom-right: Returns distribution
        returns = self.df['Portfolio_Total_Value'].pct_change() * 100
        returns = returns.dropna()

        fig.add_trace(
            go.Histogram(
                x=returns,
                name='Daily Returns',
                nbinsx=50,
                histnorm='probability density',
                marker_color='lightblue',
                opacity=0.7,
                hovertemplate='%{x:.2f}%<extra></extra>',
                showlegend=False
            ),
            row=2, col=2
        )

        # Update axes labels
        fig.update_xaxes(title_text="Date", row=1, col=1)
        fig.update_yaxes(title_text="Value ($)", row=1, col=1)

        fig.update_xaxes(title_text="Date", row=1, col=2)
        fig.update_yaxes(title_text="Drawdown (%)", row=1, col=2)

        fig.update_xaxes(title_text="Date", row=2, col=1)
        fig.update_yaxes(title_text="Value ($)", row=2, col=1)

        fig.update_xaxes(title_text="Return (%)", row=2, col=2)
        fig.update_yaxes(title_text="Density", row=2, col=2)

        # Update layout
        fig.update_layout(
            title_text='Backtest Dashboard',
            height=800,
            showlegend=True,
            template='plotly_white',
            hovermode='closest',
            legend=dict(
                orientation="v",
                yanchor="top",
                y=0.99,
                xanchor="right",
                x=1.15
            )
        )

        # Write to HTML
        output_path = self.plots_dir / filename
        fig.write_html(output_path, include_plotlyjs='cdn')

        logger.info(f"Dashboard plot saved to: {output_path}")
        return output_path

    def generate_all_plots(self) -> Dict[str, Path]:
        """
        Generate all visualization plots (equity, drawdown, positions, returns, dashboard).

        Convenience method to generate all Phase 1 and Phase 2 plots at once.

        Returns:
            Dictionary mapping plot type to file path

        Performance:
            - Target: <5s total for 4000-bar backtest
        """
        logger.info("Generating all plots...")

        plots = {}
        plots['equity_curve'] = self.generate_equity_curve()
        plots['drawdown'] = self.generate_drawdown()
        plots['positions'] = self.generate_positions()
        plots['returns'] = self.generate_returns_distribution()
        plots['dashboard'] = self.generate_dashboard()

        logger.info(
            f"All plots generated successfully in {self.plots_dir}"
        )

        return plots


# Convenience functions for direct usage

def generate_equity_curve(
    csv_path: Path,
    output_dir: Optional[Path] = None,
    filename: str = 'equity_curve.html'
) -> Path:
    """
    Generate equity curve plot from CSV file.

    Convenience function that creates an EquityPlotter and generates
    the equity curve in one step.

    Args:
        csv_path: Path to backtest CSV results
        output_dir: Optional output directory (defaults to csv_path/plots/)
        filename: Output filename for HTML plot

    Returns:
        Path to generated HTML file

    Example:
        >>> from jutsu_engine.infrastructure.visualization import generate_equity_curve
        >>> plot_path = generate_equity_curve('output/backtest_STRATEGY/results.csv')
    """
    plotter = EquityPlotter(csv_path=csv_path, output_dir=output_dir)
    return plotter.generate_equity_curve(filename=filename)


def generate_drawdown(
    csv_path: Path,
    output_dir: Optional[Path] = None,
    filename: str = 'drawdown.html'
) -> Path:
    """
    Generate drawdown plot from CSV file.

    Convenience function that creates an EquityPlotter and generates
    the drawdown plot in one step.

    Args:
        csv_path: Path to backtest CSV results
        output_dir: Optional output directory (defaults to csv_path/plots/)
        filename: Output filename for HTML plot

    Returns:
        Path to generated HTML file

    Example:
        >>> from jutsu_engine.infrastructure.visualization import generate_drawdown
        >>> plot_path = generate_drawdown('output/backtest_STRATEGY/results.csv')
    """
    plotter = EquityPlotter(csv_path=csv_path, output_dir=output_dir)
    return plotter.generate_drawdown(filename=filename)
