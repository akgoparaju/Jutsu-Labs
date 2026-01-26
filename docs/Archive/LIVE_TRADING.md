# Live Trading Guide

**WARNING**: Live trading with real money carries significant risk. ONLY proceed to production (Phase 2/3) after thorough testing in dry-run mode (Phase 1). The authors assume NO responsibility for financial losses.

---

## Overview

Jutsu Labs supports **automated live trading** with a 4-phase approach designed for safety and progressive validation:

| Phase | Mode | Purpose | Risk Level | Execution |
|-------|------|---------|------------|-----------|
| **Phase 0** | Setup | OAuth authentication, market calendar validation | None | One-time setup |
| **Phase 1** | Dry-Run | Test workflow without placing orders | None | Daily cron |
| **Phase 2** | Paper Trading | Real orders in paper/sandbox account | Low | Daily cron |
| **Phase 3** | Production | Real orders + alerts + health monitoring | HIGH | Daily cron |

### Key Features

- **3:55 Protocol**: Executes 5 minutes before market close using synthetic daily bar
- **NO FRACTIONAL SHARES**: Always rounds DOWN to whole shares
- **Atomic State Management**: Temp file + rename pattern prevents corruption
- **Slippage Validation**: Three-tier thresholds (0.3% warning, 0.5% max, 1.0% abort)
- **Financial Precision**: All calculations use `Decimal` type (never float)
- **Emergency Exit**: Close all positions in <30 seconds
- **Health Monitoring**: Automated checks every 6 hours
- **Alert System**: SMS + Email notifications via Twilio/SendGrid

---

## Phase 0: Setup (One-Time)

### Prerequisites

1. Schwab brokerage account with API access
2. Schwab API credentials (client ID + secret)
3. Python 3.10+ environment

### Step 1: Environment Configuration

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

### Step 2: OAuth Authentication

Run interactive OAuth flow (one-time):

```bash
python3 scripts/schwab_oauth.py
```

This will:
1. Open browser for Schwab login
2. Prompt for authorization code
3. Save `token.json` (auto-refreshes every 30 minutes)
4. Validate token is working

### Step 3: Market Calendar Validation

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

### Step 4: Create Configuration File

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

## Phase 1: Dry-Run Mode (Recommended: 2-4 Weeks)

**Purpose**: Validate entire workflow WITHOUT placing real orders. Simulates order execution and logs what WOULD happen.

### Step 1: Enable Dry-Run Mode

In `.env`:
```env
LIVE_TRADING_DRY_RUN=true
```

### Step 2: Manual Test Run

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

### Step 3: Schedule Daily Cron Job

Add to crontab (runs Mon-Fri at 15:50 EST):

```bash
crontab -e
```

Add line:
```cron
# Live Trading - Dry-Run Mode (Phase 1)
50 15 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/live_trader.py >> logs/live_trader.log 2>&1
```

### Step 4: Monitor Logs

Check daily execution:

```bash
# Real-time monitoring
tail -f logs/live_trader.log

# Review trade log
cat data/live_trades.csv
```

Expected Trade Log (CSV format):
```csv
Date,Strategy_State,Ticker,Decision,Shares,Price,Position_Value,Portfolio_Value_After,Allocation_After,DRY_RUN
2025-11-23 15:55:00,Bullish_Strong,TQQQ,BUY,100,45.50,4550.00,9450.00,"TQQQ: 48.1%, CASH: 51.9%",true
2025-11-24 15:55:00,Bullish_Strong,TQQQ,HOLD,100,46.25,4625.00,9625.00,"TQQQ: 48.0%, CASH: 52.0%",true
```

### Step 5: Validation Checklist

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

## Phase 2: Paper Trading (Recommended: 4-8 Weeks)

**WARNING**: Phase 2 places REAL ORDERS in your paper/sandbox account. Ensure you have a Schwab paper trading account configured.

**Purpose**: Execute real orders via Schwab API with slippage validation and retry logic.

### Step 1: Disable Dry-Run Mode

In `.env`:
```env
LIVE_TRADING_DRY_RUN=false
```

### Step 2: Configure Paper Trading Account

Ensure Schwab API credentials point to **paper/sandbox account** (NOT production account).

### Step 3: Update Cron Job

Replace Phase 1 script with Phase 2 script:

```bash
crontab -e
```

Update line:
```cron
# Live Trading - Paper Trading Mode (Phase 2)
50 15 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/live_trader_paper.py >> logs/live_trader_paper.log 2>&1
```

### Step 4: Manual Test Run

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

### Step 5: Order Execution Features

Phase 2 includes:

1. **Order Sequencing**: SELL orders first (raise cash), then BUY orders
2. **Retry Logic**: Up to 3 attempts for partial fills (5-second delay)
3. **Slippage Validation**: Three-tier thresholds
   - WARNING: 0.3% (log warning, continue)
   - MAX: 0.5% (log critical, continue)
   - ABORT: 1.0% (raise exception, halt trading)
4. **Fill Validation**: Compare expected vs actual fill price
5. **Trade Logging**: All fills logged to CSV with slippage metrics

### Step 6: Monitor Paper Trading

Check logs and trade performance:

```bash
# Real-time monitoring
tail -f logs/live_trader_paper.log

# Review fills and slippage
cat data/live_trades.csv | grep -v "DRY_RUN"

# Check Schwab paper account
# (Log into Schwab paper trading portal to verify positions)
```

### Step 7: Validation Checklist

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

## Phase 3: Production Hardening

**WARNING**: Phase 3 is for production live trading with REAL MONEY. Only proceed if you accept full financial risk.

**Purpose**: Add SMS/Email alerts, health monitoring, and emergency procedures for production safety.

### Step 1: Configure Alert Services

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

### Step 2: Enable Alerts in Config

