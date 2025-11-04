```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   ███████╗████████╗ ██████╗ ██████╗     ██╗   ██╗██╗   ██╗ ██████╗ ██╗     ║
║   ██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗    ██║   ██║██║   ██║██╔═══██╗██║     ║
║   ███████╗   ██║   ██║   ██║██████╔╝    ██║   ██║██║   ██║██║   ██║██║     ║
║   ╚════██║   ██║   ██║   ██║██╔═══╝     ╚██╗ ██╔╝██║   ██║██║   ██║██║     ║
║   ███████║   ██║   ╚██████╔╝██║          ╚████╔╝ ╚██████╔╝╚██████╔╝███████╗║
║   ╚══════╝   ╚═╝    ╚═════╝ ╚═╝           ╚═══╝   ╚═════╝  ╚═════╝ ╚══════╝║
║                                                                               ║
║                    ⛔ MANDATORY WORKFLOW ENFORCEMENT ⛔                        ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

# 🛡️ WORKFLOW GUARD - MANDATORY READING REQUIRED

**⚠️ STOP: Before ANY work on Jutsu-Labs, you MUST:**

1. ✅ **READ**: `.claude/WORKFLOW_GUARD.md` (REQUIRED every session start)
2. ✅ **ACKNOWLEDGE**: "I have read WORKFLOW_GUARD.md and will follow the mandatory workflow"
3. ✅ **ROUTE ALL WORK**: Through `/orchestrate <description>` - NO EXCEPTIONS

---

## 🔴 THE RULE (No Exceptions)

**ALL Jutsu-Labs code modifications MUST go through `/orchestrate`**

### What This Means

- ❌ NO direct use of Edit/Write/MultiEdit tools on Jutsu-Labs code files
- ❌ NO "quick fixes" or "simple changes" without `/orchestrate`
- ❌ NO bypassing agent architecture "just this once"
- ✅ ALWAYS use: `/orchestrate <task description>` for ALL code changes

### Why This Rule Exists

When you bypass `/orchestrate`:
1. **Context Loss**: Agent context files (`.md` files) contain module-specific knowledge you don't have loaded
2. **Architecture Violations**: Dependency rules and boundaries go unenforced
3. **Knowledge Gaps**: Fixes don't accumulate in Serena memories for future sessions
4. **Validation Failures**: Multi-level validation chains are broken
5. **Pattern Inconsistency**: Established module patterns are ignored

---

## ✅ Approved Tools for Information Gathering

**These tools are OK to use directly** (non-modifying operations):
- ✅ **Read**: View files for context
- ✅ **Grep**: Search for patterns
- ✅ **Glob**: Find files
- ✅ **Bash**: Run tests, git commands (non-modifying)
- ✅ **TodoWrite**: Track your tasks

**These tools require `/orchestrate`** (modifying operations):
- ⛔ **Edit**: ONLY via `/orchestrate`
- ⛔ **Write**: ONLY via `/orchestrate`
- ⛔ **MultiEdit**: ONLY via `/orchestrate`

---

## 📋 Required Acknowledgment (State This Every Session)

> "I have read WORKFLOW_GUARD.md. I understand that ALL Jutsu-Labs work MUST use `/orchestrate`. I will not use Edit/Write/MultiEdit directly on any Jutsu-Labs code files."

---

## 🚨 If You're Tempted to Bypass

**STOP and ask yourself:**
- [ ] Am I thinking "this is too simple for `/orchestrate`"? → ⛔ WRONG
- [ ] Am I thinking "I'll just quickly fix this"? → ⛔ WRONG
- [ ] Am I thinking "I already know the fix"? → ⛔ WRONG
- [ ] Am I about to use Edit/Write/MultiEdit directly? → ⛔ STOP

**Correct Response**: Always use `/orchestrate <description>` instead

---

## 📖 Full Details

See `.claude/WORKFLOW_GUARD.md` for:
- Complete pre-flight checklist
- Red flags indicating bypass temptation
- Detailed explanation of agent architecture
- Tool usage matrix
- Success criteria and metrics

---

# Claude Code Project Context - Jutsu Labs Backtesting Engine

> Essential project information for AI assistants working on this codebase

**Project Name:** Jutsu Labs - Modular Backtesting Engine
**Version:** 0.1.0 (MVP Phase)
**Last Updated:** October 31, 2025

---

## Quick Start for Claude Code

### Project Overview

**What is Jutsu Labs?**
A modular, database-backed backtesting engine for trading strategies. Think "lightweight, flexible Zipline alternative" focused on modularity and data integrity.

**Key Characteristics:**
- **Hexagonal Architecture**: Clean separation of business logic from infrastructure
- **Database-First Data**: Store once, backtest many times (no repeated API calls)
- **Event-Driven**: Bar-by-bar processing prevents lookback bias
- **Plugin System**: Drop-in strategies, indicators, and data sources
- **Financial Precision**: `Decimal` for calculations, immutable data, audit trails

**Current Status:** MVP Phase 1 (Documentation + Structure Complete, Core Implementation In Progress)

---

## Multi-Agent Architecture System

**For AI Development Assistance**: This project uses a hierarchical multi-agent system to manage development as complexity grows.

### Agent Hierarchy Overview
```
System Orchestrator (Level 0)
├─ Logging Orchestrator (Cross-cutting)
├─ Validation Orchestrator (Cross-cutting)
├─ Core Orchestrator (Layer 1)
│   ├─ EventLoop Agent
│   ├─ Portfolio Agent
│   ├─ Strategy Agent
│   └─ Events Agent
├─ Application Orchestrator (Layer 2)
│   ├─ BacktestRunner Agent
│   └─ DataSync Agent
└─ Infrastructure Orchestrator (Layer 3)
    ├─ DatabaseHandler Agent
    ├─ SchwabFetcher Agent
    ├─ Indicators Agent
    └─ Performance Agent
