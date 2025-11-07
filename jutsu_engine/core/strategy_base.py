"""
Base strategy interface for the Jutsu Labs backtesting engine.

All trading strategies must inherit from the Strategy base class and implement
the required methods. This ensures consistent interface for the EventLoop.
"""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional, TYPE_CHECKING
import pandas as pd
import logging

from jutsu_engine.core.events import MarketDataEvent, SignalEvent

if TYPE_CHECKING:
    from jutsu_engine.performance.trade_logger import TradeLogger


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

                # New API: Use portfolio percentage instead of fixed quantity
                if short_sma > long_sma and not self.has_position():
                    self.buy(bar.symbol, Decimal('0.8'))  # 80% of portfolio
                elif short_sma < long_sma and self.has_position():
                    self.sell(bar.symbol, Decimal('0.8'))  # Short 80%
    """

    def __init__(self):
        """Initialize strategy with default settings."""
        self.name = self.__class__.__name__
        self._bars: List[MarketDataEvent] = []  # Historical bars
        self._signals: List[SignalEvent] = []  # Generated signals
        self._positions: Dict[str, int] = {}  # Current positions (from portfolio)
        self._cash: Decimal = Decimal('0.00')  # Available cash (from portfolio)
        self._trade_logger: Optional['TradeLogger'] = None  # Trade context logger

    def _set_trade_logger(self, logger: 'TradeLogger') -> None:
        """
        Inject TradeLogger for strategy context logging.

        Called by EventLoop during strategy initialization.
        Strategies should call logger.log_strategy_context() before signals.

        Args:
            logger: TradeLogger instance for this backtest

        Example in strategy subclass:
            def on_bar(self, bar):
                # Calculate indicators
                ema_fast = calculate_ema(self.get_closes(10), 10)
                ema_slow = calculate_ema(self.get_closes(20), 20)
                adx = calculate_adx(self.get_highs(14), self.get_lows(14),
                                   self.get_closes(14), 14)

                # Determine regime state
                if adx > Decimal('25'):
                    if ema_fast > ema_slow:
                        regime = "Regime 1: Strong Bullish"
                    else:
                        regime = "Regime 2: Strong Bearish"
                else:
                    regime = "Regime 0: Weak Trend"

                # Log context BEFORE generating signal
                if self._trade_logger:
                    self._trade_logger.log_strategy_context(
                        timestamp=bar.timestamp,
                        symbol=bar.symbol,
                        strategy_state=regime,
                        decision_reason=f"EMA_fast({ema_fast:.2f}) > EMA_slow({ema_slow:.2f}) AND ADX({adx:.2f}) > 25",
                        indicator_values={
                            'EMA_fast': ema_fast,
                            'EMA_slow': ema_slow,
                            'ADX': adx
                        },
                        threshold_values={
                            'ADX_threshold': Decimal('25')
                        }
                    )

                # Then generate signal
                if ema_fast > ema_slow and adx > Decimal('25'):
                    self.buy(bar.symbol, Decimal('0.8'))
        """
        self._trade_logger = logger

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
                    self.buy(bar.symbol, Decimal('0.8'))  # Allocate 80%
        """
        pass

    # Helper methods provided to strategies

    def buy(
        self,
        symbol: str,
        portfolio_percent: Decimal,
        price: Optional[Decimal] = None,
        risk_per_share: Optional[Decimal] = None
    ):
        """
        Generate BUY signal with portfolio allocation percentage.

        Strategy specifies what percentage of portfolio to allocate, and Portfolio
        module converts this to actual shares based on available cash, margin
        requirements, and other constraints.

        Args:
            symbol: Stock ticker symbol
            portfolio_percent: Percentage of portfolio to allocate (0.0 to 1.0)
                              e.g., Decimal('0.8') for 80% allocation
            price: Optional limit price (None for market order)
            risk_per_share: Optional dollar risk per share for ATR-based position sizing
                          When provided, Portfolio calculates shares as:
                          shares = (portfolio_value × portfolio_percent) / risk_per_share
                          Typical value: ATR × stop_multiplier (e.g., $2.50 × 2.0 = $5.00)

        Raises:
            ValueError: If portfolio_percent is not in range [0.0, 1.0]
            ValueError: If risk_per_share is provided but not positive

        Example:
            # Simple percentage allocation
            self.buy('AAPL', Decimal('0.8'))

            # ATR-based position sizing
            atr = Decimal('2.50')
            risk_per_share = atr * Decimal('2.0')  # $5.00
            self.buy('TQQQ', Decimal('0.03'), risk_per_share=risk_per_share)

            # With limit price
            self.buy('AAPL', Decimal('0.5'), price=Decimal('150.00'))

        Note:
            Portfolio module will convert percentage to actual shares based on:
            - Available cash
            - Current portfolio value
            - Margin requirements (100% for longs)
            - Commission and slippage
            - risk_per_share if provided (ATR-based sizing)
        """
        # Validate portfolio_percent range
        if not (Decimal('0.0') <= portfolio_percent <= Decimal('1.0')):
            raise ValueError(
                f"Portfolio percent must be between 0.0 and 1.0, got {portfolio_percent}"
            )

        # Validate risk_per_share if provided
        if risk_per_share is not None and risk_per_share <= Decimal('0.0'):
            raise ValueError(
                f"risk_per_share must be positive, got {risk_per_share}"
            )

        signal = SignalEvent(
            symbol=symbol,
            signal_type='BUY',
            timestamp=self._bars[-1].timestamp if self._bars else None,
            quantity=1,  # Placeholder - Portfolio will calculate actual quantity from portfolio_percent
            portfolio_percent=portfolio_percent,
            strategy_name=self.name,
            price=price,
            risk_per_share=risk_per_share,
        )
        self._signals.append(signal)

    def sell(
        self,
        symbol: str,
        portfolio_percent: Decimal,
        price: Optional[Decimal] = None,
        risk_per_share: Optional[Decimal] = None
    ):
        """
        Generate SELL signal with portfolio allocation percentage.

        Strategy specifies what percentage of portfolio to allocate, and Portfolio
        module converts this to actual shares based on available cash, margin
        requirements (150% for shorts), and other constraints.

        Args:
            symbol: Stock ticker symbol
            portfolio_percent: Percentage of portfolio to allocate (0.0 to 1.0)
                              e.g., Decimal('0.8') for 80% allocation
            price: Optional limit price (None for market order)
            risk_per_share: Optional dollar risk per share for ATR-based position sizing
                          When provided, Portfolio calculates shares as:
                          shares = (portfolio_value × portfolio_percent) / risk_per_share
                          Typical value: ATR × stop_multiplier (e.g., $2.50 × 2.0 = $5.00)

        Raises:
            ValueError: If portfolio_percent is not in range [0.0, 1.0]
            ValueError: If risk_per_share is provided but not positive

        Example:
            # Simple percentage allocation
            self.sell('AAPL', Decimal('0.8'))

            # ATR-based position sizing
            atr = Decimal('2.50')
            risk_per_share = atr * Decimal('2.0')  # $5.00
            self.sell('SQQQ', Decimal('0.03'), risk_per_share=risk_per_share)

            # With limit price
            self.sell('AAPL', Decimal('0.5'), price=Decimal('150.00'))

        Note:
            Portfolio module will convert percentage to actual shares based on:
            - Available cash
            - Current portfolio value
            - Margin requirements (150% for shorts)
            - Commission and slippage
            - risk_per_share if provided (ATR-based sizing)
        """
        # Validate portfolio_percent range
        if not (Decimal('0.0') <= portfolio_percent <= Decimal('1.0')):
            raise ValueError(
                f"Portfolio percent must be between 0.0 and 1.0, got {portfolio_percent}"
            )

        # Validate risk_per_share if provided
        if risk_per_share is not None and risk_per_share <= Decimal('0.0'):
            raise ValueError(
                f"risk_per_share must be positive, got {risk_per_share}"
            )

        signal = SignalEvent(
            symbol=symbol,
            signal_type='SELL',
            timestamp=self._bars[-1].timestamp if self._bars else None,
            quantity=1,  # Placeholder - Portfolio will calculate actual quantity from portfolio_percent
            portfolio_percent=portfolio_percent,
            strategy_name=self.name,
            price=price,
            risk_per_share=risk_per_share,
        )
        self._signals.append(signal)

    def get_closes(self, lookback: int = 100, symbol: Optional[str] = None) -> pd.Series:
        """
        Get historical close prices.

        Args:
            lookback: Number of bars to retrieve
            symbol: Optional symbol to filter by (for multi-symbol strategies)

        Returns:
            pandas Series of close prices

        Example:
            closes = self.get_closes(20)
            sma = closes.mean()

            # Multi-symbol strategy: filter for specific symbol
            qqq_closes = self.get_closes(20, symbol='QQQ')
        """
        if not self._bars:
            return pd.Series([], dtype='float64')

        # Filter by symbol if specified (for multi-symbol strategies)
        bars = self._bars
        if symbol:
            bars = [bar for bar in bars if bar.symbol == symbol]

        closes = [bar.close for bar in bars[-lookback:]]
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

    def get_highs(self, lookback: int = 100, symbol: Optional[str] = None) -> pd.Series:
        """
        Get historical high prices.

        Args:
            lookback: Number of bars to retrieve
            symbol: Optional symbol to filter by (for multi-symbol strategies)

        Returns:
            pandas Series of high prices

        Example:
            highs = self.get_highs(20)
            highest = highs.max()

            # Multi-symbol strategy: filter for specific symbol
            qqq_highs = self.get_highs(20, symbol='QQQ')
        """
        if not self._bars:
            return pd.Series([], dtype='float64')

        # Filter by symbol if specified (for multi-symbol strategies)
        bars = self._bars
        if symbol:
            bars = [bar for bar in bars if bar.symbol == symbol]

        highs = [bar.high for bar in bars[-lookback:]]
        return pd.Series(highs)

    def get_lows(self, lookback: int = 100, symbol: Optional[str] = None) -> pd.Series:
        """
        Get historical low prices.

        Args:
            lookback: Number of bars to retrieve
            symbol: Optional symbol to filter by (for multi-symbol strategies)

        Returns:
            pandas Series of low prices

        Example:
            lows = self.get_lows(20)
            lowest = lows.min()

            # Multi-symbol strategy: filter for specific symbol
            qqq_lows = self.get_lows(20, symbol='QQQ')
        """
        if not self._bars:
            return pd.Series([], dtype='float64')

        # Filter by symbol if specified (for multi-symbol strategies)
        bars = self._bars
        if symbol:
            bars = [bar for bar in bars if bar.symbol == symbol]

        lows = [bar.low for bar in bars[-lookback:]]
        return pd.Series(lows)

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

    def log(self, message: str):
        """
        Log a strategy message.

        Args:
            message: Message to log

        Example:
            self.log(f"BUY signal: {symbol} at ${price}")
        """
        logger = logging.getLogger(f'STRATEGY.{self.name}')
        logger.info(message)

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
