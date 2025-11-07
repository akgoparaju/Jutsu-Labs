# TradeLogger Design (2025-11-06)

## Purpose

Export comprehensive CSV trade logs capturing:
- Trade execution details (symbol, shares, price, commission)
- Strategy state (indicators, thresholds, regime)
- Portfolio state (cash, positions, allocation percentages)
- Decision rationale (why trade was made)

## User Requirements

**Output Timing**: Both automatic (default location) AND on-demand via CLI flag

**CSV Columns** (from user specification):
1. **Core Trade Data**:
   - Trade ID (sequential number)
   - Date (timestamp)
   - Bar Number (sequential bar count)
   - Strategy State (e.g., "Regime 1: Strong Bullish")
   - Ticker (symbol traded)
   - Decision (BUY/SELL/CLOSE)
   - Decision Reason (explanation text)

2. **Indicator Values** (dynamic columns based on strategy):
   - Example: "EMA_fast", "EMA_slow", "ADX_val" for ADX_Trend
   - Different strategies have different indicators
   - Column names and values from strategy context

3. **Thresholds** (dynamic columns based on strategy):
   - Strategy parameters: "adx_threshold_low", "adx_threshold_high"
   - Trigger conditions: "EMA_fast > EMA_slow", "ADX > 25"
   - Both static params and dynamic conditions

4. **Order Details**:
   - Order Type (MARKET/LIMIT/STOP - MVP: only MARKET)
   - Shares (quantity executed)
   - Fill Price (execution price)
   - Position Value (shares × fill_price)
   - Slippage (currently 0 in MVP)
   - Commission (per-trade cost)

5. **Portfolio State**:
   - Portfolio Value Before (before trade)
   - Portfolio Value After (after trade)
   - Cash Before
   - Cash After
   - Allocation Before (e.g., "TQQQ: 60.0%, CASH: 40.0%")
   - Allocation After

6. **Performance**:
   - Cumulative Return % (since backtest start)

**Multi-Symbol Handling**: One row per symbol traded (separate rows for each fill)

## Architecture Constraints

**Owner**: PERFORMANCE_AGENT (jutsu_engine/performance/)

**Dependencies Allowed** (from PERFORMANCE_AGENT.md):
- ✅ Core Events (FillEvent, SignalEvent, MarketDataEvent)
- ✅ pandas, numpy, Decimal
- ✅ dataclasses, typing

**Dependencies Forbidden**:
- ❌ Cannot import Application layer (BacktestRunner)
- ❌ Cannot import Entry Points

**Integration Points**:
- Portfolio.execute_signal() → Log trade data
- Strategy (via EventLoop) → Log strategy context
- PerformanceAnalyzer → Export CSV from logs

## Data Flow Analysis

### Trade Execution Flow (from architecture memory)

```
Strategy.on_bar(bar)
  ├─ Calculate indicators (EMA_fast, EMA_slow, ADX)
  ├─ Determine regime/state
  ├─ Generate SignalEvent(symbol, signal_type, portfolio_percent)
  └─ EventLoop receives SignalEvent
       │
       ├─ Portfolio.execute_signal(signal, current_bar)
       │    ├─ Update _latest_prices[symbol]
       │    ├─ Get portfolio_value (cash + holdings)
       │    ├─ Calculate allocation_amount (portfolio_value × portfolio_percent)
       │    ├─ Calculate shares (_calculate_long_shares or _calculate_short_shares)
       │    ├─ Update positions and cash
       │    └─ Return FillEvent(symbol, direction, quantity, fill_price, commission, timestamp)
       │
       └─ Return FillEvent to EventLoop
```

### Data Availability Points

**During Strategy.on_bar()** (BEFORE SignalEvent):
- ✅ Indicator values (EMA_fast, EMA_slow, ADX_val)
- ✅ Thresholds (adx_threshold_low, adx_threshold_high)
- ✅ Regime/state ("Regime 1: Strong Bullish")
- ✅ Decision reason ("EMA crossover AND ADX > 25")
- ❌ Trade execution details (not yet executed)
- ❌ Portfolio state changes (not yet applied)

