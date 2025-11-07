"""
Unit tests for TradeLogger class.

Tests cover:
1. Strategy context logging
2. Trade execution logging
3. Context-trade matching logic
4. DataFrame generation with dynamic columns
5. Allocation formatting
6. Edge cases (empty logger, multi-symbol, unmatched contexts)
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pandas as pd

from jutsu_engine.performance.trade_logger import (
    TradeLogger,
    StrategyContext,
    TradeRecord
)
from jutsu_engine.core.events import FillEvent


@pytest.fixture
def trade_logger():
    """Create TradeLogger with $100,000 initial capital."""
    return TradeLogger(initial_capital=Decimal('100000'))


@pytest.fixture
def sample_timestamp():
    """Sample timestamp for tests."""
    return datetime(2025, 1, 15, 9, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_fill_event(sample_timestamp):
    """Sample FillEvent for tests."""
    return FillEvent(
        timestamp=sample_timestamp,
        symbol='TQQQ',
        direction='BUY',  # Fixed: direction not order_type
        quantity=100,      # Fixed: quantity not shares
        fill_price=Decimal('45.50'),
        commission=Decimal('1.00'),
        slippage=Decimal('0.50')
    )


class TestStrategyContextLogging:
    """Tests for log_strategy_context() method."""

    def test_log_basic_context(self, trade_logger, sample_timestamp):
        """Test logging basic strategy context."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Bullish_Strong',
            decision_reason='EMA fast > EMA slow AND ADX > 25',
            indicator_values={
                'EMA_fast': Decimal('450.25'),
                'EMA_slow': Decimal('445.10'),
                'ADX': Decimal('28.5')
            },
            threshold_values={
                'ADX_threshold_high': Decimal('25'),
                'ADX_threshold_low': Decimal('20')
            }
        )

        assert len(trade_logger._strategy_contexts) == 1
        context = trade_logger._strategy_contexts[0]

        assert context.symbol == 'TQQQ'
        assert context.strategy_state == 'Bullish_Strong'
        assert context.decision_reason == 'EMA fast > EMA slow AND ADX > 25'
        assert context.indicator_values['EMA_fast'] == Decimal('450.25')
        assert context.threshold_values['ADX_threshold_high'] == Decimal('25')

    def test_log_multiple_contexts(self, trade_logger, sample_timestamp):
        """Test logging multiple strategy contexts."""
        # Log context for TQQQ
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Bullish_Strong',
            decision_reason='Buy signal',
            indicator_values={'EMA': Decimal('450')},
            threshold_values={}
        )

        # Log context for SQQQ
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp + timedelta(seconds=5),
            symbol='SQQQ',
            strategy_state='Bearish_Weak',
            decision_reason='Close signal',
            indicator_values={'EMA': Decimal('25')},
            threshold_values={}
        )

        assert len(trade_logger._strategy_contexts) == 2
        assert trade_logger._strategy_contexts[0].symbol == 'TQQQ'
        assert trade_logger._strategy_contexts[1].symbol == 'SQQQ'

    def test_log_empty_indicators(self, trade_logger, sample_timestamp):
        """Test logging context with empty indicator values."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='QQQ',
            strategy_state='Neutral',
            decision_reason='No signal',
            indicator_values={},
            threshold_values={}
        )

        assert len(trade_logger._strategy_contexts) == 1
        context = trade_logger._strategy_contexts[0]
        assert context.indicator_values == {}
        assert context.threshold_values == {}


class TestTradeExecutionLogging:
    """Tests for log_trade_execution() method."""

    def test_log_execution_with_matched_context(
        self, trade_logger, sample_timestamp, sample_fill_event
    ):
        """Test logging trade execution with matched strategy context."""
        # First, log strategy context
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Bullish_Strong',
            decision_reason='EMA crossover',
            indicator_values={'EMA_fast': Decimal('450')},
            threshold_values={'ADX_threshold': Decimal('25')}
        )

        # Then, log trade execution
        trade_logger.log_trade_execution(
            fill=sample_fill_event,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={'CASH': Decimal('100')},
            allocation_after={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')}
        )

        # Context should be consumed
        assert len(trade_logger._strategy_contexts) == 0

        # Trade record should be created
        assert len(trade_logger._trade_records) == 1
        record = trade_logger._trade_records[0]

        assert record.trade_id == 1
        assert record.ticker == 'TQQQ'
        assert record.decision == 'BUY'
        assert record.strategy_state == 'Bullish_Strong'
        assert record.decision_reason == 'EMA crossover'
        assert record.shares == 100
        assert record.fill_price == Decimal('45.50')
        assert record.commission == Decimal('1.00')
        assert record.portfolio_value_after == Decimal('95449')

    def test_log_execution_without_context(
        self, trade_logger, sample_fill_event
    ):
        """Test logging trade execution without matched context (warning)."""
        # Log execution WITHOUT prior context
        trade_logger.log_trade_execution(
            fill=sample_fill_event,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={'CASH': Decimal('100')},
            allocation_after={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')}
        )

        # Trade record should still be created with defaults
        assert len(trade_logger._trade_records) == 1
        record = trade_logger._trade_records[0]

        assert record.strategy_state == 'UNKNOWN'
        assert record.decision_reason == 'No strategy context found'
        assert record.indicator_values == {}
        assert record.threshold_values == {}

    def test_log_multiple_trades(self, trade_logger, sample_timestamp):
        """Test logging multiple trade executions."""
        # Trade 1: Buy TQQQ
        fill1 = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill1,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={'CASH': Decimal('100')},
            allocation_after={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')}
        )

        # Trade 2: Sell TQQQ
        fill2 = FillEvent(
            timestamp=sample_timestamp + timedelta(hours=1),
            symbol='TQQQ',
            order_type='SELL',
            shares=100,
            fill_price=Decimal('46.00'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill2,
            portfolio_value_before=Decimal('95449'),
            portfolio_value_after=Decimal('100048'),
            cash_before=Decimal('95449'),
            cash_after=Decimal('100048'),
            allocation_before={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')},
            allocation_after={'CASH': Decimal('100')}
        )

        assert len(trade_logger._trade_records) == 2
        assert trade_logger._trade_records[0].trade_id == 1
        assert trade_logger._trade_records[1].trade_id == 2
        assert trade_logger._trade_records[0].decision == 'BUY'
        assert trade_logger._trade_records[1].decision == 'SELL'


class TestContextMatching:
    """Tests for _find_matching_context() logic."""

    def test_exact_match(self, trade_logger, sample_timestamp):
        """Test exact timestamp and symbol match."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason='Test reason',
            indicator_values={},
            threshold_values={}
        )

        fill = FillEvent(
            timestamp=sample_timestamp,  # Exact match
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        # Context should be matched and consumed
        assert len(trade_logger._strategy_contexts) == 0
        assert trade_logger._trade_records[0].strategy_state == 'Test'

    def test_within_tolerance(self, trade_logger, sample_timestamp):
        """Test timestamp match within 60-second tolerance."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason='Test reason',
            indicator_values={},
            threshold_values={}
        )

        # Fill is 30 seconds later (within tolerance)
        fill = FillEvent(
            timestamp=sample_timestamp + timedelta(seconds=30),
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        # Should match
        assert len(trade_logger._strategy_contexts) == 0
        assert trade_logger._trade_records[0].strategy_state == 'Test'

    def test_outside_tolerance(self, trade_logger, sample_timestamp):
        """Test timestamp outside 60-second tolerance (no match)."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason='Test reason',
            indicator_values={},
            threshold_values={}
        )

        # Fill is 2 minutes later (outside tolerance)
        fill = FillEvent(
            timestamp=sample_timestamp + timedelta(minutes=2),
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        # Should NOT match (context remains pending)
        assert len(trade_logger._strategy_contexts) == 1
        assert trade_logger._trade_records[0].strategy_state == 'UNKNOWN'

    def test_different_symbol(self, trade_logger, sample_timestamp):
        """Test different symbols don't match."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason='Test reason',
            indicator_values={},
            threshold_values={}
        )

        # Fill for different symbol
        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='SQQQ',  # Different symbol
            order_type='BUY',
            shares=100,
            fill_price=Decimal('15.25'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('98474'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('98474'),
            allocation_before={},
            allocation_after={}
        )

        # Should NOT match
        assert len(trade_logger._strategy_contexts) == 1
        assert trade_logger._trade_records[0].strategy_state == 'UNKNOWN'


class TestDataFrameGeneration:
    """Tests for to_dataframe() method."""

    def test_basic_dataframe(self, trade_logger, sample_timestamp):
        """Test basic DataFrame generation with one trade."""
        # Log context and trade
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Bullish_Strong',
            decision_reason='Buy signal',
            indicator_values={'EMA': Decimal('450')},
            threshold_values={'ADX_threshold': Decimal('25')}
        )

        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={'CASH': Decimal('100')},
            allocation_after={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')}
        )

        df = trade_logger.to_dataframe()

        assert len(df) == 1
        assert df.loc[0, 'Trade_ID'] == 1
        assert df.loc[0, 'Ticker'] == 'TQQQ'
        assert df.loc[0, 'Decision'] == 'BUY'
        assert df.loc[0, 'Strategy_State'] == 'Bullish_Strong'
        assert df.loc[0, 'Shares'] == 100
        assert df.loc[0, 'Fill_Price'] == Decimal('45.50')

    def test_dynamic_indicator_columns(self, trade_logger, sample_timestamp):
        """Test dynamic indicator columns for different strategies."""
        # Trade 1: Strategy with EMA, ADX
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test1',
            decision_reason='Reason1',
            indicator_values={
                'EMA_fast': Decimal('450'),
                'ADX': Decimal('28')
            },
            threshold_values={}
        )

        fill1 = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill1,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        # Trade 2: Strategy with RSI, MACD (different indicators)
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp + timedelta(hours=1),
            symbol='SQQQ',
            strategy_state='Test2',
            decision_reason='Reason2',
            indicator_values={
                'RSI': Decimal('35'),
                'MACD': Decimal('2.5')
            },
            threshold_values={}
        )

        fill2 = FillEvent(
            timestamp=sample_timestamp + timedelta(hours=1),
            symbol='SQQQ',
            order_type='BUY',
            shares=50,
            fill_price=Decimal('15.25'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill2,
            portfolio_value_before=Decimal('95449'),
            portfolio_value_after=Decimal('94686'),
            cash_before=Decimal('95449'),
            cash_after=Decimal('94686'),
            allocation_before={},
            allocation_after={}
        )

        df = trade_logger.to_dataframe()

        # Should have columns for ALL indicators (ADX, EMA_fast, MACD, RSI)
        assert 'Indicator_ADX' in df.columns
        assert 'Indicator_EMA_fast' in df.columns
        assert 'Indicator_MACD' in df.columns
        assert 'Indicator_RSI' in df.columns

        # Trade 1 should have EMA/ADX values, NaN for RSI/MACD
        assert df.loc[0, 'Indicator_EMA_fast'] == Decimal('450')
        assert df.loc[0, 'Indicator_ADX'] == Decimal('28')
        assert pd.isna(df.loc[0, 'Indicator_RSI'])
        assert pd.isna(df.loc[0, 'Indicator_MACD'])

        # Trade 2 should have RSI/MACD values, NaN for EMA/ADX
        assert df.loc[1, 'Indicator_RSI'] == Decimal('35')
        assert df.loc[1, 'Indicator_MACD'] == Decimal('2.5')
        assert pd.isna(df.loc[1, 'Indicator_EMA_fast'])
        assert pd.isna(df.loc[1, 'Indicator_ADX'])

    def test_allocation_formatting(self, trade_logger, sample_timestamp):
        """Test portfolio allocation percentage formatting."""
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason='Test',
            indicator_values={},
            threshold_values={}
        )

        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={'CASH': Decimal('100.0')},
            allocation_after={
                'TQQQ': Decimal('47.65'),
                'CASH': Decimal('52.35')
            }
        )

        df = trade_logger.to_dataframe()

        # Check allocation formatting
        assert df.loc[0, 'Allocation_Before'] == 'CASH: 100.0%'
        assert 'TQQQ: 47.65%' in df.loc[0, 'Allocation_After']
        assert 'CASH: 52.35%' in df.loc[0, 'Allocation_After']

    def test_empty_dataframe(self, trade_logger):
        """Test DataFrame generation with no trades."""
        df = trade_logger.to_dataframe()

        assert df.empty
        assert len(df) == 0

    def test_cumulative_return_calculation(self, trade_logger, sample_timestamp):
        """Test cumulative return percentage calculation."""
        # Trade 1: Initial buy
        fill1 = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill1,
            portfolio_value_before=Decimal('100000'),  # Initial
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        # Trade 2: Sell with profit
        fill2 = FillEvent(
            timestamp=sample_timestamp + timedelta(hours=1),
            symbol='TQQQ',
            order_type='SELL',
            shares=100,
            fill_price=Decimal('50.00'),  # Profit
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill2,
            portfolio_value_before=Decimal('95449'),
            portfolio_value_after=Decimal('104948'),  # 4.948% gain
            cash_before=Decimal('95449'),
            cash_after=Decimal('104948'),
            allocation_before={},
            allocation_after={}
        )

        df = trade_logger.to_dataframe()

        # Trade 1: No gain yet (still at initial capital)
        assert df.loc[0, 'Cumulative_Return_Pct'] == Decimal('0.00')

        # Trade 2: 4.948% gain
        expected_return = ((Decimal('104948') - Decimal('100000')) / Decimal('100000')) * Decimal('100')
        assert abs(df.loc[1, 'Cumulative_Return_Pct'] - expected_return) < Decimal('0.01')


class TestMultiSymbolHandling:
    """Tests for multi-symbol trading scenarios."""

    def test_separate_rows_per_symbol(self, trade_logger, sample_timestamp):
        """Test that each symbol traded gets a separate row."""
        # Context for TQQQ buy and SQQQ close
        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Bullish_Strong',
            decision_reason='Buy TQQQ',
            indicator_values={},
            threshold_values={}
        )

        trade_logger.log_strategy_context(
            timestamp=sample_timestamp + timedelta(seconds=5),
            symbol='SQQQ',
            strategy_state='Bullish_Strong',
            decision_reason='Close SQQQ',
            indicator_values={},
            threshold_values={}
        )

        # Execute TQQQ buy
        fill1 = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill1,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={'CASH': Decimal('100')},
            allocation_after={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')}
        )

        # Execute SQQQ close
        fill2 = FillEvent(
            timestamp=sample_timestamp + timedelta(seconds=5),
            symbol='SQQQ',
            order_type='SELL',
            shares=50,
            fill_price=Decimal('15.25'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill2,
            portfolio_value_before=Decimal('95449'),
            portfolio_value_after=Decimal('96211'),
            cash_before=Decimal('95449'),
            cash_after=Decimal('96211'),
            allocation_before={'TQQQ': Decimal('47.65'), 'CASH': Decimal('52.35')},
            allocation_after={'TQQQ': Decimal('47.29'), 'CASH': Decimal('52.71')}
        )

        df = trade_logger.to_dataframe()

        # Should have 2 separate rows
        assert len(df) == 2
        assert df.loc[0, 'Ticker'] == 'TQQQ'
        assert df.loc[1, 'Ticker'] == 'SQQQ'


class TestBarNumberIncrement:
    """Tests for bar number tracking."""

    def test_bar_number_increments(self, trade_logger, sample_timestamp):
        """Test that bar numbers increment correctly."""
        # Bar 1: Trade 1
        trade_logger.increment_bar()

        fill1 = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill1,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        # Bar 2-5: No trades
        for _ in range(4):
            trade_logger.increment_bar()

        # Bar 6: Trade 2
        trade_logger.increment_bar()

        fill2 = FillEvent(
            timestamp=sample_timestamp + timedelta(hours=5),
            symbol='TQQQ',
            order_type='SELL',
            shares=100,
            fill_price=Decimal('46.00'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill2,
            portfolio_value_before=Decimal('95449'),
            portfolio_value_after=Decimal('100048'),
            cash_before=Decimal('95449'),
            cash_after=Decimal('100048'),
            allocation_before={},
            allocation_after={}
        )

        df = trade_logger.to_dataframe()

        assert df.loc[0, 'Bar_Number'] == 1
        assert df.loc[1, 'Bar_Number'] == 6


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_zero_shares(self, trade_logger, sample_timestamp):
        """Test handling of zero-share fill (should not happen in practice)."""
        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=0,  # Edge case
            fill_price=Decimal('45.50'),
            commission=Decimal('0.00'),
            slippage=Decimal('0.00')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('100000'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('100000'),
            allocation_before={},
            allocation_after={}
        )

        df = trade_logger.to_dataframe()
        assert len(df) == 1
        assert df.loc[0, 'Shares'] == 0

    def test_empty_allocation(self, trade_logger, sample_timestamp):
        """Test handling of empty allocation dicts."""
        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},  # Empty
            allocation_after={}    # Empty
        )

        df = trade_logger.to_dataframe()
        assert df.loc[0, 'Allocation_Before'] == ''
        assert df.loc[0, 'Allocation_After'] == ''

    def test_very_long_decision_reason(self, trade_logger, sample_timestamp):
        """Test handling of very long decision reason text."""
        long_reason = 'A' * 500  # 500 character reason

        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason=long_reason,
            indicator_values={},
            threshold_values={}
        )

        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        df = trade_logger.to_dataframe()
        assert df.loc[0, 'Decision_Reason'] == long_reason

    def test_many_indicators(self, trade_logger, sample_timestamp):
        """Test handling of many indicator columns (performance check)."""
        # Create context with 20 indicators
        indicators = {f'Indicator_{i}': Decimal(str(i)) for i in range(20)}

        trade_logger.log_strategy_context(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            strategy_state='Test',
            decision_reason='Test',
            indicator_values=indicators,
            threshold_values={}
        )

        fill = FillEvent(
            timestamp=sample_timestamp,
            symbol='TQQQ',
            order_type='BUY',
            shares=100,
            fill_price=Decimal('45.50'),
            commission=Decimal('1.00'),
            slippage=Decimal('0.50')
        )

        trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=Decimal('100000'),
            portfolio_value_after=Decimal('95449'),
            cash_before=Decimal('100000'),
            cash_after=Decimal('95449'),
            allocation_before={},
            allocation_after={}
        )

        df = trade_logger.to_dataframe()

        # Should have 20 indicator columns
        indicator_cols = [col for col in df.columns if col.startswith('Indicator_')]
        assert len(indicator_cols) == 20
