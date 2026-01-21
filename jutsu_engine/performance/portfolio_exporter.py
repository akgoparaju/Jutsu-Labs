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
from datetime import datetime, timezone
import pytz

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
        # Eastern timezone for NYSE trading date extraction
        self._et = pytz.timezone('America/New_York')
        logger.info(f"PortfolioCSVExporter initialized with initial capital: ${initial_capital:,.2f}")

    def _get_trading_date(self, timestamp: datetime) -> str:
        """
        Extract NYSE trading date from timestamp using Eastern Time.

        Schwab convention: daily bar timestamp is 06:00 UTC = 01:00 ET same day.
        Without ET conversion, Pacific timezone would show previous calendar day.

        Args:
            timestamp: Bar timestamp (may be naive UTC or timezone-aware)

        Returns:
            Trading date string in YYYY-MM-DD format
        """
        ts = timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_et = ts.astimezone(self._et)
        return ts_et.strftime("%Y-%m-%d")

    def export_daily_portfolio_csv(
        self,
        daily_snapshots: List[Dict],
        start_date: datetime,
        output_path: str,
        strategy_name: str,
        signal_symbol: Optional[str] = None,
        signal_prices: Optional[Dict[str, Decimal]] = None,
        baseline_info: Optional[Dict[str, Any]] = None,
        regime_data: Optional[List[Dict]] = None,
    ) -> str:
        """
        Export daily portfolio snapshots to CSV.

        Generates comprehensive CSV with portfolio value, cash, positions,
        and performance metrics for each trading day. Creates output directory
        if it doesn't exist.

        Args:
            daily_snapshots: List of daily portfolio state dictionaries from
                           PortfolioSimulator.get_daily_snapshots()
            start_date: Trading period start date (excludes warmup data before this)
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
            regime_data: Optional list of regime dicts with keys:
                'timestamp', 'regime_cell', 'trend_state', 'vol_state'

        Returns:
            Full path to generated CSV file

        Raises:
            ValueError: If daily_snapshots is empty or all snapshots are before start_date

        Note:
            Only snapshots >= start_date are exported (warmup period excluded).

            If signal_symbol and signal_prices are provided, adds buy-and-hold comparison
            column showing hypothetical value if 100% allocated to signal_symbol at start.

            If baseline_info is provided, adds baseline comparison columns:
            - Baseline_QQQ_Value: Dollar value of baseline portfolio
            - Baseline_Return_Pct: Cumulative baseline return percentage

        Example:
            csv_path = exporter.export_daily_portfolio_csv(
                daily_snapshots=portfolio.get_daily_snapshots(),
                start_date=datetime(2025, 10, 1, tzinfo=timezone.utc),
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

        # Filter snapshots to exclude warmup period
        # Use defensive timezone normalization (pattern from EventLoop timezone fix)
        from datetime import timezone

        start_date_normalized = start_date
        if start_date.tzinfo is None:
            start_date_normalized = start_date.replace(tzinfo=timezone.utc)

        filtered_snapshots = []
        for snapshot in daily_snapshots:
            timestamp = snapshot['timestamp']
            # Normalize snapshot timestamp if needed
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            # Include only snapshots >= start_date (trading period)
            if timestamp >= start_date_normalized:
                filtered_snapshots.append(snapshot)

        # Handle edge case: all snapshots before start_date
        if not filtered_snapshots:
            raise ValueError(
                f"No snapshots found after start_date {start_date}. "
                f"All {len(daily_snapshots)} snapshots are in warmup period."
            )

        logger.info(
            f"Filtered {len(daily_snapshots)} snapshots to {len(filtered_snapshots)} "
            f"(excluded {len(daily_snapshots) - len(filtered_snapshots)} warmup days)"
        )

        # Determine output file path
        output_file = self._get_output_path(output_path, strategy_name)

        # Get all tickers ever held (for column headers)
        all_tickers = self._get_all_tickers(filtered_snapshots)

        # Create CSV with all columns
        self._write_csv(
            filtered_snapshots,
            output_file,
            all_tickers,
            signal_symbol,
            signal_prices,
            baseline_info,
            regime_data
        )

        logger.info(
            f"Portfolio CSV exported: {output_file} "
            f"({len(filtered_snapshots)} days, {len(all_tickers)} tickers)"
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


    def _get_all_indicators(self, daily_snapshots: List[Dict]) -> List[str]:
        """
        Extract all unique indicator names from snapshots, sorted alphabetically.

        Indicators are strategy-specific and may vary between snapshots.
        This method ensures all indicator columns are present even if
        some days don't have certain indicators computed.

        Args:
            daily_snapshots: List of daily snapshot dictionaries

        Returns:
            Sorted list of all unique indicator names
        """
        indicators_set = set()
        for snapshot in daily_snapshots:
            # Get indicators dict (may be empty or missing)
            indicators = snapshot.get('indicators', {})
            if indicators:
                indicators_set.update(indicators.keys())
        return sorted(indicators_set)

    def _write_csv(
        self,
        daily_snapshots: List[Dict],
        output_file: str,
        all_tickers: List[str],
        signal_symbol: Optional[str] = None,
        signal_prices: Optional[Dict[str, Decimal]] = None,
        baseline_info: Optional[Dict[str, Any]] = None,
        regime_data: Optional[List[Dict]] = None,
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
            regime_data: Optional list of regime dicts
        """
        # Build regime lookup map for fast access (date string -> regime dict)
        regime_lookup = {}
        if regime_data:
            for regime_bar in regime_data:
                date_str = self._get_trading_date(regime_bar['timestamp'])
                regime_lookup[date_str] = regime_bar
            logger.debug(f"Built regime lookup map with {len(regime_lookup)} entries")

        # Build column headers
        fixed_columns = ['Date']

        # Add regime columns right after Date (only if regime data exists)
        if regime_data:
            fixed_columns.extend(['Regime', 'Trend', 'Vol'])

        # Add portfolio columns
        fixed_columns.extend([
            'Portfolio_Total_Value',
            'Portfolio_Day_Change_Pct',
            'Portfolio_Overall_Return',
            'Portfolio_PL_Percent',
        ])

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

        # Get all unique indicator names across all snapshots
        all_indicators = self._get_all_indicators(daily_snapshots)

        # Add indicator columns (one per indicator, prefixed with "Ind_")
        indicator_columns = [f"Ind_{name}" for name in all_indicators]

        headers = fixed_columns + ticker_columns + indicator_columns

        if all_indicators:
            logger.debug(f"Adding {len(all_indicators)} indicator columns: {all_indicators}")

        # Calculate buy-and-hold initial shares (if signal prices provided)
        if signal_prices and daily_snapshots:
            first_date = self._get_trading_date(daily_snapshots[0]['timestamp'])
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

            # Initialize forward-fill tracking (for handling non-trading days)
            self._last_baseline_value = None
            self._last_baseline_return = None
            self._last_buyhold_value = None

            # Write data rows
            prev_value = self.initial_capital
            for snapshot in daily_snapshots:
                row = self._build_row(
                    snapshot,
                    prev_value,
                    all_tickers,
                    all_indicators,
                    signal_symbol,
                    signal_prices,
                    buyhold_initial_shares,
                    baseline_info,
                    baseline_initial_shares,
                    regime_lookup
                )
                writer.writerow(row)
                prev_value = snapshot['total_value']

        logger.debug(f"CSV written: {output_file} with {len(headers)} columns")

    def _build_row(
        self,
        snapshot: Dict,
        prev_value: Decimal,
        all_tickers: List[str],
        all_indicators: List[str],
        signal_symbol: Optional[str] = None,
        signal_prices: Optional[Dict[str, Decimal]] = None,
        buyhold_initial_shares: Optional[Decimal] = None,
        baseline_info: Optional[Dict[str, Any]] = None,
        baseline_initial_shares: Optional[Decimal] = None,
        regime_lookup: Optional[Dict[str, Dict]] = None,
    ) -> List[str]:
        """
        Build single CSV row with all columns.

        Args:
            snapshot: Daily snapshot dictionary
            prev_value: Previous day's portfolio value for day change calculation
            all_tickers: Sorted list of all ticker symbols
            all_indicators: Sorted list of all indicator names
            signal_symbol: Optional symbol for buy-and-hold comparison
            signal_prices: Optional dict mapping date strings to prices
            buyhold_initial_shares: Optional initial shares for buy-and-hold calculation
            baseline_info: Optional dict with baseline data
            baseline_initial_shares: Optional initial shares for baseline calculation
            regime_lookup: Optional dict mapping date strings to regime data

        Returns:
            List of formatted string values for CSV row
        """
        # Fixed columns
        # Extract NYSE trading date using Eastern Time (market timezone)
        date = self._get_trading_date(snapshot['timestamp'])
        total_value = snapshot['total_value']

        # Start building row with date
        row = [date]

        # Add regime columns if regime lookup exists (non-empty dict)
        if regime_lookup:
            regime = regime_lookup.get(date)
            if regime:
                # Format: "Cell_1", "BullStrong", "Low"
                regime_cell = f"Cell_{regime['regime_cell']}"
                trend_state = regime['trend_state']
                vol_state = regime['vol_state']
                row.extend([regime_cell, trend_state, vol_state])
            else:
                # No regime data for this date (graceful handling)
                row.extend(['', '', ''])  # Empty strings for missing data

        # Calculate day change as percentage
        if prev_value != 0:
            day_change_pct = ((total_value - prev_value) / prev_value) * 100
        else:
            day_change_pct = Decimal('0.0')

        overall_return = ((total_value - self.initial_capital) / self.initial_capital) * 100
        pl_percent = overall_return  # Same as overall return (cumulative)
        cash = snapshot['cash']

        # Add portfolio columns to row
        row.extend([
            f"{total_value:.2f}",       # $X.XX format
            f"{day_change_pct:.4f}",    # X.XXXX% format (4 decimals like other %)
            f"{overall_return:.4f}",    # X.XXXX% format
            f"{pl_percent:.4f}",        # X.XXXX% format
        ])

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

                # Store for forward-fill on non-trading days
                self._last_baseline_value = baseline_value
                self._last_baseline_return = baseline_return_pct

                row.append(f"{baseline_value:.2f}")      # $X.XX format
                row.append(f"{baseline_return_pct:.4f}") # X.XXXX% format
            else:
                # Date not in price history (e.g., weekend/holiday)
                # Forward-fill from last valid trading day instead of writing "N/A"
                if self._last_baseline_value is not None:
                    row.append(f"{self._last_baseline_value:.2f}")
                    row.append(f"{self._last_baseline_return:.4f}")
                else:
                    # First day is a non-trading day (unlikely but handle gracefully)
                    row.append(f"{self.initial_capital:.2f}")
                    row.append("0.0000")

        # Add cash column
        row.append(f"{cash:.2f}")      # $X.XX format

        # Add buy-and-hold value if applicable
        # CRITICAL: Condition must match header condition (signal_prices only)
        # to prevent column shift when buyhold_initial_shares is None
        if signal_prices:
            if buyhold_initial_shares is not None:
                date_str = self._get_trading_date(snapshot['timestamp'])
                current_signal_price = signal_prices.get(date_str)

                if current_signal_price:
                    buyhold_value = buyhold_initial_shares * current_signal_price
                   
                    # Store for forward-fill on non-trading days
                    self._last_buyhold_value = buyhold_value
                    
                    row.append(f"{buyhold_value:.2f}")
                else:
                    # Date not in price history (e.g., weekend/holiday)
                    # Forward-fill from last valid trading day instead of writing "N/A"
                    if self._last_buyhold_value is not None:
                        row.append(f"{self._last_buyhold_value:.2f}")
                    else:
                        # First day is a non-trading day (unlikely but handle gracefully)
                        row.append(f"{self.initial_capital:.2f}")
            else:
                # buyhold_initial_shares is None (first day price missing)
                # Use initial_capital to maintain column alignment
                row.append(f"{self.initial_capital:.2f}")

        # Dynamic ticker columns (show 0 if ticker not held)
        for ticker in all_tickers:
            qty = snapshot['positions'].get(ticker, 0)
            value = snapshot['holdings'].get(ticker, Decimal('0.00'))
            row.extend([str(qty), f"{value:.2f}"])

        # Indicator columns (show empty if indicator not present for this day)
        snapshot_indicators = snapshot.get('indicators', {})
        for indicator_name in all_indicators:
            value = snapshot_indicators.get(indicator_name)
            if value is not None:
                # Format with 6 decimal places for precision
                row.append(f"{value:.6f}")
            else:
                # Indicator not computed for this day (e.g., during warmup)
                row.append("")

        return row
