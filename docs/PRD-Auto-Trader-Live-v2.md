# Product Requirements Document: Jutsu Labs Live Trader v2.0

**Version:** 2.0
**Status:** Draft
**Strategy:** Hierarchical Adaptive v3.5b (Golden Config)
**Platform:** Schwab-py + Local Database + Web Dashboard
**Last Updated:** December 3, 2025

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Trading Modes](#3-trading-modes)
4. [Strategy Configuration](#4-strategy-configuration)
5. [Execution Time Options](#5-execution-time-options)
6. [Dashboard Requirements](#6-dashboard-requirements)
7. [Data Architecture](#7-data-architecture)
8. [Functional Requirements](#8-functional-requirements)
9. [Implementation Phases](#9-implementation-phases)
10. [Success Criteria](#10-success-criteria)

---

## 1. Executive Summary

### 1.1 Objective

Build a production-grade live trading system for the **Hierarchical Adaptive v3.5b** strategy with:

- **Dual-mode operation**: Offline mock trading + Online live trading
- **Flexible execution timing**: Multiple execution windows throughout the trading day
- **Parameter injection**: Runtime configuration without code changes
- **Web dashboard**: Real-time monitoring, control, and analysis
- **Local tracking**: All trades recorded locally for independent analysis

### 1.2 Key Changes from v1.0

| Feature | v1.0 PRD | v2.0 PRD |
|---------|----------|----------|
| Trading Mode | Paper Money (Schwab) | Offline Mock + Online Live |
| Execution Time | Fixed 15:55 EST | Configurable (4 options) |
| Configuration | Static YAML | YAML + Dashboard Overrides |
| Monitoring | Log files | Web Dashboard |
| Trade Storage | CSV only | Local SQLite Database |
| Strategy | Titan Config | Golden Config (optimized) |

### 1.3 Critical Constraint

**Schwab API does NOT support paper trading.** Therefore:
- **Offline Mode** = Mock execution with real market data, local tracking only
- **Online Mode** = Real order execution via Schwab API + local tracking

---

## 2. System Overview

### 2.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     JUTSU LABS LIVE TRADER v2.0                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │     WEB DASHBOARD (React)     │
                    │  ─────────────────────────────│
                    │  • Mode Toggle (Offline/Live) │
                    │  • Execution Time Selector    │
                    │  • Strategy Parameter Editor  │
                    │  • Live Indicator Display     │
                    │  • Portfolio Allocation View  │
                    │  • Trade History Table        │
                    │  • Performance Metrics        │
                    │  • Market Regime Display      │
                    └───────────────┬───────────────┘
                                    │ REST + WebSocket
                    ┌───────────────▼───────────────┐
                    │     FASTAPI BACKEND           │
                    │  ─────────────────────────────│
                    │  • Config Management API      │
                    │  • Status & Metrics API       │
                    │  • Trade History API          │
                    │  • Control API (start/stop)   │
                    │  • WebSocket (live updates)   │
                    └───────────────┬───────────────┘
                                    │
┌───────────────────────────────────┴───────────────────────────────────┐
│                          CORE TRADING ENGINE                          │
├───────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌──────────────────────────────────────┐ │
│  │  SCHEDULER          │    │  STRATEGY RUNNER                      │ │
│  │  ─────────────────  │    │  ──────────────────────────────────  │ │
│  │  • APScheduler      │───▶│  • Hierarchical_Adaptive_v3_5b       │ │
│  │  • Multi-window     │    │  • Runtime parameter injection       │ │
│  │  • Market calendar  │    │  • Signal generation                 │ │
│  └─────────────────────┘    └──────────────┬───────────────────────┘ │
│                                             │                         │
│  ┌──────────────────────────────────────────▼────────────────────┐   │
│  │                     EXECUTION ROUTER                           │   │
│  │                  MODE: [OFFLINE] / [ONLINE]                    │   │
│  └─────────┬───────────────────────────────────────┬─────────────┘   │
│            │                                       │                 │
│  ┌─────────▼─────────┐                  ┌──────────▼──────────┐     │
│  │  MOCK EXECUTOR    │                  │  SCHWAB EXECUTOR    │     │
│  │  • Simulates fills│                  │  • Real API orders  │     │
│  │  • Uses mid price │                  │  • Fill verification│     │
│  │  • No real orders │                  │  • Slippage tracking│     │
│  └─────────┬─────────┘                  └──────────┬──────────┘     │
│            │                                       │                 │
│            └────────────────────┬──────────────────┘                 │
│                    ┌────────────▼────────────┐                       │
│                    │    LOCAL DATABASE       │                       │
│                    │  • live_trades          │                       │
│                    │  • positions            │                       │
│                    │  • config_history       │                       │
│                    │  • performance_snapshots│                       │
│                    └─────────────────────────┘                       │
└───────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │      SCHWAB API               │
                    │  • Market Data (quotes/bars)  │
                    │  • Account Information        │
                    │  • Order Execution (online)   │
                    └───────────────────────────────┘
```

### 2.2 Component Summary

| Component | Technology | Purpose |
|-----------|------------|---------|
| Dashboard Frontend | React + shadcn/ui | User interface for monitoring/control |
| Dashboard Backend | FastAPI | REST API + WebSocket server |
| Trading Engine | Python | Strategy execution, order routing |
| Scheduler | APScheduler | Time-based execution triggers |
| Database | SQLite → PostgreSQL | Trade/config/performance storage |
| Schwab Integration | schwab-py | Market data + order execution |

---

## 3. Trading Modes

### 3.1 Mode Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MODE SELECTION                            │
│                                                                  │
│    ┌─────────────────────┐    ┌─────────────────────────────┐   │
│    │   OFFLINE MODE      │    │      ONLINE MODE            │   │
│    │   (Mock Trading)    │    │      (Live Trading)         │   │
│    └──────────┬──────────┘    └──────────────┬──────────────┘   │
│               │                              │                   │
│    ┌──────────▼──────────┐    ┌──────────────▼──────────────┐   │
│    │ • Real market data  │    │ • Real market data          │   │
│    │ • Simulated fills   │    │ • Real order execution      │   │
│    │ • No Schwab orders  │    │ • Schwab order API          │   │
│    │ • Local DB tracking │    │ • Local DB + Schwab records │   │
│    │ • Safe for testing  │    │ • Real money at risk        │   │
│    └─────────────────────┘    └─────────────────────────────┘   │
│                                                                  │
│    Both modes use SAME strategy logic and local database        │
│    Mode is recorded with each trade for audit purposes          │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Offline Mode (Mock Trading)

**Purpose**: Validate strategy behavior without financial risk.

**Characteristics**:
- Uses real Schwab API for market data (quotes, historical bars)
- Does NOT place any orders via Schwab API
- Simulates fills at current market price (mid-point)
- Records all trades to local database with `mode='offline_mock'`
- Calculates hypothetical portfolio value and returns

**Use Cases**:
- Initial strategy validation before going live
- Testing new parameter configurations
- Comparing strategy behavior vs backtest
- Training and learning the system

**CLI Command**:
```bash
jutsu live --mode offline --execution-time 15:55
```

### 3.3 Online Mode (Live Trading)

**Purpose**: Execute real trades via Schwab brokerage account.

**Characteristics**:
- Uses Schwab API for market data AND order execution
- Places real MARKET orders via Schwab API
- Verifies fills and tracks slippage
- Records all trades to local database with `mode='online_live'`
- Includes Schwab order ID for reconciliation

**Safety Requirements**:
- Explicit confirmation required before first trade
- Kill switch accessible via dashboard
- Maximum position size limits enforced
- Slippage abort threshold (>1% = cancel)

**CLI Command**:
```bash
jutsu live --mode online --execution-time 15:55 --confirm
```

### 3.4 Local Trade Database

**Rationale**: Track all trades locally regardless of mode.

**Benefits**:
1. **Independence**: Not dependent on Schwab's data retention policies
2. **Analysis**: Strategy context (cell, vol_state, indicators) captured
3. **Comparison**: Easy comparison between mock and live performance
4. **Audit**: Complete audit trail with mode flags
5. **Custom Metrics**: Calculate any metric not provided by Schwab

**Trade Record Schema**:
```python
class LiveTrade(Base):
    __tablename__ = 'live_trades'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    # Trade details
    symbol = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)  # BUY, SELL
    quantity = Column(Integer, nullable=False)
    target_price = Column(Numeric(18, 6))  # Price at signal generation
    fill_price = Column(Numeric(18, 6))    # Actual fill price
    slippage_pct = Column(Numeric(8, 4))   # (fill - target) / target

    # Mode tracking
    mode = Column(String(20), nullable=False)  # 'offline_mock', 'online_live'
    schwab_order_id = Column(String(50))       # Null for mock trades

    # Strategy context
    strategy_cell = Column(Integer)            # 1-6
    trend_state = Column(String(20))           # BullStrong, Sideways, BearStrong
    vol_state = Column(String(10))             # Low, High
    t_norm = Column(Numeric(8, 4))             # Kalman trend value
    z_score = Column(Numeric(8, 4))            # Volatility z-score

    # Metadata
    execution_time_setting = Column(String(30))  # open, 15min_after_open, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
```

---

## 4. Strategy Configuration

### 4.1 Golden Config (Hierarchical Adaptive v3.5b)

The system uses the optimized "Golden Config" parameters from grid-search:

```yaml
strategy:
  name: "Hierarchical_Adaptive_v3_5b"

  # Trading Universe
  universe:
    signal_symbol: "QQQ"
    leveraged_long_symbol: "TQQQ"
    core_long_symbol: "QQQ"
    inverse_hedge_symbol: "PSQ"
    treasury_trend_symbol: "TLT"
    bull_bond_symbol: "TMF"
    bear_bond_symbol: "TMV"

  # Kalman Trend Parameters
  kalman:
    measurement_noise: 3000.0
    process_noise_1: 0.01
    process_noise_2: 0.01
    osc_smoothness: 15
    strength_smoothness: 15
    T_max: 50.0

  # SMA Structure Parameters
  sma:
    fast: 40
    slow: 140
    t_norm_bull_thresh: 0.20
    t_norm_bear_thresh: -0.30

  # Volatility Z-Score Parameters
  volatility:
    realized_vol_window: 21
    vol_baseline_window: 126
    upper_thresh_z: 1.0
    lower_thresh_z: 0.2
    vol_crush_threshold: -0.15
    vol_crush_lookback: 5

  # Allocation Parameters
  allocation:
    leverage_scalar: 1.0
    use_inverse_hedge: false
    max_bond_weight: 0.40
    rebalance_threshold: 0.025

  # Treasury Overlay
  treasury:
    enabled: true
    bond_sma_fast: 20
    bond_sma_slow: 60
```

### 4.2 Parameter Injection System

**Priority Order** (highest to lowest):
1. **Dashboard Override**: Runtime changes via web UI (stored in DB)
2. **YAML Config File**: Persistent configuration (`live_trading_config.yaml`)
3. **Strategy Defaults**: Hardcoded in strategy class

**Parameter Change Workflow**:
```
User changes parameter in Dashboard
        │
        ▼
Dashboard saves to config_overrides table
        │
        ▼
Next execution cycle reads:
  1. Check DB for overrides
  2. Merge with YAML config
  3. Inject into strategy
        │
        ▼
Strategy runs with updated parameters
        │
        ▼
Trade record includes parameter snapshot
```

**Config Override Schema**:
```python
class ConfigOverride(Base):
    __tablename__ = 'config_overrides'

    id = Column(Integer, primary_key=True)
    parameter_path = Column(String(100))  # e.g., "sma.fast"
    override_value = Column(String(100))  # JSON encoded
    effective_from = Column(DateTime(timezone=True))
    effective_until = Column(DateTime(timezone=True))  # Null = permanent
    created_by = Column(String(50))  # "dashboard", "cli"
    created_at = Column(DateTime, default=datetime.utcnow)
```

### 4.3 Parameter Validation

All parameter changes must pass validation:

```python
PARAMETER_CONSTRAINTS = {
    "sma.fast": {"type": int, "min": 10, "max": 100},
    "sma.slow": {"type": int, "min": 50, "max": 300},
    "volatility.upper_thresh_z": {"type": float, "min": 0.5, "max": 2.0},
    "volatility.lower_thresh_z": {"type": float, "min": -0.5, "max": 0.5},
    "allocation.leverage_scalar": {"type": float, "min": 0.5, "max": 1.5},
    # ... etc
}

def validate_parameter_change(path: str, value: Any) -> bool:
    """Validate parameter change against constraints."""
    constraint = PARAMETER_CONSTRAINTS.get(path)
    if not constraint:
        return False
    if not isinstance(value, constraint["type"]):
        return False
    if value < constraint["min"] or value > constraint["max"]:
        return False
    return True
```

---

## 5. Execution Time Options

### 5.1 Available Execution Windows

```python
EXECUTION_WINDOWS = {
    "open": {
        "time": "09:30",
        "description": "Market Open",
        "characteristics": "Captures overnight gaps, higher volatility",
        "risk": "High slippage, wide spreads"
    },
    "15min_after_open": {
        "time": "09:45",
        "description": "15 minutes after open",
        "characteristics": "Opening volatility settled, spreads narrowing",
        "risk": "Moderate slippage"
    },
    "15min_before_close": {
        "time": "15:45",
        "description": "15 minutes before close",
        "characteristics": "Stable prices, good liquidity",
        "risk": "Low slippage"
    },
    "5min_before_close": {
        "time": "15:55",
        "description": "5 minutes before close (MOC proxy)",
        "characteristics": "Very close to EOD, matches backtest",
        "risk": "Low slippage, time pressure"
    }
}
```

### 5.2 Execution Time Selection

**Configuration Methods**:
1. **YAML Config**: Default execution time
2. **CLI Flag**: Override for single run
3. **Dashboard**: Change via UI

**Example YAML**:
```yaml
execution:
  default_time: "5min_before_close"

  # Future: Multiple execution windows per day
  # windows:
  #   - "open"
  #   - "5min_before_close"
```

### 5.3 Signal vs Fill Timing

**Important Distinction**:
- **Signal Generation**: ALWAYS uses EOD bar data for consistency
- **Fill Pricing**: Uses intraday price at execution_time

**Why This Matters**:
```
Backtest: Uses EOD close prices → signals based on EOD
Live (close): Uses EOD-like price → matches backtest
Live (open): Uses opening price → different fill, same signal
```

This separation ensures signal logic is consistent while allowing flexible execution timing.

---

## 6. Dashboard Requirements

### 6.1 Dashboard Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    JUTSU LABS DASHBOARD                          │
├─────────────────────────────────────────────────────────────────┤
│  HEADER: Status Bar | Mode Indicator | Last Update Time         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐ │
│  │  CONTROL PANEL  │  │    MARKET REGIME DISPLAY              │ │
│  │  ─────────────  │  │    ──────────────────────────────────│ │
│  │  Mode: [▼ OFF ] │  │    Cell: 1 (Kill Zone)               │ │
│  │  Time: [▼ 3:55]│  │    Trend: BullStrong                 │ │
│  │  ──────────────│  │    Vol State: Low (z=0.45)           │ │
│  │  [▶ START]     │  │    Bond Trend: Bull → TMF            │ │
│  │  [⏹ STOP]      │  │    ──────────────────────────────────│ │
│  │  [⚙ CONFIG]    │  │    Next Execution: 15:55 EST         │ │
│  └─────────────────┘  └──────────────────────────────────────┘ │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                LIVE INDICATOR PANEL                       │  │
│  │  ────────────────────────────────────────────────────────│  │
│  │                                                          │  │
│  │  Kalman T_norm    ████████░░░░░░  0.35                   │  │
│  │                   Bear ◄──────────────────► Bull         │  │
│  │                         -0.3    0    0.2                 │  │
│  │                                                          │  │
│  │  SMA Structure    Fast: 525.43  |  Slow: 498.22          │  │
│  │                   [BULL STRUCTURE - Fast > Slow]         │  │
│  │                                                          │  │
│  │  Volatility Z     ██░░░░░░░░░░░░  0.45                   │  │
│  │                   Low ◄────────────────────► High        │  │
│  │                        0.2           1.0                 │  │
│  │                                                          │  │
│  │  Bond Trend       SMA20: 92.15  |  SMA60: 89.44          │  │
│  │                   [BULL BONDS - Deflation Hedge → TMF]   │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────┐  ┌───────────────────────────────┐ │
│  │  PORTFOLIO ALLOCATION  │  │  PERFORMANCE METRICS          │ │
│  │  ────────────────────  │  │  ─────────────────────────── │ │
│  │                        │  │                               │ │
│  │  TQQQ  ████████░░ 60%  │  │  Total Return:    +18.52%    │ │
│  │        $15,558         │  │  Annualized:      +24.16%    │ │
│  │                        │  │  Sharpe Ratio:    2.31       │ │
│  │  QQQ   █████░░░░░ 40%  │  │  Max Drawdown:    -8.24%     │ │
│  │        $10,372         │  │  Win Rate:        67%        │ │
│  │                        │  │  Total Trades:    32         │ │
│  │  Cash  $930 (3.6%)     │  │                               │ │
│  │  ────────────────────  │  │  YTD Return:      +18.52%    │ │
│  │  Total: $25,930        │  │  MTD Return:      +3.21%     │ │
│  │                        │  │  WTD Return:      +0.89%     │ │
│  └────────────────────────┘  └───────────────────────────────┘ │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   TRADE HISTORY                           │  │
│  │  ────────────────────────────────────────────────────────│  │
│  │  Date       Time   Symbol  Action  Qty    Price    Mode  │  │
│  │  ──────────────────────────────────────────────────────  │  │
│  │  2025-12-03 15:55  TQQQ    BUY     10    $89.45   MOCK  │  │
│  │  2025-12-03 15:55  TMF     SELL    25    $51.20   MOCK  │  │
│  │  2025-12-02 15:55  TMF     BUY     25    $50.80   MOCK  │  │
│  │  2025-12-01 15:55  QQQ     SELL    15    $525.30  MOCK  │  │
│  │  2025-11-29 15:55  TQQQ    BUY     8     $88.12   MOCK  │  │
│  │  ────────────────────────────────────────────────────────│  │
│  │  [Show More] [Export CSV] [Filter: All/Mock/Live]        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Feature Priority Matrix

| Priority | Feature | Description | Complexity |
|----------|---------|-------------|------------|
| **P0** | Mode Toggle | Switch between Offline/Online | Low |
| **P0** | Regime Display | Current cell, trend, vol state | Low |
| **P0** | Portfolio View | Current allocation and values | Low |
| **P0** | Trade History | Table of recent trades | Medium |
| **P1** | Indicator Panel | Live indicator visualizations | Medium |
| **P1** | Execution Time | Change execution time | Low |
| **P1** | Performance Metrics | Returns, Sharpe, drawdown | Medium |
| **P2** | Parameter Editor | Modify strategy parameters | High |
| **P2** | Real-time Updates | WebSocket live refresh | High |
| **P3** | Charts | Equity curve, regime timeline | High |
| **P3** | Alert Config | SMS/Email notification setup | Medium |

### 6.3 API Endpoints

```yaml
# REST Endpoints
GET  /api/status           # Current system status, regime, portfolio
GET  /api/config           # Current configuration
PUT  /api/config           # Update configuration
GET  /api/trades           # Trade history (paginated)
GET  /api/trades/export    # Export trades as CSV
GET  /api/performance      # Performance metrics
POST /api/control/start    # Start trading engine
POST /api/control/stop     # Stop trading engine
GET  /api/indicators       # Current indicator values

# WebSocket
WS   /ws/live              # Real-time updates (status, indicators, trades)
```

### 6.4 Technology Stack

**Frontend**:
- Framework: React 18+
- UI Components: shadcn/ui (Tailwind-based)
- State Management: React Query + Zustand
- Charts: Lightweight-charts (TradingView) or Recharts
- Real-time: Socket.io client

**Backend**:
- Framework: FastAPI
- WebSocket: FastAPI WebSocket
- Database: SQLAlchemy (SQLite dev, PostgreSQL prod)
- Scheduler: APScheduler
- Validation: Pydantic

---

## 7. Data Architecture

### 7.1 Database Schema

```sql
-- Core trading tables
CREATE TABLE live_trades (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    target_price DECIMAL(18,6),
    fill_price DECIMAL(18,6),
    slippage_pct DECIMAL(8,4),
    mode VARCHAR(20) NOT NULL,
    schwab_order_id VARCHAR(50),
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    t_norm DECIMAL(8,4),
    z_score DECIMAL(8,4),
    execution_time_setting VARCHAR(30),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    avg_cost DECIMAL(18,6),
    current_value DECIMAL(18,6),
    mode VARCHAR(20) NOT NULL,
    last_updated DATETIME,
    UNIQUE(symbol, mode)
);

CREATE TABLE performance_snapshots (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    mode VARCHAR(20) NOT NULL,
    total_equity DECIMAL(18,6),
    daily_return DECIMAL(8,4),
    cumulative_return DECIMAL(8,4),
    drawdown DECIMAL(8,4),
    strategy_cell INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Configuration tables
CREATE TABLE config_overrides (
    id INTEGER PRIMARY KEY,
    parameter_path VARCHAR(100) NOT NULL,
    override_value TEXT NOT NULL,
    effective_from DATETIME,
    effective_until DATETIME,
    created_by VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE config_history (
    id INTEGER PRIMARY KEY,
    config_snapshot TEXT NOT NULL,
    changed_by VARCHAR(50),
    change_reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- System tables
CREATE TABLE system_state (
    id INTEGER PRIMARY KEY,
    key VARCHAR(50) UNIQUE NOT NULL,
    value TEXT,
    updated_at DATETIME
);
```

### 7.2 State Management

**State File** (`state/state.json`):
```json
{
    "last_run": "2025-12-03T15:56:00Z",
    "vol_state": "Low",
    "current_positions": {
        "TQQQ": 150,
        "QQQ": 20
    },
    "account_equity": 25930.67,
    "last_cell": 1,
    "last_allocation": {
        "TQQQ": 0.60,
        "QQQ": 0.40
    },
    "mode": "offline_mock",
    "execution_time": "5min_before_close"
}
```

---

## 8. Functional Requirements

### FR-1: Mode Switching

**Requirement**: System must support instant switching between offline and online modes.

**Acceptance Criteria**:
- [ ] Mode can be changed via CLI, dashboard, or config file
- [ ] Mode change takes effect on next execution cycle
- [ ] Mode is recorded with every trade
- [ ] Online mode requires explicit confirmation on first use

### FR-2: Execution Time Configuration

**Requirement**: System must support multiple execution time options.

**Acceptance Criteria**:
- [ ] Four execution times available: open, 15min_after_open, 15min_before_close, 5min_before_close
- [ ] Execution time can be changed via dashboard
- [ ] Scheduler adjusts to selected execution time
- [ ] Signal generation uses EOD data regardless of execution time

### FR-3: Parameter Injection

**Requirement**: Strategy parameters must be configurable without code changes.

**Acceptance Criteria**:
- [ ] Parameters loaded from YAML config at startup
- [ ] Dashboard can override parameters at runtime
- [ ] Parameter changes are validated against constraints
- [ ] Parameter history is preserved for audit

### FR-4: Local Trade Database

**Requirement**: All trades must be recorded locally regardless of mode.

**Acceptance Criteria**:
- [ ] Every trade (mock or live) written to local database
- [ ] Strategy context (cell, vol_state, indicators) captured
- [ ] Mode flag clearly distinguishes mock vs live trades
- [ ] Trade data exportable to CSV

### FR-5: Dashboard Monitoring

**Requirement**: Web dashboard must provide real-time monitoring.

**Acceptance Criteria**:
- [ ] Current regime (cell, trend, vol) displayed
- [ ] Portfolio allocation shown with percentages and values
- [ ] Trade history accessible with filtering
- [ ] Performance metrics calculated and displayed

### FR-6: Safety Controls

**Requirement**: System must include safety mechanisms for online mode.

**Acceptance Criteria**:
- [ ] Kill switch accessible via dashboard
- [ ] Maximum position size limits enforced
- [ ] Slippage threshold triggers abort (>1%)
- [ ] Online mode requires confirmation before first trade

---

## 9. Implementation Phases

### Phase 0: Foundation Enhancement (Week 1-2)

**Objectives**:
- Add 5min_before_close execution time option
- Create LiveTrade database model
- Refactor to unified executor interface
- Add mode flag to all components

**Deliverables**:
- [ ] Updated strategy with `5min_before_close` option
- [ ] Database migration for live_trades table
- [ ] MockOrderExecutor class
- [ ] Mode enum and validation

### Phase 1: Offline Mock Trading (Week 3-4)

**Objectives**:
- Complete offline trading workflow
- Full local database tracking
- CLI interface for running offline mode

**Deliverables**:
- [ ] `jutsu live --mode offline` command
- [ ] Mock execution with simulated fills
- [ ] Strategy context logging
- [ ] Daily performance snapshots

### Phase 2: Online Live Trading (Week 5-6)

**Objectives**:
- Real Schwab order execution
- Fill verification and slippage tracking
- Safety confirmation workflow

**Deliverables**:
- [ ] SchwabOrderExecutor class
- [ ] `jutsu live --mode online --confirm` command
- [ ] Fill reconciliation logic
- [ ] Slippage abort mechanism

### Phase 3: Dashboard MVP (Week 7-10)

**Objectives**:
- FastAPI backend with core endpoints
- React frontend with essential views
- Mode toggle and basic monitoring

**Deliverables**:
- [ ] FastAPI server with REST endpoints
- [ ] React dashboard with P0 features
- [ ] Mode toggle functionality
- [ ] Trade history view

### Phase 4: Dashboard Advanced (Week 11-14)

**Objectives**:
- Parameter editor with validation
- Real-time WebSocket updates
- Performance charts

**Deliverables**:
- [ ] Parameter editor UI
- [ ] WebSocket live updates
- [ ] Equity curve chart
- [ ] Execution time selector

### Phase 5: Production Hardening (Week 15+)

**Objectives**:
- Health monitoring
- Alert system
- Automated recovery

**Deliverables**:
- [ ] Health check endpoints
- [ ] SMS/Email alerts
- [ ] Crash recovery logic
- [ ] System documentation

---

## 10. Success Criteria

### 10.1 Offline Mode Validation

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Uptime | 20 consecutive days | No crashes or missed executions |
| Logic Match | 100% | Mock decisions match backtest rerun |
| Database Integrity | 100% | All trades recorded with complete context |
| Performance Tracking | Accurate | Mock returns match manual calculation |

### 10.2 Online Mode Validation

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Fill Rate | 100% | All orders filled successfully |
| Slippage | <0.5% average | (fill - target) / target |
| Reconciliation | Match | Local records match Schwab account |
| Safety | No incidents | Kill switch never needed |

### 10.3 Dashboard Validation

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Availability | 99.9% | Dashboard accessible during market hours |
| Latency | <1s | Data refresh within 1 second |
| Accuracy | 100% | All displayed data matches database |
| Usability | Positive | User can complete all workflows |

---

## Appendix A: Migration from v1.0

### Files to Update

| File | Changes |
|------|---------|
| `jutsu_engine/live/dry_run_executor.py` | Rename to MockOrderExecutor |
| `jutsu_engine/data/models.py` | Add LiveTrade, ConfigOverride models |
| `config/live_trading_config.yaml` | Add mode, execution_time options |
| `scripts/daily_dry_run.py` | Refactor to use unified executor |

### New Files to Create

| File | Purpose |
|------|---------|
| `jutsu_engine/live/executor_router.py` | Route to Mock or Schwab executor |
| `jutsu_engine/live/mock_executor.py` | Mock order execution |
| `jutsu_engine/live/schwab_executor.py` | Real Schwab order execution |
| `jutsu_engine/api/main.py` | FastAPI application |
| `dashboard/` | React dashboard application |

---

## Appendix B: CLI Reference

```bash
# Offline mock trading
jutsu live --mode offline --execution-time 5min_before_close

# Online live trading (requires confirmation)
jutsu live --mode online --execution-time 5min_before_close --confirm

# Check current status
jutsu live status

# View recent trades
jutsu live trades --limit 20 --mode all

# Export trades to CSV
jutsu live export --output trades_2025.csv

# Start dashboard server
jutsu dashboard --port 8000
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Nov 2025 | Team | Original PRD |
| 2.0 | Dec 2025 | Team | Added dual-mode, dashboard, multi-time execution |

---

**End of Document**
