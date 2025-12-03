"""
Unit tests for SchwabDataFetcher.

Tests OAuth authentication, rate limiting, retry logic, and data fetching.
All external dependencies (API calls) are mocked.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timezone
from decimal import Decimal
import time

import pytest
import requests

from jutsu_engine.data.fetchers.schwab import (
    SchwabDataFetcher,
    RateLimiter,
    APIError,
    AuthError
)


class TestRateLimiter(unittest.TestCase):
    """Test RateLimiter class."""

    def test_initialization(self):
        """Test rate limiter initialization."""
        limiter = RateLimiter(max_requests=2, time_window=1.0)
        assert limiter.max_requests == 2
        assert limiter.time_window == 1.0
        assert limiter.requests == []

    def test_first_requests_immediate(self):
        """Test first requests don't wait."""
        limiter = RateLimiter(max_requests=2, time_window=1.0)

        # First two requests should be immediate
        start = time.time()
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        elapsed = time.time() - start

        assert elapsed < 0.1  # Should be immediate
        assert len(limiter.requests) == 2

    def test_rate_limit_enforcement(self):
        """Test rate limiter enforces 2 req/sec."""
        limiter = RateLimiter(max_requests=2, time_window=1.0)

        # First two requests immediate
        limiter.wait_if_needed()
        limiter.wait_if_needed()

        # Third request should wait
        start = time.time()
        limiter.wait_if_needed()
        elapsed = time.time() - start

        # Should wait approximately 1 second
        assert 0.9 < elapsed < 1.2
        assert len(limiter.requests) == 3

    def test_old_requests_removed(self):
        """Test that old requests are removed from tracking."""
        limiter = RateLimiter(max_requests=2, time_window=1.0)

        # Add two requests
        limiter.wait_if_needed()
        limiter.wait_if_needed()

        # Wait for time window to pass
        time.sleep(1.1)

        # Old requests should be removed, next request immediate
        start = time.time()
        limiter.wait_if_needed()
        elapsed = time.time() - start

        assert elapsed < 0.1  # Should be immediate
        # Should only have 1 request in tracking (old ones removed)
        assert len(limiter.requests) == 1


class TestSchwabDataFetcherInit(unittest.TestCase):
    """Test SchwabDataFetcher initialization."""

    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_initialization_with_params(self, mock_get_config):
        """Test fetcher initialization with explicit parameters."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "env_key"
        mock_config.schwab_api_secret = "env_secret"
        mock_get_config.return_value = mock_config

        fetcher = SchwabDataFetcher(
            api_key="test_api_key",
            api_secret="test_api_secret",
            callback_url="https://localhost:8080/callback",
            token_path="test_token.json"
        )

        assert fetcher.api_key == "test_api_key"
        assert fetcher.api_secret == "test_api_secret"
        assert fetcher.callback_url == "https://localhost:8080/callback"
        assert fetcher.token_path == "test_token.json"
        assert fetcher._rate_limiter is not None
        assert fetcher._client is None  # Lazy initialization

    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_initialization_from_config(self, mock_get_config):
        """Test fetcher initialization from config."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "config_key"
        mock_config.schwab_api_secret = "config_secret"
        mock_get_config.return_value = mock_config

        fetcher = SchwabDataFetcher()

        assert fetcher.api_key == "config_key"
        assert fetcher.api_secret == "config_secret"

    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_missing_credentials_raises_error(self, mock_get_config):
        """Test initialization with missing credentials raises ValueError."""
        # Mock config with no credentials
        mock_config = Mock()
        mock_config.schwab_api_key = None
        mock_config.schwab_api_secret = None
        mock_get_config.return_value = mock_config

        with pytest.raises(ValueError, match="SCHWAB_API_KEY and SCHWAB_API_SECRET"):
            SchwabDataFetcher()

    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_placeholder_credentials_raises_error(self, mock_get_config):
        """Test initialization with placeholder credentials raises ValueError."""
        # Mock config with placeholder credentials
        mock_config = Mock()
        mock_config.schwab_api_key = "your_api_key_here"
        mock_config.schwab_api_secret = "your_api_secret_here"
        mock_get_config.return_value = mock_config

        with pytest.raises(ValueError, match="placeholder credentials"):
            SchwabDataFetcher()


