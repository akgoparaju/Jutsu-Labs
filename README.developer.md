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

### Current (Phases 1-4) ✅ COMPLETE

**Phase 1 Features** (Foundation):
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

**Phase 2 Features** (Service Layer):
- ✅ **PostgreSQL Production Database**: Multi-database support with connection pooling and migration tools
- ✅ **CSV Loader Module**: Flexible CSV import with auto-format detection and validation
- ✅ **Yahoo Finance Integration**: Free data source with no API keys required
- ✅ **Advanced Performance Metrics**: 20+ metrics including Sortino, Omega, Calmar, VaR, CVaR, rolling Sharpe, Ulcer Index
- ✅ **Parameter Optimization Framework**: Grid search, genetic algorithms, random search, walk-forward analysis
- ✅ **REST API with FastAPI**: 20+ endpoints, JWT authentication, rate limiting, OpenAPI documentation
- ✅ **Trade Log CSV Export**: Comprehensive audit trail with strategy context, indicators, portfolio state, and allocations
- ✅ **Monte Carlo Simulation**: Bootstrap resampling to test strategy robustness against sequence risk and luck

**Phase 3 Features** (UI & Dashboard):
- ✅ **React Dashboard**: Modern React 18 + TypeScript UI with Vite build
- ✅ **Multi-Strategy Comparison**: Compare up to 3 strategies with overlaid equity curves and metrics
- ✅ **Responsive Design**: Mobile-first UI with touch-friendly controls (all 63 tasks complete)
- ✅ **Real-Time Updates**: WebSocket push-based refresh when backend data changes
- ✅ **Backtest Dashboard**: Interactive backtesting with date pickers and regime visualization
- ✅ **Performance Dashboard**: KPI cards, equity curves, regime breakdown, and daily performance tables
- ✅ **Docker Deployment**: Multi-container orchestration with docker-compose

**Phase 4 Features** (Production & Live Trading):
- ✅ **Live Trading**: Paper trading and real execution with 4-phase safety approach (Phases 0-3)
- ✅ **Multi-User Access**: Role-based access control (Admin, Trader, Viewer) with invitations
- ✅ **2FA Authentication**: TOTP-based two-factor authentication with backup codes
- ✅ **Passkey/WebAuthn**: Passwordless authentication support
- ✅ **EOD Daily Performance**: Pre-computed KPIs via nightly finalization job (fixes Sharpe ratio accuracy)
- ✅ **Performance API v2**: Pre-computed metrics with baseline comparison and fallback behavior
- ✅ **Multi-Strategy Scheduling**: Parallel tracking of multiple strategies with hourly data refresh

