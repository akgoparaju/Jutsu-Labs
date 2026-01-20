"""
CSV exporter for backtest dashboard display.

Exports a single consolidated CSV file with all data needed for the dashboard UI:
- Header metadata (strategy name, dates, summary metrics) as comment lines
- Timeseries data with minimal columns for equity curve and regime filtering

This format is designed for easy API parsing and atomic file updates.
"""

import csv
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from jutsu_engine.utils.logging_config import get_logger

logger = get_logger('DASHBOARD_EXPORT')


class DashboardCSVExporter:
    """
    Exports consolidated backtest data for dashboard display.

    Creates a single CSV file with:
    - Comment header lines (# prefix) containing metadata and summary metrics
    - Data rows with minimal columns: Date, Portfolio_Value, Baseline_Value,
      BuyHold_Value, Regime, Trend, Vol

    CSV Format:
        # Backtest Dashboard Export
        # strategy_name: Hierarchical_Adaptive_v3_5b
        # start_date: 2010-01-04
        # end_date: 2025-12-11
        # initial_capital: 10000.00
        # total_return: 8768.85
        # annualized_return: 32.50
        # sharpe_ratio: 1.18
        # max_drawdown: -28.63
        # alpha: 7.18
        # baseline_ticker: QQQ
        Date,Portfolio_Value,Baseline_Value,BuyHold_Value,Regime,Trend,Vol
        2010-01-04,10000.00,10000.00,10000.00,Cell_3,Sideways,Low
        ...

    Note:
        - All numeric values are clean (no $, %, commas)
        - Returns are stored as percentages (e.g., 8768.85 means 8768.85%)
        - Drawdown is negative (e.g., -28.63 means -28.63%)
        - Alpha is ratio (e.g., 7.18 means 7.18x baseline)
    """

    def __init__(self, initial_capital: Decimal = Decimal('10000')):
        """
        Initialize dashboard CSV exporter.

        Args:
            initial_capital: Starting capital for baseline calculations
        """
        self.initial_capital = initial_capital

    def export_dashboard_csv(
        self,
        daily_snapshots: List[Dict],
        results: Dict[str, Any],
        baseline: Optional[Dict[str, Any]],
        baseline_info: Optional[Dict[str, Any]],
        signal_prices: Optional[Dict[str, Decimal]],
        regime_data: Optional[List[Dict]],
        start_date: datetime,
        output_path: str,
        strategy_name: str,
    ) -> str:
        """
        Export consolidated dashboard CSV file.

        Args:
            daily_snapshots: List of daily portfolio state dictionaries from
                           PortfolioSimulator.get_daily_snapshots()
            results: Full backtest results dictionary with metrics
            baseline: Baseline metrics dictionary (or None if not available)
            baseline_info: Dict with baseline price data:
                - 'symbol': Baseline ticker (e.g., 'QQQ')
                - 'start_price': Price at backtest start
                - 'price_history': Dict[date, price] for daily prices
            signal_prices: Optional dict mapping date strings to signal symbol prices
                          for buy-and-hold calculation {YYYY-MM-DD: Decimal}
            regime_data: List of regime dicts with keys:
                'timestamp', 'regime_cell', 'trend_state', 'vol_state'
            start_date: Trading period start date (excludes warmup)
            output_path: Directory path for CSV output
            strategy_name: Strategy name for filename and metadata

        Returns:
            Full path to generated CSV file

        Raises:
            ValueError: If daily_snapshots is empty or all before start_date

        Example:
            exporter = DashboardCSVExporter(initial_capital=Decimal('10000'))
            csv_path = exporter.export_dashboard_csv(
                daily_snapshots=portfolio.get_daily_snapshots(),
                results=backtest_results,
                baseline=baseline_result,
                baseline_info={'symbol': 'QQQ', 'start_price': ..., 'price_history': ...},
                signal_prices=signal_prices,
                regime_data=regime_data,
                start_date=start_date,
                output_path='config/backtest',
                strategy_name='Hierarchical_Adaptive_v3_5b'
            )
        """
        if not daily_snapshots:
            raise ValueError("Cannot export empty daily snapshots")

        # Filter snapshots to exclude warmup period
        start_date_normalized = start_date
        if start_date.tzinfo is None:
            start_date_normalized = start_date.replace(tzinfo=timezone.utc)

        filtered_snapshots = []
        for snapshot in daily_snapshots:
            timestamp = snapshot['timestamp']
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            if timestamp >= start_date_normalized:
                filtered_snapshots.append(snapshot)

        if not filtered_snapshots:
            raise ValueError(
                f"No snapshots found after start_date {start_date}. "
                f"All {len(daily_snapshots)} snapshots are in warmup period."
            )

        logger.info(
            f"Filtered {len(daily_snapshots)} snapshots to {len(filtered_snapshots)} "
            f"(excluded {len(daily_snapshots) - len(filtered_snapshots)} warmup days)"
        )

        # Create regime lookup dict for fast access
        regime_lookup = {}
        if regime_data:
            for entry in regime_data:
                ts = entry['timestamp']
                if hasattr(ts, 'date'):
                    date_key = ts.date() if callable(ts.date) else ts.date
                else:
                    date_key = ts
                regime_lookup[date_key] = entry

        # Create output directory if needed
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        filename = f"dashboard_{strategy_name}.csv"
        csv_path = output_dir / filename

        # Extract metadata
        config = results.get('config', {})
        end_date = config.get('end_date', datetime.now())
        if hasattr(end_date, 'date'):
            end_date_str = end_date.strftime('%Y-%m-%d')
        else:
            end_date_str = str(end_date)

        start_date_str = start_date.strftime('%Y-%m-%d')

        # Extract summary metrics (convert to percentages for display)
        total_return = float(results.get('total_return', 0)) * 100  # e.g., 87.6885 → 8768.85
        annualized_return = float(results.get('annualized_return', 0)) * 100
        sharpe_ratio = float(results.get('sharpe_ratio', 0))
        max_drawdown = float(results.get('max_drawdown', 0)) * 100  # e.g., -0.2863 → -28.63
        alpha = float(baseline.get('alpha', 1.0)) if baseline else 1.0

        baseline_ticker = baseline_info.get('symbol', 'QQQ') if baseline_info else 'QQQ'

        # Write CSV
        with open(csv_path, 'w', newline='') as f:
            # Write comment header with metadata
            f.write("# Backtest Dashboard Export\n")
            f.write(f"# strategy_name: {strategy_name}\n")
            f.write(f"# start_date: {start_date_str}\n")
            f.write(f"# end_date: {end_date_str}\n")
            f.write(f"# initial_capital: {float(self.initial_capital):.2f}\n")
            f.write(f"# total_return: {total_return:.2f}\n")
            f.write(f"# annualized_return: {annualized_return:.2f}\n")
            f.write(f"# sharpe_ratio: {sharpe_ratio:.2f}\n")
            f.write(f"# max_drawdown: {max_drawdown:.2f}\n")
            f.write(f"# alpha: {alpha:.2f}\n")
            f.write(f"# baseline_ticker: {baseline_ticker}\n")

            # Write data rows
            writer = csv.writer(f)
            writer.writerow([
                'Date', 'Portfolio_Value', 'Baseline_Value', 'BuyHold_Value',
                'Regime', 'Trend', 'Vol'
            ])

            # Calculate baseline and buy-hold values
            baseline_start_price = None
            if baseline_info and 'start_price' in baseline_info:
                baseline_start_price = baseline_info['start_price']
                baseline_shares = self.initial_capital / baseline_start_price

            buyhold_start_price = None
            buyhold_shares = None
            if signal_prices:
                # Get first price for buy-and-hold calculation
                first_snapshot = filtered_snapshots[0]
                first_date_str = first_snapshot['timestamp'].strftime('%Y-%m-%d')
                if first_date_str in signal_prices:
                    buyhold_start_price = signal_prices[first_date_str]
                    buyhold_shares = self.initial_capital / buyhold_start_price

            for snapshot in filtered_snapshots:
                timestamp = snapshot['timestamp']
                date_str = timestamp.strftime('%Y-%m-%d')
                date_obj = timestamp.date() if hasattr(timestamp, 'date') else timestamp

                # Portfolio value
                portfolio_value = float(snapshot.get('total_value', 0))

                # Baseline value (QQQ)
                baseline_value = ''
                if baseline_info and 'price_history' in baseline_info:
                    price_history = baseline_info['price_history']
                    current_price = price_history.get(date_obj)
                    if current_price and baseline_shares:
                        baseline_value = float(baseline_shares * current_price)

                # Buy-and-hold value
                buyhold_value = ''
                if signal_prices and buyhold_shares:
                    current_price = signal_prices.get(date_str)
                    if current_price:
                        buyhold_value = float(buyhold_shares * current_price)

                # Regime data
                regime = ''
                trend = ''
                vol = ''
                if date_obj in regime_lookup:
                    regime_entry = regime_lookup[date_obj]
                    regime = regime_entry.get('regime_cell', '')
                    trend = regime_entry.get('trend_state', '')
                    vol = regime_entry.get('vol_state', '')

                writer.writerow([
                    date_str,
                    f'{portfolio_value:.2f}',
                    f'{baseline_value:.2f}' if baseline_value else '',
                    f'{buyhold_value:.2f}' if buyhold_value else '',
                    regime,
                    trend,
                    vol
                ])

        logger.info(f"Dashboard CSV exported: {csv_path} ({len(filtered_snapshots)} days)")
        return str(csv_path)