class TestFetchBars(unittest.TestCase):
    """Test fetch_bars method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_response = Mock()
        self.mock_response.json.return_value = {
            'candles': [
                {
                    'datetime': 1704067200000,  # 2024-01-01 00:00:00 UTC
                    'open': 150.0,
                    'high': 155.0,
                    'low': 149.0,
                    'close': 153.0,
                    'volume': 1000000
                },
                {
                    'datetime': 1704153600000,  # 2024-01-02 00:00:00 UTC
                    'open': 153.0,
                    'high': 157.0,
                    'low': 152.0,
                    'close': 156.0,
                    'volume': 1200000
                }
            ]
        }
        self.mock_response.raise_for_status = Mock()

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_success(self, mock_get_config, mock_easy_client):
        """Test successful data fetch."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock client with frequency enums
        mock_client = Mock()
        mock_client.get_price_history.return_value = self.mock_response
        # Mock PriceHistory.FrequencyType and Frequency enums (use actual Schwab API names)
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Verify
        assert len(bars) == 2
        assert bars[0]['close'] == Decimal('153.0')
        assert bars[0]['volume'] == 1000000
        assert bars[1]['close'] == Decimal('156.0')

        # Verify API was called with correct parameters
        mock_client.get_price_history.assert_called_once()

    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_invalid_timeframe(self, mock_get_config):
        """Test fetch_bars with invalid timeframe raises ValueError."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        fetcher = SchwabDataFetcher()

        with pytest.raises(ValueError, match="not supported"):
            fetcher.fetch_bars(
                symbol='AAPL',
                timeframe='1H',  # Use unsupported timeframe
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
            )

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_validates_high_low(self, mock_get_config, mock_easy_client):
        """Test fetch_bars validates high >= low."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock response with invalid bar (high < low)
        mock_response = Mock()
        mock_response.json.return_value = {
            'candles': [
                {
                    'datetime': 1704067200000,
                    'open': 150.0,
                    'high': 145.0,  # Invalid: high < low
                    'low': 149.0,
                    'close': 148.0,
                    'volume': 1000000
                }
            ]
        }
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Should skip invalid bar
        assert len(bars) == 0

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_validates_close_in_range(self, mock_get_config, mock_easy_client):
        """Test fetch_bars validates close within high/low range."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock response with invalid bar (close outside range)
        mock_response = Mock()
        mock_response.json.return_value = {
            'candles': [
                {
                    'datetime': 1704067200000,
                    'open': 150.0,
                    'high': 155.0,
                    'low': 149.0,
                    'close': 160.0,  # Invalid: close > high
                    'volume': 1000000
                }
            ]
        }
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Should skip invalid bar
        assert len(bars) == 0

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_validates_open_in_range(self, mock_get_config, mock_easy_client):
        """Test fetch_bars validates open within high/low range."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock response with invalid bar (open outside range)
        mock_response = Mock()
        mock_response.json.return_value = {
            'candles': [
                {
                    'datetime': 1704067200000,
                    'open': 140.0,  # Invalid: open < low
                    'high': 155.0,
                    'low': 149.0,
                    'close': 153.0,
                    'volume': 1000000
                }
            ]
        }
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Should skip invalid bar
        assert len(bars) == 0

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_empty_response(self, mock_get_config, mock_easy_client):
        """Test fetch_bars handles empty response."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock empty response
        mock_response = Mock()
        mock_response.json.return_value = {'candles': []}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Should return empty list
        assert len(bars) == 0

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_fetch_bars_no_candles_key(self, mock_get_config, mock_easy_client):
        """Test fetch_bars handles response without 'candles' key."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock response without candles key
        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Should return empty list
        assert len(bars) == 0


