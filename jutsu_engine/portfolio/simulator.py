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
    ):
        """
        Initialize portfolio simulator.

        Args:
            initial_capital: Starting cash amount
            commission_per_share: Commission cost per share (default: $0.01)
            slippage_percent: Slippage as percentage of price (default: 0.1%)

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

        # Latest prices for each symbol
        self._latest_prices: Dict[str, Decimal] = {}

        logger.info(
            f"Portfolio initialized with ${initial_capital:,.2f}, "
            f"commission: ${commission_per_share}/share, "
            f"slippage: {slippage_percent*100}%"
        )

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
            # Market order fills at close price with slippage
            fill_price = current_bar.close

            # Apply slippage (disadvantageous to trader)
            if direction == 'BUY':
                fill_price = fill_price * (Decimal('1') + self.slippage_percent)
            else:  # SELL
                fill_price = fill_price * (Decimal('1') - self.slippage_percent)

        elif order_type == 'LIMIT':
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

        # Check if we have enough cash for buy orders
        if direction == 'BUY' and total_cost > self.cash:
            logger.warning(
                f"Insufficient cash: Need ${total_cost:,.2f}, have ${self.cash:,.2f}"
            )
            return None

        # Update cash
        if direction == 'BUY':
            self.cash -= total_cost
        else:  # SELL
            self.cash += (fill_price * quantity) - commission

        # Update positions
        current_position = self.positions.get(symbol, 0)
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

        Returns:
            Total portfolio value as Decimal

        Example:
            portfolio_value = portfolio.get_portfolio_value()
            print(f"Portfolio: ${portfolio_value:,.2f}")
        """
        holdings_value = sum(self.current_holdings.values())
        return self.cash + holdings_value

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
