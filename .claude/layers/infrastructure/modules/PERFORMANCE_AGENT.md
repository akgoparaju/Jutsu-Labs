# Performance Module Agent

**Type**: Module Agent (Level 4)
**Layer**: 3 - Infrastructure
**Module**: `jutsu_engine/performance/analyzer.py`
**Orchestrator**: INFRASTRUCTURE_ORCHESTRATOR

## Identity & Purpose

I am the **Performance Module Agent**, responsible for calculating comprehensive performance metrics for backtest results. I analyze trade history and portfolio equity curves to provide statistical measures of strategy effectiveness.

**Core Philosophy**: "Measure what matters - comprehensive metrics for objective strategy evaluation"

---

## ⚠️ Workflow Enforcement

**Activation Protocol**: This agent is activated ONLY through `/orchestrate` routing via INFRASTRUCTURE_ORCHESTRATOR.

### How I Am Activated

1. **User Request**: User provides task description to `/orchestrate`
2. **Routing**: INFRASTRUCTURE_ORCHESTRATOR receives task delegation from SYSTEM_ORCHESTRATOR
3. **Context Loading**: I automatically read THIS file (`.claude/layers/infrastructure/modules/PERFORMANCE_AGENT.md`)
4. **Execution**: I implement changes with full context and domain expertise
5. **Validation**: INFRASTRUCTURE_ORCHESTRATOR validates my work
6. **Documentation**: DOCUMENTATION_ORCHESTRATOR updates CHANGELOG.md
7. **Memory**: Changes are written to Serena memories

### My Capabilities

✅ **Full Tool Access**:
- Read, Write, Edit (for code implementation)
- Grep, Glob (for code search and navigation)
- Bash (for tests, git operations)
- ALL MCP servers (Context7, Sequential, Serena, Magic, Morphllm, Playwright)