**During Portfolio.execute_signal()** (AFTER SignalEvent, BEFORE FillEvent):
- ✅ Portfolio value BEFORE trade
- ✅ Cash BEFORE trade
- ✅ Positions BEFORE trade
- ✅ Allocation BEFORE trade
- ❌ Indicator values (not passed through SignalEvent)
- ❌ Regime/state (not in SignalEvent)

**After FillEvent returned**:
- ✅ All execution details (symbol, shares, fill_price, commission)
- ✅ Portfolio value AFTER trade
- ✅ Cash AFTER trade
- ✅ Positions AFTER trade
- ✅ Allocation AFTER trade
- ❌ Indicator values (lost unless captured earlier)
- ❌ Regime/state (lost unless captured earlier)

### The Challenge: Strategy Context

**Problem**: Indicator values and regime are NOT in SignalEvent or FillEvent.

**Why Not Add to SignalEvent?**
- SignalEvent is Core domain event (immutable interface)
- Adding strategy-specific fields breaks Core/Infrastructure separation
- Different strategies have different indicators (not uniform schema)

**Solution Options**:

1. **Option A: Extend SignalEvent with metadata dict** (REJECTED - breaks architecture)
2. **Option B: Log strategy context separately** (SELECTED)
   - TradeLogger has two logging methods:
     - `log_strategy_context()`: Called by Strategy BEFORE generating signal
     - `log_trade_execution()`: Called by Portfolio AFTER executing fill
   - Match strategy context to trade via (symbol, timestamp) correlation

3. **Option C: EventLoop coordinates logging** (MORE COMPLEX - defer to future)

## TradeLogger Class Design

### Location
`jutsu_engine/performance/trade_logger.py`

### Data Structures

