# 🎯 Jutsu Labs - Modular Backtesting Engine

> A lightweight, modular, and expandable Python-based backtesting engine for trading strategies.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## 📋 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Development](#development)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## 🎯 Overview

Jutsu Labs is a backtesting engine designed for **modularity**, **data integrity**, and **expandability**. Built with solo developers and small teams in mind, it prioritizes:

- 🔌 **Pluggable Components**: Swap data sources, strategies, and indicators without touching core code
- 📊 **Database-First Data**: Store market data once, backtest many times (no repeated API calls)
- 🔍 **Transparency**: Clear, auditable calculations for all metrics
- 🚀 **Evolution Path**: Start simple (Python library), scale to multi-container services

## ✨ Key Features

### Current (MVP - Phases 1 & 2) ✅ COMPLETE

**Phase 1 Features**:
- ✅ **Modular Architecture**: Hexagonal/Ports & Adapters pattern with clean separation
- ✅ **Database-Backed Data**: SQLite with incremental updates
- ✅ **Schwab API Integration**: OAuth 2.0 authentication with rate limiting
- ✅ **Event-Driven Processing**: Bar-by-bar backtesting with EventLoop coordination
- ✅ **Strategy Framework**: Base class system for drop-in strategies
- ✅ **Indicator Library**: 8 technical indicators (SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, OBV)
- ✅ **Performance Metrics**: 11 core metrics (Sharpe, max drawdown, win rate, etc.)
- ✅ **Comprehensive Logging**: Module-based audit trail with timestamps
- ✅ **CLI Interface**: Command-line tool for data sync and backtest execution
- ✅ **Data Validation**: Quality checks for OHLC relationships and data integrity

**Phase 2 Features** (NEW):
- ✅ **PostgreSQL Production Database**: Multi-database support with connection pooling and migration tools
- ✅ **CSV Loader Module**: Flexible CSV import with auto-format detection and validation
- ✅ **Yahoo Finance Integration**: Free data source with no API keys required
- ✅ **Advanced Performance Metrics**: 20+ metrics including Sortino, Omega, Calmar, VaR, CVaR, rolling Sharpe, Ulcer Index
- ✅ **Parameter Optimization Framework**: Grid search, genetic algorithms, random search, walk-forward analysis
- ✅ **REST API with FastAPI**: 20+ endpoints, JWT authentication, rate limiting, OpenAPI documentation
- ✅ **Trade Log CSV Export**: Comprehensive audit trail with strategy context, indicators, portfolio state, and allocations

### Planned (Future Phases)
- 📈 **Web Dashboard**: Streamlit UI for visualization and interactive analysis
- 🎲 **Monte Carlo Simulation**: Strategy robustness testing with confidence intervals
- 🐳 **Docker Deployment**: Multi-container orchestration with Kubernetes support
- 🔴 **Live Trading**: Paper trading and real execution (with proper safeguards)

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│  Entry Points (Library, CLI, API, UI)   │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Application Layer                       │
│  ├─ BacktestRunner                      │
│  ├─ DataSync                            │
│  └─ StrategyOptimizer (future)          │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Core Domain                             │
│  ├─ EventLoop (coordinator)             │
│  ├─ PortfolioSimulator (state)          │
│  └─ PerformanceAnalyzer (metrics)       │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Infrastructure                          │
│  ├─ Data Handlers (Schwab, CSV, ...)    │
│  ├─ Database Repository (SQLAlchemy)    │
│  ├─ Indicator Library                   │
│  └─ Strategy Implementations            │
└─────────────────────────────────────────┘
```

**Key Design Principles:**
- **Modularity**: Every component is independent and swappable
- **Data Integrity**: Use `Decimal` for financial calculations, immutable historical data
- **Testability**: Full unit and integration test coverage
- **Documentation**: Comprehensive docs in `docs/` directory

See [SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) for detailed architecture documentation.

## 🚀 Installation

### Prerequisites
- Python 3.10 or higher
- pip package manager
- Schwab API credentials (for live data)

### Basic Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/jutsu-engine.git
cd jutsu-engine

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package with dependencies
pip install -e .

# Copy environment template
cp .env.example .env
# Edit .env with your Schwab API credentials
```

