"""
Base interface for data fetchers.

Defines the contract that all data fetchers must implement.
Data fetchers are responsible for retrieving market data from
external sources (APIs, files, etc.).

Example:
    from jutsu_engine.data.fetchers.base import DataFetcher

    class MyDataFetcher(DataFetcher):
        def fetch_bars(self, symbol, timeframe, start_date, end_date):
            # Implementation here
            return bars
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any


class DataFetcher(ABC):
    """
    Abstract base class for market data fetchers.

    All data fetchers must implement this interface to be compatible
    with DataSync and other application components.

    Subclasses must implement:
        - fetch_bars(): Retrieve historical market data
    """

    @abstractmethod
    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical market data bars.

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
            timeframe: Bar timeframe ('1D', '1H', '5m', etc.)
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            List of dictionaries, each containing:
            - timestamp: datetime (bar timestamp in UTC)
            - open: Decimal (opening price)
            - high: Decimal (highest price)
            - low: Decimal (lowest price)
            - close: Decimal (closing price)
            - volume: int (trading volume)

        Raises:
            NotImplementedError: If not implemented by subclass
            ValueError: If parameters are invalid
            RuntimeError: If data fetch fails

        Example:
            bars = fetcher.fetch_bars(
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31)
            )

            for bar in bars:
                print(f"{bar['timestamp']}: ${bar['close']}")
        """
        raise NotImplementedError(
            "Subclasses must implement fetch_bars()"
        )

    def validate_parameters(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ):
        """
        Validate fetch parameters.

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar timeframe
            start_date: Start date
            end_date: End date

        Raises:
            ValueError: If parameters are invalid

        Example:
            fetcher.validate_parameters('AAPL', '1D', start, end)
        """
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")

        if not timeframe or not timeframe.strip():
            raise ValueError("Timeframe cannot be empty")

        if start_date >= end_date:
            raise ValueError(
                f"Start date ({start_date}) must be before end date ({end_date})"
            )

        # Compare end_date against current time, handling both naive and aware datetimes
        now = datetime.now(timezone.utc)
        # Convert to naive for comparison if end_date is naive
        if end_date.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)

        if end_date > now:
            raise ValueError(
                f"End date ({end_date}) cannot be in the future"
            )