class TestRetryLogic(unittest.TestCase):
    """Test retry logic with exponential backoff."""

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    @patch('time.sleep')
    def test_retry_on_503(self, mock_sleep, mock_get_config, mock_easy_client):
        """Test retry on 503 server error."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Create mock responses
        mock_response_error = Mock()
        error_response = Mock()
        error_response.status_code = 503
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response_error.raise_for_status.side_effect = http_error

        mock_response_success = Mock()
        mock_response_success.raise_for_status = Mock()
        mock_response_success.json.return_value = {'candles': []}

        # First two attempts fail, third succeeds
        mock_client = Mock()
        mock_client.get_price_history.side_effect = [
            mock_response_error,
            mock_response_error,
            mock_response_success
        ]
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Verify retry attempts
        assert mock_client.get_price_history.call_count == 3

        # Verify exponential backoff: 1s, 2s
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == 1  # First retry: 1s
        assert mock_sleep.call_args_list[1][0][0] == 2  # Second retry: 2s

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    @patch('time.sleep')
    def test_retry_exhausted_raises_error(self, mock_sleep, mock_get_config, mock_easy_client):
        """Test retry logic raises APIError after max retries."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # All attempts fail
        mock_response = Mock()
        error_response = Mock()
        error_response.status_code = 503
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response.raise_for_status.side_effect = http_error

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute and verify
        with pytest.raises(APIError, match="API request failed"):
            fetcher.fetch_bars(
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
            )

        # Verify max retries attempted
        assert mock_client.get_price_history.call_count == 3

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_no_retry_on_401(self, mock_get_config, mock_easy_client):
        """Test 401 authentication error raises AuthError without retry."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # 401 error
        mock_response = Mock()
        error_response = Mock()
        error_response.status_code = 401
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response.raise_for_status.side_effect = http_error

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute and verify
        with pytest.raises(AuthError, match="Authentication failed"):
            fetcher.fetch_bars(
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
            )

        # Verify no retries on 401
        assert mock_client.get_price_history.call_count == 1

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_no_retry_on_400(self, mock_get_config, mock_easy_client):
        """Test 400 client error raises APIError without retry."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # 400 error
        mock_response = Mock()
        error_response = Mock()
        error_response.status_code = 400
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response.raise_for_status.side_effect = http_error

        mock_client = Mock()
        mock_client.get_price_history.return_value = mock_response
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute and verify
        with pytest.raises(APIError, match="Client error"):
            fetcher.fetch_bars(
                symbol='AAPL',
                timeframe='1D',
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
            )

        # Verify no retries on 400
        assert mock_client.get_price_history.call_count == 1

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    @patch('time.sleep')
    def test_retry_on_connection_error(self, mock_sleep, mock_get_config, mock_easy_client):
        """Test retry on network connection error."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # First attempt fails with connection error, second succeeds
        mock_response_success = Mock()
        mock_response_success.raise_for_status = Mock()
        mock_response_success.json.return_value = {'candles': []}

        mock_client = Mock()
        mock_client.get_price_history.side_effect = [
            requests.exceptions.ConnectionError("Network error"),
            mock_response_success
        ]
        mock_client.PriceHistory.FrequencyType.DAILY = 'DAILY'
        mock_client.PriceHistory.FrequencyType.MINUTE = 'MINUTE'
        mock_client.PriceHistory.Frequency.DAILY = 'DAILY'
        mock_client.PriceHistory.Frequency.EVERY_FIVE_MINUTES = 'EVERY_FIVE_MINUTES'
        mock_client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES = 'EVERY_FIFTEEN_MINUTES'
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        bars = fetcher.fetch_bars(
            symbol='AAPL',
            timeframe='1D',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )

        # Verify retry happened
        assert mock_client.get_price_history.call_count == 2
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args_list[0][0][0] == 1  # First retry: 1s


class TestGetQuote(unittest.TestCase):
    """Test get_quote method."""

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_get_quote_success(self, mock_get_config, mock_easy_client):
        """Test successful quote fetch."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            'AAPL': {
                'lastPrice': 150.25,
                'bidPrice': 150.20,
                'askPrice': 150.30,
                'totalVolume': 50000000,
                'quoteTime': 1704067200000
            }
        }
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_quote.return_value = mock_response
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        quote = fetcher.get_quote('AAPL')

        # Verify
        assert quote['symbol'] == 'AAPL'
        assert quote['last_price'] == Decimal('150.25')
        assert quote['bid'] == Decimal('150.20')
        assert quote['ask'] == Decimal('150.30')
        assert quote['volume'] == 50000000


class TestConnection(unittest.TestCase):
    """Test connection testing method."""

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_connection_success(self, mock_get_config, mock_easy_client):
        """Test successful connection test."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get_quote.return_value = mock_response
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        result = fetcher.test_connection()

        # Verify
        assert result is True
        mock_client.get_quote.assert_called_once_with("SPY")

    @patch('jutsu_engine.data.fetchers.schwab.auth.easy_client')
    @patch('jutsu_engine.data.fetchers.schwab.get_config')
    def test_connection_failure(self, mock_get_config, mock_easy_client):
        """Test failed connection test."""
        # Mock config
        mock_config = Mock()
        mock_config.schwab_api_key = "test_key"
        mock_config.schwab_api_secret = "test_secret"
        mock_get_config.return_value = mock_config

        # Mock failure
        mock_client = Mock()
        mock_client.get_quote.side_effect = Exception("Connection failed")
        mock_easy_client.return_value = mock_client

        fetcher = SchwabDataFetcher()

        # Execute
        result = fetcher.test_connection()

        # Verify
        assert result is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
