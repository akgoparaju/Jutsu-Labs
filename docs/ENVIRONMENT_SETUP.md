# Environment Setup Guide - Jutsu Labs

> Step-by-step guide for configuring your development environment

**Last Updated:** November 2, 2025

---

## Overview

This guide will help you set up the Jutsu Labs backtesting engine on your local machine, including:
1. Python environment configuration
2. Schwab API credentials setup
3. Database initialization
4. Verification and testing

---

## Prerequisites

### Required Software
- **Python 3.10+** (Python 3.11 recommended)
- **pip** package manager
- **Git** (for version control)
- **Schwab Developer Account** (for market data access)

### Check Your Python Version
```bash
python --version
# Should show: Python 3.10.x or higher
```

---

## Step 1: Clone and Setup Project

### 1.1 Clone Repository (if not already done)
```bash
cd ~/Documents/Python/Projects
git clone <repository-url> Jutsu-Labs
cd Jutsu-Labs
```

### 1.2 Create Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows

# Verify activation (should show venv in prompt)
which python
# Should show: /path/to/Jutsu-Labs/venv/bin/python
```

### 1.3 Install Dependencies
```bash
# Install in editable mode
pip install -e .

# Verify installation
jutsu --version
# Should show: Jutsu, version 0.1.0
```

---

## Step 2: Schwab API Credentials

### 2.1 Create Developer Account

1. **Go to Schwab Developer Portal**
   - Visit: https://developer.schwab.com
   - Click "Sign Up" or "Login"

2. **Create Application**
   - Navigate to "My Apps"
   - Click "Create New App"
   - Fill in application details:
     - **App Name**: "Jutsu Labs Backtesting" (or your preference)
     - **App Type**: "Individual"
     - **Callback URL**: `https://localhost:8080/callback`

3. **Get Credentials**
   - After creation, you'll receive:
     - **API Key (Client ID)**: Long alphanumeric string
     - **API Secret**: Another long alphanumeric string
   - **IMPORTANT**: Save these securely - you'll need them for configuration

### 2.2 Understanding API Limits

**Schwab API Rate Limits:**
- **2 requests per second** maximum
- **120 requests per minute** maximum
- Exceeding limits results in HTTP 429 errors

**Jutsu Labs implements automatic rate limiting**, so you don't need to worry about this during normal usage.

---

## Step 3: Environment Configuration

### 3.1 Locate .env File

The `.env` file should already exist in the project root. If it doesn't:

```bash
# Check if .env exists
ls -la .env

# If missing, create from template
cp .env.example .env
```

### 3.2 Edit .env File

Open `.env` in your text editor:

```bash
# Using nano
nano .env

# Or using VS Code
code .env

# Or any text editor you prefer
```

### 3.3 Add Your Schwab Credentials

Replace the placeholder values with your actual credentials:

```bash
# Schwab API Credentials
# Get your API credentials from https://developer.schwab.com
SCHWAB_API_KEY=your_actual_api_key_here_from_schwab_portal
SCHWAB_API_SECRET=your_actual_secret_here_from_schwab_portal
SCHWAB_CALLBACK_URL=https://localhost:8080/callback

# Database Configuration
DATABASE_URL=sqlite:///data/market_data.db

# Logging Configuration
LOG_LEVEL=INFO
LOG_TO_CONSOLE=true

# Application Configuration
ENV=development
DEBUG=true

# Data Configuration
DATA_CACHE_DIR=data/
DEFAULT_TIMEFRAME=1D
DEFAULT_LOOKBACK_DAYS=365

# Backtest Configuration
INITIAL_CAPITAL=100000
DEFAULT_COMMISSION=0.01
DEFAULT_SLIPPAGE=0.0

# API Configuration (future)
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Security
SECRET_KEY=your_secret_key_for_jwt_tokens_here
```

**IMPORTANT:**
- Replace `your_actual_api_key_here_from_schwab_portal` with your API Key
- Replace `your_actual_secret_here_from_schwab_portal` with your API Secret
- Keep the callback URL as `https://localhost:8080/callback`
- Don't commit `.env` to git (it's in `.gitignore`)

### 3.4 Verify .env is Gitignored

```bash
# Check if .env is in .gitignore
grep "^\.env$" .gitignore

# Should output: .env
```

✅ **The .env file is already excluded from version control** - your credentials are safe!

---

## Step 4: Database Initialization

### 4.1 Initialize Database

```bash
# Create database tables
jutsu init

# Expected output:
# ✅ Database initialized successfully
# ✅ Created tables: market_data, data_metadata, data_audit_log
# ✅ Database location: data/market_data.db
```

### 4.2 Verify Database

```bash
# Check database file was created
ls -la data/market_data.db

# Should show: -rw-r--r--  1 user  staff  <size> <date> data/market_data.db
```

---

## Step 5: Test Configuration

### 5.1 Verify CLI Commands

```bash
# Test CLI is working
jutsu --help

# Should show all available commands:
# - init       Initialize database
# - sync       Sync market data
# - status     Check data status
# - validate   Validate data integrity
# - backtest   Run backtest
```

### 5.2 Check Status (Before Data Sync)

```bash
# Check system status
jutsu status

# Expected output (no data yet):
# 📊 Jutsu Labs Status
#
# Database: ✅ Connected (SQLite)
# Symbols: 0 symbols tracked
# Data Range: No data available
```

### 5.3 Test Data Sync (Optional)

**WARNING**: This will make API calls to Schwab!

