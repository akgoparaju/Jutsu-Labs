"""
Base strategy interface for the Jutsu Labs backtesting engine.

All trading strategies must inherit from the Strategy base class and implement
the required methods. This ensures consistent interface for the EventLoop.
"""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd

from jutsu_engine.core.events import MarketDataEvent, SignalEvent


class Strategy(ABC):
    """
    Abstract base class for trading strategies.

    All custom strategies must inherit from this class and implement:
    - init(): Setup parameters and state
    - on_bar(): Process each new bar and generate signals

    The Strategy is "dumb" - it only generates signals, does not manage state.
    PortfolioSimulator handles all state management (cash, positions, PnL).

    Example:
        class SMA_Crossover(Strategy):
            def init(self):
                self.short_period = 20
                self.long_period = 50

            def on_bar(self, bar: MarketDataEvent):
                closes = self.get_closes(self.long_period)
                if len(closes) < self.long_period:
                    return  # Not enough data

                short_sma = closes.tail(self.short_period).mean()
                long_sma = closes.tail(self.long_period).mean()

                if short_sma > long_sma and not self.has_position():
                    self.buy(bar.symbol, 100)
                elif short_sma < long_sma and self.has_position():
                    self.sell(bar.symbol, 100)
    """

    def __init__(self):
        """Initialize strategy with default settings."""
        self.name = self.__class__.__name__
        self._bars: List[MarketDataEvent] = []  # Historical bars
        self._signals: List[SignalEvent] = []  # Generated signals
        self._positions: Dict[str, int] = {}  # Current positions (from portfolio)
        self._cash: Decimal = Decimal('0.00')  # Available cash (from portfolio)

    @abstractmethod
    def init(self):
        """
        Initialize strategy parameters and state.

        Called once before backtesting starts. Use this to:
        - Set strategy parameters (periods, thresholds, etc.)
        - Initialize any required state variables
        - Preload any data if needed

        Example:
            def init(self):
                self.sma_period = 20
                self.rsi_period = 14
                self.position_size = 100
        """
        pass

    @abstractmethod
    def on_bar(self, bar: MarketDataEvent):
        """
        Process new bar and generate trading signals.

        Called for each bar during backtest. Use this to:
        - Calculate indicators
        - Evaluate trading conditions
        - Generate buy/sell signals via self.buy() or self.sell()

        Args:
            bar: New market data bar with OHLCV data

        Example:
            def on_bar(self, bar: MarketDataEvent):
                closes = self.get_closes(20)
                sma = closes.mean()

                if bar.close > sma:
                    self.buy(bar.symbol, 100)
        """
        pass

    # Helper methods provided to strategies

    def buy(self, symbol: str, quantity: int, price: Optional[Decimal] = None):
        """
        Generate BUY signal.

        Args:
            symbol: Stock ticker symbol
            quantity: Number of shares to buy
            price: Optional limit price (None for market order)
        """
        signal = SignalEvent(
            symbol=symbol,
            signal_type='BUY',
            timestamp=self._bars[-1].timestamp if self._bars else None,
            quantity=quantity,
            strategy_name=self.name,
            price=price,
        )
        self._signals.append(signal)

    def sell(self, symbol: str, quantity: int, price: Optional[Decimal] = None):
        """
        Generate SELL signal.

        Args:
            symbol: Stock ticker symbol
            quantity: Number of shares to sell
            price: Optional limit price (None for market order)
        """
        signal = SignalEvent(
            symbol=symbol,
            signal_type='SELL',
            timestamp=self._bars[-1].timestamp if self._bars else None,
            quantity=quantity,
            strategy_name=self.name,
            price=price,
        )
        self._signals.append(signal)

    def get_closes(self, lookback: int = 100) -> pd.Series:
        """
        Get historical close prices.

        Args:
            lookback: Number of bars to retrieve

        Returns:
            pandas Series of close prices

        Example:
            closes = self.get_closes(20)
            sma = closes.mean()
        """
        if not self._bars:
            return pd.Series([], dtype='float64')

        closes = [bar.close for bar in self._bars[-lookback:]]
        return pd.Series(closes)

    def get_bars(self, lookback: int = 100) -> List[MarketDataEvent]:
        """
        Get historical bars.

        Args:
            lookback: Number of bars to retrieve

        Returns:
            List of MarketDataEvent objects

        Example:
            bars = self.get_bars(20)
            highs = [bar.high for bar in bars]
        """
        return self._bars[-lookback:]

    def has_position(self, symbol: Optional[str] = None) -> bool:
        """
        Check if we have an open position.

        Args:
            symbol: Stock symbol to check (None for any position)

        Returns:
            True if position exists

        Example:
            if not self.has_position('AAPL'):
                self.buy('AAPL', 100)
        """
        if symbol is None:
            return len(self._positions) > 0
        return self._positions.get(symbol, 0) > 0

    def get_position(self, symbol: str) -> int:
        """
        Get current position size for symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Number of shares held (0 if no position)

        Example:
            current_shares = self.get_position('AAPL')
        """
        return self._positions.get(symbol, 0)

    # Internal methods (called by EventLoop/Portfolio)

    def _update_bar(self, bar: MarketDataEvent):
        """
        Internal: Add new bar to history.

        Called by EventLoop before on_bar(). Not for strategy use.
        """
        self._bars.append(bar)

    def _update_portfolio_state(self, positions: Dict[str, int], cash: Decimal):
        """
        Internal: Update portfolio state from PortfolioSimulator.

        Called by EventLoop after each bar. Not for strategy use.
        """
        self._positions = positions.copy()
        self._cash = cash

    def get_signals(self) -> List[SignalEvent]:
        """
        Internal: Get generated signals and clear buffer.

        Called by EventLoop after on_bar(). Not for strategy use.
        """
        signals = self._signals.copy()
        self._signals.clear()
        return signals
