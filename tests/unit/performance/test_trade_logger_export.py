"""
Unit tests for TradeLogger CSV export functionality.

Tests trade log export to output directory:
- Export to directory with timestamp
- Export to specific file path
- Filename format validation
- Empty trade records handling
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from jutsu_engine.performance.trade_logger import TradeLogger
from jutsu_engine.core.events import FillEvent


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def initial_capital():
    """Standard initial capital for tests."""
    return Decimal('100000.00')


@pytest.fixture
def trade_logger(initial_capital):
    """Create TradeLogger instance."""
    return TradeLogger(initial_capital=initial_capital)


@pytest.fixture
def sample_fill():
    """Create sample FillEvent."""
    return FillEvent(
        symbol='AAPL',
        direction='BUY',
        quantity=100,
        fill_price=Decimal('150.00'),
        timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
        commission=Decimal('1.00'),
        slippage=Decimal('0.00')
    )


class TestTradeLoggerExport:
    """Test suite for TradeLogger CSV export."""

    def test_export_empty_raises_error(self, trade_logger, temp_output_dir):
        """Test that exporting with no trades raises ValueError."""
        with pytest.raises(ValueError, match="Cannot export: No trade records available"):
            trade_logger.export_trades_csv(
                output_path=temp_output_dir,
                strategy_name="TestStrategy"
            )

    def test_export_to_directory(
        self,
        trade_logger,
        sample_fill,
        temp_output_dir
    ):
        """Test export to directory creates timestamped file."""
        # Add strategy context and trade
        trade_logger.increment_bar()
        trade_logger.log_strategy_context(
            timestamp=sample_fill.timestamp,
            symbol=sample_fill.symbol,
            strategy_state="Test State",
            decision_reason="Test Reason",
            indicator_values={'EMA': Decimal('150.0')},
            threshold_values={'threshold': Decimal('25.0')}
        )
        
        trade_logger.log_trade_execution(
            fill=sample_fill,
            portfolio_value_before=Decimal('100000.00'),
            portfolio_value_after=Decimal('85000.00'),
            cash_before=Decimal('100000.00'),
            cash_after=Decimal('85000.00'),
            allocation_before={'CASH': Decimal('100')},
            allocation_after={'AAPL': Decimal('15'), 'CASH': Decimal('85')}
        )
        
        csv_path = trade_logger.export_trades_csv(
            output_path=temp_output_dir,
            strategy_name="TestStrategy"
        )
        
        # Verify file created
        assert Path(csv_path).exists()
        assert csv_path.startswith(temp_output_dir)
        assert "TestStrategy" in csv_path
        assert "_trades.csv" in csv_path

    def test_export_to_file_path(
        self,
        trade_logger,
        sample_fill,
        temp_output_dir
    ):
        """Test export to specific file path."""
        # Add strategy context and trade
        trade_logger.increment_bar()
        trade_logger.log_strategy_context(
            timestamp=sample_fill.timestamp,
            symbol=sample_fill.symbol,
            strategy_state="Test State",
            decision_reason="Test Reason",
            indicator_values={},
            threshold_values={}
        )
        
        trade_logger.log_trade_execution(
            fill=sample_fill,
            portfolio_value_before=Decimal('100000.00'),
            portfolio_value_after=Decimal('85000.00'),
            cash_before=Decimal('100000.00'),
            cash_after=Decimal('85000.00'),
            allocation_before={},
            allocation_after={}
        )
        
        custom_path = str(Path(temp_output_dir) / "custom_trades.csv")
        csv_path = trade_logger.export_trades_csv(
            output_path=custom_path,
            strategy_name="TestStrategy"
        )
        
        # Should use exact path
        assert csv_path == custom_path
        assert Path(csv_path).exists()

    def test_export_creates_parent_directory(self, trade_logger, sample_fill, temp_output_dir):
        """Test that export creates parent directory if it doesn't exist."""
        # Add strategy context and trade
        trade_logger.increment_bar()
        trade_logger.log_strategy_context(
            timestamp=sample_fill.timestamp,
            symbol=sample_fill.symbol,
            strategy_state="Test State",
            decision_reason="Test Reason",
            indicator_values={},
            threshold_values={}
        )
        
        trade_logger.log_trade_execution(
            fill=sample_fill,
            portfolio_value_before=Decimal('100000.00'),
            portfolio_value_after=Decimal('85000.00'),
            cash_before=Decimal('100000.00'),
            cash_after=Decimal('85000.00'),
            allocation_before={},
            allocation_after={}
        )
        
        # Use nested path that doesn't exist
        nested_path = str(Path(temp_output_dir) / "nested" / "path" / "trades.csv")
        csv_path = trade_logger.export_trades_csv(
            output_path=nested_path,
            strategy_name="TestStrategy"
        )
        
        assert Path(csv_path).exists()
        assert Path(csv_path).parent.exists()

    def test_filename_format(self, trade_logger, sample_fill, temp_output_dir):
        """Test that filename follows format: {strategy}_{timestamp}_trades.csv"""
        # Add strategy context and trade
        trade_logger.increment_bar()
        trade_logger.log_strategy_context(
            timestamp=sample_fill.timestamp,
            symbol=sample_fill.symbol,
            strategy_state="Test State",
            decision_reason="Test Reason",
            indicator_values={},
            threshold_values={}
        )
        
        trade_logger.log_trade_execution(
            fill=sample_fill,
            portfolio_value_before=Decimal('100000.00'),
            portfolio_value_after=Decimal('85000.00'),
            cash_before=Decimal('100000.00'),
            cash_after=Decimal('85000.00'),
            allocation_before={},
            allocation_after={}
        )
        
        csv_path = trade_logger.export_trades_csv(
            output_path=temp_output_dir,
            strategy_name="MACD_Strategy"
        )
        
        filename = Path(csv_path).name
        
        # Should match: MACD_Strategy_YYYYMMDD_HHMMSS_trades.csv
        assert filename.startswith("MACD_Strategy_")
        assert filename.endswith("_trades.csv")
        assert len(filename.split('_')) >= 4  # strategy, date, time, trades.csv

    def test_export_with_multiple_trades(
        self,
        trade_logger,
        sample_fill,
        temp_output_dir
    ):
        """Test export with multiple trades."""
        # Add multiple trades
        for i in range(3):
            trade_logger.increment_bar()
            trade_logger.log_strategy_context(
                timestamp=sample_fill.timestamp,
                symbol=sample_fill.symbol,
                strategy_state=f"State {i}",
                decision_reason=f"Reason {i}",
                indicator_values={},
                threshold_values={}
            )
            
            trade_logger.log_trade_execution(
                fill=sample_fill,
                portfolio_value_before=Decimal('100000.00'),
                portfolio_value_after=Decimal('85000.00'),
                cash_before=Decimal('100000.00'),
                cash_after=Decimal('85000.00'),
                allocation_before={},
                allocation_after={}
            )
        
        csv_path = trade_logger.export_trades_csv(
            output_path=temp_output_dir,
            strategy_name="MultiTrade"
        )
        
        # Verify file has all trades
        import pandas as pd
        df = pd.read_csv(csv_path)
        assert len(df) == 3
