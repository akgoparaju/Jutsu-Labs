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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger('INFRA.VISUALIZATION')


def _to_list(series):
    """
    Convert pandas Series or numpy array to Python list.

    Plotly 6.x uses binary (base64) encoding for numpy arrays by default,
    which can cause rendering issues with CDN Plotly.js. Converting to
    Python lists ensures plain JSON array serialization.

    Args:
        series: pandas Series, numpy array, or list

    Returns:
        Python list
    """
    if hasattr(series, 'tolist'):
        return series.tolist()
    return list(series)


# Regime cell color palette (semi-transparent for overlay)
# Using Okabe-Ito colorblind-safe palette (Okabe & Ito, 2008)
# Reference: https://jfly.uni-koeln.de/color/
# This palette is distinguishable by individuals with all forms of color vision deficiency
REGIME_COLORS = {
    1: 'rgba(0, 114, 178, 0.18)',    # Blue - Bull/Low Vol (Okabe-Ito blue #0072B2)
    2: 'rgba(86, 180, 233, 0.18)',   # Sky Blue - Bull/High Vol (Okabe-Ito sky blue #56B4E9)
    3: 'rgba(153, 153, 153, 0.18)',  # Grey - Sideways/Low Vol (Okabe-Ito grey #999999)
    4: 'rgba(204, 121, 167, 0.18)',  # Purple - Sideways/High Vol (Okabe-Ito purple #CC79A7)
    5: 'rgba(230, 159, 0, 0.18)',    # Orange - Bear/Low Vol (Okabe-Ito orange #E69F00)
    6: 'rgba(213, 94, 0, 0.18)',     # Vermillion - Bear/High Vol (Okabe-Ito vermillion #D55E00)
}