### Configuration

1. **Set up environment variables** in `.env`:
```env
SCHWAB_API_KEY=your_api_key_here
SCHWAB_API_SECRET=your_api_secret_here
DATABASE_URL=sqlite:///data/market_data.db
LOG_LEVEL=INFO
```

2. **Initialize database**:
```bash
jutsu init
```

3. **Verify installation**:
```bash
jutsu --version
jutsu --help
```

### Development Installation

```bash
# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=jutsu_engine --cov-report=html

# Format code
black jutsu_engine/ tests/
isort jutsu_engine/ tests/

# Type check
mypy jutsu_engine/
```

## 🎮 Quick Start

### CLI Usage (Recommended)

```bash
# 1. Initialize database
jutsu init

# 2. Sync market data from Schwab (or Yahoo Finance - free!)
jutsu sync schwab --symbol AAPL --timeframe 1D --start 2024-01-01
jutsu sync yahoo --symbol AAPL --timeframe 1D --start 2024-01-01

# 3. Import CSV data
jutsu load csv --file data/AAPL_historical.csv

# 4. Check data status
jutsu status --symbol AAPL --timeframe 1D

# 5. Run a backtest
jutsu backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31 \
  --capital 100000 --short-period 20 --long-period 50

# 5a. Run backtest with trade log export (NEW!)
jutsu backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31 \
  --capital 100000 --short-period 20 --long-period 50 \
  --export-trades --trades-output results/trades.csv

# 6. Optimize strategy parameters
jutsu optimize grid --symbol AAPL --start 2024-01-01 --end 2024-12-31 \
  --param short_period 10,20,30 --param long_period 40,50,60

# 7. Validate data quality
jutsu validate --symbol AAPL --timeframe 1D
```

### Python API Usage

```python
from datetime import datetime
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.application.data_sync import DataSync
from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

# 1. Sync Market Data
engine = create_engine('sqlite:///data/market_data.db')
Session = sessionmaker(bind=engine)
session = Session()

fetcher = SchwabDataFetcher()
sync = DataSync(session)

sync.sync_symbol(
    fetcher=fetcher,
    symbol='AAPL',
    timeframe='1D',
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31)
)

# 2. Run Backtest
config = {
    'symbol': 'AAPL',
    'timeframe': '1D',
    'start_date': datetime(2024, 1, 1),
    'end_date': datetime(2024, 12, 31),
    'initial_capital': Decimal('100000'),
}

runner = BacktestRunner(config)
strategy = SMA_Crossover(short_period=20, long_period=50, position_size=100)
results = runner.run(strategy)

# 3. View Results
print(f"Total Return: {results['total_return']:.2%}")
print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {results['max_drawdown']:.2%}")
print(f"Win Rate: {results['win_rate']:.2%}")
```

### Create Custom Strategy

```python
from decimal import Decimal
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import sma, rsi

class MyStrategy(Strategy):
    def __init__(self, short_period=10, long_period=30):
        super().__init__(name="MyCustomStrategy")
        self.short_period = short_period
        self.long_period = long_period
        self.position_size = Decimal('0.8')  # 80% portfolio allocation

    def init(self):
        """Initialize strategy (called before backtest starts)"""
        pass

    def on_bar(self, bar):
        """Process each bar and generate signals"""
        symbol = bar.symbol

        # Need enough bars for indicators
        if len(self._bars) < self.long_period:
            return

        # Get historical closes
        closes = self.get_closes(lookback=self.long_period)

        # Calculate indicators
        short_sma = sma(closes, period=self.short_period).iloc[-1]
        long_sma = sma(closes, period=self.long_period).iloc[-1]
        rsi_value = rsi(closes, period=14).iloc[-1]

        # Generate signals with portfolio allocation %
        if short_sma > long_sma and rsi_value < 70 and not self.has_position(symbol):
            self.buy(symbol, self.position_size)  # Buy with 80% allocation
        elif short_sma < long_sma and self.has_position(symbol):
            self.sell(symbol, Decimal('0.0'))  # Close position
```

