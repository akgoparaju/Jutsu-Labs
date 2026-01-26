# Best Practices - Jutsu Labs Backtesting Engine

> Coding standards, financial data handling, and design patterns for reliable backtesting

**Version:** 1.0
**Last Updated:** October 31, 2025

---

## Table of Contents

1. [Data Integrity Principles](#1-data-integrity-principles)
2. [Financial Data Handling](#2-financial-data-handling)
3. [Modular Design Patterns](#3-modular-design-patterns)
4. [Testing Strategy](#4-testing-strategy)
5. [Performance Considerations](#5-performance-considerations)
6. [Security & Credentials](#6-security--credentials)
7. [Error Handling](#7-error-handling)
8. [Logging Best Practices](#8-logging-best-practices)
9. [Code Style & Standards](#9-code-style--standards)
10. [Preventing Lookback Bias](#10-preventing-lookback-bias)

---

## 1. Data Integrity Principles

### 1.1 Immutability

**Rule:** Historical data must NEVER be modified once stored.

```python
# ❌ BAD: Modifying historical data
def fix_bad_data(symbol, date, new_close):
    db.update(MarketData)
      .where(symbol=symbol, date=date)
      .set(close=new_close)

# ✅ GOOD: Mark as invalid, insert corrected data with new source
def correct_data(symbol, date, correct_close):
    # Mark original as invalid
    db.update(MarketData)
      .where(symbol=symbol, date=date)
      .set(is_valid=False)

    # Insert corrected data with different source
    db.insert(MarketData(
        symbol=symbol,
        date=date,
        close=correct_close,
        data_source='manual_correction',
        created_at=datetime.now()
    ))
```

**Rationale:**
- Audit trail requirement for financial data
- Can trace data lineage (original vs corrected)
- Reproducibility (can recreate exact historical backtests)

### 1.2 Validation

**Rule:** Validate ALL incoming data before storage.

```python
from decimal import Decimal

def validate_bar(bar: MarketDataEvent) -> tuple[bool, Optional[str]]:
    """
    Validate OHLCV bar data.
    Returns (is_valid, error_message)
    """
    # 1. Required fields present
    if not all([bar.open, bar.high, bar.low, bar.close, bar.volume]):
        return False, "Missing required OHLCV fields"

    # 2. Prices are positive
    if any(p <= 0 for p in [bar.open, bar.high, bar.low, bar.close]):
        return False, "Prices must be positive"

    # 3. High is highest, Low is lowest
    if not (bar.low <= bar.open <= bar.high and
            bar.low <= bar.close <= bar.high):
        return False, "OHLC relationship invalid (High must be highest, Low must be lowest)"

    # 4. Volume is non-negative
    if bar.volume < 0:
        return False, "Volume cannot be negative"

    # 5. Reasonable price limits (stock between $0.01 and $100,000)
    if not (Decimal('0.01') <= bar.close <= Decimal('100000')):
        return False, f"Price {bar.close} outside reasonable range"

    return True, None


# Usage in data sync
is_valid, error = validate_bar(bar)
if is_valid:
    db.insert_bar(bar)
else:
    logger.warning(f"Invalid bar for {bar.symbol} on {bar.timestamp}: {error}")
    # Store in error table for investigation
    db.insert_error(symbol=bar.symbol, timestamp=bar.timestamp, error=error, raw_data=bar)
```

### 1.3 Audit Trail

**Rule:** Log every data modification with timestamp and source.

```python
# Every table has audit fields
class MarketData(Base):
    # ... OHLCV fields ...
    data_source = Column(String(20), nullable=False)   # 'schwab', 'csv', 'manual'
    created_at = Column(DateTime, nullable=False)      # When inserted
    created_by = Column(String(50), default='system')  # Who/what inserted

    # Audit log - separate table
class DataAuditLog(Base):
    __tablename__ = 'data_audit_log'

    id = Column(Integer, primary_key=True)
    action = Column(String(20))  # 'INSERT', 'UPDATE', 'DELETE', 'INVALIDATE'
    table_name = Column(String(50))
    record_id = Column(Integer)
    changed_by = Column(String(50))
    changed_at = Column(DateTime, default=datetime.utcnow)
    old_value = Column(JSON)
    new_value = Column(JSON)
```

### 1.4 Deduplication

**Rule:** Prevent duplicate bars using database constraints.

```sql
-- Unique constraint prevents duplicates
CREATE UNIQUE INDEX idx_unique_bar
ON market_data(symbol, timeframe, timestamp);
```

```python
# Handle duplicate gracefully
try:
    db.insert(bar)
except IntegrityError as e:
    if 'unique constraint' in str(e).lower():
        logger.debug(f"Bar already exists for {bar.symbol} on {bar.timestamp}, skipping")
    else:
        raise  # Re-raise if different error
```

### 1.5 Gap Detection

**Rule:** Identify missing bars in time series.

```python
def detect_gaps(symbol: str, timeframe: str) -> List[tuple]:
    """
    Detect missing bars in time series.
    Returns list of (expected_timestamp, actual_next_timestamp) tuples.
    """
    bars = db.query(MarketData)
             .filter_by(symbol=symbol, timeframe=timeframe)
             .order_by(MarketData.timestamp)
             .all()

    gaps = []
    for i in range(len(bars) - 1):
        current = bars[i].timestamp
        next_bar = bars[i + 1].timestamp
        expected = get_next_timestamp(current, timeframe)

        if next_bar != expected:
            gaps.append((expected, next_bar))
            logger.warning(f"Gap detected for {symbol}: expected {expected}, got {next_bar}")

    return gaps


def get_next_timestamp(current: datetime, timeframe: str) -> datetime:
    """Calculate expected next timestamp based on timeframe"""
    if timeframe == '1D':
        # Skip weekends (assuming US market)
        next_day = current + timedelta(days=1)
        while next_day.weekday() >= 5:  # Saturday=5, Sunday=6
            next_day += timedelta(days=1)
        return next_day
    elif timeframe == '1H':
        return current + timedelta(hours=1)
    # ... handle other timeframes
```

---

## 2. Financial Data Handling

### 2.1 Use Decimal for Financial Calculations

**Rule:** NEVER use `float` for prices or monetary amounts.

```python
from decimal import Decimal, ROUND_HALF_UP

# ❌ BAD: Float precision errors
price = 0.1 + 0.2  # = 0.30000000000000004 !!
total = price * 100  # = 30.000000000000004

# ✅ GOOD: Decimal for exact precision
price = Decimal('0.1') + Decimal('0.2')  # = Decimal('0.3')
total = price * 100  # = Decimal('30.0')

# Rounding to 2 decimal places (cents)
amount = Decimal('10.125')
rounded = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)  # 10.13
```

```python
# SQLAlchemy model
class MarketData(Base):
    # ❌ BAD
    # close = Column(Float)

    # ✅ GOOD
    close = Column(Numeric(18, 6))  # 18 total digits, 6 after decimal
```

**Why:**
- Float: `0.1 + 0.2 != 0.3` (binary representation error)
- Decimal: Exact representation, no rounding errors
- Financial regulations require exact calculations
- Prevents accumulation of rounding errors in long backtests

### 2.1.1 Portfolio Allocation Values

Always use `Decimal` for `portfolio_percent`:

```python
from decimal import Decimal

# ✅ CORRECT
self.buy('AAPL', Decimal('0.8'))

# ❌ WRONG (float loses precision)
self.buy('AAPL', 0.8)
```

**Common Allocation Patterns**:
- Full allocation: `Decimal('1.0')` (100%)
- Standard allocation: `Decimal('0.8')` (80%)
- Conservative allocation: `Decimal('0.5')` (50%)
- Close position: `Decimal('0.0')` (0%)

### 2.2 Timezone Handling

**Rule:** Store all timestamps in UTC, convert for display only.

```python
from datetime import datetime, timezone
import pytz

# ❌ BAD: Naive datetime (no timezone)
timestamp = datetime.now()  # Ambiguous!

# ✅ GOOD: UTC timezone-aware
timestamp = datetime.now(timezone.utc)

# Converting to local timezone (for display only)
eastern = pytz.timezone('America/New_York')
local_time = timestamp.astimezone(eastern)

# Database storage
class MarketData(Base):
    timestamp = Column(DateTime(timezone=True), nullable=False)  # Timezone-aware

# Querying with timezone
from sqlalchemy import func
bars = db.query(MarketData)
         .filter(MarketData.timestamp >= datetime(2024, 1, 1, tzinfo=timezone.utc))
         .all()
```

**Why:**
- Unambiguous timestamps (daylight saving time, international users)
- Market data from different exchanges (NYSE, NASDAQ, international)
- Consistent sorting and querying

### 2.3 Corporate Actions (Future)

**Rule:** Account for splits, dividends, and other corporate actions.

```python
# Example split adjustment (Phase 2+)
def adjust_for_split(symbol: str, split_date: datetime, split_ratio: Decimal):
    """
    Adjust historical prices for stock split.
    e.g., 2-for-1 split: all prices before split_date are divided by 2
    """
    bars = db.query(MarketData)
             .filter(
                 MarketData.symbol == symbol,
                 MarketData.timestamp < split_date
             )
             .all()

    for bar in bars:
        bar.open /= split_ratio
        bar.high /= split_ratio
        bar.low /= split_ratio
        bar.close /= split_ratio
        bar.volume *= split_ratio  # Volume is multiplied
        bar.adjusted = True  # Flag as adjusted

    db.commit()
    logger.info(f"Adjusted {len(bars)} bars for {symbol} split on {split_date}")
```

**Note:** For MVP, we assume no corporate actions. Phase 2 will add split/dividend adjustment.

### 2.4 Data Normalization

**Rule:** Ensure consistent format across all data sources.

```python
def normalize_bar(raw_bar: dict, source: str) -> MarketDataEvent:
    """
    Normalize raw data from different sources to standard format.
    """
    if source == 'schwab':
        return MarketDataEvent(
            symbol=raw_bar['symbol'].upper(),  # Uppercase
            timestamp=parse_schwab_timestamp(raw_bar['datetime']),  # UTC
            open=Decimal(str(raw_bar['open'])),  # str → Decimal (avoid float)
            high=Decimal(str(raw_bar['high'])),
            low=Decimal(str(raw_bar['low'])),
            close=Decimal(str(raw_bar['close'])),
            volume=int(raw_bar['volume'])
        )
    elif source == 'csv':
        return MarketDataEvent(
            symbol=raw_bar['Symbol'].upper(),
            timestamp=datetime.fromisoformat(raw_bar['Date']),
            open=Decimal(raw_bar['Open']),
            # ... similar normalization
        )
```

### 2.5 Preventing Lookback Bias

**Rule:** NEVER use future data in backtesting logic.

**Critical for Valid Backtests!**

```python
# ❌ BAD: Using future data (lookback bias)
def on_bar(self, bar):
    # This peek into future data!!!
    future_bars = self.get_bars(bar.symbol, lookback=-5)  # Next 5 bars
    if future_bars[-1].close > bar.close:
        self.buy(bar.symbol, 100)  # Cheating!

# ✅ GOOD: Only use past data
def on_bar(self, bar):
    # Only look at historical data
    past_bars = self.get_bars(bar.symbol, lookback=20)  # Last 20 bars
    sma = calculate_sma(past_bars)

    if bar.close > sma:
        self.buy(bar.symbol, 100)
```

**How EventLoop prevents bias:**
- Bar-by-bar processing (sequential, no peeking ahead)
- Strategy only receives current bar and historical bars
- Database queries restricted to `timestamp <= current_bar.timestamp`

---

## 3. Modular Design Patterns

### 3.1 SOLID Principles

#### Single Responsibility Principle (SRP)
**Rule:** Each class should have ONE reason to change.

```python
# ❌ BAD: God class (too many responsibilities)
class Backtester:
    def fetch_data(self): ...
    def calculate_indicators(self): ...
    def execute_strategy(self): ...
    def manage_portfolio(self): ...
    def calculate_metrics(self): ...
    def generate_report(self): ...

# ✅ GOOD: Single responsibilities
class DataHandler:
    def get_next_bar(self): ...

class Strategy:
    def on_bar(self, bar): ...

class PortfolioSimulator:
    def execute_trade(self, signal): ...

class PerformanceAnalyzer:
    def calculate_metrics(self, trades): ...
```

#### Open/Closed Principle (OCP)
**Rule:** Open for extension, closed for modification.

```python
# ❌ BAD: Must modify DataHandler to add new source
class DataHandler:
    def get_data(self, source):
        if source == 'schwab':
            # Schwab logic
        elif source == 'yahoo':
            # Yahoo logic
        # Must add new elif for each source!

# ✅ GOOD: Extend via inheritance
class DataHandler(ABC):
    @abstractmethod
    def get_next_bar(self): ...

class SchwabDataHandler(DataHandler):
    def get_next_bar(self): ...

class YahooDataHandler(DataHandler):
    def get_next_bar(self): ...

# Add new source without modifying existing code
class BinanceDataHandler(DataHandler):
    def get_next_bar(self): ...
```

#### Dependency Inversion Principle (DIP)
**Rule:** Depend on abstractions, not concretions.

```python
# ❌ BAD: Strategy depends on concrete database
class Strategy:
    def __init__(self):
        self.db = SQLiteDatabase()  # Concrete dependency

# ✅ GOOD: Strategy depends on interface
class Strategy:
    def __init__(self, data_handler: DataHandler):  # Abstract interface
        self.data_handler = data_handler

# Can inject any DataHandler implementation
strategy = Strategy(data_handler=SchwabDataHandler())
# or
strategy = Strategy(data_handler=MockDataHandler())  # For testing
```

### 3.2 Design Patterns

#### Strategy Pattern
```python
# Strategy interface
class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar): ...

# Concrete strategies
class SMA_Crossover(Strategy):
    def on_bar(self, bar): ...

class RSI_MeanReversion(Strategy):
    def on_bar(self, bar): ...

# Usage - swap strategies without changing EventLoop
runner = BacktestRunner()
results = runner.run(strategy=SMA_Crossover())  # Easy to swap
```

#### Portfolio Allocation Pattern

**Use portfolio_percent for Position Sizing**:

```python
from decimal import Decimal

class MyStrategy(Strategy):
    def __init__(self):
        super().__init__()
        self.position_size = Decimal('0.8')  # 80% of portfolio

    def on_bar(self, bar):
        # Signal generation logic
        if buy_condition:
            # Specify allocation %, Portfolio calculates shares
            self.buy(bar.symbol, self.position_size)

        elif sell_condition:
            # Close position with 0% allocation
            self.sell(bar.symbol, Decimal('0.0'))
```

**DON'T Calculate Shares Yourself**:
```python
# ❌ WRONG (Old pattern - DO NOT USE):
portfolio_value = self._cash + position_value
desired_shares = int((portfolio_value * 0.8) / price)
self.buy(symbol, desired_shares)  # OLD API

# ✅ RIGHT (New pattern - USE THIS):
self.buy(symbol, Decimal('0.8'))  # Portfolio handles share calculation
```

**Position Closing**:
```python
# Close long position
if exit_long_condition:
    self.sell(symbol, Decimal('0.0'))

# Close short position
if exit_short_condition:
    self.buy(symbol, Decimal('0.0'))
```

**Validation**:
- `portfolio_percent` must be between 0.0 and 1.0
- 0.0 = close position
- 1.0 = allocate entire portfolio
- Typical range: 0.5 to 0.8 (50-80%)

#### Repository Pattern
```python
# Repository interface
class DataRepository(ABC):
    @abstractmethod
    def get_bars(self, symbol, start, end): ...
    @abstractmethod
    def insert_bar(self, bar): ...

# Concrete repository
class SQLAlchemyRepository(DataRepository):
    def get_bars(self, symbol, start, end):
        return self.session.query(MarketData)...

# Usage - can swap database without changing application code
repo = SQLAlchemyRepository(session)
bars = repo.get_bars('AAPL', '2024-01-01', '2024-12-31')
```

#### Factory Pattern
```python
# Factory for creating data handlers
class DataHandlerFactory:
    @staticmethod
    def create(source: str) -> DataHandler:
        if source == 'schwab':
            return SchwabDataHandler()
        elif source == 'csv':
            return CSVDataHandler()
        else:
            raise ValueError(f"Unknown data source: {source}")

# Usage
handler = DataHandlerFactory.create('schwab')
```

---

## 4. Testing Strategy

### 4.1 Test Pyramid

```
         /\
        /  \  E2E Tests (Few)
       /────\
      /      \  Integration Tests (Some)
     /────────\
    /          \  Unit Tests (Many)
   /────────────\
```

**Target Coverage:**
- Unit Tests: >80% coverage
- Integration Tests: Critical paths (data sync, backtest execution)
- E2E Tests: Full workflow (sync → backtest → results)

### 4.2 Unit Testing

**Rule:** Every module should be independently testable.

```python
# tests/unit/test_portfolio.py
import pytest
from decimal import Decimal
from jutsu_engine.portfolio.simulator import PortfolioSimulator

def test_portfolio_buy_sufficient_cash():
    """Test buying shares with sufficient cash"""
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))

    # Execute buy order
    portfolio.buy(symbol='AAPL', quantity=100, price=Decimal('150.00'))

    # Verify state
    assert portfolio.cash == Decimal('85000.00')  # 100000 - (100 * 150)
    assert portfolio.positions['AAPL'] == 100
    assert len(portfolio.trades) == 1


def test_portfolio_buy_insufficient_cash():
    """Test buying shares with insufficient cash"""
    portfolio = PortfolioSimulator(initial_capital=Decimal('1000'))

    # Should raise exception or return error
    with pytest.raises(InsufficientFundsError):
        portfolio.buy(symbol='AAPL', quantity=100, price=Decimal('150.00'))
```

### 4.3 Mock External Dependencies

**Rule:** Don't hit real APIs or databases in unit tests.

```python
# tests/unit/test_data_sync.py
from unittest.mock import Mock, patch
from jutsu_engine.application.data_sync import DataSync

@patch('jutsu_engine.data.handlers.schwab.SchwabAPI')
def test_data_sync(mock_api):
    """Test data sync with mocked API"""
    # Setup mock
    mock_api.return_value.fetch_bars.return_value = [
        {'symbol': 'AAPL', 'close': 150.00, ...}
    ]

    # Execute
    syncer = DataSync(api=mock_api)
    syncer.sync_symbol('AAPL', '1D')

    # Verify API was called correctly
    mock_api.fetch_bars.assert_called_once_with('AAPL', '1D', ...)
```

### 4.4 Test Fixtures

**Rule:** Use fixtures for reusable test data.

```python
# tests/fixtures/sample_data.py
from decimal import Decimal
from datetime import datetime

SAMPLE_BARS = [
    MarketDataEvent(
        symbol='AAPL',
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        open=Decimal('150.00'),
        high=Decimal('152.00'),
        low=Decimal('149.00'),
        close=Decimal('151.00'),
        volume=1000000
    ),
    # ... more bars
]

# tests/unit/test_strategy.py
from tests.fixtures.sample_data import SAMPLE_BARS

def test_sma_strategy():
    strategy = SMA_Crossover()
    for bar in SAMPLE_BARS:
        strategy.on_bar(bar)
    # Verify signals generated correctly
```

### 4.5 Integration Testing

**Rule:** Test module interactions with real database (but isolated).

```python
# tests/integration/test_backtest_runner.py
import pytest
from sqlalchemy import create_engine
from jutsu_engine.application.backtest_runner import BacktestRunner

@pytest.fixture
def test_db():
    """Create temporary in-memory database for testing"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

def test_full_backtest(test_db):
    """Test complete backtest workflow"""
    # 1. Insert test data
    insert_sample_bars(test_db, 'AAPL', '2024-01-01', '2024-12-31')

    # 2. Run backtest
    config = {'symbol': 'AAPL', 'start': '2024-01-01', ...}
    runner = BacktestRunner(config, db=test_db)
    results = runner.run(strategy=SMA_Crossover())

    # 3. Verify results
    assert 'total_return' in results
    assert results['total_trades'] > 0
```

---

## 5. Performance Considerations

### 5.1 Database Indexing

**Rule:** Index frequently queried columns.

```sql
-- Primary index for symbol + timeframe + timestamp (most common query)
CREATE INDEX idx_market_data_lookup
ON market_data(symbol, timeframe, timestamp);

-- Index for date range queries
CREATE INDEX idx_market_data_date
ON market_data(timestamp);

-- Composite index for data sync queries
CREATE INDEX idx_metadata_lookup
ON data_metadata(symbol, timeframe, data_source);
```

### 5.2 Batch Operations

**Rule:** Insert/update in batches, not one-by-one.

```python
# ❌ BAD: Individual inserts (slow)
for bar in bars:
    db.session.add(MarketData(**bar))
    db.session.commit()  # Commit each one!

# ✅ GOOD: Batch insert (fast)
db.session.bulk_insert_mappings(MarketData, bars)
db.session.commit()  # Single commit

# Or use bulk_save_objects for ORM objects
market_data_objects = [MarketData(**bar) for bar in bars]
db.session.bulk_save_objects(market_data_objects)
db.session.commit()
```

### 5.3 Memory Management

**Rule:** Stream data, don't load entire dataset into memory.

```python
# ❌ BAD: Load all bars into memory (crashes with large datasets)
bars = db.query(MarketData).filter_by(symbol='AAPL').all()
for bar in bars:
    process(bar)

# ✅ GOOD: Stream bars with yield_per
bars = db.query(MarketData)
         .filter_by(symbol='AAPL')
         .yield_per(1000)  # Fetch 1000 at a time
for bar in bars:
    process(bar)

# Even better: Use iterator in DataHandler
class DatabaseDataHandler(DataHandler):
    def get_next_bar(self) -> Iterator[MarketDataEvent]:
        query = self.session.query(MarketData)...
        for bar in query.yield_per(1000):
            yield self._to_event(bar)
```

### 5.4 Caching

**Rule:** Cache computed indicators within backtest run.

```python
class Strategy:
    def __init__(self):
        self._sma_cache = {}  # Cache SMA values

    def on_bar(self, bar):
        # Check cache first
        cache_key = (bar.symbol, 20)
        if cache_key in self._sma_cache:
            sma = self._sma_cache[cache_key]
        else:
            # Calculate and cache
            prices = self.get_closes(lookback=20)
            sma = calculate_sma(prices)
            self._sma_cache[cache_key] = sma

        # Use SMA for trading logic
```

---

## 6. Security & Credentials

### 6.1 Never Commit Secrets

**Rule:** API keys and passwords must NEVER be in version control.

```python
# ❌ BAD: Hardcoded API key
API_KEY = "my_secret_api_key_12345"

# ✅ GOOD: Environment variable
import os
API_KEY = os.getenv('SCHWAB_API_KEY')

if not API_KEY:
    raise ValueError("SCHWAB_API_KEY environment variable not set")
```

**.gitignore:**
```
.env
config/secrets.yaml
*.key
*.pem
```

**.env (not committed):**
```
SCHWAB_API_KEY=your_key_here
SCHWAB_API_SECRET=your_secret_here
```

### 6.2 API Rate Limiting

**Rule:** Respect API rate limits to avoid bans.

```python
import time
from functools import wraps

def rate_limit(calls_per_second: float):
    """Decorator to enforce rate limiting"""
    interval = 1.0 / calls_per_second

    def decorator(func):
        last_call = [0.0]

        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_call[0]
            if elapsed < interval:
                time.sleep(interval - elapsed)

            last_call[0] = time.time()
            return func(*args, **kwargs)

        return wrapper
    return decorator


class SchwabAPI:
    @rate_limit(calls_per_second=2)  # Max 2 calls/second
    def fetch_bars(self, symbol, timeframe):
        # API call here
        ...
```

---

## 7. Error Handling

### 7.1 Graceful Degradation

**Rule:** Continue on non-critical errors, log and report critical ones.

```python
def sync_data(symbols: List[str]):
    """Sync data for multiple symbols, continue on individual failures"""
    results = {'success': [], 'failed': []}

    for symbol in symbols:
        try:
            fetch_and_store(symbol)
            results['success'].append(symbol)
            logger.info(f"Successfully synced {symbol}")
        except APIRateLimitError:
            logger.error(f"Rate limit hit, stopping sync")
            break  # Critical - stop immediately
        except (APIError, NetworkError) as e:
            logger.warning(f"Failed to sync {symbol}: {e}")
            results['failed'].append((symbol, str(e)))
            # Continue to next symbol

    return results
```

### 7.2 Comprehensive Logging

**Rule:** Log errors with context (what failed, why, how to fix).

```python
try:
    result = api.fetch_bars(symbol, timeframe)
except APIError as e:
    logger.error(
        f"API Error fetching {symbol}:{timeframe}",
        extra={
            'symbol': symbol,
            'timeframe': timeframe,
            'error_code': e.code,
            'error_message': str(e),
            'suggestion': 'Check API credentials or rate limits'
        }
    )
    raise
```

### 7.3 Retry Logic

**Rule:** Retry transient failures with exponential backoff.

```python
import time
from typing import TypeVar, Callable

T = TypeVar('T')

def retry_with_backoff(
    func: Callable[..., T],
    max_attempts: int = 3,
    backoff_factor: float = 2.0
) -> T:
    """Retry function with exponential backoff"""
    for attempt in range(max_attempts):
        try:
            return func()
        except (NetworkError, TimeoutError) as e:
            if attempt == max_attempts - 1:
                raise  # Last attempt, give up

            wait_time = backoff_factor ** attempt
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
```

---

## 8. Logging Best Practices

### 8.1 Module-Based Loggers

**Rule:** Use module-specific loggers for traceability.

```python
# jutsu_engine/data/handlers/schwab.py
import logging
logger = logging.getLogger('DATA.SCHWAB')

logger.info("Fetching AAPL data from 2024-01-01 to 2024-12-31")
```

**Output:**
```
2025-10-31 14:30:22,123 | DATA.SCHWAB | INFO | Fetching AAPL data from 2024-01-01 to 2024-12-31
```

### 8.2 Log Levels

**Rule:** Use appropriate log levels.

- **DEBUG**: Detailed info for troubleshooting (indicator values, intermediate calculations)
- **INFO**: General operational events (data sync complete, backtest started)
- **WARNING**: Unexpected but handled (partial data, API slowness)
- **ERROR**: Errors that prevent operation (API failure, invalid data)
- **CRITICAL**: System failures (database corruption, total API outage)

### 8.3 Structured Logging

**Rule:** Include context in log messages.

```python
# ❌ BAD: Vague log message
logger.info("Trade executed")

# ✅ GOOD: Contextual log message
logger.info(
    f"BUY 100 AAPL @ $150.25 | Cash: ${self.cash:,.2f} | Portfolio Value: ${self.portfolio_value:,.2f}",
    extra={
        'action': 'BUY',
        'symbol': 'AAPL',
        'quantity': 100,
        'price': Decimal('150.25'),
        'cash_remaining': self.cash,
        'portfolio_value': self.portfolio_value
    }
)
```

---

## 9. Code Style & Standards

### 9.1 Type Hints

**Rule:** All public functions must have type hints.

```python
from typing import List, Optional, Iterator
from decimal import Decimal

# ✅ GOOD: Full type hints
def calculate_sma(prices: pd.Series, period: int) -> Decimal:
    """
    Calculate Simple Moving Average.

    Args:
        prices: Series of historical prices
        period: Number of periods for SMA

    Returns:
        SMA value as Decimal

    Raises:
        ValueError: If period > len(prices)
    """
    if period > len(prices):
        raise ValueError(f"Period {period} exceeds available data {len(prices)}")

    return Decimal(str(prices.tail(period).mean()))
```

### 9.2 Docstrings

**Rule:** Use Google-style docstrings for all public APIs.

```python
def fetch_historical_data(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    timeframe: str = '1D'
) -> List[MarketDataEvent]:
    """
    Fetch historical market data from API.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        start_date: Start date for data fetch (inclusive)
        end_date: End date for data fetch (inclusive)
        timeframe: Bar timeframe (default: '1D')
            Valid values: '1D', '1H', '5m', '1m'

    Returns:
        List of MarketDataEvent objects sorted by timestamp

    Raises:
        APIError: If API request fails
        ValueError: If start_date > end_date or invalid timeframe

    Example:
        >>> bars = fetch_historical_data('AAPL', datetime(2024,1,1), datetime(2024,12,31))
        >>> len(bars)
        252  # Trading days in 2024
    """
    ...
```

### 9.3 Naming Conventions

**Rule:** Follow Python PEP 8 naming standards.

- **snake_case**: Functions, variables, modules
- **PascalCase**: Classes
- **UPPER_CASE**: Constants
- **_leading_underscore**: Private methods/variables

```python
# Constants
MAX_POSITION_SIZE = Decimal('0.20')
DEFAULT_COMMISSION = Decimal('0.01')

# Classes
class PortfolioSimulator:
    ...

# Functions and variables
def calculate_sharpe_ratio(returns: pd.Series) -> float:
    annual_return = returns.mean() * 252
    annual_volatility = returns.std() * (252 ** 0.5)
    return annual_return / annual_volatility

# Private methods
def _validate_input(self, data):
    ...
```

---

## 10. Preventing Lookback Bias

### 10.1 What is Lookback Bias?

**Lookback bias** (also called "future peeking") occurs when your backtest uses information that wouldn't have been available at that point in time. This makes your strategy appear better than it actually is.

**Common Sources:**
- Using future prices to make current decisions
- Training indicators on entire dataset (including future data)
- Rebalancing portfolio based on end-of-period performance

### 10.2 How EventLoop Prevents Bias

```python
class EventLoop:
    def run(self, data_handler, strategy):
        """
        Process bars sequentially (bar-by-bar).
        Strategy can ONLY see current bar and historical bars.
        """
        for bar in data_handler.get_next_bar():
            # 1. Current bar
            current_bar = bar

            # 2. Historical bars (only past data)
            historical = data_handler.get_bars(
                symbol=bar.symbol,
                end_date=bar.timestamp,  # Only up to current bar
                lookback=strategy.lookback_period
            )

            # 3. Strategy processes (no future data accessible)
            strategy.on_bar(current_bar, historical)

            # 4. Portfolio updates
            self.portfolio.update(current_bar)
```

### 10.3 Testing for Bias

**Rule:** Run walk-forward analysis to detect overfitting.

```python
# Walk-forward test
# Train on 1 year, test on next 3 months, repeat

results = []
for year in range(2020, 2025):
    train_start = f"{year}-01-01"
    train_end = f"{year}-12-31"
    test_start = f"{year+1}-01-01"
    test_end = f"{year+1}-03-31"

    # Optimize on training period
    best_params = optimize_strategy(train_start, train_end)

    # Test on out-of-sample data
    result = run_backtest(test_start, test_end, params=best_params)
    results.append(result)

# If performance degrades significantly in out-of-sample, likely overfit
```

---

## Summary

These best practices ensure:
- ✅ **Data Integrity**: Immutable, validated, auditable financial data
- ✅ **Precision**: Decimal arithmetic, no floating-point errors
- ✅ **Modularity**: SOLID principles, clean architecture, swappable components
- ✅ **Testability**: High coverage, isolated unit tests, integration tests
- ✅ **Performance**: Indexed queries, batch operations, streaming data
- ✅ **Security**: No secrets in code, rate limiting, encrypted storage
- ✅ **Reliability**: Graceful error handling, comprehensive logging, retry logic
- ✅ **Valid Backtests**: No lookback bias, sequential processing, audit trail

Following these practices results in a **trustworthy**, **maintainable**, and **expandable** backtesting engine.