### Planned (Future Enhancements)
- 📊 **Advanced Analytics**: Machine learning-based strategy evaluation
- 🌐 **Cloud Deployment**: Kubernetes support for horizontal scaling
- 📱 **Mobile App**: Native iOS/Android companion app

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Entry Points                                               │
│  ├─ React Dashboard (TypeScript + Vite)                    │
│  ├─ REST API (FastAPI + JWT Auth)                          │
│  ├─ CLI (jutsu commands)                                   │
│  └─ WebSocket (Real-time updates)                          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Application Layer                                          │
│  ├─ BacktestRunner (backtesting orchestration)             │
│  ├─ DataSync (market data synchronization)                 │
│  ├─ StrategyOptimizer (grid search, WFO, Monte Carlo)      │
│  ├─ EOD Finalization (daily KPI computation)               │
│  └─ Multi-Strategy Scheduler (parallel tracking)           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Core Domain                                                │
│  ├─ EventLoop (bar-by-bar coordinator)                     │
│  ├─ PortfolioSimulator (positions, cash, P&L)              │
│  ├─ PerformanceAnalyzer (20+ metrics)                      │
│  ├─ KPI Calculations (Welford's algorithm for O(1) updates)│
│  └─ Trading Calendar (NYSE schedule, half-day support)     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Infrastructure                                             │
│  ├─ Data Handlers (Schwab, Yahoo, CSV)                     │
│  ├─ PostgreSQL + SQLite (multi-database support)           │
│  ├─ Indicator Library (8 technical indicators)             │
│  ├─ Strategy Implementations (MACD_Trend_v4/v5/v6, etc.)   │
│  ├─ APScheduler (cron jobs, hourly refresh, EOD)           │
│  └─ Auth (JWT, 2FA, Passkey, Role-based access)            │
└─────────────────────────────────────────────────────────────┘
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

### Docker Installation (Recommended for Production)

```bash
# Clone the repository
git clone https://github.com/yourusername/jutsu-engine.git
cd jutsu-engine

# Copy environment template and configure
cp .env.example .env
# Edit .env with your credentials

# Build and start all services
docker-compose up -d

# Access the dashboard at http://localhost:3000
# API available at http://localhost:8000

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
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

### Frontend Development

```bash
# Navigate to dashboard directory
cd dashboard

# Install dependencies (using pnpm)
pnpm install

# Start development server
pnpm dev

# Build for production
pnpm build

# Run type checks
pnpm typecheck
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

# 6. Run multi-symbol regime strategy (Momentum-ATR)
jutsu backtest --strategy Momentum_ATR \
  --symbols QQQ,VIX,TQQQ,SQQQ \
  --start 2024-01-01 --end 2024-12-31 \
  --capital 10000

# 6a. Override strategy parameters via CLI
jutsu backtest --strategy Momentum_ATR \
  --symbols QQQ,VIX,TQQQ,SQQQ \
  --start 2024-01-01 --end 2024-12-31 \
  --vix-kill-switch 25.0 \
  --risk-strong-trend 0.05

# 7. Optimize strategy parameters
jutsu optimize grid --symbol AAPL --start 2024-01-01 --end 2024-12-31 \
  --param short_period 10,20,30 --param long_period 40,50,60

# 8. Validate data quality
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

## Implemented Strategies

The following production-ready strategies are included with Jutsu Labs. All strategies support configuration via `.env`, CLI flags, and YAML configuration files.

### MACD_Trend_v4 (Goldilocks)
- **Type**: Regime-based trend-following with dual position sizing
- **Assets**: Signal asset (e.g., QQQ), bull leverage (e.g., TQQQ), defensive (e.g., QQQ)
- **Signals**: EMA trend + MACD momentum + MACD histogram confirmation
- **Position Sizing**: Dual-mode (ATR-based risk for leveraged, flat % for defensive)
- **Risk Management**: 3-state exit system (EMA, MACD crossdown, histogram bearish)
- **Documentation**: `jutsu_engine/strategies/MACD_Trend-v4.md`
- **Grid-Search**: `grid-configs/examples/grid_search_macd_v4.yaml`

### MACD_Trend_v5 (Dynamic Regime)
- **Type**: Dual-regime strategy-of-strategies with VIX volatility filter
- **Assets**: QQQ (signal), TQQQ (3x bull), $VIX (regime detection)
- **Regime Detection**: VIX vs VIX_EMA_50 (CALM vs CHOPPY markets)
- **Parameter Switching**:
  - CALM: EMA=200, ATR_Stop=3.0 (optimized for smooth trends)
  - CHOPPY: EMA=75, ATR_Stop=2.0 (optimized for volatile markets)
- **Position Sizing**: Dual-mode (ATR-based for TQQQ, flat 60% for QQQ)
- **Key Feature**: Automatically adapts parameters based on market volatility regime
- **Documentation**: `jutsu_engine/strategies/MACD_Trend-v5.md`
- **Grid-Search**: `grid-configs/examples/grid_search_macd_v5.yaml`

### MACD_Trend_v6 (VIX-Filtered) ⭐ NEW
- **Type**: VIX-gated Goldilocks strategy with master switch
- **Assets**: QQQ (signal), TQQQ (3x bull), $VIX (master switch)
- **Core Philosophy**: "Only run V8.0 (v4) when market is CALM, else hold CASH"
- **Master Switch Logic**:
  - Step 1: VIX > VIX_EMA → CASH (stop, don't run v4)
  - Step 2: VIX ≤ VIX_EMA → Run full v4 logic (CASH/TQQQ/QQQ)
- **Key Difference from v5**: v5 switches parameters, v6 gates execution (simpler, binary)
- **Position Sizing**: Dual-mode inherited from v4 (ATR-based for TQQQ, flat 60% for QQQ)
- **Parameters**: 2 VIX params (vix_symbol, vix_ema_period=50) + all v4 parameters
- **Conservative Default**: Holds CASH when insufficient VIX data
- **Documentation**: `jutsu_engine/strategies/MACD_Trend-v6.md`
- **Grid-Search**: `grid-configs/examples/grid_search_macd_v6.yaml` (432 combinations)

### Grid Search Parameter Optimization

Automate parameter optimization by testing all combinations of strategy parameters.

**Usage**:
```bash
# Run grid search
jutsu grid-search --config configs/examples/grid_search_macd_v4.yaml

# Custom output directory
jutsu grid-search -c configs/examples/grid_search_simple.yaml -o results/
```

**Configuration File** (`grid_search_macd_v4.yaml`):
```yaml
strategy: MACD_Trend_v4

symbol_sets:
  - name: "QQQ-TQQQ"
    signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: QQQ

base_config:
  start_date: "2020-01-01"
  end_date: "2024-12-31"

parameters:
  ema_period: [50, 100, 150]
  atr_stop_multiplier: [2.0, 3.0]
  risk_bull: [0.02, 0.025]
```

**Output Structure**:
```
output/grid_search_MACD_Trend_v4_2025-11-07_143022/
├── summary_comparison.csv   # All metrics for comparison
├── run_config.csv          # Parameter mapping
├── parameters.yaml         # Copy of input config
├── README.txt             # Summary statistics
├── run_001/
│   ├── portfolio_daily.csv
│   └── trades.csv
└── run_002/
    ├── portfolio_daily.csv
    └── trades.csv
```

**Output CSV Metrics**:
- Final Value, Total Return %, Annualized Return %
- Sharpe Ratio, Sortino Ratio
- Max Drawdown %, Calmar Ratio
- Win Rate %, Total Trades
- Profit Factor, Avg Win/Loss

**Tips**:
- Start with fewer combinations (< 50) to test configuration
- Use `max_combinations` to limit total runs
- Results automatically checkpoint every 10 runs (resume capability)
- Sort `summary_comparison.csv` by Sharpe Ratio to find optimal parameters

### Walk-Forward Optimization (NEW - 2025-11-09)

Defeat curve-fitting with rigorous Walk-Forward Optimization. Periodically re-optimizes parameters on past data (In-Sample) and tests on future data (Out-of-Sample).

**Why WFO?**
Standard backtesting optimizes over entire history, leading to brittle strategies. WFO simulates real-world trading where parameters need periodic adjustment based only on past data.

**Usage**:
```bash
# Preview window plan without running
jutsu wfo --config grid-configs/examples/wfo_macd_v6.yaml --dry-run

# Run full WFO
jutsu wfo --config grid-configs/examples/wfo_macd_v6.yaml

# Custom output directory
jutsu wfo -c grid-configs/examples/wfo_macd_v6.yaml -o results/wfo_test
```

**Configuration** (`wfo_macd_v6.yaml`):
```yaml
strategy: "MACD_Trend_v6"

# Same as grid search
symbol_sets: [...]
base_config: {...}
parameters: {...}

# WFO-specific settings (NEW)
walk_forward:
  total_start_date: "2010-01-01"
  total_end_date: "2024-12-31"
  window_size_years: 3.0        # Total window (IS + OOS)
  in_sample_years: 2.5          # Optimization period
  out_of_sample_years: 0.5      # Testing period
  slide_years: 0.5              # Window advance amount
  selection_metric: "sharpe_ratio"  # Metric to optimize
```

**Output Structure**:
```
output/wfo_MACD_Trend_v6_2025-11-09_153022/
├── wfo_trades_master.csv       # All OOS trades (stitched chronologically)
├── wfo_parameter_log.csv       # Best params per window
├── wfo_equity_curve.csv        # Trade-by-trade equity progression
├── wfo_summary.txt             # Performance + parameter stability
├── wfo_config.yaml             # Copy of input config
└── window_XXX/                 # Individual window results
    ├── is_grid_search/         # In-sample optimization
    │   ├── summary_comparison.csv
    │   └── run_config.csv
    └── oos_backtest/           # Out-of-sample testing
        ├── trades.csv
        ├── portfolio_daily.csv
        └── summary.csv
```

**Key Outputs**:
1. **wfo_trades_master.csv**: All OOS trades with Portfolio_Return_Percent
2. **wfo_equity_curve.csv**: Compounded equity growth (OOS only)
3. **wfo_parameter_log.csv**: Parameter evolution over time
4. **wfo_summary.txt**: Final metrics + parameter stability (CV%)

**Parameter Stability** (Coefficient of Variation):
- CV < 20%: Stable parameters → Robust strategy
- CV 20-50%: Moderate stability → Adaptive strategy
- CV > 50%: High variability → Potential overfitting

**Example Output**:
```
OOS Return: 45.23%
Parameter Stability (CV%):
  ✓ ema_period: 12.45%
  ✓ atr_stop_multiplier: 18.32%
  ⚠ risk_bull: 35.67%
```

**Performance**:
- Window calculation: <10ms
- Per window: 2-15 min (depends on grid size)
- Total: 30 min - 8 hours (depends on # windows × grid size)
- Example: 24 windows × 432 combinations = 10,368 backtests (~4-8 hours)

**Tips**:
- Start with smaller date ranges to test (2-3 years)
- Use smaller parameter grids for faster iteration
- OOS period should be ≥ average holding period
- Check parameter stability - jumping values indicate overfitting
- Compare OOS equity curve smoothness vs buy-and-hold

### Monte Carlo Simulation (NEW - 2025-11-10)

Test if your strategy's performance is due to **skill** or **luck** by shuffling trade order. Monte Carlo simulation uses bootstrap resampling to answer: "If my trades happened in random order, what's the probability of catastrophic loss?"

**Why Monte Carlo?**
A strategy's performance depends on trade sequence. Monte Carlo shuffles trades 10,000+ times to reveal if your result was due to favorable ordering (luck) or consistent edge (skill). Critical for live trading decisions.

**Usage**:
```bash
# Step 1: Run WFO first (generates monte_carlo_input.csv)
jutsu wfo --config grid-configs/examples/wfo_macd_v6.yaml

# Step 2: Run Monte Carlo on WFO results
jutsu monte-carlo --config config/examples/monte_carlo_config.yaml

# Override iterations for faster testing
jutsu monte-carlo -c config.yaml --iterations 1000

# Override input/output paths
jutsu monte-carlo -c config.yaml \
  --input wfo_output/monte_carlo_input.csv \
  --output results/monte_carlo/

# Verbose logging
jutsu monte-carlo -c config.yaml --verbose
```

**Configuration** (`monte_carlo_config.yaml`):
```yaml
monte_carlo:
  # Input from WFO (supports glob patterns)
  input_file: output/wfo_MACD_Trend_v6_*/monte_carlo_input.csv
  output_directory: output/monte_carlo_MACD_Trend_v6

  # Simulation parameters
  iterations: 10000           # Bootstrap samples
  initial_capital: 10000      # Match WFO initial capital
  random_seed: 42             # For reproducibility (optional)

  # Analysis configuration
  analysis:
    percentiles: [5, 25, 50, 75, 95]
    confidence_level: 0.95    # 95% confidence interval
    risk_of_ruin_thresholds: [30, 40, 50]  # % loss thresholds

  # Performance options
  performance:
    parallel: false           # Enable for faster execution
    num_workers: 4           # CPU count - 1 (if parallel: true)
```

**Output Structure**:
```
output/monte_carlo_MACD_Trend_v6/
├── monte_carlo_results_2025-11-10_142530.csv  # All 10,000 simulation results
└── monte_carlo_summary_2025-11-10_142530.txt  # Statistical analysis + interpretation
```

**Key Outputs**:
1. **monte_carlo_results.csv**: All simulation results
   - Columns: Run_ID, Final_Equity, Annualized_Return, Max_Drawdown
   - 10,000 rows (one per bootstrap sample)

2. **monte_carlo_summary.txt**: Human-readable interpretation
   - Percentile analysis (5th, 25th, 50th, 75th, 95th)
   - Risk of ruin (% of runs with >30%, >40%, >50% loss)
   - Confidence intervals (95% by default)
   - Original result ranking (where your WFO result falls)
   - Recommendations (robust/moderate/high risk)

**Example Summary Output**:
```
Percentile Analysis - Final Equity:
   5th percentile:  $8,934  (Very unlucky scenario)
  25th percentile: $11,245  (Below average)
  50th percentile: $13,156  (Median outcome)
  75th percentile: $15,678  (Above average)
  95th percentile: $18,923  (Very lucky scenario)

Your original result ($14,281) is at the 62nd percentile.
Interpretation: Near median - likely reflects true strategy edge (not luck)

Risk of Ruin:
  30% loss: 2.3% of simulations (ACCEPTABLE)
  40% loss: 0.7% of simulations (LOW RISK)
  50% loss: 0.1% of simulations (VERY LOW RISK)

Recommendation: Strategy appears robust. Proceed with paper trading.
```

**Interpreting Results**:
- **Original Result Percentile**:
  - 50th percentile: Strategy has true edge (skill, not luck)
  - 95th percentile: Very lucky sequence (be cautious)
  - 5th percentile: Very unlucky sequence
- **Risk of Ruin**:
  - <10%: Robust strategy (acceptable for live trading)
  - 10-25%: Moderate risk (consider position sizing)
  - >25%: High sequence dependency (risky)
- **Percentile Range** (95th - 5th):
  - Narrow range: Consistent performance (robust)
  - Wide range: High sensitivity to trade order (volatile)

**Performance**:
- 1,000 iterations: 30-60s (quick test)
- 10,000 iterations: 2-5 min (standard)
- 100,000 iterations: 20-30 min (high precision)
- Parallel mode: ~4x faster (enable in config)

**Tips**:
- Run Monte Carlo AFTER WFO (requires monte_carlo_input.csv)
- Use random_seed for reproducible research
- 10,000 iterations is sufficient for most strategies
- If risk of ruin >10%, consider smaller position sizes
- Compare percentile range with buy-and-hold benchmark
- Re-run Monte Carlo periodically as you add more trades

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

## 📊 Web Dashboard (NEW)

Jutsu Labs includes a modern React-based dashboard for visualizing strategy performance and managing live trading.

### Features

- **Multi-Strategy Comparison**: Compare up to 3 strategies side-by-side with overlaid equity curves
- **Real-Time Updates**: WebSocket push notifications when backend data changes
- **Responsive Design**: Mobile-first UI tested on iPhone, iPad, and desktop viewports
- **Role-Based Access**: Admin, Trader, and Viewer roles with permission-based UI
- **2FA Security**: TOTP-based two-factor authentication with backup codes
- **Passkey Support**: WebAuthn passwordless authentication

### Dashboard Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Key metrics overview, strategy comparison, equity curves |
| **Performance** | Detailed KPIs, regime breakdown, daily performance table |
| **Backtest** | Historical analysis with date range selection |
| **Trades** | Trade history with filtering and statistics |
| **Decision Tree** | Strategy state visualization |
| **Settings** | Account management, 2FA setup, user invitations |

### Quick Start (Docker)

```bash
# Build and run the full stack
docker-compose up -d

# Access the dashboard
open http://localhost:3000
```

### Quick Start (Development)

```bash
# Start the backend API
cd jutsu_engine && uvicorn api.main:app --reload --port 8000

# Start the frontend (in another terminal)
cd dashboard && pnpm dev
```

### Multi-Strategy Comparison

Compare strategies by selecting up to 3 from the dropdown. Features include:
- Color-coded equity curves (Blue, Green, Amber) with pattern indicators
- Comparative metrics table with best value highlighting (★)
- URL synchronization (`?strategies=v3_5b+v3_5d`) for shareable links
- QQQ baseline comparison (gray line)

### EOD Daily Performance System

The dashboard uses pre-computed KPIs from the EOD (End-of-Day) finalization system:
- **Scheduled Job**: Runs at 4:15 PM EST (Mon-Fri), 1:15 PM on half-days
- **Pre-computed Metrics**: Sharpe, Sortino, Calmar, CAGR, max drawdown
- **Baseline Comparison**: Automatic QQQ benchmark included
- **Fallback Behavior**: Returns previous day's data before finalization completes

---

## 🔴 Live Trading (NEW - Phase 0, 1, 2, 3 Complete)

**WARNING**: Live trading with real money carries significant risk. ONLY proceed to production (Phase 2/3) after thorough testing in dry-run mode (Phase 1). The authors assume NO responsibility for financial losses.

### Overview

Jutsu Labs supports **automated live trading** with a 4-phase approach designed for safety and progressive validation:

| Phase | Mode | Purpose | Risk Level | Execution |
|-------|------|---------|------------|-----------|
| **Phase 0** | Setup | OAuth authentication, market calendar validation | None | One-time setup |
| **Phase 1** | Dry-Run | Test workflow without placing orders | None | Daily cron |
| **Phase 2** | Paper Trading | Real orders in paper/sandbox account | Low | Daily cron |
| **Phase 3** | Production | Real orders + alerts + health monitoring | HIGH | Daily cron |

**Key Features**:
- ✅ **3:55 Protocol**: Executes 5 minutes before market close using synthetic daily bar
- ✅ **NO FRACTIONAL SHARES**: Always rounds DOWN to whole shares (user requirement)
- ✅ **Atomic State Management**: Temp file + rename pattern prevents corruption
- ✅ **Slippage Validation**: Three-tier thresholds (0.3% warning, 0.5% max, 1.0% abort)
- ✅ **Financial Precision**: All calculations use `Decimal` type (never float)
- ✅ **Emergency Exit**: Close all positions in <30 seconds
- ✅ **Health Monitoring**: Automated checks every 6 hours
- ✅ **Alert System**: SMS + Email notifications via Twilio/SendGrid

### Phase 0: Setup (One-Time)

**Prerequisites**:
1. Schwab brokerage account with API access
2. Schwab API credentials (client ID + secret)
3. Python 3.10+ environment

**Step 1: Environment Configuration**

Create `.env` file with Schwab credentials:
```env
# Schwab API Credentials
SCHWAB_CLIENT_ID=your_client_id_here
SCHWAB_CLIENT_SECRET=your_client_secret_here
SCHWAB_REDIRECT_URI=https://127.0.0.1:8182
SCHWAB_TOKEN_PATH=./token.json

# Live Trading Configuration
LIVE_TRADING_STATE_FILE=./data/live_trading_state.json
LIVE_TRADING_TRADE_LOG=./data/live_trades.csv
LIVE_TRADING_DRY_RUN=true  # Phase 1 (set to false for Phase 2/3)

# Alert Configuration (Phase 3)
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_FROM_NUMBER=+1234567890
TWILIO_TO_NUMBER=+1987654321

SENDGRID_API_KEY=your_sendgrid_api_key
SENDGRID_FROM_EMAIL=alerts@yourdomain.com
SENDGRID_TO_EMAIL=you@yourdomain.com

# Risk Management
LIVE_TRADING_MAX_SLIPPAGE_PCT=0.5  # 0.5% max slippage before critical error
```

**Step 2: OAuth Authentication**

Run interactive OAuth flow (one-time):
```bash
python3 scripts/schwab_oauth.py
```

This will:
1. Open browser for Schwab login
2. Prompt for authorization code
3. Save `token.json` (auto-refreshes every 30 minutes)
4. Validate token is working

**Step 3: Market Calendar Validation**

Verify market hours detection:
```bash
python3 scripts/validate_market_calendar.py
```

Expected output:
```
Market Calendar Validation
==========================
Today: 2025-11-23 (Saturday)
Market Status: CLOSED (Weekend)

Next Trading Day: 2025-11-25 (Monday)
Market Hours: 09:30 - 16:00 EST
```

**Step 4: Create Configuration File**

Create `config/live_trading_config.yaml`:
```yaml
strategy:
  name: "Hierarchical_Adaptive_v3_5b"
  module_path: "jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b"
  class_name: "Hierarchical_Adaptive_v3_5b"
  
  # Strategy parameters
  params:
    trend_ema_period: 200
    volatility_lookback: 20
    vix_kill_switch: 25.0
    risk_strong_trend: 0.05
    risk_weak_trend: 0.03

execution:
  symbols: ["QQQ", "VIX", "TQQQ", "SQQQ"]
  initial_capital: 10000.0
  max_slippage_pct: 0.5
  commission_per_share: 0.01
  
  # 3:55 Protocol
  execution_time: "15:55"  # EST
  execution_timezone: "US/Eastern"

risk:
  max_position_pct: 0.95  # Max 95% portfolio allocation
  min_cash_reserve: 500.0  # Min $500 cash
  
alerts:
  enabled: true
  sms_enabled: true
  email_enabled: true
  critical_only: false  # Send all alerts (not just critical)

logging:
  level: "INFO"
  trade_log_path: "./data/live_trades.csv"
  state_file_path: "./data/live_trading_state.json"
```

Phase 0 is now complete. Proceed to Phase 1 for dry-run testing.

---

### Phase 1: Dry-Run Mode (Recommended: 2-4 Weeks)

**Purpose**: Validate entire workflow WITHOUT placing real orders. Simulates order execution and logs what WOULD happen.

**Step 1: Enable Dry-Run Mode**

In `.env`:
```env
LIVE_TRADING_DRY_RUN=true
```

**Step 2: Manual Test Run**

Execute manually to verify workflow:
```bash
python3 scripts/live_trader.py
```

Expected output:
```
[15:50:00] Starting live trader (DRY-RUN MODE)
[15:50:01] Market check: OPEN (15:50 EST)
[15:50:02] Loading state from data/live_trading_state.json
[15:50:03] Fetching historical bars for QQQ, VIX, TQQQ, SQQQ
[15:50:05] Creating synthetic daily bar (15:55 quote as close)
[15:50:06] Running strategy: Hierarchical_Adaptive_v3_5b
[15:50:07] Strategy decision: BUY TQQQ (allocation: 47.6%)
[15:50:08] [DRY-RUN] Would execute: BUY 100 shares TQQQ @ $45.50
[15:50:09] Validating slippage: 0.0% (OK)
[15:50:10] Saving state atomically (temp + rename)
[15:50:11] Total execution time: 11.2s
[15:50:11] Next run: 2025-11-24 15:50:00 EST
```

**Step 3: Schedule Daily Cron Job**

Add to crontab (runs Mon-Fri at 15:50 EST):
```bash
crontab -e
```

Add line:
```cron
# Live Trading - Dry-Run Mode (Phase 1)
50 15 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/live_trader.py >> logs/live_trader.log 2>&1
```

**Step 4: Monitor Logs**

Check daily execution:
```bash
# Real-time monitoring
tail -f logs/live_trader.log

# Review trade log
cat data/live_trades.csv
```

**Expected Trade Log** (CSV format):
```csv
Date,Strategy_State,Ticker,Decision,Shares,Price,Position_Value,Portfolio_Value_After,Allocation_After,DRY_RUN
2025-11-23 15:55:00,Bullish_Strong,TQQQ,BUY,100,45.50,4550.00,9450.00,"TQQQ: 48.1%, CASH: 51.9%",true
2025-11-24 15:55:00,Bullish_Strong,TQQQ,HOLD,100,46.25,4625.00,9625.00,"TQQQ: 48.0%, CASH: 52.0%",true
```

**Step 5: Validation Checklist**

Before proceeding to Phase 2, verify:
- [ ] Cron job runs daily at 15:50 EST (Mon-Fri)
- [ ] Strategy produces expected decisions (compare to backtest)
- [ ] State file updates correctly after each run
- [ ] Trade log shows consistent position sizing
- [ ] NO fractional shares (shares always whole numbers)
- [ ] Execution completes in <60 seconds (15:50-15:56 window)
- [ ] Logs show no errors or exceptions

**Recommended Duration**: Run Phase 1 for 2-4 weeks (10-20 trading days) to validate consistency.

---

### Phase 2: Paper Trading (Recommended: 4-8 Weeks)

**WARNING**: Phase 2 places REAL ORDERS in your paper/sandbox account. Ensure you have a Schwab paper trading account configured.

**Purpose**: Execute real orders via Schwab API with slippage validation and retry logic.

**Step 1: Disable Dry-Run Mode**

In `.env`:
```env
LIVE_TRADING_DRY_RUN=false
```

**Step 2: Configure Paper Trading Account**

Ensure Schwab API credentials point to **paper/sandbox account** (NOT production account).

**Step 3: Update Cron Job**

Replace Phase 1 script with Phase 2 script:
```bash
crontab -e
```

Update line:
```cron
# Live Trading - Paper Trading Mode (Phase 2)
50 15 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/live_trader_paper.py >> logs/live_trader_paper.log 2>&1
```

**Step 4: Manual Test Run**

Execute manually to verify order execution:
```bash
python3 scripts/live_trader_paper.py
```

Expected output:
```
[15:50:00] Starting live trader (PAPER TRADING MODE)
[15:50:01] Market check: OPEN (15:50 EST)
[15:50:02] Loading state from data/live_trading_state.json
[15:50:05] Creating synthetic daily bar (15:55 quote)
[15:50:06] Strategy decision: BUY TQQQ (allocation: 47.6%)
[15:50:07] Executing REAL ORDER: BUY 100 shares TQQQ
[15:50:08] Order submitted: Order ID 12345
[15:50:09] Fill received: 100 shares @ $45.52 (slippage: 0.04%)
[15:50:10] Slippage validation: 0.04% < 0.5% (OK)
[15:50:11] Logged to data/live_trades.csv
[15:50:12] Saving state atomically
[15:50:13] Total execution time: 13.1s
```

**Step 5: Order Execution Features**

Phase 2 includes:
1. **Order Sequencing**: SELL orders first (raise cash), then BUY orders
2. **Retry Logic**: Up to 3 attempts for partial fills (5-second delay)
3. **Slippage Validation**: Three-tier thresholds
   - WARNING: 0.3% (log warning, continue)
   - MAX: 0.5% (log critical, continue)
   - ABORT: 1.0% (raise exception, halt trading)
4. **Fill Validation**: Compare expected vs actual fill price
5. **Trade Logging**: All fills logged to CSV with slippage metrics

**Step 6: Monitor Paper Trading**

Check logs and trade performance:
```bash
# Real-time monitoring
tail -f logs/live_trader_paper.log

# Review fills and slippage
cat data/live_trades.csv | grep -v "DRY_RUN"

# Check Schwab paper account
# (Log into Schwab paper trading portal to verify positions)
```

**Step 7: Validation Checklist**

Before proceeding to Phase 3, verify:
- [ ] Orders execute successfully via Schwab API
- [ ] Fills received within 5 seconds
- [ ] Slippage consistently <0.5%
- [ ] NO fractional shares in fills
- [ ] State file updates after successful fills
- [ ] Paper account positions match trade log
- [ ] Retry logic works for partial fills (if encountered)
- [ ] No failed orders (100% fill rate)

**Recommended Duration**: Run Phase 2 for 4-8 weeks (20-40 trading days) to validate execution quality.

---

### Phase 3: Production Hardening (Optional but Recommended)

**WARNING**: Phase 3 is for production live trading with REAL MONEY. Only proceed if you accept full financial risk.

**Purpose**: Add SMS/Email alerts, health monitoring, and emergency procedures for production safety.

**Step 1: Configure Alert Services**

**Twilio (SMS)**:
1. Sign up at [twilio.com](https://www.twilio.com)
2. Get Account SID, Auth Token, and phone number
3. Add to `.env`:
   ```env
   TWILIO_ACCOUNT_SID=your_sid
   TWILIO_AUTH_TOKEN=your_token
   TWILIO_FROM_NUMBER=+1234567890
   TWILIO_TO_NUMBER=+1987654321
   ```

**SendGrid (Email)**:
1. Sign up at [sendgrid.com](https://sendgrid.com)
2. Get API key
3. Add to `.env`:
   ```env
   SENDGRID_API_KEY=your_api_key
   SENDGRID_FROM_EMAIL=alerts@yourdomain.com
   SENDGRID_TO_EMAIL=you@yourdomain.com
   ```

**Step 2: Enable Alerts in Config**

In `config/live_trading_config.yaml`:
```yaml
alerts:
  enabled: true
  sms_enabled: true
  email_enabled: true
  critical_only: false  # Send all alerts (recommended)
```

**Step 3: Test Alert System**

Manually trigger test alert:
```bash
python3 -c "
from jutsu_engine.live.alert_manager import AlertManager
alerts = AlertManager()
alerts.send_info_alert('Test alert from Jutsu Labs')
"
```

You should receive SMS + Email within 5 seconds.

**Step 4: Schedule Health Checks**

Add health monitoring cron (runs every 6 hours):
```bash
crontab -e
```

Add line:
```cron
# Health Monitoring (every 6 hours)
0 */6 * * * cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/health_check.py >> logs/health_check.log 2>&1
```

**Step 5: Health Check Features**

Automated checks:
1. **API Connectivity**: Test Schwab API with sample request
2. **State File Integrity**: Validate JSON structure and required fields
3. **Disk Space**: Ensure >1GB available
4. **Cron Schedule**: Verify cron job exists and is correct

Example output:
```
Health Check Report - 2025-11-23 18:00:00
============================================
✅ API Connectivity: OK (response time: 234ms)
✅ State File Integrity: OK (valid JSON, all fields present)
✅ Disk Space: OK (12.3 GB available)
✅ Cron Schedule: OK (found entry for 15:50 daily)

Overall Status: HEALTHY
```

**Step 6: Emergency Exit Procedure**

Create `scripts/emergency_exit.py` for instant liquidation:
```bash
python3 scripts/emergency_exit.py
```

**Interactive confirmation required**:
```
EMERGENCY POSITION LIQUIDATION
==============================
WARNING: This will close ALL positions immediately.

Current Positions:
  TQQQ: 100 shares @ $45.50 = $4,550.00

This action CANNOT be undone.
Type 'CONFIRM' to proceed: CONFIRM

Executing market sell orders...
[15:45:01] SELL 100 TQQQ @ market
[15:45:02] Fill: 100 shares @ $45.48
[15:45:03] Position closed. Portfolio: 100% CASH

Emergency exit complete (2.1s)
Alert sent to +1987654321 and you@yourdomain.com
```

**Emergency Exit Features**:
- Close all positions in <30 seconds
- Market orders (guaranteed fill, slippage accepted)
- Interactive confirmation (prevents accidental execution)
- SMS + Email alerts on completion
- Logs to trade log with "EMERGENCY_EXIT" tag

**Step 7: Production Deployment Checklist**

Before going live with real money:
- [ ] Phase 1 dry-run validated (2-4 weeks)
- [ ] Phase 2 paper trading validated (4-8 weeks)
- [ ] SMS alerts tested and working
- [ ] Email alerts tested and working
- [ ] Health checks running every 6 hours
- [ ] Emergency exit procedure tested
- [ ] Schwab API credentials point to PRODUCTION account (NOT paper account)
- [ ] Initial capital matches Schwab account balance
- [ ] Risk limits configured (max_position_pct, min_cash_reserve)
- [ ] You accept FULL FINANCIAL RISK

**Step 8: Switch to Production Account**

**FINAL WARNING**: This step enables real money trading.

1. Update `.env` with **production** Schwab credentials:
   ```env
   SCHWAB_CLIENT_ID=production_client_id
   SCHWAB_CLIENT_SECRET=production_client_secret
   ```

2. Re-run OAuth authentication:
   ```bash
   python3 scripts/schwab_oauth.py
   ```

3. Verify production account:
   ```bash
   python3 -c "
   from schwab import auth
   client = auth.client_from_token_file('token.json')
   account = client.get_account()
   print(f'Account: {account}')
   "
   ```

4. Update cron to production script:
   ```cron
   # Live Trading - PRODUCTION MODE (Phase 3)
   50 15 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/live_trader_paper.py >> logs/live_trader_prod.log 2>&1
   ```

Production live trading is now active. Monitor closely for the first 2 weeks.

---

### Daily Monitoring & Maintenance

**Daily Tasks**:
1. Check logs for errors: `tail logs/live_trader_prod.log`
2. Verify fills in trade log: `cat data/live_trades.csv | tail -5`
3. Compare Schwab account positions with state file
4. Review slippage metrics (should be <0.3% average)

**Weekly Tasks**:
1. Review health check reports: `cat logs/health_check.log | grep "Overall Status"`
2. Validate strategy performance vs backtest expectations
3. Check for any failed health checks

**Monthly Tasks**:
1. Review cumulative performance
2. Compare live results with WFO out-of-sample expectations
3. Run Monte Carlo on live trades to validate robustness
4. Adjust parameters if strategy degrading (only after analysis)

**Emergency Procedures**:
- **Market crash**: Run `scripts/emergency_exit.py` to liquidate
- **API failure**: Check Schwab status page, wait for resolution
- **Strategy malfunction**: Disable cron job, investigate logs, fix, re-enable
- **Slippage spike**: Review fill quality, consider reducing position size

---

### Configuration Reference

**Environment Variables** (`.env`):
```env
# Schwab API (Required)
SCHWAB_CLIENT_ID=<your_client_id>
SCHWAB_CLIENT_SECRET=<your_client_secret>
SCHWAB_REDIRECT_URI=https://127.0.0.1:8182
SCHWAB_TOKEN_PATH=./token.json

# Live Trading (Required)
LIVE_TRADING_STATE_FILE=./data/live_trading_state.json
LIVE_TRADING_TRADE_LOG=./data/live_trades.csv
LIVE_TRADING_DRY_RUN=true  # false for Phase 2/3

# Risk Management (Required)
LIVE_TRADING_MAX_SLIPPAGE_PCT=0.5

# Alerts (Optional - Phase 3)
TWILIO_ACCOUNT_SID=<twilio_sid>
TWILIO_AUTH_TOKEN=<twilio_token>
TWILIO_FROM_NUMBER=<+1234567890>
TWILIO_TO_NUMBER=<+1987654321>

SENDGRID_API_KEY=<sendgrid_api_key>
SENDGRID_FROM_EMAIL=<alerts@domain.com>
SENDGRID_TO_EMAIL=<you@domain.com>
```

**State File Schema** (`live_trading_state.json`):
```json
{
  "last_run_date": "2025-11-23",
  "portfolio": {
    "cash": 5450.00,
    "positions": {
      "TQQQ": {
        "shares": 100,
        "avg_price": 45.50
      }
    }
  },
  "last_strategy_state": "Bullish_Strong",
  "last_decision": "BUY",
  "last_execution_time": 13.2
}
```

**Trade Log Schema** (`live_trades.csv`):
```csv
Date,Strategy_State,Ticker,Decision,Shares,Price,Slippage_Pct,Position_Value,Portfolio_Value_After,Allocation_After,DRY_RUN
2025-11-23 15:55:00,Bullish_Strong,TQQQ,BUY,100,45.50,0.04,4550.00,9450.00,"TQQQ: 48.1%, CASH: 51.9%",false
```

---

### Performance Targets

**Execution Latency**:
- Total workflow (15:50-15:56): <60 seconds ✅
- Order submission: <5 seconds per order ✅
- Fill validation: <2 seconds ✅
- State save: <1 second ✅

**Reliability**:
- Order fill rate: 100% (retry logic ensures fills) ✅
- State corruption: 0% (atomic writes prevent corruption) ✅
- Cron execution: 100% (runs daily Mon-Fri at 15:50) ✅

**Quality**:
- Slippage average: <0.3% (monitored and logged) ✅
- Alert delivery: <5 seconds (SMS + Email) ✅
- Health check duration: <10 seconds (all checks) ✅

---

### Troubleshooting

**Issue: OAuth token expired**
```
Error: 401 Unauthorized
```
Solution: Re-run OAuth flow
```bash
python3 scripts/schwab_oauth.py
```

**Issue: Cron job not executing**
```
# Check cron status
crontab -l | grep live_trader

# Verify cron service running
systemctl status cron  # Linux
launchctl list | grep cron  # macOS
```

**Issue: Slippage exceeds threshold**
```
CRITICAL: Slippage 1.2% exceeds abort threshold 1.0%
```
Solution: Review market conditions, consider reducing position size or pausing trading

**Issue: State file corrupted**
```
Error: Invalid JSON in live_trading_state.json
```
Solution: Restore from backup (atomic writes create `.tmp` backups)
```bash
cp data/live_trading_state.json.tmp data/live_trading_state.json
```

**Issue: SMS/Email alerts not sending**
```
Warning: Failed to send SMS alert
```
Solution: Verify Twilio/SendGrid credentials in `.env`, check API key validity

---

### Safety & Risk Disclosure

**IMPORTANT**: Live trading involves significant financial risk. This software is provided "AS IS" without warranty. The authors assume NO responsibility for:
- Financial losses from live trading
- Execution errors or API failures
- Strategy underperformance
- Slippage or market impact
- Data quality issues

**Best Practices**:
1. ✅ Start with Phase 1 dry-run (2-4 weeks minimum)
2. ✅ Validate in Phase 2 paper trading (4-8 weeks minimum)
3. ✅ Only use capital you can afford to lose
4. ✅ Monitor daily for first 2 weeks of production
5. ✅ Set reasonable risk limits (max_position_pct, min_cash_reserve)
6. ✅ Have emergency exit plan ready
7. ✅ Never override safety checks (NO fractional shares, slippage validation)

**You accept full responsibility** for any financial outcomes when using live trading features.

---

## 📚 Documentation

### Core Documentation
- **[README.md](README.md)**: Project overview and quick start (this file)
- **[SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)**: Complete architecture and design decisions
- **[API_REFERENCE.md](docs/API_REFERENCE.md)**: Comprehensive API documentation
- **[BEST_PRACTICES.md](docs/BEST_PRACTICES.md)**: Financial data handling and coding standards
- **[CLAUDE.md](docs/CLAUDE.md)**: Development guide for AI assistants
- **[CHANGELOG.md](CHANGELOG.md)**: Version history and release notes

### Strategy Documentation
- **[MACD_Trend-v4.md](jutsu_engine/strategies/MACD_Trend-v4.md)**: Goldilocks strategy documentation
- **[MACD_Trend-v5.md](jutsu_engine/strategies/MACD_Trend-v5.md)**: Dynamic Regime strategy
- **[MACD_Trend-v6.md](jutsu_engine/strategies/MACD_Trend-v6.md)**: VIX-Filtered strategy
- **[Hierarchical_Adaptive_v3_5b.md](jutsu_engine/strategies/Hierarchical_Adaptive_v3_5b.md)**: Golden strategy

### API & Dashboard
- **[V2_API_BASELINE_LIMITATION.md](docs/V2_API_BASELINE_LIMITATION.md)**: V2 API baseline data details
- **[RESPONSIVE-UI-PROGRESS.md](docs/RESPONSIVE-UI-PROGRESS.md)**: Mobile UI implementation status
- **EOD Workflow**: `claudedocs/eod_daily_performance_workflow.md`

### Additional Resources
- **Example Scripts**: See `scripts/` directory for backfill, verification, and live trading
- **Test Suite**: See `tests/` for unit, integration, and E2E tests (Playwright)
- **Configuration**: See `config/` for YAML templates and environment examples
- **Grid Search Configs**: See `grid-configs/examples/` for parameter optimization setups

## 🛠️ Development

### Project Structure

```
jutsu-labs/
├── jutsu_engine/              # Core Python library
│   ├── core/                  # Domain logic (EventLoop, Strategy base)
│   ├── application/           # Use cases (Backtest runner, Data sync)
│   ├── data/                  # Data infrastructure (Handlers, Database, Models)
│   ├── api/                   # FastAPI routes, schemas, WebSocket, scheduler
│   │   ├── routes/            # REST endpoints (performance_v2, trades, etc.)
│   │   ├── scheduler.py       # APScheduler hourly/EOD jobs
│   │   └── websocket.py       # Real-time push notifications
│   ├── jobs/                  # Scheduled jobs (EOD finalization)
│   ├── indicators/            # Technical analysis functions
│   ├── portfolio/             # Portfolio management
│   ├── performance/           # Metrics calculation
│   ├── strategies/            # Strategy implementations (MACD_Trend_v4/v5/v6, etc.)
│   ├── live/                  # Live trading (alerts, order execution)
│   └── utils/                 # Utilities (KPI calculations, trading calendar)
├── dashboard/                 # React 18 + TypeScript frontend
│   ├── src/
│   │   ├── api/               # API client with React Query
│   │   ├── components/        # Reusable UI components
│   │   ├── contexts/          # React contexts (Auth, Strategy, Theme)
│   │   ├── hooks/             # Custom hooks (useWebSocket, useMultiStrategyData)
│   │   └── pages/v2/          # Dashboard, Performance, Backtest, Trades pages
│   └── vite.config.ts         # Vite build configuration
├── alembic/                   # Database migrations
├── tests/                     # Tests (unit, integration, e2e with Playwright)
├── scripts/                   # Utility scripts (backfill, verify, live trader)
├── docs/                      # Documentation
├── config/                    # Configuration files (YAML, env templates)
├── grid-configs/              # Grid search YAML configurations
└── docker-compose.yml         # Multi-container deployment
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
- [x] Monte Carlo simulation for robustness testing
- [x] Walk-forward optimization for out-of-sample validation

### Phase 3: UI & Dashboard ✅ COMPLETE
- [x] React 18 + TypeScript dashboard with Vite
- [x] Multi-container Docker deployment
- [x] Scheduled data refresh jobs (hourly + market close)
- [x] Multi-strategy comparison (up to 3 strategies)
- [x] Responsive mobile-first design (63 tasks complete)
- [x] WebSocket real-time updates
- [x] Backtest dashboard with regime visualization
- [x] Performance dashboard with KPIs and equity curves

### Phase 4: Production Features ✅ COMPLETE
- [x] Live trading with 4-phase safety approach (dry-run → paper → production)
- [x] Multi-user access with role-based permissions (Admin, Trader, Viewer)
- [x] 2FA authentication (TOTP + backup codes)
- [x] Passkey/WebAuthn passwordless authentication
- [x] EOD Daily Performance system with pre-computed KPIs
- [x] Performance API v2 with baseline comparison
- [x] Multi-strategy parallel tracking and scheduling
- [x] SMS/Email alerting via Twilio/SendGrid

### Future Enhancements (Planned)
- [ ] Machine learning strategy evaluation
- [ ] Kubernetes horizontal scaling
- [ ] Mobile companion app (iOS/Android)
- [ ] Options and futures support

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
- Dashboard built with [React 18](https://react.dev), [TypeScript](https://www.typescriptlang.org), and [Vite](https://vitejs.dev)
- Charts powered by [Lightweight Charts](https://tradingview.github.io/lightweight-charts/) and [Plotly](https://plotly.com/javascript/)
- API powered by [FastAPI](https://fastapi.tiangolo.com) with [Pydantic](https://pydantic-docs.helpmanual.io)
- Trading calendar via [pandas_market_calendars](https://github.com/rsheftel/pandas_market_calendars)
- Following hexagonal architecture principles

---

**⚠️ Disclaimer**: This software is for educational and research purposes only. Past performance does not guarantee future results. Trading involves risk. Always test strategies thoroughly before using real capital.