```python
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd

@dataclass
class StrategyContext:
    """
    Captures strategy state at signal generation time.
    
    Attributes:
        timestamp: When context was captured
        symbol: Symbol being analyzed (may differ from symbol traded)
        bar_number: Sequential bar count
        strategy_state: Human-readable state (e.g., "Regime 1: Strong Bullish")
        decision_reason: Why signal was generated
        indicator_values: Dict of indicator names → values (dynamic)
        threshold_values: Dict of threshold names → values (dynamic)
    """
    timestamp: datetime
    symbol: str
    bar_number: int
    strategy_state: str
    decision_reason: str
    indicator_values: Dict[str, Decimal] = field(default_factory=dict)
    threshold_values: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class TradeRecord:
    """
    Complete trade record combining strategy context and execution details.
    
    Matches user's required CSV columns.
    """
    # Core Trade Data
    trade_id: int
    date: datetime
    bar_number: int
    strategy_state: str
    ticker: str
    decision: str  # BUY/SELL/CLOSE
    decision_reason: str
    
    # Indicator Values (dynamic - flattened from dict)
    indicator_values: Dict[str, Decimal] = field(default_factory=dict)
    
    # Thresholds (dynamic - flattened from dict)
    threshold_values: Dict[str, Decimal] = field(default_factory=dict)
    
    # Order Details
    order_type: str  # MARKET (MVP only)
    shares: int
    fill_price: Decimal
    position_value: Decimal  # shares × fill_price
    slippage: Decimal  # 0 in MVP
    commission: Decimal
    
    # Portfolio State
    portfolio_value_before: Decimal
    portfolio_value_after: Decimal
    cash_before: Decimal
    cash_after: Decimal
    allocation_before: Dict[str, Decimal]  # {symbol: percent}
    allocation_after: Dict[str, Decimal]
    
    # Performance
    cumulative_return_pct: Decimal


class TradeLogger:
    """
    Captures trade data for CSV export.
    
    Two-phase logging:
    1. Strategy phase: log_strategy_context() - indicators, thresholds, regime
    2. Execution phase: log_trade_execution() - portfolio state, fill details
    
    Correlation: Match strategy context to trade via (symbol, timestamp) proximity
    """
    
    def __init__(self, initial_capital: Decimal):
        self._initial_capital = initial_capital
        self._trade_counter = 0
        self._bar_counter = 0
        
        # Storage
        self._strategy_contexts: List[StrategyContext] = []
        self._trade_records: List[TradeRecord] = []
        
    def increment_bar(self) -> None:
        """Called by EventLoop on each bar."""
        self._bar_counter += 1
    
    def log_strategy_context(
        self,
        timestamp: datetime,
        symbol: str,
        strategy_state: str,
        decision_reason: str,
        indicator_values: Dict[str, Decimal],
        threshold_values: Dict[str, Decimal]
    ) -> None:
        """
        Log strategy context BEFORE signal generation.
        
        Called by Strategy in on_bar() when decision is made.
        """
        context = StrategyContext(
            timestamp=timestamp,
            symbol=symbol,
            bar_number=self._bar_counter,
            strategy_state=strategy_state,
            decision_reason=decision_reason,
            indicator_values=indicator_values.copy(),
            threshold_values=threshold_values.copy()
        )
        self._strategy_contexts.append(context)
    
    def log_trade_execution(
        self,
        fill: FillEvent,
        portfolio_value_before: Decimal,
        portfolio_value_after: Decimal,
        cash_before: Decimal,
        cash_after: Decimal,
        allocation_before: Dict[str, Decimal],
        allocation_after: Dict[str, Decimal]
    ) -> None:
        """
        Log trade execution AFTER Portfolio.execute_signal().
        
        Matches with most recent StrategyContext for this symbol.
        """
        # Find matching strategy context
        context = self._find_matching_context(fill.symbol, fill.timestamp)
        
        # Calculate cumulative return
        current_value = portfolio_value_after
        cumulative_return = ((current_value - self._initial_capital) / self._initial_capital) * Decimal('100')
        
        # Create trade record
        self._trade_counter += 1
        record = TradeRecord(
            trade_id=self._trade_counter,
            date=fill.timestamp,
            bar_number=context.bar_number if context else self._bar_counter,
            strategy_state=context.strategy_state if context else "Unknown",
            ticker=fill.symbol,
            decision=fill.direction,  # BUY/SELL
            decision_reason=context.decision_reason if context else "No context",
            indicator_values=context.indicator_values.copy() if context else {},
            threshold_values=context.threshold_values.copy() if context else {},
            order_type="MARKET",
            shares=fill.quantity,
            fill_price=fill.fill_price,
            position_value=fill.fill_price * Decimal(fill.quantity),
            slippage=Decimal('0'),  # MVP: no slippage
            commission=fill.commission,
            portfolio_value_before=portfolio_value_before,
            portfolio_value_after=portfolio_value_after,
            cash_before=cash_before,
            cash_after=cash_after,
            allocation_before=allocation_before.copy(),
            allocation_after=allocation_after.copy(),
            cumulative_return_pct=cumulative_return
        )
        
        self._trade_records.append(record)
    
    def _find_matching_context(self, symbol: str, timestamp: datetime) -> Optional[StrategyContext]:
        """
        Find most recent StrategyContext for this symbol.
        
        Matching strategy:
        1. Filter by symbol (exact match)
        2. Filter by timestamp (within same bar - tolerance 1 second)
        3. Return most recent match
        """
        # For signal asset pattern (e.g., QQQ signal → TQQQ trade),
        # we might need fuzzy matching or explicit signal_asset tracking
        # MVP: Use exact symbol match for simplicity
        
        matches = [
            ctx for ctx in self._strategy_contexts
            if ctx.symbol == symbol and abs((ctx.timestamp - timestamp).total_seconds()) < 60
        ]
        
        return matches[-1] if matches else None
    
    def get_trade_records(self) -> List[TradeRecord]:
        """Get all trade records for CSV export."""
        return self._trade_records.copy()
    
    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert trade records to DataFrame for CSV export.
        
        Handles dynamic columns (indicators, thresholds, allocations).
        """
        if not self._trade_records:
            return pd.DataFrame()
        
        # Extract all indicator names across all records
        all_indicators = set()
        for record in self._trade_records:
            all_indicators.update(record.indicator_values.keys())
        
        # Extract all threshold names
        all_thresholds = set()
        for record in self._trade_records:
            all_thresholds.update(record.threshold_values.keys())
        
        # Build DataFrame rows
        rows = []
        for record in self._trade_records:
            row = {
                'Trade ID': record.trade_id,
                'Date': record.date,
                'Bar Number': record.bar_number,
                'Strategy State': record.strategy_state,
                'Ticker': record.ticker,
                'Decision': record.decision,
                'Decision Reason': record.decision_reason,
            }
            
            # Add indicator columns (dynamic)
            for ind_name in sorted(all_indicators):
                row[f'Indicator_{ind_name}'] = record.indicator_values.get(ind_name, None)
            
            # Add threshold columns (dynamic)
            for thresh_name in sorted(all_thresholds):
                row[f'Threshold_{thresh_name}'] = record.threshold_values.get(thresh_name, None)
            
            # Add order details
            row.update({
                'Order Type': record.order_type,
                'Shares': record.shares,
                'Fill Price': float(record.fill_price),
                'Position Value': float(record.position_value),
                'Slippage': float(record.slippage),
                'Commission': float(record.commission),
            })
            
            # Add portfolio state
            row.update({
                'Portfolio Value Before': float(record.portfolio_value_before),
                'Portfolio Value After': float(record.portfolio_value_after),
                'Cash Before': float(record.cash_before),
                'Cash After': float(record.cash_after),
            })
            
            # Add allocation (formatted as "TQQQ: 60.0%, CASH: 40.0%")
            row['Allocation Before'] = self._format_allocation(record.allocation_before)
            row['Allocation After'] = self._format_allocation(record.allocation_after)
            
            # Add performance
            row['Cumulative Return %'] = float(record.cumulative_return_pct)
            
            rows.append(row)
        
        return pd.DataFrame(rows)
    
    def _format_allocation(self, allocation: Dict[str, Decimal]) -> str:
        """Format allocation dict as percentage string."""
        if not allocation:
            return "CASH: 100.0%"
        
        parts = [f"{symbol}: {float(pct):.1f}%" for symbol, pct in sorted(allocation.items())]
        return ", ".join(parts)
```

