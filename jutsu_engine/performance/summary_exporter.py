"""
CSV exporter for backtest summary metrics.

Exports high-level performance metrics (baseline, strategy, comparison) to CSV format.
Complements the daily portfolio CSV and trade log CSV with summary-level statistics.
"""

import csv
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


class SummaryCSVExporter:
    """
    Exports backtest summary metrics to CSV.

    Creates a single CSV file with all key performance metrics from the CLI output:
    - Baseline metrics (Final Value, Total Return, Annualized Return)
    - Strategy metrics (Initial Capital, Final Value, Returns, Sharpe, Drawdown, Win Rate, Trades)
    - Comparison metrics (Alpha, Excess Return, Return Ratio)

    CSV Format:
        Category, Metric, Baseline, Strategy, Difference
        Performance, Final_Value, $25412.61, $33139.62, +$7727.01
        ...
    """

    def __init__(self):
        """Initialize summary CSV exporter."""
        pass

    def export_summary_csv(
        self,
        results: Dict[str, Any],
        baseline: Optional[Dict[str, Any]],
        output_dir: str = "output",
        strategy_name: str = "Strategy"
    ) -> str:
        """
        Export summary metrics to CSV file.

        Args:
            results: Full backtest results dictionary
            baseline: Baseline metrics dictionary (or None if not available)
            output_dir: Output directory path
            strategy_name: Strategy name for filename

        Returns:
            str: Path to created CSV file

        Example:
            exporter = SummaryCSVExporter()
            csv_path = exporter.export_summary_csv(results, baseline, "output", "MACD_Trend_v6")
            # Creates: output/MACD_Trend_v6_20251109_203705_summary.csv
        """
        # Create output directory if needed
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{strategy_name}_{timestamp}_summary.csv"
        csv_path = output_path / filename

        # Build rows
        rows = self._build_summary_rows(results, baseline)

        # Write CSV
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow(['Category', 'Metric', 'Baseline', 'Strategy', 'Difference'])

            # Data rows
            for row in rows:
                writer.writerow(row)

        return str(csv_path)

    def _build_summary_rows(
        self,
        results: Dict[str, Any],
        baseline: Optional[Dict[str, Any]]
    ) -> list:
        """
        Build summary CSV rows from results and baseline.

        Args:
            results: Backtest results dictionary
            baseline: Baseline metrics dictionary (or None)

        Returns:
            List of row tuples (category, metric, baseline_val, strategy_val, diff)
        """
        rows = []

        # Extract strategy metrics
        initial_capital = results.get('config', {}).get('initial_capital', 0)
        final_value = results.get('final_value', 0)
        total_return = results.get('total_return', 0)
        annual_return = results.get('annualized_return', 0)
        sharpe = results.get('sharpe_ratio', 0)
        max_dd = results.get('max_drawdown', 0)
        win_rate = results.get('win_rate', 0)
        total_fills = results.get('total_fills', 0)        # All BUY/SELL executions
        closed_trades = results.get('closed_trades', 0)    # Complete BUY→SELL cycles
        total_trades = results.get('total_trades', 0)      # Backwards compatibility (deprecated)

        # Extract baseline metrics (if available)
        if baseline:
            baseline_final = baseline.get('baseline_final_value', 0)
            baseline_return = baseline.get('baseline_total_return', 0)
            baseline_annual = baseline.get('baseline_annualized_return', 0)
            baseline_sharpe = baseline.get('baseline_sharpe_ratio')
            baseline_max_dd = baseline.get('baseline_max_drawdown')
            baseline_sortino = baseline.get('baseline_sortino_ratio')
            baseline_calmar = baseline.get('baseline_calmar_ratio')
            alpha = baseline.get('alpha')
        else:
            baseline_final = None
            baseline_return = None
            baseline_annual = None
            baseline_sharpe = None
            baseline_max_dd = None
            baseline_sortino = None
            baseline_calmar = None
            alpha = None

        # Performance Metrics
        rows.append([
            'Performance',
            'Initial_Capital',
            'N/A',
            f'${float(initial_capital):,.2f}',
            'N/A'
        ])

        rows.append([
            'Performance',
            'Final_Value',
            f'${float(baseline_final):,.2f}' if baseline_final is not None else 'N/A',
            f'${float(final_value):,.2f}',
            f'+${float(final_value) - float(baseline_final):,.2f}' if baseline_final is not None else 'N/A'
        ])

        rows.append([
            'Performance',
            'Total_Return',
            f'{float(baseline_return) * 100:.2f}%' if baseline_return is not None else 'N/A',
            f'{float(total_return) * 100:.2f}%',
            f'+{(float(total_return) - float(baseline_return)) * 100:.2f}%' if baseline_return is not None else 'N/A'
        ])

        rows.append([
            'Performance',
            'Annualized_Return',
            f'{float(baseline_annual) * 100:.2f}%' if baseline_annual is not None else 'N/A',
            f'{float(annual_return) * 100:.2f}%',
            f'+{(float(annual_return) - float(baseline_annual)) * 100:.2f}%' if baseline_annual is not None else 'N/A'
        ])

        # Risk Metrics
        rows.append([
            'Risk',
            'Sharpe_Ratio',
            f'{float(baseline_sharpe):.2f}' if baseline_sharpe is not None else 'N/A',
            f'{float(sharpe):.2f}',
            f'+{float(sharpe) - float(baseline_sharpe):.2f}' if baseline_sharpe is not None else 'N/A'
        ])

        rows.append([
            'Risk',
            'Max_Drawdown',
            f'{float(baseline_max_dd) * 100:.2f}%' if baseline_max_dd is not None else 'N/A',
            f'{float(max_dd) * 100:.2f}%',
            f'+{(float(max_dd) - float(baseline_max_dd)) * 100:.2f}%' if baseline_max_dd is not None else 'N/A'
        ])

        # Beta metrics (systematic risk vs market benchmarks)
        beta_vs_qqq = baseline.get('beta_vs_QQQ') if baseline else None
        beta_vs_spy = baseline.get('beta_vs_SPY') if baseline else None

        rows.append([
            'Risk',
            'Beta_vs_QQQ',
            '1.00',  # Baseline QQQ beta to itself is 1.0
            f'{float(beta_vs_qqq):.3f}' if beta_vs_qqq is not None else 'N/A',
            f'{float(beta_vs_qqq) - 1.0:+.3f}' if beta_vs_qqq is not None else 'N/A'
        ])

        rows.append([
            'Risk',
            'Beta_vs_SPY',
            'N/A',  # SPY beta not applicable to QQQ baseline
            f'{float(beta_vs_spy):.3f}' if beta_vs_spy is not None else 'N/A',
            'N/A'
        ])

        # Trading Metrics
        rows.append([
            'Trading',
            'Win_Rate',
            'N/A',
            f'{float(win_rate) * 100:.2f}%',
            'N/A'
        ])

        rows.append([
            'Trading',
            'Total_Fills',
            'N/A',
            f'{int(total_fills)}',
            'N/A'
        ])

        rows.append([
            'Trading',
            'Closed_Trades',
            'N/A',
            f'{int(closed_trades)}',
            'N/A'
        ])

        # Comparison Metrics (only if baseline available)
        if baseline and alpha is not None:
            excess_return = float(total_return) - float(baseline_return)
            outperformance_pct = (alpha - 1) * 100 if alpha >= 1 else (1 - alpha) * -100

            rows.append([
                'Comparison',
                'Alpha',
                '1.00x',
                f'{float(alpha):.2f}x',
                f'+{outperformance_pct:.2f}%' if alpha >= 1 else f'{outperformance_pct:.2f}%'
            ])

            rows.append([
                'Comparison',
                'Excess_Return',
                '0.00%',
                f'{excess_return * 100:+.2f}%',
                f'{excess_return * 100:+.2f}%'
            ])

            return_ratio = float(total_return) / float(baseline_return) if baseline_return != 0 else 0
            rows.append([
                'Comparison',
                'Return_Ratio',
                '1.00:1',
                f'{return_ratio:.2f}:1',
                'N/A'
            ])

        return rows
