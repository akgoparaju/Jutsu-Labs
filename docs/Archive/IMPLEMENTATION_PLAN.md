# Jutsu Labs - Comprehensive Implementation Plan

> Detailed roadmap for Phases 2-4 implementation with dependencies, technical specifications, and acceptance criteria

**Version:** 1.0
**Last Updated:** November 2, 2025
**Status:** Phase 1 Complete ✅ | Phase 2-4 Planned 📋

---

## Table of Contents

1. [Overview](#overview)
2. [Phase 2: Service Layer (Q1 2025)](#phase-2-service-layer-q1-2025)
3. [Phase 3: UI & Distribution (Q2 2025)](#phase-3-ui--distribution-q2-2025)
4. [Phase 4: Production Features (Q3-Q4 2025)](#phase-4-production-features-q3-q4-2025)
5. [Implementation Order & Dependencies](#implementation-order--dependencies)
6. [Technical Stack Additions](#technical-stack-additions)
7. [Risk Assessment](#risk-assessment)

---

## Overview

### Current Status (Phase 1: MVP) ✅ COMPLETE

**Completed Components:**
- ✅ Core Domain: EventLoop, Strategy Base, Events, Portfolio Simulator
- ✅ Application Layer: BacktestRunner, DataSync
- ✅ Infrastructure: DatabaseDataHandler, SchwabDataFetcher, Indicators, Performance Analyzer
- ✅ CLI: 5 commands (init, sync, status, validate, backtest)
- ✅ Database: SQLite with 3 tables (MarketData, DataMetadata, DataAuditLog)
- ✅ Documentation: Complete architecture and development guides
- ✅ Test Coverage: 80%+ with unit and integration tests

**Architecture:** Hexagonal (Ports & Adapters) with 4 layers

### Implementation Principles

1. **Incremental Delivery**: Each feature should be independently deployable
2. **Backward Compatibility**: Don't break existing functionality
3. **Test-Driven**: Maintain >80% test coverage
4. **Documentation-First**: Update docs before implementation
5. **Performance Monitoring**: Benchmark and optimize early
6. **Security-First**: Security considerations from day 1

---

## Phase 2: Service Layer (Q1 2025)

**Duration:** ~12 weeks
**Complexity:** Moderate
**Dependencies:** Phase 1 Complete ✅

### 2.1 REST API with FastAPI

**Priority:** HIGH
**Complexity:** Moderate (3-4 weeks)
**Dependencies:** None

#### Implementation Steps

**Step 1: API Foundation (Week 1)**
1. Create `jutsu_api/` package structure
2. Set up FastAPI application with CORS
3. Implement health check and version endpoints
4. Add OpenAPI documentation generation
5. Configure logging and error handling

**Files to Create:**
```
jutsu_api/
├── __init__.py
├── main.py              # FastAPI app initialization
├── models/
│   ├── __init__.py
│   └── schemas.py       # Pydantic models
├── routers/
│   ├── __init__.py
│   ├── backtest.py      # Backtest endpoints
│   ├── data.py          # Data management endpoints
│   └── strategies.py    # Strategy endpoints
└── dependencies.py      # Dependency injection
```

**Step 2: Backtest Endpoints (Week 2)**
1. POST `/api/v1/backtest` - Submit backtest job
2. GET `/api/v1/backtest/{id}` - Get backtest status
3. GET `/api/v1/backtest/{id}/results` - Retrieve results
4. DELETE `/api/v1/backtest/{id}` - Cancel/delete backtest

**Request Schema:**
```python
class BacktestRequest(BaseModel):
    symbol: str
    strategy: str
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    commission: Optional[Decimal] = Decimal('0.01')
    parameters: Optional[Dict[str, Any]] = {}
```

**Step 3: Data Endpoints (Week 2)**
1. GET `/api/v1/data/symbols` - List available symbols
2. GET `/api/v1/data/{symbol}/status` - Data availability
3. POST `/api/v1/data/sync` - Trigger data sync
4. GET `/api/v1/data/{symbol}/bars` - Retrieve bars with pagination

**Step 4: Strategy Endpoints (Week 3)**
1. GET `/api/v1/strategies` - List available strategies
2. GET `/api/v1/strategies/{name}` - Strategy details
3. POST `/api/v1/strategies/validate` - Validate strategy parameters

**Step 5: Authentication & Rate Limiting (Week 4)**
1. Implement JWT token authentication
2. Add API key support
3. Implement rate limiting (100 req/min per user)
4. Add request logging and audit trail

#### Integration Points

- **BacktestRunner**: Wrap existing functionality
- **DataSync**: Expose sync operations
- **Database**: Shared session management
- **Config**: Environment-based configuration

#### Acceptance Criteria

- [ ] All endpoints documented in OpenAPI
- [ ] Response time <200ms for non-compute endpoints
- [ ] Proper error handling with status codes
- [ ] JWT authentication working
- [ ] Rate limiting enforced
- [ ] >90% test coverage for API layer
- [ ] Load tested: 100 concurrent requests

#### Testing Strategy

1. **Unit Tests**: Individual endpoint logic
2. **Integration Tests**: End-to-end API flows
3. **Load Tests**: Locust/k6 for performance
4. **Security Tests**: OWASP top 10 validation

---

### 2.2 Parameter Optimization Framework

**Priority:** HIGH
**Complexity:** High (4-5 weeks)
**Dependencies:** REST API (optional), BacktestRunner

#### Implementation Steps

**Step 1: Optimizer Architecture (Week 1)**

**Files to Create:**
```
jutsu_engine/optimization/
├── __init__.py
├── base.py              # Optimizer base class
├── grid_search.py       # Grid search optimizer
├── genetic.py           # Genetic algorithm optimizer
├── results.py           # Result aggregation
└── visualizer.py        # Optimization visualization
```

**Base Optimizer Interface:**
```python
class Optimizer(ABC):
    @abstractmethod
    def optimize(
        self,
        strategy_class: Type[Strategy],
        param_space: Dict[str, List[Any]],
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        objective: str = 'sharpe_ratio'
    ) -> OptimizationResults:
        pass
```

**Step 2: Grid Search Implementation (Week 2)**

**Features:**
1. Exhaustive parameter space exploration
2. Parallel backtest execution
3. Progress tracking with callbacks
4. Result caching and resumption

**Parameter Space Definition:**
```python
param_space = {
    'short_period': [10, 20, 30, 50],
    'long_period': [50, 100, 150, 200],
    'position_size': [0.1, 0.25, 0.5, 1.0]
}
```

**Implementation:**
- Use `multiprocessing` for parallel execution
- Implement timeout per backtest (configurable)
- Store intermediate results to database
- Support resumption from interruption

**Step 3: Genetic Algorithm Implementation (Week 3)**

**Features:**
1. Population-based optimization
2. Crossover and mutation operators
3. Elitism and diversity preservation
4. Multi-objective optimization support

**Genetic Algorithm Parameters:**
```python
class GeneticConfig:
    population_size: int = 50
    generations: int = 100
    crossover_rate: float = 0.8
    mutation_rate: float = 0.1
    elitism_rate: float = 0.1
```

**Step 4: Walk-Forward Analysis (Week 4)**

**Features:**
1. Rolling window optimization
2. Out-of-sample validation
3. Overfitting detection
4. Performance decay analysis

**Walk-Forward Structure:**
```python
# Example: 6-month optimize, 3-month validate
optimize_window = timedelta(days=180)
validate_window = timedelta(days=90)
step_size = timedelta(days=30)
```

**Step 5: Result Analysis & Visualization (Week 5)**

**Outputs:**
1. Parameter sensitivity heatmaps
2. 3D surface plots for 2-parameter optimizations
3. Performance distribution histograms
4. Overfitting metrics (in-sample vs out-of-sample)
5. Stability analysis across parameter ranges

#### Integration Points

- **BacktestRunner**: Run multiple backtests
- **Database**: Store optimization results
- **Performance Analyzer**: Objective function calculation
- **CLI**: Add `jutsu optimize` command
- **API**: Add `/api/v1/optimize` endpoints

#### Acceptance Criteria

- [ ] Grid search: 1000 backtests in <10 minutes (parallel)
- [ ] Genetic algorithm: 5000 evaluations in <30 minutes
- [ ] Walk-forward analysis: 12-month period in <15 minutes
- [ ] Results stored in database with reproducibility
- [ ] Visualization exports (PNG, HTML interactive)
- [ ] >85% test coverage
- [ ] Overfitting metrics calculated automatically

#### Testing Strategy

1. **Synthetic Tests**: Known optimal parameters
2. **Benchmark Tests**: Compare to known strategies
3. **Convergence Tests**: Genetic algorithm convergence
4. **Stability Tests**: Repeated runs produce similar results

---

### 2.3 PostgreSQL Migration

**Priority:** MEDIUM
**Complexity:** Low (1-2 weeks)
**Dependencies:** None

#### Implementation Steps

**Step 1: Database Abstraction (Week 1)**

1. Create database factory pattern
2. Implement connection pooling
3. Add database-specific optimizations
4. Create migration utilities

**Files to Modify:**
```
jutsu_engine/data/
├── database_factory.py  # NEW: Database provider factory
├── postgres_handler.py  # NEW: PostgreSQL-specific handler
└── models.py            # MODIFY: Add PostgreSQL types
```

**Database Factory:**
```python
class DatabaseFactory:
    @staticmethod
    def create_engine(db_url: str) -> Engine:
        if db_url.startswith('postgresql'):
            return create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20
            )
        # SQLite configuration
```

**Step 2: Migration Scripts (Week 1)**

**Create migration utilities:**
```
scripts/
├── migrate_sqlite_to_postgres.py  # Data migration
└── performance_comparison.py      # Benchmark both DBs
```

**Migration Steps:**
1. Export data from SQLite
2. Create PostgreSQL schema
3. Import data with validation
4. Update indexes and constraints
5. Verify data integrity

**Step 3: Performance Optimization (Week 2)**

**PostgreSQL-specific optimizations:**
1. Partitioning by symbol/timeframe
2. Index optimization for time-series queries
3. Materialized views for common aggregations
4. Connection pooling configuration

**Partitioning Strategy:**
```sql
-- Partition market_data by symbol
CREATE TABLE market_data (
    ...
) PARTITION BY LIST (symbol);

CREATE TABLE market_data_aapl PARTITION OF market_data
FOR VALUES IN ('AAPL');
```

#### Integration Points

- **Config**: Add PostgreSQL connection settings
- **DataHandlers**: Use database factory
- **Tests**: Support both SQLite and PostgreSQL
- **CLI**: Add `jutsu migrate` command

#### Acceptance Criteria

- [ ] Supports both SQLite and PostgreSQL
- [ ] Migration script: 1M bars in <5 minutes
- [ ] Query performance: >2x faster for large datasets
- [ ] Connection pooling working
- [ ] All existing tests pass with PostgreSQL
- [ ] Documentation updated with PostgreSQL setup

#### Testing Strategy

1. **Migration Tests**: Verify data integrity
2. **Performance Tests**: Compare SQLite vs PostgreSQL
3. **Concurrency Tests**: Multiple connections
4. **Failover Tests**: Connection recovery

---

### 2.4 Advanced Metrics

**Priority:** MEDIUM
**Complexity:** Low (1 week)
**Dependencies:** None

#### Implementation Steps

**Step 1: Additional Metrics (Days 1-3)**

**Add to PerformanceAnalyzer:**
1. Sortino Ratio (downside deviation)
2. Omega Ratio
3. Tail Ratio
4. Value at Risk (VaR)
5. Conditional VaR (CVaR)
6. Rolling Sharpe Ratio (30-day, 90-day)
7. Rolling Max Drawdown
8. Recovery Time Analysis

**Implementation:**
```python
def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04,
    target: float = 0.0
) -> float:
    """Sortino ratio using downside deviation"""
    excess_returns = returns - risk_free_rate / 252
    downside_returns = returns[returns < target]
    downside_dev = downside_returns.std() * np.sqrt(252)
    return excess_returns.mean() * 252 / downside_dev
```

**Step 2: Time-Series Metrics (Days 4-5)**

**Rolling Statistics:**
1. 30-day rolling Sharpe
2. 90-day rolling volatility
3. Rolling correlation with benchmark
4. Drawdown duration analysis
5. Recovery period tracking

**Storage:**
```python
# Add to database
class PerformanceTimeSeries(Base):
    backtest_id: int
    date: datetime
    metric_name: str
    metric_value: Decimal
```

#### Integration Points

- **PerformanceAnalyzer**: Add new methods
- **Database**: Store time-series metrics
- **API**: Expose via `/api/v1/backtest/{id}/metrics`
- **CLI**: Add to backtest output

#### Acceptance Criteria

- [ ] 8 new metrics implemented
- [ ] Rolling metrics calculated correctly
- [ ] Performance: Metric calculation <1s for 1000 trades
- [ ] Stored in database with time-series
- [ ] Visualizable in reports
- [ ] >90% test coverage

---

### 2.5 Multiple Data Sources

**Priority:** LOW
**Complexity:** Moderate (2-3 weeks)
**Dependencies:** None

#### Implementation Steps

**Step 1: Data Source Abstraction (Week 1)**

**Create unified interface:**
```
jutsu_engine/data/fetchers/
├── yahoo.py         # Yahoo Finance fetcher
├── csv.py           # CSV file loader
├── polygon.py       # Polygon.io fetcher
└── alpha_vantage.py # Alpha Vantage fetcher
```

**Unified Fetcher Interface:**
```python
class DataFetcher(ABC):
    @abstractmethod
    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_available_symbols(self) -> List[str]:
        pass
```

**Step 2: Yahoo Finance Integration (Week 1)**

**Features:**
1. Free historical data (no API key needed)
2. Support for stocks, ETFs, indices
3. Dividend and split adjustment
4. Rate limiting and retry logic

**Implementation:**
```python
import yfinance as yf

class YahooDataFetcher(DataFetcher):
    def fetch_bars(self, symbol, timeframe, start, end):
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start,
            end=end,
            interval=self._convert_timeframe(timeframe)
        )
        return self._convert_to_bars(df)
```

**Step 3: CSV File Loader (Week 2)**

**Features:**
1. Support multiple CSV formats
2. Auto-detect column mappings
3. Date parsing with multiple formats
4. Data validation and cleaning

**Configuration:**
```yaml
csv_loader:
  column_mappings:
    timestamp: ['Date', 'Datetime', 'Time']
    open: ['Open', 'open']
    high: ['High', 'high']
    # ...
  date_formats:
    - '%Y-%m-%d'
    - '%m/%d/%Y'
    - '%Y-%m-%d %H:%M:%S'
```

**Step 4: Data Source Registry (Week 3)**

**Central registry for all sources:**
```python
class DataSourceRegistry:
    _sources: Dict[str, Type[DataFetcher]] = {}

    @classmethod
    def register(cls, name: str, fetcher: Type[DataFetcher]):
        cls._sources[name] = fetcher

    @classmethod
    def get(cls, name: str) -> DataFetcher:
        return cls._sources[name]()

# Usage
registry.register('schwab', SchwabDataFetcher)
registry.register('yahoo', YahooDataFetcher)
registry.register('csv', CSVDataFetcher)
```

#### Integration Points

- **DataSync**: Use registry for source selection
- **Config**: Add data source configuration
- **CLI**: Add `--source` flag to sync command
- **API**: Add source selection in endpoints

#### Acceptance Criteria

- [ ] 3 data sources implemented (Schwab, Yahoo, CSV)
- [ ] Unified interface for all sources
- [ ] Source priority and fallback logic
- [ ] Data quality validation across sources
- [ ] >85% test coverage
- [ ] Documentation for adding new sources

---

## Phase 3: UI & Distribution (Q2 2025)

**Duration:** ~12 weeks
**Complexity:** Moderate-High
**Dependencies:** Phase 2 Complete (API required)

### 3.1 Web Dashboard with Streamlit

**Priority:** HIGH
**Complexity:** Moderate (4-5 weeks)
**Dependencies:** REST API

#### Implementation Steps

**Step 1: Dashboard Foundation (Week 1)**

**Files to Create:**
```
jutsu_ui/
├── __init__.py
├── app.py                  # Main Streamlit app
├── pages/
│   ├── 1_📊_Backtests.py
│   ├── 2_📈_Analytics.py
│   ├── 3_⚙️_Strategies.py
│   └── 4_💾_Data.py
├── components/
│   ├── __init__.py
│   ├── charts.py           # Chart components
│   ├── metrics.py          # Metric displays
│   └── forms.py            # Input forms
└── utils/
    ├── api_client.py       # API wrapper
    └── theme.py            # Custom theme
```

**Step 2: Backtest Management Page (Week 2)**

**Features:**
1. Submit new backtest form
2. View running backtests
3. Historical backtest list
4. Cancel running backtests

**UI Components:**
```python
# Backtest form
with st.form("backtest_form"):
    symbol = st.selectbox("Symbol", available_symbols)
    strategy = st.selectbox("Strategy", available_strategies)
    date_range = st.date_input("Date Range", [start, end])
    capital = st.number_input("Initial Capital", value=100000)
    # Strategy parameters
    params = st.json_input("Parameters")
    submit = st.form_submit_button("Run Backtest")
```

**Step 3: Analytics Dashboard (Week 3)**

**Features:**
1. Interactive equity curve (Plotly)
2. Drawdown chart
3. Returns distribution histogram
4. Trade analysis table
5. Performance metrics cards
6. Comparison with benchmarks

**Charts:**
```python
# Equity curve with Plotly
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=equity_curve['date'],
    y=equity_curve['equity'],
    mode='lines',
    name='Strategy'
))
fig.add_trace(go.Scatter(
    x=benchmark['date'],
    y=benchmark['value'],
    mode='lines',
    name='Benchmark'
))
st.plotly_chart(fig)
```

**Step 4: Strategy Configuration Page (Week 4)**

**Features:**
1. List available strategies
2. View strategy parameters
3. Strategy documentation
4. Parameter validation
5. Save strategy configurations

**Step 5: Data Management Page (Week 5)**

**Features:**
1. Data availability calendar
2. Sync data by symbol/date range
3. Data quality reports
4. Database statistics
5. Export data functionality

#### Integration Points

- **REST API**: All data via API calls
- **Authentication**: JWT token management
- **WebSockets**: Real-time backtest updates (future)
- **Config**: Dashboard configuration file

#### Acceptance Criteria

- [ ] All 4 pages functional
- [ ] Responsive design (works on mobile)
- [ ] Real-time backtest status updates
- [ ] Interactive charts with zoom/pan
- [ ] <3s page load time
- [ ] Authentication working
- [ ] Error handling and user feedback
- [ ] >80% component test coverage

---

### 3.2 Docker Deployment

**Priority:** HIGH
**Complexity:** Moderate (2-3 weeks)
**Dependencies:** API, UI

#### Implementation Steps

**Step 1: Containerization (Week 1)**

**Files to Create:**
```
docker/
├── api.Dockerfile          # FastAPI container
├── ui.Dockerfile           # Streamlit container
├── worker.Dockerfile       # Background jobs
└── postgres.Dockerfile     # Database
```

**API Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY jutsu_engine/ ./jutsu_engine/
COPY jutsu_api/ ./jutsu_api/

CMD ["uvicorn", "jutsu_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Docker Compose (Week 2)**

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: jutsu_engine
      POSTGRES_USER: jutsu_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  api:
    build:
      context: .
      dockerfile: docker/api.Dockerfile
    environment:
      DATABASE_URL: postgresql://jutsu_user:${POSTGRES_PASSWORD}@postgres/jutsu_engine
      SCHWAB_API_KEY: ${SCHWAB_API_KEY}
    depends_on:
      - postgres
    ports:
      - "8000:8000"

  ui:
    build:
      context: .
      dockerfile: docker/ui.Dockerfile
    environment:
      API_URL: http://api:8000
    depends_on:
      - api
    ports:
      - "8501:8501"

  worker:
    build:
      context: .
      dockerfile: docker/worker.Dockerfile
    environment:
      DATABASE_URL: postgresql://jutsu_user:${POSTGRES_PASSWORD}@postgres/jutsu_engine
    depends_on:
      - postgres
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

**Step 3: Orchestration & Scaling (Week 3)**

**Features:**
1. Health checks for all services
2. Auto-restart policies
3. Resource limits
4. Logging configuration
5. Environment variable management

**Kubernetes deployment (optional):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jutsu-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: jutsu-api
  template:
    metadata:
      labels:
        app: jutsu-api
    spec:
      containers:
      - name: api
        image: jutsu/api:latest
        resources:
          limits:
            memory: "512Mi"
            cpu: "500m"
```

#### Integration Points

- **CI/CD**: GitHub Actions for Docker builds
- **Secrets Management**: Environment variables
- **Monitoring**: Prometheus + Grafana
- **Logs**: Centralized logging with ELK stack

#### Acceptance Criteria

- [ ] All services start with `docker-compose up`
- [ ] Health checks working for all services
- [ ] Data persistence across restarts
- [ ] Environment variables properly configured
- [ ] <30s startup time
- [ ] Documentation for deployment
- [ ] Backup and restore procedures documented

---

### 3.3 Scheduled Backtest Jobs

**Priority:** MEDIUM
**Complexity:** Moderate (2 weeks)
**Dependencies:** API, Background Worker

#### Implementation Steps

**Step 1: Job Queue System (Week 1)**

**Use Celery for background tasks:**
```
jutsu_worker/
├── __init__.py
├── celery_app.py           # Celery configuration
├── tasks/
│   ├── __init__.py
│   ├── backtest.py         # Backtest tasks
│   ├── data_sync.py        # Data sync tasks
│   └── optimization.py     # Optimization tasks
└── scheduler.py            # Scheduled job manager
```

**Celery Configuration:**
```python
from celery import Celery
from celery.schedules import crontab

app = Celery('jutsu_worker', broker='redis://localhost:6379/0')

app.conf.beat_schedule = {
    'daily-data-sync': {
        'task': 'tasks.data_sync.sync_all_symbols',
        'schedule': crontab(hour=22, minute=0),  # 10 PM daily
    },
    'weekly-backtest': {
        'task': 'tasks.backtest.run_weekly_backtests',
        'schedule': crontab(day_of_week=6, hour=10, minute=0),  # Saturday 10 AM
    },
}
```

**Step 2: Task Implementation (Week 1)**

**Backtest Task:**
```python
@app.task(bind=True)
def run_backtest(self, backtest_config: dict):
    """Run backtest as background task"""
    try:
        runner = BacktestRunner(**backtest_config)
        results = runner.run()

        # Store results
        db.store_backtest_results(results)

        # Send notification
        notify_user(backtest_config['user_id'], results)

        return results
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)
```

**Step 3: Scheduling API (Week 2)**

**Endpoints:**
1. POST `/api/v1/schedule/backtest` - Schedule recurring backtest
2. GET `/api/v1/schedule/jobs` - List scheduled jobs
3. DELETE `/api/v1/schedule/{job_id}` - Delete scheduled job
4. PATCH `/api/v1/schedule/{job_id}` - Update schedule

**Schedule Configuration:**
```python
class BacktestSchedule(BaseModel):
    name: str
    strategy: str
    symbols: List[str]
    cron_expression: str  # "0 10 * * 6" = Saturday 10 AM
    enabled: bool = True
```

#### Integration Points

- **API**: Schedule management endpoints
- **Database**: Store job configurations
- **Worker**: Execute scheduled tasks
- **Notifications**: Email/webhook on completion

#### Acceptance Criteria

- [ ] Jobs execute on schedule
- [ ] Failed jobs retry with backoff
- [ ] Job status monitoring
- [ ] Concurrent job execution (10+)
- [ ] Job logs stored and accessible
- [ ] UI for schedule management
- [ ] >85% test coverage for tasks

---

### 3.4 Monte Carlo Simulation

**Priority:** MEDIUM
**Complexity:** Moderate (2-3 weeks)
**Dependencies:** BacktestRunner, Optimization

#### Implementation Steps

**Step 1: Simulation Engine (Week 1)**

**Files to Create:**
```
jutsu_engine/simulation/
├── __init__.py
├── monte_carlo.py          # Main simulation engine
├── parameter_sampler.py    # Parameter sampling strategies
├── results_aggregator.py   # Aggregate simulation results
└── visualizer.py           # Simulation visualization
```

**Monte Carlo Engine:**
```python
class MonteCarloSimulator:
    def __init__(
        self,
        strategy_class: Type[Strategy],
        param_distributions: Dict[str, Distribution],
        n_simulations: int = 1000
    ):
        self.strategy_class = strategy_class
        self.param_distributions = param_distributions
        self.n_simulations = n_simulations

    def run_simulations(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> SimulationResults:
        """Run N simulations with random parameters"""
        results = []

        for i in range(self.n_simulations):
            # Sample parameters from distributions
            params = self._sample_parameters()

            # Run backtest with sampled parameters
            result = self._run_backtest(params, symbol, start_date, end_date)
            results.append(result)

        return SimulationResults(results)
```

**Step 2: Parameter Sampling (Week 1-2)**

**Distribution Types:**
```python
class ParameterDistribution:
    """Base class for parameter distributions"""
    pass

class UniformDistribution(ParameterDistribution):
    def __init__(self, min_val: float, max_val: float):
        self.min_val = min_val
        self.max_val = max_val

    def sample(self) -> float:
        return random.uniform(self.min_val, self.max_val)

class NormalDistribution(ParameterDistribution):
    def __init__(self, mean: float, std: float):
        self.mean = mean
        self.std = std

    def sample(self) -> float:
        return random.gauss(self.mean, self.std)
```

**Usage:**
```python
param_distributions = {
    'short_period': UniformDistribution(10, 50),
    'long_period': NormalDistribution(mean=100, std=20),
    'position_size': UniformDistribution(0.1, 1.0)
}
```

**Step 3: Results Analysis (Week 2)**

**Statistical Analysis:**
1. Mean and median returns
2. Confidence intervals (95%, 99%)
3. Probability of profit
4. Worst-case scenarios
5. Parameter sensitivity

**Visualization:**
```python
class SimulationVisualizer:
    def plot_return_distribution(self, results):
        """Histogram of returns across simulations"""

    def plot_confidence_intervals(self, results):
        """Equity curves with confidence bands"""

    def plot_parameter_sensitivity(self, results):
        """How parameters affect outcomes"""
```

**Step 4: Robustness Testing (Week 3)**

**Features:**
1. Out-of-sample validation with random walks
2. Noise injection in price data
3. Parameter perturbation analysis
4. Stress testing scenarios

**Stress Tests:**
```python
class StressTest:
    scenarios = [
        'market_crash': -20% sudden drop,
        'high_volatility': 3x normal volatility,
        'low_liquidity': sparse data,
        'regime_change': bull to bear transition
    ]
```

#### Integration Points

- **Optimization**: Use optimized parameters as distribution centers
- **API**: Add `/api/v1/simulate` endpoint
- **Database**: Store simulation results
- **UI**: Visualization dashboard

#### Acceptance Criteria

- [ ] 1000 simulations in <5 minutes (parallel)
- [ ] Statistical analysis complete
- [ ] Confidence intervals calculated
- [ ] Stress testing implemented
- [ ] Interactive visualizations
- [ ] Results reproducible with seed
- [ ] >85% test coverage

---

## Phase 4: Production Features (Q3-Q4 2025)

**Duration:** ~24 weeks
**Complexity:** High
**Dependencies:** Phase 3 Complete

### 4.1 Paper Trading Integration

**Priority:** HIGH
**Complexity:** High (6-8 weeks)
**Dependencies:** API, Real-time data integration

#### Implementation Steps

**Step 1: Paper Trading Engine (Week 1-2)**

**Files to Create:**
```
jutsu_engine/paper_trading/
├── __init__.py
├── engine.py               # Paper trading coordinator
├── order_manager.py        # Order lifecycle management
├── position_tracker.py     # Real-time position tracking
└── reconciliation.py       # Daily reconciliation
```

**Paper Trading Engine:**
```python
class PaperTradingEngine:
    def __init__(
        self,
        strategy: Strategy,
        initial_capital: Decimal,
        broker_simulator: BrokerSimulator
    ):
        self.strategy = strategy
        self.portfolio = PaperPortfolio(initial_capital)
        self.broker = broker_simulator

    async def run(self):
        """Run paper trading in real-time"""
        while self.is_running:
            # Get latest market data
            bar = await self.get_latest_bar()

            # Strategy generates signals
            signals = self.strategy.on_bar(bar)

            # Execute orders via simulated broker
            for signal in signals:
                order = self.create_order(signal)
                fill = await self.broker.submit_order(order)
                self.portfolio.update(fill)
```

**Step 2: Real-time Data Integration (Week 3-4)**

**Features:**
1. WebSocket connection to data provider
2. Real-time bar aggregation (1m, 5m, etc.)
3. Data validation and error handling
4. Fallback to polling if WebSocket fails

**Real-time Data Handler:**
```python
class RealtimeDataHandler:
    async def connect(self):
        """Connect to real-time data feed"""
        self.ws = await websockets.connect(self.ws_url)

    async def subscribe(self, symbols: List[str]):
        """Subscribe to symbols"""
        await self.ws.send(json.dumps({
            'action': 'subscribe',
            'symbols': symbols
        }))

    async def stream_bars(self) -> AsyncIterator[MarketDataEvent]:
        """Stream real-time bars"""
        async for message in self.ws:
            data = json.loads(message)
            yield self._parse_bar(data)
```

**Step 3: Order Simulation (Week 5-6)**

**Broker Simulator:**
1. Market order execution with realistic slippage
2. Limit order management
3. Order rejection scenarios
4. Partial fills
5. After-hours trading rules

**Fill Simulation:**
```python
class BrokerSimulator:
    def simulate_fill(
        self,
        order: OrderEvent,
        current_bar: MarketDataEvent
    ) -> Optional[FillEvent]:
        """Simulate realistic order fills"""

        # Market orders: fill at bid/ask with slippage
        if order.order_type == 'market':
            fill_price = self._calculate_fill_price(
                order, current_bar, slippage=0.001
            )
            return FillEvent(
                symbol=order.symbol,
                quantity=order.quantity,
                fill_price=fill_price,
                commission=self._calculate_commission(order)
            )

        # Limit orders: check if price reached
        elif order.order_type == 'limit':
            if self._limit_reached(order, current_bar):
                return self._create_fill(order)
            return None
```

**Step 4: Risk Management (Week 7)**

**Safety Features:**
1. Maximum position size limits
2. Daily loss limits (stop all trading)
3. Maximum drawdown thresholds
4. Order size validation
5. Symbol whitelist/blacklist

**Risk Manager:**
```python
class RiskManager:
    def validate_order(self, order: OrderEvent) -> Tuple[bool, str]:
        """Validate order against risk rules"""

        # Check position size
        if self._exceeds_position_limit(order):
            return False, "Exceeds maximum position size"

        # Check daily loss limit
        if self._exceeds_daily_loss_limit():
            return False, "Daily loss limit reached"

        # Check account equity
        if self._insufficient_capital(order):
            return False, "Insufficient capital"

        return True, "OK"
```

**Step 5: Monitoring & Alerts (Week 8)**

**Features:**
1. Real-time performance dashboard
2. Email/SMS alerts on triggers
3. Trade execution logs
4. Daily performance reports
5. Error notifications

**Alert System:**
```python
class AlertManager:
    triggers = [
        'position_opened',
        'position_closed',
        'daily_loss_limit',
        'max_drawdown_reached',
        'execution_error'
    ]

    async def send_alert(self, trigger: str, data: dict):
        """Send alert via configured channels"""
        if 'email' in self.channels:
            await self._send_email(trigger, data)
        if 'sms' in self.channels:
            await self._send_sms(trigger, data)
```

#### Integration Points

- **Strategy**: Use existing strategy framework
- **Portfolio**: Enhanced portfolio tracking
- **Database**: Store paper trading results
- **API**: Paper trading control endpoints
- **UI**: Real-time monitoring dashboard

#### Acceptance Criteria

- [ ] Real-time data streaming working
- [ ] Order simulation realistic (tested against live data)
- [ ] Risk management enforced
- [ ] <100ms latency from signal to order
- [ ] Alert system functional
- [ ] Reconciliation matches expected results
- [ ] >90% test coverage
- [ ] 24/7 uptime capability
- [ ] Comprehensive error handling

---

### 4.2 Advanced Risk Management

**Priority:** HIGH
**Complexity:** Moderate (3-4 weeks)
**Dependencies:** Paper Trading

#### Implementation Steps

**Step 1: Position Sizing Algorithms (Week 1)**

**Files to Create:**
```
jutsu_engine/risk/
├── __init__.py
├── position_sizer.py       # Position sizing strategies
├── portfolio_heat.py       # Portfolio heat management
├── correlation.py          # Cross-asset correlation
└── var_calculator.py       # Value at Risk
```

**Position Sizing Strategies:**
```python
class PositionSizer(ABC):
    @abstractmethod
    def calculate_size(
        self,
        signal: SignalEvent,
        portfolio: Portfolio,
        risk_params: RiskParameters
    ) -> int:
        pass

class FixedFractionalSizer(PositionSizer):
    """Risk fixed % of capital per trade"""
    def calculate_size(self, signal, portfolio, risk_params):
        risk_amount = portfolio.equity * risk_params.risk_per_trade
        stop_distance = signal.price - signal.stop_loss
        position_size = risk_amount / stop_distance
        return int(position_size)

class KellyPositionSizer(PositionSizer):
    """Kelly Criterion for optimal sizing"""
    def calculate_size(self, signal, portfolio, risk_params):
        win_rate = self._calculate_win_rate(signal.strategy)
        avg_win = self._calculate_avg_win(signal.strategy)
        avg_loss = self._calculate_avg_loss(signal.strategy)

        kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        kelly_fraction = kelly * risk_params.kelly_multiplier  # Use fraction of Kelly

        return int(portfolio.equity * kelly_fraction / signal.price)
```

**Step 2: Portfolio Heat Management (Week 2)**

**Features:**
1. Maximum correlated risk exposure
2. Sector concentration limits
3. Cross-asset correlation analysis
4. Dynamic position sizing based on portfolio heat

**Portfolio Heat:**
```python
class PortfolioHeatManager:
    def calculate_portfolio_heat(self, portfolio: Portfolio) -> float:
        """
        Portfolio heat = Sum of all position risks
        Target: <20% of total capital at risk
        """
        total_risk = Decimal('0')

        for position in portfolio.positions.values():
            risk = self._calculate_position_risk(position)
            total_risk += risk

        return float(total_risk / portfolio.equity)

    def can_add_position(
        self,
        new_position_risk: Decimal,
        max_heat: float = 0.20
    ) -> bool:
        """Check if adding position exceeds heat limit"""
        current_heat = self.calculate_portfolio_heat(self.portfolio)
        new_heat = current_heat + float(new_position_risk / self.portfolio.equity)
        return new_heat <= max_heat
```

**Step 3: Value at Risk (VaR) (Week 3)**

**VaR Calculation Methods:**
1. Historical VaR (based on past returns)
2. Parametric VaR (assumes normal distribution)
3. Monte Carlo VaR (simulation-based)

**Implementation:**
```python
class VaRCalculator:
    def calculate_historical_var(
        self,
        returns: pd.Series,
        confidence_level: float = 0.95,
        horizon_days: int = 1
    ) -> Decimal:
        """Calculate VaR using historical returns"""
        var_percentile = 1 - confidence_level
        var_value = returns.quantile(var_percentile)
        return Decimal(str(var_value)) * np.sqrt(horizon_days)

    def calculate_cvar(
        self,
        returns: pd.Series,
        confidence_level: float = 0.95
    ) -> Decimal:
        """Conditional VaR (expected shortfall)"""
        var_value = self.calculate_historical_var(returns, confidence_level)
        tail_returns = returns[returns <= float(var_value)]
        return Decimal(str(tail_returns.mean()))
```

**Step 4: Stop Loss & Take Profit (Week 4)**

**Features:**
1. ATR-based stop loss
2. Trailing stops
3. Break-even stops
4. Profit target ladders

**Stop Loss Manager:**
```python
class StopLossManager:
    def calculate_atr_stop(
        self,
        entry_price: Decimal,
        atr: Decimal,
        multiplier: float = 2.0,
        direction: str = 'long'
    ) -> Decimal:
        """ATR-based stop loss"""
        if direction == 'long':
            stop = entry_price - (atr * Decimal(str(multiplier)))
        else:
            stop = entry_price + (atr * Decimal(str(multiplier)))
        return stop

    def update_trailing_stop(
        self,
        current_price: Decimal,
        entry_price: Decimal,
        current_stop: Decimal,
        trailing_pct: Decimal
    ) -> Decimal:
        """Update trailing stop if price moves favorably"""
        # Calculate potential new stop
        new_stop = current_price * (Decimal('1') - trailing_pct)

        # Only move stop up, never down
        if new_stop > current_stop:
            return new_stop
        return current_stop
```

#### Integration Points

- **Strategy**: Position sizing integration
- **Portfolio**: Risk metrics tracking
- **Paper Trading**: Live risk management
- **Database**: Store risk metrics
- **API**: Risk analytics endpoints

#### Acceptance Criteria

- [ ] Multiple position sizing algorithms
- [ ] Portfolio heat <20% enforced
- [ ] VaR calculated daily
- [ ] Stop losses managed automatically
- [ ] Risk metrics in real-time
- [ ] >90% test coverage
- [ ] Backtested against historical crashes

---

### 4.3 Live Trading (EXTREME CAUTION)

**Priority:** LOW
**Complexity:** Very High (8-10 weeks)
**Dependencies:** Paper Trading validated for 3+ months

⚠️ **WARNING**: Live trading involves REAL MONEY and REAL RISK. Only implement after:
1. Paper trading validated for minimum 3 months
2. Comprehensive testing in all market conditions
3. Legal and regulatory compliance verified
4. User acceptance of risk disclosures
5. Insurance/safeguards in place

#### Implementation Steps

**Step 1: Broker Integration (Week 1-3)**

**Supported Brokers:**
1. Interactive Brokers (IBKR API)
2. Alpaca (Commission-free API)
3. TD Ameritrade (via Schwab)

**Files to Create:**
```
jutsu_engine/brokers/
├── __init__.py
├── base.py                 # Broker interface
├── ibkr.py                 # Interactive Brokers
├── alpaca.py               # Alpaca integration
└── schwab.py               # Schwab/TD Ameritrade
```

**Broker Interface:**
```python
class Broker(ABC):
    @abstractmethod
    async def connect(self, credentials: dict) -> bool:
        """Establish connection to broker"""

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Retrieve account information"""

    @abstractmethod
    async def submit_order(self, order: OrderEvent) -> str:
        """Submit order, return order ID"""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order"""

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Get current positions"""
```

**Step 2: Safety Mechanisms (Week 4-5)**

**Multi-Layer Safety:**
1. **Pre-trade validation**: Order size, account balance, market hours
2. **Circuit breakers**: Stop all trading on anomalies
3. **Kill switch**: Manual emergency stop
4. **Reconciliation**: Verify broker positions match internal state
5. **Audit logging**: Every action logged immutably

**Safety System:**
```python
class LiveTradingSafetySystem:
    def __init__(self):
        self.enabled = True
        self.circuit_breakers = [
            MaxDailyLossBreaker(threshold=0.05),  # 5% daily loss
            MaxDrawdownBreaker(threshold=0.10),   # 10% drawdown
            OrderRateBreaker(max_orders_per_min=10),
            AccountBalanceBreaker(min_balance=1000)
        ]

    async def validate_order(self, order: OrderEvent) -> Tuple[bool, str]:
        """Validate order through all safety checks"""

        # Check if live trading is enabled
        if not self.enabled:
            return False, "Live trading disabled"

        # Check all circuit breakers
        for breaker in self.circuit_breakers:
            passed, reason = await breaker.check(order)
            if not passed:
                await self.trigger_circuit_breaker(breaker, reason)
                return False, reason

        # Final confirmation
        return True, "OK"

    async def trigger_circuit_breaker(self, breaker, reason):
        """Circuit breaker triggered - STOP EVERYTHING"""
        self.enabled = False
        await self.cancel_all_orders()
        await self.close_all_positions()  # Optional
        await self.send_emergency_alert(breaker, reason)
```

**Step 3: Order Execution (Week 6-7)**

**Features:**
1. Smart order routing
2. Order retry logic with exponential backoff
3. Partial fill handling
4. Slippage tracking
5. Execution quality metrics

**Order Executor:**
```python
class LiveOrderExecutor:
    async def execute_order(
        self,
        order: OrderEvent,
        max_retries: int = 3
    ) -> FillEvent:
        """Execute order with retries and error handling"""

        for attempt in range(max_retries):
            try:
                # Validate order through safety system
                safe, reason = await self.safety_system.validate_order(order)
                if not safe:
                    raise OrderRejected(reason)

                # Submit to broker
                order_id = await self.broker.submit_order(order)

                # Wait for fill confirmation
                fill = await self.wait_for_fill(order_id, timeout=30)

                # Reconcile with broker
                await self.reconcile_fill(fill)

                return fill

            except Exception as e:
                logger.error(f"Order execution failed (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise
```

**Step 4: Monitoring & Reconciliation (Week 8)**

**Features:**
1. Real-time position reconciliation (every 1 minute)
2. End-of-day full reconciliation
3. Discrepancy detection and alerts
4. Automatic error correction (when safe)

**Reconciliation:**
```python
class Reconciliator:
    async def reconcile_positions(self):
        """Reconcile internal positions with broker"""

        # Get positions from broker
        broker_positions = await self.broker.get_positions()

        # Compare with internal state
        discrepancies = []
        for symbol, internal_pos in self.portfolio.positions.items():
            broker_pos = broker_positions.get(symbol)

            if broker_pos is None:
                discrepancies.append({
                    'symbol': symbol,
                    'type': 'missing_at_broker',
                    'internal': internal_pos,
                    'broker': None
                })
            elif internal_pos.quantity != broker_pos.quantity:
                discrepancies.append({
                    'symbol': symbol,
                    'type': 'quantity_mismatch',
                    'internal': internal_pos,
                    'broker': broker_pos
                })

        # Handle discrepancies
        if discrepancies:
            await self.handle_discrepancies(discrepancies)
```

**Step 5: Legal & Compliance (Week 9-10)**

**Requirements:**
1. Terms of Service and Risk Disclosure
2. User must explicitly enable live trading
3. Minimum account balance requirements
4. Trading hours restrictions
5. Symbol restrictions (no penny stocks, etc.)
6. Audit trail for regulatory compliance

**User Agreement:**
```python
class LiveTradingAgreement:
    def enable_live_trading(self, user_id: str) -> bool:
        """Enable live trading after user acceptance"""

        # Check requirements
        requirements = [
            self._verify_identity(user_id),
            self._verify_broker_connection(user_id),
            self._verify_minimum_balance(user_id, min_balance=5000),
            self._verify_risk_disclosure_signed(user_id),
            self._verify_paper_trading_history(user_id, min_months=3)
        ]

        if not all(requirements):
            return False

        # Log legal acceptance
        self._log_legal_acceptance(user_id)

        # Enable with caution
        self._enable_live_trading_for_user(user_id)
        return True
```

#### Integration Points

- **Paper Trading**: Transition from paper to live
- **Risk Management**: All risk controls active
- **Monitoring**: Real-time alerts
- **Database**: Audit logging
- **API**: Live trading control (with MFA)

#### Acceptance Criteria

- [ ] Broker integration tested extensively
- [ ] All safety mechanisms validated
- [ ] Circuit breakers trigger correctly
- [ ] Reconciliation accurate 100%
- [ ] Legal compliance verified
- [ ] Insurance/liability addressed
- [ ] >95% test coverage
- [ ] Passed independent security audit
- [ ] 3+ months paper trading success
- [ ] User risk disclosure mandatory

---

## Implementation Order & Dependencies

### Phase 2 Dependency Graph

```
Phase 2 (12 weeks)
│
├─ Week 1-4: REST API (INDEPENDENT)
│   └─ Enables: Remote access, UI development
│
├─ Week 1-2: PostgreSQL (INDEPENDENT)
│   └─ Enables: Scalability, multi-user
│
├─ Week 2-6: Parameter Optimization (DEPENDS: BacktestRunner)
│   └─ Enables: Strategy improvement, walk-forward
│
├─ Week 7: Advanced Metrics (INDEPENDENT)
│   └─ Enables: Better performance analysis
│
└─ Week 8-10: Multiple Data Sources (INDEPENDENT)
    └─ Enables: Data redundancy, cost savings
```

**Recommended Order:**
1. **Weeks 1-4**: REST API (enables frontend development)
2. **Weeks 1-2**: PostgreSQL (can run parallel with API)
3. **Weeks 5-9**: Parameter Optimization (depends on stable API)
4. **Week 10**: Advanced Metrics (quick win)
5. **Weeks 11-12**: Multiple Data Sources (polish)

### Phase 3 Dependency Graph

```
Phase 3 (12 weeks)
│
├─ Week 1-5: Web Dashboard (DEPENDS: REST API ✅)
│   └─ Enables: User-friendly interface
│
├─ Week 6-8: Docker Deployment (DEPENDS: API ✅, UI ✅)
│   └─ Enables: Easy deployment, scaling
│
├─ Week 9-10: Scheduled Jobs (DEPENDS: API ✅, Docker)
│   └─ Enables: Automation, recurring backtests
│
└─ Week 11-12: Monte Carlo (DEPENDS: Optimization ✅)
    └─ Enables: Robustness testing, confidence intervals
```

**Recommended Order:**
1. **Weeks 1-5**: Web Dashboard (UI is high value)
2. **Weeks 6-8**: Docker Deployment (enables production)
3. **Weeks 9-10**: Scheduled Jobs (automation value)
4. **Weeks 11-12**: Monte Carlo (final enhancement)

### Phase 4 Dependency Graph

```
Phase 4 (24 weeks)
│
├─ Week 1-8: Paper Trading (DEPENDS: API ✅, Real-time data)
│   └─ Enables: Strategy validation, live testing
│
├─ Week 9-12: Advanced Risk (DEPENDS: Paper Trading)
│   └─ Enables: Professional risk management
│
└─ Week 13-24: Live Trading (DEPENDS: Paper Trading ✅ for 3+ months)
    └─ Enables: Real money trading (EXTREME CAUTION)
```

**Recommended Order:**
1. **Weeks 1-8**: Paper Trading (critical prerequisite)
2. **Weeks 9-12**: Advanced Risk Management (test in paper)
3. **Weeks 13-15**: PAUSE and VALIDATE (3+ months paper trading)
4. **Weeks 16-24**: Live Trading (if paper trading successful)

---

## Technical Stack Additions

### Phase 2
- **FastAPI**: REST API framework
- **Celery**: Background task queue
- **Redis**: Task broker, caching
- **PostgreSQL**: Production database
- **Alembic**: Database migrations

### Phase 3
- **Streamlit**: Web dashboard
- **Plotly**: Interactive charts
- **Docker**: Containerization
- **Docker Compose**: Multi-container orchestration
- **Nginx**: Reverse proxy (optional)

### Phase 4
- **AsyncIO**: Asynchronous programming
- **WebSockets**: Real-time data streaming
- **IBKR/Alpaca SDK**: Broker integration
- **APScheduler**: Advanced scheduling

---

## Risk Assessment

### Phase 2 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| API performance issues | Medium | High | Load testing, caching |
| Optimization too slow | Medium | Medium | Profiling, parallelization |
| PostgreSQL migration data loss | Low | Critical | Backup, validation |

### Phase 3 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| UI complexity overwhelming | Medium | Medium | Start simple, iterate |
| Docker networking issues | Low | Medium | Thorough testing |
| Real-time data unreliable | High | High | Fallback mechanisms |

### Phase 4 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Live trading losses | High | CRITICAL | Extensive paper trading, safety systems |
| Broker API failures | Medium | High | Retry logic, fallbacks |
| Legal/compliance issues | Low | Critical | Legal review, insurance |

---

## Success Metrics

### Phase 2
- [ ] API: 10,000 requests/day with <200ms response
- [ ] Optimization: 1000 backtests in <10 minutes
- [ ] PostgreSQL: 10M+ bars with <1s queries
- [ ] Multiple sources: 3+ data providers working

### Phase 3
- [ ] Dashboard: 100+ active users
- [ ] Docker: <30s startup, 99.9% uptime
- [ ] Scheduled jobs: 100+ jobs/day executed
- [ ] Monte Carlo: 1000 simulations in <5 minutes

### Phase 4
- [ ] Paper trading: 30+ days without errors
- [ ] Risk management: 0 rule violations
- [ ] Live trading: Net positive after 6+ months
- [ ] User satisfaction: >90% positive feedback

---

## Conclusion

This implementation plan provides a **comprehensive roadmap** for Phases 2-4 of Jutsu Labs. Each phase builds incrementally on previous work while maintaining backward compatibility.

**Key Principles:**
1. **Incremental delivery** with independent features
2. **Test-driven development** throughout
3. **Documentation first** before implementation
4. **Security and safety** as top priorities
5. **User feedback** drives priorities

**Next Steps:**
1. Review and approve Phase 2 priorities
2. Set up project tracking (GitHub Projects/Jira)
3. Begin with REST API implementation
4. Maintain regular progress reviews

---

**Maintainers:**
- Anil Goparaju
- Padma Priya Garnepudi

**License:** MIT
