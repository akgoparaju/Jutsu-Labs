"""
Yahoo Finance data fetcher implementation.

Provides free historical market data using the yfinance library.
No authentication required, supports stocks, ETFs, indices, and currencies.

Example:
    from jutsu_engine.data.fetchers.yahoo import YahooDataFetcher
    from datetime import datetime

    fetcher = YahooDataFetcher()
    bars = fetcher.fetch_bars(
        symbol='AAPL',
        timeframe='1d',
        start_date=datetime(2020, 1, 1),
        end_date=datetime(2023, 1, 1)
    )
"""
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.data.fetchers.base import DataFetcher
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import yfinance as yf
import pandas as pd
import time
import logging
from requests.exceptions import HTTPError, Timeout, ConnectionError

logger = logging.getLogger('DATA.YAHOO')


class YahooDataFetcher(DataFetcher):
    """
    Yahoo Finance data fetcher using yfinance library.

    Features:
    - Free historical data
    - No authentication required
    - Supports stocks, ETFs, indices, currencies
    - Automatic handling of splits and dividends

    Examples:
        >>> fetcher = YahooDataFetcher()
        >>> bars = fetcher.fetch_bars(
        ...     symbol='AAPL',
        ...     timeframe='1d',
        ...     start_date=datetime(2020, 1, 1),
        ...     end_date=datetime(2023, 1, 1)
        ... )
    """

    def __init__(self, rate_limit_delay: float = 0.5):
        """
        Initialize Yahoo Finance fetcher.

        Args:
            rate_limit_delay: Delay between requests in seconds (default 0.5s = 2 req/s)
        """
        super().__init__()
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0.0

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str = '1d',
        start_date: datetime = None,
        end_date: datetime = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical bars from Yahoo Finance.

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            timeframe: Data interval ('1d', '1wk', '1mo', '1h', '5m', etc.)
            start_date: Start date for historical data
            end_date: End date for historical data
            **kwargs: Additional arguments (unused but required by interface)

        Returns:
            List of dictionaries containing OHLCV data with structure:
            - timestamp: datetime (bar timestamp in UTC)
            - open: Decimal (opening price)
            - high: Decimal (highest price)
            - low: Decimal (lowest price)
            - close: Decimal (closing price)
            - volume: int (trading volume)

        Raises:
            ValueError: If symbol is invalid or dates are malformed
            ConnectionError: If Yahoo Finance API is unreachable
        """
        # Validate inputs
        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"Invalid symbol: {symbol}")

        # Validate parameters using base class method
        self.validate_parameters(symbol, timeframe, start_date, end_date)

        symbol = symbol.upper()
        logger.info(
            f"Fetching {symbol} data from Yahoo Finance "
            f"({start_date} to {end_date}, {timeframe})"
        )

        # Apply rate limiting
        self._apply_rate_limit()

        try:
            # Fetch data using yfinance with retry logic
            bars = self._fetch_with_retry(
                symbol, timeframe, start_date, end_date,
                max_retries=3
            )

            logger.info(f"Retrieved {len(bars)} bars for {symbol}")
            return bars

        except HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 404:
                raise ValueError(f"Symbol {symbol} not found on Yahoo Finance")
            logger.error(f"HTTP error fetching {symbol}: {e}")
            raise ConnectionError(f"Yahoo Finance API error: {e}")

        except (Timeout, ConnectionError) as e:
            logger.error(f"Connection error fetching {symbol}: {e}")
            raise ConnectionError(f"Failed to connect to Yahoo Finance: {e}")

        except Exception as e:
            logger.error(f"Unexpected error fetching {symbol}: {e}", exc_info=True)
            raise

    def _fetch_with_retry(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Fetch bars with retry logic for transient errors.

        Args:
            symbol: Stock symbol
            timeframe: Data interval
            start_date: Start date
            end_date: End date
            max_retries: Maximum retry attempts

        Returns:
            List of bar dictionaries

        Raises:
            ConnectionError: If all retry attempts fail
            ValueError: If symbol is invalid (no retry)
        """
        for attempt in range(max_retries):
            try:
                # Fetch data using yfinance
                ticker = yf.Ticker(symbol)
                df = ticker.history(
                    start=start_date,
                    end=end_date,
                    interval=timeframe,
                    auto_adjust=False,  # Keep unadjusted prices
                    actions=False       # Don't include dividends/splits
                )

                if df.empty:
                    logger.warning(f"No data returned for {symbol}")
                    return []

                # Convert to bar dictionaries
                bars = self._convert_to_dicts(df, symbol)
                return bars

            except (Timeout, ConnectionError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {symbol}, "
                        f"retrying in {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"All {max_retries} attempts failed for {symbol}")
                    raise

            except ValueError as e:
                # Don't retry for invalid symbols
                logger.error(f"Invalid symbol {symbol}: {e}")
                raise

        # This should never be reached due to raise in loop
        return []

    def _apply_rate_limit(self):
        """Apply rate limiting between requests using token bucket algorithm."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last_request
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _convert_to_dicts(
        self,
        df: pd.DataFrame,
        symbol: str
    ) -> List[Dict[str, Any]]:
        """
        Convert yfinance DataFrame to bar dictionaries.

        Args:
            df: DataFrame from yfinance with OHLCV data
            symbol: Stock symbol

        Returns:
            List of bar dictionaries with OHLCV data
        """
        bars = []

        for timestamp, row in df.iterrows():
            try:
                # Create bar dictionary
                bar = {
                    'timestamp': timestamp.to_pydatetime(),
                    'open': Decimal(str(row['Open'])),
                    'high': Decimal(str(row['High'])),
                    'low': Decimal(str(row['Low'])),
                    'close': Decimal(str(row['Close'])),
                    'volume': int(row['Volume'])
                }

                # Validate bar
                if self._validate_bar_dict(bar):
                    bars.append(bar)
                else:
                    logger.warning(
                        f"Invalid bar for {symbol} at {timestamp}: skipping"
                    )

            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    f"Failed to convert bar for {symbol} at {timestamp}: {e}"
                )
                continue

        return bars

    def _validate_bar_dict(self, bar: Dict[str, Any]) -> bool:
        """
        Validate a single bar dictionary.

        Args:
            bar: Bar dictionary to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            # Check OHLC relationship
            if not (bar['low'] <= bar['open'] <= bar['high'] and
                    bar['low'] <= bar['close'] <= bar['high']):
                return False

            # Check for positive prices
            if bar['open'] <= 0 or bar['close'] <= 0:
                return False

            # Check for non-negative volume
            if bar['volume'] < 0:
                return False

            return True

        except (KeyError, TypeError):
            return False

    def get_symbols(self, **kwargs) -> List[str]:
        """
        Get list of available symbols.

        Note: Yahoo Finance doesn't provide a comprehensive symbol list API.
        This method returns empty list. Users should know their symbols.

        Args:
            **kwargs: Additional arguments (unused)

        Returns:
            Empty list
        """
        logger.warning("Yahoo Finance doesn't provide symbol list API")
        return []

    def validate_symbol(self, symbol: str) -> bool:
        """
        Validate if a symbol exists on Yahoo Finance.

        Args:
            symbol: Ticker symbol to validate

        Returns:
            True if symbol exists, False otherwise
        """
        try:
            self._apply_rate_limit()
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return 'symbol' in info or 'shortName' in info
        except Exception as e:
            logger.debug(f"Symbol validation failed for {symbol}: {e}")
            return False