### Trade Log Export (NEW - 2025-11-06)

Export comprehensive trade logs to CSV for detailed post-analysis. Captures strategy context, execution details, portfolio state, and performance metrics for every trade.

**CLI Usage**:
```bash
# Export trades automatically after backtest
jutsu backtest --strategy ADX_Trend --export-trades

# Specify custom output path
jutsu backtest --strategy ADX_Trend --export-trades --trades-output results/trades.csv
```

**Programmatic Usage**:
```python
from decimal import Decimal
from jutsu_engine.application.backtest_runner import BacktestRunner
from jutsu_engine.strategies.sma_crossover import SMA_Crossover

# Run backtest with trade export
runner = BacktestRunner(config={'initial_capital': Decimal('100000')})
strategy = SMA_Crossover(short_period=20, long_period=50)

results = runner.run(
    strategy=strategy,
    export_trades=True,  # Enable trade log export
    trades_output_path='my_trades.csv'
)

# CSV path included in results
print(f"Trade log exported to: {results['trades_csv_path']}")
```

**CSV Output Format** (23 columns):

| Column Group | Columns | Description |
|--------------|---------|-------------|
| **Core Trade Data** | Trade_ID, Date, Bar_Number, Strategy_State, Ticker, Decision, Decision_Reason | Sequential tracking and strategy context |
| **Indicators** (Dynamic) | Indicator_EMA_fast, Indicator_ADX, ... | Strategy-specific indicator values at decision time |
| **Thresholds** (Dynamic) | Threshold_ADX_threshold, ... | Strategy parameters and trigger conditions |
| **Order Details** | Order_Type, Shares, Fill_Price, Position_Value, Slippage, Commission | Execution specifics |
| **Portfolio State** | Portfolio_Value_Before, Portfolio_Value_After, Cash_Before, Cash_After | State changes from trade |
| **Allocation** | Allocation_Before, Allocation_After | Position percentages (e.g., "TQQQ: 47.6%, CASH: 52.4%") |
| **Performance** | Cumulative_Return_Pct | Running performance metric |

**Example CSV Output**:
```csv
Trade ID,Date,Bar Number,Strategy State,Ticker,Decision,Decision Reason,Indicator_EMA_fast,Indicator_ADX,Threshold_ADX_threshold,Order Type,Shares,Fill Price,Position Value,Slippage,Commission,Portfolio Value Before,Portfolio Value After,Cash Before,Cash After,Allocation Before,Allocation After,Cumulative Return %
1,2024-01-15 09:30:00+00:00,1,Bullish_Strong,TQQQ,BUY,EMA crossover AND ADX > 25,450.25,28.5,25.0,MARKET,100,45.5,4550.0,0.0,1.0,100000.0,95449.0,100000.0,95449.0,CASH: 100.0%,"CASH: 52.4%, TQQQ: 47.6%",-4.551
2,2024-01-15 14:30:00+00:00,6,Bearish_Building,TQQQ,SELL,EMA crossdown AND ADX declining,448.1,22.3,20.0,MARKET,100,46.75,4675.0,0.0,1.0,95449.0,100123.0,95449.0,100123.0,"CASH: 51.1%, TQQQ: 48.9%",CASH: 100.0%,0.123
```

**Use Cases**:
- 📊 **Post-Analysis**: Import into Excel/Python for detailed trade analysis
- 🔍 **Pattern Discovery**: Identify winning/losing trade patterns
- 📈 **Strategy Refinement**: Analyze indicator values at entry/exit points
- 💰 **Tax Reporting**: Complete audit trail with dates, prices, and P&L
- 🎯 **Risk Management**: Review allocation percentages and position sizing

**Dynamic Columns**: CSV automatically adapts to strategy - ADX_Trend gets EMA/ADX columns, RSI strategy gets RSI columns, etc.

## 📚 Documentation

