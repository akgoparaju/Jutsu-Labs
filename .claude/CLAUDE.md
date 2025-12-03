# ⛔ JUTSU-LABS MANDATORY WORKFLOW

**CRITICAL**: Read `.claude/WORKFLOW_GUARD.md` EVERY session → ALL work via `/orchestrate`

❌ NEVER use Edit/Write/MultiEdit directly on code
✅ ALWAYS route through `/orchestrate <description>`

**Why**: Agent context files contain module knowledge, enforce architecture, accumulate in memories

---

# Jutsu Labs - Modular Backtesting Engine

**What**: Database-backed backtesting engine | **Version**: 0.1.0 MVP
**Architecture**: Hexagonal (business logic ⇄ infrastructure)
**Key**: Event-driven bar-by-bar, Decimal precision, plugin system

## Layer Structure
```
Entry → Application → Core → Infrastructure
        (outer → inner, NEVER reverse)
```

---

## Orchestration System

**Universal**: `/orchestrate <task>` for ALL work

| Task Type | Example |
|-----------|---------|
| Implement | `/orchestrate implement layer/core` |
| Debug | `/orchestrate fix bug in EventLoop` |
| Refactor | `/orchestrate refactor Core for perf` |
| Analyze | `/orchestrate analyze system security` |
| Optimize | `/orchestrate optimize Portfolio perf` |

**Auto-Execution**:
1. Detects task type → decompose → parallel modules → sequential layers
2. Reads agent `.md` context → implements → validates → updates docs
3. CHANGELOG.md + Serena memories updated automatically

**Scope**: system (all layers) | layer/X | module/X | custom

**Performance**: <100ms startup | 2-5min/module | 10-20min/layer | 60-90min/system

**Quality Gates**: Module (unit tests, types) → Layer (interfaces) → System (integration)

---

## Project Structure

```
jutsu_engine/
├── core/             # EventLoop, Strategy, Events
├── application/      # BacktestRunner, DataSync
├── data/             # Handlers, Database
├── indicators/       # Stateless TA functions
├── portfolio/        # State management
├── performance/      # Metrics
├── strategies/       # Implementations
└── utils/            # Logging, config

tests/                # unit/ integration/ fixtures/
docs/                 # SYSTEM_DESIGN.md, BEST_PRACTICES.md
```

---

## Module Responsibilities

| Layer | Module | Core Function |
|-------|--------|---------------|
| **Core** | EventLoop | Bar-by-bar coordinator, prevents lookback bias |
| | Strategy | `init()` + `on_bar()` interface |
| | Events | MarketData, Signal, Order, Fill events |
| **Application** | BacktestRunner | Orchestrates: data → strategy → portfolio → metrics |
| | DataSync | Incremental fetch, validate, store, update metadata |
| **Infrastructure** | DataHandler | Abstract source: `get_next_bar()`, `get_latest_bar()` |
| | Database | SQLAlchemy: market_data + data_metadata tables |
| | Indicators | Stateless TA: `calculate_sma/ema/rsi(prices, period) → Decimal` |
| | Portfolio | State mgmt: cash, positions, executes trades, audit trail |
| | Performance | Post-backtest metrics: Sharpe, drawdown, win rate |

---

## Coding Standards

| Standard | Format | Example |
|----------|--------|---------|
| Type hints | Required | `def calc_sma(prices: pd.Series, period: int) → Decimal` |
| Docstrings | Google style | Args/Returns/Raises |
| Logging | Module-based | `logger = logging.getLogger('DATA.SCHWAB')` |
| Naming | PEP 8 | snake_case, PascalCase, UPPER_CASE |
| Precision | Decimal | `Decimal('100.15')` not `float` |
| Timestamps | UTC | `datetime.now(timezone.utc)` |

---

## Data Rules

✅ **Decimal for $**: `Decimal('100.15')` not `100.15`
✅ **UTC timestamps**: `datetime.now(timezone.utc)`
✅ **Validate inputs**: check OHLCV fields, High ≥ Low, prices > 0
✅ **Immutable history**: mark invalid, insert corrected
✅ **No lookback bias**: only historical data

---

## Common Patterns

**Strategy**: `init()` + `on_bar()` → signals
**Repository**: `get_bars()` + `insert_bar()` → data access
**Factory**: `create(source)` → handler instances

---

