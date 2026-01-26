# Implementation Plan: Live Trading System (v3.5b)

**Version:** 1.0
**Status:** Planning
**Target Platform:** Schwab Thinkorswim (Paper Money)
**Strategy:** Hierarchical Adaptive v3.5b ("Titan Config")
**Created:** 2025-11-23

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Implementation Phases](#implementation-phases)
3. [Module Architecture](#module-architecture)
4. [Configuration Management](#configuration-management)
5. [Error Handling & Recovery](#error-handling--recovery)
6. [Testing Strategy](#testing-strategy)
7. [Validation Criteria](#validation-criteria)
8. [Risk Mitigation](#risk-mitigation)
9. [Deployment Checklist](#deployment-checklist)
10. [Maintenance & Monitoring](#maintenance--monitoring)

---

## Executive Summary

### Objective
Automate the Hierarchical Adaptive v3.5b strategy for live execution using Schwab's Thinkorswim platform (paper money incubation), replicating backtest performance with the "3:55 Protocol" execution model.

### Key Design Decisions

✅ **Validated Assumptions:**
- **Synthetic Bar Drift**: QQQ/TLT 15:55 vs 16:00 analysis shows average drift ≈0%, max drift -0.88%
- **Execution Window**: 15:50-15:56 EST provides 6-minute buffer for computation and validation
- **Whole Shares Only**: No fractional shares, round down to avoid over-allocation
- **Configurable Slippage**: Max acceptable slippage configurable (default: 0.5%)

✅ **Critical Safeguards:**
- Pre-execution auth validation (15:49:30)
- State reconciliation with live account positions
- Post-market validation reports
- Dry-run mode before paper trading
- Corporate action detection (splits, dividends)

---

## Implementation Phases

### Phase 0: Foundation & "Hello World" (Week 1)

**Duration:** 3-5 days
**Goal:** Establish authentication, basic data fetching, and cron scheduling

#### Deliverables

1. **Schwab Developer Setup**
   - Create Schwab Developer App (get API Key + Secret)
   - Configure OAuth 2.0 redirect URI
   - Test initial authentication flow manually

2. **Hello World Script** (`scripts/hello_schwab.py`)
   ```python
   # Minimal script to validate:
   # 1. OAuth authentication
   # 2. Token refresh mechanism
   # 3. Single quote fetch (QQQ)
   # 4. Account info retrieval
   ```

3. **Market Calendar Integration**
   - Implement `is_trading_day()` function
   - Test on weekend to validate graceful exit
   - Log market holidays from NYSE calendar

4. **Cron Scheduling Test**
   - Schedule dummy script to run at 15:49 EST
   - Verify timezone handling (EST vs local time)
   - Test across DST transition (if applicable)

**Success Criteria:**
- ✅ Script authenticates successfully on first run
- ✅ Token refresh works after 30-minute timeout
- ✅ Script correctly identifies weekends/holidays and exits
- ✅ Cron runs at exact scheduled time (±10 seconds)

---

### Phase 1: Dry-Run Mode (Weeks 2-3)

**Duration:** 10-15 trading days
**Goal:** Run full trading logic without executing orders, validate decision accuracy

#### Module Development

1. **LiveDataFetcher** (`jutsu_engine/live/data_fetcher.py`)
   ```python
   class LiveDataFetcher:
       def fetch_historical_bars(symbol, lookback=250) -> pd.DataFrame
       def fetch_current_quote(symbol) -> Decimal
       def create_synthetic_daily_bar(hist_df, current_quote) -> pd.DataFrame
       def validate_corporate_actions(df) -> bool
   ```

2. **LiveStrategyRunner** (`jutsu_engine/live/strategy_runner.py`)
   ```python
   class LiveStrategyRunner:
       def __init__(strategy_class, config)
       def calculate_signals(market_data) -> Dict[str, float]
       def determine_target_allocation(signals, account_value) -> Dict[str, Decimal]
   ```

3. **DryRunExecutor** (`jutsu_engine/live/dry_run_executor.py`)
   ```python
   class DryRunExecutor:
       def calculate_rebalance_diff(current, target) -> Dict[str, int]
       def log_hypothetical_orders(orders) -> None
       def compare_with_backtest_rerun() -> ValidationReport
   ```

4. **State Manager** (`jutsu_engine/live/state_manager.py`)
   ```python
   class StateManager:
       def load_state() -> Dict
       def save_state(state) -> None
       def validate_state_integrity() -> bool
       def reconcile_with_account(api_positions) -> Dict
   ```

#### Daily Workflow (15:49 - 15:56)

```
15:49:30 → Validate OAuth token, refresh if needed
15:50:00 → Check if trading day (market calendar)
15:50:30 → Fetch historical bars (QQQ, TLT - last 250 days)
15:51:00 → Fetch current quotes (all 5 symbols)
15:51:30 → Validate corporate actions (split/dividend detection)
15:52:00 → Create synthetic daily bar (append quote to history)
15:52:30 → Run v3.5b strategy logic (signals, allocation)
15:53:00 → Fetch account positions (for state reconciliation)
15:53:30 → Calculate rebalance diff (target - current)
15:54:00 → [DRY RUN] Log hypothetical orders
15:54:30 → Save state file (for tomorrow's comparison)
15:55:00 → [NO ACTUAL ORDERS IN DRY RUN]
```

#### Post-Market Validation (16:15)

```python
# scripts/post_market_validation.py
def daily_validation_report():
    """
    Compare:
    1. Decision at 15:55 (using 15:51 quotes)
    2. Backtest re-run at 16:00 (using actual close)
    3. Price divergence (15:55 vs 16:00)

    Email report:
    - ✅ GREEN: 100% logic match, <0.2% price drift
    - ⚠️  YELLOW: Logic match, 0.2-0.5% price drift
    - 🔴 RED: Logic mismatch OR >0.5% price drift
    """
```

**Success Criteria:**
- ✅ 10 consecutive trading days with no errors
- ✅ Logic match ≥95% (allow 1 divergence in 20 days for extreme volatility)
- ✅ Average price drift <0.3%
- ✅ State file never corrupted

**Data Collection:**
- Track 15:55 vs 16:00 price divergence daily
- Log all hypothetical orders for later analysis
- Record any API errors, timeouts, or data anomalies

---

### Phase 2: Paper Trading Execution (Weeks 4-7)

**Duration:** 20-30 trading days
**Goal:** Execute real orders in paper account, validate fill quality and slippage

#### New Modules

1. **OrderExecutor** (`jutsu_engine/live/order_executor.py`)
   ```python
   class OrderExecutor:
       def __init__(client, config)

       def execute_rebalance(orders: List[Order]) -> List[Fill]:
           # 1. Sell orders first (raise cash)
           # 2. Buy orders second
           # 3. Retry partial fills (max 3 attempts)
           # 4. Validate fills vs expected

       def submit_order(symbol, action, quantity) -> OrderID
       def check_fill_status(order_id) -> FillInfo
       def validate_slippage(expected_price, fill_price) -> bool
   ```

2. **SlippageValidator** (`jutsu_engine/live/slippage_validator.py`)
   ```python
   class SlippageValidator:
       def __init__(max_slippage_pct: float = 0.5)

       def validate_fill(symbol, expected_price, fill_price) -> bool:
           # Calculate slippage percentage
           # If > max_slippage_pct, log WARNING
           # If > 2 × max_slippage_pct, raise CRITICAL ERROR
   ```

3. **PositionRounder** (`jutsu_engine/live/position_rounder.py`)
   ```python
   class PositionRounder:
       @staticmethod
       def round_to_shares(dollar_amount, price) -> int:
           # NO FRACTIONAL SHARES
           # Always round DOWN to avoid over-allocation
           shares = int(dollar_amount / price)
           return shares

       @staticmethod
       def calculate_cash_remainder(target_allocation, executed_shares) -> Decimal:
           # Track unallocated cash from rounding
   ```

#### Enhanced Workflow (15:49 - 15:56)

```
15:49:30 → Validate OAuth token + test API call
15:50:00 → Check if trading day
15:50:30 → Fetch historical bars (250 days)
15:51:00 → Fetch current quotes
15:51:30 → Validate corporate actions
15:52:00 → Create synthetic daily bar
15:52:30 → Run strategy logic → Target allocation (% weights)
15:53:00 → Fetch account equity + positions
15:53:30 → Reconcile state.json with API positions
15:54:00 → Convert % weights to $ amounts
15:54:15 → Convert $ amounts to whole shares (round down)
15:54:30 → Calculate rebalance diff (shares to buy/sell)
15:54:45 → Filter orders by 5% threshold
15:55:00 → EXECUTE SELL ORDERS (market orders)
15:55:05 → Wait for fills, retry if partial
15:55:15 → EXECUTE BUY ORDERS (market orders)
15:55:20 → Wait for fills, retry if partial
15:55:30 → Validate all fills (slippage check)
15:55:45 → Update state.json with executed positions
15:56:00 → Log trade details to live_trades.csv
```

#### Error Handling Enhancements

```python
# Critical failures that ABORT trading
class CriticalFailure(Exception):
    pass

ABORT_CONDITIONS = [
    "OAuth authentication failed",
    "Corporate action detected (split >20%)",
    "Data fetch timeout >30 seconds",
    "Account equity mismatch >10%",
    "State file corrupted and no API backup"
]

# Recoverable warnings (continue but log)
WARNING_CONDITIONS = [
    "Slippage >0.5% but <1.0%",
    "Partial fill after 3 retries (log and continue)",
    "Price drift 15:55 vs 16:00 >0.5% but <1.0%"
]
```

**Success Criteria:**
- ✅ 20 consecutive trading days with no critical errors
- ✅ Average slippage <0.3% (below 0.5% threshold)
- ✅ Fill rate ≥99% (allow 1-2 partial fills in 20 days)
- ✅ Logic match with backtest ≥98%
- ✅ No position drift >2% between state.json and API

**Monitoring:**
- Daily email report (execution summary + slippage)
- Weekly performance comparison (paper account vs backtest)
- Track cash drag from share rounding

---

### Phase 3: Production Hardening (Week 8)

**Duration:** 5-7 days
**Goal:** Prepare for live trading with comprehensive error recovery

#### Additional Features

1. **AlertManager** (`jutsu_engine/live/alert_manager.py`)
   ```python
   class AlertManager:
       def send_sms(message) → via Twilio
       def send_email(subject, body) → via SendGrid
       def send_critical_alert(error) → SMS + Email + Log
   ```

2. **EmergencyKillSwitch** (`scripts/emergency_exit.py`)
   ```python
   # Manual script to:
   # 1. Close ALL positions immediately
   # 2. Move to 100% cash
   # 3. Disable cron job
   # 4. Send notification
   ```

3. **HealthCheckMonitor** (`jutsu_engine/live/health_monitor.py`)
   ```python
   class HealthMonitor:
       def check_api_connectivity() -> bool
       def check_state_file_integrity() -> bool
       def check_disk_space() -> bool
       def check_cron_schedule() -> bool

       # Run every 6 hours, alert if any check fails
   ```

**Final Testing:**
- Simulate API downtime (disconnect network at 15:52)
- Corrupt state.json file, verify recovery
- Test partial fill scenarios (manually cancel orders)
- Validate kill switch execution time (<30 seconds)

---

## Module Architecture

### Directory Structure

```
jutsu_engine/
├── live/                           # NEW: Live trading modules
│   ├── __init__.py
│   ├── data_fetcher.py            # Fetch live bars + quotes
│   ├── strategy_runner.py         # Run v3.5b logic on live data
│   ├── order_executor.py          # Execute orders via Schwab API
│   ├── state_manager.py           # State persistence + reconciliation
│   ├── slippage_validator.py      # Validate fill quality
│   ├── position_rounder.py        # Whole share calculations
│   ├── dry_run_executor.py        # Dry-run mode (no orders)
│   ├── alert_manager.py           # SMS/Email alerts
│   └── health_monitor.py          # System health checks
│
├── strategies/
│   └── Hierarchical_Adaptive_v3_5b.py  # REUSE existing strategy class
│
└── cli/
    └── main.py                     # Add 'jutsu live' command

scripts/
├── hello_schwab.py                 # Phase 0: Auth test
├── live_trader.py                  # Main cron script (15:50)
├── post_market_validation.py      # Validation script (16:15)
├── emergency_exit.py               # Kill switch
└── backtest_rerun.py               # Daily backtest comparison

config/
└── live_config.yaml                # Live trading configuration

logs/
├── live_trading_YYYY-MM-DD.log    # Daily execution logs
└── trade_history/
    └── live_trades.csv            # Trade log (CSV format)

state/
├── state.json                      # Current positions + vol state
└── state_backup_YYYY-MM-DD.json   # Daily backups
```

---

## Configuration Management

### Config File: `config/live_config.yaml`

```yaml
# Live Trading Configuration
version: "1.0"
environment: "paper"  # Options: dry_run, paper, live

# Strategy Parameters (Titan Config from PRD)
strategy:
  name: "Hierarchical_Adaptive_v3_5b"
  universe:
    signal_symbol: "QQQ"
    bull_symbol: "TQQQ"
    bond_signal: "TLT"
    bull_bond: "TMF"
    bear_bond: "TMV"

  trend_engine:
    equity_fast_sma: 40
    equity_slow_sma: 140
    bond_fast_sma: 20
    bond_slow_sma: 60
    kalman_model: "velocity_v3.5"

  volatility_engine:
    short_window: 21
    long_window: 126
    z_upper: 1.0
    z_lower: 0.2
    vol_crush_threshold: -0.15

  allocation:
    leverage_scalar: 1.0
    inverse_hedge: false
    safe_haven_active: true
    max_bond_weight: 0.40

# Execution Settings
execution:
  rebalance_threshold_pct: 5.0      # Don't trade if diff <5%
  max_slippage_pct: 0.5              # Configurable max slippage
  slippage_warning_pct: 0.3          # Warn if >0.3%
  slippage_abort_pct: 1.0            # Abort if >1.0%
  max_order_retries: 3
  retry_delay_seconds: 5
  max_buying_power_pct: 95           # Leave 5% buffer

# Timing (EST)
schedule:
  auth_check_time: "15:49:30"
  data_fetch_time: "15:50:00"
  execution_time: "15:55:00"
  validation_time: "16:15:00"

# Risk Limits
risk:
  max_position_size_pct: 100         # Per symbol (TQQQ can be 100%)
  max_total_leverage: 2.0            # Hard cap on total exposure
  min_cash_pct: 5.0                  # Always keep 5% cash

# State Management
state:
  file_path: "state/state.json"
  backup_enabled: true
  backup_path: "state/backups/"
  reconciliation_threshold_pct: 2.0  # Warn if state drift >2%

# Alerts
alerts:
  sms_enabled: true
  email_enabled: true
  critical_conditions:
    - "auth_failure"
    - "corporate_action_detected"
    - "slippage_exceeded"
    - "position_drift_high"

  # Contact info (populate with actual values)
  sms_number: "+1234567890"
  email_address: "trader@example.com"

# Schwab API
schwab:
  api_key: "${SCHWAB_API_KEY}"       # From environment variable
  api_secret: "${SCHWAB_API_SECRET}"
  redirect_uri: "https://localhost:8080"
  account_number: "${SCHWAB_ACCOUNT_NUMBER}"
  environment: "paper"               # paper or live

# Logging
logging:
  level: "INFO"                      # DEBUG, INFO, WARNING, ERROR
  file_path: "logs/live_trading_{date}.log"
  retention_days: 90
  format: "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

# Validation
validation:
  backtest_rerun_enabled: true
  price_drift_threshold_pct: 0.5     # Warn if 15:55 vs 16:00 >0.5%
  logic_match_threshold_pct: 95      # Require ≥95% logic match over 20 days
```

---

## Error Handling & Recovery

### Error Categories

#### 1. **CRITICAL (Abort Trading)**
```python
CRITICAL_ERRORS = {
    "AUTH_FAILURE": "OAuth token invalid and refresh failed",
    "DATA_TIMEOUT": "API call timeout >30 seconds",
    "CORPORATE_ACTION": "Split/dividend detected, manual review required",
    "STATE_CORRUPTION": "state.json corrupted and no API backup available",
    "ACCOUNT_MISMATCH": "Account equity differs >10% from expected",
    "EXTREME_SLIPPAGE": "Fill price >1.0% from expected"
}

# Action: Send SMS + Email, DO NOT TRADE, exit script
```

#### 2. **WARNING (Log & Continue)**
```python
WARNING_CONDITIONS = {
    "PARTIAL_FILL": "Order partially filled after 3 retries",
    "MODERATE_SLIPPAGE": "Slippage 0.5-1.0% (within tolerance)",
    "PRICE_DRIFT": "15:55 vs 16:00 drift 0.5-1.0%",
    "STATE_DRIFT": "Position drift 2-5% (reconciled from API)"
}

# Action: Log warning, send email (no SMS), continue trading
```

#### 3. **INFO (Normal Operation)**
```python
INFO_EVENTS = {
    "NO_REBALANCE": "All positions within 5% threshold, no trades",
    "MARKET_CLOSED": "Weekend/holiday detected, exiting gracefully",
    "DRY_RUN_MODE": "Dry-run active, no orders executed"
}

# Action: Log only, no alerts
```

### Recovery Strategies

**Scenario 1: Token Expires Mid-Execution**
```python
def execute_with_token_recovery(api_call, *args, **kwargs):
    try:
        return api_call(*args, **kwargs)
    except TokenExpiredError:
        logger.warning("Token expired, refreshing...")
        client.refresh_token()
        return api_call(*args, **kwargs)  # Retry once
    except Exception as e:
        raise CriticalFailure(f"API call failed: {e}")
```

**Scenario 2: State File Corrupted**
```python
def load_state_with_recovery():
    try:
        return load_state("state/state.json")
    except (JSONDecodeError, FileNotFoundError):
        logger.error("state.json corrupted, loading from API")
        api_positions = fetch_account_positions()

        # Rebuild state from API (source of truth)
        state = {
            "last_run": today(),
            "vol_state": 0,  # Reset hysteresis (conservative)
            "current_positions": api_positions
        }
        save_state(state)
        return state
```

**Scenario 3: Partial Fill**
```python
def handle_partial_fill(order_id, expected_qty):
    filled_qty = get_fill_quantity(order_id)
    remaining = expected_qty - filled_qty

    if remaining / expected_qty > 0.1:  # >10% unfilled
        logger.warning(f"Large partial fill: {remaining}/{expected_qty} unfilled")

        # Retry up to 3 times
        for attempt in range(3):
            new_order_id = submit_order(symbol, action, remaining)
            time.sleep(5)
            new_filled = get_fill_quantity(new_order_id)
            remaining -= new_filled
            if remaining == 0:
                return  # Fully filled

        # After 3 retries, accept partial fill
        send_warning_alert(f"Could not fill {remaining} shares, proceeding with partial")
```

---

## Testing Strategy

### Unit Tests

**Target Coverage:** >85%

```python
# tests/unit/live/test_data_fetcher.py
def test_synthetic_bar_creation():
    hist_df = load_fixture("historical_bars.csv")
    quote = Decimal("450.25")
    synthetic_df = create_synthetic_daily_bar(hist_df, quote)

    assert len(synthetic_df) == len(hist_df) + 1
    assert synthetic_df.iloc[-1]['close'] == quote

def test_corporate_action_detection():
    # Test split detection
    df_with_split = create_test_data_with_split()
    assert detect_corporate_actions(df_with_split) == False

    # Test normal data
    df_normal = create_test_data_normal()
    assert detect_corporate_actions(df_normal) == True

# tests/unit/live/test_position_rounder.py
def test_share_rounding():
    # $10,000 target, $100/share → 100 shares
    shares = PositionRounder.round_to_shares(10000, 100)
    assert shares == 100

    # $10,500 target, $100/share → 105 shares (round down from 105.0)
    shares = PositionRounder.round_to_shares(10500, 100)
    assert shares == 105

    # $10,050 target, $100/share → 100 shares (round down from 100.5)
    shares = PositionRounder.round_to_shares(10050, 100)
    assert shares == 100

# tests/unit/live/test_slippage_validator.py
def test_slippage_validation():
    validator = SlippageValidator(max_slippage_pct=0.5)

    # 0.2% slippage → OK
    assert validator.validate_fill("QQQ", 450.00, 450.90) == True

    # 0.6% slippage → WARNING (but allowed)
    assert validator.validate_fill("QQQ", 450.00, 452.70) == True

    # 1.5% slippage → CRITICAL (abort)
    with pytest.raises(CriticalFailure):
        validator.validate_fill("QQQ", 450.00, 456.75)
```

### Integration Tests

```python
# tests/integration/test_dry_run_workflow.py
@pytest.mark.integration
def test_full_dry_run_workflow(mock_schwab_client):
    """
    Simulate full 15:50-15:56 workflow:
    1. Mock API responses
    2. Run LiveTrader in dry-run mode
    3. Verify no actual orders submitted
    4. Verify state.json updated correctly
    """
    runner = LiveTrader(mode="dry_run", config=test_config)
    result = runner.execute_daily_cycle()

    assert result.status == "SUCCESS"
    assert len(result.hypothetical_orders) > 0
    assert mock_schwab_client.submit_order.call_count == 0  # No real orders

# tests/integration/test_paper_trading_workflow.py
@pytest.mark.integration
@pytest.mark.paper_account
def test_paper_trading_execution(live_schwab_client):
    """
    ONLY RUN IN PAPER ACCOUNT
    Execute real orders and validate fills
    """
    runner = LiveTrader(mode="paper", config=test_config)
    result = runner.execute_daily_cycle()

    assert result.status == "SUCCESS"
    assert all(fill.slippage_pct < 0.5 for fill in result.fills)
```

### Manual Testing Checklist

**Phase 0:**
- [ ] OAuth flow completes successfully
- [ ] Token refresh works after 30 minutes
- [ ] Market calendar correctly identifies weekends
- [ ] Cron job runs at exact scheduled time

**Phase 1 (Dry-Run):**
- [ ] Strategy logic matches backtest for same input data
- [ ] Hypothetical orders logged correctly
- [ ] 15:55 vs 16:00 price drift tracked
- [ ] State file saves/loads without corruption

**Phase 2 (Paper Trading):**
- [ ] Sell orders execute before buy orders
- [ ] Partial fills retry correctly
- [ ] Slippage within acceptable limits
- [ ] Position reconciliation detects manual trades
- [ ] Emergency kill switch closes all positions

**Phase 3 (Production Hardening):**
- [ ] SMS alerts received for critical errors
- [ ] Health monitor detects API downtime
- [ ] Recovery from corrupted state.json works
- [ ] Weekend token expiry handled correctly

---

## Validation Criteria

### Phase 1 Success Criteria (Dry-Run)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Uptime | 10 consecutive trading days | No errors in logs |
| Logic Match | ≥95% | Compare with backtest re-run |
| Price Drift | Average <0.3% | 15:55 vs 16:00 close |
| Max Price Drift | <0.88% | Worst-case divergence |
| State Integrity | 100% | No corrupted files |

**Exit Criteria:**
- ✅ All metrics above thresholds
- ✅ No critical errors logged
- ✅ Post-market validation reports all GREEN for ≥8/10 days

---

### Phase 2 Success Criteria (Paper Trading)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Uptime | 20 consecutive trading days | No critical failures |
| Fill Rate | ≥99% | Fills / Orders submitted |
| Average Slippage | <0.3% | Average |fill_price - quote_price| |
| Max Slippage | <0.5% | Configurable threshold |
| Logic Match | ≥98% | vs backtest |
| Position Drift | <2% | state.json vs API |

**Exit Criteria:**
- ✅ All metrics above thresholds
- ✅ No unrecoverable errors
- ✅ Paper account performance within 5% of backtest
- ✅ No manual interventions needed in last 10 days

---

## Risk Mitigation

### Pre-Flight Checks (Every Day at 15:49:30)

```python
def pre_flight_checks():
    """
    Run before any trading logic.
    If ANY check fails → ABORT and send critical alert
    """
    checks = [
        ("Market Open", is_trading_day()),
        ("OAuth Valid", validate_oauth_token()),
        ("API Connectivity", test_api_connection()),
        ("State File", validate_state_file()),
        ("Disk Space", check_disk_space_gb() > 1.0),
        ("Cron Schedule", verify_cron_schedule())
    ]

    for check_name, result in checks:
        if not result:
            send_critical_alert(f"PRE-FLIGHT FAILED: {check_name}")
            raise CriticalFailure(f"{check_name} check failed")
        logger.info(f"✅ {check_name}: PASS")
```

### Position Limits

```python
# Hard caps to prevent runaway leverage
POSITION_LIMITS = {
    "max_single_position_pct": 100,    # TQQQ can be 100% of account
    "max_total_leverage": 2.0,         # Total exposure cannot exceed 2x
    "min_cash_reserve_pct": 5.0        # Always keep 5% cash
}

def validate_target_allocation(target_weights, account_value):
    total_exposure = sum(target_weights.values()) * account_value
    leverage = total_exposure / account_value

    if leverage > POSITION_LIMITS["max_total_leverage"]:
        raise CriticalFailure(f"Leverage {leverage:.2f}x exceeds limit")

    if target_weights.get("CASH", 0) < POSITION_LIMITS["min_cash_reserve_pct"]:
        logger.warning("Cash reserve below minimum, adjusting...")
        # Reduce all positions proportionally to maintain 5% cash
```

### Disaster Recovery

**Daily Backups:**
```bash
# Cron job at 23:59 EST
0 23 * * * cp state/state.json state/backups/state_$(date +\%Y-\%m-\%d).json
0 23 * * * cp logs/live_trading_$(date +\%Y-\%m-\%d).log logs/archive/
```

**Emergency Procedures:**

1. **Total System Failure → Manual Exit**
   ```bash
   python scripts/emergency_exit.py
   # Closes all positions, moves to cash, disables cron
   ```

2. **Partial Failure → Skip Day**
   - If any pre-flight check fails, do NOT trade
   - Keep current positions unchanged
   - Better to miss one day than execute wrong trades

3. **Data Integrity Issue → Validate from Multiple Sources**
   ```python
   # Cross-check prices from multiple endpoints
   quote_1 = fetch_quote_stream("QQQ")
   quote_2 = fetch_quote_realtime("QQQ")

   if abs(quote_1 - quote_2) / quote_1 > 0.01:  # >1% divergence
       raise DataIntegrityError("Quote mismatch across APIs")
   ```

---

## Deployment Checklist

### Pre-Deployment (Before Phase 0)

- [ ] Schwab Developer account created
- [ ] API credentials stored in `.env` (not hardcoded)
- [ ] OAuth redirect URI configured
- [ ] Cron daemon installed and tested
- [ ] Timezone set to EST (or handle conversion)
- [ ] SMS/Email alert credentials configured
- [ ] Backup strategy implemented (daily state backups)

### Phase 0 Go-Live

- [ ] `hello_schwab.py` runs successfully
- [ ] Token refresh tested manually
- [ ] Cron job scheduled for 15:49 EST
- [ ] Test on Friday, verify no Saturday execution

### Phase 1 Go-Live (Dry-Run)

- [ ] `live_trader.py` configured for dry_run mode
- [ ] Post-market validation script scheduled for 16:15
- [ ] Daily email reports working
- [ ] Backtest comparison logic validated
- [ ] State file directory created with write permissions

### Phase 2 Go-Live (Paper Trading)

- [ ] Paper money account funded ($10,000+ recommended)
- [ ] Mode switched to `paper` in config
- [ ] Emergency kill switch tested
- [ ] SMS alerts tested with dummy error
- [ ] Health monitor cron job running (every 6 hours)
- [ ] Manual override procedure documented

### Phase 3 Go-Live (Production)

**NOT APPLICABLE YET - Paper trading validation first**

---

## Maintenance & Monitoring

### Daily Monitoring (Automated)

**15:56 - Immediate Post-Execution Report (Email)**
```
Subject: [LIVE TRADING] Daily Execution Report - 2025-11-23

Status: ✅ SUCCESS
Mode: Paper Trading
Execution Time: 15:55:03 EST

Orders Executed:
- SELL 50 TQQQ @ $45.12 (Target: $45.10, Slippage: 0.04%)
- BUY 30 TMF @ $65.80 (Target: $65.75, Slippage: 0.08%)

Allocation:
- TQQQ: 45% ($22,500)
- TMF: 30% ($15,000)
- Cash: 25% ($12,500)

Validation:
- Logic Match: ✅ Matches backtest
- Slippage: ✅ 0.06% avg (threshold: 0.5%)
- Position Drift: ✅ 0.1% (threshold: 2%)

Logs: logs/live_trading_2025-11-23.log
```

**16:15 - Post-Market Validation Report (Email)**
```
Subject: [VALIDATION] 15:55 vs 16:00 Analysis - 2025-11-23

Price Divergence:
- QQQ: 15:55=$450.12, 16:00=$450.35 (0.05%) ✅
- TLT: 15:55=$92.80, 16:00=$92.75 (0.05%) ✅

Logic Comparison:
- 15:55 Decision: Cell 3 (Bullish Equity)
- 16:00 Backtest: Cell 3 (Bullish Equity)
- Match: ✅ 100%

Rolling Stats (Last 20 Days):
- Logic Match: 19/20 (95%) ✅
- Avg Price Drift: 0.18% ✅
- Avg Slippage: 0.24% ✅

Status: GREEN - All metrics within targets
```

### Weekly Review (Manual)

**Every Sunday Evening:**
1. Review cumulative performance (paper account vs backtest)
2. Check for recurring warnings (e.g., slippage patterns)
3. Analyze any logic mismatches
4. Review error logs for anomalies
5. Validate health monitor hasn't missed issues

**Review Template:**
```markdown
## Weekly Review - Week of YYYY-MM-DD

### Performance
- Paper Account Return: +X.XX%
- Backtest Return (same period): +X.XX%
- Tracking Error: X.XX%

### Execution Quality
- Avg Slippage: X.XX%
- Fill Rate: XX/XX (100%)
- Logic Match: XX/XX (XX%)

### Issues
- [List any warnings, errors, or anomalies]

### Action Items
- [Any config changes, code fixes, or investigations needed]

### Go/No-Go for Next Week
- [ ] Continue paper trading
- [ ] Needs attention before continuing
```

### Monthly Audit

1. **Performance Attribution**
   - Compare live performance vs backtest
   - Decompose tracking error (slippage, timing, logic drift)

2. **Code Review**
   - Review any emergency patches
   - Update dependencies (schwab-py, etc.)

3. **Configuration Drift**
   - Verify live config matches "Titan" spec
   - Check for parameter creep

4. **Security Audit**
   - Rotate API keys (if applicable)
   - Review access logs
   - Test emergency procedures

---

## Appendix A: Code Snippets

### Main Entry Point: `scripts/live_trader.py`

```python
#!/usr/bin/env python3
"""
Live Trading System - Main Entry Point
Scheduled via cron: 0 15 * * 1-5 (15:00 EST, Mon-Fri)
"""

import sys
from pathlib import Path
from jutsu_engine.live.data_fetcher import LiveDataFetcher
from jutsu_engine.live.strategy_runner import LiveStrategyRunner
from jutsu_engine.live.order_executor import OrderExecutor
from jutsu_engine.live.state_manager import StateManager
from jutsu_engine.live.alert_manager import AlertManager
from jutsu_engine.utils.config import load_config
from jutsu_engine.utils.logging_config import get_logger

logger = get_logger('LIVE.TRADER')

def main():
    """Main execution loop"""
    try:
        # 1. Load configuration
        config = load_config("config/live_config.yaml")
        logger.info(f"Starting live trader - Mode: {config['environment']}")

        # 2. Pre-flight checks
        pre_flight_checks(config)

        # 3. Check if trading day
        if not is_trading_day():
            logger.info("Not a trading day - exiting")
            return

        # 4. Initialize components
        data_fetcher = LiveDataFetcher(config)
        strategy_runner = LiveStrategyRunner(config)
        state_manager = StateManager(config)
        alert_manager = AlertManager(config)

        # 5. Fetch market data
        logger.info("Fetching market data...")
        market_data = data_fetcher.fetch_all_data()

        # 6. Validate data integrity
        data_fetcher.validate_corporate_actions(market_data)

        # 7. Run strategy logic
        logger.info("Calculating target allocation...")
        target_allocation = strategy_runner.calculate_target_allocation(market_data)

        # 8. Load state and reconcile positions
        state = state_manager.load_and_reconcile()

        # 9. Calculate rebalance requirements
        orders = calculate_rebalance_orders(target_allocation, state, config)

        # 10. Execute orders (or dry-run)
        if config['environment'] == 'dry_run':
            logger.info("[DRY RUN] Hypothetical orders:")
            for order in orders:
                logger.info(f"  {order}")
        else:
            executor = OrderExecutor(config)
            fills = executor.execute_rebalance(orders)

            # 11. Validate fills
            for fill in fills:
                validate_slippage(fill, config)

            # 12. Update state
            state_manager.update_state(fills)

        logger.info("✅ Daily trading cycle complete")

    except CriticalFailure as e:
        logger.critical(f"CRITICAL FAILURE: {e}")
        alert_manager.send_critical_alert(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        alert_manager.send_email(f"Live Trading Error", str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
```

---

## Appendix B: Cron Schedule

```bash
# /etc/crontab or crontab -e

# Set timezone
CRON_TZ=America/New_York

# Live trading execution (15:50 EST, Mon-Fri)
50 15 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python scripts/live_trader.py >> logs/cron.log 2>&1

# Post-market validation (16:15 EST, Mon-Fri)
15 16 * * 1-5 cd /path/to/jutsu-labs && /path/to/venv/bin/python scripts/post_market_validation.py >> logs/cron.log 2>&1

# Daily state backup (23:59 EST, every day)
59 23 * * * cp /path/to/jutsu-labs/state/state.json /path/to/jutsu-labs/state/backups/state_$(date +\%Y-\%m-\%d).json

# Health check (every 6 hours)
0 */6 * * * cd /path/to/jutsu-labs && /path/to/venv/bin/python scripts/health_check.py >> logs/health.log 2>&1
```

---

## Appendix C: Environment Variables

```bash
# .env file (DO NOT COMMIT TO GIT)

# Schwab API Credentials
SCHWAB_API_KEY=your_api_key_here
SCHWAB_API_SECRET=your_api_secret_here
SCHWAB_ACCOUNT_NUMBER=12345678
SCHWAB_REDIRECT_URI=https://localhost:8080

# Alert Credentials
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_FROM_NUMBER=+1234567890
ALERT_SMS_NUMBER=+1234567890
ALERT_EMAIL=trader@example.com
SENDGRID_API_KEY=your_sendgrid_key

# Environment
ENV=paper  # Options: dry_run, paper, live
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-23 | Initial | Complete implementation plan created |

---

## Next Steps

1. **Review and Approve Plan** → Stakeholder signoff
2. **Phase 0 Kickoff** → Create Schwab Developer App
3. **Setup Development Environment** → Install dependencies, configure .env
4. **Begin Module Development** → Start with `LiveDataFetcher`
5. **Weekly Progress Reviews** → Track against timeline

---

**Document Status:** ✅ Ready for Review
**Estimated Total Timeline:** 8-10 weeks (Phase 0-3)
**Risk Level:** Medium (Paper trading reduces risk significantly)
**Go-Live Readiness:** Pending Phase 2 completion and validation