```

### How to Use the Agent System

**Automatic Routing** (Recommended):
Just describe what you want - the system auto-routes to the appropriate agent:
```
"Fix bug in EventLoop" → CORE/EVENT_LOOP_AGENT
"Optimize backtest performance" → APP/BACKTEST_RUNNER_AGENT
"Add Schwab API retry logic" → INFRA/SCHWAB_FETCHER_AGENT
```

**Manual Routing** (For Precision):
Use explicit agent commands when you need control:
```
/agent core/event-loop "add feature X"
/agent logging "update format"
/agent validation "run full suite"
```

**Validation Before Commit**:
```
"Run full validation before commit"
# or
/validate full
```

### Agent Context Documents

Each agent has a dedicated context document with detailed information:

**System Level**:
- `.claude/system/SYSTEM_ORCHESTRATOR.md` - Overall architecture and coordination
- `.claude/system/LOGGING_ORCHESTRATOR.md` - Logging standards and coordination
- `.claude/system/VALIDATION_ORCHESTRATOR.md` - Quality gates and validation
- `.claude/system/ROUTING_GUIDE.md` - How to activate and use agents

**Layer Orchestrators**:
- `.claude/layers/core/CORE_ORCHESTRATOR.md` - Core domain coordination
- `.claude/layers/application/APPLICATION_ORCHESTRATOR.md` - Use case coordination
- `.claude/layers/infrastructure/INFRASTRUCTURE_ORCHESTRATOR.md` - Technical services coordination

**Module Agents** (Example):
- `.claude/layers/core/modules/EVENT_LOOP_AGENT.md` - EventLoop module specialist
- See `MODULE_AGENT_TEMPLATE.md` for creating additional module agents

### Agent Responsibilities

**System Orchestrator**:
- System-wide architecture decisions
- Cross-layer coordination
- Strategic planning
- Assigns tasks to layer orchestrators

**Layer Orchestrators**:
- Coordinate module agents within their layer
- Enforce layer-specific constraints
- Review code for architecture compliance
- **Do NOT write code** (only review and coordinate)

**Module Agents**:
- Implement specific modules
- Write and maintain code
- Report to layer orchestrator
- Maintain module-specific context

**Cross-Cutting Orchestrators**:
- Logging: Manage logging standards across all layers
- Validation: Enforce quality gates and validation workflows

### When to Use Agents

Use the agent system when:
- Working on complex multi-module features
- Need architectural guidance
- Changing interfaces between layers
- Implementing new modules
- Running validation workflows

For simple single-file changes, you may work directly without explicit agent routing.

### Quick Reference

**Routing Guide**: See `.claude/system/ROUTING_GUIDE.md` for complete routing documentation

**Agent Activation**: Agents auto-activate based on keywords or use manual `/agent` commands

**Validation**: Two-tier system (fast layer validation + comprehensive system validation)

---

## Autonomous Orchestration System

**For AI Development Assistance**: This project has a fully autonomous orchestration system that can handle ANY development task from a high-level description.

### The /orchestrate Command

**Universal Task Handler**: One command for all development tasks - implementation, debugging, refactoring, analysis, optimization.

```bash
# Implementation tasks
/orchestrate implement layer/core
/orchestrate implement module/portfolio
/orchestrate implement system

# Debugging tasks
/orchestrate fix bug in EventLoop, check logs/error.log
/orchestrate debug performance issue in Portfolio

# Refactoring tasks
/orchestrate refactor Core layer for better performance
/orchestrate cleanup code in Portfolio module

# Analysis tasks
/orchestrate analyze system security
/orchestrate review architecture quality

# Optimization tasks
/orchestrate optimize Portfolio module performance
```

### How It Works

**Autonomous Hierarchical Execution**:
1. **Auto-Detection**: Automatically detects task type from your description
2. **Hierarchical Decomposition**: Breaks down into System → Layer → Module → Task agents
3. **Parallel Execution**: Modules within layers execute concurrently
4. **Dependency-Aware**: Executes layers sequentially based on architecture dependencies
5. **Automatic Documentation**: Updates CHANGELOG.md and docs after every operation
6. **Zero Manual Intervention**: Fully autonomous from description to completion

**Execution Flow**:
```
User: "/orchestrate implement layer/core"
    ↓
System Orchestrator reads SYSTEM_ORCHESTRATOR.md
    ↓
Reads CORE_ORCHESTRATOR.md for layer plan
    ↓
