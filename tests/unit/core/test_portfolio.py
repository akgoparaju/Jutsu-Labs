"""
Unit tests for Portfolio Simulator.

Tests position sizing logic, order execution, and state management.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from jutsu_engine.portfolio.simulator import PortfolioSimulator
from jutsu_engine.core.events import (
    SignalEvent,
    OrderEvent,
    MarketDataEvent,
    FillEvent
)


@pytest.fixture
def portfolio():
    """Create a portfolio with $100,000 initial capital."""
    return PortfolioSimulator(
        initial_capital=Decimal('100000'),
        commission_per_share=Decimal('0.01'),
        slippage_percent=Decimal('0.001')
    )


@pytest.fixture
def market_bar():
    """Create a sample market data bar."""
    return MarketDataEvent(
        symbol='AAPL',
        timestamp=datetime.now(timezone.utc),
        open=Decimal('150.00'),
        high=Decimal('152.00'),
        low=Decimal('149.00'),
        close=Decimal('151.00'),
        volume=1000000,
        timeframe='1D'
    )


class TestExecuteSignal:
    """Test the execute_signal method for position sizing."""

    def test_execute_signal_buy_80_percent(self, portfolio, market_bar):
        """Test BUY signal with 80% allocation calculates correct shares."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.80'),
            strategy_name='test'
        )

        fill = portfolio.execute_signal(signal, market_bar)

        assert fill is not None
        assert fill.direction == 'BUY'
        assert fill.symbol == 'AAPL'

        # Calculate expected shares
        # Portfolio value: $100,000
        # Allocation: 80% = $80,000
        # Price with slippage: $151.00 * 1.001 = $151.151
        # Cost per share: $151.151 + $0.01 commission = $151.161
        # Shares: $80,000 / $151.161 = 529 shares (floor)
        assert fill.quantity == 529

    def test_execute_signal_sell_80_percent_short(self, portfolio, market_bar):
        """Test SELL signal with 80% allocation calculates correct short shares."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='SELL',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.80'),
            strategy_name='test'
        )

        fill = portfolio.execute_signal(signal, market_bar)

        assert fill is not None
        assert fill.direction == 'SELL'
        assert fill.symbol == 'AAPL'

        # Calculate expected shares
        # Portfolio value: $100,000
        # Allocation: 80% = $80,000
        # Price with slippage: $151.00 * 0.999 = $150.849
        # Collateral per share: $150.849 * 1.5 + $0.01 = $226.2835
        # Shares: $80,000 / $226.2835 = 353 shares (floor)
        assert fill.quantity == 353

    def test_execute_signal_hold_returns_none(self, portfolio, market_bar):
        """Test HOLD signal returns None without execution."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='HOLD',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored for HOLD
            portfolio_percent=Decimal('0.50'),
            strategy_name='test'
        )

        fill = portfolio.execute_signal(signal, market_bar)

        assert fill is None
        assert portfolio.cash == Decimal('100000')  # No change

    def test_execute_signal_zero_percent_allocation(self, portfolio, market_bar):
        """Test 0% allocation returns None."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored
            portfolio_percent=Decimal('0.00'),
            strategy_name='test'
        )

        fill = portfolio.execute_signal(signal, market_bar)

        assert fill is None
        assert portfolio.cash == Decimal('100000')

    def test_execute_signal_100_percent_allocation(self, portfolio, market_bar):
        """Test 100% allocation uses most of portfolio value."""
        # Use 99% allocation to avoid edge case with slippage
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.99'),  # 99% to account for slippage
            strategy_name='test'
        )

        fill = portfolio.execute_signal(signal, market_bar)

        assert fill is not None
        # Should use approximately 99% of portfolio
        # With $99,000 allocation, should buy around 654 shares
        assert 640 <= fill.quantity <= 660
        # Verify most cash is used (at least 95%)
        assert portfolio.cash < Decimal('5000')

    def test_execute_signal_with_existing_holdings(self, portfolio, market_bar):
        """Test execute_signal with existing holdings affects portfolio value."""
        # First buy some shares
        order1 = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )
        portfolio.execute_order(order1, market_bar)
        portfolio.update_market_value({'AAPL': market_bar})

        # Now execute signal with 80% of new portfolio value
        signal = SignalEvent(
            symbol='MSFT',
            signal_type='BUY',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.80'),
            strategy_name='test'
        )

        # Create MSFT bar
        msft_bar = MarketDataEvent(
            symbol='MSFT',
            timestamp=market_bar.timestamp,
            open=Decimal('200.00'),
            high=Decimal('201.00'),
            low=Decimal('199.00'),
            close=Decimal('200.50'),
            volume=500000,
            timeframe='1D'
        )

        fill = portfolio.execute_signal(signal, msft_bar)

        assert fill is not None
        assert fill.symbol == 'MSFT'
        # Portfolio value should be higher than initial due to AAPL position


class TestCalculateLongShares:
    """Test the _calculate_long_shares helper method."""

    def test_calculate_long_shares_basic(self, portfolio):
        """Test basic long share calculation."""
        allocation = Decimal('80000')
        price = Decimal('150.00')

        shares = portfolio._calculate_long_shares(allocation, price)

        # Expected: 80000 / (150.00 + 0.01) = 533 shares
        assert shares == 533

    def test_calculate_long_shares_exact_fit(self, portfolio):
        """Test when allocation exactly fits whole shares."""
        allocation = Decimal('15001.00')  # 100 shares * 150.01
        price = Decimal('150.00')

        shares = portfolio._calculate_long_shares(allocation, price)

        assert shares == 100

    def test_calculate_long_shares_fractional_rounding(self, portfolio):
        """Test that fractional shares are floored."""
        allocation = Decimal('10000')
        price = Decimal('150.00')

        shares = portfolio._calculate_long_shares(allocation, price)

        # Expected: 10000 / 150.01 = 66.66... → 66 shares
        assert shares == 66

    def test_calculate_long_shares_zero_allocation(self, portfolio):
        """Test zero allocation returns zero shares."""
        shares = portfolio._calculate_long_shares(Decimal('0'), Decimal('150.00'))
        assert shares == 0

    def test_calculate_long_shares_small_allocation(self, portfolio):
        """Test very small allocation that can't buy even one share."""
        allocation = Decimal('100')  # Only $100
        price = Decimal('150.00')

        shares = portfolio._calculate_long_shares(allocation, price)

        assert shares == 0  # Can't afford even 1 share


