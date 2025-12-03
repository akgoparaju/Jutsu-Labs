"""
Simple Moving Average (SMA) Crossover Strategy.

Classic trend-following strategy that generates signals based on
crossovers between short-term and long-term moving averages.

Strategy Logic:
- BUY when short SMA crosses above long SMA (golden cross)
- SELL when short SMA crosses below long SMA (death cross)
- Only one position at a time (no pyramiding)

Multi-Symbol Support:
- Supports backtesting with multiple symbols simultaneously
- SMAs calculated independently per symbol (no mixing of data)
- Crossover signals generated per symbol

Example:
    from jutsu_engine.strategies.sma_crossover import SMA_Crossover

    strategy = SMA_Crossover(
        short_period=20,
        long_period=50,
        position_percent=Decimal('1.0')  # 100% portfolio allocation
    )

    # Used in EventLoop (single or multi-symbol)
    loop = EventLoop(data_handler, strategy, portfolio)
    loop.run()
"""
from decimal import Decimal
from typing import Optional

from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.indicators.technical import sma
from jutsu_engine.utils.logging_config import get_strategy_logger

logger = get_strategy_logger('SMA_CROSSOVER')


class SMA_Crossover(Strategy):
    """
    SMA Crossover trading strategy.

    Generates trading signals based on moving average crossovers.
    This is a classic trend-following strategy.

    Attributes:
        short_period: Period for short-term SMA
        long_period: Period for long-term SMA
        position_percent: Portfolio allocation percentage (0.0-1.0)
    """

    def __init__(
        self,
        short_period: int = 20,
        long_period: int = 50,
        position_percent: Decimal = Decimal('1.0'),
    ):
        """
        Initialize SMA Crossover strategy.

        Args:
            short_period: Short-term SMA period (default: 20)
            long_period: Long-term SMA period (default: 50)
            position_percent: Portfolio allocation percentage (default: Decimal('1.0'), i.e., 100%)
                            Valid range: 0.0 to 1.0
                            e.g., Decimal('0.8') for 80% allocation

        Example:
            strategy = SMA_Crossover(
                short_period=10,
                long_period=30,
                position_percent=Decimal('0.8')  # 80% allocation
            )
        """
        super().__init__()

        self.short_period = short_period
        self.long_period = long_period
        self.position_percent = position_percent

        # Track previous SMA values for crossover detection
        self._prev_short_sma: Optional[float] = None
        self._prev_long_sma: Optional[float] = None

        logger.info(
            f"SMA_Crossover initialized: "
            f"short={short_period}, long={long_period}, "
            f"allocation={position_percent * 100:.0f}%"
        )

    def init(self):
        """
        Initialize strategy (called before backtest starts).

        Can be used for loading data, setting up indicators, etc.
        """
        logger.info("Strategy initialized")

    def on_bar(self, bar: MarketDataEvent):
        """
        Process new market data bar and generate signals.

        Args:
            bar: Latest market data event

        Example:
            strategy.on_bar(market_data_event)
            signals = strategy.get_signals()
        """
        # Add bar to history
        self._bars.append(bar)
        symbol = bar.symbol

        # Need enough bars for long SMA
        if len(self._bars) < self.long_period:
            return

        # Calculate SMAs (filter by symbol for multi-symbol strategies)
        closes = self.get_closes(lookback=self.long_period, symbol=symbol)

        short_sma_series = sma(closes, period=self.short_period)
        long_sma_series = sma(closes, period=self.long_period)

        # Get current SMA values (most recent)
        current_short_sma = short_sma_series.iloc[-1]
        current_long_sma = long_sma_series.iloc[-1]

        # Check for NaN (insufficient data)
        if pd.isna(current_short_sma) or pd.isna(current_long_sma):
            return

        # Detect crossover
        if self._prev_short_sma is not None and self._prev_long_sma is not None:
            # Golden cross: short SMA crosses above long SMA
            if (self._prev_short_sma <= self._prev_long_sma and
                current_short_sma > current_long_sma):

                # Only buy if we don't have a position
                if not self.has_position(symbol):
                    logger.info(
                        f"GOLDEN CROSS: Short SMA ({current_short_sma:.2f}) "
                        f"crossed above Long SMA ({current_long_sma:.2f}) - "
                        f"Allocating {self.position_percent * 100:.0f}% of portfolio"
                    )
                    self.buy(symbol, self.position_percent)

            # Death cross: short SMA crosses below long SMA
            elif (self._prev_short_sma >= self._prev_long_sma and
                  current_short_sma < current_long_sma):

                # Only sell if we have a position
                if self.has_position(symbol):
                    logger.info(
                        f"DEATH CROSS: Short SMA ({current_short_sma:.2f}) "
                        f"crossed below Long SMA ({current_long_sma:.2f}) - "
                        f"Selling {self.position_percent * 100:.0f}% of portfolio"
                    )
                    self.sell(symbol, self.position_percent)

        # Update previous values for next bar
        self._prev_short_sma = current_short_sma
        self._prev_long_sma = current_long_sma

        # Debug logging
        logger.debug(
            f"{bar.timestamp.date()}: "
            f"Close=${bar.close:.2f}, "
            f"Short SMA={current_short_sma:.2f}, "
            f"Long SMA={current_long_sma:.2f}, "
            f"Position={self._positions.get(symbol, 0)}"
        )


# Import pandas for NaN check
import pandas as pd  # noqa: E402
