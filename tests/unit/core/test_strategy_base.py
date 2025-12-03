"""
Unit tests for Strategy base class.

Tests the abstract Strategy interface and helper methods.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent, SignalEvent


class ConcreteStrategy(Strategy):
    """Concrete strategy for testing (minimal implementation)."""

    def init(self):
        """Initialize test strategy."""
        self.test_param = 42

    def on_bar(self, bar: MarketDataEvent):
        """Minimal on_bar implementation."""
        pass


class TestStrategyInitialization:
    """Test strategy initialization and abstract methods."""

    def test_cannot_instantiate_abstract_strategy(self):
        """Strategy ABC cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Strategy()

    def test_concrete_strategy_instantiation(self):
        """Concrete strategy can be instantiated."""
        strategy = ConcreteStrategy()
        assert strategy.name == 'ConcreteStrategy'
        assert strategy._bars == []
        assert strategy._signals == []
        assert strategy._positions == {}
        assert strategy._cash == Decimal('0.00')

    def test_init_method_called(self):
        """Strategy.init() is called and sets parameters."""
        strategy = ConcreteStrategy()
        strategy.init()
        assert strategy.test_param == 42


class TestBuyMethod:
    """Test buy() method with portfolio percentage API."""

    def setup_method(self):
        """Set up test strategy with a bar."""
        self.strategy = ConcreteStrategy()
        bar = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.00'),
            low=Decimal('149.00'),
            close=Decimal('151.00'),
            volume=1000000,
            timeframe='1D'
        )
        self.strategy._update_bar(bar)

    def test_buy_with_valid_percentage(self):
        """buy() generates SignalEvent with portfolio_percent."""
        self.strategy.buy('AAPL', Decimal('0.8'))

        signals = self.strategy.get_signals()
        assert len(signals) == 1

        signal = signals[0]
        assert signal.symbol == 'AAPL'
        assert signal.signal_type == 'BUY'
        assert signal.portfolio_percent == Decimal('0.8')
        assert signal.strategy_name == 'ConcreteStrategy'
        assert signal.price is None

    def test_buy_with_limit_price(self):
        """buy() with limit price."""
        self.strategy.buy('AAPL', Decimal('0.5'), price=Decimal('150.00'))

        signals = self.strategy.get_signals()
        signal = signals[0]
        assert signal.portfolio_percent == Decimal('0.5')
        assert signal.price == Decimal('150.00')

    def test_buy_with_min_percentage(self):
        """buy() with 0% (edge case)."""
        self.strategy.buy('AAPL', Decimal('0.0'))
        signals = self.strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.0')

    def test_buy_with_max_percentage(self):
        """buy() with 100%."""
        self.strategy.buy('AAPL', Decimal('1.0'))
        signals = self.strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('1.0')

    def test_buy_with_negative_percentage_raises_error(self):
        """buy() with negative percentage raises ValueError."""
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            self.strategy.buy('AAPL', Decimal('-0.1'))

    def test_buy_with_percentage_above_one_raises_error(self):
        """buy() with percentage > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            self.strategy.buy('AAPL', Decimal('1.5'))

    def test_buy_multiple_signals(self):
        """Multiple buy() calls generate multiple signals."""
        self.strategy.buy('AAPL', Decimal('0.5'))
        self.strategy.buy('MSFT', Decimal('0.3'))

        signals = self.strategy.get_signals()
        assert len(signals) == 2
        assert signals[0].symbol == 'AAPL'
        assert signals[0].portfolio_percent == Decimal('0.5')
        assert signals[1].symbol == 'MSFT'
        assert signals[1].portfolio_percent == Decimal('0.3')


class TestSellMethod:
    """Test sell() method with portfolio percentage API."""

    def setup_method(self):
        """Set up test strategy with a bar."""
        self.strategy = ConcreteStrategy()
        bar = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.00'),
            low=Decimal('149.00'),
            close=Decimal('151.00'),
            volume=1000000,
            timeframe='1D'
        )
        self.strategy._update_bar(bar)

    def test_sell_with_valid_percentage(self):
        """sell() generates SignalEvent with portfolio_percent."""
        self.strategy.sell('AAPL', Decimal('0.8'))

        signals = self.strategy.get_signals()
        assert len(signals) == 1

        signal = signals[0]
        assert signal.symbol == 'AAPL'
        assert signal.signal_type == 'SELL'
        assert signal.portfolio_percent == Decimal('0.8')
        assert signal.strategy_name == 'ConcreteStrategy'
        assert signal.price is None

    def test_sell_with_limit_price(self):
        """sell() with limit price."""
        self.strategy.sell('AAPL', Decimal('0.5'), price=Decimal('150.00'))

        signals = self.strategy.get_signals()
        signal = signals[0]
        assert signal.portfolio_percent == Decimal('0.5')
        assert signal.price == Decimal('150.00')

    def test_sell_with_min_percentage(self):
        """sell() with 0% (edge case)."""
        self.strategy.sell('AAPL', Decimal('0.0'))
        signals = self.strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('0.0')

    def test_sell_with_max_percentage(self):
        """sell() with 100%."""
        self.strategy.sell('AAPL', Decimal('1.0'))
        signals = self.strategy.get_signals()
        assert signals[0].portfolio_percent == Decimal('1.0')

    def test_sell_with_negative_percentage_raises_error(self):
        """sell() with negative percentage raises ValueError."""
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            self.strategy.sell('AAPL', Decimal('-0.1'))

    def test_sell_with_percentage_above_one_raises_error(self):
        """sell() with percentage > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            self.strategy.sell('AAPL', Decimal('1.5'))