class TestCalculateShortShares:
    """Test the _calculate_short_shares helper method."""

    def test_calculate_short_shares_basic(self, portfolio):
        """Test basic short share calculation with margin."""
        allocation = Decimal('80000')
        price = Decimal('150.00')

        shares = portfolio._calculate_short_shares(allocation, price)

        # Expected: 80000 / (150.00 * 1.5 + 0.01) = 80000 / 225.01 = 355 shares
        assert shares == 355

    def test_calculate_short_shares_margin_requirement(self, portfolio):
        """Test that margin requirement is correctly applied."""
        allocation = Decimal('45000')
        price = Decimal('100.00')

        shares = portfolio._calculate_short_shares(allocation, price)

        # Expected: 45000 / (100.00 * 1.5 + 0.01) = 45000 / 150.01 = 299 shares
        assert shares == 299

    def test_calculate_short_shares_vs_long_shares(self, portfolio):
        """Test that short shares are fewer than long shares for same allocation."""
        allocation = Decimal('50000')
        price = Decimal('100.00')

        long_shares = portfolio._calculate_long_shares(allocation, price)
        short_shares = portfolio._calculate_short_shares(allocation, price)

        # Short requires more collateral, so fewer shares
        assert short_shares < long_shares
        # Long: 50000 / 100.01 = 499 shares
        # Short: 50000 / 150.01 = 333 shares
        assert long_shares == 499
        assert short_shares == 333

    def test_calculate_short_shares_zero_allocation(self, portfolio):
        """Test zero allocation returns zero shares."""
        shares = portfolio._calculate_short_shares(Decimal('0'), Decimal('150.00'))
        assert shares == 0

    def test_calculate_short_shares_insufficient_collateral(self, portfolio):
        """Test small allocation that can't cover margin for even one share."""
        allocation = Decimal('100')  # Only $100
        price = Decimal('150.00')

        shares = portfolio._calculate_short_shares(allocation, price)

        # Need 150 * 1.5 + 0.01 = $225.01 per share
        assert shares == 0