Identifies modules: Events, EventLoop, Portfolio, Strategy
    ↓
Creates dependency waves:
  Wave 1: Events (no dependencies)
  Wave 2: EventLoop, Portfolio, Strategy (depend on Events)
    ↓
Spawns Task agents in parallel for each module (FULL MCP access)
    ↓
Each Task agent:
  - Reads module specification from agent .md file
  - Implements module with tests (>80% coverage)
  - Validates performance targets
  - Reports completion
    ↓
Layer validation: Tests, interfaces, performance
    ↓
Documentation update: CHANGELOG.md, README.md, etc.
    ↓
Reports completion with evidence
```

### Full SuperClaude MCP Integration

**Every orchestration uses FULL MCP capabilities**:

**At Orchestrator Level** (Claude Code):
- ✅ **TodoWrite**: Tracks progress across all phases
- ✅ **Sequential MCP**: Task decomposition and dependency analysis
- ✅ **Context7 MCP**: Framework patterns and best practices
- ✅ **Serena MCP**: Checkpoint/resume functionality and memory
- ✅ **Morphllm MCP**: Large-scale code analysis

**At Task Agent Level** (Autonomous agents):
- ✅ **ALL MCP servers**: Every Task agent gets full SuperClaude MCP access
- ✅ **Context7**: Look up official documentation and patterns
- ✅ **Sequential**: Complex logic and systematic analysis
- ✅ **Serena**: Read project memories and context
- ✅ **All tools**: Read, Write, Edit, Grep, Bash

### Automatic Documentation Updates

**DOCUMENTATION_ORCHESTRATOR** automatically updates documentation after every operation:

**CHANGELOG.md Updates**:
```markdown
### Added (After Implementation)
- **Portfolio Module**: State management and trade execution
  - Position tracking with Decimal precision
  - Commission and slippage modeling
  - Performance: <0.1ms per order ✅
  - Test coverage: 91% ✅

### Fixed (After Bug Fix)
- **EventLoop Module**: Fixed performance degradation
  - Root cause: Memory loading issue
  - Resolution: Generator pattern implementation
  - Performance improvement: 3x faster

### Changed (After Refactoring)
- **Core Layer**: Performance optimization
  - EventLoop: Reduced processing time by 40%
  - Portfolio: Optimized position tracking
```

**Other Documentation**:
- **README.md**: Updated for major features
- **SYSTEM_DESIGN.md**: Updated for architecture changes
- **API_REFERENCE.md**: Updated for interface changes

### Task Types Supported

**Implementation** (implement|create|build):
- System-level: All layers in dependency order
- Layer-level: All modules within a layer
- Module-level: Single module with tests
- Hierarchical execution with validation

**Debugging** (debug|fix|troubleshoot):
- Log analysis → Root cause diagnosis → Fix → Validation
- Systematic hypothesis testing with Sequential MCP
- Regression tests added automatically
- CHANGELOG.md updated with fix details

**Refactoring** (refactor|improve|cleanup):
- Code analysis → Improvement planning → Implementation → Validation
- Performance optimization and quality improvements
- Architecture compliance verification
- Documentation updates

**Analysis** (analyze|review|audit):
- Security, quality, architecture, or performance analysis
- Comprehensive reporting with evidence
- No code changes (analysis only)
- Recommendations for improvements

**Optimization** (optimize|speed up):
- Performance profiling → Bottleneck identification → Optimization → Validation
- Performance metrics validation
- No degradation in other dimensions

### Scope Levels

**System Level** (All layers in order):
```bash
/orchestrate implement system
# Implements: Core → Application → Infrastructure → Entry Points
```

**Layer Level**:
```bash
/orchestrate implement layer/core
/orchestrate implement layer/application
/orchestrate implement layer/infrastructure
```

**Module Level**:
```bash
/orchestrate implement module/portfolio
/orchestrate implement module/event-loop
```

**Custom** (Auto-detected):
```bash
/orchestrate fix bug in EventLoop
/orchestrate analyze security
```

### Performance & Quality

**Performance Targets**:
- Command startup: <100ms
- Planning phase: <500ms
- Per module: 2-5 minutes
- Per layer: 10-20 minutes
- Full system: 60-90 minutes

**Quality Gates** (Automatic):
1. **Module-level**: Unit tests, type hints, logging
2. **Layer-level**: Interface compatibility, dependencies
3. **System-level**: Integration tests, end-to-end flow
4. **Documentation**: CHANGELOG.md, README.md synchronized

**Parallelization**:
- Modules within layer: **PARALLEL**
- Layers: **SEQUENTIAL** (dependency order)
- Task agents: **CONCURRENT**

### Examples

**Example 1: Implement Core Layer (~15 min)**:
```bash
/orchestrate implement layer/core
```
Result:
- 4 modules implemented (Events, EventLoop, Portfolio, Strategy)
- 83 tests, 94% coverage
- CHANGELOG.md updated with all modules
- README.md updated with features

**Example 2: Debug Bug (~5 min)**:
```bash
/orchestrate fix bug in EventLoop, check logs/error.log
```
Result:
- Root cause identified (memory loading issue)
- Fix implemented (generator pattern)
- Regression test added
- Performance improved 3x
- CHANGELOG.md updated with fix details

**Example 3: Full System (~60 min)**:
```bash
/orchestrate implement system
```
Result:
- All 4 layers implemented
- 11 modules, 190 tests, 92% coverage
- 12 integration tests
- 2 example scripts
- Complete CHANGELOG.md and documentation

### Status & Resume

**Check Progress**:
```bash
/orchestrate status
```

**Resume After Interruption**:
```bash
/orchestrate resume
```
Reads Serena checkpoint and continues from last incomplete task.

### Integration with Existing Agents

Uses ALL existing agent structure:
- ✅ SYSTEM_ORCHESTRATOR.md
- ✅ Layer orchestrators (CORE, APPLICATION, INFRASTRUCTURE)
- ✅ Module agents (all 11 created)
- ✅ Cross-cutting orchestrators (LOGGING, VALIDATION, DOCUMENTATION)

### Key Files

**Orchestration System**:
- `.claude/system/ORCHESTRATION_ENGINE.md` - Complete orchestration algorithms
- `.claude/system/DOCUMENTATION_ORCHESTRATOR.md` - Automatic doc updates
- `.claude/commands/orchestrate.md` - Command specification

**Prompt Templates** (For Task agents):
- `.claude/prompts/module_implementation_template.md`
- `.claude/prompts/debugging_workflow_template.md`
- `.claude/prompts/layer_validation_template.md`
- `.claude/prompts/system_integration_template.md`

### Benefits

✅ **Universal**: Handles ANY task (implement, debug, refactor, analyze)
✅ **Autonomous**: Zero manual intervention
✅ **Intelligent**: Full MCP integration at all levels
✅ **Documented**: Automatic CHANGELOG.md updates
✅ **Hierarchical**: Respects existing agent structure
✅ **Parallel**: Maximum efficiency
✅ **Resumable**: Checkpoint/resume capability
✅ **Validated**: Multi-level quality gates

---

## Architecture Quick Reference

### Layered Structure
```
Entry Points (CLI, Library, API, UI)
    ↓
