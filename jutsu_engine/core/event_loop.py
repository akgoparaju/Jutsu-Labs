"""
Event loop for backtesting engine.

Coordinates bar-by-bar execution of strategies with portfolio management.
Prevents lookback bias by processing data chronologically and ensuring
strategies only see past information.

Example:
    from jutsu_engine.core.event_loop import EventLoop

    event_loop = EventLoop(
        data_handler=db_handler,
        strategy=sma_strategy,
        portfolio=portfolio_simulator
    )

    event_loop.run()

    print(f"Portfolio value: ${portfolio.get_portfolio_value():,.2f}")
"""
from typing import List, Dict, Optional
from decimal import Decimal
from datetime import date

from jutsu_engine.data.handlers.base import DataHandler
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.portfolio.simulator import PortfolioSimulator
from jutsu_engine.core.events import (
    MarketDataEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
)
from jutsu_engine.utils.logging_config import get_engine_logger

logger = get_engine_logger()


class EventLoop:
    """
    Core backtesting event loop.

    Processes market data bars sequentially and coordinates all components:
    - Feeds bars to strategy
    - Collects signals from strategy
    - Converts signals to orders
    - Executes orders via portfolio
    - Updates portfolio values
    - Records all events

    This sequential processing prevents lookback bias.

    Attributes:
        data_handler: Source of historical market data
        strategy: Trading strategy to execute
        portfolio: Portfolio simulator for position/cash management
    """

    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        portfolio: PortfolioSimulator,
        trade_logger: Optional['TradeLogger'] = None,
    ):
        """
        Initialize event loop.

        Args:
            data_handler: DataHandler providing market data
            strategy: Strategy instance to execute
            portfolio: PortfolioSimulator for execution
            trade_logger: Optional TradeLogger for CSV export (default: None)

        Example:
            loop = EventLoop(
                data_handler=DatabaseDataHandler(...),
                strategy=SMA_Crossover(...),
                portfolio=PortfolioSimulator(...)
            )
        """
        self.data_handler = data_handler
        self.strategy = strategy
        self.portfolio = portfolio
        self.trade_logger = trade_logger

        # Inject TradeLogger into strategy for context logging
        if self.trade_logger:
            self.strategy._set_trade_logger(self.trade_logger)

        # Event tracking
        self.all_bars: List[MarketDataEvent] = []
        self.all_signals: List[SignalEvent] = []
        self.all_orders: List[OrderEvent] = []
        self.all_fills: List[FillEvent] = []

        # Current market data (symbol -> latest bar)
        self.current_bars: Dict[str, MarketDataEvent] = {}

        # Daily snapshot tracking (prevent duplicate snapshots per date)
        self._last_snapshot_date: Optional['date'] = None

        logger.info(
            f"EventLoop initialized with strategy: {strategy.name}"
        )

    def run(self):
        """
        Run the backtest event loop.

        Processes all bars from data_handler sequentially:
        1. Update portfolio market values
        2. Update strategy state (bar history and portfolio state)
        3. Feed bar to strategy
        4. Collect and process signals
        5. Execute orders
        6. Record portfolio value

        Example:
            loop = EventLoop(data_handler, strategy, portfolio)
            loop.run()

            fills = loop.all_fills
            signals = loop.all_signals
        """
        logger.info("Starting event loop...")

        bar_count = 0

        # Process each bar chronologically
        for bar in self.data_handler.get_next_bar():
            bar_count += 1

            # Increment trade logger bar counter
            if self.trade_logger:
                self.trade_logger.increment_bar()

            # Update current bars
            self.current_bars[bar.symbol] = bar
            self.all_bars.append(bar)

            # Step 1: Update portfolio market values
            self.portfolio.update_market_value(self.current_bars)

            # Step 2: Update strategy state (bar history and portfolio state)
            self.strategy._update_bar(bar)
            self.strategy._update_portfolio_state(
                self.portfolio.positions,
                self.portfolio.cash
            )

            # Step 3: Feed bar to strategy
            self.strategy.on_bar(bar)

            # Step 4: Collect signals from strategy
            signals = self.strategy.get_signals()
            self.all_signals.extend(signals)

            # Step 5: Process each signal
            for signal in signals:
                # NEW API: Execute signal directly (Portfolio handles position sizing)
                # Portfolio.execute_signal() calculates actual shares from portfolio_percent
                fill = self.portfolio.execute_signal(signal, bar)
                if fill:
                    self.all_fills.append(fill)

            # Step 6: Record portfolio value
            self.portfolio.record_portfolio_value(bar.timestamp)

            # Step 7: Record daily portfolio snapshot for CSV export (once per unique date)
            current_date = bar.timestamp.date()
            if current_date != self._last_snapshot_date:
                self.portfolio.record_daily_snapshot(bar.timestamp)
                self._last_snapshot_date = current_date

            # Periodic logging
            if bar_count % 100 == 0:
                value = self.portfolio.get_portfolio_value()
                logger.debug(
                    f"Processed {bar_count} bars, "
                    f"portfolio: ${value:,.2f}"
                )

        logger.info(
            f"Event loop completed: {bar_count} bars processed, "
            f"{len(self.all_signals)} signals, "
            f"{len(self.all_fills)} fills"
        )

        # Log final results
        final_value = self.portfolio.get_portfolio_value()
        return_pct = self.portfolio.get_total_return() * 100

        logger.info(
            f"Final portfolio value: ${final_value:,.2f} "
            f"(Return: {return_pct:+.2f}%)"
        )

    def _convert_signal_to_order(self, signal: SignalEvent) -> Optional[OrderEvent]:
        """
        Convert trading signal to order event.

        Args:
            signal: SignalEvent from strategy

        Returns:
            OrderEvent or None if signal is invalid

        Example:
            signal = SignalEvent(symbol='AAPL', signal_type='BUY', ...)
            order = loop._convert_signal_to_order(signal)
        """
        if signal.signal_type == 'HOLD':
            return None

        # Determine order direction
        if signal.signal_type == 'BUY':
            direction = 'BUY'
        elif signal.signal_type == 'SELL':
            direction = 'SELL'
        else:
            logger.warning(f"Unknown signal type: {signal.signal_type}")
            return None

        # Create order (market order by default)
        order = OrderEvent(
            symbol=signal.symbol,
            order_type='MARKET',  # Can be extended to support limit orders
            direction=direction,
            quantity=signal.quantity,
            timestamp=signal.timestamp,
            price=signal.price,  # Optional limit price
        )

        return order

    def get_results(self) -> Dict:
        """
        Get backtest results summary.

        Returns:
            Dictionary with event counts and portfolio state

        Example:
            results = loop.get_results()
            print(f"Total signals: {results['total_signals']}")
        """
        return {
            'total_bars': len(self.all_bars),
            'total_signals': len(self.all_signals),
            'total_orders': len(self.all_orders),
            'total_fills': len(self.all_fills),
            'final_value': self.portfolio.get_portfolio_value(),
            'total_return': self.portfolio.get_total_return(),
            'positions': dict(self.portfolio.positions),
            'cash': self.portfolio.cash,
        }