class TestHelperMethods:
    """Test strategy helper methods."""

    def setup_method(self):
        """Set up test strategy."""
        self.strategy = ConcreteStrategy()

    def test_get_closes_empty(self):
        """get_closes() with no bars returns empty series."""
        closes = self.strategy.get_closes(10)
        assert len(closes) == 0

    def test_get_closes_with_bars(self):
        """get_closes() returns close prices."""
        for i in range(5):
            close_price = Decimal(f'{150 + i}.00')
            bar = MarketDataEvent(
                symbol='AAPL',
                timestamp=datetime.now(timezone.utc),
                open=Decimal('150.00'),
                high=Decimal(f'{152 + i}.00'),  # High must be >= close
                low=Decimal('149.00'),
                close=close_price,
                volume=1000000,
                timeframe='1D'
            )
            self.strategy._update_bar(bar)

        closes = self.strategy.get_closes(5)
        assert len(closes) == 5
        assert closes.iloc[-1] == Decimal('154.00')

    def test_has_position_no_positions(self):
        """has_position() returns False with no positions."""
        assert not self.strategy.has_position('AAPL')
        assert not self.strategy.has_position()

    def test_has_position_with_positions(self):
        """has_position() returns True with positions."""
        self.strategy._update_portfolio_state(
            positions={'AAPL': 100},
            cash=Decimal('10000.00')
        )
        assert self.strategy.has_position('AAPL')
        assert self.strategy.has_position()

    def test_get_position(self):
        """get_position() returns position size."""
        self.strategy._update_portfolio_state(
            positions={'AAPL': 100, 'MSFT': 50},
            cash=Decimal('10000.00')
        )
        assert self.strategy.get_position('AAPL') == 100
        assert self.strategy.get_position('MSFT') == 50
        assert self.strategy.get_position('GOOGL') == 0


class TestSignalBuffer:
    """Test signal buffer management."""

    def setup_method(self):
        """Set up test strategy."""
        self.strategy = ConcreteStrategy()
        bar = MarketDataEvent(
            symbol='AAPL',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('152.00'),
            low=Decimal('149.00'),
            close=Decimal('151.00'),
            volume=1000000,
            timeframe='1D'
        )
        self.strategy._update_bar(bar)

    def test_get_signals_clears_buffer(self):
        """get_signals() returns signals and clears buffer."""
        self.strategy.buy('AAPL', Decimal('0.8'))
        signals = self.strategy.get_signals()
        assert len(signals) == 1

        # Buffer should be cleared
        signals2 = self.strategy.get_signals()
        assert len(signals2) == 0

    def test_signals_accumulate(self):
        """Multiple signals accumulate before get_signals()."""
        self.strategy.buy('AAPL', Decimal('0.5'))
        self.strategy.sell('MSFT', Decimal('0.3'))

        signals = self.strategy.get_signals()
        assert len(signals) == 2


class TestWarmupPeriod:
    """Test warmup period functionality."""

    def test_default_warmup_returns_zero(self):
        """Base strategy returns 0 warmup bars by default."""
        strategy = ConcreteStrategy()
        warmup_bars = strategy.get_required_warmup_bars()
        assert warmup_bars == 0

    def test_strategy_can_override_warmup(self):
        """Strategy subclass can override warmup period."""
        class WarmupStrategy(Strategy):
            """Test strategy with warmup period."""

            def init(self):
                self.sma_period = 50

            def on_bar(self, bar: MarketDataEvent):
                pass

            def get_required_warmup_bars(self) -> int:
                return 100

        strategy = WarmupStrategy()
        warmup_bars = strategy.get_required_warmup_bars()
        assert warmup_bars == 100

    def test_warmup_calculation_with_parameters(self):
        """Warmup period calculated from strategy parameters."""
        class ParameterizedWarmupStrategy(Strategy):
            """Test strategy with parameter-based warmup."""

            def init(self):
                self.short_period = 20
                self.long_period = 50
                self.buffer = 10

            def on_bar(self, bar: MarketDataEvent):
                pass

            def get_required_warmup_bars(self) -> int:
                # Need longest period + buffer
                return self.long_period + self.buffer

        strategy = ParameterizedWarmupStrategy()
        strategy.init()  # Initialize parameters
        warmup_bars = strategy.get_required_warmup_bars()
        assert warmup_bars == 60  # 50 + 10