## Integration Points

### 1. Portfolio.execute_signal() Integration

**File**: `jutsu_engine/portfolio/simulator.py`

**Change**: Add TradeLogger parameter and logging calls

```python
class PortfolioSimulator:
    def __init__(
        self,
        initial_capital: Decimal,
        commission_per_share: Decimal = Decimal('0.01'),
        trade_logger: Optional['TradeLogger'] = None  # NEW
    ):
        # ... existing fields ...
        self._trade_logger = trade_logger  # NEW
    
    def execute_signal(
        self,
        signal: SignalEvent,
        current_bar: MarketDataEvent
    ) -> Optional[FillEvent]:
        """Execute a signal from the strategy."""
        # Capture state BEFORE trade
        portfolio_value_before = self.get_portfolio_value()
        cash_before = self.cash
        allocation_before = self._calculate_allocation_percentages() if self._trade_logger else {}
        
        # Execute trade (existing logic)
        self._latest_prices[signal.symbol] = current_bar.close
        portfolio_value = self.get_portfolio_value()
        allocation_amount = portfolio_value * signal.portfolio_percent
        
        if signal.signal_type == 'BUY':
            shares = self._calculate_long_shares(allocation_amount, current_bar.close)
            fill = self._execute_buy(signal.symbol, shares, current_bar.close, current_bar.timestamp)
        else:  # SELL
            shares = self._calculate_short_shares(allocation_amount, current_bar.close)
            fill = self._execute_sell(signal.symbol, shares, current_bar.close, current_bar.timestamp)
        
        if fill and self._trade_logger:
            # Capture state AFTER trade
            portfolio_value_after = self.get_portfolio_value()
            cash_after = self.cash
            allocation_after = self._calculate_allocation_percentages()
            
            # Log trade execution
            self._trade_logger.log_trade_execution(
                fill=fill,
                portfolio_value_before=portfolio_value_before,
                portfolio_value_after=portfolio_value_after,
                cash_before=cash_before,
                cash_after=cash_after,
                allocation_before=allocation_before,
                allocation_after=allocation_after
            )
        
        return fill
    
    def _calculate_allocation_percentages(self) -> Dict[str, Decimal]:
        """Calculate current allocation as percentages."""
        portfolio_value = self.get_portfolio_value()
        if portfolio_value == Decimal('0'):
            return {}
        
        allocations = {}
        
        # Add positions
        for symbol, quantity in self.positions.items():
            if symbol in self._latest_prices:
                position_value = self._latest_prices[symbol] * Decimal(quantity)
                allocations[symbol] = (position_value / portfolio_value) * Decimal('100')
        
        # Add cash (if significant)
        cash_percent = (self.cash / portfolio_value) * Decimal('100')
        if cash_percent > Decimal('1'):  # Only show if >1%
            allocations['CASH'] = cash_percent
        
        return allocations
```