In `config/live_trading_config.yaml`:
```yaml
alerts:
  enabled: true
  sms_enabled: true
  email_enabled: true
  critical_only: false  # Send all alerts (recommended)
```

### Step 3: Test Alert System

Manually trigger test alert:

```bash
python3 -c "
from jutsu_engine.live.alert_manager import AlertManager
alerts = AlertManager()
alerts.send_info_alert('Test alert from Jutsu Labs')
"
```

You should receive SMS + Email within 5 seconds.

### Step 4: Schedule Health Checks

Add health monitoring cron (runs every 6 hours):

```bash
crontab -e
```

Add line:
```cron
# Health Monitoring (every 6 hours)
0 */6 * * * cd /path/to/jutsu-labs && /path/to/venv/bin/python3 scripts/health_check.py >> logs/health_check.log 2>&1
```

### Step 5: Health Check Features

Automated checks:
1. **API Connectivity**: Test Schwab API with sample request
2. **State File Integrity**: Validate JSON structure and required fields
3. **Disk Space**: Ensure >1GB available
4. **Cron Schedule**: Verify cron job exists and is correct

Example output:
```
Health Check Report - 2025-11-23 18:00:00
============================================
 API Connectivity: OK (response time: 234ms)
 State File Integrity: OK (valid JSON, all fields present)
 Disk Space: OK (12.3 GB available)
 Cron Schedule: OK (found entry for 15:50 daily)

Overall Status: HEALTHY
```

### Step 6: Emergency Exit Procedure

Create `scripts/emergency_exit.py` for instant liquidation:

```bash
python3 scripts/emergency_exit.py
```

Interactive confirmation required:
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

### Step 7: Production Deployment Checklist

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

### Step 8: Switch to Production Account

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

## Daily Monitoring & Maintenance

### Daily Tasks

1. Check logs for errors: `tail logs/live_trader_prod.log`
2. Verify fills in trade log: `cat data/live_trades.csv | tail -5`
3. Compare Schwab account positions with state file
4. Review slippage metrics (should be <0.3% average)

### Weekly Tasks

1. Review health check reports: `cat logs/health_check.log | grep "Overall Status"`
2. Validate strategy performance vs backtest expectations
3. Check for any failed health checks

### Monthly Tasks

1. Review cumulative performance
2. Compare live results with WFO out-of-sample expectations
3. Run Monte Carlo on live trades to validate robustness
4. Adjust parameters if strategy degrading (only after analysis)

### Emergency Procedures

- **Market crash**: Run `scripts/emergency_exit.py` to liquidate
- **API failure**: Check Schwab status page, wait for resolution
- **Strategy malfunction**: Disable cron job, investigate logs, fix, re-enable
- **Slippage spike**: Review fill quality, consider reducing position size

---

## Configuration Reference

### Environment Variables (`.env`)

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

### State File Schema (`live_trading_state.json`)

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

### Trade Log Schema (`live_trades.csv`)

```csv
Date,Strategy_State,Ticker,Decision,Shares,Price,Slippage_Pct,Position_Value,Portfolio_Value_After,Allocation_After,DRY_RUN
2025-11-23 15:55:00,Bullish_Strong,TQQQ,BUY,100,45.50,0.04,4550.00,9450.00,"TQQQ: 48.1%, CASH: 51.9%",false
```

---

## Performance Targets

### Execution Latency

| Metric | Target |
|--------|--------|
| Total workflow (15:50-15:56) | <60 seconds |
| Order submission | <5 seconds per order |
| Fill validation | <2 seconds |
| State save | <1 second |

### Reliability

| Metric | Target |
|--------|--------|
| Order fill rate | 100% (retry logic ensures fills) |
| State corruption | 0% (atomic writes prevent corruption) |
| Cron execution | 100% (runs daily Mon-Fri at 15:50) |

### Quality

| Metric | Target |
|--------|--------|
| Slippage average | <0.3% (monitored and logged) |
| Alert delivery | <5 seconds (SMS + Email) |
| Health check duration | <10 seconds (all checks) |

---

## Troubleshooting

### OAuth token expired

```
Error: 401 Unauthorized
```

**Solution**: Re-run OAuth flow
```bash
python3 scripts/schwab_oauth.py
```

### Cron job not executing

```bash
# Check cron status
crontab -l | grep live_trader

# Verify cron service running
systemctl status cron  # Linux
launchctl list | grep cron  # macOS
```

### Slippage exceeds threshold

```
CRITICAL: Slippage 1.2% exceeds abort threshold 1.0%
```

**Solution**: Review market conditions, consider reducing position size or pausing trading

### State file corrupted

```
Error: Invalid JSON in live_trading_state.json
```

**Solution**: Restore from backup (atomic writes create `.tmp` backups)
```bash
cp data/live_trading_state.json.tmp data/live_trading_state.json
```

### SMS/Email alerts not sending

```
Warning: Failed to send SMS alert
```

**Solution**: Verify Twilio/SendGrid credentials in `.env`, check API key validity

---

## Safety & Risk Disclosure

**IMPORTANT**: Live trading involves significant financial risk. This software is provided "AS IS" without warranty. The authors assume NO responsibility for:

- Financial losses from live trading
- Execution errors or API failures
- Strategy underperformance
- Slippage or market impact
- Data quality issues

### Best Practices

1. Start with Phase 1 dry-run (2-4 weeks minimum)
2. Validate in Phase 2 paper trading (4-8 weeks minimum)
3. Only use capital you can afford to lose
4. Monitor daily for first 2 weeks of production
5. Set reasonable risk limits (max_position_pct, min_cash_reserve)
6. Have emergency exit plan ready
7. Never override safety checks (NO fractional shares, slippage validation)

**You accept full responsibility** for any financial outcomes when using live trading features.