REGIME_LABELS = {
    1: 'Cell 1: Bull/Low',
    2: 'Cell 2: Bull/High',
    3: 'Cell 3: Sideways/Low',
    4: 'Cell 4: Sideways/High',
    5: 'Cell 5: Bear/Low',
    6: 'Cell 6: Bear/High',
}


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

        # Detect regime column for overlay support
        self._has_regime_data = 'Regime' in df.columns
        if self._has_regime_data:
            logger.info("Regime data detected in CSV - overlay will be available")
        else:
            logger.debug("No Regime column in CSV - overlay will be skipped")

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

    def _get_regime_spans(self) -> List[Tuple[datetime, datetime, int]]:
        """
        Consolidate consecutive days with same regime into spans.

        Processes the Regime column (format: 'Cell_X') and groups consecutive
        days with the same regime into single spans for efficient visualization.

        Returns:
            List of (start_date, end_date, regime_cell) tuples
            Empty list if no regime data available

        Example:
            [(datetime(2020,1,1), datetime(2020,1,15), 1),
             (datetime(2020,1,16), datetime(2020,2,1), 3),
             ...]
        """
        if not self._has_regime_data:
            return []

        # Parse regime cell number from 'Cell_X' format
        df = self._df.copy()
        df['regime_num'] = df['Regime'].str.extract(r'Cell_(\d+)').astype(float)

        spans = []
        current_regime = None
        span_start = None
        prev_date = None

        for _, row in df.iterrows():
            regime = row.get('regime_num')
            if pd.isna(regime):
                continue
            regime = int(regime)

            if regime != current_regime:
                # Close previous span
                if current_regime is not None:
                    spans.append((span_start, prev_date, current_regime))
                # Start new span
                current_regime = regime
                span_start = row['Date']
            prev_date = row['Date']

        # Close final span
        if current_regime is not None:
            spans.append((span_start, prev_date, current_regime))

        logger.info(f"Identified {len(spans)} regime spans for overlay")
        return spans

    def generate_equity_curve(
        self,
        filename: str = 'equity_curve.html',
        include_baseline: bool = True,
        show_regime_overlay: bool = True,
        auto_scale_y: bool = True
    ) -> Path:
        """
        Generate interactive equity curve plot with portfolio vs. baseline.

        Creates a time-series line chart showing portfolio value evolution
        compared to baseline (Buy & Hold) performance. Includes a dropdown
        to switch between absolute dollar values ($) and percentage returns (%).

        In percentage mode, when zoomed, all curves are normalized to start at 0%
        from the first visible data point, allowing relative performance comparison
        from any starting point.

        Args:
            filename: Output filename for HTML plot
            include_baseline: Whether to include baseline comparison traces
            show_regime_overlay: Whether to show colored regime cell backgrounds (default: True)
                Requires Regime column in CSV. If not available, silently skips.
            auto_scale_y: Whether to dynamically adjust Y-axis range when zooming X-axis.
                When enabled, Y-axis will auto-fit to visible data when using rangeslider,
                rangeselector buttons, or zoom. Default: True.

        Returns:
            Path to generated HTML file

        Performance:
            - Target: <1s for 4000-bar backtest
            - File size: <100KB (using CDN Plotly.js)
        """
        logger.info(f"Generating equity curve plot: {filename}")

        fig = go.Figure()

        # Add regime overlay (behind the lines)
        if show_regime_overlay and self._has_regime_data:
            spans = self._get_regime_spans()
            added_regimes = set()  # Track which regimes we've added to avoid duplicate legends

            for start_date, end_date, regime in spans:
                # Add vertical rectangle for this regime period
                show_legend = regime not in added_regimes

                fig.add_vrect(
                    x0=start_date,
                    x1=end_date,
                    fillcolor=REGIME_COLORS.get(regime, 'rgba(128,128,128,0.1)'),
                    layer='below',
                    line_width=0,
                )

                # Add invisible trace for legend entry (only first occurrence of each regime)
                if show_legend:
                    fig.add_trace(go.Scatter(
                        x=[None],
                        y=[None],
                        mode='markers',
                        marker=dict(
                            size=15,
                            color=REGIME_COLORS.get(regime, 'rgba(128,128,128,0.3)'),
                            symbol='square'
                        ),
                        name=REGIME_LABELS.get(regime, f'Cell {regime}'),
                        showlegend=True,
                        legendgroup='regime'
                    ))
                    added_regimes.add(regime)

            logger.info(f"Added {len(spans)} regime overlay spans ({len(added_regimes)} unique regimes)")

        # Prepare regime labels for hover tooltip
        regime_hover_labels = None
        if self._has_regime_data and 'Regime' in self._df.columns:
            regime_hover_labels = []
            for regime_val in self._df['Regime']:
                if pd.isna(regime_val):
                    regime_hover_labels.append('N/A')
                else:
                    # Extract cell number from 'Cell_X' format
                    try:
                        cell_num = int(str(regime_val).replace('Cell_', ''))
                        regime_hover_labels.append(REGIME_LABELS.get(cell_num, str(regime_val)))
                    except (ValueError, AttributeError):
                        regime_hover_labels.append(str(regime_val))

        # Calculate percentage returns from initial value for each series
        portfolio_values = _to_list(self._df['Portfolio_Total_Value'])
        portfolio_pct = [(v / portfolio_values[0] - 1) * 100 for v in portfolio_values]
        dates = _to_list(self._df['Date'])

        # Track trace indices for mode switching (excluding regime legend placeholders)
        data_trace_start_idx = len(fig.data)  # Index where data traces start

        # Add portfolio equity trace
        # Store both dollar and percentage values for mode switching
        # Note: Use _to_list() to avoid Plotly 6.x binary encoding issues with CDN
        if regime_hover_labels:
            fig.add_trace(go.Scatter(
                x=dates,
                y=portfolio_values,
                mode='lines',
                name='Portfolio',
                line=dict(color='#1f77b4', width=2),
                customdata=list(zip(regime_hover_labels, portfolio_pct, portfolio_values)),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Portfolio: $%{y:,.2f}<br>Regime: %{customdata[0]}<extra></extra>',
                meta={'original_y': portfolio_values, 'pct_y': portfolio_pct, 'trace_type': 'portfolio'}
            ))
        else:
            fig.add_trace(go.Scatter(
                x=dates,
                y=portfolio_values,
                mode='lines',
                name='Portfolio',
                line=dict(color='#1f77b4', width=2),
                customdata=list(zip(portfolio_pct, portfolio_values)),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Portfolio: $%{y:,.2f}<extra></extra>',
                meta={'original_y': portfolio_values, 'pct_y': portfolio_pct, 'trace_type': 'portfolio'}
            ))

        # Add baseline traces if available and requested
        if include_baseline:
            # Use dynamically detected baseline column (supports configurable baseline_symbol)
            if self.baseline_value_col:
                baseline_values = _to_list(self._df[self.baseline_value_col])
                baseline_pct = [(v / baseline_values[0] - 1) * 100 for v in baseline_values]
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=baseline_values,
                    mode='lines',
                    name=f'Baseline ({self.baseline_symbol})',
                    line=dict(color='#ff7f0e', width=1.5, dash='dot'),
                    customdata=list(zip(baseline_pct, baseline_values)),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Baseline: $%{y:,.2f}<extra></extra>',
                    meta={'original_y': baseline_values, 'pct_y': baseline_pct, 'trace_type': 'baseline'}
                ))

            # Legacy BuyHold column support (if exists)
            if 'BuyHold_QQQ_Value' in self._df.columns:
                buyhold_values = _to_list(self._df['BuyHold_QQQ_Value'])
                buyhold_pct = [(v / buyhold_values[0] - 1) * 100 for v in buyhold_values]
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=buyhold_values,
                    mode='lines',
                    name='Buy & Hold (QQQ)',
                    line=dict(color='#2ca02c', width=1.5, dash='dash'),
                    customdata=list(zip(buyhold_pct, buyhold_values)),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Buy & Hold: $%{y:,.2f}<extra></extra>',
                    meta={'original_y': buyhold_values, 'pct_y': buyhold_pct, 'trace_type': 'buyhold'}
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
                type='date',  # Explicit date type required for Plotly 3.x CDN with legend placeholders
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="YTD", step="year", stepmode="todate"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(step="all", label="All")
                    ]),
                    x=0.01,
                    y=1.12
                )
            ),
            # Add dropdown for $ vs % mode
            updatemenus=[
                dict(
                    type='dropdown',
                    direction='down',
                    x=0.99,
                    xanchor='right',
                    y=1.12,
                    yanchor='top',
                    showactive=True,
                    active=0,
                    buttons=[
                        dict(
                            label='Value ($)',
                            method='skip',  # We handle mode switching via JavaScript
                            args=[{'mode': 'dollar'}]
                        ),
                        dict(
                            label='Return (%)',
                            method='skip',  # We handle mode switching via JavaScript
                            args=[{'mode': 'percent'}]
                        ),
                    ],
                    bgcolor='white',
                    bordercolor='rgba(0,0,0,0.2)',
                    font=dict(size=12)
                )
            ]
        )

        # JavaScript for:
        # 1. Dynamic Y-axis auto-scaling when X-axis is zoomed ($ mode)
        # 2. Mode switching between $ and % display
        # 3. Percentage normalization on zoom (% mode only) - all curves start at 0%
        mode_switch_script = """
        (function() {
            var gd = document.querySelector('.plotly-graph-div');
            if (!gd) return;
            
            // State management
            var isUpdatingYAxis = false;
            var currentMode = 'dollar';  // 'dollar' or 'percent'
            var dataTraceStartIdx = """ + str(data_trace_start_idx) + """;
            
            // Store original data for each trace (populated on first load)
            var originalData = {};
            
            // Initialize original data storage
            function initOriginalData() {
                for (var i = dataTraceStartIdx; i < gd.data.length; i++) {
                    var trace = gd.data[i];
                    if (trace.x && trace.y && trace.x.length > 0 && trace.x[0] !== null) {
                        originalData[i] = {
                            original_y: trace.y.slice(),  // Clone array
                            // Calculate initial percentage returns
                            pct_y: trace.y.map(function(v) { 
                                return (v / trace.y[0] - 1) * 100; 
                            })
                        };
                    }
                }
            }
            
            // Wait for plot to be ready then initialize
            setTimeout(initOriginalData, 100);
            
            // Get visible X range (returns [startTimestamp, endTimestamp])
            function getVisibleXRange() {
                var xaxis = gd._fullLayout.xaxis;

                // Helper to get full range from trace data
                function getFullRangeFromData() {
                    for (var i = dataTraceStartIdx; i < gd.data.length; i++) {
                        if (gd.data[i].x && gd.data[i].x.length > 0 && gd.data[i].x[0] !== null) {
                            return [
                                new Date(gd.data[i].x[0]).getTime(),
                                new Date(gd.data[i].x[gd.data[i].x.length - 1]).getTime()
                            ];
                        }
                    }
                    return null;
                }

                // If autorange is true, return full range
                if (xaxis.autorange) {
                    return getFullRangeFromData() || [0, Date.now()];
                }

                // Check if range values are indices (small numbers) or dates
                // Plotly stores range as indices when showing "all" data on categorical/date axes
                var r0 = xaxis.range[0];
                var r1 = xaxis.range[1];

                // If range values are small numbers (likely indices), use full data range
                // Real timestamps would be > 1e10 (milliseconds since 1970)
                // Index values are typically small integers or small floats
                if (typeof r0 === 'number' && typeof r1 === 'number' &&
                    Math.abs(r0) < 1e9 && Math.abs(r1) < 1e9) {
                    return getFullRangeFromData() || [0, Date.now()];
                }

                // Parse as date strings or timestamps
                return [new Date(r0).getTime(), new Date(r1).getTime()];
            }
            
            // Find first visible index for a trace given X range
            function findFirstVisibleIndex(trace, x0, x1) {
                if (!trace.x || trace.x.length === 0 || trace.x[0] === null) return -1;
                for (var j = 0; j < trace.x.length; j++) {
                    var xVal = new Date(trace.x[j]).getTime();
                    if (xVal >= x0 && xVal <= x1) {
                        return j;
                    }
                }
                return -1;
            }
            
            // Update traces for dollar mode
            function updateDollarMode() {
                // Save current x-axis range to restore after update
                // (showing rangeslider can reset the view)
                var savedXRange = gd._fullLayout.xaxis.range ? gd._fullLayout.xaxis.range.slice() : null;
                var wasAutorange = gd._fullLayout.xaxis.autorange;

                var updates = {y: [], hovertemplate: []};
                var indices = [];

                for (var i = dataTraceStartIdx; i < gd.data.length; i++) {
                    var trace = gd.data[i];
                    if (!originalData[i]) continue;

                    indices.push(i);
                    updates.y.push(originalData[i].original_y);

                    // Update hovertemplate for dollar format
                    var name = trace.name || 'Value';
                    if (trace.customdata && trace.customdata[0] && trace.customdata[0].length === 3) {
                        // Has regime data
                        updates.hovertemplate.push('<b>%{x|%Y-%m-%d}</b><br>' + name + ': $%{y:,.2f}<br>Regime: %{customdata[0]}<extra></extra>');
                    } else {
                        updates.hovertemplate.push('<b>%{x|%Y-%m-%d}</b><br>' + name + ': $%{y:,.2f}<extra></extra>');
                    }
                }

                if (indices.length > 0) {
                    // Use Plotly.update() for ATOMIC trace + layout update
                    // This prevents intermediate state where xaxis.type gets corrupted
                    Plotly.update(gd, updates, {
                        'yaxis.title.text': 'Portfolio Value ($)',
                        'yaxis.autorange': true,
                        'xaxis.rangeslider.visible': true,
                        'xaxis.type': 'date'
                    }, indices).then(function() {
                        // Restore the x-axis range after showing rangeslider
                        // (rangeslider changes can reset the zoom level)
                        if (savedXRange && !wasAutorange) {
                            return Plotly.relayout(gd, {'xaxis.range': savedXRange});
                        }
                    });
                }
            }

            // Update traces for percent mode with normalization to first visible point
            function updatePercentMode() {
                var xRange = getVisibleXRange();
                var x0 = xRange[0];
                var x1 = xRange[1];

                // Save current x-axis range to restore after update
                // (hiding rangeslider can reset the view)
                var savedXRange = gd._fullLayout.xaxis.range ? gd._fullLayout.xaxis.range.slice() : null;
                var wasAutorange = gd._fullLayout.xaxis.autorange;

                var updates = {y: [], hovertemplate: []};
                var indices = [];

                for (var i = dataTraceStartIdx; i < gd.data.length; i++) {
                    var trace = gd.data[i];
                    if (!originalData[i]) continue;

                    var firstVisibleIdx = findFirstVisibleIndex(trace, x0, x1);
                    if (firstVisibleIdx === -1) continue;

                    // Normalize all values relative to first visible value
                    var baseValue = originalData[i].original_y[firstVisibleIdx];
                    var normalizedPct = originalData[i].original_y.map(function(v) {
                        return (v / baseValue - 1) * 100;
                    });

                    indices.push(i);
                    updates.y.push(normalizedPct);

                    // Update hovertemplate for percent format
                    var name = trace.name || 'Return';
                    if (trace.customdata && trace.customdata[0] && trace.customdata[0].length === 3) {
                        // Has regime data
                        updates.hovertemplate.push('<b>%{x|%Y-%m-%d}</b><br>' + name + ': %{y:,.2f}%<br>Regime: %{customdata[0]}<extra></extra>');
                    } else {
                        updates.hovertemplate.push('<b>%{x|%Y-%m-%d}</b><br>' + name + ': %{y:,.2f}%<extra></extra>');
                    }
                }

                if (indices.length > 0) {
                    isUpdatingYAxis = true;

                    // Use Plotly.update() for ATOMIC trace + layout update
                    // This prevents intermediate state where xaxis.type gets corrupted
                    Plotly.update(gd, updates, {
                        'yaxis.title.text': 'Return (%)',
                        'yaxis.autorange': true,
                        'xaxis.rangeslider.visible': false,
                        'xaxis.type': 'date'
                    }, indices).then(function() {
                        // Restore the x-axis range after hiding rangeslider
                        // (rangeslider changes can reset the zoom level)
                        if (savedXRange && !wasAutorange) {
                            return Plotly.relayout(gd, {'xaxis.range': savedXRange});
                        }
                    }).then(function() {
                        isUpdatingYAxis = false;
                    });
                }
            }

            // Handle dropdown selection change
            gd.on('plotly_buttonclicked', function(eventdata) {
                // Check if this is our mode dropdown (updatemenus[0])
                if (eventdata.menu && eventdata.menu._index === 0) {
                    var newMode = eventdata.active === 0 ? 'dollar' : 'percent';
                    if (newMode !== currentMode) {
                        currentMode = newMode;
                        if (currentMode === 'dollar') {
                            updateDollarMode();
                        } else {
                            updatePercentMode();
                        }
                    }
                }
            });
            
            // Handle zoom/pan events
            gd.on('plotly_relayout', function(eventdata) {
                // Skip if this is our own Y-axis update
                if (isUpdatingYAxis) return;
                
                // Check if this is just a Y-axis change (from our update)
                if (eventdata['yaxis.range'] || eventdata['yaxis.range[0]'] !== undefined) {
                    // Only Y-axis changed, not X-axis - skip
                    if (!eventdata['xaxis.range'] && eventdata['xaxis.range[0]'] === undefined && 
                        !eventdata['xaxis.autorange']) {
                        return;
                    }
                }
                
                // Handle autorange (e.g., "All" button or double-click reset)
                if (eventdata['xaxis.autorange'] === true) {
                    if (currentMode === 'percent') {
                        // Re-normalize from full range start
                        updatePercentMode();
                    } else {
                        isUpdatingYAxis = true;
                        Plotly.relayout(gd, {'yaxis.autorange': true}).then(function() {
                            isUpdatingYAxis = false;
                        });
                    }
                    return;
                }
                
                // Check for X-axis range change
                var hasXRangeChange = eventdata['xaxis.range'] || eventdata['xaxis.range[0]'] !== undefined;
                if (!hasXRangeChange) return;
                
                if (currentMode === 'percent') {
                    // In percent mode, re-normalize all curves to start at 0% from first visible point
                    updatePercentMode();
                } else {
                    // In dollar mode, just auto-scale Y axis
                    var xRange;
                    if (eventdata['xaxis.range']) {
                        xRange = eventdata['xaxis.range'];
                    } else {
                        xRange = [eventdata['xaxis.range[0]'], eventdata['xaxis.range[1]']];
                    }
                    
                    var x0 = new Date(xRange[0]).getTime();
                    var x1 = new Date(xRange[1]).getTime();
                    
                    var yMin = Infinity;
                    var yMax = -Infinity;
                    
                    for (var i = 0; i < gd.data.length; i++) {
                        var trace = gd.data[i];
                        if (!trace.x || !trace.y || trace.x.length === 0 || trace.x[0] === null) continue;
                        if (trace.visible === 'legendonly' || trace.visible === false) continue;
                        
                        for (var j = 0; j < trace.x.length; j++) {
                            var xVal = new Date(trace.x[j]).getTime();
                            if (xVal >= x0 && xVal <= x1) {
                                var yVal = trace.y[j];
                                if (typeof yVal === 'number' && !isNaN(yVal)) {
                                    if (yVal < yMin) yMin = yVal;
                                    if (yVal > yMax) yMax = yVal;
                                }
                            }
                        }
                    }
                    
                    if (yMin !== Infinity && yMax !== -Infinity && yMin !== yMax) {
                        var padding = (yMax - yMin) * 0.05;
                        isUpdatingYAxis = true;
                        Plotly.relayout(gd, {
                            'yaxis.range': [yMin - padding, yMax + padding]
                        }).then(function() {
                            isUpdatingYAxis = false;
                        });
                    }
                }
            });
        })();
        """

        # Write to HTML with CDN Plotly.js for small file size
        output_path = self.output_dir / filename
        
        if auto_scale_y:
            fig.write_html(output_path, include_plotlyjs='cdn', post_script=mode_switch_script)
            logger.info(f"Equity curve plot saved to: {output_path} (with $ vs % toggle and dynamic Y-axis scaling)")
        else:
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
            x=_to_list(self._df['Date']),
            y=_to_list(portfolio_dd),
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
                    x=_to_list(self._df['Date']),
                    y=_to_list(baseline_dd),
                    mode='lines',
                    name=f'Baseline ({self.baseline_symbol}) Drawdown',
                    line=dict(color='#ff7f0e', width=1, dash='dot'),
                    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Baseline DD: %{y:.2f}%<extra></extra>'
                ))

            # Legacy BuyHold column support (if exists)
            if 'BuyHold_QQQ_Value' in self._df.columns:
                buyhold_dd = self._calculate_drawdown(self._df['BuyHold_QQQ_Value'])
                fig.add_trace(go.Scatter(
                    x=_to_list(self._df['Date']),
                    y=_to_list(buyhold_dd),
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
                type='date',  # Explicit date type required for Plotly 3.x CDN
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
                    x=_to_list(self.df['Date']),
                    y=_to_list(self.df[col]),
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
                type='date',  # Explicit date type required for Plotly 3.x CDN
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
            x=_to_list(returns),
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
                x=_to_list(self.df['Date']),
                y=_to_list(self.df['Portfolio_Total_Value']),
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
                    x=_to_list(self.df['Date']),
                    y=_to_list(self.df['Baseline_QQQ_Value']),
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
                x=_to_list(self.df['Date']),
                y=_to_list(portfolio_dd),
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
                    x=_to_list(self.df['Date']),
                    y=_to_list(self.df[col]),
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
                x=_to_list(returns),
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