Application (BacktestRunner, DataSync)
    ↓
Core Domain (EventLoop, Portfolio, Strategy)
    ↓
Infrastructure (DataHandlers, Database, Indicators)
```

### Key Dependency Rule
**Outer layers depend on inner layers, NEVER reverse.**

This means:
- CLI can import Application and Core
- Application can import Core
- Core imports NOTHING from outer layers
- Infrastructure implements Core interfaces

---

## Project Structure

```
jutsu-labs-vibe/
├── jutsu_engine/           # Core library (import as package)
│   ├── core/             # Domain: EventLoop, Strategy base, Events
│   ├── application/      # Use cases: BacktestRunner, DataSync
│   ├── data/             # Infrastructure: Handlers, Database
│   ├── indicators/       # Stateless TA functions
│   ├── portfolio/        # Portfolio state management
│   ├── performance/      # Metrics calculation
│   ├── strategies/       # Concrete strategy implementations
│   └── utils/            # Logging, config, helpers
│
├── jutsu_cli/             # CLI entry point (Click/Typer)
├── jutsu_api/             # REST API wrapper (future)
├── vibe_ui/              # Web dashboard (future)
│
├── tests/                # All tests
│   ├── unit/            # Isolated module tests
│   ├── integration/     # Module interaction tests
│   └── fixtures/        # Reusable test data
│
├── scripts/              # Example usage scripts
├── docs/                 # Comprehensive documentation
│   ├── SYSTEM_DESIGN.md     # Full architecture
│   ├── BEST_PRACTICES.md    # Coding standards
│   └── ...
│
├── config/               # Configuration files
├── logs/                 # Runtime logs (gitignored)
└── data/                 # Database (gitignored)
```

---

## Module Responsibilities

### Core Domain (`jutsu_engine/core/`)

**EventLoop** - Central coordinator
- Processes bars sequentially (bar-by-bar)
- Publishes MarketDataEvents
- Coordinates Strategy → Portfolio → Analyzer flow
- Prevents lookback bias through sequential processing

**Strategy Base** - Interface all strategies implement
```python
class Strategy(ABC):
    def init(self): ...       # Setup parameters
    def on_bar(self, bar): ...  # Process each bar
```

**Events** - Event definitions
- `MarketDataEvent`: OHLCV bar
- `SignalEvent`: Buy/Sell signal
- `OrderEvent`: Trade order
- `FillEvent`: Executed trade

### Application Layer (`jutsu_engine/application/`)

**BacktestRunner** - Orchestrates full backtest
- Loads data from database
- Initializes strategy and portfolio
- Runs EventLoop
- Returns performance metrics

**DataSync** - Fetches and stores market data
- Checks metadata for existing data
- Fetches incrementally from API (only new bars)
- Validates and stores in database
- Updates metadata

### Infrastructure (`jutsu_engine/data/`)

**DataHandler Interface** - Abstract data source
```python
class DataHandler(ABC):
    def get_next_bar(self) -> Iterator[MarketDataEvent]: ...
    def get_latest_bar(self, symbol: str) -> MarketDataEvent: ...
