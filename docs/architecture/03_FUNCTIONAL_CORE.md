# 03 - Functional Core Architecture

> Core computational logic: backtesting engine, strategy execution, indicators, and optimization

**Last Updated**: 2026-01-25
**Status**: Complete
**Related Documents**: [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | [02_DATA_LAYER](./02_DATA_LAYER.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [EventLoop Architecture](#2-eventloop-architecture)
3. [Strategy Execution Pipeline](#3-strategy-execution-pipeline)
4. [Indicator Calculation Framework](#4-indicator-calculation-framework)
5. [Portfolio Simulator](#5-portfolio-simulator)
6. [Performance Analyzer](#6-performance-analyzer)
7. [Optimization Framework](#7-optimization-framework)
8. [Cross-References](#8-cross-references)

---

## 1. Overview

The Functional Core implements the computational heart of Jutsu Labs - a bar-by-bar backtesting engine with strict lookahead bias prevention, extensible strategy framework, comprehensive indicator library, and multi-method optimization suite.

### Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Lookahead Bias Prevention** | EventLoop processes bars chronologically; strategies only see historical data |
| **Financial Precision** | All calculations use `Decimal` type for monetary values |
| **Deterministic Execution** | Same inputs produce identical outputs across runs |
| **Extensibility** | Abstract base classes enable custom strategies and indicators |
| **Separation of Concerns** | Clear boundaries between data, logic, and presentation |

### Component Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    BacktestRunner                           │
│              (High-level orchestration API)                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  EventLoop  │──│  Strategy   │──│  PortfolioSimulator │ │
│  │ (Bar-by-bar)│  │ (Signals)   │  │ (Position mgmt)     │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         ▼                ▼                     ▼            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ DataHandler │  │ Indicators  │  │ PerformanceAnalyzer │ │
│  │ (Market DB) │  │ (Technical) │  │ (Metrics calc)      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. EventLoop Architecture

The EventLoop is the central coordinator that drives bar-by-bar simulation while preventing lookahead bias.

### Core Responsibilities

1. **Chronological Processing**: Process market bars in timestamp order
2. **Warmup Phase Management**: Skip signal generation during indicator warmup
3. **Snapshot Recording**: Capture portfolio state at each bar for equity curve
4. **Signal Coordination**: Route strategy signals to portfolio for execution

### EventLoop Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        EventLoop.run()                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Initialize State │
                    │ - warmup_complete│
                    │ - bars_processed │
                    └────────┬────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │   For each bar in data_feed  │◄─────────────────┐
              └──────────────┬───────────────┘                  │
                             │                                  │
                             ▼                                  │
                   ┌─────────────────┐                          │
                   │ Process Bar Data │                         │
                   │ - OHLCV values   │                         │
                   │ - Timestamp      │                         │
                   └────────┬────────┘                          │
                            │                                   │
                            ▼                                   │
               ┌────────────────────────┐                       │
               │  Warmup Phase Check    │                       │
               │ bars_processed < warmup│                       │
               └───────────┬────────────┘                       │
                           │                                    │
              ┌────────────┴────────────┐                       │
              │                         │                       │
         [In Warmup]              [Warmup Complete]             │
              │                         │                       │
              ▼                         ▼                       │
    ┌─────────────────┐      ┌─────────────────────┐           │
    │ Feed bar to     │      │ strategy.on_bar()   │           │
    │ strategy (no    │      │ - Generate signals  │           │
    │ signal gen)     │      │ - Return SignalEvent│           │
    └────────┬────────┘      └──────────┬──────────┘           │
             │                          │                       │
             │                          ▼                       │
             │               ┌─────────────────────┐            │
             │               │ Execute Signal      │            │
             │               │ portfolio.execute() │            │
             │               └──────────┬──────────┘            │
             │                          │                       │
             └──────────┬───────────────┘                       │
                        │                                       │
                        ▼                                       │
           ┌─────────────────────────┐                          │
           │ Record Equity Snapshot  │                          │
           │ BEFORE market value     │◄── Critical timing!      │
           │ update for this bar     │                          │
           └───────────┬─────────────┘                          │
                       │                                        │
                       ▼                                        │
           ┌─────────────────────────┐                          │
           │ Update Market Value     │                          │
           │ portfolio.update_       │                          │
           │ market_value(close)     │                          │
           └───────────┬─────────────┘                          │
                       │                                        │
                       ▼                                        │
           ┌─────────────────────────┐                          │
           │ Increment bar counter   │                          │
           │ bars_processed += 1     │──────────────────────────┘
           └─────────────────────────┘
```

### Key Implementation Details

```python
# jutsu_engine/core/event_loop.py

class EventLoop:
    """Bar-by-bar event coordinator with lookahead bias prevention."""

    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        portfolio: PortfolioSimulator,
        warmup_period: int = 0
    ):
        self.data_handler = data_handler
        self.strategy = strategy
        self.portfolio = portfolio
        self.warmup_period = warmup_period

    def run(self) -> List[Dict]:
        """Execute backtest simulation bar-by-bar."""
        equity_curve = []
        bars_processed = 0
        warmup_complete = False

        for bar in self.data_handler.get_bars():
            # Create market data event
            market_event = MarketDataEvent(
                symbol=bar['symbol'],
                timestamp=bar['timestamp'],
                open=bar['open'],
                high=bar['high'],
                low=bar['low'],
                close=bar['close'],
                volume=bar['volume']
            )

            # Feed bar to strategy
            self.strategy._receive_bar(market_event)

            # Check warmup completion
            if not warmup_complete and bars_processed >= self.warmup_period:
                warmup_complete = True

            # Generate signals only after warmup
            if warmup_complete:
                signal = self.strategy.on_bar(market_event)
                if signal:
                    self.portfolio.execute_signal(signal, bar['close'])

            # CRITICAL: Record snapshot BEFORE updating market value
            # This ensures equity curve reflects pre-update state
            equity_curve.append({
                'timestamp': bar['timestamp'],
                'equity': self.portfolio.total_equity,
                'cash': self.portfolio.cash,
                'positions_value': self.portfolio.positions_value
            })

            # Update portfolio with current prices
            self.portfolio.update_market_value(bar['close'])
            bars_processed += 1

        return equity_curve
```

### Warmup Phase Handling

The warmup period allows indicators to accumulate sufficient historical data before generating signals.

| Component | Warmup Requirement |
|-----------|-------------------|
| SMA(20) | 20 bars minimum |
| MACD(12,26,9) | 35 bars minimum (26 + 9) |
| RSI(14) | 15 bars minimum |
| Bollinger(20) | 20 bars minimum |
| Kalman Filter | 5-10 bars for convergence |

```python
# Strategy warmup calculation
def calculate_warmup_period(strategy_params: dict) -> int:
    """Calculate minimum warmup based on indicator requirements."""
    indicators = strategy_params.get('indicators', {})
    max_period = 0

    for indicator, params in indicators.items():
        if indicator == 'macd':
            period = params['slow'] + params['signal']
        else:
            period = params.get('period', 0)
        max_period = max(max_period, period)

    return max_period + 5  # Safety buffer
```

---

## 3. Strategy Execution Pipeline

Strategies are the decision-making components that analyze market data and generate trading signals.

### Strategy Base Class

```python
# jutsu_engine/core/strategy_base.py

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, List

class Strategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, name: str):
        self.name = name
        self._bars: List[Dict] = []
        self._portfolio = None

    def _receive_bar(self, bar: MarketDataEvent) -> None:
        """Internal: receive and store bar data."""
        self._bars.append(bar.to_dict())

    @abstractmethod
    def on_bar(self, bar: MarketDataEvent) -> Optional[SignalEvent]:
        """
        Process new bar and optionally generate signal.

        This method is called AFTER warmup period completes.
        Override in subclass to implement trading logic.

        Args:
            bar: Current market data bar

        Returns:
            SignalEvent if action needed, None otherwise
        """
        pass

    def get_closes(self, lookback: int) -> List[Decimal]:
        """Get recent close prices for indicator calculation."""
        return [Decimal(str(b['close'])) for b in self._bars[-lookback:]]

    def has_position(self, symbol: str) -> bool:
        """Check if portfolio holds position in symbol."""
        return self._portfolio.has_position(symbol)

    def buy(self, symbol: str, quantity: int) -> SignalEvent:
        """Generate buy signal."""
        return SignalEvent(
            symbol=symbol,
            signal_type='BUY',
            quantity=quantity,
            strategy_name=self.name
        )

    def sell(self, symbol: str, quantity: int) -> SignalEvent:
        """Generate sell signal."""
        return SignalEvent(
            symbol=symbol,
            signal_type='SELL',
            quantity=quantity,
            strategy_name=self.name
        )

    def buy_percent(self, symbol: str, percent: float) -> SignalEvent:
        """Generate buy signal for percentage of portfolio."""
        return SignalEvent(
            symbol=symbol,
            signal_type='BUY_PERCENT',
            percent=percent,
            strategy_name=self.name
        )
```

### Signal Event Structure

```python
# jutsu_engine/core/events.py

@dataclass
class SignalEvent:
    """Trading signal generated by strategy."""
    symbol: str
    signal_type: str  # 'BUY', 'SELL', 'BUY_PERCENT', 'SELL_PERCENT'
    strategy_name: str
    quantity: Optional[int] = None
    percent: Optional[float] = None  # For percentage-based sizing
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
```

### Strategy Implementation Example

```python
# jutsu_engine/strategies/hierarchical_adaptive.py

class HierarchicalAdaptiveStrategy(Strategy):
    """
    Multi-regime adaptive strategy with Kalman trend detection.

    Operates on 6-cell regime matrix:
    - Volatility: Low, Medium, High (Z-score based)
    - Trend: Bull, Bear (Kalman filter direction)

    Allocation adjusts based on regime classification.
    """

    def __init__(
        self,
        name: str = "hierarchical_adaptive_v3_5b",
        kalman_process_variance: float = 0.001,
        vol_zscore_lookback: int = 20,
        max_allocation: float = 0.95,
        regime_allocation_map: Optional[Dict] = None
    ):
        super().__init__(name)
        self.kalman = AdaptiveKalmanFilter(
            process_variance=kalman_process_variance
        )
        self.vol_lookback = vol_zscore_lookback
        self.max_allocation = max_allocation
        self.regime_map = regime_allocation_map or DEFAULT_REGIME_MAP

    def on_bar(self, bar: MarketDataEvent) -> Optional[SignalEvent]:
        """Generate signal based on current regime classification."""
        closes = self.get_closes(lookback=self.vol_lookback + 10)

        # Classify regime
        vol_state = self._classify_volatility(closes)
        trend_state = self._classify_trend(closes)
        regime = (vol_state, trend_state)

        # Get target allocation for regime
        target_allocation = self.regime_map.get(regime, 0.5)

        # Generate signal based on allocation change
        current_allocation = self._get_current_allocation()

        if target_allocation > current_allocation + 0.05:
            return self.buy_percent(bar.symbol, target_allocation)
        elif target_allocation < current_allocation - 0.05:
            return self.sell_percent(bar.symbol, target_allocation)

        return None
```

---

## 4. Indicator Calculation Framework

The indicator library provides technical analysis tools with consistent APIs and Decimal precision support.

### Technical Indicators

| Indicator | Function | Parameters | Output |
|-----------|----------|------------|--------|
| **SMA** | `sma(data, period)` | period: int | Rolling mean |
| **EMA** | `ema(data, period)` | period: int | Exponential weighted mean |
| **RSI** | `rsi(data, period)` | period: int (default 14) | 0-100 oscillator |
| **MACD** | `macd(data, fast, slow, signal)` | 12, 26, 9 defaults | (macd_line, signal_line, histogram) |
| **Bollinger** | `bollinger_bands(data, period, std)` | 20, 2 defaults | (upper, middle, lower) |
| **ATR** | `atr(high, low, close, period)` | period: int | Average True Range |
| **Stochastic** | `stochastic(high, low, close, k, d)` | 14, 3 defaults | (%K, %D) |
| **OBV** | `obv(close, volume)` | - | On Balance Volume |
| **ADX** | `adx(high, low, close, period)` | period: int | 0-100 trend strength |

### Indicator Implementation Pattern

```python
# jutsu_engine/indicators/technical.py

from typing import Union, List, Tuple
import pandas as pd
from decimal import Decimal

def _to_series(data: Union[pd.Series, List]) -> pd.Series:
    """Convert input to pandas Series with Decimal support."""
    if isinstance(data, pd.Series):
        return data.astype(float)  # pd operations need float
    return pd.Series([float(d) for d in data])

def sma(data: Union[pd.Series, List], period: int) -> pd.Series:
    """
    Calculate Simple Moving Average.

    Args:
        data: Price series (close prices typically)
        period: Lookback period for averaging

    Returns:
        pd.Series with SMA values (NaN for first period-1 values)
    """
    series = _to_series(data)
    return series.rolling(window=period).mean()

def macd(
    data: Union[pd.Series, List],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD indicator.

    Args:
        data: Price series
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line EMA period (default 9)

    Returns:
        Tuple of (macd_line, signal_line, histogram)
    """
    series = _to_series(data)

    fast_ema = series.ewm(span=fast_period, adjust=False).mean()
    slow_ema = series.ewm(span=slow_period, adjust=False).mean()

    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram

def rsi(data: Union[pd.Series, List], period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index.

    Args:
        data: Price series
        period: Lookback period (default 14)

    Returns:
        pd.Series with RSI values (0-100 scale)
    """
    series = _to_series(data)
    delta = series.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss.replace(0, float('inf'))
    return 100 - (100 / (1 + rs))
```

### Kalman Filter Implementation

The Kalman filter provides adaptive trend detection with noise filtering.

```python
# jutsu_engine/indicators/kalman.py

class KalmanFilterModel:
    """
    Kalman Filter for price trend estimation.

    State Model:
        x_t = A * x_{t-1} + w  (state transition)
        z_t = H * x_t + v      (observation)

    Where:
        x_t = [price, velocity]  (hidden state)
        z_t = observed price
        w ~ N(0, Q)  (process noise)
        v ~ N(0, R)  (measurement noise)
    """

    def __init__(
        self,
        process_variance: float = 0.001,
        measurement_variance: float = 0.1,
        initial_estimate: float = 0.0
    ):
        self.Q = process_variance      # Process noise covariance
        self.R = measurement_variance  # Measurement noise covariance

        # State estimate [price, velocity]
        self.x = np.array([initial_estimate, 0.0])

        # Error covariance matrix
        self.P = np.eye(2) * 1.0

        # State transition matrix (constant velocity model)
        self.A = np.array([[1, 1], [0, 1]])

        # Observation matrix (we observe price only)
        self.H = np.array([[1, 0]])

    def update(self, measurement: float) -> Tuple[float, float]:
        """
        Process new measurement and return filtered estimate.

        Args:
            measurement: Observed price

        Returns:
            Tuple of (filtered_price, velocity_estimate)
        """
        # Predict step
        x_pred = self.A @ self.x
        P_pred = self.A @ self.P @ self.A.T + self.Q * np.eye(2)

        # Update step
        y = measurement - self.H @ x_pred  # Innovation
        S = self.H @ P_pred @ self.H.T + self.R  # Innovation covariance
        K = P_pred @ self.H.T / S  # Kalman gain

        self.x = x_pred + K.flatten() * y
        self.P = (np.eye(2) - np.outer(K, self.H)) @ P_pred

        return self.x[0], self.x[1]  # (price, velocity)


class AdaptiveKalmanFilter(KalmanFilterModel):
    """
    Adaptive Kalman Filter with regime-dependent parameters.

    Adjusts process/measurement variance based on volatility regime.
    """

    def __init__(
        self,
        process_variance: float = 0.001,
        measurement_variance: float = 0.1,
        adaptation_rate: float = 0.1
    ):
        super().__init__(process_variance, measurement_variance)
        self.adaptation_rate = adaptation_rate
        self.innovation_history = []

    def adapt_parameters(self, volatility_zscore: float) -> None:
        """Adjust filter parameters based on market regime."""
        if volatility_zscore > 1.5:  # High volatility
            self.Q = 0.01   # More responsive
            self.R = 0.05   # Trust measurements less
        elif volatility_zscore < -0.5:  # Low volatility
            self.Q = 0.0001  # Smoother
            self.R = 0.2     # Trust measurements more
        else:  # Normal volatility
            self.Q = 0.001
            self.R = 0.1
```

### Volatility Z-Score

Used for regime classification in the 6-cell matrix.

```python
def volatility_zscore(returns: pd.Series, lookback: int = 20) -> float:
    """
    Calculate volatility Z-score for regime classification.

    Z = (current_vol - mean_vol) / std_vol

    Thresholds:
        Z > 1.0  → High volatility
        Z < -1.0 → Low volatility
        else     → Medium volatility
    """
    vol = returns.rolling(window=lookback).std()
    current_vol = vol.iloc[-1]
    mean_vol = vol.mean()
    std_vol = vol.std()

    if std_vol == 0:
        return 0.0

    return (current_vol - mean_vol) / std_vol
```

---

## 5. Portfolio Simulator

The PortfolioSimulator manages positions, cash, and order execution during backtests.

### Core Responsibilities

1. **Position Management**: Track open positions with quantities and cost basis
2. **Cash Management**: Maintain available cash with transaction costs
3. **Order Execution**: Execute signals with commission and slippage
4. **Mark-to-Market**: Update position values with current prices

### Portfolio Simulator Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PortfolioSimulator                          │
├─────────────────────────────────────────────────────────────────┤
│ State:                                                          │
│  - initial_capital: Decimal                                     │
│  - cash: Decimal                                                │
│  - positions: Dict[symbol, Position]                            │
│  - total_equity: Decimal (cash + positions_value)               │
│                                                                 │
│ Configuration:                                                  │
│  - commission_per_share: Decimal (default $0.01)                │
│  - slippage_percent: Decimal (default 0.1%)                     │
│  - max_position_percent: float (default 95%)                    │
├─────────────────────────────────────────────────────────────────┤
│ Methods:                                                        │
│  - execute_signal(signal, price) → FillEvent                    │
│  - update_market_value(prices) → None                           │
│  - has_position(symbol) → bool                                  │
│  - get_position(symbol) → Position                              │
│  - calculate_position_size(percent, price) → int                │
└─────────────────────────────────────────────────────────────────┘
```

### Position Tracking

```python
@dataclass
class Position:
    """Represents an open position in a security."""
    symbol: str
    quantity: int
    avg_entry_price: Decimal
    current_price: Decimal

    @property
    def market_value(self) -> Decimal:
        """Current market value of position."""
        return Decimal(str(self.quantity)) * self.current_price

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized profit/loss."""
        return self.market_value - (Decimal(str(self.quantity)) * self.avg_entry_price)

    @property
    def unrealized_pnl_percent(self) -> Decimal:
        """Unrealized P&L as percentage of cost basis."""
        cost_basis = Decimal(str(self.quantity)) * self.avg_entry_price
        if cost_basis == 0:
            return Decimal('0')
        return (self.unrealized_pnl / cost_basis) * 100
```

### Order Execution Logic

```python
class PortfolioSimulator:
    """Simulates portfolio management with realistic execution."""

    def __init__(
        self,
        initial_capital: Decimal,
        commission_per_share: Decimal = Decimal('0.01'),
        slippage_percent: Decimal = Decimal('0.001')
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.commission_per_share = commission_per_share
        self.slippage_percent = slippage_percent

    def execute_signal(self, signal: SignalEvent, price: Decimal) -> Optional[FillEvent]:
        """
        Execute trading signal with commission and slippage.

        Args:
            signal: Trading signal from strategy
            price: Current market price

        Returns:
            FillEvent if execution successful, None otherwise
        """
        if signal.signal_type == 'BUY':
            return self._execute_buy(signal.symbol, signal.quantity, price)
        elif signal.signal_type == 'SELL':
            return self._execute_sell(signal.symbol, signal.quantity, price)
        elif signal.signal_type == 'BUY_PERCENT':
            quantity = self._calculate_quantity_for_percent(signal.percent, price)
            return self._execute_buy(signal.symbol, quantity, price)
        elif signal.signal_type == 'SELL_PERCENT':
            return self._execute_sell_to_percent(signal.symbol, signal.percent, price)

        return None

    def _execute_buy(
        self, symbol: str, quantity: int, price: Decimal
    ) -> Optional[FillEvent]:
        """Execute buy order with slippage and commission."""
        # Apply slippage (adverse price movement)
        fill_price = price * (1 + self.slippage_percent)

        # Calculate total cost
        commission = self.commission_per_share * Decimal(str(quantity))
        total_cost = fill_price * Decimal(str(quantity)) + commission

        # Check available cash
        if total_cost > self.cash:
            return None  # Insufficient funds

        # Update cash
        self.cash -= total_cost

        # Update or create position
        if symbol in self.positions:
            pos = self.positions[symbol]
            # Calculate new average entry price
            total_shares = pos.quantity + quantity
            total_cost_basis = (pos.avg_entry_price * pos.quantity) + (fill_price * quantity)
            pos.avg_entry_price = total_cost_basis / Decimal(str(total_shares))
            pos.quantity = total_shares
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=fill_price,
                current_price=fill_price
            )

        return FillEvent(
            symbol=symbol,
            quantity=quantity,
            fill_price=fill_price,
            commission=commission,
            direction='BUY'
        )

    def update_market_value(self, prices: Dict[str, Decimal]) -> None:
        """Update all positions with current market prices."""
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.current_price = prices[symbol]

    @property
    def total_equity(self) -> Decimal:
        """Total portfolio value (cash + positions)."""
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash + positions_value

    @property
    def positions_value(self) -> Decimal:
        """Total value of all positions."""
        return sum(p.market_value for p in self.positions.values())
```

---

## 6. Performance Analyzer

The PerformanceAnalyzer calculates comprehensive metrics from backtest results.

### Metrics Overview

| Category | Metrics |
|----------|---------|
| **Returns** | Total Return, CAGR, Daily/Monthly Returns |
| **Risk-Adjusted** | Sharpe Ratio, Sortino Ratio, Calmar Ratio |
| **Drawdown** | Max Drawdown, Avg Drawdown, Drawdown Duration |
| **Risk** | Volatility, VaR (95%), CVaR, Beta |
| **Trade Analysis** | Win Rate, Profit Factor, Avg Win/Loss |
| **Recovery** | Recovery Factor, Time to Recovery |

### Key Metric Calculations

```python
# jutsu_engine/performance/analyzer.py

class PerformanceAnalyzer:
    """Comprehensive performance metrics calculator."""

    def __init__(self, equity_curve: pd.DataFrame, risk_free_rate: float = 0.02):
        """
        Args:
            equity_curve: DataFrame with 'timestamp' and 'equity' columns
            risk_free_rate: Annual risk-free rate (default 2%)
        """
        self.equity_curve = equity_curve
        self.risk_free_rate = risk_free_rate
        self.daily_rfr = (1 + risk_free_rate) ** (1/252) - 1

        # Calculate returns
        self.returns = equity_curve['equity'].pct_change().dropna()

    def total_return(self) -> Decimal:
        """Total percentage return over period."""
        start = self.equity_curve['equity'].iloc[0]
        end = self.equity_curve['equity'].iloc[-1]
        return Decimal(str((end - start) / start * 100))

    def cagr(self) -> Decimal:
        """Compound Annual Growth Rate."""
        start = float(self.equity_curve['equity'].iloc[0])
        end = float(self.equity_curve['equity'].iloc[-1])
        days = (self.equity_curve['timestamp'].iloc[-1] -
                self.equity_curve['timestamp'].iloc[0]).days
        years = days / 365.25

        if years <= 0:
            return Decimal('0')

        cagr = (end / start) ** (1 / years) - 1
        return Decimal(str(cagr * 100))

    def sharpe_ratio(self) -> Decimal:
        """
        Sharpe Ratio: Risk-adjusted return.

        Sharpe = (Mean_Return - Risk_Free_Rate) / Std_Return
        Annualized by sqrt(252)
        """
        excess_returns = self.returns - self.daily_rfr

        if excess_returns.std() == 0:
            return Decimal('0')

        sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252)
        return Decimal(str(sharpe))

    def sortino_ratio(self) -> Decimal:
        """
        Sortino Ratio: Downside risk-adjusted return.

        Sortino = (Mean_Return - Risk_Free_Rate) / Downside_Std
        Only considers negative returns for volatility.
        """
        excess_returns = self.returns - self.daily_rfr
        downside_returns = excess_returns[excess_returns < 0]

        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return Decimal('0')

        sortino = (excess_returns.mean() / downside_returns.std()) * np.sqrt(252)
        return Decimal(str(sortino))

    def max_drawdown(self) -> Decimal:
        """
        Maximum Drawdown: Largest peak-to-trough decline.

        MDD = (Trough - Peak) / Peak
        """
        equity = self.equity_curve['equity']
        rolling_max = equity.expanding().max()
        drawdowns = (equity - rolling_max) / rolling_max
        return Decimal(str(drawdowns.min() * 100))

    def calmar_ratio(self) -> Decimal:
        """
        Calmar Ratio: Return relative to max drawdown.

        Calmar = CAGR / |Max_Drawdown|
        """
        mdd = abs(float(self.max_drawdown()))
        if mdd == 0:
            return Decimal('0')

        calmar = float(self.cagr()) / mdd
        return Decimal(str(calmar))

    def var_95(self) -> Decimal:
        """
        Value at Risk (95%): Maximum expected loss.

        5th percentile of return distribution.
        """
        var = np.percentile(self.returns, 5)
        return Decimal(str(var * 100))

    def cvar_95(self) -> Decimal:
        """
        Conditional VaR (Expected Shortfall): Average loss beyond VaR.

        Mean of returns below 5th percentile.
        """
        var_threshold = np.percentile(self.returns, 5)
        tail_returns = self.returns[self.returns <= var_threshold]

        if len(tail_returns) == 0:
            return Decimal('0')

        cvar = tail_returns.mean()
        return Decimal(str(cvar * 100))

    def win_rate(self, trades: List[Dict]) -> Decimal:
        """Percentage of profitable trades."""
        if not trades:
            return Decimal('0')

        winners = sum(1 for t in trades if t['pnl'] > 0)
        return Decimal(str(winners / len(trades) * 100))

    def profit_factor(self, trades: List[Dict]) -> Decimal:
        """
        Profit Factor: Gross profits / Gross losses.

        Values > 1.5 generally considered good.
        """
        gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))

        if gross_loss == 0:
            return Decimal('inf') if gross_profit > 0 else Decimal('0')

        return Decimal(str(gross_profit / gross_loss))

    def calculate_all_metrics(self, trades: Optional[List[Dict]] = None) -> Dict:
        """Calculate all performance metrics."""
        metrics = {
            'total_return_pct': self.total_return(),
            'cagr_pct': self.cagr(),
            'sharpe_ratio': self.sharpe_ratio(),
            'sortino_ratio': self.sortino_ratio(),
            'max_drawdown_pct': self.max_drawdown(),
            'calmar_ratio': self.calmar_ratio(),
            'volatility_pct': Decimal(str(self.returns.std() * np.sqrt(252) * 100)),
            'var_95_pct': self.var_95(),
            'cvar_95_pct': self.cvar_95(),
        }

        if trades:
            metrics.update({
                'win_rate_pct': self.win_rate(trades),
                'profit_factor': self.profit_factor(trades),
                'total_trades': len(trades),
            })

        return metrics
```

---

## 7. Optimization Framework

The optimization suite provides multiple methods for parameter tuning and robustness testing.

### 7.1 Grid Search Optimizer

Exhaustive search over parameter combinations.

```python
# jutsu_engine/optimization/grid_search.py

class GridSearchOptimizer:
    """
    Exhaustive parameter search with parallel execution.

    Searches all combinations of specified parameter ranges
    and returns results sorted by optimization target.
    """

    def __init__(
        self,
        strategy_class: Type[Strategy],
        param_grid: Dict[str, List],
        metric: str = 'sharpe_ratio',
        n_jobs: int = -1  # -1 = all cores
    ):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.metric = metric
        self.n_jobs = n_jobs

    def optimize(
        self,
        data_handler: DataHandler,
        initial_capital: Decimal
    ) -> List[Dict]:
        """
        Run grid search optimization.

        Args:
            data_handler: Market data source
            initial_capital: Starting capital for each backtest

        Returns:
            List of results sorted by target metric (descending)
        """
        # Generate all parameter combinations
        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())
        combinations = list(itertools.product(*param_values))

        results = []

        # Parallel execution
        with ProcessPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = {
                executor.submit(
                    self._run_backtest,
                    dict(zip(param_names, combo)),
                    data_handler,
                    initial_capital
                ): combo
                for combo in combinations
            }

            for future in as_completed(futures):
                result = future.result()
                results.append(result)

        # Sort by target metric
        results.sort(key=lambda x: x.get(self.metric, 0), reverse=True)
        return results

    def _run_backtest(
        self,
        params: Dict,
        data_handler: DataHandler,
        initial_capital: Decimal
    ) -> Dict:
        """Run single backtest with given parameters."""
        strategy = self.strategy_class(**params)
        portfolio = PortfolioSimulator(initial_capital)
        event_loop = EventLoop(data_handler, strategy, portfolio)

        equity_curve = event_loop.run()

        analyzer = PerformanceAnalyzer(pd.DataFrame(equity_curve))
        metrics = analyzer.calculate_all_metrics()

        return {
            'params': params,
            **{k: float(v) for k, v in metrics.items()}
        }
```

### 7.2 Walk-Forward Analyzer

Out-of-sample validation with rolling windows.

```
┌─────────────────────────────────────────────────────────────────┐
│                  Walk-Forward Analysis                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Window 1:  [===== In-Sample =====][== OOS ==]                 │
│  Window 2:       [===== In-Sample =====][== OOS ==]            │
│  Window 3:            [===== In-Sample =====][== OOS ==]       │
│  Window 4:                 [===== In-Sample =====][== OOS ==]  │
│                                                                 │
│  In-Sample:  Optimize parameters                                │
│  OOS:        Validate with optimized parameters                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

```python
# jutsu_engine/optimization/walk_forward.py

class WalkForwardAnalyzer:
    """
    Walk-Forward Optimization with rolling windows.

    Prevents overfitting by separating optimization (in-sample)
    from validation (out-of-sample) periods.
    """

    def __init__(
        self,
        strategy_class: Type[Strategy],
        param_grid: Dict[str, List],
        in_sample_periods: int = 252,  # ~1 year
        out_of_sample_periods: int = 63,  # ~3 months
        metric: str = 'sharpe_ratio'
    ):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.in_sample = in_sample_periods
        self.out_of_sample = out_of_sample_periods
        self.metric = metric

    def analyze(self, data: pd.DataFrame) -> Dict:
        """
        Run walk-forward analysis.

        Returns:
            Dict with:
            - 'windows': List of per-window results
            - 'oos_equity_curve': Combined OOS equity
            - 'oos_metrics': Aggregated OOS performance
            - 'efficiency_ratio': OOS / IS performance ratio
        """
        window_size = self.in_sample + self.out_of_sample
        n_windows = (len(data) - self.in_sample) // self.out_of_sample

        windows = []
        oos_equity = []

        for i in range(n_windows):
            start_idx = i * self.out_of_sample
            is_end = start_idx + self.in_sample
            oos_end = is_end + self.out_of_sample

            # In-sample optimization
            is_data = data.iloc[start_idx:is_end]
            best_params = self._optimize_in_sample(is_data)

            # Out-of-sample validation
            oos_data = data.iloc[is_end:oos_end]
            oos_result = self._validate_out_of_sample(oos_data, best_params)

            windows.append({
                'window': i + 1,
                'is_params': best_params,
                'is_metric': self._get_is_metric(is_data, best_params),
                'oos_metric': oos_result['metrics'][self.metric],
                'oos_equity': oos_result['equity_curve']
            })

            oos_equity.extend(oos_result['equity_curve'])

        # Calculate efficiency ratio
        avg_is = np.mean([w['is_metric'] for w in windows])
        avg_oos = np.mean([w['oos_metric'] for w in windows])
        efficiency = avg_oos / avg_is if avg_is != 0 else 0

        return {
            'windows': windows,
            'oos_equity_curve': oos_equity,
            'efficiency_ratio': efficiency,
            'n_windows': n_windows
        }
```

### 7.3 Monte Carlo Simulator

Robustness testing through statistical resampling.

```python
# jutsu_engine/optimization/monte_carlo_simulator.py

class MonteCarloSimulator:
    """
    Monte Carlo simulation for strategy robustness testing.

    Methods:
    1. Return Shuffling: Randomize daily return order
    2. Bootstrap Resampling: Sample returns with replacement
    3. Parameter Perturbation: Add noise to parameters

    Outputs probability distributions for key metrics.
    """

    def __init__(
        self,
        n_simulations: int = 1000,
        confidence_level: float = 0.95,
        method: str = 'bootstrap'  # 'shuffle', 'bootstrap', 'parameter'
    ):
        self.n_simulations = n_simulations
        self.confidence_level = confidence_level
        self.method = method

    def run(
        self,
        backtest_result: Dict,
        strategy_params: Optional[Dict] = None
    ) -> Dict:
        """
        Run Monte Carlo simulation.

        Args:
            backtest_result: Original backtest output with equity curve
            strategy_params: Parameters for perturbation method

        Returns:
            Dict with:
            - 'simulations': Raw simulation results
            - 'metrics_distribution': {metric: [values]}
            - 'confidence_intervals': {metric: (low, high)}
            - 'probability_of_loss': P(total_return < 0)
            - 'histograms': Matplotlib figures
        """
        original_returns = self._extract_returns(backtest_result)
        simulations = []

        for i in range(self.n_simulations):
            if self.method == 'shuffle':
                sim_returns = self._shuffle_returns(original_returns)
            elif self.method == 'bootstrap':
                sim_returns = self._bootstrap_returns(original_returns)
            else:  # parameter perturbation
                sim_returns = self._perturb_parameters(
                    original_returns, strategy_params
                )

            # Calculate metrics for this simulation
            sim_metrics = self._calculate_simulation_metrics(sim_returns)
            simulations.append(sim_metrics)

        return self._analyze_results(simulations)

    def _bootstrap_returns(self, returns: np.ndarray) -> np.ndarray:
        """Sample returns with replacement."""
        indices = np.random.choice(len(returns), size=len(returns), replace=True)
        return returns[indices]

    def _shuffle_returns(self, returns: np.ndarray) -> np.ndarray:
        """Randomly shuffle return order."""
        shuffled = returns.copy()
        np.random.shuffle(shuffled)
        return shuffled

    def _analyze_results(self, simulations: List[Dict]) -> Dict:
        """Aggregate simulation results."""
        metrics = ['total_return', 'sharpe_ratio', 'max_drawdown']
        distributions = {m: [s[m] for s in simulations] for m in metrics}

        alpha = 1 - self.confidence_level
        confidence_intervals = {
            m: (
                np.percentile(distributions[m], alpha/2 * 100),
                np.percentile(distributions[m], (1 - alpha/2) * 100)
            )
            for m in metrics
        }

        prob_loss = sum(1 for s in simulations if s['total_return'] < 0) / len(simulations)

        return {
            'simulations': simulations,
            'metrics_distribution': distributions,
            'confidence_intervals': confidence_intervals,
            'probability_of_loss': prob_loss,
            'median_sharpe': np.median(distributions['sharpe_ratio']),
            'worst_case_drawdown': np.percentile(distributions['max_drawdown'], 5)
        }
```

### Optimization Comparison

| Method | Use Case | Computation | Overfitting Risk |
|--------|----------|-------------|------------------|
| **Grid Search** | Initial parameter exploration | High (exponential) | High |
| **Walk-Forward** | Production parameter validation | Medium | Low |
| **Monte Carlo** | Robustness/confidence testing | Medium | N/A |

### Recommended Workflow

```
1. Grid Search (broad parameter sweep)
   └─► Top 10 parameter sets

2. Walk-Forward Analysis (OOS validation)
   └─► Filter to sets with efficiency > 0.7

3. Monte Carlo Simulation (robustness check)
   └─► Final parameters with confidence intervals
```

---

## 8. Cross-References

### Related Architecture Documents

| Document | Relevance |
|----------|-----------|
| [00_SYSTEM_OVERVIEW](./00_SYSTEM_OVERVIEW.md) | High-level architecture context |
| [01_DOMAIN_MODEL](./01_DOMAIN_MODEL.md) | Strategy domain concepts, regime definitions |
| [02_DATA_LAYER](./02_DATA_LAYER.md) | Data models consumed by functional core |
| [05_LIFECYCLE](./05_LIFECYCLE.md) | Trading day flow (uses functional core) |
| [06_WORKERS](./06_WORKERS.md) | Scheduled job execution of strategies |

### Key Source Files

| Component | File Path |
|-----------|-----------|
| EventLoop | `jutsu_engine/core/event_loop.py` |
| Strategy Base | `jutsu_engine/core/strategy_base.py` |
| Events | `jutsu_engine/core/events.py` |
| Technical Indicators | `jutsu_engine/indicators/technical.py` |
| Kalman Filter | `jutsu_engine/indicators/kalman.py` |
| Portfolio Simulator | `jutsu_engine/portfolio/simulator.py` |
| Performance Analyzer | `jutsu_engine/performance/analyzer.py` |
| Grid Search | `jutsu_engine/optimization/grid_search.py` |
| Walk-Forward | `jutsu_engine/optimization/walk_forward.py` |
| Monte Carlo | `jutsu_engine/optimization/monte_carlo_simulator.py` |
| Backtest Runner | `jutsu_engine/application/backtest_runner.py` |

### External Dependencies

| Package | Purpose |
|---------|---------|
| `pandas` | Time series data manipulation |
| `numpy` | Numerical computations |
| `scipy` | Statistical functions |
| `sqlalchemy` | Database ORM |
| `matplotlib` | Visualization (Monte Carlo histograms) |

---

**Document Version**: 1.0
**Author**: Claude (Architecture Documentation)
**Review Status**: Draft
