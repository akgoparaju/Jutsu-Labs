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
from datetime import date, datetime, timezone

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
        regime_analyzer: Optional['RegimePerformanceAnalyzer'] = None,
        warmup_end_date: Optional[datetime] = None,
    ):
        """
        Initialize event loop.

        Args:
            data_handler: DataHandler providing market data
            strategy: Strategy instance to execute
            portfolio: PortfolioSimulator for execution
            trade_logger: Optional TradeLogger for CSV export (default: None)
            regime_analyzer: Optional RegimePerformanceAnalyzer for regime-specific analysis (default: None)
            warmup_end_date: End of warmup period (start of trading period).
                           If provided, bars before this date are warmup-only (no trades).

        Example:
            loop = EventLoop(
                data_handler=DatabaseDataHandler(...),
                strategy=SMA_Crossover(...),
                portfolio=PortfolioSimulator(...),
                warmup_end_date=datetime(2024, 1, 10, tzinfo=timezone.utc)
            )
        """
        self.data_handler = data_handler
        self.strategy = strategy
        self.portfolio = portfolio
        self.trade_logger = trade_logger
        self.regime_analyzer = regime_analyzer
        self.warmup_end_date = warmup_end_date

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
        self._previous_bar_timestamp: Optional[datetime] = None

        # Regime recording tracking (prevent duplicate records per date)
        # Records once per trading day when date changes (like Step 7 pattern)
        self._last_regime_record_date: Optional['date'] = None
        self._pending_regime_data: Optional[dict] = None

        # Indicator tracking for CSV export
        # Stores latest indicator values from strategy.get_current_indicators()
        self._pending_indicators: Optional[dict] = None

        logger.info(
            f"EventLoop initialized with strategy: {strategy.name}"
        )

    def _in_warmup_phase(self, current_date: datetime) -> bool:
        """
        Check if current bar is in warmup phase.

        Args:
            current_date: Timestamp of current bar

        Returns:
            bool: True if in warmup phase, False if in trading phase

        Notes:
            - Warmup phase: current_date < warmup_end_date
            - Trading phase: current_date >= warmup_end_date
            - If warmup_end_date is None, always in trading phase
            - Defensive timezone normalization ensures comparison compatibility
        """
        if self.warmup_end_date is None:
            return False
        
        # Defensive timezone normalization (prevents offset-naive vs offset-aware comparison errors)
        # Database timestamps may be offset-naive, warmup_end_date is timezone-aware
        current_date_normalized = current_date
        if current_date.tzinfo is None:
            current_date_normalized = current_date.replace(tzinfo=timezone.utc)
        
        warmup_end_normalized = self.warmup_end_date
        if self.warmup_end_date.tzinfo is None:
            warmup_end_normalized = self.warmup_end_date.replace(tzinfo=timezone.utc)
        
        return current_date_normalized < warmup_end_normalized

    def run(self):
        """
        Run the backtest event loop.

        Processes all bars from data_handler sequentially:
        1. Update portfolio market values
        2. Update strategy state (bar history and portfolio state)
        3. Feed bar to strategy
        4. Collect and process signals
        5. Execute orders (skipped during warmup phase)
        6. Record portfolio value

        Warmup Phase Behavior:
            - If warmup_end_date is set, bars before this date are warmup-only
            - Strategy.on_bar() is still called (to compute indicators)
            - SignalEvents are collected but NOT processed (no trades)
            - Portfolio state is updated with market values only

        Example:
            loop = EventLoop(data_handler, strategy, portfolio)
            loop.run()

            fills = loop.all_fills
            signals = loop.all_signals
        """
        logger.info("Starting event loop...")

        if self.warmup_end_date:
            logger.info(f"Warmup period enabled: bars before {self.warmup_end_date} will not execute trades")

        bar_count = 0
        warmup_bar_count = 0
        trading_bar_count = 0

        # Process each bar chronologically
        for bar in self.data_handler.get_next_bar():
            bar_count += 1

            # Increment trade logger bar counter
            if self.trade_logger:
                self.trade_logger.increment_bar()

            # Update current bars
            self.current_bars[bar.symbol] = bar
            self.all_bars.append(bar)

            # CRITICAL FIX: Record daily snapshot BEFORE updating market values
            # When date changes, we must capture portfolio value using PREVIOUS day's prices
            # before update_market_value() overwrites _latest_prices with new day's data.
            # Without this fix, snapshots for day N incorrectly use day N+1's prices,
            # causing a 1-day forward shift that breaks beta/correlation calculations.
            current_date = bar.timestamp.date()
            if self._last_snapshot_date is not None and current_date != self._last_snapshot_date:
                # All bars for previous date are now processed
                # Record snapshot NOW while portfolio still has previous day's prices
                self.portfolio.record_daily_snapshot(
                    self._previous_bar_timestamp,
                    indicators=self._pending_indicators
                )

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

            # Step 3.5: Capture indicator values for CSV export
            # Must happen AFTER on_bar() when indicators are computed
            if hasattr(self.strategy, 'get_current_indicators'):
                self._pending_indicators = self.strategy.get_current_indicators()

            # Step 4: Collect signals from strategy
            signals = self.strategy.get_signals()
            self.all_signals.extend(signals)

            # Check if we're in warmup phase
            in_warmup = self._in_warmup_phase(bar.timestamp)

            if in_warmup:
                warmup_bar_count += 1
                if signals:
                    logger.debug(f"Warmup phase: {bar.timestamp}, ignoring {len(signals)} signal(s)")
            else:
                trading_bar_count += 1

                # Log transition from warmup to trading (only once)
                if self.warmup_end_date and warmup_bar_count > 0 and trading_bar_count == 1:
                    logger.info(f"Warmup complete. Processed {warmup_bar_count} warmup bars. Starting trading period.")

                # Step 5: Process each signal (only during trading phase)
                for signal in signals:
                    # NEW API: Execute signal directly (Portfolio handles position sizing)
                    # Portfolio.execute_signal() calculates actual shares from portfolio_percent
                    fill = self.portfolio.execute_signal(signal, bar)
                    if fill:
                        self.all_fills.append(fill)

            # Step 6: Record portfolio value (only during trading phase to match baseline period)
            if not in_warmup:
                self.portfolio.record_portfolio_value(bar.timestamp)

            # Step 6.5: Record regime performance (if analyzer available and strategy supports it)
            # FIX: Record ONCE per trading day (on date change), not per bar
            # This prevents duplicate rows when processing multiple symbols per day
            if self.regime_analyzer and hasattr(self.strategy, 'get_current_regime'):
                # Get current regime from strategy
                trend_state, vol_state, cell_id = self.strategy.get_current_regime()

                # Get QQQ close price (strategy's signal_symbol)
                signal_symbol = getattr(self.strategy, 'signal_symbol', 'QQQ')
                qqq_bar = self.current_bars.get(signal_symbol)

                if qqq_bar:
                    regime_date = bar.timestamp.date()

                    # When date changes, record the PREVIOUS day's regime data
                    # This ensures we capture final portfolio value after all trades
                    if (self._last_regime_record_date is not None and
                            regime_date != self._last_regime_record_date and
                            self._pending_regime_data is not None):
                        self.regime_analyzer.record_bar(**self._pending_regime_data)

                    # Store current data as pending (will be recorded on next date change)
                    self._pending_regime_data = {
                        'timestamp': bar.timestamp,
                        'regime_cell': cell_id,
                        'trend_state': trend_state,
                        'vol_state': vol_state,
                        'qqq_close': qqq_bar.close,
                        'portfolio_value': self.portfolio.get_portfolio_value()
                    }
                    self._last_regime_record_date = regime_date

            # Step 7: Update daily snapshot tracking variables
            # NOTE: Actual snapshot recording was moved earlier in the loop (before update_market_value)
            # to ensure snapshots use the correct day's closing prices, not the next day's prices.
            # We only update tracking variables here.
            self._last_snapshot_date = current_date
            self._previous_bar_timestamp = bar.timestamp  # Track for next date change

            # Periodic logging
            if bar_count % 100 == 0:
                value = self.portfolio.get_portfolio_value()
                logger.debug(
                    f"Processed {bar_count} bars, "
                    f"portfolio: ${value:,.2f}"
                )

        # Record final daily snapshot (for the last date in the dataset)
        if self._previous_bar_timestamp is not None:
            self.portfolio.record_daily_snapshot(
                self._previous_bar_timestamp,
                indicators=self._pending_indicators
            )

        # Record final regime data (for the last date in the dataset)
        if self.regime_analyzer and self._pending_regime_data is not None:
            self.regime_analyzer.record_bar(**self._pending_regime_data)

        # Log summary with warmup stats
        if self.warmup_end_date:
            logger.info(
                f"Event loop completed: {bar_count} total bars processed "
                f"({warmup_bar_count} warmup, {trading_bar_count} trading), "
                f"{len(self.all_signals)} signals, "
                f"{len(self.all_fills)} fills"
            )
        else:
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
