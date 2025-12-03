"""
Unit tests for Live Data Fetcher.

Tests historical data fetching, synthetic bar creation, and validation.
Uses mocked Schwab API to avoid external dependencies.
"""

import pytest
from unittest.mock import Mock, MagicMock
from decimal import Decimal
from datetime import datetime, timezone
import pandas as pd

from jutsu_engine.live.data_fetcher import LiveDataFetcher


@pytest.fixture
def mock_schwab_client():
    """Create mocked Schwab client for testing."""
    client = Mock()
    return client


@pytest.fixture
def data_fetcher(mock_schwab_client):
    """Create LiveDataFetcher with mocked client."""
    return LiveDataFetcher(mock_schwab_client)


class TestDataFetcher:
    """Test suite for LiveDataFetcher class."""

    def test_fetch_historical_bars_success(self, data_fetcher, mock_schwab_client):
        """Test successful historical bar fetching."""
        # Mock API response
        mock_schwab_client.get_price_history.return_value = {
            'candles': [
                {
                    'datetime': 1699142400000,  # 2023-11-05 (epoch ms)
                    'open': 500.0,
                    'high': 505.0,
                    'low': 495.0,
                    'close': 502.0,
                    'volume': 1000000
                }
            ]
        }

        df = data_fetcher.fetch_historical_bars('QQQ', lookback=10)

        assert len(df) == 1
        assert list(df.columns) == ['date', 'open', 'high', 'low', 'close', 'volume']
        assert df.iloc[0]['close'] == 502.0

    def test_create_synthetic_daily_bar(self, data_fetcher):
        """Test synthetic daily bar creation."""
        hist_df = pd.DataFrame({
            'date': [pd.Timestamp('2025-11-20', tz='UTC')],
            'open': [500.0],
            'high': [505.0],
            'low': [498.0],
            'close': [502.0],
            'volume': [1000000]
        })

        current_quote = Decimal('503.50')

        result_df = data_fetcher.create_synthetic_daily_bar(hist_df, current_quote)

        assert len(result_df) == 2  # Historical + synthetic
        assert result_df.iloc[-1]['close'] == 503.50

    def test_validate_corporate_actions_no_action(self, data_fetcher):
        """Test validation passes when no corporate action."""
        df = pd.DataFrame({
            'date': pd.date_range('2025-11-01', periods=5, tz='UTC'),
            'close': [500.0, 505.0, 502.0, 507.0, 510.0]  # Normal movement
        })

        is_valid = data_fetcher.validate_corporate_actions(df)

        assert is_valid is True

    def test_validate_corporate_actions_detects_split(self, data_fetcher):
        """Test validation detects stock split (>20% drop)."""
        df = pd.DataFrame({
            'date': pd.date_range('2025-11-01', periods=5, tz='UTC'),
            'close': [500.0, 505.0, 250.0, 252.0, 255.0]  # 50% drop = split
        })

        is_valid = data_fetcher.validate_corporate_actions(df)

        assert is_valid is False  # Split detected
