"""
Portfolio simulator for backtesting.

Manages positions, cash, and order execution during backtest simulations.
Tracks portfolio value and generates fill events.

Example:
    from jutsu_engine.portfolio.simulator import PortfolioSimulator
    from decimal import Decimal

    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    # Execute a market buy order
    order = OrderEvent(...)
    fill = portfolio.execute_order(order, current_bar)

    # Check portfolio state
    print(f"Cash: ${portfolio.cash}")
    print(f"Portfolio Value: ${portfolio.get_portfolio_value()}")
"""
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime

from jutsu_engine.core.events import OrderEvent, FillEvent, MarketDataEvent
from jutsu_engine.utils.logging_config import get_portfolio_logger

logger = get_portfolio_logger()

# Short selling margin requirement (150% of short value per regulatory standards)
SHORT_MARGIN_REQUIREMENT = Decimal('1.5')


class PortfolioSimulator:
    """
    Simulates portfolio management during backtesting.

    Tracks cash, positions, and executes orders with realistic costs.
    Maintains portfolio value history for performance analysis.

    Attributes:
        initial_capital: Starting cash amount
        cash: Current available cash
        positions: Dict[symbol, quantity] (negative for short positions)
        fills: List of all fill events
        current_holdings: Dict[symbol, market_value]
        portfolio_value_history: List of (timestamp, value) tuples
    """

    def __init__(
        self,
        initial_capital: Decimal,
        commission_per_share: Decimal = Decimal('0.01'),
        slippage_percent: Decimal = Decimal('0.001'),
        trade_logger: Optional['TradeLogger'] = None,
    ):
        """
        Initialize portfolio simulator.

        Args:
            initial_capital: Starting cash amount
            commission_per_share: Commission cost per share (default: $0.01)
            slippage_percent: Slippage as percentage of price (default: 0.1%)
            trade_logger: Optional TradeLogger for CSV export (default: None)

        Example:
            portfolio = PortfolioSimulator(
                initial_capital=Decimal('100000'),
                commission_per_share=Decimal('0.01'),
                slippage_percent=Decimal('0.001')
            )
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_per_share = commission_per_share
        self.slippage_percent = slippage_percent

        # Position tracking
        self.positions: Dict[str, int] = {}  # symbol -> quantity
        self.current_holdings: Dict[str, Decimal] = {}  # symbol -> market_value

        # Event history
        self.fills: List[FillEvent] = []
        self.portfolio_value_history: List[tuple[datetime, Decimal]] = []

        # Daily portfolio snapshots for CSV export
        self.daily_snapshots: List[Dict] = []

        # Latest prices for each symbol
        self._latest_prices: Dict[str, Decimal] = {}

        # Trade logger (optional)
        self._trade_logger = trade_logger

        # Execution timing context (optional, for intraday fill pricing)
        self._execution_time: Optional[str] = None
        self._end_date: Optional[datetime] = None
        self._data_handler = None

        logger.info(
            f"Portfolio initialized with ${initial_capital:,.2f}, "
            f"commission: ${commission_per_share}/share, "
            f"slippage: {slippage_percent*100}%"
        )

    def _validate_order(
        self,
        order: OrderEvent,
        fill_price: Decimal,
        commission: Decimal,
        total_cost: Decimal
    ) -> tuple[bool, str]:
        """
        Validate order against realistic trading constraints.

        Checks:
        1. Cash constraint for buys
        2. Collateral requirement for short sales
        3. Share ownership for sells
        4. Prevents simultaneous long/short positions
        5. Enforces position transition rules

        Args:
            order: OrderEvent to validate
            fill_price: Calculated fill price
            commission: Order commission
            total_cost: Total cost for buy orders

        Returns:
            (is_valid, rejection_reason) tuple
        """
        symbol = order.symbol
        quantity = order.quantity
        direction = order.direction

        current_position = self.positions.get(symbol, 0)

        # Determine current and target position directions
        if current_position == 0:
            current_dir = 'FLAT'
        elif current_position > 0:
            current_dir = 'LONG'
        else:
            current_dir = 'SHORT'

        # Calculate target position after this order
        if direction == 'BUY':
            target_position = current_position + quantity
        else:  # SELL
            target_position = current_position - quantity

        # Determine target direction
        if target_position == 0:
            target_dir = 'FLAT'
        elif target_position > 0:
            target_dir = 'LONG'
        else:
            target_dir = 'SHORT'

        # === VALIDATION RULES ===

        # Rule 1: BUY orders - cash constraint
        if direction == 'BUY':
            if total_cost > self.cash:
                return False, (
                    f"Insufficient cash for BUY: "
                    f"Need ${total_cost:,.2f}, have ${self.cash:,.2f}"
                )

        # Rule 2: Prevent illegal LONG → SHORT transition
        if current_dir == 'LONG' and target_dir == 'SHORT':
            return False, (
                f"Cannot transition from LONG to SHORT directly: "
                f"Current position {current_position}, order would result in {target_position}. "
                f"Must close long position first (sell {current_position} shares), "
                f"then open short position separately."
            )

        # Rule 3: Prevent illegal SHORT → LONG transition
        if current_dir == 'SHORT' and target_dir == 'LONG':
            return False, (
                f"Cannot transition from SHORT to LONG directly: "
                f"Current position {current_position}, order would result in {target_position}. "
                f"Must cover short position first (buy {abs(current_position)} shares), "
                f"then open long position separately."
            )

        # Rule 4: SELL orders when LONG - ownership check
        if direction == 'SELL' and current_dir == 'LONG':
            if quantity > current_position:
                return False, (
                    f"Cannot sell more shares than owned: "
                    f"Have {current_position} shares, trying to sell {quantity}"
                )

        # Rule 5: SELL orders when FLAT - short selling collateral check
        if direction == 'SELL' and current_dir == 'FLAT':
            # This is a short sale, need collateral
            short_value = fill_price * quantity
            margin_required = short_value * SHORT_MARGIN_REQUIREMENT
            collateral_needed = margin_required + commission

            if collateral_needed > self.cash:
                return False, (
                    f"Insufficient collateral for short sale: "
                    f"Need ${collateral_needed:,.2f} "
                    f"(${margin_required:,.2f} margin + ${commission:.2f} commission), "
                    f"have ${self.cash:,.2f}"
                )

        # Rule 6: SELL orders when SHORT - additional short collateral check
        if direction == 'SELL' and current_dir == 'SHORT':
            # Increasing short position, need more collateral
            short_value = fill_price * quantity
            margin_required = short_value * SHORT_MARGIN_REQUIREMENT
            collateral_needed = margin_required + commission

            if collateral_needed > self.cash:
                return False, (
                    f"Insufficient collateral for additional short: "
                    f"Need ${collateral_needed:,.2f} "
                    f"(${margin_required:,.2f} margin + ${commission:.2f} commission), "
                    f"have ${self.cash:,.2f}"
                )

        # All checks passed
        return True, ""

    def execute_signal(
        self,
        signal: 'SignalEvent',
        current_bar: MarketDataEvent
    ) -> Optional[FillEvent]:
        """
        Convert signal with portfolio % to actual shares and execute.

        This method implements the position sizing logic that converts a
        portfolio percentage allocation to an actual number of shares,
        accounting for long/short position requirements and margin.

        Args:
            signal: SignalEvent with portfolio_percent (0.0 to 1.0)
            current_bar: Current market data for pricing

        Returns:
            FillEvent if executed successfully, None if rejected

        Process:
            1. Calculate portfolio value (cash + holdings)
            2. Calculate allocation amount (portfolio_value * portfolio_percent)
            3. Convert to shares (long vs short logic with margin)
            4. Create OrderEvent with calculated quantity
            5. Execute order using existing execute_order()

        Example:
            # Strategy generates signal for 80% portfolio allocation
            signal = SignalEvent(
                symbol='AAPL',
                signal_type='BUY',
                timestamp=current_bar.timestamp,
                quantity=0,  # Ignored, calculated from portfolio_percent
                portfolio_percent=Decimal('0.80')  # 80% allocation
            )
            fill = portfolio.execute_signal(signal, current_bar)
        """
        from jutsu_engine.core.events import SignalEvent, OrderEvent

        # Capture state BEFORE trade (for trade logger)
        # NOTE: EventLoop already updated all prices via update_market_value() before calling this method.
        # We capture "before" state here using those already-updated prices.
        portfolio_value_before = self.get_portfolio_value()
        cash_before = self.cash
        allocation_before = self._calculate_allocation_percentages() if self._trade_logger else {}

        # Calculate portfolio value (using prices already set by EventLoop.update_market_value())
        # DO NOT update _latest_prices here - EventLoop is responsible for price updates
        portfolio_value = self.get_portfolio_value()

        # Calculate allocation amount
        allocation_amount = portfolio_value * signal.portfolio_percent

        # DEBUG logging
        logger.info(
            f"Position sizing: portfolio_value=${portfolio_value:,.2f}, "
            f"allocation%={signal.portfolio_percent*100:.1f}%, "
            f"allocation_amount=${allocation_amount:,.2f}"
        )

        # Use price already set by EventLoop.update_market_value()
        # NOTE: EventLoop updated _latest_prices for ALL symbols before calling this method
        # Fallback to current_bar.close for direct usage (tests, manual execution)
        price = self._latest_prices.get(signal.symbol, current_bar.close)

        # Log if using fallback (indicates potential symbol mismatch)
        if signal.symbol not in self._latest_prices:
            logger.debug(
                f"Using fallback price from current_bar for {signal.symbol} "
                f"(current_bar.symbol={current_bar.symbol}). "
                f"This is expected for direct portfolio usage but NOT in EventLoop context."
            )

        # Get current position for rebalancing logic
        current_position = self.positions.get(signal.symbol, 0)

        # Special case: 0% allocation means "close position"
        if signal.portfolio_percent == Decimal('0.0'):
            if current_position == 0:
                logger.debug(f"0% allocation for {signal.symbol} with no position, skipping")
                return None

            # Close existing position
            quantity = abs(current_position)
            # Determine direction: close long = SELL, close short = BUY
            close_direction = 'SELL' if current_position > 0 else 'BUY'

            logger.info(
                f"Closing position: {close_direction} {quantity} {signal.symbol} "
                f"(current position: {current_position})"
            )

            # Create order to close position
            order = OrderEvent(
                symbol=signal.symbol,
                order_type='MARKET',
                direction=close_direction,
                quantity=quantity,
                timestamp=signal.timestamp,
                price=None
            )

            fill = self.execute_order(order, current_bar)

            # Log trade execution (close position)
            if fill and self._trade_logger:
                portfolio_value_after = self.get_portfolio_value()
                cash_after = self.cash
                allocation_after = self._calculate_allocation_percentages()

                self._trade_logger.log_trade_execution(
                    fill=fill,
                    portfolio_value_before=portfolio_value_before,
                    portfolio_value_after=portfolio_value_after,
                    cash_before=cash_before,
                    cash_after=cash_after,
                    allocation_before=allocation_before,
                    allocation_after=allocation_after
                )

            return fill

        # REBALANCING LOGIC: Check if we have an existing position
        # If yes, calculate delta between target and current allocation
        if current_position != 0:
            # Calculate current position value and allocation percentage
            position_value = Decimal(str(abs(current_position))) * price
            current_allocation_pct = position_value / portfolio_value

            # Calculate delta between target and current allocation
            delta_pct = signal.portfolio_percent - current_allocation_pct

            # Calculate shares to adjust (positive = buy more, negative = sell some)
            delta_amount = portfolio_value * delta_pct

            # Account for slippage and commission in share calculation
            # Cash-constrained position sizing fix
            if delta_pct > 0:
                # BUY operation: include slippage and commission in cost per share
                # Slippage is applied in execute_order(): BUY at price × (1 + slippage)
                slippage_adjusted_price = price * (Decimal('1') + self.slippage_percent)
                cost_per_share = slippage_adjusted_price + self.commission_per_share

                # ROOT CAUSE: delta_amount calculated from total portfolio value (cash + illiquid positions)
                # but execution can only spend actual cash. In multi-position rebalancing, remaining
                # positions are illiquid and cannot be spent like cash.
                # SOLUTION: Limit BUY to available cash. Accepts small allocation drift for zero errors.
                affordable_amount = min(delta_amount, self.cash)
                delta_shares = int(affordable_amount / cost_per_share)

                logger.debug(
                    f"CASH-CONSTRAINED BUY: delta_amount=${delta_amount:.2f}, "
                    f"available_cash=${self.cash:.2f}, affordable=${affordable_amount:.2f}, "
                    f"delta_shares={delta_shares}"
                )
            else:
                # SELL operation: include slippage (we sell at lower price)
                # Slippage is applied in execute_order(): SELL at price × (1 - slippage)
                slippage_adjusted_price = price * (Decimal('1') - self.slippage_percent)
                delta_shares = int(delta_amount / slippage_adjusted_price)

            logger.info(
                f"Rebalancing {signal.symbol}: current={current_allocation_pct*100:.2f}%, "
                f"target={signal.portfolio_percent*100:.2f}%, "
                f"delta={delta_pct*100:+.2f}% ({delta_shares:+d} shares)"
            )

            # If delta is negligible (within rebalance threshold), skip
            # Using 1 share as minimum threshold to avoid tiny rebalances
            if abs(delta_shares) < 1:
                logger.debug(
                    f"Delta too small ({delta_shares} shares), skipping rebalance for {signal.symbol}"
                )
                return None

            # Determine direction based on delta
            if delta_shares > 0:
                # Need to BUY more shares (increase position)
                rebalance_direction = 'BUY'
                rebalance_quantity = delta_shares
            else:
                # Need to SELL shares (reduce position)
                rebalance_direction = 'SELL'
                rebalance_quantity = abs(delta_shares)

            # Create rebalancing order
            order = OrderEvent(
                symbol=signal.symbol,
                order_type='MARKET',
                direction=rebalance_direction,
                quantity=rebalance_quantity,
                timestamp=signal.timestamp,
                price=None
            )

            fill = self.execute_order(order, current_bar)

            # Log trade execution (rebalance)
            if fill and self._trade_logger:
                portfolio_value_after = self.get_portfolio_value()
                cash_after = self.cash
                allocation_after = self._calculate_allocation_percentages()

                self._trade_logger.log_trade_execution(
                    fill=fill,
                    portfolio_value_before=portfolio_value_before,
                    portfolio_value_after=portfolio_value_after,
                    cash_before=cash_before,
                    cash_after=cash_after,
                    allocation_before=allocation_before,
                    allocation_after=allocation_after
                )

            return fill

        # NEW POSITION LOGIC: No existing position, treat as new allocation
        # Calculate shares based on signal type (normal allocation)
        if signal.signal_type == 'BUY':
            # Long position calculation
            quantity = self._calculate_long_shares(
                allocation_amount,
                price,
                risk_per_share=signal.risk_per_share
            )
        elif signal.signal_type == 'SELL':
            # Short position calculation
            quantity = self._calculate_short_shares(
                allocation_amount,
                price,
                risk_per_share=signal.risk_per_share
            )
        else:  # HOLD
            logger.debug(f"HOLD signal for {signal.symbol}, skipping execution")
            return None

        if quantity <= 0:
            logger.warning(
                f"Insufficient allocation for {signal.signal_type} {signal.symbol}: "
                f"${allocation_amount:,.2f} @ ${price:.2f} = {quantity} shares"
            )
            return None

        # Create OrderEvent with calculated quantity
        order = OrderEvent(
            symbol=signal.symbol,
            order_type='MARKET',
            direction=signal.signal_type,  # 'BUY' or 'SELL'
            quantity=quantity,
            timestamp=signal.timestamp,
            price=None  # Market order
        )

        # Execute order using existing logic
        logger.debug(
            f"Executing signal: {signal.signal_type} {quantity} {signal.symbol} "
            f"({signal.portfolio_percent*100:.1f}% allocation = ${allocation_amount:,.2f})"
        )

        fill = self.execute_order(order, current_bar)

        # Log trade execution (if logger provided and fill succeeded)
        if fill and self._trade_logger:
            portfolio_value_after = self.get_portfolio_value()
            cash_after = self.cash
            allocation_after = self._calculate_allocation_percentages()

            self._trade_logger.log_trade_execution(
                fill=fill,
                portfolio_value_before=portfolio_value_before,
                portfolio_value_after=portfolio_value_after,
                cash_before=cash_before,
                cash_after=cash_after,
                allocation_before=allocation_before,
                allocation_after=allocation_after
            )

        return fill

    def _calculate_long_shares(
        self,
        allocation_amount: Decimal,
        price: Decimal,
        risk_per_share: Optional[Decimal] = None
    ) -> int:
        """
        Calculate maximum shares for long position.

        Supports two position sizing modes:
        1. ATR-based sizing (when risk_per_share provided)
        2. Percentage-based sizing (when risk_per_share is None)

        Args:
            allocation_amount: Dollar amount to allocate
            price: Current share price
            risk_per_share: Optional ATR-based risk per share

        Returns:
            Maximum affordable shares for long purchase

        Formula (ATR-based, when risk_per_share provided):
            shares = min(allocation_amount, self.cash) / risk_per_share

        Formula (Percentage-based, when risk_per_share is None):
            shares = min(allocation_amount, self.cash) / (price + commission_per_share)

        Example (ATR-based):
            allocation = Decimal('1500')   # Dollar risk
            risk_per_share = Decimal('5.00')  # ATR * stop_multiplier
            # Result: 1500 / 5.00 = 300 shares

        Example (Percentage-based):
            allocation = Decimal('80000')  # $80,000
            price = Decimal('150.00')      # $150 per share
            commission = Decimal('0.01')   # $0.01 per share
            # Result: 80000 / 150.01 = 533 shares
        """
        # CASH-CONSTRAINED FIX: Limit to available cash
        # ROOT CAUSE: allocation_amount calculated from total portfolio value (cash + illiquid positions)
        # but execution can only spend actual cash. In multi-position strategies, remaining
        # positions are illiquid and cannot be spent like cash.
        # SOLUTION: Use min(allocation_amount, self.cash) for share calculation.
        affordable_amount = min(allocation_amount, self.cash)

        if risk_per_share is not None:
            # ATR-based position sizing
            if risk_per_share <= 0:
                logger.error(f"Invalid risk_per_share: {risk_per_share}")
                return 0

            shares = affordable_amount / risk_per_share
            shares_int = int(shares)

            logger.debug(
                f"ATR-based long sizing: ${affordable_amount:,.2f} / "
                f"${risk_per_share:.2f} risk/share = {shares_int} shares "
                f"(allocation=${allocation_amount:,.2f}, cash=${self.cash:,.2f})"
            )
        else:
            # Percentage-based position sizing (legacy)
            # Account for slippage and commission (fix for "Insufficient cash" issue)
            # Slippage is applied in execute_order(): BUY at price × (1 + slippage)
            slippage_adjusted_price = price * (Decimal('1') + self.slippage_percent)
            cost_per_share = slippage_adjusted_price + self.commission_per_share

            if cost_per_share <= 0:
                logger.error(f"Invalid cost per share: {cost_per_share}")
                return 0

            shares = affordable_amount / cost_per_share
            shares_int = int(shares)

            logger.debug(
                f"Percentage-based long sizing: ${affordable_amount:,.2f} / "
                f"${cost_per_share:.2f} = {shares_int} shares "
                f"(allocation=${allocation_amount:,.2f}, cash=${self.cash:,.2f})"
            )

        return shares_int

    def _calculate_short_shares(
        self,
        allocation_amount: Decimal,
        price: Decimal,
        risk_per_share: Optional[Decimal] = None
    ) -> int:
        """
        Calculate maximum shares for short position.

        Supports two position sizing modes:
        1. ATR-based sizing (when risk_per_share provided)
        2. Percentage-based sizing with margin (when risk_per_share is None)

        Args:
            allocation_amount: Dollar amount to allocate
            price: Current share price
            risk_per_share: Optional ATR-based risk per share

        Returns:
            Maximum affordable shares for short sale

        Formula (ATR-based, when risk_per_share provided):
            shares = allocation_amount / risk_per_share

        Formula (Percentage-based, when risk_per_share is None):
            shares = allocation_amount / (price * 1.5 + commission_per_share)

        Note:
            SHORT_MARGIN_REQUIREMENT = 1.5 (150% margin per Regulation T)
            This ensures sufficient collateral is reserved for the short position.

        Example (ATR-based):
            allocation = Decimal('1500')   # Dollar risk
            risk_per_share = Decimal('5.00')  # ATR * stop_multiplier
            # Result: 1500 / 5.00 = 300 shares

        Example (Percentage-based):
            allocation = Decimal('80000')  # $80,000
            price = Decimal('150.00')      # $150 per share
            margin_req = 1.5               # 150% Regulation T margin
            commission = Decimal('0.01')   # $0.01 per share
            # Cost per share: 150 * 1.5 + 0.01 = $225.01
            # Result: 80000 / 225.01 = 355 shares
        """
        if risk_per_share is not None:
            # ATR-based position sizing
            if risk_per_share <= 0:
                logger.error(f"Invalid risk_per_share: {risk_per_share}")
                return 0

            shares = allocation_amount / risk_per_share
            shares_int = int(shares)

            logger.debug(
                f"ATR-based short sizing: ${allocation_amount:,.2f} / "
                f"${risk_per_share:.2f} risk/share = {shares_int} shares"
            )
        else:
            # Percentage-based position sizing with margin (legacy)
            # Account for slippage and commission (fix for "Insufficient cash" issue)
            # Slippage is applied in execute_order(): SELL at price × (1 - slippage)
            slippage_adjusted_price = price * (Decimal('1') - self.slippage_percent)
            # Calculate collateral needed per share (price * margin + commission)
            collateral_per_share = (slippage_adjusted_price * SHORT_MARGIN_REQUIREMENT) + self.commission_per_share

            if collateral_per_share <= 0:
                logger.error(f"Invalid collateral per share: {collateral_per_share}")
                return 0

            shares = allocation_amount / collateral_per_share
            shares_int = int(shares)

            logger.debug(
                f"Percentage-based short sizing: ${allocation_amount:,.2f} / "
                f"${collateral_per_share:.2f} = {shares_int} shares "
                f"(margin requirement: {SHORT_MARGIN_REQUIREMENT}x)"
            )

        return shares_int

    def set_execution_context(
        self,
        execution_time: str,
        end_date: datetime,
        data_handler
    ) -> None:
        """
        Set execution timing context for intraday fill pricing.

        Enables portfolio to use intraday prices for fills on the last day
        of backtest when execution_time is not "close".

        Args:
            execution_time: Execution time ("open", "15min_after_open", "15min_before_close", "close")
            end_date: Last date of backtest (used to detect last trading day)
            data_handler: Data handler with get_intraday_bars_for_time_window() method

        Example:
            portfolio.set_execution_context(
                execution_time="15min_after_open",
                end_date=datetime(2025, 11, 24),
                data_handler=data_handler
            )
        """
        self._execution_time = execution_time
        self._end_date = end_date
        self._data_handler = data_handler
        logger.info(f"Execution context set: execution_time={execution_time}, end_date={end_date.date()}")

    def _should_use_intraday_price(self, current_bar: MarketDataEvent) -> bool:
        """
        Check if intraday fill price should be used instead of EOD close.

        Returns True only if:
        1. Execution context has been injected (execution_time, end_date, data_handler)
        2. execution_time is not "close"
        3. Current bar is on the last trading day

        Args:
            current_bar: Current market data bar

        Returns:
            True if intraday price should be used, False for EOD close
        """
        # No injection = use EOD close (backward compatible)
        if self._execution_time is None or self._end_date is None or self._data_handler is None:
            return False

        # execution_time="close" = use EOD close (standard behavior)
        if self._execution_time == "close":
            return False

        # Check if today is last trading day
        is_last_day = current_bar.timestamp.date() == self._end_date.date()

        return is_last_day

    def _get_intraday_fill_price(self, symbol: str, current_bar: MarketDataEvent) -> Decimal:
        """
        Fetch intraday fill price based on execution_time.

        Fetches 5-minute intraday bar at execution_time and returns close price.
        Falls back to EOD close if intraday data is unavailable.

        Args:
            symbol: Symbol to fetch price for
            current_bar: Current EOD bar (used for fallback)

        Returns:
            Intraday close price at execution_time, or EOD close as fallback

        Example:
            # execution_time="15min_after_open" → fetch 9:45 AM bar
            price = portfolio._get_intraday_fill_price("QQQ", current_bar)
        """
        from datetime import time

        # Map execution_time to time objects
        execution_times = {
            "open": time(9, 30),
            "15min_after_open": time(9, 45),
            "15min_before_close": time(15, 45),
            "close": time(16, 0),
        }

        target_time = execution_times[self._execution_time]

        try:
            # Fetch intraday bar at target time
            intraday_bars = self._data_handler.get_intraday_bars_for_time_window(
                symbol=symbol,
                date=current_bar.timestamp.date(),
                start_time=target_time,
                end_time=target_time,
                interval='5m'
            )

            if intraday_bars and len(intraday_bars) > 0:
                intraday_price = intraday_bars[0].close
                logger.debug(
                    f"Using intraday fill price for {symbol}: ${intraday_price:.2f} "
                    f"at {target_time} (last day execution timing)"
                )
                return intraday_price
            else:
                logger.warning(
                    f"No intraday data for {symbol} at {target_time}, "
                    f"falling back to EOD close: ${current_bar.close:.2f}"
                )
                return current_bar.close

        except Exception as e:
            logger.error(
                f"Error fetching intraday price for {symbol} at {target_time}: {e}. "
                f"Falling back to EOD close: ${current_bar.close:.2f}"
            )
            return current_bar.close

    def execute_order(
        self,
        order: OrderEvent,
        current_bar: MarketDataEvent
    ) -> Optional[FillEvent]:
        """
        Execute an order and return fill event.

        Calculates fill price, applies costs (commission, slippage),
        updates cash and positions, and returns fill event.

        Args:
            order: OrderEvent to execute
            current_bar: Current market data for price reference

        Returns:
            FillEvent if order executed successfully, None if rejected

        Example:
            order = OrderEvent(
                symbol='AAPL',
                order_type='MARKET',
                direction='BUY',
                quantity=100,
                timestamp=current_bar.timestamp
            )
            fill = portfolio.execute_order(order, current_bar)
        """
        symbol = order.symbol
        quantity = order.quantity
        direction = order.direction
        order_type = order.order_type

        # Determine fill price
        if order_type == 'MARKET':
            # Check if we should use intraday price (last day execution timing)
            if self._should_use_intraday_price(current_bar):
                fill_price = self._get_intraday_fill_price(symbol, current_bar)
            else:
                # Use price already set by EventLoop.update_market_value()
                # NOTE: _latest_prices contains correct close price for this symbol
                # Fallback to current_bar.close for direct usage (tests, manual execution)
                fill_price = self._latest_prices.get(symbol, current_bar.close)

                # Log if using fallback (indicates potential symbol mismatch)
                if symbol not in self._latest_prices:
                    logger.debug(
                        f"Using fallback price from current_bar for {symbol} "
                        f"(current_bar.symbol={current_bar.symbol}). "
                        f"This is expected for direct portfolio usage but NOT in EventLoop context."
                    )

            # Apply slippage (disadvantageous to trader)
            if direction == 'BUY':
                fill_price = fill_price * (Decimal('1') + self.slippage_percent)
            else:  # SELL
                fill_price = fill_price * (Decimal('1') - self.slippage_percent)

        elif order_type == 'LIMIT':
            # LIMITATION: Limit orders require high/low prices from the correct symbol's bar
            # EventLoop currently passes the "current" bar, not the order's symbol bar
            # For now, validate that we have the correct bar
            if current_bar.symbol != symbol:
                logger.error(
                    f"Cannot execute limit order for {symbol}: "
                    f"received bar for {current_bar.symbol} instead. "
                    f"This is a known limitation requiring EventLoop changes."
                )
                return None

            # Limit order only fills if price is favorable
            limit_price = order.price

            if direction == 'BUY' and current_bar.low <= limit_price:
                fill_price = limit_price
            elif direction == 'SELL' and current_bar.high >= limit_price:
                fill_price = limit_price
            else:
                # Limit order not filled
                logger.debug(
                    f"Limit order not filled: {symbol} {direction} @ {limit_price}"
                )
                return None
        else:
            logger.warning(f"Unknown order type: {order_type}")
            return None

        # Calculate costs
        commission = self.commission_per_share * quantity
        total_cost = (fill_price * quantity) + commission

        # Validate order against realistic trading constraints
        is_valid, rejection_reason = self._validate_order(
            order, fill_price, commission, total_cost
        )

        if not is_valid:
            logger.warning(f"Order rejected: {rejection_reason}")
            return None

        # Update cash and positions BEFORE creating fill event
        # We need current_position to determine cash handling for SELL/BUY orders
        current_position = self.positions.get(symbol, 0)

        if direction == 'BUY':
            if current_position >= 0:
                # Opening or adding to long position - PAY for shares
                self.cash -= total_cost
            else:
                # Covering short position - PAY to buy back + RELEASE margin
                # Cost to buy back shares
                self.cash -= total_cost
                # Release margin that was locked up (150% of original short value)
                # Note: We release margin based on CURRENT price, not original short price
                margin_to_release = fill_price * quantity * SHORT_MARGIN_REQUIREMENT
                self.cash += margin_to_release
        else:  # SELL
            # SELL order handling depends on current position
            if current_position > 0:
                # Closing or reducing long position - RECEIVE proceeds from sale
                self.cash += (fill_price * quantity) - commission
            else:
                # Opening or adding to short position - LOCK UP margin
                # We need 150% of short value as collateral per Regulation T
                margin_required = fill_price * quantity * SHORT_MARGIN_REQUIREMENT
                self.cash -= (margin_required + commission)

        # Update positions
        if direction == 'BUY':
            self.positions[symbol] = current_position + quantity
        else:  # SELL
            self.positions[symbol] = current_position - quantity

        # Remove position if closed
        if self.positions[symbol] == 0:
            del self.positions[symbol]
            if symbol in self.current_holdings:
                del self.current_holdings[symbol]

        # Create fill event
        fill = FillEvent(
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            fill_price=fill_price,
            timestamp=order.timestamp,
            commission=commission,
            slippage=abs(fill_price - current_bar.close) * quantity,
        )

        self.fills.append(fill)

        logger.info(
            f"Fill: {direction} {quantity} {symbol} @ ${fill_price:.2f}, "
            f"commission: ${commission:.2f}, cash: ${self.cash:,.2f}"
        )

        return fill

    def update_market_value(self, current_bars: Dict[str, MarketDataEvent]):
        """
        Update portfolio holdings value based on current market prices.

        Args:
            current_bars: Dict of symbol -> current MarketDataEvent

        Example:
            current_bars = {'AAPL': market_data_event}
            portfolio.update_market_value(current_bars)
        """
        # Update latest prices
        for symbol, bar in current_bars.items():
            self._latest_prices[symbol] = bar.close

        # Recalculate holdings value
        self.current_holdings.clear()
        for symbol, quantity in self.positions.items():
            if symbol in self._latest_prices:
                price = self._latest_prices[symbol]
                market_value = price * Decimal(quantity)
                self.current_holdings[symbol] = market_value

    def get_portfolio_value(self) -> Decimal:
        """
        Get total portfolio value (cash + holdings).

        Calculates holdings value dynamically using current positions and latest prices.
        This ensures accurate portfolio value even if update_market_value() is not called.

        Returns:
            Total portfolio value as Decimal

        Example:
            portfolio_value = portfolio.get_portfolio_value()
            print(f"Portfolio: ${portfolio_value:,.2f}")
        """
        # Calculate holdings value dynamically from positions and latest prices
        holdings_value = Decimal('0')
        for symbol, quantity in self.positions.items():
            if symbol in self._latest_prices:
                market_value = self._latest_prices[symbol] * Decimal(quantity)
                holdings_value += market_value

        return self.cash + holdings_value

    def _calculate_allocation_percentages(self) -> Dict[str, Decimal]:
        """
        Calculate current portfolio allocation as percentages.

        Used by TradeLogger to record portfolio allocation before/after trades.
        Calculates percentage of total portfolio value for each position and cash.

        Returns:
            Dict of symbol → allocation percentage (0-100)
            Includes 'CASH' if cash > 1% of portfolio

        Example:
            allocations = portfolio._calculate_allocation_percentages()
            # {'TQQQ': Decimal('60.5'), 'CASH': Decimal('39.5')}
        """
        portfolio_value = self.get_portfolio_value()
        if portfolio_value == Decimal('0'):
            return {}

        allocations = {}

        # Add positions
        for symbol, quantity in self.positions.items():
            if symbol in self._latest_prices:
                position_value = self._latest_prices[symbol] * Decimal(quantity)
                percent = (position_value / portfolio_value) * Decimal('100')
                allocations[symbol] = percent

        # Add cash (if significant)
        cash_percent = (self.cash / portfolio_value) * Decimal('100')
        if cash_percent > Decimal('1'):  # Only show if >1%
            allocations['CASH'] = cash_percent

        return allocations

    def get_position(self, symbol: str) -> int:
        """
        Get current position for a symbol.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Quantity (positive for long, negative for short, 0 for no position)

        Example:
            position = portfolio.get_position('AAPL')
            if position > 0:
                print(f"Long {position} shares")
        """
        return self.positions.get(symbol, 0)

    def has_position(self, symbol: Optional[str] = None) -> bool:
        """
        Check if portfolio has a position.

        Args:
            symbol: Specific symbol to check, or None to check any position

        Returns:
            True if position exists

        Example:
            if not portfolio.has_position('AAPL'):
                strategy.buy('AAPL', 100)
        """
        if symbol is None:
            return len(self.positions) > 0
        return symbol in self.positions

    def record_portfolio_value(self, timestamp: datetime):
        """
        Record current portfolio value with timestamp.

        Used for performance analysis and equity curve generation.

        Args:
            timestamp: Timestamp for this portfolio value snapshot

        Example:
            portfolio.record_portfolio_value(current_bar.timestamp)
        """
        value = self.get_portfolio_value()
        self.portfolio_value_history.append((timestamp, value))

    def get_equity_curve(self) -> List[tuple[datetime, Decimal]]:
        """
        Get historical portfolio values (equity curve).

        Returns:
            List of (timestamp, portfolio_value) tuples

        Example:
            equity_curve = portfolio.get_equity_curve()
            for timestamp, value in equity_curve:
                print(f"{timestamp}: ${value:,.2f}")
        """
        return self.portfolio_value_history

    def record_daily_snapshot(
        self,
        timestamp: datetime,
        indicators: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Record complete portfolio state snapshot for daily CSV reporting.

        Called at end of each trading day by EventLoop. Captures cash,
        positions, holdings, total portfolio value, and optional indicator
        values for comprehensive daily reporting and performance analysis.

        Args:
            timestamp: End-of-day timestamp for this snapshot
            indicators: Optional dict of indicator values from strategy
                        (e.g., {'T_norm': 0.15, 'z_score': -0.3})

        Example:
            portfolio.record_daily_snapshot(bar.timestamp)
            portfolio.record_daily_snapshot(bar.timestamp, indicators={'T_norm': 0.15})
        """
        snapshot = {
            'timestamp': timestamp,
            'cash': self.cash,
            'positions': self.positions.copy(),  # {symbol: qty}
            'holdings': self.current_holdings.copy(),  # {symbol: market_value}
            'total_value': self.get_portfolio_value(),
            'indicators': indicators.copy() if indicators else {}
        }
        self.daily_snapshots.append(snapshot)
        indicator_count = len(snapshot['indicators'])
        logger.debug(
            f"Daily snapshot recorded: {timestamp.date()}, "
            f"value=${snapshot['total_value']:,.2f}, "
            f"cash=${snapshot['cash']:,.2f}, "
            f"positions={len(snapshot['positions'])}, "
            f"indicators={indicator_count}"
        )

    def get_daily_snapshots(self) -> List[Dict]:
        """
        Get all daily portfolio snapshots.

        Returns complete portfolio state history including cash, positions,
        holdings, total value, and indicator values for each trading day.
        Used for CSV export and detailed performance analysis.

        Returns:
            List of snapshot dictionaries with keys:
                - timestamp: End-of-day timestamp
                - cash: Available cash
                - positions: Dict[symbol, quantity]
                - holdings: Dict[symbol, market_value]
                - total_value: Total portfolio value
                - indicators: Dict[str, float] of indicator values (may be empty)

        Example:
            snapshots = portfolio.get_daily_snapshots()
            for snap in snapshots:
                print(f"{snap['timestamp'].date()}: ${snap['total_value']:,.2f}")
                if snap['indicators']:
                    print(f"  T_norm: {snap['indicators'].get('T_norm', 'N/A')}")
        """
        return self.daily_snapshots.copy()

    def get_total_return(self) -> Decimal:
        """
        Calculate total return percentage.

        Returns:
            Total return as decimal (e.g., 0.15 for 15% return)

        Example:
            total_return = portfolio.get_total_return()
            print(f"Return: {total_return*100:.2f}%")
        """
        current_value = self.get_portfolio_value()
        return (current_value - self.initial_capital) / self.initial_capital

    def __repr__(self) -> str:
        """String representation of portfolio state."""
        value = self.get_portfolio_value()
        return_pct = self.get_total_return() * 100

        return (
            f"PortfolioSimulator("
            f"value=${value:,.2f}, "
            f"cash=${self.cash:,.2f}, "
            f"return={return_pct:+.2f}%, "
            f"positions={len(self.positions)})"
        )