### 2. Strategy Integration (Example: ADX_Trend)

**File**: `jutsu_engine/strategies/adx_trend.py`

**Change**: Add TradeLogger parameter and log strategy context

```python
class ADX_Trend(Strategy):
    def __init__(
        self,
        symbols: List[str],
        signal_asset: str = 'QQQ',
        trade_logger: Optional['TradeLogger'] = None  # NEW
    ):
        # ... existing fields ...
        self._trade_logger = trade_logger  # NEW
    
    def on_bar(self, bar: MarketDataEvent) -> None:
        """Process each bar."""
        # Only process signal asset bars
        if bar.symbol != self.signal_asset:
            return
        
        # Calculate indicators (existing logic)
        ema_fast = self._calculate_ema('fast', bar.close)
        ema_slow = self._calculate_ema('slow', bar.close)
        adx_val = self._calculate_adx()
        
        # Determine regime (existing logic)
        new_regime = self._classify_regime(ema_fast, ema_slow, adx_val)
        
        # Check if regime changed
        if new_regime != self.previous_regime:
            # Determine target vehicle and allocation
            target_vehicle, allocation = self._get_target_allocation(new_regime)
            
            # Build decision reason
            decision_reason = self._build_decision_reason(new_regime, ema_fast, ema_slow, adx_val)
            
            # Log strategy context BEFORE generating signal
            if self._trade_logger:
                self._trade_logger.log_strategy_context(
                    timestamp=bar.timestamp,
                    symbol=bar.symbol,
                    strategy_state=f"Regime {new_regime}: {self._regime_description(new_regime)}",
                    decision_reason=decision_reason,
                    indicator_values={
                        'EMA_fast': ema_fast,
                        'EMA_slow': ema_slow,
                        'ADX': adx_val
                    },
                    threshold_values={
                        'adx_threshold_low': Decimal('20'),
                        'adx_threshold_high': Decimal('25')
                    }
                )
            
            # Generate signals (existing logic)
            # ... close old positions, open new positions ...
```

### 3. EventLoop Integration

**File**: `jutsu_engine/core/event_loop.py`

**Change**: Pass TradeLogger to Portfolio and call increment_bar()

