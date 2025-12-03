"""
Unit tests for Market Calendar.

Tests trading day validation using NYSE calendar.
"""

import pytest
from datetime import datetime, timezone

from jutsu_engine.live.market_calendar import is_trading_day, is_market_hours


class TestMarketCalendar:
    """Test suite for market calendar functions."""

    def test_is_trading_day_weekday(self):
        """Test that weekdays are trading days (when not holidays)."""
        # 2025-11-03 is a Monday (not a holiday)
        monday = datetime(2025, 11, 3, 12, 0, tzinfo=timezone.utc)
        assert is_trading_day(monday) is True

    def test_is_trading_day_saturday(self):
        """Test that Saturday is NOT a trading day."""
        # 2025-11-01 is a Saturday
        saturday = datetime(2025, 11, 1, 12, 0, tzinfo=timezone.utc)
        assert is_trading_day(saturday) is False

    def test_is_trading_day_sunday(self):
        """Test that Sunday is NOT a trading day."""
        # 2025-11-02 is a Sunday
        sunday = datetime(2025, 11, 2, 12, 0, tzinfo=timezone.utc)
        assert is_trading_day(sunday) is False

    def test_is_trading_day_today(self):
        """Test checking if today is a trading day."""
        # Should not crash (may be True or False depending on actual day)
        result = is_trading_day()
        assert isinstance(result, bool)

    def test_is_market_hours_during_market(self):
        """Test that market hours (9:30-16:00 EST) return True."""
        # 2025-11-03 14:00 EST (market open)
        market_time = datetime(2025, 11, 3, 19, 0, tzinfo=timezone.utc)  # 14:00 EST
        assert is_market_hours(market_time) is True

    def test_is_market_hours_before_open(self):
        """Test that before market open returns False."""
        # 2025-11-03 08:00 EST (before 9:30 open)
        before_open = datetime(2025, 11, 3, 13, 0, tzinfo=timezone.utc)
        assert is_market_hours(before_open) is False

    def test_is_market_hours_after_close(self):
        """Test that after market close returns False."""
        # 2025-11-03 17:00 EST (after 16:00 close)
        after_close = datetime(2025, 11, 3, 22, 0, tzinfo=timezone.utc)
        assert is_market_hours(after_close) is False
