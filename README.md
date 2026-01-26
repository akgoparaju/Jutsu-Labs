# Jutsu Labs

**Automated trading made transparent.** A backtesting and live trading platform for systematic strategies.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker Ready](https://img.shields.io/badge/docker-ready-2496ED.svg)](https://www.docker.com/)

---

## What is Jutsu Labs?

Jutsu Labs helps you **build, test, and run** trading strategies with confidence:

- **Backtest** strategies against historical data with detailed performance metrics
- **Optimize** parameters using grid search, walk-forward analysis, and Monte Carlo simulation
- **Monitor** live performance through a modern web dashboard
- **Execute** trades automatically with built-in safety controls

Built for individual traders and small teams who want **full control** over their trading systems.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Strategy Backtesting** | Test strategies against years of historical data with realistic commission and slippage modeling |
| **Parameter Optimization** | Find optimal parameters with grid search, walk-forward optimization, and Monte Carlo analysis |
| **Web Dashboard** | Real-time performance monitoring with equity curves, regime analysis, and trade history |
| **Multi-Strategy Tracking** | Compare up to 3 strategies side-by-side with live performance metrics |
| **Live Trading** | Automated execution with 4-phase safety approach (dry-run → paper → production) |
| **Data Management** | Sync from Schwab API, Yahoo Finance, or import your own CSV files |

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/jutsu-labs.git
cd jutsu-labs

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Start all services
docker-compose up -d

# Open dashboard
open http://localhost:3000
```

### Option 2: Local Development

```bash
# Clone and setup
git clone https://github.com/yourusername/jutsu-labs.git
cd jutsu-labs

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install
pip install -e .
cp .env.example .env

# Initialize and sync data
jutsu init
jutsu sync yahoo --symbol AAPL --timeframe 1D --start 2024-01-01

# Run a backtest
jutsu backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31 --capital 100000
```

---

## Dashboard Preview

The web dashboard provides real-time visibility into your trading strategies:

- **Dashboard** - Key metrics, strategy comparison, equity curves
- **Performance** - Detailed KPIs, regime breakdown, daily performance table
- **Backtest** - Historical analysis with date range selection
- **Trades** - Complete trade history with filtering
- **Settings** - Account management, 2FA, user invitations

Access at `http://localhost:3000` after starting Docker.

---

## Included Strategies

Jutsu Labs includes production-tested strategies:

| Strategy | Description |
|----------|-------------|
| **Hierarchical Adaptive v3.5b** | Multi-regime trend-following with dynamic position sizing |
| **MACD Trend v4** (Goldilocks) | EMA trend + MACD momentum with dual-mode position sizing |
| **MACD Trend v5** | Dual-regime with VIX-based parameter switching |
| **MACD Trend v6** | VIX-gated execution with binary market filter |

All strategies are configurable via YAML files and support parameter optimization.

---

## Live Trading

Jutsu Labs supports automated live trading with a progressive safety approach:

| Phase | Mode | Purpose |
|-------|------|---------|
| **Phase 0** | Setup | OAuth authentication, calendar validation |
| **Phase 1** | Dry-Run | Test workflow without placing orders (2-4 weeks) |
| **Phase 2** | Paper | Real orders in sandbox account (4-8 weeks) |
| **Phase 3** | Production | Real money with alerts and monitoring |

Features include:
- 3:55 PM execution protocol (5 minutes before market close)
- Slippage validation and retry logic
- SMS and email alerts via Twilio/SendGrid
- Emergency position liquidation

See [Live Trading Guide](docs/LIVE_TRADING.md) for detailed setup instructions.

---

## Documentation

| Document | Description |
|----------|-------------|
| [System Design](docs/SYSTEM_DESIGN.md) | Architecture and design decisions |
| [API Reference](docs/API_REFERENCE.md) | REST API endpoints and schemas |
| [Best Practices](docs/BEST_PRACTICES.md) | Financial data handling standards |
| [Strategy Docs](jutsu_engine/strategies/) | Individual strategy documentation |
| [Changelog](CHANGELOG.md) | Version history and release notes |

For development setup, testing, and contribution guidelines, see [Developer Guide](README.developer.md).

---

## Requirements

- **Python** 3.10 or higher
- **Docker** (recommended for production)
- **Schwab API credentials** (for live data and trading)
- **Node.js 18+** (for dashboard development only)

---

## Security

- JWT-based authentication with refresh tokens
- TOTP two-factor authentication with backup codes
- Passkey/WebAuthn passwordless login
- Role-based access control (Admin, Trader, Viewer)
- Encrypted credential storage

---

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/jutsu-labs/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/jutsu-labs/discussions)

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Disclaimer

This software is for educational and research purposes. Trading involves significant financial risk. Past performance does not guarantee future results. The authors assume no responsibility for financial losses. Always test strategies thoroughly before using real capital.
