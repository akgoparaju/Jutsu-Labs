# Claude Development Guide for Jutsu Labs Engine

This document provides context and guidance for Claude Code when working on the Vibe backtesting engine project.

## Project Overview

**Name**: Jutsu Labs Engine
**Version**: 0.1.0 (MVP Phase 1 - COMPLETE)
**Purpose**: Modular, event-driven backtesting framework for algorithmic trading strategies
**Architecture**: Hexagonal (Ports & Adapters) with clear separation of concerns

## Current Status (MVP Phase 1 Complete)

### ✅ Implemented Components

1. **Core Domain Layer**
   - `EventLoop`: Bar-by-bar coordinator preventing lookback bias
   - `Strategy`: Base class for all trading strategies
   - `Events`: MarketDataEvent, SignalEvent, OrderEvent, FillEvent

2. **Application Layer**
   - `BacktestRunner`: High-level API orchestrating all components
   - `DataSync`: Incremental data synchronization with metadata tracking

3. **Infrastructure Layer**
   - `DatabaseDataHandler`: Chronological data provider from database
   - `SchwabDataFetcher`: OAuth 2.0 API integration with rate limiting
   - `PortfolioSimulator`: Position/cash management with costs
   - `PerformanceAnalyzer`: 11 comprehensive performance metrics

4. **Strategy & Indicators**
   - `SMA_Crossover`: Example strategy implementation
   - 8 Technical Indicators: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, OBV

5. **CLI Interface**
   - 5 commands: init, sync, status, validate, backtest
   - Entry point: `vibe` command

6. **Database Models**
   - `MarketData`: OHLC price data
   - `DataMetadata`: Tracking last updates
   - `DataAuditLog`: Operation audit trail

### 🎯 Architecture Principles

**Key Design Decisions:**
- **Decimal Precision**: All financial calculations use `Decimal` type (no float errors)
- **Lookback Bias Prevention**: Strict chronological data processing with timestamp filtering
- **UTC Timestamps**: All timestamps stored and processed in UTC
- **Immutable History**: Market data never modified after initial storage
- **Type Safety**: Full type hints throughout codebase (Python 3.10+)
- **Modular Design**: Each component independent and swappable
- **Comprehensive Logging**: Module-specific loggers with prefixes

**Financial Accuracy Safeguards:**
1. Commission and slippage modeling in all executions
2. Realistic order fills (no guaranteed fills)
3. Position tracking with average entry price
4. Proper cost basis calculations

## Project Structure

```
jutsu-engine/
├── jutsu_engine/
│   ├── core/                 # Domain logic
│   │   ├── strategy_base.py  # Strategy base class
│   │   ├── event_loop.py     # Coordinator
│   │   └── events.py         # Event definitions
│   ├── application/          # Use cases
│   │   ├── backtest_runner.py
│   │   └── data_sync.py
│   ├── data/                 # Data infrastructure
│   │   ├── handlers/
│   │   │   ├── base.py
│   │   │   └── database.py
│   │   ├── fetchers/
│   │   │   ├── base.py
│   │   │   └── schwab.py
│   │   └── models.py         # SQLAlchemy models
│   ├── indicators/
│   │   └── technical.py      # 8 indicators
│   ├── portfolio/
│   │   └── simulator.py      # Portfolio management
│   ├── performance/
│   │   └── analyzer.py       # Metrics calculation
│   ├── strategies/
│   │   └── sma_crossover.py  # Example strategy
│   ├── cli/
│   │   └── main.py           # Click-based CLI
│   └── utils/
│       ├── config.py         # Configuration management
│       └── logging_config.py # Logging setup
├── tests/                    # Test suite
│   ├── unit/
│   └── integration/
├── config/
│   └── config.yaml.example
├── docs/
│   ├── SYSTEM_DESIGN.md
│   ├── BEST_PRACTICES.md
│   └── CLAUDE.md (this file)
└── pyproject.toml            # Dependencies and tools
```

## Development Workflow

### Adding a New Strategy

1. Inherit from `Strategy` base class
2. Implement `init()` and `on_bar()` methods
3. Use indicator library for calculations
4. Call `self.buy()` and `self.sell()` to generate signals
5. Test with BacktestRunner

Example:
```python
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import sma

class MyStrategy(Strategy):
    def __init__(self, period=20):
        super().__init__(name="MyStrategy")
        self.period = period

    def init(self):
        pass

    def on_bar(self, bar):
        if len(self._bars) < self.period:
            return
        closes = self.get_closes(lookback=self.period)
        sma_value = sma(closes, self.period).iloc[-1]
        # Strategy logic here
```

### Adding a New Indicator

1. Add function to `jutsu_engine/indicators/technical.py`
2. Accept `Union[pd.Series, List]` input
3. Return `pd.Series` output
4. Use `_to_series()` helper for input conversion
5. Add comprehensive docstring

