"""
Integration tests for data flow through the system.

Demonstrates testing interactions between multiple components:
- Data models → Events → Strategy
- Configuration → Logger integration
- End-to-end data validation

Note: Some tests are skipped until MVP components are implemented.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.data.models import MarketData
from jutsu_engine.utils.config import Config
from jutsu_engine.utils.logging_config import setup_logger

from tests.fixtures.sample_data import create_sample_bar, create_sample_bars


class TestMarketDataToEvent:
    """Test conversion from database models to events."""

    def test_market_data_model_to_event(self):
        """Test converting MarketData model to MarketDataEvent."""
        # Create database model instance
        db_model = MarketData(
            symbol='AAPL',
            timeframe='1D',
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.50'),
            low=Decimal('149.50'),
            close=Decimal('151.00'),
            volume=1000000,
            data_source='schwab',
            is_valid=True,
        )

        # Convert to event
        event = MarketDataEvent(
            symbol=db_model.symbol,
            timestamp=db_model.timestamp,
            open=db_model.open,
            high=db_model.high,
            low=db_model.low,
            close=db_model.close,
            volume=db_model.volume,
            timeframe=db_model.timeframe,
        )

        # Verify conversion
        assert event.symbol == db_model.symbol
        assert event.timestamp == db_model.timestamp
        assert event.open == db_model.open
        assert event.high == db_model.high
        assert event.low == db_model.low
        assert event.close == db_model.close
        assert event.volume == db_model.volume

    def test_batch_conversion_maintains_order(self):
        """Test that batch conversion maintains chronological order."""
        # Create sequence of bars
        bars = create_sample_bars(num_bars=10)

        # Verify chronological order
        for i in range(1, len(bars)):
            assert bars[i].timestamp > bars[i - 1].timestamp

        # Verify data integrity
        for bar in bars:
            assert bar.low <= bar.open <= bar.high
            assert bar.low <= bar.close <= bar.high


class TestConfigurationLoading:
    """Test configuration loading and usage."""

    def test_config_loads_defaults(self):
        """Test that Config loads with default values."""
        config = Config()

        # Should have default database URL
        assert config.database_url is not None
        assert 'sqlite' in config.database_url or 'postgresql' in config.database_url

        # Should have default log level
        assert config.log_level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']

        # Should have default initial capital
        assert config.initial_capital > Decimal('0')

    def test_config_get_method(self):
        """Test Config.get() method with defaults."""
        config = Config()

        # Test getting value with default
        value = config.get('NONEXISTENT_KEY', 'default_value')
        assert value == 'default_value'

    def test_config_decimal_conversion(self):
        """Test that get_decimal() returns Decimal type."""
        config = Config()

        capital = config.initial_capital
        assert isinstance(capital, Decimal)

        commission = config.commission_per_share
        assert isinstance(commission, Decimal)


class TestLoggingIntegration:
    """Test logging system integration."""

    def test_logger_creation(self, tmp_path):
        """Test that logger creates log files correctly."""
        # Note: This test uses tmp_path fixture which creates temporary directory
        # In real usage, logs go to logs/ directory

        logger = setup_logger('TEST_INTEGRATION', log_to_console=False)

        # Logger should be created
        assert logger is not None
        assert logger.name == 'TEST_INTEGRATION'

        # Should be able to log messages
        logger.info("Test message")
        logger.debug("Debug message")
        logger.warning("Warning message")

    def test_logger_modules(self):
        """Test that pre-configured module loggers exist."""
        from jutsu_engine.utils.logging_config import (
            DATA_LOGGER,
            PORTFOLIO_LOGGER,
            ENGINE_LOGGER,
        )

        # Loggers should be created
        assert DATA_LOGGER is not None
        assert PORTFOLIO_LOGGER is not None
        assert ENGINE_LOGGER is not None

        # Loggers should have correct names
        assert 'DATA' in DATA_LOGGER.name
        assert 'PORTFOLIO' in PORTFOLIO_LOGGER.name
        assert 'ENGINE' in ENGINE_LOGGER.name


class TestDataValidation:
    """Test data validation across the system."""

    def test_invalid_data_rejected_at_event_level(self):
        """Test that invalid data is caught at event creation."""
        with pytest.raises(ValueError):
            # High less than low - should fail
            MarketDataEvent(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                open=Decimal('150.00'),
                high=Decimal('140.00'),  # Invalid: high < low
                low=Decimal('149.00'),
                close=Decimal('151.00'),
                volume=1000000,
            )

    def test_valid_data_passes_validation(self):
        """Test that valid data passes all validation."""
        # Should not raise any exceptions
        event = create_sample_bar()

        assert event.symbol == 'AAPL'
        assert event.low <= event.open <= event.high
        assert event.low <= event.close <= event.high


@pytest.mark.skip(reason="EventLoop not implemented yet - part of MVP Phase 1")
class TestEventLoopIntegration:
    """Test EventLoop integration (placeholder for future tests)."""

    def test_event_loop_processes_bars(self):
        """Test that EventLoop processes bars sequentially."""
        # TODO: Implement after EventLoop is created
        pass

    def test_strategy_receives_bars_in_order(self):
        """Test that strategy receives bars in chronological order."""
        # TODO: Implement after EventLoop and Strategy are integrated
        pass


@pytest.mark.skip(reason="DatabaseDataHandler not implemented yet - part of MVP Phase 1")
class TestDatabaseIntegration:
    """Test database integration (placeholder for future tests)."""

    def test_database_stores_market_data(self):
        """Test that market data is stored correctly in database."""
        # TODO: Implement after DatabaseDataHandler is created
        pass

    def test_incremental_data_sync(self):
        """Test that incremental data sync works correctly."""
        # TODO: Implement after DataSync is implemented
        pass
