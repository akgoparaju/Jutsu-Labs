"""
Base interface for data handlers.

All data sources (Schwab, CSV, Yahoo, etc.) must implement this interface.
This allows the EventLoop to work with any data source without modification.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator, List, Optional

from jutsu_engine.core.events import MarketDataEvent


class DataHandler(ABC):
    """
    Abstract base class for data handlers.

    Data handlers are responsible for providing market data to the backtesting engine.
    They abstract the data source (database, API, CSV) from the EventLoop.

    Implementations:
        - DatabaseDataHandler: Reads from SQLite/PostgreSQL
        - SchwabDataFetcher: Fetches from Schwab API (for syncing)
        - CSVDataHandler: Reads from CSV files
        - (Future) YahooDataHandler, BinanceDataHandler, etc.

    Example:
        class DatabaseDataHandler(DataHandler):
            def get_next_bar(self) -> Iterator[MarketDataEvent]:
                for row in self.db.query(MarketData).yield_per(1000):
                    yield MarketDataEvent(
                        symbol=row.symbol,
                        timestamp=row.timestamp,
                        open=row.open,
                        ...
                    )
    """

    @abstractmethod
    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        """
        Yield bars one at a time for EventLoop processing.

        This is the primary method used during backtesting. Returns an iterator
        to avoid loading entire dataset into memory.

        Returns:
            Iterator of MarketDataEvent objects in chronological order

        Example:
            for bar in data_handler.get_next_bar():
                strategy.on_bar(bar)
        """
        pass

    @abstractmethod
    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        """
        Get the most recent bar for a symbol.

        Useful for strategies that need current market price.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Latest MarketDataEvent or None if no data

        Example:
            latest = data_handler.get_latest_bar('AAPL')
            if latest:
                current_price = latest.close
        """
        pass

    @abstractmethod
    def get_bars(
        self, symbol: str, start_date: datetime, end_date: datetime, limit: Optional[int] = None
    ) -> List[MarketDataEvent]:
        """
        Get bars for a date range.

        Used for indicator calculation that needs historical context.

        Args:
            symbol: Stock ticker symbol
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            limit: Optional max number of bars to return

        Returns:
            List of MarketDataEvent objects in chronological order

        Example:
            # Get last 20 bars
            bars = data_handler.get_bars(
                'AAPL',
                datetime(2024, 1, 1),
                datetime(2024, 12, 31),
                limit=20
            )
        """
        pass

    @abstractmethod
    def get_bars_lookback(self, symbol: str, lookback: int) -> List[MarketDataEvent]:
        """
        Get last N bars for a symbol.

        Convenient method for strategies that need recent history.

        Args:
            symbol: Stock ticker symbol
            lookback: Number of bars to retrieve

        Returns:
            List of MarketDataEvent objects (most recent first)

        Example:
            # Get last 20 bars for SMA calculation
            bars = data_handler.get_bars_lookback('AAPL', 20)
            closes = [bar.close for bar in bars]
            sma = sum(closes) / len(closes)
        """
        pass

    def get_symbols(self) -> List[str]:
        """
        Get list of available symbols.

        Optional method - not all handlers may implement this.

        Returns:
            List of stock ticker symbols

        Example:
            symbols = data_handler.get_symbols()
            # ['AAPL', 'MSFT', 'GOOGL', ...]
        """
        raise NotImplementedError("get_symbols not implemented for this handler")


class DataFetcher(ABC):
    """
    Abstract base class for data fetchers (API clients).

    DataFetchers are used to fetch data from external sources (APIs).
    They are separate from DataHandlers which provide data to EventLoop.

    Use case: DataSync uses DataFetcher to get new data, then stores in database.
    Later, DatabaseDataHandler reads from database for backtesting.

    Implementations:
        - SchwabDataFetcher: Fetches from Schwab API
        - YahooDataFetcher: Fetches from Yahoo Finance API
        - BinanceDataFetcher: Fetches from Binance API
    """

    @abstractmethod
    def fetch_bars(
        self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime
    ) -> List[MarketDataEvent]:
        """
        Fetch historical bars from external API.

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar period ('1D', '1H', '5m', etc.)
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of MarketDataEvent objects

        Raises:
            APIError: If API request fails
            RateLimitError: If rate limit exceeded

        Example:
            fetcher = SchwabDataFetcher(api_key, api_secret)
            bars = fetcher.fetch_bars(
                'AAPL', '1D',
                datetime(2024, 1, 1),
                datetime(2024, 12, 31)
            )
        """
        pass

    @abstractmethod
    def validate_credentials(self) -> bool:
        """
        Validate API credentials.

        Returns:
            True if credentials are valid

        Raises:
            AuthenticationError: If credentials are invalid
        """
        pass