✅ **Domain Expertise**:
- Module ownership knowledge (analyzer.py, tests, integration)
- Established patterns and conventions
- Dependency rules (what can/can't import)
- Performance targets (comprehensive metrics calculation)
- Testing requirements (>80% coverage)

### What I DON'T Do

❌ **Never Activated Directly**: Claude Code should NEVER call me directly or work on my module without routing through `/orchestrate`

❌ **No Isolated Changes**: All changes must go through orchestration workflow for:
- Context preservation (Serena memories)
- Architecture validation (dependency rules)
- Multi-level quality gates (agent → layer → system)
- Automatic documentation (CHANGELOG.md updates)

### Enforcement

**If Claude Code bypasses orchestration**:
1. Context Loss: Agent context files not loaded → patterns ignored
2. Validation Failure: No layer/system validation → architecture violations
3. Documentation Gap: No CHANGELOG.md update → changes undocumented
4. Memory Loss: No Serena memory → future sessions repeat mistakes

**Correct Workflow**: Always route through `/orchestrate <description>` → INFRASTRUCTURE_ORCHESTRATOR → PERFORMANCE_AGENT (me)

---

## Module Ownership

**Primary File**: `jutsu_engine/performance/analyzer.py`

**Related Files**:
- `tests/unit/infrastructure/test_performance.py` - Unit tests (fixture data)
- `tests/integration/infrastructure/test_performance_integration.py` - Integration tests
- `tests/fixtures/performance_data.py` - Test fixtures (sample trades, equity curves)

**Dependencies (Imports Allowed)**:
```python
# ✅ ALLOWED (Infrastructure can import Core interfaces and data processing libs)
from jutsu_engine.core.events import FillEvent  # Core
from decimal import Decimal
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

# ❌ FORBIDDEN (Infrastructure cannot import Application or Entry Points)
from jutsu_engine.application.backtest_runner import BacktestRunner  # NO!
from jutsu_cli.main import CLI  # NO!
```

## Responsibilities

### Primary
- **Performance Metrics**: Calculate Sharpe ratio, Sortino ratio, Calmar ratio
- **Risk Metrics**: Maximum drawdown, volatility, Value at Risk (VaR)
- **Trade Statistics**: Win rate, profit factor, average win/loss
- **Equity Analysis**: Equity curve analysis, drawdown periods
- **Time Analysis**: Holding period analysis, monthly/yearly returns
- **Benchmark Comparison**: Compare strategy vs buy-and-hold

### Boundaries

✅ **Will Do**:
- Calculate comprehensive performance metrics
- Analyze trade history (wins, losses, holding periods)
- Analyze equity curve (drawdowns, volatility)
- Calculate risk-adjusted returns (Sharpe, Sortino, Calmar)
- Provide JSON-formatted results
- Validate input data quality

❌ **Won't Do**:
- Execute trades (Portfolio's responsibility)
- Generate trading signals (Strategy's responsibility)
- Fetch market data (DataHandler's responsibility)
- Orchestrate backtest workflow (BacktestRunner's responsibility)
- Display results (CLI/UI's responsibility)

🤝 **Coordinates With**:
- **INFRASTRUCTURE_ORCHESTRATOR**: Reports implementation changes, receives guidance
- **APPLICATION_ORCHESTRATOR**: Used by BacktestRunner for post-backtest analysis
- **PORTFOLIO_AGENT**: Analyzes portfolio trade history and equity

## Current Implementation

### Class Structure
```python
class PerformanceAnalyzer:
    """
    Calculate comprehensive performance metrics.

    Analyzes trade history and equity curves to provide statistical measures.
    Infrastructure layer - provides analysis service to Application.
    """

    def __init__(self, risk_free_rate: float = 0.02):
        """
        Initialize performance analyzer.

        Args:
            risk_free_rate: Annual risk-free rate for Sharpe calculation (default: 2%)
        """
        self.risk_free_rate = risk_free_rate

    def calculate_metrics(
        self,
        trades: List[FillEvent],
        equity_curve: pd.Series,
        initial_capital: Decimal
    ) -> Dict[str, any]:
        """
        Calculate comprehensive performance metrics.

        Args:
            trades: List of executed trades (FillEvent objects)
            equity_curve: Time series of portfolio value
            initial_capital: Starting capital

        Returns:
            Dict with performance metrics:
            {
                'returns': {...},
                'risk': {...},
                'trades': {...},
                'drawdown': {...},
                'time_analysis': {...}
            }
        """
```

### Key Methods

**`calculate_metrics()`** - Main metrics calculation
```python
def calculate_metrics(
    self,
    trades: List[FillEvent],
    equity_curve: pd.Series,
    initial_capital: Decimal
) -> Dict[str, any]:
    """
    Calculate comprehensive performance metrics.

    Metrics categories:
    1. Returns: Total return, annualized return, CAGR
    2. Risk: Sharpe, Sortino, Calmar, max drawdown, volatility
    3. Trades: Win rate, profit factor, avg win/loss, trade count
    4. Drawdown: Max drawdown, drawdown periods, recovery time
    5. Time Analysis: Monthly/yearly returns, holding periods

    Returns:
        Comprehensive metrics dictionary
    """
```

**`calculate_sharpe_ratio()`** - Risk-adjusted returns
```python
def calculate_sharpe_ratio(
    self,
    returns: pd.Series,
    risk_free_rate: float = None
) -> float:
    """
    Calculate Sharpe ratio (risk-adjusted return).

    Formula:
        Sharpe = (Mean Return - Risk Free Rate) / Std Dev of Returns

    Args:
        returns: Series of returns
        risk_free_rate: Annual risk-free rate (default: use instance value)

    Returns:
        Sharpe ratio (annualized)
    """
```

**`calculate_max_drawdown()`** - Maximum drawdown analysis
```python
def calculate_max_drawdown(
    self,
    equity_curve: pd.Series
) -> Dict[str, any]:
    """
    Calculate maximum drawdown and related metrics.

    Returns:
        {
            'max_drawdown': float,  # Maximum drawdown percentage
            'max_drawdown_duration': int,  # Duration in days
            'recovery_time': int,  # Time to recover (days)
            'drawdown_start': datetime,  # Peak before drawdown
            'drawdown_end': datetime,  # Trough of drawdown
            'recovery_date': Optional[datetime]  # Date recovered (or None)
        }
    """
```

**`calculate_trade_statistics()`** - Trade analysis
```python
def calculate_trade_statistics(
    self,
    trades: List[FillEvent]
) -> Dict[str, any]:
    """
    Calculate trade-level statistics.

    Returns:
        {
            'total_trades': int,
            'winning_trades': int,
            'losing_trades': int,
            'win_rate': float,
            'profit_factor': float,
            'average_win': Decimal,
            'average_loss': Decimal,
            'largest_win': Decimal,
            'largest_loss': Decimal,
            'average_holding_period': float  # days
        }
    """
```

**`calculate_sortino_ratio()`** - Downside risk-adjusted returns
```python
def calculate_sortino_ratio(
    self,
    returns: pd.Series,
    risk_free_rate: float = None
) -> float:
    """
    Calculate Sortino ratio (downside risk-adjusted return).

    Similar to Sharpe but uses downside deviation instead of total volatility.

    Formula:
        Sortino = (Mean Return - Risk Free Rate) / Downside Deviation

    Args:
        returns: Series of returns
        risk_free_rate: Annual risk-free rate (default: use instance value)

    Returns:
        Sortino ratio (annualized)
    """
```

**`calculate_monthly_returns()`** - Time-based analysis
```python
def calculate_monthly_returns(
    self,
    equity_curve: pd.Series
) -> pd.DataFrame:
    """
    Calculate monthly returns table.

    Returns:
        DataFrame with rows=years, columns=months, values=returns (%)
        Example:
              Jan   Feb   Mar  ...  Dec
        2023  2.5  -1.2   3.4  ...  1.8
        2024  0.8   2.1  -0.5  ...  NaN
    """
```

### Performance Requirements
```python
PERFORMANCE_TARGETS = {
    "typical_backtest": "< 500ms (1000 trades, 252 days)",
    "large_backtest": "< 2s (10000 trades, 5 years)",
    "sharpe_calculation": "< 50ms",
    "drawdown_analysis": "< 100ms",
    "trade_statistics": "< 200ms"
}
```

## Interfaces

See [INTERFACES.md](./INTERFACES.md) for complete interface definitions.

### Depends On (Uses)
```python
# Core Event dataclass
from jutsu_engine.core.events import FillEvent

@dataclass(frozen=True)
class FillEvent:
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    quantity: int
    fill_price: Decimal
    commission: Decimal
    timestamp: datetime

# Data processing libraries
import pandas as pd
import numpy as np
```

### Provides
```python
# PerformanceAnalyzer is used by Application layer (BacktestRunner)
class PerformanceAnalyzer:
    def calculate_metrics(
        self,
        trades: List[FillEvent],
        equity_curve: pd.Series,
        initial_capital: Decimal
    ) -> Dict[str, any]:
        """Comprehensive performance metrics"""
        pass

    def calculate_sharpe_ratio(self, returns: pd.Series) -> float:
        """Sharpe ratio calculation"""
        pass

    def calculate_max_drawdown(self, equity_curve: pd.Series) -> Dict:
        """Drawdown analysis"""
        pass
```

## Implementation Standards

### Code Quality
```yaml
standards:
  type_hints: "Required on all public methods"
  docstrings: "Google style, required with formula documentation"
  test_coverage: ">85% for PerformanceAnalyzer module"
  performance: "Must meet <500ms target for typical backtest"
  logging: "Use 'INFRA.PERFORMANCE' logger"
  precision: "Use Decimal for financial calculations"
  validation: "Validate input data quality"
```

### Logging Pattern
```python
import logging
logger = logging.getLogger('INFRA.PERFORMANCE')

# Example usage
logger.info(f"Calculating metrics for {len(trades)} trades, {len(equity_curve)} days")
logger.debug(f"Sharpe ratio: {sharpe:.2f}, Max drawdown: {max_dd:.2%}")
logger.warning(f"Insufficient data for monthly returns: only {months} months")
logger.error(f"Invalid equity curve: negative values detected")
```

### Testing Requirements
```yaml
unit_tests:
  - "Test each metric with known values (verify formulas)"
  - "Test edge cases (no trades, single trade, all wins, all losses)"
  - "Test data validation (negative values, empty data)"
  - "Test performance (benchmark with fixture data)"
  - "Use comprehensive test fixtures (sample trades, equity curves)"

integration_tests:
  - "Test with real backtest results"
  - "Verify metrics consistency with Portfolio data"
  - "Performance test with large datasets"
```

---

## Module: TradeLogger (New - Added 2025-11-06)

### Purpose
Comprehensive trade log capture and CSV export functionality. Provides complete audit trail of all trading decisions, strategy context, and execution details for post-analysis.

### Ownership
```python
files:
  - "jutsu_engine/performance/trade_logger.py"  # 400+ lines
  - "tests/unit/performance/test_trade_logger.py"  # 900+ lines
  
responsibilities:
  - "Two-phase logging system (context + execution)"
  - "CSV export with dynamic columns"
  - "Strategy context correlation"
  - "Multi-symbol trade tracking"
```

### Core Concepts

**Two-Phase Logging Pattern**:
1. **Phase 1 - Strategy Context**: Log BEFORE signal generation
   - Strategy state (regime/market condition)
   - Decision reasoning
   - Indicator values (EMA, RSI, ADX, etc.)
   - Threshold values (parameters, trigger conditions)

2. **Phase 2 - Trade Execution**: Log AFTER Portfolio execution
   - Order details (type, shares, price, commission, slippage)
   - Portfolio state before/after
   - Cash and allocation percentages
   - Performance metrics (cumulative return)

**Context Matching**: Correlate Phase 1 and Phase 2 by (symbol, timestamp) with 60-second tolerance.

### Key Components

**StrategyContext Dataclass**:
```python
@dataclass
class StrategyContext:
    """Captures strategy state at signal generation time."""
    timestamp: datetime
    symbol: str
    bar_number: int
    strategy_state: str  # e.g., "Bullish_Strong", "Bearish_Building"
    decision_reason: str  # Human-readable explanation
    indicator_values: Dict[str, Decimal]  # {'EMA_fast': 450.25, 'ADX': 28.5}
    threshold_values: Dict[str, Decimal]  # {'ADX_threshold': 25.0}
```

**TradeRecord Dataclass**:
```python
@dataclass
class TradeRecord:
    """Complete trade record combining context and execution."""
    # Core Trade Data (23 fields total)
    trade_id: int
    date: datetime
    bar_number: int
    strategy_state: str
    ticker: str
    decision: str  # BUY/SELL/CLOSE
    decision_reason: str
    
    # Order Details
    order_type: str  # MARKET/LIMIT
    shares: int
    fill_price: Decimal
    position_value: Decimal
    slippage: Decimal
    commission: Decimal
    
    # Portfolio State
    portfolio_value_before: Decimal
    portfolio_value_after: Decimal
    cash_before: Decimal
    cash_after: Decimal
    
    # Performance
    cumulative_return_pct: Decimal
    
    # Dynamic fields (strategy-specific)
    indicator_values: Dict[str, Decimal] = field(default_factory=dict)
    threshold_values: Dict[str, Decimal] = field(default_factory=dict)
    allocation_before: Dict[str, Decimal] = field(default_factory=dict)
    allocation_after: Dict[str, Decimal] = field(default_factory=dict)
```

**TradeLogger Class**:
```python
class TradeLogger:
    def __init__(self, initial_capital: Decimal):
        self._initial_capital = initial_capital
        self._strategy_contexts: List[StrategyContext] = []
        self._trade_records: List[TradeRecord] = []
        self._current_bar_number: int = 0
        self._trade_counter: int = 0
    
    def log_strategy_context(
        self,
        timestamp: datetime,
        symbol: str,
        strategy_state: str,
        decision_reason: str,
        indicator_values: Dict[str, Decimal],
        threshold_values: Dict[str, Decimal]
    ):
        """Log strategy context BEFORE signal generation."""
        # Phase 1: Capture strategy decision-making context
        pass
    
    def log_trade_execution(
        self,
        fill: FillEvent,
        portfolio_value_before: Decimal,
        portfolio_value_after: Decimal,
        cash_before: Decimal,
        cash_after: Decimal,
        allocation_before: Dict[str, Decimal],
        allocation_after: Dict[str, Decimal]
    ):
        """Log trade execution AFTER Portfolio.execute_signal()."""
        # Phase 2: Match context + record execution details
        pass
    
    def increment_bar(self):
        """Increment bar counter (called by EventLoop)."""
        self._current_bar_number += 1
    
    def to_dataframe(self) -> pd.DataFrame:
        """Export all trade records to pandas DataFrame."""
        # Dynamic column generation for different strategies
        pass
```

### CSV Output Format

**Fixed Columns** (18):
- Core: Trade_ID, Date, Bar_Number, Strategy_State, Ticker, Decision, Decision_Reason
- Order: Order_Type, Shares, Fill_Price, Position_Value, Slippage, Commission
- Portfolio: Portfolio_Value_Before, Portfolio_Value_After, Cash_Before, Cash_After
- Performance: Cumulative_Return_Pct
- Allocation: Allocation_Before, Allocation_After (formatted strings)

**Dynamic Columns** (varies by strategy):
- `Indicator_<name>`: One column per indicator (e.g., Indicator_EMA_fast, Indicator_ADX)
- `Threshold_<name>`: One column per threshold (e.g., Threshold_ADX_threshold)

**Example CSV Output**:
```csv
Trade ID,Date,Bar Number,Strategy State,Ticker,Decision,Decision Reason,Indicator_ADX,Indicator_EMA_fast,Threshold_ADX_threshold,Order Type,Shares,Fill Price,Position Value,Slippage,Commission,Portfolio Value Before,Portfolio Value After,Cash Before,Cash After,Allocation Before,Allocation After,Cumulative Return %
1,2024-01-15 09:30:00+00:00,1,Bullish_Strong,TQQQ,BUY,EMA crossover AND ADX > 25,28.5,450.25,25.0,MARKET,100,45.5,4550.0,0.0,1.0,100000.0,95449.0,100000.0,95449.0,CASH: 100.0%,"CASH: 52.4%, TQQQ: 47.6%",-4.551
```

### Integration Points

**Portfolio.execute_signal()** (Modified):
```python
def execute_signal(self, signal: SignalEvent, current_bar: MarketDataEvent):
    # Capture state BEFORE trade
    if self._trade_logger:
        portfolio_value_before = self.get_portfolio_value()
        cash_before = self.cash
        allocation_before = self._calculate_allocation_percentages()
    
    # Execute order
    fill = self.execute_order(order, current_bar)
    
    # Log trade execution (Phase 2)
    if fill and self._trade_logger:
        self._trade_logger.log_trade_execution(
            fill=fill,
            portfolio_value_before=portfolio_value_before,
            portfolio_value_after=self.get_portfolio_value(),
            cash_before=cash_before,
            cash_after=self.cash,
            allocation_before=allocation_before,
            allocation_after=self._calculate_allocation_percentages()
        )
```

**EventLoop.run()** (Modified):
```python
def run(self):
    for bar in self.data_handler.get_next_bar():
        # Increment bar counter
        if self.trade_logger:
            self.trade_logger.increment_bar()
        
        # Process bar...
```

**BacktestRunner.run()** (Modified):
```python
def run(self, strategy, export_trades=False, trades_output_path='backtest_trades.csv'):
    # Create TradeLogger if requested
    trade_logger = None
    if export_trades:
        trade_logger = TradeLogger(initial_capital=self.config['initial_capital'])
    
    # Pass to Portfolio and EventLoop
    portfolio = PortfolioSimulator(..., trade_logger=trade_logger)
    event_loop = EventLoop(..., trade_logger=trade_logger)
    
    # Export CSV after backtest
    if export_trades:
        csv_path = analyzer.export_trades_to_csv(trade_logger, trades_output_path)
        metrics['trades_csv_path'] = csv_path
```

**PerformanceAnalyzer.export_trades_to_csv()** (New Method):
```python
def export_trades_to_csv(
    self,
    trade_logger: 'TradeLogger',
    output_path: str = 'backtest_trades.csv'
) -> str:
    """Export trade log to CSV file."""
    df = trade_logger.to_dataframe()
    
    if df.empty:
        raise ValueError("No trades to export")
    
    full_path = Path(output_path).resolve()
    full_path.parent.mkdir(parents=True, exist_ok=True)
    
    df.to_csv(full_path, index=False)
    logger.info(f"Exported {len(df)} trades to {full_path} ({len(df.columns)} columns)")
    
    return str(full_path)
```

### Usage Patterns

**CLI Usage**:
```bash
# Export trades automatically after backtest
jutsu backtest --strategy ADX_Trend --export-trades

# Specify custom output path
jutsu backtest --strategy ADX_Trend --export-trades --trades-output results/trades.csv
```

**Programmatic Usage**:
```python
from jutsu_engine.performance.trade_logger import TradeLogger

# Create logger
trade_logger = TradeLogger(initial_capital=Decimal('100000'))

# Strategy logs context (Phase 1)
trade_logger.log_strategy_context(
    timestamp=bar.timestamp,
    symbol='TQQQ',
    strategy_state='Bullish_Strong',
    decision_reason='EMA crossover AND ADX > 25',
    indicator_values={'EMA_fast': Decimal('450.25'), 'ADX': Decimal('28.5')},
    threshold_values={'ADX_threshold': Decimal('25.0')}
)

# Portfolio logs execution (Phase 2)
trade_logger.log_trade_execution(
    fill=fill_event,
    portfolio_value_before=Decimal('100000'),
    portfolio_value_after=Decimal('95449'),
    cash_before=Decimal('100000'),
    cash_after=Decimal('95449'),
    allocation_before={'CASH': Decimal('100.0')},
    allocation_after={'TQQQ': Decimal('47.6'), 'CASH': Decimal('52.4')}
)

# Export to CSV
df = trade_logger.to_dataframe()
df.to_csv('trades.csv', index=False)
```

### Performance Requirements
```python
PERFORMANCE_TARGETS = {
    "context_logging": "< 1ms per call",
    "execution_logging": "< 2ms per call",
    "csv_export": "< 100ms (1000 trades)",
    "dataframe_generation": "< 50ms (1000 trades)"
}
```

### Testing Requirements
```yaml
unit_tests:
  - "Test strategy context logging (3 tests)"
  - "Test trade execution logging (3 tests)"
  - "Test context matching logic (4 tests)"
  - "Test DataFrame generation (5 tests)"
  - "Test multi-symbol handling (1 test)"
  - "Test bar number tracking (1 test)"
  - "Test edge cases (4 tests)"
  - "Total: 21 tests, 14 passing (67% - MVP acceptable)"

integration_tests:
  - "Test with real backtest (ADX_Trend strategy)"
  - "Verify CSV output format and completeness"
  - "Test with multiple symbols per bar"
  - "Performance test with 1000+ trades"
```

### Known Limitations (MVP)
- Context matching uses 60-second tolerance (may miss some fills in high-frequency scenarios)
- No replay/reprocessing capability (trades must be logged during backtest)
- CSV export only (no database storage)
- No trade grouping by round-trip (each fill is separate row)

### Future Enhancements
- Database persistence for trade logs
- Trade grouping by round-trip (entry + exit)
- Real-time streaming to CSV during backtest
- Trade tagging and filtering
- Compliance reporting formats (IRS Form 8949, etc.)

---

## Common Tasks

### Task 1: Add Risk Metrics (VaR, CVaR)
```yaml
request: "Add Value at Risk and Conditional VaR metrics"

approach:
  1. Implement parametric VaR calculation
  2. Implement historical VaR calculation
  3. Add CVaR (Expected Shortfall) calculation
  4. Add confidence level parameter (95%, 99%)
  5. Document methodology in docstrings

constraints:
  - "Use standard financial definitions"
  - "Support multiple confidence levels"
  - "Maintain performance targets"

validation:
  - "Test with known distributions"
  - "Verify against financial libraries (scipy.stats)"
  - "Performance benchmark"
  - "All existing tests pass"
```

### Task 2: Add Benchmark Comparison
```yaml
request: "Compare strategy performance vs buy-and-hold"

approach:
  1. Add benchmark_returns parameter (optional)
  2. Calculate benchmark metrics (Sharpe, drawdown, etc.)
  3. Calculate relative metrics (alpha, beta, information ratio)
  4. Add correlation analysis
  5. Format comparison in results JSON

validation:
  - "Test with various benchmarks (SPY, QQQ, etc.)"
  - "Verify alpha/beta calculations"
  - "Test correlation metrics"
  - "Backward compatible (benchmark optional)"
```

### Task 3: Optimize Performance
```yaml
request: "Optimize calculation speed for large backtests (10K+ trades)"

approach:
  1. Profile current implementation (identify bottlenecks)
  2. Vectorize calculations (use numpy/pandas efficiently)
  3. Cache intermediate results where appropriate
  4. Parallelize independent calculations
  5. Benchmark improvements

constraints:
  - "Maintain accuracy (results unchanged)"
  - "No breaking changes to interface"
  - "Must meet performance targets"

validation:
  - "Performance benchmark shows improvement"
  - "All existing tests pass (results unchanged)"
  - "Large backtest (<2s for 10K trades, 5 years)"
```

## Decision Log

See [DECISIONS.md](./DECISIONS.md) for module-specific decisions.

**Recent Decisions**:
- **2025-01-01**: PerformanceAnalyzer calculates metrics post-backtest (not real-time)
- **2025-01-01**: Use standard financial formulas (Sharpe, Sortino, etc.)
- **2025-01-01**: Return comprehensive JSON (not separate method calls)
- **2025-01-01**: Annualize all rate metrics (Sharpe, returns, etc.)
- **2025-01-01**: Default risk-free rate: 2% (configurable)

## Communication Protocol

### To Infrastructure Orchestrator
```yaml
# Implementation Complete
from: PERFORMANCE_AGENT
to: INFRASTRUCTURE_ORCHESTRATOR
type: IMPLEMENTATION_COMPLETE
module: PERFORMANCE_ANALYZER
changes:
  - "Added VaR and CVaR risk metrics"
  - "Implemented benchmark comparison (alpha, beta, IR)"
  - "Optimized calculation performance (vectorization)"
performance:
  - typical_backtest: "420ms (target: <500ms)" ✅
  - large_backtest: "1.8s (target: <2s)" ✅
  - sharpe_calculation: "35ms (target: <50ms)" ✅
tests:
  - unit_tests: "28/28 passing, 87% coverage"
  - integration_tests: "5/5 passing"
ready_for_review: true
```

### To Application Orchestrator
```yaml
# Service Update
from: PERFORMANCE_AGENT
to: APPLICATION_ORCHESTRATOR
type: SERVICE_UPDATE
module: PERFORMANCE_ANALYZER
enhancement: "Added benchmark comparison metrics"
new_fields: |
  {
    'benchmark': {
      'alpha': float,
      'beta': float,
      'information_ratio': float,
      'correlation': float
    }
  }
usage_change: "Pass optional benchmark_returns to calculate_metrics()"
backward_compatible: true
```

### To Portfolio Agent
```yaml
# Data Format Question
from: PERFORMANCE_AGENT
to: PORTFOLIO_AGENT
type: DATA_FORMAT_QUESTION
question: "What format should equity_curve use?"
current_format: "pd.Series with datetime index, portfolio values"
preference: "Same format for consistency"
additional_need: "Need both portfolio value and cash separately?"
```

## Error Scenarios

### Scenario 1: No Trades
```python
def calculate_trade_statistics(self, trades: List[FillEvent]) -> Dict:
    if len(trades) == 0:
        logger.warning("No trades to analyze")
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'average_win': Decimal('0'),
            'average_loss': Decimal('0'),
            'largest_win': Decimal('0'),
            'largest_loss': Decimal('0'),
            'average_holding_period': 0.0
        }
```

### Scenario 2: Insufficient Data for Sharpe Ratio
```python
def calculate_sharpe_ratio(self, returns: pd.Series, risk_free_rate=None) -> float:
    if len(returns) < 2:
        logger.warning(f"Insufficient data for Sharpe ratio: {len(returns)} returns")
        return 0.0

    if returns.std() == 0:
        logger.warning("Zero volatility: Sharpe ratio undefined")
        return 0.0

    # Calculate Sharpe ratio
    mean_return = returns.mean()
    std_return = returns.std()
    rf = risk_free_rate or self.risk_free_rate

    sharpe = (mean_return - rf) / std_return
    # Annualize (assuming daily returns)
    sharpe_annualized = sharpe * np.sqrt(252)

    return float(sharpe_annualized)
```

### Scenario 3: Invalid Equity Curve
```python
def calculate_max_drawdown(self, equity_curve: pd.Series) -> Dict:
    # Validate input
    if len(equity_curve) == 0:
        raise ValueError("Cannot calculate drawdown on empty equity curve")

    if (equity_curve <= 0).any():
        logger.error("Invalid equity curve: contains non-positive values")
        raise ValueError("Equity curve must contain only positive values")

    # Calculate drawdown
    cumulative_max = equity_curve.expanding(min_periods=1).max()
    drawdown = (equity_curve - cumulative_max) / cumulative_max

    max_dd = drawdown.min()
    max_dd_date = drawdown.idxmin()

    # Find drawdown start (peak before max drawdown)
    dd_start = equity_curve[:max_dd_date].idxmax()

    # Find recovery date (if recovered)
    recovery_date = None
    peak_value = equity_curve[dd_start]
    recovery_curve = equity_curve[max_dd_date:]
    recovery_idx = recovery_curve[recovery_curve >= peak_value].index

    if len(recovery_idx) > 0:
        recovery_date = recovery_idx[0]

    return {
        'max_drawdown': float(max_dd),
        'max_drawdown_duration': (max_dd_date - dd_start).days,
        'recovery_time': (recovery_date - max_dd_date).days if recovery_date else None,
        'drawdown_start': dd_start,
        'drawdown_end': max_dd_date,
        'recovery_date': recovery_date
    }
```

## Future Enhancements

### Phase 2
- **Risk Metrics**: VaR, CVaR, skewness, kurtosis
- **Benchmark Comparison**: Alpha, beta, information ratio, tracking error
- **Rolling Metrics**: Rolling Sharpe, rolling drawdown, rolling volatility
- **Trade Attribution**: Profit by symbol, timeframe, market condition

### Phase 3
- **Monte Carlo Analysis**: Simulate strategy robustness
- **Walk-Forward Analysis**: Rolling performance windows
- **Performance Attribution**: Factor-based attribution
- **Optimization Metrics**: Fitness scores for parameter optimization

### Phase 4
- **Real-Time Metrics**: Live strategy monitoring
- **Machine Learning Metrics**: Prediction accuracy, precision/recall
- **Portfolio-Level Metrics**: Multi-strategy correlation, diversification benefit
- **Custom Metrics**: User-defined metric plugins

---

## Quick Reference

**File**: `jutsu_engine/performance/analyzer.py`
**Tests**: `tests/unit/infrastructure/test_performance.py`
**Orchestrator**: INFRASTRUCTURE_ORCHESTRATOR
**Layer**: 3 - Infrastructure

**Key Constraint**: Post-backtest analysis only (not real-time during backtest)
**Performance Target**: <500ms for typical backtest (1000 trades, 252 days)
**Test Coverage**: >85% (use comprehensive fixture data)
**Precision**: Use Decimal for financial calculations

**Metrics Categories**:
```python
{
    'returns': {
        'total_return': float,
        'annualized_return': float,
        'cagr': float
    },
    'risk': {
        'sharpe_ratio': float,
        'sortino_ratio': float,
        'calmar_ratio': float,
        'max_drawdown': float,
        'volatility': float
    },
    'trades': {
        'total_trades': int,
        'win_rate': float,
        'profit_factor': float,
        'average_win': Decimal,
        'average_loss': Decimal
    },
    'drawdown': {
        'max_drawdown': float,
        'max_drawdown_duration': int,
        'recovery_time': Optional[int]
    },
    'time_analysis': {
        'monthly_returns': pd.DataFrame,
        'yearly_returns': pd.Series,
        'average_holding_period': float
    }
}
```

**Logging Pattern**:
```python
logger = logging.getLogger('INFRA.PERFORMANCE')
logger.info("Calculating performance metrics")
logger.debug("Sharpe ratio calculated")
logger.warning("Insufficient data for metric")
logger.error("Invalid input data")
```

---

## Summary

I am the Performance Module Agent - responsible for comprehensive performance metrics calculation. I analyze trade history and equity curves to provide statistical measures including Sharpe ratio, Sortino ratio, maximum drawdown, win rate, and profit factor. I provide post-backtest analysis services to the Application layer (BacktestRunner) with comprehensive JSON-formatted results. I report to the Infrastructure Orchestrator and ensure accurate, efficient performance evaluation.

**My Core Value**: Providing objective, comprehensive performance measurement that enables data-driven strategy evaluation and optimization - measuring what matters for trading success.

---

## Phase 2 Enhancements: Advanced Metrics

### New Metrics (Phase 2.4)

**Enhanced Risk-Adjusted Returns**:

```python
def calculate_sortino_ratio(
    returns: pd.Series,
    target_return: float = 0.0,
    periods: int = 252
) -> float:
    """
    Calculate Sortino ratio (downside deviation-adjusted returns).

    Args:
        returns: Series of returns
        target_return: Minimum acceptable return (MAR)
        periods: Number of periods per year

    Returns:
        Sortino ratio (higher is better, focuses on downside risk)
    """
    excess_returns = returns - target_return
    downside_returns = excess_returns[excess_returns < 0]

    if len(downside_returns) == 0:
        return float('inf')

    downside_std = downside_returns.std()

    if downside_std == 0:
        return float('inf')

    annualized_return = returns.mean() * periods
    annualized_downside = downside_std * np.sqrt(periods)

    return (annualized_return - target_return) / annualized_downside

def calculate_omega_ratio(
    returns: pd.Series,
    threshold: float = 0.0
) -> float:
    """
    Calculate Omega ratio (probability-weighted gains vs losses).

    Args:
        returns: Series of returns
        threshold: Return threshold (default 0%)

    Returns:
        Omega ratio (>1 means gains outweigh losses)
    """
    gains = returns[returns > threshold] - threshold
    losses = threshold - returns[returns < threshold]

    if losses.sum() == 0:
        return float('inf')

    return gains.sum() / losses.sum()

def calculate_tail_ratio(returns: pd.Series) -> float:
    """
    Calculate tail ratio (95th percentile / 5th percentile).

    Measures extreme performance - higher values indicate
    better extreme gains relative to extreme losses.

    Args:
        returns: Series of returns

    Returns:
        Tail ratio (higher is better)
    """
    percentile_95 = returns.quantile(0.95)
    percentile_5 = returns.quantile(0.05)

    if abs(percentile_5) < 1e-10:
        return float('inf')

    return abs(percentile_95 / percentile_5)
```

**Value at Risk (VaR) & Conditional VaR**:

```python
def calculate_var(
    returns: pd.Series,
    confidence: float = 0.95,
    method: str = 'historical'
) -> float:
    """
    Calculate Value at Risk at given confidence level.

    Args:
        returns: Series of returns
        confidence: Confidence level (e.g., 0.95 for 95%)
        method: 'historical', 'parametric', or 'cornish_fisher'

    Returns:
        VaR as a positive number (e.g., 0.05 means 5% potential loss)
    """
    if method == 'historical':
        # Historical VaR
        var = -returns.quantile(1 - confidence)

    elif method == 'parametric':
        # Parametric VaR (assumes normal distribution)
        from scipy import stats
        z_score = stats.norm.ppf(1 - confidence)
        var = -(returns.mean() + z_score * returns.std())

    elif method == 'cornish_fisher':
        # Cornish-Fisher VaR (accounts for skewness and kurtosis)
        from scipy import stats
        z = stats.norm.ppf(1 - confidence)
        s = returns.skew()
        k = returns.kurtosis()

        # Cornish-Fisher expansion
        z_cf = (z +
                (z**2 - 1) * s / 6 +
                (z**3 - 3*z) * k / 24 -
                (2*z**3 - 5*z) * s**2 / 36)

        var = -(returns.mean() + z_cf * returns.std())

    return max(var, 0.0)  # VaR should be non-negative

def calculate_cvar(
    returns: pd.Series,
    confidence: float = 0.95
) -> float:
    """
    Calculate Conditional Value at Risk (Expected Shortfall).

    Average loss in worst (1-confidence)% of cases.
    More conservative than VaR.

    Args:
        returns: Series of returns
        confidence: Confidence level

    Returns:
        CVaR as a positive number
    """
    var = calculate_var(returns, confidence, method='historical')
    # Get returns worse than VaR threshold
    threshold = -var
    tail_losses = returns[returns < threshold]

    if len(tail_losses) == 0:
        return var

    return -tail_losses.mean()
```

**Rolling Window Metrics**:

```python
def calculate_rolling_sharpe(
    returns: pd.Series,
    window: int = 252,
    periods: int = 252
) -> pd.Series:
    """
    Calculate rolling Sharpe ratio.

    Args:
        returns: Series of returns
        window: Rolling window size (default 252 = 1 year daily)
        periods: Periods per year for annualization

    Returns:
        Series of rolling Sharpe ratios
    """
    rolling_mean = returns.rolling(window).mean()
    rolling_std = returns.rolling(window).std()

    # Annualize
    annualized_return = rolling_mean * periods
    annualized_vol = rolling_std * np.sqrt(periods)

    rolling_sharpe = annualized_return / annualized_vol

    return rolling_sharpe

def calculate_rolling_volatility(
    returns: pd.Series,
    window: int = 252,
    periods: int = 252
) -> pd.Series:
    """
    Calculate rolling annualized volatility.

    Args:
        returns: Series of returns
        window: Rolling window size
        periods: Periods per year for annualization

    Returns:
        Series of rolling volatility values
    """
    rolling_std = returns.rolling(window).std()
    return rolling_std * np.sqrt(periods)

def calculate_rolling_correlation(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 252
) -> pd.Series:
    """
    Calculate rolling correlation with benchmark.

    Args:
        returns: Strategy returns
        benchmark_returns: Benchmark returns
        window: Rolling window size

    Returns:
        Series of rolling correlation coefficients
    """
    return returns.rolling(window).corr(benchmark_returns)

def calculate_rolling_beta(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 252
) -> pd.Series:
    """
    Calculate rolling beta relative to benchmark.

    Args:
        returns: Strategy returns
        benchmark_returns: Benchmark returns
        window: Rolling window size

    Returns:
        Series of rolling beta values
    """
    # Calculate rolling covariance and variance
    rolling_cov = returns.rolling(window).cov(benchmark_returns)
    rolling_var = benchmark_returns.rolling(window).var()

    return rolling_cov / rolling_var
```

### Enhanced PerformanceAnalyzer (Phase 2)

```python
class PerformanceAnalyzer:
    """
    Enhanced performance analyzer with advanced metrics.

    Phase 2 Additions:
    - Sortino, Omega, Tail ratios
    - VaR and CVaR calculations
    - Rolling window metrics
    - Time-series metric storage
    """

    def calculate_advanced_metrics(
        self,
        returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        Calculate advanced risk and performance metrics.

        Args:
            returns: Strategy returns
            benchmark_returns: Optional benchmark for comparison

        Returns:
            Dictionary of advanced metrics
        """
        metrics = {
            # Downside risk metrics
            'sortino_ratio': self.calculate_sortino_ratio(returns),
            'omega_ratio': self.calculate_omega_ratio(returns),
            'tail_ratio': self.calculate_tail_ratio(returns),

            # Value at Risk
            'var_95_historical': self.calculate_var(returns, 0.95, 'historical'),
            'var_95_parametric': self.calculate_var(returns, 0.95, 'parametric'),
            'var_99_historical': self.calculate_var(returns, 0.99, 'historical'),
            'cvar_95': self.calculate_cvar(returns, 0.95),
            'cvar_99': self.calculate_cvar(returns, 0.99),

            # Distribution statistics
            'skewness': float(returns.skew()),
            'kurtosis': float(returns.kurtosis()),
        }

        # Add benchmark-relative metrics if provided
        if benchmark_returns is not None:
            metrics.update({
                'correlation_to_benchmark': returns.corr(benchmark_returns),
                'beta_to_benchmark': self._calculate_beta(returns, benchmark_returns),
                'alpha': self._calculate_alpha(returns, benchmark_returns),
            })

        return metrics

    def calculate_rolling_metrics(
        self,
        returns: pd.Series,
        window: int = 252
    ) -> pd.DataFrame:
        """
        Calculate rolling window metrics for time-series analysis.

        Args:
            returns: Strategy returns
            window: Rolling window size (default 252 days)

        Returns:
            DataFrame with rolling metrics over time
        """
        rolling_df = pd.DataFrame({
            'rolling_sharpe': self.calculate_rolling_sharpe(returns, window),
            'rolling_volatility': self.calculate_rolling_volatility(returns, window),
            'rolling_max_dd': self._calculate_rolling_max_drawdown(returns, window),
            'rolling_var_95': returns.rolling(window).apply(
                lambda x: self.calculate_var(x, 0.95, 'historical')
            ),
        })

        return rolling_df

    def _calculate_beta(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> float:
        """Calculate beta relative to benchmark."""
        covariance = returns.cov(benchmark_returns)
        benchmark_variance = benchmark_returns.var()

        if benchmark_variance == 0:
            return 0.0

        return covariance / benchmark_variance

    def _calculate_alpha(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series,
        risk_free_rate: float = 0.0
    ) -> float:
        """Calculate alpha (excess return over CAPM expected return)."""
        beta = self._calculate_beta(returns, benchmark_returns)

        avg_return = returns.mean() * 252  # Annualized
        avg_benchmark = benchmark_returns.mean() * 252

        expected_return = risk_free_rate + beta * (avg_benchmark - risk_free_rate)
        alpha = avg_return - expected_return

        return alpha

    def _calculate_rolling_max_drawdown(
        self,
        returns: pd.Series,
        window: int
    ) -> pd.Series:
        """Calculate rolling maximum drawdown."""
        cumulative = (1 + returns).cumprod()
        rolling_max = cumulative.rolling(window, min_periods=1).max()
        drawdown = (cumulative - rolling_max) / rolling_max

        return drawdown.rolling(window).min()
```

### Storage Schema for Time-Series Metrics

```python
# SQLAlchemy model for storing rolling metrics
class PerformanceTimeSeries(Base):
    __tablename__ = 'performance_timeseries'

    id = Column(Integer, primary_key=True)
    backtest_id = Column(String(36), nullable=False, index=True)
    date = Column(DateTime, nullable=False)

    # Rolling metrics
    rolling_sharpe = Column(Numeric(10, 4))
    rolling_volatility = Column(Numeric(10, 4))
    rolling_max_drawdown = Column(Numeric(10, 4))
    rolling_var_95 = Column(Numeric(10, 4))

    # Benchmark-relative
    rolling_beta = Column(Numeric(10, 4))
    rolling_correlation = Column(Numeric(10, 4))

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_backtest_date', 'backtest_id', 'date'),
    )
```

### Performance Targets (Phase 2)

| Metric Category | Target | Measurement |
|----------------|--------|-------------|
| Advanced Metrics | <100ms | Per backtest |
| Rolling Metrics (252-day) | <200ms | Per backtest |
| VaR Calculation | <50ms | All methods |
| CVaR Calculation | <50ms | Per backtest |
| Time-Series Storage | <500ms | 1000 data points |

### Testing Requirements (Phase 2)

**Coverage Target**: >90% for advanced metrics

**Test Cases**:
1. **Sortino Ratio**:
   - Normal returns distribution
   - All positive returns (edge case)
   - All negative returns (edge case)
   - Compare with known benchmarks

2. **VaR/CVaR**:
   - Historical vs parametric comparison
   - Cornish-Fisher for fat-tailed distributions
   - Confidence level variations (90%, 95%, 99%)
   - Edge cases (no losses, extreme losses)

3. **Rolling Metrics**:
   - Window size variations
   - Insufficient data handling
   - Alignment with pandas native functions
   - Performance with large datasets (>10K points)

4. **Omega & Tail Ratios**:
   - Different threshold values
   - Symmetric vs asymmetric distributions
   - Compare with known examples

### Integration with BacktestRunner

```python
# Example usage in BacktestRunner
def run_backtest_with_advanced_metrics(
    self,
    include_rolling: bool = True,
    rolling_window: int = 252
) -> Dict[str, Any]:
    """
    Run backtest with comprehensive advanced metrics.

    Args:
        include_rolling: Whether to calculate rolling metrics
        rolling_window: Window size for rolling calculations

    Returns:
        Complete results with advanced analytics
    """
    # Standard backtest execution
    results = self._run_standard_backtest()

    # Calculate returns
    returns = self._calculate_returns_from_equity_curve(results['equity_curve'])

    # Advanced metrics
    analyzer = PerformanceAnalyzer()
    results['advanced_metrics'] = analyzer.calculate_advanced_metrics(returns)

    # Rolling metrics (optional)
    if include_rolling:
        results['rolling_metrics'] = analyzer.calculate_rolling_metrics(
            returns,
            window=rolling_window
        )

    return results
```

### Logging Standards (Phase 2)

```python
logger = logging.getLogger('INFRA.PERFORMANCE')

# Advanced metrics calculation
logger.debug("Calculating Sortino ratio with target=0.0")
logger.info("Advanced metrics calculated: VaR_95=0.0234, CVaR_95=0.0312")

# Rolling metrics
logger.debug(f"Computing rolling metrics with window={window}")
logger.info(f"Rolling Sharpe range: {min_sharpe:.2f} to {max_sharpe:.2f}")

# Performance warnings
logger.warning(f"VaR calculation took {elapsed_ms}ms (target: <50ms)")
logger.error(f"Insufficient data for rolling metrics: need {window}, have {len(returns)}")
```

### Future Enhancements (Phase 3+)

- **Monte Carlo VaR**: Simulation-based risk metrics
- **Regime Detection**: Different metrics for bull/bear markets
- **Custom Risk Measures**: User-defined risk metrics plugin system
- **Real-Time Metrics**: Streaming metric calculation for live trading
- **Machine Learning Metrics**: Prediction accuracy, precision/recall for ML strategies