## Session Protocol (MANDATORY)

**Every Session**:
1. `/orchestrate <task>` → Auto-activates Serena, reads memories, routes to agents
2. Agents read `.claude/layers/.../modules/*_AGENT.md` for context
3. Multi-level validation: agent → layer → system
4. Auto-updates: CHANGELOG.md + Serena memories

**Agent Expertise** (auto-selected by `/orchestrate`):

| Layer | Agents | Domain |
|-------|--------|--------|
| Core | EventLoop, Portfolio, Strategy, Events | Business logic |
| Application | BacktestRunner, DataSync | Use cases |
| Infrastructure | Schwab, Database, Indicators, Performance | Technical services |

**Why Mandatory**:
- ✅ Context preservation (agent .md files + Serena memories)
- ✅ Architecture enforcement (boundaries + dependencies)
- ✅ Knowledge accumulation (CHANGELOG + memories)
- ✅ Multi-level validation (agent → layer → system)

**Examples**:
```bash
/orchestrate fix bug in Schwab API, returns 0 bars
/orchestrate implement trailing stop-loss
/orchestrate refactor Core for performance
```

---

## Development Workflow

**Tests**: `pytest` | `pytest --cov=jutsu_engine --cov-report=html`
**Quality**: `black . && isort .` | `flake8` | `mypy jutsu_engine/`
**Git**: Feature branches → tests → format → commit → PR
**Coverage**: >80% unit | 100% critical paths

---

## Testing

**Unit**: Isolated module tests with fixtures
**Mock**: External dependencies (API, DB)
**Coverage**: >80% overall, 100% EventLoop/Portfolio/DataSync

---

## Configuration

**.env**: API keys, DATABASE_URL, LOG_LEVEL
**config.yaml**: Database, data sources, backtest defaults, metrics

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Import errors | `source venv/bin/activate` → `pip install -e .` |
| Database errors | Check DATABASE_URL, verify file exists, check logs |
| API errors | Verify credentials, check rate limits, review API logs |
| Test failures | Run specific test with `-v`, check isolation/mocks |

---

## Key Files

**Docs**: `docs/SYSTEM_DESIGN.md`, `docs/BEST_PRACTICES.md`, `README.md`
**Config**: `.env`, `config/config.yaml`, `requirements.txt`, `pyproject.toml`
**Core**: `core/event_loop.py`, `core/strategy_base.py`, `data/models.py`, `portfolio/simulator.py`
**Agent System**: `.claude/system/ORCHESTRATION_ENGINE.md`, `.claude/commands/orchestrate.md`

---

## Agent Architecture

```
System Orchestrator
├─ Logging/Validation Orchestrators (Cross-cutting)
├─ Core Orchestrator → EventLoop, Portfolio, Strategy, Events
├─ Application Orchestrator → BacktestRunner, DataSync
└─ Infrastructure Orchestrator → Schwab, Database, Indicators, Performance
```

**Routing**: Auto (keyword detection) | Manual (`/agent core/event-loop "task"`)
**Context**: Each agent has `.claude/layers/.../modules/*_AGENT.md` with responsibilities, patterns, targets
**Validation**: Fast layer validation + comprehensive system validation

---

## Quick Commands

**Start**: Automatic with `/orchestrate` or manual `mcp__serena__activate_project("Jutsu-Labs")`
**Execute**: `/orchestrate <task description>` (for EVERYTHING)
**Status**: `/orchestrate status`
**Resume**: `/orchestrate resume` (from Serena checkpoint)
**Validate**: `pytest && black . && isort . && mypy jutsu_engine/`

---

## Project Philosophy

**Simplicity**: Easy to work with, avoid over-engineering, clarity > cleverness
**Modularity**: Swappable components, interfaces > implementations, plugin architecture
**Data Integrity**: Decimal precision, validation, logging, immutable history
**Expandability**: Future-proof interfaces, simple → complex evolution

---

## Contact & Resources

**Authors**: Anil Goparaju, Padma Priya Garnepudi
**External**: Schwab API (developer.schwab.com), schwab-py (github.com/itsjafer/schwab-py), SQLAlchemy
**Internal**: `docs/SYSTEM_DESIGN.md`, `docs/BEST_PRACTICES.md`, `README.md`

**Remember**: Educational/research purposes. Validate thoroughly. Past performance ≠ future results.
