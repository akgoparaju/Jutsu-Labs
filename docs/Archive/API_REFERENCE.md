# Jutsu Labs Engine API Reference

Complete API documentation for the Vibe backtesting engine.

## Table of Contents

- [Core Components](#core-components)
  - [EventLoop](#eventloop)
  - [Strategy](#strategy)
  - [Events](#events)
- [Application Layer](#application-layer)
  - [BacktestRunner](#backtestrunner)
  - [DataSync](#datasync)
- [Infrastructure](#infrastructure)
  - [DataHandler](#datahandler)
  - [DataFetcher](#datafetcher)
  - [PortfolioSimulator](#portfoliosimulator)
  - [PerformanceAnalyzer](#performanceanalyzer)
- [Indicators](#indicators)
- [CLI Commands](#cli-commands)

---

## Core Components

### EventLoop

**Location**: `jutsu_engine.core.event_loop.EventLoop`

Main backtesting coordinator that processes market data bar-by-bar.

#### Constructor

```python
EventLoop(
    data_handler: DataHandler,
    strategy: Strategy,
    portfolio: PortfolioSimulator
)
```

**Parameters:**
- `data_handler`: Source of historical market data
- `strategy`: Trading strategy instance
- `portfolio`: Portfolio simulator for execution

#### Methods

##### `run()`

Execute the complete backtest loop.

```python
def run() -> None
```

Processes all bars sequentially:
1. Updates portfolio market values
2. Feeds bar to strategy
3. Collects signals
4. Converts signals to orders
5. Executes orders
6. Records portfolio value

##### `get_results()`

Retrieve backtest summary.

```python
def get_results() -> Dict[str, Any]
```

**Returns:** Dictionary with:
- `total_bars`: Number of bars processed
- `total_signals`: Signals generated
- `total_orders`: Orders created
- `total_fills`: Successful fills
- `final_value`: Final portfolio value
- `total_return`: Overall return percentage
- `positions`: Final position holdings
- `cash`: Remaining cash

---

### Strategy

**Location**: `jutsu_engine.core.strategy_base.Strategy`

Base class for all trading strategies.

#### Constructor

```python
Strategy(name: str)
```

**Parameters:**
- `name`: Strategy name for identification

#### Abstract Methods

##### `init()`

Initialize strategy (called before backtest starts).

```python
def init() -> None
```

Use this to set up indicators, load data, or configure parameters.

##### `on_bar(bar: MarketDataEvent)`

Process each market data bar.

```python
def on_bar(bar: MarketDataEvent) -> None
```

**Parameters:**
- `bar`: Latest market data event

Called for every bar in the backtest. Generate signals by calling `buy()` or `sell()`.

#### Trading Methods

##### `buy(symbol: str, quantity: int)`

Generate buy signal.

```python
def buy(symbol: str, quantity: int) -> None
```

**Parameters:**
- `symbol`: Stock ticker
- `quantity`: Number of shares

##### `sell(symbol: str, quantity: int)`

Generate sell signal.

```python
def sell(symbol: str, quantity: int) -> None
```

**Parameters:**
- `symbol`: Stock ticker
- `quantity`: Number of shares

#### Utility Methods

##### `get_closes(lookback: int) -> pd.Series`

Get recent closing prices.

```python
def get_closes(lookback: int = 100) -> pd.Series
```

**Parameters:**
- `lookback`: Number of bars to retrieve

**Returns:** pandas Series of closing prices

##### `has_position(symbol: str) -> bool`

Check if position exists.

```python
def has_position(symbol: str) -> bool
```

**Parameters:**
- `symbol`: Stock ticker

**Returns:** True if position held

##### `get_signals() -> List[SignalEvent]`

Retrieve generated signals.

```python
def get_signals() -> List[SignalEvent]
```

**Returns:** List of signal events

---

### Events

**Location**: `jutsu_engine.core.events`

Event classes for the event-driven architecture.

#### MarketDataEvent

```python
@dataclass
class MarketDataEvent:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    timeframe: str
```

#### SignalEvent

```python
@dataclass
class SignalEvent:
    timestamp: datetime
    symbol: str
    signal_type: str  # 'BUY', 'SELL', 'HOLD'
    quantity: int
    price: Decimal
    strategy_id: str
```

#### OrderEvent

```python
@dataclass
class OrderEvent:
    timestamp: datetime
    symbol: str
    order_type: str  # 'MARKET', 'LIMIT'
    direction: str   # 'BUY', 'SELL'
    quantity: int
    price: Optional[Decimal] = None
```

#### FillEvent

```python
@dataclass
class FillEvent:
    timestamp: datetime
    symbol: str
    direction: str
    quantity: int
    fill_price: Decimal
    commission: Decimal
    slippage: Decimal
```

---

## Application Layer

### BacktestRunner

**Location**: `jutsu_engine.application.backtest_runner.BacktestRunner`

High-level API for running backtests.

#### Constructor

```python
BacktestRunner(config: Dict[str, Any])
```

**Required Config Keys:**
- `symbol`: Stock ticker (str)
- `timeframe`: Bar timeframe (str)
- `start_date`: Start date (datetime)
- `end_date`: End date (datetime)
- `initial_capital`: Starting capital (Decimal)

**Optional Config Keys:**
- `commission_per_share`: Commission per share (Decimal, default: 0.01)
- `slippage_percent`: Slippage percentage (Decimal, default: 0.001)
- `database_url`: Database URL (str, default: from config)

#### Methods

##### `run(strategy: Strategy) -> Dict[str, Any]`

Execute complete backtest.

```python
def run(strategy: Strategy) -> Dict[str, Any]
```

**Parameters:**
- `strategy`: Strategy instance to backtest

**Returns:** Dictionary with comprehensive results:
- Performance metrics (return, Sharpe, drawdown, etc.)
- Trade statistics (win rate, profit factor, etc.)
- Event counts
- Configuration details

---

### DataSync

**Location**: `jutsu_engine.application.data_sync.DataSync`

Manages incremental data synchronization.

#### Constructor

```python
DataSync(session: Session)
```

**Parameters:**
- `session`: SQLAlchemy database session

#### Methods

##### `sync_symbol()`

Synchronize data for a symbol.

```python
def sync_symbol(
    fetcher: DataFetcher,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: Optional[datetime] = None,
    force_refresh: bool = False
) -> Dict[str, Any]
```

**Parameters:**
- `fetcher`: DataFetcher implementation
- `symbol`: Stock ticker
- `timeframe`: Bar timeframe
- `start_date`: Start date
- `end_date`: End date (default: today)
- `force_refresh`: Force re-fetch (default: False)

**Returns:** Dictionary with sync results:
- `bars_fetched`: Bars retrieved
- `bars_stored`: New bars written
- `bars_updated`: Existing bars updated
- `start_date`: Actual start date used
- `end_date`: Actual end date used
- `duration_seconds`: Time taken

##### `get_sync_status(symbol: str, timeframe: str) -> Dict[str, Any]`

Get synchronization status.

**Returns:**
- `has_data`: Whether data exists
- `total_bars`: Bar count
- `last_update`: Last sync timestamp
- `last_bar_timestamp`: Most recent bar
- `first_bar_timestamp`: Oldest bar

##### `validate_data()`

Validate data quality.

```python
def validate_data(
    symbol: str,
    timeframe: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]
```

**Returns:**
- `total_bars`: Bars checked
- `valid_bars`: Valid bar count
- `invalid_bars`: Invalid bar count
- `issues`: List of issue descriptions

---

## Infrastructure

### DataHandler

**Location**: `jutsu_engine.data.handlers.base.DataHandler`

Abstract base class for data handlers.

#### Methods

##### `get_next_bar() -> Iterator[MarketDataEvent]`

Yield bars chronologically (prevents lookback bias).

##### `get_latest_bar(symbol: str) -> Optional[MarketDataEvent]`

Get most recent bar for symbol.

##### `get_bars() -> List[MarketDataEvent]`

Get bars for date range.

##### `get_bars_lookback() -> List[MarketDataEvent]`

Get last N bars up to current position.

---

### DataFetcher

**Location**: `jutsu_engine.data.fetchers.base.DataFetcher`

Abstract base class for data fetchers.

#### Methods

##### `fetch_bars() -> List[Dict[str, Any]]`

Fetch historical market data.

```python
def fetch_bars(
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime
) -> List[Dict[str, Any]]
```

**Returns:** List of bar dictionaries with:
- `timestamp`: Bar timestamp (datetime)
- `open`: Opening price (Decimal)
- `high`: Highest price (Decimal)
- `low`: Lowest price (Decimal)
- `close`: Closing price (Decimal)
- `volume`: Trading volume (int)

---

### PortfolioSimulator

**Location**: `jutsu_engine.portfolio.simulator.PortfolioSimulator`

Portfolio state management during backtesting.

#### Constructor

```python
PortfolioSimulator(
    initial_capital: Decimal,
    commission_per_share: Decimal = Decimal('0.01'),
    slippage_percent: Decimal = Decimal('0.001')
)
```

#### Methods

##### `execute_order() -> Optional[FillEvent]`

Execute order and return fill.

```python
def execute_order(
    order: OrderEvent,
    current_bar: MarketDataEvent
) -> Optional[FillEvent]
```

##### `update_market_value(current_bars: Dict[str, MarketDataEvent])`

Update holdings value based on current prices.

##### `get_portfolio_value() -> Decimal`

Get total portfolio value (cash + holdings).

##### `get_total_return() -> float`

Calculate total return percentage.

##### `get_equity_curve() -> List[Tuple[datetime, Decimal]]`

Retrieve equity curve history.

---

### PerformanceAnalyzer

**Location**: `jutsu_engine.performance.analyzer.PerformanceAnalyzer`

Calculate comprehensive performance metrics.

#### Constructor

```python
PerformanceAnalyzer(
    fills: List[FillEvent],
    equity_curve: List[Tuple[datetime, Decimal]],
    initial_capital: Decimal
)
```

#### Methods

##### `calculate_metrics() -> Dict[str, float]`

Calculate all performance metrics.

**Returns:** Dictionary with:

**Return Metrics:**
- `total_return`: Total return percentage
- `annualized_return`: Annualized return
- `final_value`: Final portfolio value
- `initial_capital`: Starting capital

**Risk Metrics:**
- `volatility`: Annualized volatility
- `sharpe_ratio`: Risk-adjusted return (default rf=2%)
- `max_drawdown`: Maximum peak-to-trough decline
- `calmar_ratio`: Return / max drawdown

**Trade Statistics:**
- `total_trades`: Total closed trades
- `winning_trades`: Profitable trade count
- `losing_trades`: Unprofitable trade count
- `win_rate`: Percentage of winning trades
- `profit_factor`: Total wins / total losses
- `avg_win`: Average winning trade
- `avg_loss`: Average losing trade

##### `generate_report() -> str`

Generate formatted performance report.

**Returns:** String with formatted metrics

---

## Indicators

**Location**: `jutsu_engine.indicators.technical`

All functions accept `Union[pd.Series, List]` and return `pd.Series`.

### Simple Moving Average (SMA)

```python
def sma(data: Union[pd.Series, List], period: int) -> pd.Series
```

### Exponential Moving Average (EMA)

```python
def ema(data: Union[pd.Series, List], period: int) -> pd.Series
```

### Relative Strength Index (RSI)

```python
def rsi(data: Union[pd.Series, List], period: int = 14) -> pd.Series
```

### Moving Average Convergence Divergence (MACD)

```python
def macd(
    data: Union[pd.Series, List],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]
```

**Returns:** (macd_line, signal_line, histogram)

### Bollinger Bands

```python
def bollinger_bands(
    data: Union[pd.Series, List],
    period: int = 20,
    num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]
```

**Returns:** (upper_band, middle_band, lower_band)

### Average True Range (ATR)

```python
def atr(
    high: Union[pd.Series, List],
    low: Union[pd.Series, List],
    close: Union[pd.Series, List],
    period: int = 14
) -> pd.Series
```

### Stochastic Oscillator

```python
def stochastic(
    high: Union[pd.Series, List],
    low: Union[pd.Series, List],
    close: Union[pd.Series, List],
    k_period: int = 14,
    d_period: int = 3
) -> tuple[pd.Series, pd.Series]
```

**Returns:** (%K, %D)

### On-Balance Volume (OBV)

```python
def obv(
    close: Union[pd.Series, List],
    volume: Union[pd.Series, List]
) -> pd.Series
```

---

## CLI Commands

### vibe init

Initialize database schema.

```bash
vibe init [--db-url URL]
```

**Options:**
- `--db-url`: Database URL (default: from config)

### vibe sync

Synchronize market data from Schwab API.

```bash
vibe sync --symbol SYMBOL --timeframe TIMEFRAME --start DATE [OPTIONS]
```

**Required:**
- `--symbol`: Stock ticker
- `--timeframe`: Bar timeframe (1m, 5m, 1H, 1D, etc.)
- `--start`: Start date (YYYY-MM-DD)

**Optional:**
- `--end`: End date (default: today)
- `--force`: Force refresh, ignore existing data

### vibe status

Check data synchronization status.

```bash
vibe status --symbol SYMBOL [--timeframe TIMEFRAME]
```

**Options:**
- `--symbol`: Stock ticker (required)
- `--timeframe`: Bar timeframe (default: 1D)

### vibe validate

Validate data quality.

```bash
vibe validate --symbol SYMBOL [OPTIONS]
```

**Required:**
- `--symbol`: Stock ticker

**Optional:**
- `--timeframe`: Bar timeframe (default: 1D)
- `--start`: Start date for validation
- `--end`: End date for validation

### vibe backtest

Run a backtest.

```bash
vibe backtest --symbol SYMBOL --start DATE --end DATE [OPTIONS]
```

**Required:**
- `--symbol`: Stock ticker
- `--start`: Backtest start date (YYYY-MM-DD)
- `--end`: Backtest end date (YYYY-MM-DD)

**Optional:**
- `--timeframe`: Bar timeframe (default: 1D)
- `--capital`: Initial capital (default: 100000)
- `--strategy`: Strategy name (default: sma_crossover)
- `--short-period`: Short SMA period (default: 20)
- `--long-period`: Long SMA period (default: 50)
- `--position-size`: Shares per trade (default: 100)
- `--commission`: Commission per share (default: 0.01)
- `--output`: Output file for results (JSON)

---

## Configuration

### Environment Variables (.env)

```
SCHWAB_API_KEY=your_api_key
SCHWAB_API_SECRET=your_api_secret
DATABASE_URL=sqlite:///data/market_data.db
LOG_LEVEL=INFO
ENV=development
```

### Config File (config/config.yaml)

```yaml
backtesting:
  defaults:
    initial_capital: 100000
    commission_per_share: 0.01
    slippage_percent: 0.001

database:
  url: sqlite:///data/market_data.db
  echo: false

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

---

## Error Handling

### Common Exceptions

- `ValueError`: Invalid parameters or configuration
- `RuntimeError`: API failures, authentication errors
- `FileNotFoundError`: Missing config files
- `DatabaseError`: Database connection or query failures

### Best Practices

1. Always validate input parameters
2. Use try-except blocks for external API calls
3. Log errors with context
4. Clean up resources (database sessions, file handles)
5. Provide meaningful error messages

---

## Examples

See README.md and example scripts in `scripts/` directory for complete usage examples.