```bash
# Sync a small amount of data (last 30 days)
jutsu sync AAPL --timeframe 1D --start-date 2024-10-01

# Expected output:
# 🔄 Syncing AAPL data...
# ✅ Fetched 21 bars (2024-10-01 to 2024-10-31)
# ✅ Validated and stored 21 bars
# ✅ Updated metadata
```

### 5.4 Verify Data Was Stored

```bash
# Check status again
jutsu status

# Expected output:
# 📊 Jutsu Labs Status
#
# Database: ✅ Connected (SQLite)
# Symbols: 1 symbol(s) tracked
#   - AAPL: 21 bars (2024-10-01 to 2024-10-31)
```

---

## Step 6: Run Your First Backtest

### 6.1 Sync More Historical Data

```bash
# Sync 1 year of data for AAPL
jutsu sync AAPL --timeframe 1D --start-date 2023-01-01

# This will take ~2-3 minutes due to rate limiting
# You should see progress updates
```

### 6.2 Run Backtest

```bash
# Run SMA Crossover strategy
jutsu backtest AAPL \
  --strategy SMA_Crossover \
  --start-date 2023-01-01 \
  --end-date 2024-10-31 \
  --capital 100000

# Expected output:
# 🎯 Running backtest...
# ✅ Backtest complete!
#
# 📊 Performance Summary:
# Total Return: +15.2%
# Sharpe Ratio: 1.23
# Max Drawdown: -8.5%
# Win Rate: 58.3%
# Total Trades: 12
```

---

## Common Issues and Troubleshooting

### Issue 1: "API credentials not found"

**Symptom:**
```
❌ Error: SCHWAB_API_KEY not found in environment
```

**Solution:**
```bash
# 1. Verify .env file exists
ls -la .env

# 2. Check .env has your credentials
cat .env | grep SCHWAB_API_KEY

# 3. Make sure virtual environment is activated
source venv/bin/activate

# 4. Try loading .env manually
export $(cat .env | grep -v '^#' | xargs)
```

### Issue 2: "Database not initialized"

**Symptom:**
```
❌ Error: Table 'market_data' does not exist
```

**Solution:**
```bash
# Initialize database
jutsu init

# Verify database file
ls -la data/market_data.db
```

### Issue 3: "Rate limit exceeded"

**Symptom:**
```
⚠️  Warning: Rate limit exceeded (HTTP 429)
```

**Solution:**
- **This is normal** - Jutsu Labs automatically retries with exponential backoff
- Just wait - it will resume automatically
- Consider syncing smaller date ranges

### Issue 4: "Module not found"

**Symptom:**
```
ModuleNotFoundError: No module named 'jutsu_engine'
```

**Solution:**
```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Reinstall in editable mode
pip install -e .

# 3. Verify installation
jutsu --version
```

### Issue 5: ".env file not loading"

**Symptom:**
Environment variables not being read despite .env existing

**Solution:**
```bash
# Manually load .env for testing
export $(cat .env | grep -v '^#' | xargs)

# Or use python-dotenv
pip install python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv(); print('✅ Loaded')"
```

---

## Security Best Practices

### ✅ Do's:
- ✅ Keep `.env` file in `.gitignore`
- ✅ Use strong, unique API credentials
- ✅ Regularly rotate your API secrets
- ✅ Use environment variables for all secrets
- ✅ Back up `.env` to a secure location (not git!)

### ❌ Don'ts:
- ❌ Never commit `.env` to git
- ❌ Never share your API credentials
- ❌ Never store credentials in code
- ❌ Never use production credentials in development
- ❌ Never push `.env` to public repositories

---

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SCHWAB_API_KEY` | Schwab API Client ID | `abc123xyz...` |
| `SCHWAB_API_SECRET` | Schwab API Secret | `def456uvw...` |
| `SCHWAB_CALLBACK_URL` | OAuth callback URL | `https://localhost:8080/callback` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///data/market_data.db` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `LOG_TO_CONSOLE` | Enable console logging | `true` |
| `ENV` | Environment name | `development` |
| `DEBUG` | Debug mode | `true` |
| `INITIAL_CAPITAL` | Default backtest capital | `100000` |
| `DEFAULT_COMMISSION` | Commission per share | `0.01` |

---

## Next Steps

Now that your environment is set up:

1. **Explore Available Strategies**
   - See `jutsu_engine/strategies/` for examples
   - Start with `SMA_Crossover` (already implemented)

2. **Read Documentation**
   - `docs/SYSTEM_DESIGN.md` - Architecture overview
   - `docs/BEST_PRACTICES.md` - Coding standards
   - `docs/IMPLEMENTATION_PRIORITY.md` - What to build next

3. **Run More Backtests**
   - Test different strategies
   - Compare performance
   - Analyze results

4. **Develop New Strategies**
   - See `docs/IMPLEMENTATION_PRIORITY.md` for priority
   - Start with RSI or MACD strategies
   - Use existing strategies as templates

---

## Support

### Documentation
- System Design: `docs/SYSTEM_DESIGN.md`
- Best Practices: `docs/BEST_PRACTICES.md`
- Implementation Guide: `docs/IMPLEMENTATION_PRIORITY.md`

### Getting Help
- Check logs in `logs/` directory
- Enable DEBUG mode in `.env`
- Review error messages carefully
- Consult Schwab API documentation: https://developer.schwab.com

---

## Summary

You should now have:
- ✅ Python virtual environment configured
- ✅ Jutsu Labs package installed
- ✅ `.env` file with Schwab credentials
- ✅ Database initialized
- ✅ CLI commands working
- ✅ First backtest completed successfully

**You're ready to start backtesting strategies!** 🎉

See `docs/IMPLEMENTATION_PRIORITY.md` for what to implement next.