```

**Implementations**:
- `DatabaseDataHandler`: Reads from SQLite/PostgreSQL
- `SchwabDataFetcher`: Fetches from Schwab API
- (Future) `CSVDataHandler`, `YahooDataHandler`, etc.

**Database Models** - SQLAlchemy schema
- `market_data`: OHLCV bars with source tracking
- `data_metadata`: Tracks what data we have (for incremental updates)

### Indicators (`jutsu_engine/indicators/`)

**Stateless Functions** - Pure functions for technical analysis
```python
def calculate_sma(prices: pd.Series, period: int) -> Decimal
def calculate_ema(prices: pd.Series, period: int) -> Decimal
def calculate_rsi(prices: pd.Series, period: int) -> Decimal
```

**Key Principle:** No state, no side effects, easy to test

### Portfolio (`jutsu_engine/portfolio/`)

**PortfolioSimulator** - Manages state and executes trades
- Tracks cash and positions
- Executes buy/sell signals
- Calculates mark-to-market PnL
- Logs all transactions (audit trail)

**State Management:**
- Portfolio is "smart" (manages state)
- Strategy is "dumb" (just sends signals)

### Performance (`jutsu_engine/performance/`)

**PerformanceAnalyzer** - Calculates metrics post-backtest
- Runs AFTER EventLoop completes
- Reads trade log and portfolio history
- Returns JSON with metrics (Sharpe, drawdown, win rate, etc.)

---

## Coding Standards

### Type Hints (REQUIRED)
```python
# ✅ All public functions must have type hints
def calculate_sma(prices: pd.Series, period: int) -> Decimal:
    """Calculate Simple Moving Average"""
    ...

# ❌ No type hints is not acceptable
def calculate_sma(prices, period):
    ...
```

### Docstrings (Google Style)
```python
def fetch_data(symbol: str, start_date: datetime) -> List[MarketDataEvent]:
    """
    Fetch historical market data.

    Args:
        symbol: Stock ticker symbol
        start_date: Start date for data fetch

    Returns:
        List of MarketDataEvent objects

    Raises:
        APIError: If API request fails
    """
    ...
```

### Logging (Module-Based)
```python
import logging
logger = logging.getLogger('DATA.SCHWAB')  # Module prefix

logger.info(f"Fetching {symbol} data from {start_date}")
logger.warning(f"Partial data received for {symbol}")
logger.error(f"API failure: {error}")
```

**Log Format:**
```
2025-10-31 14:30:22,123 | DATA.SCHWAB | INFO | Fetching AAPL data...
```

### Naming Conventions (PEP 8)
- `snake_case`: functions, variables
- `PascalCase`: classes
- `UPPER_CASE`: constants
- `_private`: private methods/variables

```python
# Constants
MAX_POSITION_SIZE = Decimal('0.20')

# Classes
class PortfolioSimulator:
    ...

# Functions
def calculate_sharpe_ratio(returns: pd.Series) -> float:
    ...

# Private
def _validate_input(self):
    ...
```

---

## Development Workflow

### Running Tests
```bash
# All tests
pytest

# With coverage
pytest --cov=jutsu_engine --cov-report=html

# Specific test file
pytest tests/unit/test_portfolio.py

# Verbose
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

### Git Workflow
1. Always work on feature branches: `git checkout -b feature/strategy-optimizer`
2. Run tests before commit: `pytest`
3. Format code: `black . && isort .`
4. Commit with clear messages: `git commit -m "Add SMA crossover strategy"`
5. Push and create PR

### Logging During Development
- Check `logs/` directory for runtime logs
- Each module has separate log file with timestamp
- Use `tail -f logs/jutsu_engine_*.log` to watch live logs

---

## Common Patterns

### Strategy Pattern (for trading strategies)
```python
class SMA_Crossover(Strategy):
    def init(self):
        self.short_period = 20
        self.long_period = 50

    def on_bar(self, bar):
        closes = self.get_closes(self.long_period)
        short_sma = calculate_sma(closes, self.short_period)
        long_sma = calculate_sma(closes, self.long_period)

        if short_sma > long_sma and not self.has_position():
            self.buy(bar.symbol, 100)
        elif short_sma < long_sma and self.has_position():
            self.sell(bar.symbol, 100)
```

### Repository Pattern (for database access)
```python
class DataRepository:
    def get_bars(self, symbol, start, end):
        return self.session.query(MarketData)
                   .filter_by(symbol=symbol)
                   .filter(MarketData.timestamp.between(start, end))
                   .all()

    def insert_bar(self, bar):
        self.session.add(MarketData(**bar.dict()))
        self.session.commit()
```

### Factory Pattern (for creating handlers)
```python
class DataHandlerFactory:
    @staticmethod
    def create(source: str) -> DataHandler:
        if source == 'schwab':
            return SchwabDataHandler()
        elif source == 'csv':
            return CSVDataHandler()
```

---

## Data Handling Rules

### 1. Use Decimal for Financial Calculations
```python
from decimal import Decimal

# ❌ NEVER use float
price = 100.15
total = price * 10  # Floating point errors!

# ✅ ALWAYS use Decimal
price = Decimal('100.15')
total = price * 10  # Exact precision
```