```python
class EventLoop:
    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        portfolio: PortfolioSimulator,
        trade_logger: Optional['TradeLogger'] = None  # NEW
    ):
        # ... existing fields ...
        self._trade_logger = trade_logger  # NEW
    
    def run(self) -> None:
        """Main event loop."""
        for bar in self.data_handler.get_next_bar():
            # Increment bar counter
            if self._trade_logger:
                self._trade_logger.increment_bar()
            
            # Process bar (existing logic)
            self.strategy.on_bar(bar)
            # ... existing signal processing ...
```

### 4. PerformanceAnalyzer Integration

**File**: `jutsu_engine/performance/analyzer.py`

**Change**: Add CSV export method

```python
class PerformanceAnalyzer:
    def export_trades_to_csv(
        self,
        trade_logger: TradeLogger,
        output_path: str = 'backtest_trades.csv'
    ) -> str:
        """
        Export trade log to CSV file.
        
        Args:
            trade_logger: TradeLogger instance with recorded trades
            output_path: Path to output CSV file (default: backtest_trades.csv)
        
        Returns:
            Absolute path to created CSV file
        
        Raises:
            ValueError: If no trades to export
        """
        df = trade_logger.to_dataframe()
        
        if df.empty:
            raise ValueError("No trades to export")
        
        # Resolve full path
        full_path = Path(output_path).resolve()
        
        # Export to CSV
        df.to_csv(full_path, index=False)
        
        logger.info(f"Exported {len(df)} trades to {full_path}")
        
        return str(full_path)
```

### 5. BacktestRunner Integration

**File**: `jutsu_engine/application/backtest_runner.py`

**Change**: Create TradeLogger and pass through pipeline

```python
class BacktestRunner:
    def run(
        self,
        # ... existing params ...
        export_trades: bool = False,  # NEW
        trades_output_path: str = 'backtest_trades.csv'  # NEW
    ) -> Dict[str, Any]:
        """Run backtest and return results."""
        
        # Create TradeLogger
        trade_logger = TradeLogger(initial_capital) if export_trades else None
        
        # Create Portfolio with TradeLogger
        portfolio = PortfolioSimulator(
            initial_capital=initial_capital,
            commission_per_share=commission_per_share,
            trade_logger=trade_logger
        )
        
        # Create Strategy with TradeLogger
        strategy = strategy_class(
            # ... existing params ...
            trade_logger=trade_logger
        )
        
        # Create EventLoop with TradeLogger
        event_loop = EventLoop(
            data_handler=data_handler,
            strategy=strategy,
            portfolio=portfolio,
            trade_logger=trade_logger
        )
        
        # Run backtest
        event_loop.run()
        
        # Calculate performance metrics
        performance = PerformanceAnalyzer()
        metrics = performance.calculate_metrics(trades, equity_curve, initial_capital)
        
        # Export trades if requested
        if export_trades and trade_logger:
            csv_path = performance.export_trades_to_csv(trade_logger, trades_output_path)
            metrics['trades_csv_path'] = csv_path
        
        return metrics
```

### 6. CLI Integration

**File**: `jutsu_cli/commands/backtest.py`

**Change**: Add --export-trades flag

```python
@click.command()
@click.option('--export-trades', is_flag=True, default=False, help='Export trade log to CSV')
@click.option('--trades-output', default='backtest_trades.csv', help='Path for trade log CSV')
def backtest(
    # ... existing params ...
    export_trades: bool,
    trades_output: str
):
    """Run backtest with optional trade log export."""
    
    runner = BacktestRunner()
    results = runner.run(
        # ... existing params ...
        export_trades=export_trades,
        trades_output_path=trades_output
    )
    
    if export_trades:
        click.echo(f"Trade log exported to: {results['trades_csv_path']}")
```

## Performance Considerations

**Memory Usage**:
- One TradeRecord per fill (typically 100-1000 records per backtest)
- StrategyContext buffer (cleared periodically if memory concern)
- Acceptable: <10MB for typical backtest

