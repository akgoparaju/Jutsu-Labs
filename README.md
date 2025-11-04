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

### Current (MVP - Phase 1) ✅ COMPLETE
- ✅ **Modular Architecture**: Hexagonal/Ports & Adapters pattern with clean separation
- ✅ **Database-Backed Data**: SQLite with incremental updates (PostgreSQL-ready)
- ✅ **Schwab API Integration**: OAuth 2.0 authentication with rate limiting
- ✅ **Event-Driven Processing**: Bar-by-bar backtesting with EventLoop coordination
- ✅ **Strategy Framework**: Base class system for drop-in strategies
- ✅ **Indicator Library**: 8 technical indicators (SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, OBV)
- ✅ **Performance Metrics**: Sharpe, Sortino, Calmar ratios, max drawdown, win rate, profit factor
- ✅ **Comprehensive Logging**: Module-based audit trail with timestamps
- ✅ **CLI Interface**: Command-line tool for data sync and backtest execution
- ✅ **Data Validation**: Quality checks for OHLC relationships and data integrity

### Planned (Future Phases)
- 🔄 **REST API Service**: FastAPI wrapper for external access
- 📈 **Web Dashboard**: Streamlit UI for visualization
- 🎲 **Monte Carlo Simulation**: Strategy robustness testing
- ⚡ **Parameter Optimization**: Grid search and genetic algorithms
- 🐳 **Docker Deployment**: Multi-container orchestration
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
vibe init
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
vibe init

# 2. Sync market data from Schwab
vibe sync --symbol AAPL --timeframe 1D --start 2024-01-01

# 3. Check data status
vibe status --symbol AAPL --timeframe 1D

# 4. Run a backtest
vibe backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31 \
  --capital 100000 --short-period 20 --long-period 50

# 5. Validate data quality
vibe validate --symbol AAPL --timeframe 1D
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
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import sma, rsi

class MyStrategy(Strategy):
    def __init__(self, short_period=10, long_period=30):
        super().__init__(name="MyCustomStrategy")
        self.short_period = short_period
        self.long_period = long_period
        self.position_size = 100

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

        # Generate signals
        if short_sma > long_sma and rsi_value < 70 and not self.has_position(symbol):
            self.buy(symbol, self.position_size)
        elif short_sma < long_sma and self.has_position(symbol):
            position_size = self._positions.get(symbol, 0)
            self.sell(symbol, position_size)
```

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

### Phase 2: Service Layer (Q1 2024)
- [ ] REST API with FastAPI
- [ ] Parameter optimization framework
- [ ] PostgreSQL migration
- [ ] Advanced metrics (Sortino, Calmar, rolling stats)
- [ ] Multiple data source support (CSV, Yahoo Finance)

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
