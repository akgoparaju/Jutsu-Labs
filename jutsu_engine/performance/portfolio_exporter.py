"""
Portfolio CSV exporter for daily portfolio snapshots.

Generates comprehensive CSV reports with portfolio value, positions,
and performance metrics for each trading day.

Example:
    from jutsu_engine.performance.portfolio_exporter import PortfolioCSVExporter
    from decimal import Decimal

    exporter = PortfolioCSVExporter(initial_capital=Decimal('100000'))
    csv_path = exporter.export_daily_portfolio_csv(
        daily_snapshots=portfolio.get_daily_snapshots(),
        output_path="output",
        strategy_name="MACD_Trend"
    )
    print(f"Portfolio CSV: {csv_path}")
"""
from decimal import Decimal
from typing import List, Dict, Optional, Any
from pathlib import Path
import csv
from datetime import datetime

from jutsu_engine.utils.logging_config import get_performance_logger

logger = get_performance_logger()


class PortfolioCSVExporter:
    """
    Exports daily portfolio snapshots to CSV format.

    Creates comprehensive CSV reports with fixed columns (date, value, returns,
    cash) and dynamic ticker columns (quantity and value for each ticker ever held).

    Features:
    - Fixed columns: Date, total value, day change, returns, P/L%, cash
    - Dynamic ticker columns: All tickers ever held with qty and value
    - Precision: $X.XX (2 decimals), X.XXXX% (4 decimals)
    - All-ticker logic: Shows 0 qty/$0.00 for tickers not held on a given day

    Attributes:
        initial_capital: Starting portfolio value for return calculations
    """

    def __init__(self, initial_capital: Decimal):
        """
        Initialize exporter with initial capital for return calculations.

        Args:
            initial_capital: Starting portfolio value

        Example:
            exporter = PortfolioCSVExporter(Decimal('100000'))
        """
        self.initial_capital = initial_capital
        logger.info(f"PortfolioCSVExporter initialized with initial capital: ${initial_capital:,.2f}")

    def export_daily_portfolio_csv(
        self,
        daily_snapshots: List[Dict],
        output_path: str,
        strategy_name: str,
        signal_symbol: Optional[str] = None,
        signal_prices: Optional[Dict[str, Decimal]] = None,
        baseline_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Export daily portfolio snapshots to CSV.

        Generates comprehensive CSV with portfolio value, cash, positions,
        and performance metrics for each trading day. Creates output directory
        if it doesn't exist.

        Args:
            daily_snapshots: List of daily portfolio state dictionaries from
                           PortfolioSimulator.get_daily_snapshots()
            output_path: Directory or full file path for CSV output
                       If directory: creates {strategy}_{timestamp}.csv
                       If file path: uses exact path
            strategy_name: Strategy name for filename generation
            signal_symbol: Optional symbol for buy-and-hold comparison (e.g., 'QQQ')
            signal_prices: Optional dict mapping date strings to prices {YYYY-MM-DD: Decimal}
            baseline_info: Optional dict with baseline data for daily comparison
                Required keys: 'start_price', 'price_history', 'symbol'
                - start_price: QQQ price at backtest start
                - price_history: Dict[date, price] for daily QQQ prices
                - symbol: Baseline symbol (e.g., 'QQQ')

        Returns:
            Full path to generated CSV file

        Raises:
            ValueError: If daily_snapshots is empty

        Note:
            If signal_symbol and signal_prices are provided, adds buy-and-hold comparison
            column showing hypothetical value if 100% allocated to signal_symbol at start.

            If baseline_info is provided, adds baseline comparison columns:
            - Baseline_QQQ_Value: Dollar value of baseline portfolio
            - Baseline_Return_Pct: Cumulative baseline return percentage

        Example:
            csv_path = exporter.export_daily_portfolio_csv(
                daily_snapshots=portfolio.get_daily_snapshots(),
                output_path="output",
                strategy_name="MACD_Trend",
                baseline_info={
                    'symbol': 'QQQ',
                    'start_price': Decimal('100.00'),
                    'price_history': {date1: price1, date2: price2, ...}
                }
            )
            # Creates: output/MACD_Trend_20250107_143022.csv
        """
        if not daily_snapshots:
            raise ValueError("Cannot export empty daily snapshots")

        # Determine output file path
        output_file = self._get_output_path(output_path, strategy_name)

        # Get all tickers ever held (for column headers)
        all_tickers = self._get_all_tickers(daily_snapshots)

        # Create CSV with all columns
        self._write_csv(
            daily_snapshots,
            output_file,
            all_tickers,
            signal_symbol,
            signal_prices,
            baseline_info
        )

        logger.info(
            f"Portfolio CSV exported: {output_file} "
            f"({len(daily_snapshots)} days, {len(all_tickers)} tickers)"
        )
        return output_file

    def _get_output_path(self, output_path: str, strategy_name: str) -> str:
        """
        Determine final output file path.

        Args:
            output_path: Directory or file path
            strategy_name: Strategy name for filename

        Returns:
            Full path to CSV file
        """
        path = Path(output_path)

        # If output_path is directory or has no extension, create filename
        if path.is_dir() or not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{strategy_name}_{timestamp}.csv"
            return str(path / filename)

        # If output_path includes filename, use as-is
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _get_all_tickers(self, daily_snapshots: List[Dict]) -> List[str]:
        """
        Extract all unique tickers from snapshots, sorted alphabetically.

        Args:
            daily_snapshots: List of daily snapshot dictionaries

        Returns:
            Sorted list of all unique ticker symbols
        """
        tickers_set = set()
        for snapshot in daily_snapshots:
            tickers_set.update(snapshot['positions'].keys())
        return sorted(tickers_set)

    def _write_csv(
        self,
        daily_snapshots: List[Dict],
        output_file: str,
        all_tickers: List[str],
        signal_symbol: Optional[str] = None,
        signal_prices: Optional[Dict[str, Decimal]] = None,
        baseline_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Write CSV with all columns and data.

        Args:
            daily_snapshots: List of daily snapshot dictionaries
            output_file: Full path to output CSV file
            all_tickers: Sorted list of all ticker symbols
            signal_symbol: Optional symbol for buy-and-hold comparison
            signal_prices: Optional dict mapping date strings to prices
            baseline_info: Optional dict with baseline data for daily comparison
        """
        # Build column headers
        fixed_columns = [
            'Date',
            'Portfolio_Total_Value',
            'Portfolio_Day_Change_Pct',
            'Portfolio_Overall_Return',
            'Portfolio_PL_Percent',
        ]

        # Add baseline columns if baseline info provided
        if baseline_info:
            baseline_symbol = baseline_info.get('symbol', 'QQQ')
            fixed_columns.extend([
                f'Baseline_{baseline_symbol}_Value',
                f'Baseline_{baseline_symbol}_Return_Pct'
            ])

        # Add cash column after baseline columns
        fixed_columns.append('Cash')

        # Add buy-and-hold column if signal prices provided
        if signal_prices:
            fixed_columns.append(f'BuyHold_{signal_symbol}_Value')

        # Add dynamic ticker columns (qty and value for each ticker)
        ticker_columns = []
        for ticker in all_tickers:
            ticker_columns.extend([f"{ticker}_Qty", f"{ticker}_Value"])

        headers = fixed_columns + ticker_columns

        # Calculate buy-and-hold initial shares (if signal prices provided)
        if signal_prices and daily_snapshots:
            first_date = daily_snapshots[0]['timestamp'].strftime("%Y-%m-%d")
            first_signal_price = signal_prices.get(first_date)

            if first_signal_price and first_signal_price > 0:
                buyhold_initial_shares = self.initial_capital / first_signal_price
                logger.debug(
                    f"Buy-and-hold: {buyhold_initial_shares:.2f} shares of {signal_symbol} "
                    f"at ${first_signal_price:.2f} = ${self.initial_capital:.2f}"
                )
            else:
                buyhold_initial_shares = None
                logger.warning(f"No price data for {signal_symbol} on {first_date}, skipping buy-and-hold column")
        else:
            buyhold_initial_shares = None

        # Calculate baseline initial shares (if baseline info provided)
        baseline_initial_shares = None
        if baseline_info:
            try:
                start_price = baseline_info.get('start_price')
                baseline_symbol = baseline_info.get('symbol', 'QQQ')

                if start_price and start_price > 0:
                    baseline_initial_shares = self.initial_capital / start_price
                    logger.debug(
                        f"Baseline: {baseline_initial_shares:.2f} shares of {baseline_symbol} "
                        f"at ${start_price:.2f} = ${self.initial_capital:.2f}"
                    )
                else:
                    logger.warning(f"Invalid baseline start_price: {start_price}, skipping baseline columns")
            except Exception as e:
                logger.warning(f"Failed to calculate baseline shares: {e}")
                baseline_initial_shares = None

        # Write CSV
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            # Write data rows
            prev_value = self.initial_capital
            for snapshot in daily_snapshots:
                row = self._build_row(
                    snapshot,
                    prev_value,
                    all_tickers,
                    signal_symbol,
                    signal_prices,
                    buyhold_initial_shares,
                    baseline_info,
                    baseline_initial_shares
                )
                writer.writerow(row)
                prev_value = snapshot['total_value']

        logger.debug(f"CSV written: {output_file} with {len(headers)} columns")

    def _build_row(
        self,
        snapshot: Dict,
        prev_value: Decimal,
        all_tickers: List[str],
        signal_symbol: Optional[str] = None,
        signal_prices: Optional[Dict[str, Decimal]] = None,
        buyhold_initial_shares: Optional[Decimal] = None,
        baseline_info: Optional[Dict[str, Any]] = None,
        baseline_initial_shares: Optional[Decimal] = None,
    ) -> List[str]:
        """
        Build single CSV row with all columns.

        Args:
            snapshot: Daily snapshot dictionary
            prev_value: Previous day's portfolio value for day change calculation
            all_tickers: Sorted list of all ticker symbols
            signal_symbol: Optional symbol for buy-and-hold comparison
            signal_prices: Optional dict mapping date strings to prices
            buyhold_initial_shares: Optional initial shares for buy-and-hold calculation
            baseline_info: Optional dict with baseline data
            baseline_initial_shares: Optional initial shares for baseline calculation

        Returns:
            List of formatted string values for CSV row
        """
        # Fixed columns
        date = snapshot['timestamp'].strftime("%Y-%m-%d")
        total_value = snapshot['total_value']

        # Calculate day change as percentage
        if prev_value != 0:
            day_change_pct = ((total_value - prev_value) / prev_value) * 100
        else:
            day_change_pct = Decimal('0.0')

        overall_return = ((total_value - self.initial_capital) / self.initial_capital) * 100
        pl_percent = overall_return  # Same as overall return (cumulative)
        cash = snapshot['cash']

        # Format with required precision
        row = [
            date,
            f"{total_value:.2f}",       # $X.XX format
            f"{day_change_pct:.4f}",    # X.XXXX% format (4 decimals like other %)
            f"{overall_return:.4f}",    # X.XXXX% format
            f"{pl_percent:.4f}",        # X.XXXX% format
        ]

        # Add baseline values if applicable
        if baseline_initial_shares is not None and baseline_info:
            price_history = baseline_info.get('price_history', {})
            date_obj = snapshot['timestamp'].date()

            if date_obj in price_history:
                current_price = price_history[date_obj]
                # Calculate baseline portfolio value
                baseline_value = baseline_initial_shares * current_price
                # Calculate cumulative return
                baseline_return_pct = ((baseline_value - self.initial_capital) / self.initial_capital) * 100

                row.append(f"{baseline_value:.2f}")      # $X.XX format
                row.append(f"{baseline_return_pct:.4f}") # X.XXXX% format
            else:
                # Date not in price history (e.g., weekend/holiday)
                row.append("N/A")
                row.append("N/A")

        # Add cash column
        row.append(f"{cash:.2f}")      # $X.XX format

        # Add buy-and-hold value if applicable
        if buyhold_initial_shares is not None and signal_prices:
            date_str = snapshot['timestamp'].strftime("%Y-%m-%d")
            current_signal_price = signal_prices.get(date_str)

            if current_signal_price:
                buyhold_value = buyhold_initial_shares * current_signal_price
                row.append(f"{buyhold_value:.2f}")
            else:
                # No price data for this date
                row.append("N/A")

        # Dynamic ticker columns (show 0 if ticker not held)
        for ticker in all_tickers:
            qty = snapshot['positions'].get(ticker, 0)
            value = snapshot['holdings'].get(ticker, Decimal('0.00'))
            row.extend([str(qty), f"{value:.2f}"])

        return row