**Processing Time**:
- log_strategy_context(): O(1) append
- log_trade_execution(): O(n) context matching (n=recent contexts, typically <10)
- to_dataframe(): O(m×k) where m=records, k=dynamic columns (typical: 500 records × 20 columns = 10K ops)
- Target: <100ms for CSV generation

**CSV File Size**:
- Typical: 500 trades × 25 columns × 20 bytes/cell ≈ 250KB
- Large backtest: 5000 trades ≈ 2.5MB
- Acceptable for MVP

## Testing Strategy

### Unit Tests

**File**: `tests/unit/performance/test_trade_logger.py`

1. `test_log_strategy_context()`: Verify context capture
2. `test_log_trade_execution()`: Verify trade logging
3. `test_context_matching()`: Verify symbol/timestamp matching
4. `test_to_dataframe_basic()`: Verify DataFrame generation
5. `test_to_dataframe_dynamic_columns()`: Verify indicator columns
6. `test_allocation_formatting()`: Verify percentage format
7. `test_empty_logger()`: Verify empty case handling
8. `test_multi_symbol()`: Verify separate rows per symbol

### Integration Tests

**File**: `tests/integration/test_trade_csv_export.py`

1. `test_full_backtest_with_csv_export()`: End-to-end ADX_Trend backtest → CSV
2. `test_csv_columns_match_spec()`: Verify all required columns present
3. `test_multi_symbol_separate_rows()`: Verify TQQQ/SQQQ/QQQ separate rows

## Validation Criteria

✅ **Functionality**:
- [ ] CSV exports successfully for ADX_Trend backtest
- [ ] All 25+ required columns present
- [ ] Dynamic indicator columns adapt to strategy
- [ ] Multi-symbol trades have separate rows
- [ ] Allocation percentages formatted correctly
- [ ] Cumulative return calculated accurately

✅ **Performance**:
- [ ] CSV generation <100ms for 500 trades
- [ ] Memory usage <10MB for typical backtest
- [ ] No performance degradation in EventLoop

✅ **Quality**:
- [ ] Unit tests >80% coverage
- [ ] Integration test validates end-to-end flow
- [ ] Type hints on all public methods
- [ ] Docstrings in Google format
- [ ] Logging at INFO level

## Example CSV Output

```csv
Trade ID,Date,Bar Number,Strategy State,Ticker,Decision,Decision Reason,Indicator_ADX,Indicator_EMA_fast,Indicator_EMA_slow,Threshold_adx_threshold_high,Threshold_adx_threshold_low,Order Type,Shares,Fill Price,Position Value,Slippage,Commission,Portfolio Value Before,Portfolio Value After,Cash Before,Cash After,Allocation Before,Allocation After,Cumulative Return %
1,2025-01-15 09:30:00,1,Regime 1: Strong Bullish,TQQQ,BUY,"EMA_fast > EMA_slow AND ADX > 25",28.5,150.2,148.1,25,20,MARKET,100,45.30,4530.00,0.00,1.00,10000.00,9469.00,10000.00,5469.00,CASH: 100.0%,"TQQQ: 47.8%, CASH: 52.2%",0.0
2,2025-01-16 09:30:00,2,Regime 3: Strong Bearish,TQQQ,SELL,"EMA_fast < EMA_slow AND ADX > 25",29.1,148.5,150.0,25,20,MARKET,100,46.10,4610.00,0.00,1.00,9569.00,9649.00,5469.00,10078.00,"TQQQ: 48.2%, CASH: 51.8%",CASH: 100.0%,0.5
```

## Related Memories

- `architecture_strategy_portfolio_separation_2025-11-04`: SignalEvent portfolio_percent design
- `portfolio_position_sizing_fix_2025-11-05`: Portfolio.execute_signal() flow
- `adx_trend_strategy_implementation_2025-11-05`: Multi-symbol strategy pattern

## Status

📝 **DESIGN COMPLETE**: Ready for implementation
🎯 **NEXT STEP**: Implement TradeLogger class (task 4)
