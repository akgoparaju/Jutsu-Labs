# System Design - Jutsu Labs Backtesting Engine

> Comprehensive architectural documentation for the Vibe modular backtesting engine

**Version:** 1.0 (MVP Phase 1 Complete)
**Last Updated:** January 1, 2025
**Authors:** Anil Goparaju, Padma Priya Garnepudi

**Status**: ✅ MVP Phase 1 Complete - All 10 core components implemented

---

## Table of Contents

1. [Overview & Goals](#1-overview--goals)
2. [Architecture Layers](#2-architecture-layers)
3. [Database Design](#3-database-design)
4. [Data Flow Architecture](#4-data-flow-architecture)
5. [Module Responsibilities](#5-module-responsibilities)
6. [Communication Patterns](#6-communication-patterns)
7. [Technology Stack](#7-technology-stack)
8. [Deployment Architecture](#8-deployment-architecture)
9. [Evolution Path](#9-evolution-path)
10. [Design Decisions & Trade-offs](#10-design-decisions--trade-offs)

---

## 1. Overview & Goals

### 1.1 Project Vision

Vibe is a modular backtesting engine designed to empower solo developers and small teams to rapidly prototype, test, and iterate on trading strategies. It prioritizes **flexibility** and **pluggable components** over monolithic, one-size-fits-all solutions.

### 1.2 Core Principles

1. **Modularity over Monolith**: Every core component (data, strategy, risk, metrics) is an independent module that can be swapped out
2. **Simplicity & Clarity**: Core engine is simple, well-documented, and easy to understand
3. **Expandability First**: Design assumes new data sources, strategies, and analysis tools will be added later
4. **Trustworthy & Transparent**: Calculations for PnL, drawdown, and metrics are simple, clear, and auditable
5. **Data Integrity**: Financial data requires precision - use `Decimal`, validate inputs, maintain audit trails

### 1.3 Success Criteria

- ✅ Can fetch and store market data from multiple sources
- ✅ Can run backtests without network access (reads from database)
- ✅ Can easily add new strategies without modifying core code
- ✅ Produces reliable, transparent performance metrics
- ✅ Supports multiple entry points (library, CLI, API, UI)
- ✅ Maintains >80% test coverage
- ✅ Clear separation between layers enables independent evolution

---

## 2. Architecture Layers

### 2.1 Hexagonal/Ports & Adapters Pattern

Vibe uses the **Hexagonal Architecture** (also known as Ports & Adapters) to achieve clean separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                     Layer 4: Entry Points                    │
│                        (Adapters)                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   Library   │  │     CLI     │  │  REST API   │          │
│  │   Import    │  │   (Click)   │  │  (FastAPI)  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
                            ↓ depends on
┌─────────────────────────────────────────────────────────────┐
│                 Layer 3: Infrastructure                      │
│                    (External Systems)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Data Handlers│  │  Indicators  │  │  Strategies  │       │
│  │ (Schwab,CSV) │  │   (TA-Lib)   │  │   (Custom)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ┌──────────────┐                                            │
│  │   Database   │                                            │
│  │ (SQLAlchemy) │                                            │
│  └──────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
                            ↓ depends on
┌─────────────────────────────────────────────────────────────┐
│                  Layer 2: Application                        │
│                     (Use Cases)                              │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ BacktestRunner   │  │   DataSync       │                 │
│  │ (Orchestration)  │  │ (Data Fetching)  │                 │
│  └──────────────────┘  └──────────────────┘                 │
│  ┌──────────────────┐                                        │
│  │ StrategyOptimizer│  (Future)                             │
│  └──────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓ depends on
┌─────────────────────────────────────────────────────────────┐
│                   Layer 1: Core Domain                       │
│                   (Business Logic)                           │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │  EventLoop  │  │ PortfolioSimulator│  │PerformanceAnalyzer│
│  │(Coordinator)│  │  (State Mgmt)    │  │   (Metrics)    │ │
│  └─────────────┘  └──────────────────┘  └────────────────┘ │
│  ┌─────────────┐  ┌──────────────────┐                      │
│  │  Strategy   │  │     Events       │                      │
│  │(Base Class) │  │  (Definitions)   │                      │
│  └─────────────┘  └──────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Dependency Rule

**Outer layers depend on inner layers, NEVER the reverse.**

This means:
- **Entry Points** know about **Application** and **Domain**
- **Infrastructure** implements **Domain** interfaces but doesn't dictate them
- **Application** uses **Domain** objects
- **Domain** knows nothing about outer layers (pure business logic)

**Benefits:**
- Core business logic is testable without databases or external APIs
- Can swap implementations (SQLite → PostgreSQL, Schwab → Yahoo Finance) without changing core
- Easy to add new entry points (API, UI) without modifying existing code

### 2.3 Layer Responsibilities

#### Layer 1: Core Domain
- **Pure business logic** - No external dependencies
- **Event definitions** - MarketDataEvent, SignalEvent, OrderEvent
- **EventLoop** - Coordinates bar-by-bar processing
- **Strategy base classes** - Interfaces all strategies must implement
- **Portfolio state management** - Track positions, cash, PnL
- **Performance calculations** - Sharpe, drawdown, win rate

##### Strategy-Portfolio Separation of Concerns

**Architectural Decision (2025-11-04)**:

The Core layer separates trading intent (Strategy) from execution constraints (Portfolio):

- **Strategy Responsibility**:
  - Determine WHEN to trade (entry/exit signals)
  - Determine HOW MUCH to allocate (portfolio_percent: 0.0-1.0)
  - Focus on business logic and indicators

- **Portfolio Responsibility**:
  - Determine HOW MANY SHARES to trade (quantity calculation)
  - Apply margin requirements (150% for shorts)
  - Handle cash constraints and position limits
  - Focus on execution and risk management

**Benefits**:
1. **Separation of Concerns**: Strategy = business logic, Portfolio = execution logic
2. **Simplification**: Strategies ~15 lines simpler (no position sizing code)
3. **Centralization**: Single source of truth for margin requirements
4. **Scalability**: Adding new constraints only requires Portfolio changes

**API**:
```python
# Strategy outputs signals with allocation %
self.buy('AAPL', Decimal('0.8'))  # 80% of portfolio
self.sell('AAPL', Decimal('0.0'))  # Close position

# Portfolio calculates actual shares
# For LONG: shares = (portfolio_value * 0.8) / (price + commission)
# For SHORT: shares = (portfolio_value * 0.8) / (price * 1.5 + commission)
```

**Breaking Change**: Existing strategies must update from `buy(symbol, quantity)` to `buy(symbol, portfolio_percent)`.

#### Layer 2: Application
- **Use case orchestration** - Coordinates domain objects to achieve goals
- **BacktestRunner** - Runs full backtest from start to finish
- **DataSync** - Fetches data from APIs and stores in database
- **StrategyOptimizer** - (Future) Runs parameter sweeps

#### Layer 3: Infrastructure
- **Data handlers** - Concrete implementations for Schwab, CSV, etc.
- **Database** - SQLAlchemy models and repository pattern
- **Indicators** - Stateless functions (SMA, RSI, EMA)
- **Strategies** - Concrete strategy implementations (SMA Crossover, etc.)

#### Layer 4: Entry Points
- **Library import** - Use jutsu_engine as Python library
- **CLI** - Command-line interface with Click/Typer
- **REST API** - (Future) FastAPI endpoints
- **Web UI** - (Future) Streamlit or React dashboard

---

## 3. Database Design

### 3.1 Schema Overview

We use a **database-first approach** to market data. Data is fetched once from external APIs and stored permanently, enabling:
- **Offline backtesting** (no network required)
- **Incremental updates** (only fetch new bars, not entire history)
- **Data lineage tracking** (know source and fetch time)
- **Performance** (fast local queries vs slow API calls)

### 3.2 Table: `market_data`

Stores OHLCV (Open, High, Low, Close, Volume) bars.

```sql
CREATE TABLE market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,      -- '1D', '1H', '5m', etc.
    timestamp DATETIME NOT NULL,
    open DECIMAL(18,6) NOT NULL,         -- Use DECIMAL, not FLOAT
    high DECIMAL(18,6) NOT NULL,
    low DECIMAL(18,6) NOT NULL,
    close DECIMAL(18,6) NOT NULL,
    volume BIGINT NOT NULL,
    data_source VARCHAR(20) NOT NULL,    -- 'schwab', 'csv', 'yahoo', etc.
    created_at DATETIME NOT NULL,        -- When we fetched this data
    UNIQUE(symbol, timeframe, timestamp) -- Prevent duplicates
);

CREATE INDEX idx_market_data_lookup
ON market_data(symbol, timeframe, timestamp);
```

**Design Rationale:**
- `DECIMAL(18,6)` for prices: Financial precision, no floating-point rounding errors
- `UNIQUE` constraint: Prevents duplicate bars
- `Index`: Fast queries by symbol+timeframe+timestamp (most common lookup pattern)
- `data_source`: Track where data came from (audit trail)
- `created_at`: Track when we fetched it (data freshness)

### 3.3 Table: `data_metadata`

Tracks what data we have, enabling incremental updates.

```sql
CREATE TABLE data_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    data_source VARCHAR(20) NOT NULL,
    first_available_date DATETIME,       -- Earliest bar we have
    last_updated_date DATETIME,          -- Latest bar we have
    total_bars INTEGER DEFAULT 0,
    last_fetch_timestamp DATETIME,       -- Last time we checked API
    is_complete BOOLEAN DEFAULT TRUE,    -- Data quality flag
    UNIQUE(symbol, timeframe, data_source)
);
```

**Design Rationale:**
- `first_available_date` & `last_updated_date`: Define data range
- `total_bars`: Sanity check for data completeness
- `last_fetch_timestamp`: Track API access (respect rate limits)
- `is_complete`: Flag for data quality issues (gaps, missing bars)

### 3.4 Incremental Update Logic

```python
def sync_data(symbol: str, timeframe: str, source: str = 'schwab'):
    # 1. Check metadata
    metadata = db.get_metadata(symbol, timeframe, source)

    if metadata:
        # We have data - fetch incrementally
        fetch_from = metadata.last_updated_date + timedelta(days=1)
        logger.info(f"Incremental update for {symbol}:{timeframe} from {fetch_from}")
    else:
        # First time - fetch all historical
        fetch_from = datetime.now() - timedelta(days=365*10)  # 10 years
        logger.info(f"Initial fetch for {symbol}:{timeframe} from {fetch_from}")

    # 2. Fetch from API
    fetcher = get_fetcher(source)  # SchwabDataFetcher, CSVDataFetcher, etc.
    new_bars = fetcher.fetch(symbol, timeframe, fetch_from, datetime.now())

    # 3. Validate and store
    valid_bars = []
    for bar in new_bars:
        if validate_bar(bar):  # Check format, range, no gaps
            db.insert_bar(bar)
            valid_bars.append(bar)
        else:
            logger.warning(f"Invalid bar detected for {symbol}: {bar}")

    # 4. Update metadata
    if valid_bars:
        db.update_metadata(
            symbol=symbol,
            timeframe=timeframe,
            source=source,
            last_updated_date=valid_bars[-1].timestamp,
            total_bars=db.count_bars(symbol, timeframe),
            last_fetch_timestamp=datetime.now()
        )
```

**Benefits:**
- Only fetch new data (respects API rate limits)
- Audit trail (know when data was fetched)
- Data validation (catch errors before storage)
- Idempotent (safe to run multiple times)

### 3.5 Database Technology Evolution

**MVP (Phase 1): SQLite**
- File-based, zero configuration
- Perfect for single user, development
- Up to ~1M bars performs well
- Easy to version control (single `.db` file)

**Production (Phase 2+): PostgreSQL**
- Multi-user support
- Better performance for large datasets (>10M bars)
- Advanced features (replication, partitioning)
- Production-grade reliability

**Migration Path:**
- SQLAlchemy ORM abstracts database
- Configuration change only (no code changes)
- Alembic migrations for schema evolution

---

## 4. Data Flow Architecture

### 4.1 Data Sync Flow

```
┌──────────────┐
│  User/Cron   │ Triggers data sync
└──────┬───────┘
       │
       ↓
┌──────────────┐
│  DataSync    │ Application layer
│  (Use Case)  │
└──────┬───────┘
       │
       ↓
┌──────────────────────────────────────┐
│  Check metadata                       │
│  - Do we have data for this symbol?  │
│  - What's the latest date we have?   │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  DataFetcher (Schwab API)            │
│  - Fetch bars from last_date to now  │
│  - Or fetch all historical if new    │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  Validation                           │
│  - Check format (OHLCV complete)     │
│  - Verify range (no negative prices) │
│  - Detect gaps (missing timestamps)  │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  Database Insert                      │
│  - Batch insert (performance)        │
│  - UNIQUE constraint prevents dups   │
│  - Log insert count                  │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  Update Metadata                      │
│  - Set last_updated_date             │
│  - Increment total_bars              │
│  - Set last_fetch_timestamp          │
└──────────────────────────────────────┘
```

### 4.2 Backtest Execution Flow

```
┌──────────────┐
│     User     │ Runs backtest
└──────┬───────┘
       │
       ↓
┌──────────────────────────────────────┐
│  BacktestRunner                       │
│  - Initialize with config             │
│  - Load strategy                      │
│  - Create portfolio simulator         │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  DatabaseDataHandler                  │
│  - Query market_data table            │
│  - Load bars for date range           │
│  - Prepare iterator                   │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  EventLoop (Bar-by-Bar)               │
│  ┌────────────────────────────────┐  │
│  │ FOR EACH BAR:                  │  │
│  │ 1. Emit MarketDataEvent        │  │
│  │ 2. Strategy.on_bar()           │  │
│  │    → Generates SignalEvent     │  │
│  │      with portfolio_percent    │  │
│  │ 3. Process signals             │  │
│  │ 4. Update portfolio            │  │
│  │    → Calculates shares from %  │  │
│  │ 5. Log state                   │  │
│  └────────────────────────────────┘  │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  PortfolioSimulator                   │
│  - Receive SignalEvent w/ portfolio_% │
│  - Calculate shares (with margin)     │
│  - Execute trades                     │
│  - Update positions & cash            │
│  - Calculate mark-to-market PnL       │
│  - Log every transaction              │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────┐
│  PerformanceAnalyzer                  │
│  - Read trade log                     │
│  - Read portfolio history             │
│  - Calculate metrics                  │
│  - Return JSON results                │
└──────┬───────────────────────────────┘
       │
       ↓
┌──────────────┐
│  Results     │ JSON output
│  (Metrics)   │
└──────────────┘
```

**Key Points:**
- **Separation**: Data fetching is separate from backtesting
- **No network**: Backtests read from database, not API
- **Sequential**: EventLoop ensures no lookback bias (bar-by-bar)
- **Stateful**: PortfolioSimulator maintains state, Strategy is stateless
- **Audit trail**: Every trade logged with timestamp

---

## 5. Module Responsibilities

### 5.1 DataHandler (The "Source")

**Job:** Fetch market data from any source and feed it, bar by bar, to the EventLoop.

**Interface:**
```python
class DataHandler(ABC):
    @abstractmethod
    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        """Yield bars one at a time for EventLoop"""
        pass

    @abstractmethod
    def get_latest_bar(self, symbol: str) -> MarketDataEvent:
        """Get most recent bar for a symbol"""
        pass

    @abstractmethod
    def get_bars(self, symbol: str, lookback: int) -> List[MarketDataEvent]:
        """Get last N bars for indicator calculation"""
        pass
```

**Implementations:**
- `DatabaseDataHandler`: Reads from SQLite/PostgreSQL
- `SchwabDataFetcher`: Fetches from Schwab API (for syncing)
- `CSVDataHandler`: Reads from CSV files
- (Future) `YahooFinanceDataHandler`, `BinanceDataHandler`, etc.

**Key Design:**
- Standardized output format (MarketDataEvent with OHLCV)
- Iterator pattern (memory-efficient for large datasets)
- Pluggable (swap sources without changing EventLoop)

### 5.2 StrategyEngine (The "Brain")

**Job:** Hold and execute trading logic.

**Interface:**
```python
class Strategy(ABC):
    @abstractmethod
    def init(self):
        """Initialize strategy (set parameters, load data)"""
        pass

    @abstractmethod
    def on_bar(self, bar: MarketDataEvent):
        """Process new bar, generate signals"""
        pass

    def buy(self, symbol: str, quantity: int):
        """Send buy signal to portfolio"""
        self._emit_signal(SignalEvent('BUY', symbol, quantity))

    def sell(self, symbol: str, quantity: int):
        """Send sell signal to portfolio"""
        self._emit_signal(SignalEvent('SELL', symbol, quantity))
```

**Implementations:**
- `SMA_Crossover`: Simple moving average crossover
- `RSI_Strategy`: RSI-based mean reversion
- (Future) User-defined strategies

**Key Design:**
- Strategy is "dumb" - just sends signals, doesn't manage state
- Receives `MarketDataEvent`, returns `SignalEvent`
- Can call indicators from `IndicatorLibrary`
- Base class provides helper methods (get_closes, has_position, etc.)

### 5.3 IndicatorLibrary (The "Toolbox")

**Job:** Collection of stateless functions for technical analysis.

**Interface:**
```python
# All functions are stateless - pure functions
def calculate_sma(prices: pd.Series, period: int) -> float:
    """Calculate Simple Moving Average"""
    return prices.tail(period).mean()

def calculate_ema(prices: pd.Series, period: int) -> float:
    """Calculate Exponential Moving Average"""
    return prices.ewm(span=period, adjust=False).mean().iloc[-1]

def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """Calculate Relative Strength Index"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs)).iloc[-1]
```

**Key Design:**
- Stateless (no side effects, same input → same output)
- Easy to test (pure functions)
- Easy to extend (copy/paste from TA-Lib, pandas-ta)
- Not tied to Strategy or EventLoop

### 5.4 PortfolioSimulator (The "Bookkeeper")

**Job:** Receive trade signals, execute fills, track portfolio state.

**Responsibilities:**
- Maintain cash and positions
- Execute trades (check sufficient cash, apply commission/slippage)
- Calculate mark-to-market PnL at end of each bar
- Log all transactions (audit trail)
- Emit `FillEvent` when trades execute

**State:**
```python
{
    'cash': Decimal('95000.00'),
    'positions': {
        'AAPL': 100,  # 100 shares of AAPL
    },
    'portfolio_value': Decimal('105000.00'),  # cash + positions
    'trades': [...]  # List of all executed trades
}
```

**Key Design:**
- PortfolioSimulator is "smart" - manages all state
- Strategy is "dumb" - just sends signals
- Handles edge cases (insufficient cash, position limits)
- Immutable trade log (financial audit requirement)

### 5.5 PerformanceAnalyzer (The "Report Card")

**Job:** Take final trade log and portfolio history, generate performance metrics.

**Metrics (Phase 1):**
- Total Return (%)
- Annualized Return (%)
- Sharpe Ratio
- Max Drawdown (%)
- Win Rate (%)
- Profit Factor

**Metrics (Phase 2):**
- Sortino Ratio (downside deviation)
- Calmar Ratio (return / max drawdown)
- Rolling Sharpe Ratio
- Drawdown duration
- Monte Carlo confidence intervals

**Key Design:**
- Run *after* backtest completes (not during EventLoop)
- Completely separate from EventLoop (no performance impact)
- Returns structured JSON (easy to parse, visualize, store)

---

## 6. Communication Patterns

### 6.1 MVP: In-Process EventLoop

**Pattern:** Publish-Subscribe within single Python process

```python
class EventLoop:
    def __init__(self):
        self.subscribers = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Callable):
        """Register handler for event type"""
        self.subscribers[event_type].append(handler)

    def publish(self, event: Event):
        """Notify all subscribers of event"""
        for handler in self.subscribers[event.type]:
            handler(event)

    def run(self, data_handler: DataHandler, strategy: Strategy):
        """Main backtest loop"""
        for bar in data_handler.get_next_bar():
            # 1. Publish market data event
            self.publish(MarketDataEvent(bar))

            # 2. Strategy processes bar, may emit signals
            strategy.on_bar(bar)

            # 3. Portfolio processes signals, emits fills
            # (Subscribers handle this internally)

            # 4. Update portfolio value (mark-to-market)
```

**Benefits:**
- Fast (no network overhead)
- Simple (easy to debug)
- Testable (mock subscribers)
- Perfect for MVP

**Limitations:**
- All modules must run in same process
- Can't distribute across machines
- Python-only (no polyglot support)

### 6.2 Future: REST API Wrapper

**Pattern:** HTTP API for external access

```python
# FastAPI wrapper around core engine
@app.post("/backtest")
async def run_backtest(config: BacktestConfig):
    runner = BacktestRunner(config.dict())
    results = runner.run(strategy=load_strategy(config.strategy))
    return results

@app.post("/data/sync")
async def sync_data(symbol: str, timeframe: str):
    syncer = DataSync()
    syncer.sync_symbol(symbol, timeframe)
    return {"status": "success"}
```

**Benefits:**
- Language-agnostic clients
- Network-accessible (UI can be separate service)
- Horizontal scaling (multiple API instances)

**Limitations:**
- Network latency (not suitable for real-time trading)
- More complex deployment
- Stateless API (backtest state must be stored)

### 6.3 Future: Message Queue (Optional)

**Pattern:** Async messaging for distributed processing

**Use Cases:**
- Multiple strategies running simultaneously
- Parameter optimization (hundreds of backtests in parallel)
- Live trading (event-driven architecture)

**Technology Options:**
- RabbitMQ: Traditional message broker
- Redis Pub/Sub: Simple, fast, good for caching too
- Apache Kafka: High-throughput, persistent event log

**Decision:** Defer to Phase 3/4 (not needed for MVP)

---

## 7. Technology Stack

### 7.1 Core Technologies

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **Language** | Python 3.10+ | Type hints, dataclasses, rich ecosystem |
| **Database ORM** | SQLAlchemy 2.0+ | Database abstraction, mature, well-documented |
| **Database (MVP)** | SQLite | Zero config, file-based, perfect for development |
| **Database (Prod)** | PostgreSQL | Production-grade, scalable, advanced features |
| **Data API** | schwab-py | Official Schwab API wrapper |
| **Data Analysis** | pandas, numpy | Industry standard for financial data |
| **Configuration** | python-dotenv, PyYAML | Environment variables + YAML configs |

### 7.2 Development Tools

| Tool | Purpose |
|------|---------|
| **pytest** | Testing framework |
| **pytest-cov** | Code coverage |
| **black** | Code formatting |
| **isort** | Import sorting |
| **mypy** | Type checking |
| **flake8** | Linting |
| **pylint** | Additional linting |

### 7.3 Future Technologies

| Component | Technology | Phase |
|-----------|-----------|-------|
| **CLI** | Click or Typer | Phase 1 (MVP) |
| **REST API** | FastAPI | Phase 2 |
| **Web UI** | Streamlit or React | Phase 3 |
| **Message Queue** | Redis or RabbitMQ | Phase 3/4 |
| **Containerization** | Docker + Docker Compose | Phase 2/3 |
| **Orchestration** | Kubernetes (optional) | Phase 4 |

---

## 8. Deployment Architecture

### 8.1 Development (Current)

```
┌─────────────────────────────────┐
│      Local Machine              │
│                                 │
│  ┌──────────────────────────┐  │
│  │   jutsu_engine (library)  │  │
│  │   ├─ Core               │  │
│  │   ├─ Application        │  │
│  │   ├─ Infrastructure     │  │
│  │   └─ Entry points       │  │
│  └──────────────────────────┘  │
│                                 │
│  ┌──────────────────────────┐  │
│  │   SQLite Database        │  │
│  │   (data/market_data.db)  │  │
│  └──────────────────────────┘  │
│                                 │
│  ┌──────────────────────────┐  │
│  │   Logs                   │  │
│  │   (logs/*.log)           │  │
│  └──────────────────────────┘  │
└─────────────────────────────────┘
```

**Execution:**
```bash
# As library
python my_backtest.py

# As CLI
vibe backtest --symbol AAPL --strategy SMA
```

### 8.2 Production (Phase 2+)

```
┌──────────────────────────────────────────────────────────┐
│                    Docker Compose                         │
│                                                           │
│  ┌─────────────────────┐   ┌─────────────────────────┐  │
│  │  vibe-api           │   │  vibe-ui                │  │
│  │  (FastAPI)          │   │  (Streamlit/React)      │  │
│  │  Port: 8000         │   │  Port: 8080             │  │
│  └──────────┬──────────┘   └───────────┬─────────────┘  │
│             │                           │                │
│             └───────────┬───────────────┘                │
│                         │                                │
│              ┌──────────▼──────────┐                     │
│              │  jutsu-engine-core   │                     │
│              │  (Shared Library)   │                     │
│              └──────────┬──────────┘                     │
│                         │                                │
│              ┌──────────▼──────────┐                     │
│              │  PostgreSQL         │                     │
│              │  Port: 5432         │                     │
│              └──────────┬──────────┘                     │
│                         │                                │
│              ┌──────────▼──────────┐                     │
│              │  Redis (cache)      │                     │
│              │  Port: 6379         │                     │
│              └─────────────────────┘                     │
│                                                           │
│  Volumes:                                                 │
│  - ./data → PostgreSQL data                              │
│  - ./logs → Application logs                             │
└──────────────────────────────────────────────────────────┘
```

**docker-compose.yml (simplified):**
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: jutsu_engine
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ./data/postgres:/var/lib/postgresql/data

  vibe-api:
    build: ./docker/Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/jutsu_engine
    depends_on:
      - postgres

  vibe-ui:
    build: ./docker/Dockerfile.ui
    ports:
      - "8080:8080"
    environment:
      API_URL: http://vibe-api:8000
    depends_on:
      - vibe-api
```

---

## 9. Evolution Path

### 9.1 Phase 1: MVP (Weeks 1-4) ✅

**Goal:** End-to-end backtest with single strategy

**Deliverables:**
- [x] Project structure and documentation
- [x] Database schema (SQLite)
- [ ] Data sync with Schwab API
- [ ] Core EventLoop
- [ ] Portfolio Simulator
- [ ] Indicator library (SMA, EMA, RSI)
- [ ] SMA Crossover strategy
- [ ] Performance Analyzer (basic metrics)
- [ ] CLI entry point
- [ ] Unit tests (>80% coverage)

**Success Metric:** Can run backtest on AAPL with SMA strategy, get metrics

### 9.2 Phase 2: Service Layer (Weeks 5-8)

**Goal:** REST API and advanced features

**Deliverables:**
- [ ] FastAPI wrapper around core engine
- [ ] PostgreSQL migration
- [ ] Parameter optimization framework
- [ ] Advanced metrics (Sortino, Calmar, rolling stats)
- [ ] Multiple data sources (CSV, Yahoo Finance)
- [ ] Improved logging and monitoring

**Success Metric:** Can run backtests via HTTP API, optimize strategy parameters

### 9.3 Phase 3: UI & Distribution (Weeks 9-12)

**Goal:** Web dashboard and Docker deployment

**Deliverables:**
- [ ] Streamlit dashboard for visualization
- [ ] Multi-container Docker setup
- [ ] Scheduled backtest jobs (cron)
- [ ] Monte Carlo simulation
- [ ] Walk-forward analysis
- [ ] Performance dashboards

**Success Metric:** Non-technical users can run and visualize backtests via web UI

### 9.4 Phase 4: Production Features (Months 4-6)

**Goal:** Live trading preparation

**Deliverables:**
- [ ] Paper trading integration
- [ ] Advanced risk management (position limits, stop-loss)
- [ ] Portfolio optimization (multi-asset allocation)
- [ ] Real-time data streaming
- [ ] Live trading (with extensive safeguards)

**Success Metric:** Can paper trade strategies in real-time

---

## 10. Design Decisions & Trade-offs

### 10.1 Database-First vs API-First Data

**Decision:** Store data in database, not fetch on-demand

**Rationale:**
- ✅ Faster backtests (local queries vs network calls)
- ✅ Offline testing (no network required)
- ✅ Respect API rate limits (fetch once, use many times)
- ✅ Data lineage (know source and fetch time)
- ❌ More storage (database file grows)
- ❌ Data staleness (must sync manually)

**Mitigation:**
- Incremental updates (only fetch new data)
- Automated sync jobs (cron/scheduler)
- Data quality monitoring (detect gaps)

### 10.2 EventLoop vs Microservices

**Decision:** In-process EventLoop for MVP, abstractable for future distribution

**Rationale:**
- ✅ Simple (easier to develop and debug)
- ✅ Fast (no network overhead)
- ✅ Perfect for solo developer use case
- ❌ Not distributed (all modules in one process)
- ❌ Python-only (can't use other languages)

**Mitigation:**
- Design interfaces (ports) that can be wrapped with REST/message queue later
- Keep EventLoop logic simple and testable
- Document evolution path to distributed architecture

### 10.3 SQLite vs PostgreSQL

**Decision:** SQLite for MVP, PostgreSQL for production

**Rationale:**
- ✅ SQLite: Zero config, file-based, easy to version control
- ✅ PostgreSQL: Production-grade, multi-user, better performance at scale
- ✅ SQLAlchemy: Abstracts database, easy to swap

**Migration Path:**
- Configuration change only
- Alembic migrations for schema evolution
- Backward compatibility with SQLite for development

### 10.4 Monorepo vs Multi-Repo

**Decision:** Monorepo (single repository for all components)

**Rationale:**
- ✅ Easier to develop (single clone, shared code)
- ✅ Atomic commits (change core + tests together)
- ✅ Simpler for solo developer
- ❌ Harder to scale teams (single repo bottleneck)

**Future:** Can split into multiple repos if team grows

### 10.5 Type Hints vs Dynamic Typing

**Decision:** Full type hints on all public APIs

**Rationale:**
- ✅ IDE autocomplete (better developer experience)
- ✅ Early error detection (mypy catches bugs)
- ✅ Self-documenting (types explain intent)
- ❌ More verbose (more code to write)

**Standard:** All public functions and classes must have type hints

---

## Conclusion

Vibe's architecture prioritizes **modularity**, **data integrity**, and **evolution**. By using proven patterns (Hexagonal Architecture, Repository Pattern, Strategy Pattern) and clean separation of concerns, we ensure:

- Easy to test (mock external dependencies)
- Easy to extend (add strategies, data sources, indicators)
- Easy to scale (start simple, add layers as needed)
- Easy to understand (clear documentation, transparent design)

The system is designed to grow with user needs:
- **Phase 1**: Library + CLI for solo developers
- **Phase 2**: REST API for programmatic access
- **Phase 3**: Web UI for non-technical users
- **Phase 4**: Live trading for production use

Each phase builds on the previous without requiring rewrites, thanks to layered architecture and dependency inversion.

---

**Next Steps:**
- Implement Phase 1 MVP components
- Write comprehensive tests
- Document API with examples
- Gather user feedback and iterate
	