### 2. Store Timestamps in UTC
```python
from datetime import datetime, timezone

# ❌ Naive datetime (ambiguous)
timestamp = datetime.now()

# ✅ UTC timezone-aware
timestamp = datetime.now(timezone.utc)
```

### 3. Validate All Input Data
```python
def validate_bar(bar) -> tuple[bool, Optional[str]]:
    # Check all OHLCV fields present
    # Verify High >= Low
    # Ensure prices > 0
    # Check volume >= 0
    return is_valid, error_message
```

### 4. Never Modify Historical Data
```python
# ❌ WRONG: Modify existing bar
bar.close = new_value

# ✅ RIGHT: Mark as invalid, insert corrected data
bar.is_valid = False
insert_new_bar(corrected_data, source='manual_correction')
```

### 5. Prevent Lookback Bias
```python
# ❌ WRONG: Using future data
future_bars = get_bars(symbol, end_date=today + 5)

# ✅ RIGHT: Only historical data
historical_bars = get_bars(symbol, end_date=today)
```

---

## Testing Guidelines

### Unit Tests
```python
# tests/unit/test_portfolio.py
def test_portfolio_buy():
    portfolio = PortfolioSimulator(initial_capital=Decimal('100000'))
    portfolio.buy('AAPL', 100, Decimal('150.00'))

    assert portfolio.cash == Decimal('85000.00')
    assert portfolio.positions['AAPL'] == 100
```

### Mock External Dependencies
```python
@patch('jutsu_engine.data.handlers.schwab.SchwabAPI')
def test_data_sync(mock_api):
    mock_api.fetch_bars.return_value = [...]
    syncer = DataSync(api=mock_api)
    syncer.sync_symbol('AAPL', '1D')
    mock_api.fetch_bars.assert_called_once()
```

### Use Fixtures for Test Data
```python
# tests/fixtures/sample_data.py
SAMPLE_BARS = [
    MarketDataEvent(symbol='AAPL', close=Decimal('150.00'), ...),
    ...
]

# Use in tests
from tests.fixtures.sample_data import SAMPLE_BARS
```

### Coverage Target
- Unit tests: >80% coverage
- Critical paths: 100% coverage (EventLoop, Portfolio, DataSync)

---

## Future Enhancements (Roadmap)

### Phase 1: MVP (Current)
- [x] Project structure and documentation
- [x] Database design
- [ ] Schwab API integration
- [ ] Core EventLoop
- [ ] Portfolio simulator
- [ ] Basic strategies
- [ ] Performance metrics

### Phase 2: Service Layer
- [ ] REST API (FastAPI)
- [ ] Parameter optimization
- [ ] PostgreSQL support
- [ ] Advanced metrics
- [ ] Multiple data sources

### Phase 3: UI & Distribution
- [ ] Web dashboard (Streamlit)
- [ ] Docker deployment
- [ ] Scheduled jobs
- [ ] Monte Carlo simulation

### Phase 4: Production
- [ ] Paper trading
- [ ] Live trading integration
- [ ] Advanced risk management

---

## Configuration

### Environment Variables (.env)
```bash
SCHWAB_API_KEY=your_api_key
SCHWAB_API_SECRET=your_secret
DATABASE_URL=sqlite:///data/market_data.db
LOG_LEVEL=INFO
```

### Application Config (config/config.yaml)
- Database connection settings
- Data source configurations
- Backtesting defaults
- Logging configuration
- Performance metric settings

---

## Common Tasks

### Add a New Strategy
1. Create file in `jutsu_engine/strategies/`
2. Inherit from `Strategy` base class
3. Implement `init()` and `on_bar()` methods
4. Add tests in `tests/unit/test_strategies.py`
5. Document in docstring

### Add a New Indicator
1. Add function to `jutsu_engine/indicators/technical.py`
2. Must be stateless (pure function)
3. Use `Decimal` for precision
4. Add type hints and docstring
5. Write unit tests

### Add a New Data Source
1. Create handler in `jutsu_engine/data/handlers/`
2. Inherit from `DataHandler` base class
3. Implement required methods
4. Add to `DataHandlerFactory`
5. Update configuration

### Debug a Backtest
1. Check logs in `logs/` directory
2. Enable DEBUG level logging for specific module
3. Use `ipdb` for interactive debugging
4. Verify data quality in database
5. Test strategy in isolation with fixtures

---

## Troubleshooting

### Import Errors
- Ensure you're in virtual environment: `source venv/bin/activate`
- Install in editable mode: `pip install -e .`
- Check PYTHONPATH includes project root

### Database Errors
- Check DATABASE_URL in .env
- Verify database file exists: `ls data/market_data.db`
- Run migrations if schema changed
- Check SQLAlchemy logs for query issues

### API Errors
- Verify API credentials in .env
- Check rate limits (max 2 requests/second for Schwab)
- Review API logs: `grep "API" logs/*.log`
- Test API connection separately

### Test Failures
- Run specific test: `pytest tests/unit/test_X.py -v`
- Check test database isolation (use in-memory SQLite)
- Verify mock setup for external dependencies
- Review test fixtures for data issues

