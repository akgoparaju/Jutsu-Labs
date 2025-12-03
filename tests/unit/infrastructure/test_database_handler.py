"""
Unit tests for DatabaseDataHandler warmup functionality.

Tests warmup_bars parameter and helper method for both
DatabaseDataHandler and MultiSymbolDataHandler.
"""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.data.handlers.database import (
    DatabaseDataHandler,
    MultiSymbolDataHandler,
)
from jutsu_engine.data.models import Base, MarketData


class TestDatabaseDataHandlerWarmup(unittest.TestCase):
    """Test DatabaseDataHandler warmup functionality."""

    @classmethod
    def setUpClass(cls):
        """Create in-memory database and populate with test data."""
        # Create in-memory SQLite database
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        Session = sessionmaker(bind=cls.engine)
        cls.session = Session()

        # Create test data: 200 bars from 2023-01-01 to ~2023-10-01
        cls.symbol = "AAPL"
        cls.timeframe = "1D"
        start = datetime(2023, 1, 1)  # Timezone-naive to match database

        for i in range(200):
            bar_date = start + timedelta(days=i)
            bar = MarketData(
                symbol=cls.symbol,
                timeframe=cls.timeframe,
                timestamp=bar_date,
                open=Decimal("100.00") + Decimal(i),
                high=Decimal("101.00") + Decimal(i),
                low=Decimal("99.00") + Decimal(i),
                close=Decimal("100.50") + Decimal(i),
                volume=1000000 + i * 1000,
                data_source="test",
                is_valid=True,
            )
            cls.session.add(bar)

        cls.session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        cls.session.close()
        cls.engine.dispose()

    def test_get_bars_no_warmup(self):
        """Test get_bars with warmup_bars=0 (default behavior)."""
        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        bars = handler.get_bars(
            symbol=self.symbol,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
            warmup_bars=0,
        )

        # Should return exactly bars in June
        assert len(bars) > 0
        assert all(bar.symbol == self.symbol for bar in bars)
        assert bars[0].timestamp >= datetime(2023, 6, 1)
        assert bars[-1].timestamp <= datetime(2023, 6, 30)

    def test_get_bars_with_warmup(self):
        """Test get_bars with warmup_bars > 0."""
        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        # Request 50-bar warmup
        bars = handler.get_bars(
            symbol=self.symbol,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
            warmup_bars=50,
        )

        # Should return more bars than without warmup
        bars_no_warmup = handler.get_bars(
            symbol=self.symbol,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
            warmup_bars=0,
        )

        assert len(bars) > len(bars_no_warmup)
        # First bar should be before June 1
        assert bars[0].timestamp < datetime(2023, 6, 1)
        # Last bar should still be in June
        assert bars[-1].timestamp <= datetime(2023, 6, 30)

    def test_get_bars_warmup_147_bars(self):
        """Test get_bars with 147-bar warmup (RSI requirement)."""
        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        # Request 147-bar warmup (for RSI(14))
        bars = handler.get_bars(
            symbol=self.symbol,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
            warmup_bars=147,
        )

        # Should have warmup bars before June 1
        june_start = datetime(2023, 6, 1)
        warmup_bars = [bar for bar in bars if bar.timestamp < june_start]
        trading_bars = [bar for bar in bars if bar.timestamp >= june_start]

        assert len(warmup_bars) > 0, "Should have warmup bars before trading period"
        assert len(trading_bars) > 0, "Should have trading period bars"
        # First bar should be from the start of our test data (2023-01-01)
        # Note: Our test data starts 2023-01-01, warmup would ideally go back to 2022-11-08
        # but since we don't have data that far back, it starts from earliest available
        assert bars[0].timestamp == datetime(2023, 1, 1)

    def test_calculate_warmup_start_date(self):
        """Test _calculate_warmup_start_date helper method."""
        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        # Test with 147 bars (RSI requirement)
        start = datetime(2024, 1, 1)
        warmup_start = handler._calculate_warmup_start_date(start, 147)

        # Should be approximately 206 days before (147 * 1.4)
        expected_delta = timedelta(days=147 * 1.4)
        actual_delta = start - warmup_start

        # Allow some rounding tolerance
        assert abs((actual_delta - expected_delta).days) <= 1

    def test_calculate_warmup_start_date_zero_bars(self):
        """Test _calculate_warmup_start_date with 0 bars."""
        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        start = datetime(2024, 1, 1)
        warmup_start = handler._calculate_warmup_start_date(start, 0)

        # Should return same date
        assert warmup_start == start

    def test_warmup_bars_included_in_results(self):
        """Test that warmup bars are included in returned data."""
        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        bars = handler.get_bars(
            symbol=self.symbol,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
            warmup_bars=50,
        )

        # All bars should be MarketDataEvent objects
        assert all(isinstance(bar, MarketDataEvent) for bar in bars)
        # Bars should be in chronological order
        for i in range(len(bars) - 1):
            assert bars[i].timestamp <= bars[i + 1].timestamp

    def test_timezone_aware_dates_converted_to_naive(self):
        """Test that timezone-aware dates are converted to naive for database comparison."""
        # Create timezone-aware end_date (like CLI does)
        end_date_aware = datetime(2023, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

        handler = DatabaseDataHandler(
            session=self.session,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=end_date_aware,
        )

        # Handler should convert to naive
        assert handler.end_date.tzinfo is None
        assert handler.end_date == datetime(2023, 6, 30, 23, 59, 59)

        # Should retrieve bars correctly
        bars = list(handler.get_next_bar())
        assert len(bars) > 0


class TestMultiSymbolDataHandlerWarmup(unittest.TestCase):
    """Test MultiSymbolDataHandler warmup functionality."""

    @classmethod
    def setUpClass(cls):
        """Create in-memory database and populate with test data."""
        # Create in-memory SQLite database
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        Session = sessionmaker(bind=cls.engine)
        cls.session = Session()

        # Create test data for multiple symbols: 200 bars each
        cls.symbols = ["QQQ", "TQQQ", "SQQQ"]
        cls.timeframe = "1D"
        start = datetime(2023, 1, 1)

        for symbol in cls.symbols:
            for i in range(200):
                bar_date = start + timedelta(days=i)
                bar = MarketData(
                    symbol=symbol,
                    timeframe=cls.timeframe,
                    timestamp=bar_date,
                    open=Decimal("100.00") + Decimal(i),
                    high=Decimal("101.00") + Decimal(i),
                    low=Decimal("99.00") + Decimal(i),
                    close=Decimal("100.50") + Decimal(i),
                    volume=1000000 + i * 1000,
                    data_source="test",
                    is_valid=True,
                )
                cls.session.add(bar)

        cls.session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        cls.session.close()
        cls.engine.dispose()

    def test_get_bars_no_warmup_multi_symbol(self):
        """Test get_bars with warmup_bars=0 for multi-symbol handler."""
        handler = MultiSymbolDataHandler(
            session=self.session,
            symbols=self.symbols,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        for symbol in self.symbols:
            bars = handler.get_bars(
                symbol=symbol,
                start_date=datetime(2023, 6, 1),
                end_date=datetime(2023, 6, 30),
                warmup_bars=0,
            )

            assert len(bars) > 0
            assert all(bar.symbol == symbol for bar in bars)
            assert bars[0].timestamp >= datetime(2023, 6, 1)
            assert bars[-1].timestamp <= datetime(2023, 6, 30)

    def test_get_bars_with_warmup_multi_symbol(self):
        """Test get_bars with warmup_bars > 0 for multi-symbol handler."""
        handler = MultiSymbolDataHandler(
            session=self.session,
            symbols=self.symbols,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        for symbol in self.symbols:
            bars_with_warmup = handler.get_bars(
                symbol=symbol,
                start_date=datetime(2023, 6, 1),
                end_date=datetime(2023, 6, 30),
                warmup_bars=50,
            )

            bars_no_warmup = handler.get_bars(
                symbol=symbol,
                start_date=datetime(2023, 6, 1),
                end_date=datetime(2023, 6, 30),
                warmup_bars=0,
            )

            # Should return more bars with warmup
            assert len(bars_with_warmup) > len(bars_no_warmup)
            # First bar should be before June 1
            assert bars_with_warmup[0].timestamp < datetime(
                2023, 6, 1
            )

    def test_timezone_aware_dates_converted_to_naive_multi_symbol(self):
        """Test that timezone-aware dates are converted to naive for multi-symbol handler."""
        # Create timezone-aware end_date (like CLI does)
        end_date_aware = datetime(2023, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

        handler = MultiSymbolDataHandler(
            session=self.session,
            symbols=self.symbols,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=end_date_aware,
        )

        # Handler should convert to naive
        assert handler.end_date.tzinfo is None
        assert handler.end_date == datetime(2023, 6, 30, 23, 59, 59)

        # Should retrieve bars correctly for all symbols
        bars = list(handler.get_next_bar())
        assert len(bars) > 0

    def test_calculate_warmup_start_date_multi_symbol(self):
        """Test _calculate_warmup_start_date for multi-symbol handler."""
        handler = MultiSymbolDataHandler(
            session=self.session,
            symbols=self.symbols,
            timeframe=self.timeframe,
            start_date=datetime(2023, 6, 1),
            end_date=datetime(2023, 6, 30),
        )

        # Test with 147 bars
        start = datetime(2024, 1, 1)
        warmup_start = handler._calculate_warmup_start_date(start, 147)

        # Should be approximately 206 days before (147 * 1.4)
        expected_delta = timedelta(days=147 * 1.4)
        actual_delta = start - warmup_start

        # Allow some rounding tolerance
        assert abs((actual_delta - expected_delta).days) <= 1


if __name__ == "__main__":
    unittest.main()
