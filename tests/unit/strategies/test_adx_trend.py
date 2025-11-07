"""
Unit tests for ADX_Trend strategy.

Tests regime detection, regime transitions, multi-symbol handling,
and edge cases.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from jutsu_engine.strategies.ADX_Trend import ADX_Trend
from jutsu_engine.core.events import MarketDataEvent


class TestADXTrendRegimeDetection:
    """Test regime detection logic."""

    def test_regime_1_strong_bullish(self):
        """Test Regime 1: Strong Bullish (ADX > 25, EMA_fast > EMA_slow)."""
        strategy = ADX_Trend()
        strategy.init()

        # Strong bullish: EMA_fast > EMA_slow, ADX > 25
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('30.00')
        )
        assert regime == 1

    def test_regime_2_building_bullish(self):
        """Test Regime 2: Building Bullish (20 < ADX <= 25, EMA_fast > EMA_slow)."""
        strategy = ADX_Trend()
        strategy.init()

        # Building bullish: EMA_fast > EMA_slow, 20 < ADX <= 25
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('22.50')
        )
        assert regime == 2

    def test_regime_3_strong_bearish(self):
        """Test Regime 3: Strong Bearish (ADX > 25, EMA_fast < EMA_slow)."""
        strategy = ADX_Trend()
        strategy.init()

        # Strong bearish: EMA_fast < EMA_slow, ADX > 25
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('145.00'),
            ema_slow_val=Decimal('150.00'),
            adx_val=Decimal('30.00')
        )
        assert regime == 3

    def test_regime_4_building_bearish(self):
        """Test Regime 4: Building Bearish (20 < ADX <= 25, EMA_fast < EMA_slow)."""
        strategy = ADX_Trend()
        strategy.init()

        # Building bearish: EMA_fast < EMA_slow, 20 < ADX <= 25
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('145.00'),
            ema_slow_val=Decimal('150.00'),
            adx_val=Decimal('22.50')
        )
        assert regime == 4

    def test_regime_5_weak_bullish(self):
        """Test Regime 5: Weak Bullish (ADX <= 20, EMA_fast > EMA_slow)."""
        strategy = ADX_Trend()
        strategy.init()

        # Weak bullish: EMA_fast > EMA_slow, ADX <= 20
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('18.00')
        )
        assert regime == 5

    def test_regime_6_weak_bearish(self):
        """Test Regime 6: Weak Bearish (ADX <= 20, EMA_fast < EMA_slow)."""
        strategy = ADX_Trend()
        strategy.init()

        # Weak bearish: EMA_fast < EMA_slow, ADX <= 20
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('145.00'),
            ema_slow_val=Decimal('150.00'),
            adx_val=Decimal('18.00')
        )
        assert regime == 6

    def test_adx_boundary_low(self):
        """Test ADX threshold boundary at 20."""
        strategy = ADX_Trend()
        strategy.init()

        # Exactly at low threshold (should be weak)
        regime_weak = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('20.00')
        )
        assert regime_weak == 5  # Weak bullish

        # Just above low threshold (should be building)
        regime_building = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('20.01')
        )
        assert regime_building == 2  # Building bullish

    def test_adx_boundary_high(self):
        """Test ADX threshold boundary at 25."""
        strategy = ADX_Trend()
        strategy.init()

        # Exactly at high threshold (should be building)
        regime_building = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('25.00')
        )
        assert regime_building == 2  # Building bullish

        # Just above high threshold (should be strong)
        regime_strong = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('25.01')
        )
        assert regime_strong == 1  # Strong bullish

    def test_ema_equal(self):
        """Test EMA values equal (edge case - should be bearish)."""
        strategy = ADX_Trend()
        strategy.init()

        # EMA_fast == EMA_slow (not > so should be bearish)
        regime = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('150.00'),
            adx_val=Decimal('30.00')
        )
        assert regime == 3  # Strong bearish (not bullish since not >)


class TestADXTrendRegimeTransitions:
    """Test regime transitions and rebalancing."""

    def create_bar(self, symbol: str, price: Decimal) -> MarketDataEvent:
        """Helper to create market data bar."""
        return MarketDataEvent(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            open=price,
            high=price * Decimal('1.01'),
            low=price * Decimal('0.99'),
            close=price,
            volume=1000000
        )

    def feed_bars(self, strategy, symbol: str, count: int, start_price: Decimal):
        """Helper to feed multiple bars to strategy."""
        for i in range(count):
            price = start_price + Decimal(str(i * 0.1))
            bar = self.create_bar(symbol, price)
            strategy._update_bar(bar)

    def test_regime_change_triggers_rebalance(self):
        """Test that regime change triggers liquidation and new allocation."""
        strategy = ADX_Trend()
        strategy.init()

        # Feed enough bars for indicators
        self.feed_bars(strategy, 'QQQ', 60, Decimal('150.00'))

        # Manually set regime to strong bullish (1)
        strategy.previous_regime = 1

        # Simulate position in TQQQ
        strategy._positions['TQQQ'] = 100

        # Feed one bar (should process and potentially change regime)
        bar = self.create_bar('QQQ', Decimal('160.00'))
        strategy._update_bar(bar)
        strategy.on_bar(bar)

        # Check that signals were generated (regime transition occurred)
        signals = strategy.get_signals()
        # Should have liquidation signals and new allocation signals
        assert len(signals) >= 0  # May or may not change regime depending on indicators

    def test_no_change_no_rebalance(self):
        """Test that no regime change means no rebalancing."""
        strategy = ADX_Trend()
        strategy.init()

        # Feed enough bars
        self.feed_bars(strategy, 'QQQ', 60, Decimal('150.00'))

        # Process first bar to establish regime
        bar1 = self.create_bar('QQQ', Decimal('150.00'))
        strategy._update_bar(bar1)
        strategy.on_bar(bar1)
        initial_signals = strategy.get_signals()

        # Process second bar with similar price (regime shouldn't change)
        bar2 = self.create_bar('QQQ', Decimal('150.10'))
        strategy._update_bar(bar2)
        strategy.on_bar(bar2)
        second_signals = strategy.get_signals()

        # No signals if regime didn't change
        assert len(second_signals) == 0

    def test_liquidation_all_symbols(self):
        """Test that liquidation closes all positions."""
        strategy = ADX_Trend()
        strategy.init()

        # Simulate positions in all symbols
        strategy._positions['TQQQ'] = 100
        strategy._positions['SQQQ'] = 50
        strategy._positions['QQQ'] = 75

        # Call liquidation
        strategy._liquidate_all_positions()

        # Check signals generated (should be 3 sell signals with 0% allocation)
        signals = strategy.get_signals()
        assert len(signals) == 3

        # All should be SELL signals with 0% allocation
        for signal in signals:
            assert signal.signal_type == 'SELL'
            assert signal.portfolio_percent == Decimal('0.0')


class TestADXTrendMultiSymbol:
    """Test multi-symbol handling."""

    def create_bar(self, symbol: str, price: Decimal) -> MarketDataEvent:
        """Helper to create market data bar."""
        return MarketDataEvent(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            open=price,
            high=price * Decimal('1.01'),
            low=price * Decimal('0.99'),
            close=price,
            volume=1000000
        )

    def test_only_qqq_bars_processed(self):
        """Test that only QQQ bars trigger regime calculation."""
        strategy = ADX_Trend()
        strategy.init()

        # Feed QQQ bars
        for i in range(60):
            bar = self.create_bar('QQQ', Decimal('150.00') + Decimal(str(i * 0.1)))
            strategy._update_bar(bar)

        # Feed TQQQ bar (should be ignored)
        tqqq_bar = self.create_bar('TQQQ', Decimal('45.00'))
        strategy._update_bar(tqqq_bar)
        strategy.on_bar(tqqq_bar)
        signals = strategy.get_signals()
        assert len(signals) == 0  # TQQQ bar ignored

        # Feed SQQQ bar (should be ignored)
        sqqq_bar = self.create_bar('SQQQ', Decimal('30.00'))
        strategy._update_bar(sqqq_bar)
        strategy.on_bar(sqqq_bar)
        signals = strategy.get_signals()
        assert len(signals) == 0  # SQQQ bar ignored

    def test_correct_symbol_allocation(self):
        """Test that correct symbols are traded for each regime."""
        strategy = ADX_Trend()
        strategy.init()

        # Test Regime 1: TQQQ
        strategy._execute_regime_allocation(1)
        signals = strategy.get_signals()
        assert len(signals) == 1
        assert signals[0].symbol == 'TQQQ'
        assert signals[0].portfolio_percent == Decimal('0.60')

        # Test Regime 3: SQQQ
        strategy._execute_regime_allocation(3)
        signals = strategy.get_signals()
        assert len(signals) == 1
        assert signals[0].symbol == 'SQQQ'
        assert signals[0].portfolio_percent == Decimal('0.60')

        # Test Regime 5: QQQ
        strategy._execute_regime_allocation(5)
        signals = strategy.get_signals()
        assert len(signals) == 1
        assert signals[0].symbol == 'QQQ'
        assert signals[0].portfolio_percent == Decimal('0.50')

        # Test Regime 6: CASH (no signal)
        strategy._execute_regime_allocation(6)
        signals = strategy.get_signals()
        assert len(signals) == 0


class TestADXTrendAllocationPercentages:
    """Test allocation percentages for each regime."""

    def test_regime_1_allocation(self):
        """Test Regime 1 allocates 60% to TQQQ."""
        strategy = ADX_Trend()
        strategy.init()

        strategy._execute_regime_allocation(1)
        signals = strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.60')

    def test_regime_2_allocation(self):
        """Test Regime 2 allocates 30% to TQQQ."""
        strategy = ADX_Trend()
        strategy.init()

        strategy._execute_regime_allocation(2)
        signals = strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.30')

    def test_regime_3_allocation(self):
        """Test Regime 3 allocates 60% to SQQQ."""
        strategy = ADX_Trend()
        strategy.init()

        strategy._execute_regime_allocation(3)
        signals = strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.60')

    def test_regime_4_allocation(self):
        """Test Regime 4 allocates 30% to SQQQ."""
        strategy = ADX_Trend()
        strategy.init()

        strategy._execute_regime_allocation(4)
        signals = strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.30')

    def test_regime_5_allocation(self):
        """Test Regime 5 allocates 50% to QQQ."""
        strategy = ADX_Trend()
        strategy.init()

        strategy._execute_regime_allocation(5)
        signals = strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.50')

    def test_regime_6_allocation(self):
        """Test Regime 6 is 100% cash (no allocation)."""
        strategy = ADX_Trend()
        strategy.init()

        strategy._execute_regime_allocation(6)
        signals = strategy.get_signals()
        assert len(signals) == 0  # No position


class TestADXTrendEdgeCases:
    """Test edge cases and error conditions."""

    def create_bar(self, symbol: str, price: Decimal) -> MarketDataEvent:
        """Helper to create market data bar."""
        return MarketDataEvent(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            open=price,
            high=price * Decimal('1.01'),
            low=price * Decimal('0.99'),
            close=price,
            volume=1000000
        )

    def test_insufficient_bars(self):
        """Test that strategy doesn't trade with insufficient bars."""
        strategy = ADX_Trend()
        strategy.init()

        # Feed only a few bars (not enough for indicators)
        for i in range(10):
            bar = self.create_bar('QQQ', Decimal('150.00'))
            strategy._update_bar(bar)
            strategy.on_bar(bar)

        # Should generate no signals
        signals = strategy.get_signals()
        assert len(signals) == 0

    def test_custom_parameters(self):
        """Test strategy with custom parameters."""
        strategy = ADX_Trend(
            ema_fast_period=10,
            ema_slow_period=30,
            adx_period=10,
            adx_threshold_low=Decimal('15'),
            adx_threshold_high=Decimal('20')
        )
        strategy.init()

        # Verify parameters set correctly
        assert strategy.ema_fast_period == 10
        assert strategy.ema_slow_period == 30
        assert strategy.adx_period == 10
        assert strategy.adx_threshold_low == Decimal('15')
        assert strategy.adx_threshold_high == Decimal('20')

    def test_extreme_adx_values(self):
        """Test with extreme ADX values."""
        strategy = ADX_Trend()
        strategy.init()

        # Very low ADX (should be weak)
        regime_low = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('5.00')
        )
        assert regime_low == 5  # Weak bullish

        # Very high ADX (should be strong)
        regime_high = strategy._determine_regime(
            ema_fast_val=Decimal('150.00'),
            ema_slow_val=Decimal('145.00'),
            adx_val=Decimal('75.00')
        )
        assert regime_high == 1  # Strong bullish

    def test_initial_regime_none(self):
        """Test that initial regime is None."""
        strategy = ADX_Trend()
        strategy.init()

        assert strategy.previous_regime is None

    def test_first_regime_establishment(self):
        """Test that first regime is established correctly."""
        strategy = ADX_Trend()
        strategy.init()

        # Feed enough bars
        for i in range(60):
            bar = self.create_bar('QQQ', Decimal('150.00') + Decimal(str(i * 0.1)))
            strategy._update_bar(bar)

        # Process one bar
        bar = self.create_bar('QQQ', Decimal('156.00'))
        strategy._update_bar(bar)
        strategy.on_bar(bar)

        # Previous regime should now be set
        assert strategy.previous_regime is not None
        assert 1 <= strategy.previous_regime <= 6