---

## Key Files to Know

### Documentation
- `docs/SYSTEM_DESIGN.md` - Complete architecture and design decisions
- `docs/BEST_PRACTICES.md` - Coding standards and financial data handling
- `README.md` - User-facing project overview

### Configuration
- `.env` - Environment variables (API keys, database URL)
- `config/config.yaml` - Application configuration
- `requirements.txt` - Production dependencies
- `pyproject.toml` - Build system and tool configurations

### Core Implementation
- `jutsu_engine/core/event_loop.py` - Central backtest coordinator
- `jutsu_engine/core/strategy_base.py` - Strategy interface
- `jutsu_engine/data/models.py` - Database schema
- `jutsu_engine/portfolio/simulator.py` - Portfolio state management

---

## Working with Claude Code

**MANDATORY WORKFLOW**: All work on Jutsu-Labs MUST follow agent architecture and Serena memory system.

### Session Start Protocol (REQUIRED - Every Session)

**Step 1: Activate Serena & Read Memories**
```python
# 1. Activate Serena project
mcp__serena__activate_project("Jutsu-Labs")

# 2. List available memories
mcp__serena__list_memories()

# 3. Read relevant memories based on task
mcp__serena__read_memory("<relevant_memory>")
```

**Step 2: Review Project State**
```bash
git log --oneline -5  # Recent changes
git branch            # Current branch
git status            # Working tree state
```

**Step 3: Route to Agent Architecture**
- **For ALL tasks**: Use `/orchestrate <task description>`
- **No exceptions**: Even simple bug fixes go through agents
- **Why**: Maintains context, enables validation, preserves knowledge

### Universal Task Execution (REQUIRED - All Tasks)

**Use `/orchestrate` for EVERYTHING**:

```bash
# Bug fixes
/orchestrate fix bug in <module>, <context>

# Features
/orchestrate implement <feature description>

# Analysis
/orchestrate analyze <system/module> <aspect>

# Refactoring
/orchestrate refactor <layer/module> for <goal>

# Optimization
/orchestrate optimize <module> <metric>
```

**What `/orchestrate` Does Automatically**:
1. ✅ Activates Serena (if not already active)
2. ✅ Reads relevant project memories
3. ✅ Routes to appropriate orchestrator (SYSTEM/CORE/APPLICATION/INFRASTRUCTURE)
4. ✅ Delegates to specific agent with full context
5. ✅ Agent reads its context file (`.claude/layers/.../modules/*_AGENT.md`)
6. ✅ Agent uses domain expertise and module knowledge
7. ✅ Validates at agent, layer, and system levels
8. ✅ Updates CHANGELOG.md automatically
9. ✅ Writes Serena memory for future reference
10. ✅ Reports completion with evidence

### Agent Context Usage (AUTOMATIC)

When routed to an agent, it **automatically reads and uses** its context file:

**Example: SCHWAB_FETCHER_AGENT**
```markdown
File Read: `.claude/layers/infrastructure/modules/SCHWAB_FETCHER_AGENT.md`

Context Loaded:
- Identity & Purpose
- Module Ownership (schwab.py, tests, config)
- Responsibilities (authentication, data fetching, rate limiting)
- Allowed/Forbidden dependencies
- Current implementation patterns
- Known issues and solutions
- Performance targets
- Testing requirements
```

