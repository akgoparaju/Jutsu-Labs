"""
CSV file data handler for custom market data.

Supports flexible CSV format detection and validation for importing
historical market data from various CSV sources.
"""
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Any
import logging
import re

import pandas as pd

from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.data.handlers.base import DataHandler


logger = logging.getLogger('DATA.CSV')


class CSVDataHandler(DataHandler):
    """
    CSV file data handler with flexible format detection.

    Supports common CSV formats:
    - Date,Open,High,Low,Close,Volume
    - Timestamp,OHLCV
    - Custom column mappings

    Features:
    - Auto-detect date formats
    - Streaming for large files
    - Data validation and cleaning
    - Batch import support

    Examples:
        >>> handler = CSVDataHandler(
        ...     file_path='data/AAPL.csv',
        ...     symbol='AAPL'
        ... )
        >>> for bar in handler.get_next_bar():
        ...     print(bar)
    """

    COMMON_FORMATS = {
        'standard': {
            'date': ['Date', 'date', 'Datetime', 'datetime', 'Timestamp', 'timestamp'],
            'open': ['Open', 'open', 'OPEN'],
            'high': ['High', 'high', 'HIGH'],
            'low': ['Low', 'low', 'LOW'],
            'close': ['Close', 'close', 'CLOSE'],
            'volume': ['Volume', 'volume', 'VOLUME', 'Vol']
        }
    }

    def __init__(
        self,
        file_path: str,
        symbol: Optional[str] = None,
        column_mapping: Optional[Dict[str, str]] = None,
        date_format: Optional[str] = None,
        chunksize: int = 10000
    ):
        """
        Initialize CSV data handler.

        Args:
            file_path: Path to CSV file
            symbol: Stock symbol (extracted from filename if None)
            column_mapping: Custom column name mapping
            date_format: Date format string (auto-detected if None)
            chunksize: Number of rows to read at a time for streaming

        Raises:
            FileNotFoundError: If CSV file does not exist
            ValueError: If CSV format cannot be detected
        """
        super().__init__()
        self.file_path = Path(file_path)
        self.symbol = symbol or self._extract_symbol_from_filename()
        self.column_mapping = column_mapping or {}
        self.date_format = date_format
        self.chunksize = chunksize
        self._current_data: Optional[pd.DataFrame] = None

        if not self.file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.file_path}")

        # Detect format if not provided
        if not self.column_mapping:
            self.column_mapping = self._detect_format()

        logger.info(f"Initialized CSV handler for {self.symbol} from {self.file_path}")

    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        """
        Stream bars from CSV file.

        Yields:
            MarketDataEvent objects

        Raises:
            ValueError: If required columns are missing
        """
        logger.info(f"Reading CSV file: {self.file_path}")

        # Stream CSV file in chunks for memory efficiency
        for chunk in pd.read_csv(self.file_path, chunksize=self.chunksize):
            # Rename columns according to mapping
            chunk = chunk.rename(columns=self.column_mapping)

            # Validate required columns
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            missing = [col for col in required_cols if col not in chunk.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")

            # Convert to MarketDataEvent objects
            for _, row in chunk.iterrows():
                try:
                    event = self._row_to_event(row)
                    if event and self._validate_bar(event):
                        yield event
                except Exception as e:
                    logger.warning(f"Failed to convert row: {e}")
                    continue

        logger.info(f"Finished reading CSV file: {self.file_path}")

    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        """
        Get the most recent bar from CSV file.

        Args:
            symbol: Stock symbol

        Returns:
            Most recent MarketDataEvent or None
        """
        if symbol != self.symbol:
            logger.warning(f"Symbol mismatch: requested {symbol}, have {self.symbol}")
            return None

        # Read last row
        df = pd.read_csv(self.file_path)
        if df.empty:
            return None

        df = df.rename(columns=self.column_mapping)
        last_row = df.iloc[-1]

        try:
            return self._row_to_event(last_row)
        except Exception as e:
            logger.error(f"Failed to get latest bar: {e}")
            return None

    def get_bars(
        self, symbol: str, start_date: datetime, end_date: datetime, limit: Optional[int] = None
    ) -> List[MarketDataEvent]:
        """
        Get bars for a date range.

        Args:
            symbol: Stock ticker symbol
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            limit: Optional max number of bars to return

        Returns:
            List of MarketDataEvent objects in chronological order
        """
        if symbol != self.symbol:
            logger.warning(f"Symbol mismatch: requested {symbol}, have {self.symbol}")
            return []

        # Load full dataset
        df = pd.read_csv(self.file_path)
        df = df.rename(columns=self.column_mapping)

        # Parse dates
        df['date'] = pd.to_datetime(df['date'])

        # Filter by date range
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        df_filtered = df.loc[mask]

        # Apply limit
        if limit is not None:
            df_filtered = df_filtered.tail(limit)

        # Convert to events
        bars = []
        for _, row in df_filtered.iterrows():
            try:
                event = self._row_to_event(row)
                if event and self._validate_bar(event):
                    bars.append(event)
            except Exception as e:
                logger.warning(f"Failed to convert row: {e}")
                continue

        logger.info(f"Retrieved {len(bars)} bars for {symbol} from {start_date} to {end_date}")
        return bars

    def get_bars_lookback(self, symbol: str, lookback: int) -> List[MarketDataEvent]:
        """
        Get last N bars for a symbol.

        Args:
            symbol: Stock ticker symbol
            lookback: Number of bars to retrieve

        Returns:
            List of MarketDataEvent objects (most recent first)
        """
        if symbol != self.symbol:
            logger.warning(f"Symbol mismatch: requested {symbol}, have {self.symbol}")
            return []

        # Read last N rows
        df = pd.read_csv(self.file_path)
        df = df.rename(columns=self.column_mapping)
        df_tail = df.tail(lookback)

        # Convert to events
        bars = []
        for _, row in df_tail.iterrows():
            try:
                event = self._row_to_event(row)
                if event and self._validate_bar(event):
                    bars.append(event)
            except Exception as e:
                logger.warning(f"Failed to convert row: {e}")
                continue

        logger.info(f"Retrieved last {len(bars)} bars for {symbol}")
        return bars

    def get_symbols(self) -> List[str]:
        """
        Get list of available symbols.

        Returns:
            List containing the single symbol for this CSV file
        """
        return [self.symbol]

    def _extract_symbol_from_filename(self) -> str:
        """
        Extract symbol from filename.

        Examples:
            AAPL.csv -> AAPL
            AAPL_daily.csv -> AAPL
            2023_MSFT.csv -> MSFT

        Returns:
            Extracted symbol in uppercase
        """
        filename = self.file_path.stem  # Remove .csv extension

        # Remove common suffixes
        for suffix in ['_daily', '_1d', '_1h', '_data']:
            filename = filename.replace(suffix, '')

        # Remove dates (YYYY, YYYY-MM-DD)
        filename = re.sub(r'\d{4}[-_]?\d{0,2}[-_]?\d{0,2}', '', filename)

        # Remove leading/trailing underscores
        symbol = filename.strip('_- ')

        return symbol.upper()

    def _detect_format(self) -> Dict[str, str]:
        """
        Auto-detect CSV format by reading first few rows.

        Returns:
            Column mapping dict

        Raises:
            ValueError: If CSV format cannot be detected
        """
        # Read first row to get column names
        df = pd.read_csv(self.file_path, nrows=1)
        columns = df.columns.tolist()

        logger.debug(f"Detected columns: {columns}")

        mapping = {}

        # Match columns to standard names
        for standard_name, possible_names in self.COMMON_FORMATS['standard'].items():
            for col in columns:
                if col in possible_names:
                    mapping[col] = standard_name
                    break

        if not mapping:
            raise ValueError(f"Could not detect CSV format. Columns: {columns}")

        logger.info(f"Detected format mapping: {mapping}")
        return mapping

    def _row_to_event(self, row: pd.Series) -> MarketDataEvent:
        """
        Convert DataFrame row to MarketDataEvent.

        Args:
            row: DataFrame row

        Returns:
            MarketDataEvent object

        Raises:
            ValueError: If row data is invalid
        """
        # Parse date
        date_str = str(row['date'])
        if self.date_format:
            timestamp = datetime.strptime(date_str, self.date_format)
        else:
            timestamp = pd.to_datetime(date_str)

        # Create event
        return MarketDataEvent(
            symbol=self.symbol,
            timestamp=timestamp,
            timeframe='1d',  # Default to daily
            open=Decimal(str(row['open'])),
            high=Decimal(str(row['high'])),
            low=Decimal(str(row['low'])),
            close=Decimal(str(row['close'])),
            volume=int(row['volume'])
        )

    def _validate_bar(self, bar: MarketDataEvent) -> bool:
        """
        Validate a single bar.

        Args:
            bar: MarketDataEvent to validate

        Returns:
            True if valid, False otherwise
        """
        # Check OHLC relationship
        if not (bar.low <= bar.open <= bar.high and
                bar.low <= bar.close <= bar.high):
            logger.warning(f"Invalid OHLC relationship for {bar.symbol} at {bar.timestamp}")
            return False

        # Check for non-zero prices
        if bar.open <= 0 or bar.close <= 0:
            logger.warning(f"Non-positive prices for {bar.symbol} at {bar.timestamp}")
            return False

        # Check for non-negative volume
        if bar.volume < 0:
            logger.warning(f"Negative volume for {bar.symbol} at {bar.timestamp}")
            return False

        return True

    @staticmethod
    def batch_import(
        directory: str,
        pattern: str = "*.csv",
        **kwargs: Any
    ) -> Dict[str, List[MarketDataEvent]]:
        """
        Import multiple CSV files from a directory.

        Args:
            directory: Directory containing CSV files
            pattern: Glob pattern for file matching
            **kwargs: Arguments passed to CSVDataHandler

        Returns:
            Dict mapping symbols to lists of MarketDataEvent objects

        Example:
            >>> results = CSVDataHandler.batch_import('data/stocks/')
            >>> for symbol, bars in results.items():
            ...     print(f"{symbol}: {len(bars)} bars")
        """
        directory = Path(directory)
        csv_files = list(directory.glob(pattern))

        logger.info(f"Found {len(csv_files)} CSV files in {directory}")

        results = {}
        for csv_file in csv_files:
            try:
                handler = CSVDataHandler(file_path=str(csv_file), **kwargs)
                bars = list(handler.get_next_bar())
                results[handler.symbol] = bars
                logger.info(f"Imported {len(bars)} bars for {handler.symbol}")
            except Exception as e:
                logger.error(f"Failed to import {csv_file}: {e}")
                continue

        return results