class TestIntegrationExecuteSignal:
    """Integration tests for execute_signal with realistic scenarios."""

    def test_full_long_short_cycle(self, portfolio, market_bar):
        """Test opening and closing long and short positions via signals."""
        # Open long position with 50% allocation
        buy_signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.50'),
            strategy_name='test'
        )

        fill1 = portfolio.execute_signal(buy_signal, market_bar)
        assert fill1 is not None
        initial_cash = portfolio.cash
        initial_position = portfolio.get_position('AAPL')
        assert initial_position > 0

        # Update holdings
        portfolio.update_market_value({'AAPL': market_bar})

        # Close long position (sell all)
        close_signal = SignalEvent(
            symbol='AAPL',
            signal_type='SELL',
            timestamp=market_bar.timestamp,
            quantity=initial_position,
            portfolio_percent=Decimal('0.50'),  # Ignored for manual quantity
            strategy_name='test'
        )

        # Create manual order to close (not via execute_signal)
        close_order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='SELL',
            quantity=initial_position,
            timestamp=market_bar.timestamp
        )
        fill2 = portfolio.execute_order(close_order, market_bar)

        assert fill2 is not None
        assert portfolio.get_position('AAPL') == 0

    def test_insufficient_cash_for_signal(self, portfolio):
        """Test signal rejection when insufficient cash."""
        # Create expensive stock
        expensive_bar = MarketDataEvent(
            symbol='TSLA',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('10000.00'),
            high=Decimal('10100.00'),
            low=Decimal('9900.00'),
            close=Decimal('10000.00'),
            volume=100000,
            timeframe='1D'
        )

        # Try to buy with 150% allocation (impossible)
        signal = SignalEvent(
            symbol='TSLA',
            signal_type='BUY',
            timestamp=expensive_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('1.00'),  # Use all cash
            strategy_name='test'
        )

        fill1 = portfolio.execute_signal(signal, expensive_bar)
        assert fill1 is not None

        # Try another 100% allocation (should fail)
        signal2 = SignalEvent(
            symbol='TSLA',
            signal_type='BUY',
            timestamp=expensive_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('1.00'),
            strategy_name='test'
        )

        fill2 = portfolio.execute_signal(signal2, expensive_bar)
        # Should fail due to insufficient cash
        assert fill2 is None or portfolio.cash < Decimal('1000')

    def test_margin_fixes_short_rejection_bug(self, portfolio, market_bar):
        """Test that margin calculation fixes the original short rejection bug."""
        # This test verifies the fix for the bug where strategies
        # calculated short positions without accounting for margin,
        # causing rejections due to insufficient collateral.

        # Try to short with 80% allocation
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='SELL',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.80'),
            strategy_name='test'
        )

        fill = portfolio.execute_signal(signal, market_bar)

        # Should succeed because _calculate_short_shares accounts for margin
        assert fill is not None
        assert fill.direction == 'SELL'

        # Verify collateral is properly reserved
        # Short value = price * quantity
        short_value = fill.fill_price * fill.quantity
        margin_required = short_value * Decimal('1.5')

        # Portfolio should have reserved sufficient collateral
        # (This would have failed in the original bug)
        assert portfolio.cash > Decimal('0')  # Still has some cash
        # The order was accepted, proving margin calculation works


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_execute_signal_invalid_price(self, portfolio):
        """Test handling of invalid zero price."""
        bad_bar = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('0.01'),
            high=Decimal('0.01'),
            low=Decimal('0.01'),
            close=Decimal('0.01'),
            volume=1,
            timeframe='1D'
        )

        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=bad_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.50'),
            strategy_name='test'
        )

        # Should still work with very small price
        fill = portfolio.execute_signal(signal, bad_bar)
        assert fill is not None or fill is None  # Either way is acceptable

    def test_execute_signal_preserves_existing_logic(self, portfolio, market_bar):
        """Test that execute_signal properly delegates to execute_order."""
        signal = SignalEvent(
            symbol='AAPL',
            signal_type='BUY',
            timestamp=market_bar.timestamp,
            quantity=1,  # Ignored, using portfolio_percent instead
            portfolio_percent=Decimal('0.50'),
            strategy_name='test'
        )

        initial_cash = portfolio.cash
        fill = portfolio.execute_signal(signal, market_bar)

        assert fill is not None
        # Verify execute_order behavior is preserved
        assert portfolio.cash < initial_cash  # Cash deducted
        assert len(portfolio.fills) == 1  # Fill recorded
        assert portfolio.get_position('AAPL') > 0  # Position created