**Agent Uses This Context For**:
- ✅ Understanding module boundaries and responsibilities
- ✅ Following established patterns and conventions
- ✅ Respecting dependency rules (what can/can't import)
- ✅ Implementing consistent error handling
- ✅ Meeting performance and quality targets
- ✅ Coordinating with other agents properly

### Task Completion Protocol (REQUIRED - Every Task)

**After Agent Completes Work**:

1. ✅ **CHANGELOG.md Updated**: Automatic documentation
   - Added: New features/modules
   - Fixed: Bug fixes with root cause
   - Changed: Refactorings/improvements

2. ✅ **Serena Memory Written**: Knowledge preservation
   ```python
   mcp__serena__write_memory(
       memory_name="<task>_<date>",
       content="# <Task Title>\n\n<comprehensive documentation>"
   )
   ```

3. ✅ **Validation Complete**: Multi-level checks
   - Agent-level: Unit tests, type hints, logging
   - Layer-level: Interface compatibility, performance
   - System-level: Integration tests (if applicable)

4. ✅ **Report to User**: Evidence and results
   - What was done
   - Files modified
   - Tests passing
   - Performance metrics
   - Next steps (if any)

### Example: Fixing a Bug (Schwab API)

**❌ OLD WAY (Wrong - Don't Do This)**:
```
User: "Schwab API returns 0 bars"
Claude: *directly edits schwab.py without agent context*
```

**✅ NEW WAY (Correct - Always Do This)**:
```bash
/orchestrate fix bug in Schwab API, returns 0 bars for historical data

# Automatic Execution:
# 1. Serena activated → reads schwab_fetcher_status memory
# 2. Routes to INFRASTRUCTURE_ORCHESTRATOR
# 3. Delegates to SCHWAB_FETCHER_AGENT
# 4. Agent reads: .claude/layers/infrastructure/modules/SCHWAB_FETCHER_AGENT.md
# 5. Agent analyzes: schwab.py, API docs, logs, memories
# 6. Agent identifies: Missing period parameter
# 7. Agent fixes: Adds period=TWENTY_YEARS
# 8. Agent validates: Tests with AAPL, MSFT
# 9. CHANGELOG.md updated: Comprehensive fix documentation
# 10. Memory written: schwab_api_period_fix_2025-11-02
# 11. Reports: "Fixed - 6288 bars now retrieved successfully"
```

### Example: Implementing a Feature

**✅ CORRECT WORKFLOW**:
```bash
/orchestrate implement trailing stop-loss orders

# Automatic Execution:
# 1. Serena activated → reads strategy/portfolio/events memories
# 2. Routes to SYSTEM_ORCHESTRATOR (multi-layer feature)
# 3. Creates coordination plan:
#    - EVENTS_AGENT: Define TrailingStopEvent (reads events context)
#    - PORTFOLIO_AGENT: Implement execution (reads portfolio context)
#    - STRATEGY_AGENT: Add API method (reads strategy context)
#    - EVENT_LOOP_AGENT: Handle event (reads event_loop context)
# 4. Each agent uses its domain expertise from context files
# 5. Layer validation after each module
# 6. CHANGELOG.md updated with all changes
# 7. Memory written: trailing_stop_implementation_2025-11-02
# 8. Reports: "Feature complete - 4 modules updated, 18 tests added"
```

### Why Agent Architecture is Mandatory

**Context Preservation**:
- Each agent knows its module deeply (from .md context files)
- Agents remember decisions and patterns
- Serena memories provide cross-session continuity

**Quality Assurance**:
- Agents enforce architecture boundaries
- Multi-level validation (agent → layer → system)
- Consistent patterns across codebase

**Knowledge Management**:
- Every change documented in CHANGELOG.md
- Every fix preserved in Serena memories
- Future work benefits from past context

**Efficiency**:
- Agents work in parallel (when possible)
- Specialized expertise for each domain
- Faster than general-purpose implementation

### Agent Expertise by Layer

**Core Domain Agents** (Business Logic):
- **EVENT_LOOP_AGENT**: Bar-by-bar processing, event coordination
- **PORTFOLIO_AGENT**: State management, trade execution
- **STRATEGY_AGENT**: Trading strategy framework
- **EVENTS_AGENT**: Event type definitions

**Application Agents** (Use Cases):
- **BACKTEST_RUNNER_AGENT**: Full backtest orchestration
- **DATA_SYNC_AGENT**: Incremental data synchronization

**Infrastructure Agents** (Technical Services):
- **SCHWAB_FETCHER_AGENT**: API integration, OAuth, rate limiting
- **DATABASE_HANDLER_AGENT**: Data persistence, querying
- **INDICATORS_AGENT**: Technical analysis calculations
- **PERFORMANCE_AGENT**: Metrics and analytics

**Cross-Cutting Orchestrators**:
- **LOGGING_ORCHESTRATOR**: Log format, levels, consistency
- **VALIDATION_ORCHESTRATOR**: Testing, quality gates
- **DOCUMENTATION_ORCHESTRATOR**: CHANGELOG.md updates

### Quick Reference Commands

**Start Session**:
```bash
# Automatic when using /orchestrate
# Or manual:
mcp__serena__activate_project("Jutsu-Labs")
mcp__serena__list_memories()
```

**Execute Task** (Use for EVERYTHING):
```bash
/orchestrate <task description>
```

**Check Status**:
```bash
/orchestrate status  # Current progress
```

**Resume Interrupted Work**:
```bash
/orchestrate resume  # Continues from Serena checkpoint
```

**Before Committing**:
```bash
# Tests and validation (automatic via agents)
pytest
black . && isort .
mypy jutsu_engine/

# Manual validation if needed
/orchestrate validate before commit
```

---

## Project Philosophy

**Simplicity & Flow:**
- Core engine should be simple and easy to work with
- Avoid over-engineering the MVP
- Prioritize clarity over cleverness

**Modularity:**
- Every component should be swappable
- Interfaces over implementations
- Plugin architecture for extensibility

**Data Integrity:**
- Financial data requires precision and auditability
- Never compromise on validation or logging
- Immutable historical data

**Expandability:**
- Design assumes features will be added
- Future-proof interfaces without over-engineering
- Clear evolution path from simple → complex

---

## Contact & Resources

**Project Authors:**
- Anil Goparaju
- Padma Priya Garnepudi

**External Resources:**
- Schwab API Docs: https://developer.schwab.com
- schwab-py Library: https://github.com/itsjafer/schwab-py
- SQLAlchemy Docs: https://docs.sqlalchemy.org

**Internal Resources:**
- System Design: `docs/SYSTEM_DESIGN.md`
- Best Practices: `docs/BEST_PRACTICES.md`
- Project README: `README.md`

---

**Remember:** This is a backtesting engine for EDUCATIONAL and RESEARCH purposes. Always validate strategies thoroughly before using real capital. Past performance does not guarantee future results.