### Core Documentation
- **[README.md](README.md)**: Project overview and quick start (this file)
- **[SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)**: Complete architecture and design decisions
- **[API_REFERENCE.md](docs/API_REFERENCE.md)**: Comprehensive API documentation
- **[BEST_PRACTICES.md](docs/BEST_PRACTICES.md)**: Financial data handling and coding standards
- **[CLAUDE.md](docs/CLAUDE.md)**: Development guide for AI assistants
- **[CHANGELOG.md](CHANGELOG.md)**: Version history and release notes

### Additional Resources
- **Example Scripts**: See `scripts/` directory for usage examples
- **Test Suite**: See `tests/` for unit and integration tests
- **Configuration**: See `config/config.yaml.example` for all options

## 🛠️ Development

### Project Structure

```
jutsu-engine/
├── jutsu_engine/          # Core library
│   ├── core/            # Domain logic (EventLoop, Strategy base)
│   ├── application/     # Use cases (Backtest runner, Data sync)
│   ├── data/            # Data infrastructure (Handlers, Database)
│   ├── indicators/      # Technical analysis functions
│   ├── portfolio/       # Portfolio management
│   ├── performance/     # Metrics calculation
│   └── strategies/      # Strategy implementations
├── tests/               # All tests (unit, integration)
├── scripts/             # Example usage scripts
├── docs/                # Documentation
└── config/              # Configuration files
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=jutsu_engine --cov-report=html

# Run specific test file
pytest tests/unit/test_event_loop.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Format code
black jutsu_engine/ tests/
isort jutsu_engine/ tests/

# Lint
flake8 jutsu_engine/
pylint jutsu_engine/

# Type check
mypy jutsu_engine/
```

## 🗺️ Roadmap

### Phase 1: MVP ✅ COMPLETE
- [x] Core architecture and project structure
- [x] Database design with incremental data sync
- [x] Schwab API integration with OAuth 2.0
- [x] Strategy framework with base classes
- [x] Indicator library (8 indicators)
- [x] Portfolio simulator with commission/slippage
- [x] Performance analyzer (11 metrics)
- [x] Event loop coordination
- [x] CLI interface with 5 commands
- [x] Data validation and quality checks
- [x] Example SMA crossover strategy
- [x] Comprehensive logging system

### Phase 2: Service Layer ✅ COMPLETE
- [x] REST API with FastAPI (20+ endpoints, JWT auth, rate limiting)
- [x] Parameter optimization framework (grid search, genetic algorithms, walk-forward)
- [x] PostgreSQL migration (multi-database support with connection pooling)
- [x] Advanced metrics (20+ metrics: Sortino, Omega, Calmar, VaR, CVaR, rolling stats)
- [x] Multiple data source support (CSV loader, Yahoo Finance integration)
- [x] CSV Loader module with auto-format detection
- [x] DatabaseFactory for flexible database backend switching

### Phase 3: UI & Distribution (Q2 2024)
- [ ] Web dashboard with Streamlit
- [ ] Multi-container Docker deployment
- [ ] Scheduled backtest jobs
- [ ] Monte Carlo simulation
- [ ] Walk-forward analysis

### Phase 4: Production Features (Q3-Q4 2024)
- [ ] Paper trading integration
- [ ] Advanced risk management
- [ ] Portfolio optimization
- [ ] Live trading (with safeguards)

## 🤝 Contributing

Contributions are welcome! Please see our contributing guidelines (coming soon).

### Development Workflow
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Run tests and linters
5. Commit with clear messages
6. Push and create a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 👥 Authors

- **Anil Goparaju** - *Initial work*
- **Padma Priya Garnepudi** - *Initial work*

## 🙏 Acknowledgments

- Built with [schwab-py](https://github.com/itsjafer/schwab-py) for Schwab API access
- Inspired by [Zipline](https://github.com/quantopian/zipline) and [Backtrader](https://github.com/mementum/backtrader)
- Following hexagonal architecture principles

---

**⚠️ Disclaimer**: This software is for educational and research purposes only. Past performance does not guarantee future results. Trading involves risk. Always test strategies thoroughly before using real capital.