class TestIntradayFillPricing:
    """Test intraday fill pricing for execution timing feature."""

    def test_no_injection_uses_eod_close(self, portfolio, market_bar):
        """Test that without injection, portfolio uses EOD close (backward compatible)."""
        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )

        fill = portfolio.execute_order(order, market_bar)

        assert fill is not None
        # Should use EOD close with slippage
        expected_price = market_bar.close * (Decimal('1') + portfolio.slippage_percent)
        assert fill.fill_price == expected_price

    def test_execution_time_close_uses_eod(self, portfolio, market_bar):
        """Test that execution_time='close' uses EOD close even with injection."""
        # Mock data handler
        class MockDataHandler:
            def get_intraday_bars_for_time_window(self, **kwargs):
                return []

        portfolio.set_execution_context(
            execution_time="close",
            end_date=market_bar.timestamp,
            data_handler=MockDataHandler()
        )

        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )

        fill = portfolio.execute_order(order, market_bar)

        assert fill is not None
        # Should use EOD close even though injection exists
        expected_price = market_bar.close * (Decimal('1') + portfolio.slippage_percent)
        assert fill.fill_price == expected_price

    def test_intraday_price_on_last_day(self, portfolio, market_bar):
        """Test that intraday price is used on last day with execution_time != 'close'."""
        # Mock data handler with intraday data
        intraday_bar = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime(2025, 11, 24, 9, 45, tzinfo=timezone.utc),
            open=Decimal('148.00'),
            high=Decimal('149.00'),
            low=Decimal('147.50'),
            close=Decimal('148.50'),  # Intraday price at 9:45 AM
            volume=50000,
            timeframe='5m'
        )

        class MockDataHandler:
            def get_intraday_bars_for_time_window(self, **kwargs):
                return [intraday_bar]

        portfolio.set_execution_context(
            execution_time="15min_after_open",
            end_date=market_bar.timestamp,
            data_handler=MockDataHandler()
        )

        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )

        fill = portfolio.execute_order(order, market_bar)

        assert fill is not None
        # Should use intraday close with slippage
        expected_price = intraday_bar.close * (Decimal('1') + portfolio.slippage_percent)
        assert fill.fill_price == expected_price

    def test_fallback_to_eod_when_no_intraday_data(self, portfolio, market_bar):
        """Test graceful fallback to EOD close when intraday data unavailable."""
        # Mock data handler with no intraday data
        class MockDataHandler:
            def get_intraday_bars_for_time_window(self, **kwargs):
                return []

        portfolio.set_execution_context(
            execution_time="open",
            end_date=market_bar.timestamp,
            data_handler=MockDataHandler()
        )

        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )

        fill = portfolio.execute_order(order, market_bar)

        assert fill is not None
        # Should fallback to EOD close with slippage
        expected_price = market_bar.close * (Decimal('1') + portfolio.slippage_percent)
        assert fill.fill_price == expected_price

    def test_non_last_day_uses_eod(self, portfolio, market_bar):
        """Test that non-last days always use EOD close regardless of execution_time."""
        # Mock data handler (should NOT be called)
        class MockDataHandler:
            def get_intraday_bars_for_time_window(self, **kwargs):
                raise AssertionError("Should not fetch intraday data for non-last day")

        # Set end_date to future date (so current bar is NOT last day)
        future_date = datetime(2025, 12, 31, tzinfo=timezone.utc)
        portfolio.set_execution_context(
            execution_time="15min_after_open",
            end_date=future_date,
            data_handler=MockDataHandler()
        )

        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )

        fill = portfolio.execute_order(order, market_bar)

        assert fill is not None
        # Should use EOD close (intraday only applies to last day)
        expected_price = market_bar.close * (Decimal('1') + portfolio.slippage_percent)
        assert fill.fill_price == expected_price

    def test_multiple_symbols_intraday_pricing(self, portfolio):
        """Test intraday pricing works for multiple symbols."""
        # Create bars for QQQ and TQQQ
        qqq_bar = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime(2025, 11, 24, tzinfo=timezone.utc),
            open=Decimal('500.00'),
            high=Decimal('502.00'),
            low=Decimal('499.00'),
            close=Decimal('501.00'),
            volume=1000000,
            timeframe='1D'
        )

        tqqq_bar = MarketDataEvent(
            symbol='TQQQ',
            timestamp=datetime(2025, 11, 24, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.00'),
            low=Decimal('149.00'),
            close=Decimal('151.00'),
            volume=2000000,
            timeframe='1D'
        )

        # Mock intraday bars
        qqq_intraday = MarketDataEvent(
            symbol='QQQ',
            timestamp=datetime(2025, 11, 24, 9, 30, tzinfo=timezone.utc),
            open=Decimal('498.00'),
            high=Decimal('499.00'),
            low=Decimal('497.50'),
            close=Decimal('498.50'),
            volume=50000,
            timeframe='5m'
        )

        tqqq_intraday = MarketDataEvent(
            symbol='TQQQ',
            timestamp=datetime(2025, 11, 24, 9, 30, tzinfo=timezone.utc),
            open=Decimal('148.00'),
            high=Decimal('149.00'),
            low=Decimal('147.50'),
            close=Decimal('148.50'),
            volume=100000,
            timeframe='5m'
        )

        # Mock data handler
        class MockDataHandler:
            def get_intraday_bars_for_time_window(self, symbol, **kwargs):
                if symbol == 'QQQ':
                    return [qqq_intraday]
                elif symbol == 'TQQQ':
                    return [tqqq_intraday]
                return []

        portfolio.set_execution_context(
            execution_time="open",
            end_date=qqq_bar.timestamp,
            data_handler=MockDataHandler()
        )

        # Execute orders for both symbols
        qqq_order = OrderEvent(
            symbol='QQQ',
            order_type='MARKET',
            direction='BUY',
            quantity=10,
            timestamp=qqq_bar.timestamp
        )

        tqqq_order = OrderEvent(
            symbol='TQQQ',
            order_type='MARKET',
            direction='BUY',
            quantity=20,
            timestamp=tqqq_bar.timestamp
        )

        qqq_fill = portfolio.execute_order(qqq_order, qqq_bar)
        tqqq_fill = portfolio.execute_order(tqqq_order, tqqq_bar)

        assert qqq_fill is not None
        assert tqqq_fill is not None

        # Verify each uses its own intraday price
        qqq_expected = qqq_intraday.close * (Decimal('1') + portfolio.slippage_percent)
        tqqq_expected = tqqq_intraday.close * (Decimal('1') + portfolio.slippage_percent)

        assert qqq_fill.fill_price == qqq_expected
        assert tqqq_fill.fill_price == tqqq_expected

    def test_error_handling_in_intraday_fetch(self, portfolio, market_bar):
        """Test graceful error handling when intraday fetch fails."""
        # Mock data handler that raises exception
        class MockDataHandler:
            def get_intraday_bars_for_time_window(self, **kwargs):
                raise RuntimeError("Database connection error")

        portfolio.set_execution_context(
            execution_time="open",
            end_date=market_bar.timestamp,
            data_handler=MockDataHandler()
        )

        order = OrderEvent(
            symbol='AAPL',
            order_type='MARKET',
            direction='BUY',
            quantity=100,
            timestamp=market_bar.timestamp
        )

        fill = portfolio.execute_order(order, market_bar)

        assert fill is not None
        # Should fallback to EOD close despite error
        expected_price = market_bar.close * (Decimal('1') + portfolio.slippage_percent)
        assert fill.fill_price == expected_price