Example:
```python
def my_indicator(data: Union[pd.Series, List], period: int) -> pd.Series:
    """
    Calculate my custom indicator.

    Args:
        data: Price data (Series or List of Decimal)
        period: Lookback period

    Returns:
        pd.Series with indicator values
    """
    series = _to_series(data)
    # Calculation here
    return result
```

### Adding a New Data Fetcher

1. Inherit from `DataFetcher` base class
2. Implement `fetch_bars()` method
3. Return standardized bar dictionaries
4. Handle authentication and rate limiting
5. Use proper error handling with retries

Example structure in `jutsu_engine/data/fetchers/`:
```python
from jutsu_engine.data.fetchers.base import DataFetcher

class MyDataFetcher(DataFetcher):
    def fetch_bars(self, symbol, timeframe, start_date, end_date):
        # Implementation
        return bars  # List[Dict[str, Any]]
```

## Testing Standards

### Test Structure
- Unit tests in `tests/unit/`
- Integration tests in `tests/integration/`
- Coverage target: 80% minimum
- Use pytest fixtures for setup

### Running Tests
```bash
# All tests
pytest

# With coverage
pytest --cov=jutsu_engine --cov-report=html

# Specific file
pytest tests/unit/test_event_loop.py
```

### Test Database
- Use in-memory SQLite for tests: `sqlite:///:memory:`
- Create fresh database for each test
- Use fixtures to populate test data

## Code Quality Standards

### Style
- Black formatter (line length 100)
- isort for imports
- Type hints required
- Docstrings for all public functions/classes

### Financial Calculations
- ALWAYS use `Decimal` for money/prices
- Convert to Decimal at API boundaries
- Use string conversion: `Decimal(str(value))`
- Never use float for financial math

### Logging
- Use module-specific loggers
- Prefixes: BACKTEST, DATA, STRATEGY, PERF, etc.
- Log levels: INFO for operations, DEBUG for details, ERROR for failures
- Include timestamps and context

Example:
```python
from jutsu_engine.utils.logging_config import get_strategy_logger

logger = get_strategy_logger('MY_STRATEGY')
logger.info(f"Generated signal: {signal_type}")
```

## Common Tasks

### Adding CLI Command
1. Add `@cli.command()` decorator in `jutsu_engine/cli/main.py`
2. Use Click options for parameters
3. Create database session if needed
4. Use click.echo() for output
5. Use click.style() for colored messages

### Modifying Database Schema
1. Update models in `jutsu_engine/data/models.py`
2. Add migration script if needed
3. Update `vibe init` command
4. Test with fresh database

### Adding Performance Metric
1. Add calculation method to `PerformanceAnalyzer`
2. Include in `calculate_metrics()` return dict
3. Add to report generation
4. Update tests

## Important Patterns

### Preventing Lookback Bias
```python
# CORRECT: Filter by timestamp
bars = query.filter(MarketData.timestamp <= current_bar.timestamp)

# WRONG: Could peek into future
bars = query.filter(MarketData.symbol == symbol)
```

### Safe Decimal Conversion
```python
# CORRECT
price = Decimal(str(api_price))

# WRONG (loses precision)
price = Decimal(api_price)
```

### Strategy Signal Generation
```python
# CORRECT: Check position before buy
if not self.has_position(symbol):
    self.buy(symbol, quantity)

# WRONG: Could double-enter
self.buy(symbol, quantity)
```

## Configuration

### Environment Variables (.env)
```
SCHWAB_API_KEY=your_key
SCHWAB_API_SECRET=your_secret
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
```

## Known Limitations & Future Work

### Current Limitations
- Single symbol per backtest
- Daily timeframe optimal (intraday untested)
- No slippage modeling for market impact
- No partial fills
- No multi-asset portfolio optimization

### Phase 2 Priorities
1. REST API with FastAPI
2. Parameter optimization framework
3. Walk-forward analysis
4. PostgreSQL migration
5. Multiple timeframe support

## Troubleshooting

### Common Issues

**Import Errors**
- Ensure virtual environment activated
- Run `pip install -e .`

**Database Errors**
- Run `vibe init` to create schema
- Check DATABASE_URL in .env

**API Authentication Failures**
- Verify SCHWAB_API_KEY and SCHWAB_API_SECRET
- Check token expiry (auto-refreshes every 30min)

**Backtest Returns No Data**
- Run `vibe status` to check data availability
- Sync data with `vibe sync` command
- Verify date range has market data

## Contact & Support

For questions about architecture, design decisions, or implementation:
- See SYSTEM_DESIGN.md for detailed architecture
- See BEST_PRACTICES.md for coding standards
- Review existing code for patterns

**Authors**: Anil Goparaju, Padma Priya Garnepudi
**License**: MIT
