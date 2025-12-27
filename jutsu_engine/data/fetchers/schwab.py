"""
Schwab API data fetcher implementation using schwab-py library.

This module uses the official schwab-py library which handles:
- OAuth authorization code flow with browser-based authentication
- Token file persistence and automatic refresh
- Proper API authentication for market data endpoints

First-time setup:
1. Ensure .env has: SCHWAB_API_KEY, SCHWAB_API_SECRET, SCHWAB_CALLBACK_URL, SCHWAB_TOKEN_PATH
2. Run `jutsu sync` - it will open a browser for authentication
3. After login, tokens are saved to token.json and auto-refreshed

References:
    - schwab-py documentation: https://github.com/alexgolec/schwab-py
    - Schwab API docs: https://developer.schwab.com

Example:
    from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher

    fetcher = SchwabDataFetcher()
    bars = fetcher.fetch_bars(
        symbol='AAPL',
        timeframe='1D',
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31)
    )
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests
from schwab import auth
from schwab.client import Client

from jutsu_engine.data.fetchers.base import DataFetcher
from jutsu_engine.utils.config import get_config
from jutsu_engine.utils.logging_config import get_data_logger

logger = get_data_logger('SCHWAB')


class APIError(Exception):
    """API request error."""
    pass


class AuthError(Exception):
    """Authentication error."""
    pass


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_requests: int = 2, time_window: float = 1.0):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window (default: 2)
            time_window: Time window in seconds (default: 1.0)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: List[float] = []

    def wait_if_needed(self) -> None:
        """Wait if necessary to maintain rate limit."""
        now = time.time()

        # Remove requests outside time window
        self.requests = [
            req_time for req_time in self.requests if now - req_time < self.time_window
        ]

        # If at limit, wait
        if len(self.requests) >= self.max_requests:
            oldest = self.requests[0]
            wait_time = self.time_window - (now - oldest)
            if wait_time > 0:
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                time.sleep(wait_time)
                # Re-update now after waiting
                now = time.time()

        # Record this request
        self.requests.append(now)


class SchwabDataFetcher(DataFetcher):
    """
    Schwab API data fetcher using schwab-py library.

    Handles OAuth authentication with browser-based flow and token persistence.
    Automatically manages token refresh and API rate limiting.

    Environment Variables Required:
        SCHWAB_API_KEY: Your Schwab API Client ID
        SCHWAB_API_SECRET: Your Schwab API Secret
        SCHWAB_CALLBACK_URL: OAuth callback URL (default: https://127.0.0.1:8182)
        SCHWAB_TOKEN_PATH: Path to token.json file (default: ./token.json)

    Example:
        fetcher = SchwabDataFetcher()
        bars = fetcher.fetch_bars('AAPL', '1D', start_date, end_date)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        callback_url: Optional[str] = None,
        token_path: Optional[str] = None,
    ):
        """
        Initialize Schwab data fetcher with schwab-py client.

        Args:
            api_key: Schwab API key (defaults to config/env)
            api_secret: Schwab API secret (defaults to config/env)
            callback_url: OAuth callback URL (defaults to config/env)
            token_path: Path to token.json file (defaults to config/env)

        Raises:
            ValueError: If required environment variables are missing
            Exception: If authentication fails

        Example:
            # Use credentials from .env
            fetcher = SchwabDataFetcher()

            # Or provide explicitly
            fetcher = SchwabDataFetcher(
                api_key='your_key',
                api_secret='your_secret'
            )
        """
        config = get_config()

        # Load configuration from parameters or environment/config
        self.api_key = api_key or config.schwab_api_key
        self.api_secret = api_secret or config.schwab_api_secret
        # IMPORTANT: schwab-py only allows 127.0.0.1, NOT localhost
        # See: https://schwab-py.readthedocs.io/en/latest/auth.html#callback-url-advisory
        self.callback_url = (
            callback_url
            or os.getenv('SCHWAB_CALLBACK_URL')
            or 'https://127.0.0.1:8182'
        )

        # Get token path from parameter or environment
        token_path_raw = token_path or os.getenv('SCHWAB_TOKEN_PATH', 'token.json')

        # Handle Docker paths - match logic in schwab_auth.py
        # In Docker, /app exists and token files are stored in /app/data/
        if Path('/app').exists() and not token_path_raw.startswith('/'):
            self.token_path = f'/app/data/{token_path_raw}'
        else:
            self.token_path = token_path_raw

        # Validate credentials
        if not self.api_key or not self.api_secret:
            logger.error("Missing Schwab API credentials in environment")
            raise ValueError(
                "SCHWAB_API_KEY and SCHWAB_API_SECRET must be set in .env file. "
                "Get credentials from https://developer.schwab.com"
            )

        # Check if credentials are placeholders
        if 'your_api_key_here' in self.api_key or 'your_api_secret_here' in self.api_secret:
            logger.error("Placeholder credentials detected in .env file")
            raise ValueError(
                "Please replace placeholder credentials in .env file with your actual "
                "Schwab API credentials from https://developer.schwab.com"
            )

        # Initialize client as None (lazy initialization)
        self._client: Optional[Client] = None

        # Initialize rate limiter (2 requests per second)
        self._rate_limiter = RateLimiter(max_requests=2, time_window=1.0)

        logger.info("Schwab data fetcher initialized")
        logger.debug(f"Token path: {self.token_path}")
        logger.debug("Rate limiter initialized: 2 requests/second")

    def _check_token_validity(self) -> Tuple[bool, bool, Optional[float]]:
        """
        Check if token file exists and is valid (not expired).

        Schwab tokens expire after 7 days and require re-authentication.
        This check prevents easy_client() from blocking in Docker environments
        when the token is expired.

        Returns:
            Tuple of (exists: bool, is_valid: bool, expires_in_days: Optional[float])
        """
        if not os.path.exists(self.token_path):
            return False, False, None

        try:
            with open(self.token_path, 'r') as f:
                token_data = json.load(f)

            # schwab-py wraps tokens with metadata including creation_timestamp
            if 'creation_timestamp' not in token_data:
                # Legacy token format - can't determine validity, assume expired
                logger.warning("Token file has legacy format without creation_timestamp")
                return True, False, None

            creation_ts = token_data['creation_timestamp']
            age_seconds = time.time() - creation_ts

            # Schwab tokens expire after 7 days
            max_age_seconds = 7 * 24 * 60 * 60
            remaining_seconds = max_age_seconds - age_seconds
            expires_in_days = remaining_seconds / (24 * 60 * 60)

            is_valid = remaining_seconds > 0
            return True, is_valid, expires_in_days

        except (json.JSONDecodeError, KeyError, IOError) as e:
            logger.warning(f"Error reading token file: {e}")
            return True, False, None

    def _get_client(self) -> Client:
        """
        Get or create authenticated Schwab client.

        On first run without token.json, this will:
        1. Open a browser for user authentication
        2. User logs in to Schwab
        3. Token is saved to token.json
        4. Subsequent runs reuse token (auto-refresh handled by schwab-py)

        Returns:
            Authenticated Schwab client

        Raises:
            Exception: If authentication fails
        """
        if self._client is not None:
            return self._client

        try:
            # Check if token file exists AND is valid (not expired)
            # CRITICAL: In Docker/headless environments, easy_client blocks forever
            # if the token is missing OR expired (it tries to open browser for OAuth)
            # See: https://schwab-py.readthedocs.io/en/latest/auth.html
            token_exists, token_valid, expires_in_days = self._check_token_validity()
            is_docker = Path('/app').exists()

            if not token_exists:
                if is_docker:
                    logger.error(
                        f"No Schwab token found at {self.token_path}. "
                        "In Docker, authenticate via dashboard /config page first. "
                        "Cannot proceed without valid token."
                    )
                    raise FileNotFoundError(
                        f"Schwab token not found at {self.token_path}. "
                        "Please authenticate via dashboard /config page."
                    )
                else:
                    logger.info(
                        f"No token file found at {self.token_path}. "
                        "Browser will open for first-time authentication."
                    )
                    logger.info("Please log in to Schwab in the browser window that opens.")
            elif not token_valid:
                # Token exists but is expired (>7 days old)
                if is_docker:
                    logger.error(
                        f"Schwab token at {self.token_path} has expired. "
                        "In Docker, re-authenticate via dashboard /config page. "
                        "Tokens expire after 7 days and require manual re-authentication."
                    )
                    raise AuthError(
                        f"Schwab token has expired (>7 days old). "
                        "Please re-authenticate via dashboard /config page."
                    )
                else:
                    logger.warning(
                        f"Token at {self.token_path} has expired. "
                        "Browser will open for re-authentication."
                    )
            else:
                logger.info(
                    f"Using existing token from {self.token_path} "
                    f"(expires in {expires_in_days:.1f} days)"
                )

            # Create client using schwab-py's easy_client
            # This handles OAuth flow, token storage, and auto-refresh
            self._client = auth.easy_client(
                api_key=self.api_key,
                app_secret=self.api_secret,
                callback_url=self.callback_url,
                token_path=self.token_path,
                asyncio=False,  # Use synchronous client
            )

            logger.info("Successfully authenticated with Schwab API")
            # Note: schwab-py library handles timeouts internally
            # Default timeout is typically 30s for HTTP requests
            # Custom timeout configuration may require schwab-py library updates
            return self._client

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            logger.info(
                "\nAuthentication troubleshooting:\n"
                "1. Verify credentials in .env are correct\n"
                "2. Ensure app status is 'Ready for Use' at developer.schwab.com\n"
                "3. Check callback URL uses 127.0.0.1 (NOT localhost!): https://127.0.0.1:8182\n"
                "4. Try removing token.json and re-authenticating\n"
                "5. Ensure SCHWAB_CALLBACK_URL env var is set correctly"
            )
            raise

    def _make_request_with_retry(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        period_type_str: str,
        period_str: str,
        frequency_type_str: str,
        frequency_str: str,
        max_retries: int = 3,
    ) -> requests.Response:
        """
        Make API request with exponential backoff retry.

        Retry conditions:
        - Network errors (connection timeout, DNS)
        - 5xx server errors
        - 429 rate limit errors

        Don't retry:
        - 4xx client errors (invalid request)
        - 401 authentication errors (need re-auth)

        Args:
            symbol: Stock ticker
            start_date: Start date
            end_date: End date
            period_type_str: Period type ('YEAR', 'MONTH', 'DAY', etc.)
            period_str: Period ('TWENTY_YEARS', 'ONE_DAY', etc.)
            frequency_type_str: Frequency type ('DAILY', 'MINUTE', etc.)
            frequency_str: Frequency ('DAILY', 'EVERY_FIVE_MINUTES', 'EVERY_FIFTEEN_MINUTES', etc.)
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            API response object

        Raises:
            APIError: After max retries exceeded
            AuthError: Authentication failed (need re-auth)
        """
        client = self._get_client()

        # Map string parameters to Schwab client enums
        period_type = getattr(client.PriceHistory.PeriodType, period_type_str)
        period = getattr(client.PriceHistory.Period, period_str)
        frequency_type = getattr(client.PriceHistory.FrequencyType, frequency_type_str)
        frequency = getattr(client.PriceHistory.Frequency, frequency_str)

        for attempt in range(1, max_retries + 1):
            try:
                # Convert UTC-aware datetimes to naive for schwab-py compatibility
                # schwab-py uses dt.timestamp() which interprets naive datetimes as local time
                # This is required for proper API timestamp conversion
                start_naive = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
                end_naive = end_date.replace(tzinfo=None) if end_date.tzinfo else end_date

                # Make API call with period and frequency parameters
                # period_type and period are REQUIRED for proper API behavior
                # - For daily bars: period_type=YEAR, period=TWENTY_YEARS
                # - For intraday: period_type=DAY, period=ONE_DAY
                response = client.get_price_history(
                    symbol,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency,
                    start_datetime=start_naive,
                    end_datetime=end_naive,
                    need_extended_hours_data=False,
                )

                # Check for errors
                response.raise_for_status()
                return response

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code

                # Don't retry on client errors (4xx except 429)
                if 400 <= status_code < 500 and status_code != 429:
                    if status_code == 401:
                        raise AuthError(f"Authentication failed: {e}")
                    raise APIError(f"Client error: {e}")

                # Retry on 429 (rate limit) and 5xx (server errors)
                if attempt == max_retries:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise APIError(f"API request failed: {e}")

                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2 ** (attempt - 1)
                logger.warning(
                    f"Request failed (attempt {attempt}/{max_retries}), "
                    f"status {status_code}, retrying in {wait_time}s..."
                )
                time.sleep(wait_time)

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.RequestException,
            ) as e:

                if attempt == max_retries:
                    logger.error(f"Network error after {max_retries} attempts: {e}")
                    raise APIError(f"Network error: {e}")

                wait_time = 2 ** (attempt - 1)
                logger.warning(
                    f"Network error (attempt {attempt}/{max_retries}), "
                    f"retrying in {wait_time}s..."
                )
                time.sleep(wait_time)

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical OHLCV bars from Schwab API.

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            timeframe: Bar timeframe - supported: '1D' (daily), '5m' (5-minute), '15m' (15-minute)
            start_date: Start date for data fetch
            end_date: End date for data fetch

        Returns:
            List of bar dictionaries with keys:
                - timestamp: datetime
                - open: Decimal
                - high: Decimal
                - low: Decimal
                - close: Decimal
                - volume: int

        Raises:
            ValueError: If timeframe is not supported
            Exception: If API request fails

        Example:
            # Daily bars
            bars = fetcher.fetch_bars('AAPL', '1D',
                                     datetime(2024, 1, 1),
                                     datetime(2024, 12, 31))

            # 5-minute bars
            bars = fetcher.fetch_bars('AAPL', '5m',
                                     datetime(2024, 1, 1),
                                     datetime(2024, 1, 31))
        """
        # Validate parameters
        self.validate_parameters(symbol, timeframe, start_date, end_date)

        logger.info(
            f"Fetching {symbol} {timeframe} bars from {start_date.date()} to {end_date.date()}"
        )

        # Validate timeframe and map to Schwab API parameters
        # Each timeframe maps to: (period_type, period, frequency_type, frequency)
        # - Daily bars use YEAR/TWENTY_YEARS to get maximum history
        # - Intraday bars use DAY/ONE_DAY for recent data
        timeframe_mapping = {
            '1D': ('YEAR', 'TWENTY_YEARS', 'DAILY', 'DAILY'),
            '5m': ('DAY', 'ONE_DAY', 'MINUTE', 'EVERY_FIVE_MINUTES'),
            '15m': ('DAY', 'ONE_DAY', 'MINUTE', 'EVERY_FIFTEEN_MINUTES'),
        }

        if timeframe not in timeframe_mapping:
            supported = ', '.join(timeframe_mapping.keys())
            raise ValueError(
                f"Timeframe '{timeframe}' not supported. "
                f"Supported timeframes: {supported}"
            )

        # Get period and frequency parameters for this timeframe
        period_type_str, period_str, frequency_type_str, frequency_str = timeframe_mapping[timeframe]

        try:
            # Wait for rate limiter (enforce 2 requests/second)
            self._rate_limiter.wait_if_needed()

            # Fetch price history with retry logic
            logger.debug(f"Requesting {timeframe} data for {symbol} from Schwab API")
            response = self._make_request_with_retry(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period_type_str=period_type_str,
                period_str=period_str,
                frequency_type_str=frequency_type_str,
                frequency_str=frequency_str,
                max_retries=3
            )

            # Parse response
            data = response.json()

            # Parse candles from response
            if 'candles' not in data:
                logger.warning(f"No candle data in response for {symbol}")
                return []

            candles = data['candles']

            # Check if we received any data
            if len(candles) == 0:
                logger.warning(
                    f"Received 0 bars from Schwab API for {symbol} "
                    f"({start_date.date()} to {end_date.date()})"
                )
                logger.info(
                    f"Possible reasons for 0 bars:\n"
                    f"  1. Ticker may not have existed during requested date range\n"
                    f"     - Many ETFs (like QQQ, SPY, etc.) launched in late 1990s\n"
                    f"     - Check ticker inception date before requesting historical data\n"
                    f"  2. Date range may fall entirely on market holidays/weekends\n"
                    f"  3. Ticker symbol may be incorrect or delisted\n"
                    f"  Try: Request more recent dates to verify ticker validity"
                )
                return []

            logger.info(f"Received {len(candles)} bars from Schwab API")

            # Convert to standard format
            bars = []
            for candle in candles:
                try:
                    # Parse timestamp (milliseconds since epoch) with UTC timezone
                    # CRITICAL: Use tz=timezone.utc to avoid local timezone interpretation
                    # Bug: datetime.fromtimestamp() without tz interprets as local time (PST/PDT)
                    # which causes 8-hour offset and wrong dates in database
                    timestamp = datetime.fromtimestamp(candle['datetime'] / 1000, tz=timezone.utc)

                    # Convert prices to Decimal for precision
                    bar = {
                        'timestamp': timestamp,
                        'open': Decimal(str(candle['open'])),
                        'high': Decimal(str(candle['high'])),
                        'low': Decimal(str(candle['low'])),
                        'close': Decimal(str(candle['close'])),
                        'volume': int(candle['volume']),
                    }

                    # Validate OHLC relationships
                    if bar['high'] < bar['low']:
                        logger.warning(
                            f"Invalid bar at {timestamp}: high ({bar['high']}) < low ({bar['low']})"
                        )
                        continue

                    if not (bar['low'] <= bar['close'] <= bar['high']):
                        logger.warning(
                            f"Invalid bar at {timestamp}: close ({bar['close']}) "
                            f"outside high/low range"
                        )
                        continue

                    if not (bar['low'] <= bar['open'] <= bar['high']):
                        logger.warning(
                            f"Invalid bar at {timestamp}: open ({bar['open']}) "
                            f"outside high/low range"
                        )
                        continue

                    bars.append(bar)

                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse candle: {e}")
                    continue

            logger.info(f"Successfully parsed {len(bars)} valid bars")
            return bars

        except Exception as e:
            logger.error(f"Failed to fetch data from Schwab API: {e}")
            raise

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get real-time quote for a symbol.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Quote data dictionary with last_price, bid, ask, volume, timestamp

        Example:
            quote = fetcher.get_quote('AAPL')
            current_price = quote['last_price']
        """
        logger.info(f"Fetching quote for {symbol}")

        try:
            # Wait for rate limiter
            self._rate_limiter.wait_if_needed()

            client = self._get_client()
            response = client.get_quote(symbol)
            response.raise_for_status()
            data = response.json()

            if symbol.upper() not in data:
                raise ValueError(f"No quote data for {symbol}")

            quote_data = data[symbol.upper()]

            return {
                'symbol': symbol.upper(),
                'last_price': Decimal(str(quote_data['lastPrice'])),
                'bid': Decimal(str(quote_data['bidPrice'])),
                'ask': Decimal(str(quote_data['askPrice'])),
                'volume': int(quote_data['totalVolume']),
                'timestamp': datetime.fromtimestamp(quote_data['quoteTime'] / 1000),
            }

        except Exception as e:
            logger.error(f"Failed to fetch quote for {symbol}: {e}")
            raise

    def test_connection(self) -> bool:
        """
        Test API connection with a simple quote request.

        Returns:
            True if connection successful, False otherwise

        Example:
            if fetcher.test_connection():
                print("Schwab API connection successful")
        """
        try:
            # Wait for rate limiter
            self._rate_limiter.wait_if_needed()

            client = self._get_client()
            response = client.get_quote("SPY")
            response.raise_for_status()
            logger.info("Connection test successful!")
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
