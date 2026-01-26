# Jutsu Labs - Product Requirements Document

**Document Version:** 4.0
**Status:** Production
**Last Updated:** January 25, 2026
**Document Owner:** Jutsu Labs Team

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Nov 2025 | Team | Initial PRD |
| 2.0 | Dec 2025 | Team | Dual-mode trading, dashboard wireframes |
| 3.0 | Jan 2026 | Team | Production release, v5.1 strategy, passkeys, PostgreSQL |
| 4.0 | Jan 2026 | Team | Multi-strategy engine, EOD daily performance, V2 API, RBAC |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Overview](#2-product-overview)
3. [User Personas & Use Cases](#3-user-personas--use-cases)
4. [Functional Requirements](#4-functional-requirements)
5. [System Architecture](#5-system-architecture)
6. [Data Architecture](#6-data-architecture)
7. [API Specification](#7-api-specification)
8. [Security & Authentication](#8-security--authentication)
9. [Performance Requirements](#9-performance-requirements)
10. [Deployment & Infrastructure](#10-deployment--infrastructure)
11. [Monitoring & Observability](#11-monitoring--observability)
12. [Success Metrics](#12-success-metrics)
13. [Roadmap](#13-roadmap)
14. [Appendices](#appendices)

---

## 1. Executive Summary

### 1.1 Product Vision

Jutsu Labs is an **automated trading platform** that enables systematic traders to build, test, and run algorithmic trading strategies with full transparency and control. The platform bridges the gap between backtesting research and live execution through a unified workflow.

### 1.2 Problem Statement

Individual traders and small teams face significant challenges:
- **Fragmented tooling**: Separate systems for backtesting, optimization, and live trading
- **Execution gap**: Strategies that work in backtests fail in production due to implementation differences
- **Lack of visibility**: No unified view of historical vs. live performance
- **Complexity barrier**: Enterprise-grade features require significant engineering effort

### 1.3 Solution

Jutsu Labs provides an integrated platform with:
- **Unified backtesting and live trading** using the same strategy code
- **Multi-strategy tracking** with side-by-side performance comparison
- **Web-based dashboard** for real-time monitoring and control
- **Progressive deployment model** from dry-run to production
- **Enterprise security** with multi-factor authentication and role-based access

### 1.4 Key Capabilities

| Capability | Description | Status |
|------------|-------------|--------|
| Strategy Backtesting | Historical simulation with realistic cost modeling | Production |
| Parameter Optimization | Grid search, walk-forward analysis, Monte Carlo | Production |
| Live Trading | Automated execution with Schwab API integration | Production |
| Multi-Strategy Tracking | Compare up to 3 strategies simultaneously | Production |
| Web Dashboard | Real-time monitoring with equity curves and KPIs | Production |
| Multi-User Access | Role-based permissions (Admin, Viewer) | Production |
| Data Management | Schwab API, Yahoo Finance, CSV import | Production |

### 1.5 Target Users

- Individual algorithmic traders
- Small trading teams (2-5 members)
- Quantitative researchers transitioning to live trading
- Self-directed investors with programming experience

---

## 2. Product Overview

### 2.1 Product Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            JUTSU LABS PLATFORM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐       │
│  │   WEB DASHBOARD  │    │    REST API      │    │  TRADING ENGINE  │       │
│  │   (React 18)     │◄──►│    (FastAPI)     │◄──►│    (Python)      │       │
│  │                  │    │                  │    │                  │       │
│  │  • Dashboard     │    │  • Auth API      │    │  • Backtesting   │       │
│  │  • Performance   │    │  • Trading API   │    │  • Optimization  │       │
│  │  • Backtest      │    │  • Data API      │    │  • Live Trading  │       │
│  │  • Trades        │    │  • WebSocket     │    │  • Scheduler     │       │
│  │  • Settings      │    │                  │    │                  │       │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘       │
│           │                       │                       │                  │
│           └───────────────────────┼───────────────────────┘                  │
│                                   │                                          │
│                      ┌────────────▼────────────┐                            │
│                      │      DATA LAYER         │                            │
│                      │      (PostgreSQL)       │                            │
│                      │                         │                            │
│                      │  • Market Data          │                            │
│                      │  • Performance Metrics  │                            │
│                      │  • Trade History        │                            │
│                      │  • User Management      │                            │
│                      └─────────────────────────┘                            │
│                                   │                                          │
│                      ┌────────────▼────────────┐                            │
│                      │    EXTERNAL SERVICES    │                            │
│                      │                         │                            │
│                      │  • Schwab API (Broker)  │                            │
│                      │  • Yahoo Finance (Data) │                            │
│                      │  • Slack/Discord (Alerts)│                           │
│                      └─────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Technology Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Frontend | React | 18.x | Web dashboard UI |
| Frontend | TypeScript | 5.x | Type safety |
| Frontend | Vite | 5.x | Build tooling |
| Frontend | Tailwind CSS | 3.x | Styling |
| Frontend | TanStack Query | 5.x | Data fetching |
| Backend API | FastAPI | 0.110+ | REST API server |
| Backend Engine | Python | 3.10+ | Trading engine |
| Database | PostgreSQL | 15+ | Primary datastore |
| Scheduler | APScheduler | 3.x | Job scheduling |
| Broker | schwab-py | 1.x | Schwab API client |
| Reverse Proxy | NGINX | 1.x | Load balancing |
| Containerization | Docker | 24+ | Deployment |

### 2.3 Included Strategies

| Strategy | Type | Description | Status |
|----------|------|-------------|--------|
| Hierarchical Adaptive v3.5b | Trend-Following | 6-cell regime matrix with Treasury overlay | Production |
| Hierarchical Adaptive v3.5d | Trend-Following | Enhanced v3.5b with refined parameters | Production |
| MACD Trend v4 (Goldilocks) | Momentum | EMA trend + MACD with dual-mode sizing | Production |
| MACD Trend v5 | Momentum | Dual-regime with VIX parameter switching | Production |
| MACD Trend v6 | Momentum | VIX-gated execution with binary filter | Production |
| Kalman Gearing | Adaptive | Kalman filter-based trend detection | Experimental |

---

## 3. User Personas & Use Cases

### 3.1 User Personas

#### Persona 1: Solo Algorithmic Trader

**Profile:**
- Experience: 3-5 years trading, 1-2 years programming
- Goals: Automate trading to reduce emotional decisions, track performance rigorously
- Pain Points: Manual trade execution, scattered performance data, no systematic approach

**Key Needs:**
- Simple deployment (Docker)
- Clear performance metrics
- Reliable automated execution
- Mobile-friendly dashboard

#### Persona 2: Quantitative Researcher

**Profile:**
- Experience: 5+ years quantitative analysis, strong programming skills
- Goals: Test multiple strategy variations, find optimal parameters, validate ideas
- Pain Points: Slow iteration cycles, difficulty comparing strategies, overfitting concerns

**Key Needs:**
- Comprehensive backtesting
- Walk-forward optimization
- Monte Carlo simulation
- Multi-strategy comparison

#### Persona 3: Trading Team Admin

**Profile:**
- Experience: Managing small trading operation (2-5 people)
- Goals: Provide team visibility, control access, maintain security
- Pain Points: Sharing strategies safely, audit trails, role management

**Key Needs:**
- Multi-user access control
- Role-based permissions
- Invitation-based onboarding
- Audit logging

### 3.2 Primary Use Cases

#### UC-1: Strategy Backtesting

**Actor:** Trader/Researcher
**Preconditions:** Historical data available, strategy defined
**Flow:**
1. User selects strategy and date range
2. System loads historical data
3. System simulates trades bar-by-bar
4. System calculates performance metrics
5. User reviews results (equity curve, metrics, trades)

**Acceptance Criteria:**
- Backtest completes within 30 seconds for 10 years of daily data
- Metrics include: CAGR, Sharpe, Sortino, Max Drawdown, Win Rate
- Results exportable to CSV

#### UC-2: Live Trading Execution

**Actor:** Trader
**Preconditions:** Schwab authentication, strategy configured, market open
**Flow:**
1. Scheduler triggers trading job at 3:55 PM ET
2. System fetches current market data
3. Strategy generates signals
4. System calculates position changes
5. System executes orders via Schwab API
6. System logs trades and updates positions

**Acceptance Criteria:**
- Orders placed within 5 minutes of trigger
- Fill prices tracked with slippage analysis
- Failures trigger alerts via webhook

#### UC-3: Performance Monitoring

**Actor:** Trader/Admin
**Preconditions:** User authenticated, historical data exists
**Flow:**
1. User opens dashboard
2. System displays current regime, positions, equity
3. User selects time range for analysis
4. System shows performance metrics and chart
5. User compares against baseline (QQQ)

**Acceptance Criteria:**
- Dashboard loads within 2 seconds
- Real-time updates via WebSocket
- Baseline comparison available for all periods

#### UC-4: Multi-Strategy Comparison

**Actor:** Trader/Researcher
**Preconditions:** Multiple strategies with performance data
**Flow:**
1. User enables comparison mode
2. User selects up to 3 strategies
3. System displays side-by-side metrics
4. System overlays equity curves on chart
5. User analyzes relative performance

**Acceptance Criteria:**
- Strategy selection persisted in URL
- Chart supports up to 3 overlaid curves
- Metrics table shows all strategies

#### UC-5: User Invitation

**Actor:** Admin
**Preconditions:** Admin authenticated, user limit not reached
**Flow:**
1. Admin creates invitation with email and role
2. System generates secure token (48-hour expiry)
3. Admin shares invitation link
4. Invitee clicks link and creates account
5. System assigns specified role

**Acceptance Criteria:**
- Maximum 20 users per installation
- Tokens expire after 48 hours
- Roles: Admin, Viewer

---

## 4. Functional Requirements

### 4.1 Backtesting Engine

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| BE-01 | Execute bar-by-bar simulation without lookahead bias | P0 | Done |
| BE-02 | Support daily and intraday timeframes | P0 | Done |
| BE-03 | Model commission and slippage costs | P0 | Done |
| BE-04 | Calculate 15+ performance metrics | P0 | Done |
| BE-05 | Generate equity curve and drawdown series | P0 | Done |
| BE-06 | Export results to CSV | P1 | Done |
| BE-07 | Support custom date ranges | P0 | Done |
| BE-08 | Compare against benchmark (QQQ baseline) | P1 | Done |

### 4.2 Optimization Framework

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| OP-01 | Grid search across parameter space | P0 | Done |
| OP-02 | Walk-forward optimization with rolling windows | P1 | Done |
| OP-03 | Monte Carlo simulation for robustness testing | P1 | Done |
| OP-04 | Parameter sensitivity analysis | P2 | Done |
| OP-05 | YAML-based configuration for reproducibility | P0 | Done |
| OP-06 | Progress reporting during optimization | P1 | Done |

### 4.3 Live Trading

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| LT-01 | Schwab OAuth authentication | P0 | Done |
| LT-02 | Scheduled execution at 3:55 PM ET | P0 | Done |
| LT-03 | Mock mode for validation without orders | P0 | Done |
| LT-04 | Online mode for real order execution | P0 | Done |
| LT-05 | Slippage tracking and abort threshold | P1 | Done |
| LT-06 | Position reconciliation at market close | P1 | Done |
| LT-07 | Manual kill switch via dashboard | P0 | Done |
| LT-08 | Token expiration monitoring and alerts | P1 | Done |

### 4.4 Web Dashboard

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| DB-01 | Display current positions and equity | P0 | Done |
| DB-02 | Show strategy regime (cell, trend, volatility) | P0 | Done |
| DB-03 | Interactive equity curve chart | P0 | Done |
| DB-04 | Trade history with filtering and pagination | P0 | Done |
| DB-05 | Performance metrics table | P0 | Done |
| DB-06 | Strategy selector for multi-strategy tracking | P1 | Done |
| DB-07 | Strategy comparison mode (up to 3) | P1 | Done |
| DB-08 | Scheduler control (start/stop/pause) | P1 | Done |
| DB-09 | Schwab token status banner | P1 | Done |
| DB-10 | Responsive mobile layout | P2 | Done |
| DB-11 | Daily performance table with regime breakdown | P1 | Done |
| DB-12 | Backtest page with historical analysis | P1 | Done |

### 4.5 Data Management

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| DM-01 | Sync daily bars from Schwab API | P0 | Done |
| DM-02 | Sync data from Yahoo Finance | P1 | Done |
| DM-03 | Import data from CSV files | P2 | Done |
| DM-04 | Incremental sync (only new data) | P1 | Done |
| DM-05 | Data validation and gap detection | P1 | Done |
| DM-06 | Market calendar awareness (holidays, weekends) | P1 | Done |
| DM-07 | Multi-symbol sync support | P0 | Done |

### 4.6 Multi-User Access

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| MU-01 | Role-based access control (Admin, Viewer) | P1 | Done |
| MU-02 | Invitation-based user onboarding | P1 | Done |
| MU-03 | User limit enforcement (20 users) | P2 | Done |
| MU-04 | Permission-protected API endpoints | P1 | Done |
| MU-05 | Admin user management UI | P2 | Done |
| MU-06 | Self-service password change | P2 | Done |

---

## 5. System Architecture

### 5.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL ACCESS                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Internet ──► Cloudflare Tunnel ──► NGINX (SSL, Rate Limiting) ──► App     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          APPLICATION LAYER                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        WEB DASHBOARD (React 18)                      │    │
│  │  Port: 3000 | Vite Build | TailwindCSS | TanStack Query             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    │ HTTP/WebSocket                          │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        REST API (FastAPI)                            │    │
│  │  Port: 8000 | JWT Auth | Rate Limiting | OpenAPI Docs               │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  Routes:                                                             │    │
│  │  • /api/auth/*        Authentication & tokens                       │    │
│  │  • /api/status/*      System status & health                        │    │
│  │  • /api/performance/* Performance metrics & equity curves           │    │
│  │  • /api/trades/*      Trade history & export                        │    │
│  │  • /api/control/*     Engine start/stop, scheduler control          │    │
│  │  • /api/config/*      Strategy parameters                           │    │
│  │  • /api/strategies/*  Multi-strategy management                     │    │
│  │  • /api/users/*       User management (admin)                       │    │
│  │  • /api/v2/*          V2 API (daily performance)                    │    │
│  │  • /ws                WebSocket for real-time updates               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      TRADING ENGINE (Python)                         │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  Components:                                                         │    │
│  │  • EventLoop         Bar-by-bar simulation coordinator              │    │
│  │  • Strategy          Base class for trading strategies              │    │
│  │  • PortfolioSimulator Position and cash management                  │    │
│  │  • PerformanceAnalyzer Metrics calculation                          │    │
│  │  • Scheduler (APScheduler) Time-based job execution                 │    │
│  │  • ExecutionRouter   Mock vs Live order routing                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA LAYER                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      PostgreSQL 15+                                  │    │
│  │  Database: jutsu_labs | Host: tower.local | Port: 5432              │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  Tables:                                                             │    │
│  │  • market_data           OHLCV price data by symbol/timeframe       │    │
│  │  • live_trades           Executed trades with context               │    │
│  │  • positions             Current holdings by mode                    │    │
│  │  • performance_snapshots Point-in-time portfolio state              │    │
│  │  • daily_performance     EOD aggregated metrics (V2)                │    │
│  │  • users                 User accounts and credentials              │    │
│  │  • passkeys              WebAuthn credentials                       │    │
│  │  • user_invitations      Pending invitations                        │    │
│  │  • regime_timeseries     Historical regime states                   │    │
│  │  • data_metadata         Sync tracking                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL INTEGRATIONS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐               │
│  │  Schwab API   │    │ Yahoo Finance │    │ Webhooks      │               │
│  │               │    │               │    │               │               │
│  │ • OAuth 2.0   │    │ • Historical  │    │ • Slack       │               │
│  │ • Quotes      │    │   data        │    │ • Discord     │               │
│  │ • Orders      │    │ • Free tier   │    │ • Generic     │               │
│  │ • Account     │    │               │    │               │               │
│  └───────────────┘    └───────────────┘    └───────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Module Structure

```
jutsu-labs/
├── jutsu_engine/              # Core trading engine
│   ├── core/                  # Domain logic
│   │   ├── event_loop.py      # Bar-by-bar coordinator
│   │   ├── strategy_base.py   # Strategy base class
│   │   └── events.py          # Event definitions
│   ├── strategies/            # Strategy implementations
│   │   ├── Hierarchical_Adaptive_v3_5b.py
│   │   ├── Hierarchical_Adaptive_v3_5d.py
│   │   ├── MACD_Trend_v4.py
│   │   └── ...
│   ├── indicators/            # Technical indicators
│   ├── portfolio/             # Position management
│   ├── performance/           # Metrics calculation
│   ├── optimization/          # Grid search, WFO, Monte Carlo
│   ├── live/                  # Live trading components
│   ├── data/                  # Data handlers and fetchers
│   ├── api/                   # Internal API routes
│   ├── jobs/                  # Scheduled jobs
│   └── cli/                   # Command-line interface
├── jutsu_api/                 # FastAPI application
│   ├── routers/               # API route definitions
│   ├── auth/                  # Authentication logic
│   ├── models/                # Pydantic schemas
│   └── main.py                # Application entry
├── dashboard/                 # React frontend
│   ├── src/
│   │   ├── pages/             # Page components
│   │   ├── components/        # Reusable components
│   │   ├── contexts/          # React contexts
│   │   ├── hooks/             # Custom hooks
│   │   └── api/               # API client
│   └── vite.config.ts
├── config/                    # Configuration files
├── alembic/                   # Database migrations
├── tests/                     # Test suite
├── docker/                    # Docker configuration
├── scripts/                   # Utility scripts
└── docs/                      # Documentation
```

### 5.3 Strategy Architecture

The Hierarchical Adaptive strategy family uses a regime-based approach:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    HIERARCHICAL ADAPTIVE STRATEGY                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     REGIME DETECTION LAYER                           │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                       │    │
│  │   ┌─────────────────┐         ┌─────────────────┐                   │    │
│  │   │  TREND STATE    │         │  VOLATILITY     │                   │    │
│  │   │                 │         │  STATE          │                   │    │
│  │   │  • Kalman filter│         │  • Z-score      │                   │    │
│  │   │  • SMA cross    │         │  • Realized vol │                   │    │
│  │   │  • T-norm       │         │  • Vol crush    │                   │    │
│  │   │                 │         │                 │                   │    │
│  │   │  Output:        │         │  Output:        │                   │    │
│  │   │  BULL/NEUTRAL/  │         │  LOW/NORMAL/    │                   │    │
│  │   │  BEAR           │         │  HIGH           │                   │    │
│  │   └────────┬────────┘         └────────┬────────┘                   │    │
│  │            │                           │                             │    │
│  │            └───────────┬───────────────┘                             │    │
│  │                        ▼                                             │    │
│  │              ┌─────────────────┐                                     │    │
│  │              │  6-CELL MATRIX  │                                     │    │
│  │              │                 │                                     │    │
│  │              │  BULL + LOW → 1 │                                     │    │
│  │              │  BULL + NORMAL→2│                                     │    │
│  │              │  BULL + HIGH → 3│                                     │    │
│  │              │  BEAR + LOW → 4 │                                     │    │
│  │              │  BEAR + NORMAL→5│                                     │    │
│  │              │  BEAR + HIGH → 6│                                     │    │
│  │              └────────┬────────┘                                     │    │
│  └───────────────────────┼─────────────────────────────────────────────┘    │
│                          ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     ALLOCATION LAYER                                 │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                       │    │
│  │   CELL 1: 80% TQQQ, 20% TMF   (Aggressive bull, low vol)            │    │
│  │   CELL 2: 60% TQQQ, 30% QQQ, 10% TMF (Moderate bull)                │    │
│  │   CELL 3: 40% QQQ, 40% TMV, 20% Cash (Volatile bull)                │    │
│  │   CELL 4: 50% TMF, 30% QQQ, 20% Cash (Defensive bear)               │    │
│  │   CELL 5: 60% TMV, 20% PSQ, 20% Cash (Active bear)                  │    │
│  │   CELL 6: 80% Cash, 20% PSQ (Crisis mode)                           │    │
│  │                                                                       │    │
│  │   Treasury Overlay: TMF/TMV selection based on TLT trend            │    │
│  │   Rebalance Threshold: 2.5% drift triggers rebalance                │    │
│  │                                                                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Architecture

### 6.1 Database Schema (Core Tables)

#### market_data
```sql
CREATE TABLE market_data (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(18,6) NOT NULL,
    high NUMERIC(18,6) NOT NULL,
    low NUMERIC(18,6) NOT NULL,
    close NUMERIC(18,6) NOT NULL,
    volume BIGINT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timeframe, timestamp)
);
CREATE INDEX idx_market_data_symbol_tf_ts ON market_data(symbol, timeframe, timestamp DESC);
```

#### daily_performance (V2 API)
```sql
CREATE TABLE daily_performance (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(50) NOT NULL,
    trading_date DATE NOT NULL,

    -- Equity metrics
    total_equity NUMERIC(18,6) NOT NULL,
    daily_return NUMERIC(12,8),
    cumulative_return NUMERIC(12,8),

    -- Risk metrics
    sharpe_ratio NUMERIC(10,6),
    sortino_ratio NUMERIC(10,6),
    max_drawdown NUMERIC(10,6),
    calmar_ratio NUMERIC(10,6),

    -- Trade metrics
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(6,4),

    -- Regime context
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),

    -- Positions
    positions_json JSONB,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_id, trading_date)
);
```

#### live_trades
```sql
CREATE TABLE live_trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    strategy_id VARCHAR(50),
    symbol VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    target_price NUMERIC(18,6),
    fill_price NUMERIC(18,6),
    slippage_pct NUMERIC(8,4),
    mode VARCHAR(20) NOT NULL,
    schwab_order_id VARCHAR(50),
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

#### users
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'viewer' NOT NULL,
    totp_secret VARCHAR(32),
    totp_enabled BOOLEAN DEFAULT FALSE,
    backup_codes TEXT[],
    failed_login_count INTEGER DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

### 6.2 Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DATA FLOW                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INGEST                    PROCESS                      SERVE               │
│  ──────                    ───────                      ─────               │
│                                                                              │
│  ┌───────────┐           ┌─────────────┐           ┌─────────────┐         │
│  │Schwab API │──────────►│ DataSync    │──────────►│ market_data │         │
│  │Yahoo Fin  │           │ Service     │           │ table       │         │
│  │CSV Import │           │             │           │             │         │
│  └───────────┘           │ • Normalize │           └──────┬──────┘         │
│                          │ • Validate  │                  │                 │
│                          │ • Dedupe    │                  ▼                 │
│                          └─────────────┘           ┌─────────────┐         │
│                                                     │ EventLoop   │         │
│  ┌───────────┐           ┌─────────────┐           │ (Backtest)  │         │
│  │Scheduler  │──────────►│ Strategy    │◄──────────│             │         │
│  │ 3:55 PM   │           │ Runner      │           └──────┬──────┘         │
│  └───────────┘           │             │                  │                 │
│                          │ • Signals   │                  ▼                 │
│                          │ • Allocate  │           ┌─────────────┐         │
│                          │ • Execute   │           │ Performance │         │
│                          └──────┬──────┘           │ Analyzer    │         │
│                                 │                  │             │         │
│                                 ▼                  │ • Metrics   │         │
│                          ┌─────────────┐           │ • Equity    │         │
│                          │ live_trades │           └──────┬──────┘         │
│                          │ positions   │                  │                 │
│                          └─────────────┘                  ▼                 │
│                                                    ┌─────────────┐         │
│                                                    │ daily_perf  │         │
│                                                    │ snapshots   │         │
│                                                    └──────┬──────┘         │
│                                                           │                 │
│                                                           ▼                 │
│                                                    ┌─────────────┐         │
│                                                    │ REST API    │         │
│                                                    │ → Dashboard │         │
│                                                    └─────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. API Specification

### 7.1 Authentication API

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/login` | Login with username/password | No |
| POST | `/api/auth/login/2fa` | Complete 2FA verification | No |
| POST | `/api/auth/refresh` | Refresh access token | Refresh Token |
| POST | `/api/auth/logout` | Logout and revoke tokens | Access Token |
| GET | `/api/auth/me` | Get current user info | Access Token |

### 7.2 Trading API

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/status` | System status overview | Access Token |
| GET | `/api/status/health` | Health check | No |
| GET | `/api/status/regime` | Current regime state | Access Token |
| GET | `/api/indicators` | Current indicator values | Access Token |
| POST | `/api/trades/execute` | Manual trade execution | Admin |
| GET | `/api/trades` | Trade history | Access Token |
| GET | `/api/trades/export` | Export trades to CSV | Access Token |

### 7.3 Performance API

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/performance` | Performance metrics | Access Token |
| GET | `/api/performance/equity-curve` | Equity curve data | Access Token |
| GET | `/api/v2/daily-performance` | V2 daily performance | Access Token |
| GET | `/api/v2/daily-performance/history` | V2 historical data | Access Token |

### 7.4 Strategy API

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/strategies` | List registered strategies | Access Token |
| GET | `/api/strategies/{id}` | Get strategy details | Access Token |
| GET | `/api/config` | Get strategy parameters | Access Token |
| PUT | `/api/config` | Update parameters | Admin |

### 7.5 Control API

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/control/start` | Start trading engine | Admin |
| POST | `/api/control/stop` | Stop trading engine | Admin |
| POST | `/api/control/restart` | Restart engine | Admin |
| GET | `/api/scheduler/jobs` | List scheduled jobs | Access Token |
| POST | `/api/scheduler/jobs/{id}/pause` | Pause job | Admin |
| POST | `/api/scheduler/jobs/{id}/resume` | Resume job | Admin |

### 7.6 User Management API

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/users` | List users | Admin |
| POST | `/api/users/invite` | Create invitation | Admin |
| GET | `/api/users/{id}` | Get user details | Admin |
| PUT | `/api/users/{id}` | Update user role | Admin |
| DELETE | `/api/users/{id}` | Delete user | Admin |
| GET | `/api/invitations/{token}` | Validate invitation | No |
| POST | `/api/invitations/{token}/accept` | Accept invitation | No |

### 7.7 WebSocket Events

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `status_update` | Server → Client | `{equity, positions, regime}` | Periodic status |
| `trade_executed` | Server → Client | `{trade_details}` | Trade notification |
| `regime_change` | Server → Client | `{old_regime, new_regime}` | Regime transition |
| `error` | Server → Client | `{message, code}` | Error notification |

---

## 8. Security & Authentication

### 8.1 Authentication Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AUTHENTICATION FLOW                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────┐                                                          │
│  │ Login Request │                                                          │
│  │ (user/pass)   │                                                          │
│  └───────┬───────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│  ┌───────────────┐     ┌───────────────┐                                    │
│  │ Rate Limiter  │────►│ 5 req/min/IP  │                                    │
│  │ (slowapi)     │     │ Brute force   │                                    │
│  └───────┬───────┘     │ protection    │                                    │
│          │             └───────────────┘                                    │
│          ▼                                                                   │
│  ┌───────────────┐                                                          │
│  │ Password      │                                                          │
│  │ Verification  │                                                          │
│  │ (bcrypt)      │                                                          │
│  └───────┬───────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│  ┌───────────────────────────────────────────────────────────┐              │
│  │                    2FA CHECK                               │              │
│  │  ┌─────────────┐              ┌─────────────────────────┐ │              │
│  │  │ Has Passkey?│──── YES ────►│ WebAuthn Challenge      │ │              │
│  │  │             │              │ (FIDO2 authenticator)   │ │              │
│  │  └──────┬──────┘              └────────────┬────────────┘ │              │
│  │         │ NO                               │              │              │
│  │         ▼                                  │              │              │
│  │  ┌─────────────┐                           │              │              │
│  │  │ TOTP Code   │                           │              │              │
│  │  │ (6 digits)  │                           │              │              │
│  │  └──────┬──────┘                           │              │              │
│  │         │                                  │              │              │
│  │         └──────────────┬───────────────────┘              │              │
│  └────────────────────────┼──────────────────────────────────┘              │
│                           │                                                  │
│                           ▼                                                  │
│  ┌───────────────────────────────────────────────────────────┐              │
│  │                    TOKEN ISSUANCE                          │              │
│  │  ┌─────────────────────┐    ┌─────────────────────────┐   │              │
│  │  │  Password Login     │    │  Passkey Login          │   │              │
│  │  │  Access: 15 min     │    │  Access: 7 hours        │   │              │
│  │  │  Refresh: 7 days    │    │  Refresh: 7 days        │   │              │
│  │  └─────────────────────┘    └─────────────────────────┘   │              │
│  └───────────────────────────────────────────────────────────┘              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Security Controls

| Control | Implementation | Configuration |
|---------|---------------|---------------|
| Password Hashing | bcrypt with salt | 12 rounds |
| JWT Tokens | HS256 algorithm | 256-bit secret key |
| Rate Limiting | slowapi middleware | 5 requests/minute/IP |
| Account Lockout | Progressive lockout | 10 failed attempts |
| CORS | Configurable origins | `CORS_ORIGINS` env var |
| HTTPS | Cloudflare + NGINX | TLS 1.2+ required |
| Security Headers | NGINX | HSTS, X-Frame-Options, CSP |

### 8.3 Role-Based Access Control

| Role | Permissions |
|------|-------------|
| **Admin** | Full access to all features |
| **Viewer** | Read-only access to dashboard, performance, trades |

**Admin-Only Operations:**
- Execute trades
- Start/stop trading engine
- Modify strategy parameters
- Manage scheduler jobs
- Create/delete users
- Access Schwab re-authentication

**Viewer Permissions:**
- View dashboard and performance
- View trade history
- View configuration (read-only)
- Change own password
- Manage own 2FA/passkeys

---

## 9. Performance Requirements

### 9.1 Response Time Targets

| Operation | Target | Actual |
|-----------|--------|--------|
| Dashboard load | < 2 seconds | < 500ms |
| API response (simple) | < 200ms | < 100ms |
| API response (complex) | < 1 second | < 500ms |
| Trade execution | < 5 seconds | < 3 seconds |
| Backtest (1 year) | < 5 seconds | < 2 seconds |
| Backtest (10 years) | < 30 seconds | < 15 seconds |

### 9.2 Scalability Targets

| Metric | Target |
|--------|--------|
| Concurrent users | 20 |
| Historical data | 20+ years |
| Symbols tracked | 50+ |
| Strategies active | 10 |
| Daily snapshots | 365,000+ (10 years × 100 strategies) |

### 9.3 Availability Targets

| Metric | Target |
|--------|--------|
| Uptime | 99.9% |
| Scheduled downtime | < 4 hours/month |
| Recovery time (failure) | < 5 minutes |
| Data durability | 99.999% |

---

## 10. Deployment & Infrastructure

### 10.1 Docker Deployment

```yaml
# docker-compose.yml structure
services:
  jutsu-labs:
    image: ankugo/jutsu-labs:latest
    ports:
      - "8000:8000"   # API
      - "3000:3000"   # Dashboard
    environment:
      - DATABASE_TYPE=postgresql
      - POSTGRES_HOST=tower.local
      - AUTH_REQUIRED=true
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./token.json:/app/token.json

  postgresql:
    image: postgres:15
    environment:
      - POSTGRES_DB=jutsu_labs
      - POSTGRES_USER=jutsu
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

### 10.2 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_TYPE` | Database type | Yes | `sqlite` |
| `POSTGRES_HOST` | PostgreSQL host | If PostgreSQL | - |
| `POSTGRES_PORT` | PostgreSQL port | No | `5432` |
| `POSTGRES_USER` | Database user | If PostgreSQL | - |
| `POSTGRES_PASSWORD` | Database password | If PostgreSQL | - |
| `POSTGRES_DATABASE` | Database name | If PostgreSQL | - |
| `AUTH_REQUIRED` | Enable authentication | No | `true` |
| `SECRET_KEY` | JWT signing key | Yes | - |
| `ADMIN_PASSWORD` | Initial admin password | Yes | - |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | No | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | No | `7` |
| `SCHWAB_API_KEY` | Schwab API key | For live trading | - |
| `SCHWAB_APP_SECRET` | Schwab app secret | For live trading | - |
| `NOTIFICATION_WEBHOOK_URL` | Webhook URL | For alerts | - |
| `CORS_ORIGINS` | Allowed origins | No | `*` |

### 10.3 Production Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PRODUCTION DEPLOYMENT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Internet ────► Cloudflare Tunnel ────► NGINX ────► Docker Container        │
│                 (SSL termination)        (Rate limiting)                     │
│                 (DDoS protection)        (Security headers)                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      DOCKER HOST (Unraid)                            │    │
│  │                                                                       │    │
│  │   ┌───────────────────────────────────────────────────────────┐     │    │
│  │   │  jutsu-labs:latest                                        │     │    │
│  │   │                                                            │     │    │
│  │   │  • FastAPI backend (port 8000)                            │     │    │
│  │   │  • React dashboard (port 3000, served by FastAPI)         │     │    │
│  │   │  • APScheduler (in-process)                               │     │    │
│  │   │                                                            │     │    │
│  │   └───────────────────────────────────────────────────────────┘     │    │
│  │                              │                                        │    │
│  │                              ▼                                        │    │
│  │   ┌───────────────────────────────────────────────────────────┐     │    │
│  │   │  PostgreSQL 15                                             │     │    │
│  │   │                                                            │     │    │
│  │   │  • Database: jutsu_labs                                   │     │    │
│  │   │  • Persistent volume                                       │     │    │
│  │   │  • Daily backups                                           │     │    │
│  │   │                                                            │     │    │
│  │   └───────────────────────────────────────────────────────────┘     │    │
│  │                                                                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Monitoring & Observability

### 11.1 Scheduled Jobs

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `trading_job` | Cron: 15:55 ET M-F | Execute strategy |
| `hourly_refresh_job` | Every hour | Update market data |
| `market_close_job` | Cron: 16:05 ET M-F | EOD snapshot |
| `eod_daily_performance_job` | Cron: 16:15 ET M-F | V2 daily metrics |
| `token_expiration_check_job` | Every 12 hours | Check Schwab token |

### 11.2 Webhook Notifications

**Notification Events:**
- Token expiration warnings (5 days, 2 days, 1 day, 12 hours)
- Trade execution failures
- Strategy errors
- System health alerts

**Supported Platforms:**
- Slack
- Discord
- Generic HTTP POST

### 11.3 Dashboard Token Banner

| Token Remaining | Banner Color | Message |
|-----------------|--------------|---------|
| > 5 days | Hidden | - |
| 2-5 days | Info (blue) | Plan re-authentication |
| 1-2 days | Warning (yellow) | Re-authenticate soon |
| < 12 hours | Critical (red) | Re-authenticate now |
| Expired | Critical (red) | Token expired |

---

## 12. Success Metrics

### 12.1 System Reliability

| Metric | Target | Current |
|--------|--------|---------|
| Uptime | 99.9% | 99.9%+ |
| Trade execution success rate | 100% | 100% |
| Average slippage | < 0.5% | < 0.3% |
| Dashboard availability | 99.9% | 99.9%+ |
| API response time (p95) | < 500ms | < 200ms |

### 12.2 Data Integrity

| Metric | Target | Current |
|--------|--------|---------|
| Position reconciliation accuracy | 100% | 100% |
| Performance calculation accuracy | 100% | 100% |
| Database integrity | 100% | 100% |
| Backup success rate | 100% | 100% |

### 12.3 Security

| Metric | Target | Current |
|--------|--------|---------|
| Authentication bypass vulnerabilities | 0 | 0 |
| SQL injection vulnerabilities | 0 | 0 |
| XSS vulnerabilities | 0 | 0 |
| Security audit pass rate | 100% | 100% |

---

## 13. Roadmap

### 13.1 Completed (v4.0)

- [x] Multi-strategy tracking and comparison
- [x] EOD daily performance aggregation (V2 API)
- [x] Role-based access control (Admin, Viewer)
- [x] Invitation-based user onboarding
- [x] Responsive mobile dashboard
- [x] Baseline comparison (QQQ)
- [x] Daily performance table with regime breakdown

### 13.2 Planned (v4.1)

- [ ] Investor role with restricted metrics
- [ ] Email notifications for token expiry
- [ ] Strategy cloning and parameter editing UI
- [ ] Alert configuration per strategy
- [ ] Historical regime visualization

### 13.3 Future Considerations

- [ ] Multi-broker support (Interactive Brokers, Alpaca)
- [ ] Options trading support
- [ ] Crypto asset support
- [ ] Machine learning strategy framework
- [ ] Mobile native app

---

## Appendices

### Appendix A: CLI Reference

```bash
# Data Management
jutsu init                                    # Initialize database
jutsu sync --symbol AAPL --start 2020-01-01  # Sync single symbol
jutsu sync --all                              # Sync all tracked symbols
jutsu delete-data --symbol AAPL               # Delete symbol data

# Backtesting
jutsu backtest --strategy MACD_Trend_v4 --start 2020-01-01 --end 2024-12-31
jutsu backtest --config config/backtest/config_v3_5b.yaml

# Optimization
jutsu grid-search --config grid-configs/search_v3_5b.yaml
jutsu wfo --config grid-configs/wfo_v3_5b.yaml
jutsu monte-carlo --config config/monte_carlo.yaml

# Live Trading
jutsu live --mode mock --execution-time 5min_before_close
jutsu live --mode online --execution-time 5min_before_close --confirm
jutsu live status

# Dashboard
jutsu dashboard --port 8000 --host 0.0.0.0
```

### Appendix B: Strategy Parameters (v3.5b)

```yaml
strategy:
  name: Hierarchical_Adaptive_v3_5b
  parameters:
    # Kalman Trend (6 parameters)
    measurement_noise: 3000.0
    process_noise_1: 0.01
    process_noise_2: 0.01
    osc_smoothness: 15
    strength_smoothness: 15
    T_max: 50.0

    # Structural Trend (4 parameters)
    sma_fast: 40
    sma_slow: 140
    t_norm_bull_thresh: 0.05
    t_norm_bear_thresh: -0.30

    # Volatility Z-Score (4 parameters)
    realized_vol_window: 21
    vol_baseline_window: 200
    upper_thresh_z: 1.0
    lower_thresh_z: 0.2

    # Vol-Crush Override (2 parameters)
    vol_crush_threshold: -0.15
    vol_crush_lookback: 5

    # Treasury Overlay (5 parameters)
    allow_treasury: true
    bond_sma_fast: 20
    bond_sma_slow: 60
    max_bond_weight: 0.4
    treasury_trend_symbol: TLT

    # Allocation (3 parameters)
    leverage_scalar: 1.0
    use_inverse_hedge: false
    w_PSQ_max: 0.5

    # Rebalancing (1 parameter)
    rebalance_threshold: 0.025
```

### Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Regime** | Market state classification (trend + volatility) |
| **Cell** | Position in the 6-cell allocation matrix |
| **T-norm** | Normalized trend strength indicator |
| **Z-score** | Volatility normalized to historical baseline |
| **Treasury Overlay** | Bond allocation based on TLT trend |
| **Vol Crush** | Volatility compression breakout signal |
| **Slippage** | Difference between expected and actual fill price |
| **Drawdown** | Peak-to-trough equity decline |
| **Sharpe Ratio** | Risk-adjusted return metric |
| **Walk-Forward** | Rolling optimization methodology |

---

**End of Document**
