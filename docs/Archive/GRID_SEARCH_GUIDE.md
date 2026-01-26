# Grid Search Parameter Optimization Guide

**Version**: 1.0
**Last Updated**: 2025-11-07
**Module**: `jutsu_engine.application.grid_search_runner`

---

## Table of Contents

1. [Introduction](#introduction)
2. [When to Use Grid Search](#when-to-use-grid-search)
3. [Configuration File Structure](#configuration-file-structure)
4. [Running Grid Search](#running-grid-search)
5. [Interpreting Results](#interpreting-results)
6. [Best Practices](#best-practices)
7. [Advanced Usage](#advanced-usage)
8. [Troubleshooting](#troubleshooting)
9. [Examples](#examples)

---

## Introduction

Grid search is an automated parameter optimization technique that systematically tests **all combinations** of strategy parameters to find the configuration that maximizes performance (typically Sharpe Ratio).

**Key Concept**: Instead of manually running 50 backtests with different parameters, define ranges once and let the system test all combinations automatically.

### What Grid Search Does

1. **Loads Configuration**: Reads YAML file with parameter ranges
2. **Generates Combinations**: Creates Cartesian product of all parameter values
3. **Runs Backtests**: Executes each combination with progress tracking
4. **Collects Metrics**: Gathers performance metrics from all runs
5. **Generates Comparison**: Creates sortable CSV with all metrics
6. **Identifies Optimal**: Highlights best-performing parameter combinations

### What's Included

- **12 Performance Metrics**: Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, etc.
- **Progress Tracking**: Real-time progress bar with tqdm
- **Resume Capability**: Automatic checkpoints every 10 runs
- **Symbol Set Grouping**: Prevents invalid symbol combinations (e.g., mixing NVDA signals with QQQ leverage)
- **Comparison CSVs**: Easy sorting/filtering in Excel or Python

---

## When to Use Grid Search

### ✅ Good Use Cases

**New Strategy Development**:
- Testing initial parameter sensitivity
- Establishing baseline performance ranges
- Discovering parameter interactions

**Strategy Refinement**:
- Fine-tuning existing strategies
- Validating parameter stability across symbols
- Finding regime-specific optimal parameters

**Research & Analysis**:
- Identifying overfitting (parameters that work for one symbol but not others)
- Testing robustness across time periods
- Comparing parameter sensitivity

### ❌ When NOT to Use Grid Search

**Too Many Parameters**: >5 parameters with >5 values each = combinatorial explosion
- **Solution**: Use staged optimization (optimize 2-3 params at a time)

**Continuous Parameters**: Testing every value from 0.01 to 1.00 in steps of 0.01
- **Solution**: Start with coarse grid (0.1, 0.3, 0.5), then refine around best

**Overfitting Risk**: Using results from a single time period without validation
- **Solution**: Use walk-forward analysis after grid search

**Computational Constraints**: Limited time/resources for hundreds of backtests
- **Solution**: Start with simple grid (< 50 combinations)

---

## Configuration File Structure

Grid search uses **YAML** configuration files with four main sections.

### Complete Example

```yaml
# Grid Search Configuration for MACD Trend V4
strategy: MACD_Trend_v4

# Symbol Sets - Groups prevent invalid combinations
symbol_sets:
  - name: "QQQ-TQQQ"
    signal_symbol: QQQ      # Symbol for signals
    bull_symbol: TQQQ       # Leveraged bull ETF
    defense_symbol: QQQ     # Defensive position

  - name: "SPY-SPXL"
    signal_symbol: SPY
    bull_symbol: SPXL
    defense_symbol: SPY

# Fixed Backtest Configuration
base_config:
  start_date: "2020-01-01"
  end_date: "2024-12-31"
  timeframe: "1D"
  initial_capital: 100000
  commission: 0.01
  slippage: 0.0

# Parameter Ranges (Cartesian Product)
parameters:
  # Testing 3 EMA periods
  ema_period: [100, 150, 200]

  # Testing 2 ATR multipliers
  atr_stop_multiplier: [2.5, 3.0]

  # Testing 2 risk levels
  risk_bull: [0.02, 0.03]

  # Keep defaults (single value)
  macd_fast_period: [12]
  macd_slow_period: [26]
  macd_signal_period: [9]

# Optional Constraints
max_combinations: 500
checkpoint_interval: 10
```

### Section Breakdown

#### 1. Strategy Selection

```yaml
strategy: MACD_Trend_v4
```

**Must match** the strategy class name exactly (case-sensitive).

**Available Strategies**:
- `SMA_Crossover`
- `ADX_Trend`
- `Momentum_ATR`
- `MACD_Trend_v4`
- (Any custom strategy in `jutsu_engine/strategies/`)

#### 2. Symbol Sets

```yaml
symbol_sets:
  - name: "Descriptive Name"
    signal_symbol: TICKER1   # Symbol for generating signals
    bull_symbol: TICKER2     # Symbol for bullish allocation
    defense_symbol: TICKER3  # Symbol for defensive allocation
```

**Why Symbol Sets?**

Prevents invalid combinations like:
- ❌ Using NVDA signals with QQQ leverage (different assets)
- ❌ Mixing incompatible timeframes or data sources
- ✅ Ensures signal/bull/defense symbols are logically grouped

**Single Symbol Strategies**: For strategies that use only one symbol (e.g., SMA_Crossover), all three can be the same:

```yaml
symbol_sets:
  - name: "AAPL"
    signal_symbol: AAPL
    bull_symbol: AAPL
    defense_symbol: AAPL
```

**Multiple Symbol Sets**: Grid search will test **each symbol set** with all parameter combinations:

```
2 symbol_sets × 10 parameter_combinations = 20 total backtests
```

#### 3. Base Configuration

```yaml
base_config:
  start_date: "2020-01-01"
  end_date: "2024-12-31"
  timeframe: "1D"
  initial_capital: 100000
  commission: 0.01
  slippage: 0.0
```

**Fixed Settings** applied to ALL backtests.

**Common Parameters**:
- `start_date`, `end_date`: Date range (YYYY-MM-DD format)
- `timeframe`: Bar size (`1D`, `1H`, `15m`, etc.)
- `initial_capital`: Starting portfolio value
- `commission`: Per-share commission cost
- `slippage`: Slippage percentage (0.0 = no slippage)

#### 4. Parameters to Optimize

```yaml
parameters:
  # Multiple values = optimization target
  ema_period: [50, 100, 150, 200]
  atr_stop_multiplier: [2.0, 2.5, 3.0]

  # Single value = keep default
  macd_fast_period: [12]
  atr_period: [14]
```

**Rules**:
- **List of Values**: Each parameter is a YAML list
- **Multiple Values**: Parameters with >1 value will be optimized
- **Single Value**: Parameters with 1 value remain constant
- **Cartesian Product**: Total combinations = product of all list lengths

**Example Calculation**:
```yaml
ema_period: [50, 100, 150]         # 3 values
atr_stop_multiplier: [2.0, 3.0]    # 2 values
risk_bull: [0.02, 0.025, 0.03]     # 3 values

# Total combinations: 3 × 2 × 3 = 18 backtests
```

#### 5. Optional Constraints

```yaml
max_combinations: 500         # Abort if combinations exceed this
checkpoint_interval: 10        # Save progress every N backtests
```

**max_combinations**: Safety check to prevent accidentally running thousands of backtests
- If actual combinations exceed this, grid search will abort with error
- Default: No limit (not recommended)

**checkpoint_interval**: How often to save progress for resume capability
- Default: 10 (save every 10 backtests)
- Set to 1 for critical long-running jobs

---

## Running Grid Search

### Command-Line Interface

**Basic Usage**:
```bash
jutsu grid-search --config configs/my_grid.yaml
```

**Options**:
```bash
jutsu grid-search \
  --config configs/grid_search_macd_v4.yaml \
  --output-dir results/optimization_001/
```

**Flags**:
- `-c, --config`: Path to YAML configuration file (REQUIRED)
- `-o, --output-dir`: Custom output directory (optional, default: `output/`)

### Execution Flow

**Step 1: Configuration Loading**
```
Loading configuration from: configs/grid_search_macd_v4.yaml
Strategy: MACD_Trend_v4
Symbol sets: 2
Parameter combinations: 90
```

**Step 2: User Confirmation** (if > 100 combinations)
```
WARNING: This will run 150 backtests.
Estimated time: ~30-60 minutes.
Continue? [y/N]:
```

**Step 3: Progress Tracking**
```
Running Grid Search: 45/90 [=============>----------] 50% | ETA: 15m 22s
```

**Step 4: Checkpoint Saves** (every 10 runs)
```
Checkpoint saved: output/.../checkpoint_010.json
```

**Step 5: Completion Summary**
```
✅ Grid search complete!
Total runs: 90
Successful: 88
Failed: 2
Output directory: output/grid_search_MACD_Trend_v4_2025-11-07_143022/
```

### Resume Interrupted Runs

If grid search is interrupted (Ctrl+C, crash, etc.):

```bash
# Grid search automatically resumes from last checkpoint
jutsu grid-search --config configs/my_grid.yaml

# Output:
# Found checkpoint: 40 of 90 runs complete
# Resuming from run 41...
```

**How It Works**:
- Every 10 runs, saves checkpoint to `output/.../checkpoint_XXX.json`
- On restart, scans for existing checkpoint files
- Skips completed runs, continues from next unfinished run
- Works across sessions (can close terminal and resume later)

---

## Interpreting Results

### Output Directory Structure

```
output/grid_search_MACD_Trend_v4_2025-11-07_143022/
├── summary_comparison.csv   # ⭐ Main results file
├── run_config.csv          # Parameter mapping
├── parameters.yaml         # Copy of input config
├── README.txt             # Quick summary
├── checkpoint_010.json    # Resume checkpoints
├── checkpoint_020.json
├── run_001/               # Individual backtest results
│   ├── portfolio_daily.csv
│   └── trades.csv
├── run_002/
│   ├── portfolio_daily.csv
│   └── trades.csv
└── ... (88 more runs)
```

### Key Files

#### 1. `summary_comparison.csv` ⭐ MOST IMPORTANT

**Contains**: All performance metrics for all runs in a single sortable table.

**Columns** (22 total):

| Column | Description | Units |
|--------|-------------|-------|
| `Run` | Run number (maps to `run_XXX/` directory) | Integer |
| `Symbol_Set` | Symbol set name (e.g., "QQQ-TQQQ") | String |
| `Final_Value` | Ending portfolio value | Dollars |
| `Total_Return_Pct` | Total return | Percentage |
| `Annual_Return_Pct` | Annualized return | Percentage |
| `Sharpe_Ratio` | Risk-adjusted return | Ratio |
| `Sortino_Ratio` | Downside risk-adjusted return | Ratio |
| `Max_Drawdown_Pct` | Maximum peak-to-trough decline | Percentage |
| `Calmar_Ratio` | Annual return / Max drawdown | Ratio |
| `Win_Rate_Pct` | Percentage of winning trades | Percentage |
| `Total_Trades` | Number of completed trades | Integer |
| `Profit_Factor` | Gross profit / Gross loss | Ratio |
| `Avg_Win_Pct` | Average winning trade return | Percentage |
| `Avg_Loss_Pct` | Average losing trade return | Percentage |
| `ema_period` | EMA period parameter | Integer |
| `atr_stop_multiplier` | ATR stop multiplier parameter | Float |
| `risk_bull` | Risk per trade parameter | Float |
| ... | (Other strategy-specific parameters) | Varies |

**ASCII Visualization**:
```
Run | Symbol_Set | Final_Value | Total_Return | Sharpe | ema_period | atr_stop | risk_bull
----|------------|-------------|--------------|--------|------------|----------|----------
1   | QQQ-TQQQ   | 152340      | 52.34%       | 1.85   | 50         | 2.0      | 0.02
2   | QQQ-TQQQ   | 148920      | 48.92%       | 1.72   | 50         | 2.0      | 0.025
3   | QQQ-TQQQ   | 156780      | 56.78%       | 2.01   | 50         | 2.0      | 0.03 ⭐
...
```

#### 2. `run_config.csv`

**Contains**: Parameter values for each run (same info as last columns of summary_comparison.csv).

**Use Case**: Quick lookup of "What parameters did run_042 use?"

#### 3. `README.txt`

**Contains**: Human-readable summary statistics.

**Example**:
```
Grid Search Results - MACD_Trend_v4
====================================

Configuration:
- Symbol Sets: 2 (QQQ-TQQQ, SPY-SPXL)
- Parameter Combinations: 90
- Date Range: 2020-01-01 to 2024-12-31

Execution:
- Total Runs: 90
- Successful: 88
- Failed: 2
- Runtime: 28 minutes 15 seconds

Top 5 Performers (by Sharpe Ratio):
1. Run 067: Sharpe 2.34, Annual Return 45.2%, Max DD -12.5%
2. Run 042: Sharpe 2.18, Annual Return 42.1%, Max DD -14.2%
3. Run 023: Sharpe 2.05, Annual Return 38.7%, Max DD -11.8%
4. Run 089: Sharpe 1.98, Annual Return 39.5%, Max DD -15.1%
5. Run 012: Sharpe 1.91, Annual Return 37.2%, Max DD -13.3%

Files:
- summary_comparison.csv: All metrics for all runs
- run_config.csv: Parameter mapping
- run_XXX/: Individual backtest outputs
```

### Analysis Workflow

**Step 1: Open `summary_comparison.csv` in Excel or Python**

**Excel**:
```
1. Open summary_comparison.csv
2. Select all data (Ctrl+A)
3. Data > Sort > Sort by "Sharpe_Ratio" descending
4. Review top 10 rows
```

**Python**:
```python
import pandas as pd

# Load results
df = pd.read_csv('summary_comparison.csv')

# Sort by Sharpe Ratio
top_10 = df.nlargest(10, 'Sharpe_Ratio')

# Display
print(top_10[['Run', 'Symbol_Set', 'Sharpe_Ratio', 'Annual_Return_Pct',
              'Max_Drawdown_Pct', 'ema_period', 'atr_stop_multiplier', 'risk_bull']])
```

**Step 2: Identify Patterns**

**Look for**:
- **Consistent Parameters**: Do top performers share common parameter values?
  - ✅ If top 5 all use `ema_period=200`, that's a strong signal
  - ⚠️ If top 5 use different `ema_period` values, parameter may not matter

- **Symbol Sensitivity**: Do parameters work across symbol sets?
  - ✅ If top performers include both QQQ-TQQQ and SPY-SPXL, parameters are robust
  - ⚠️ If all top performers use same symbol set, may be overfitting

- **Trade-offs**: Are there parameter interactions?
  - Example: Higher `risk_bull` → Higher returns BUT also higher drawdowns
  - Balance risk/reward based on your preferences

**Step 3: Validate Top Performers**

**Sanity Checks**:
1. **Trade Count**: Check `Total_Trades` column
   - ⚠️ Too few trades (< 20) → May be luck, not skill
   - ⚠️ Too many trades (> 500) → May be overtrading

2. **Win Rate**: Check `Win_Rate_Pct`
   - ✅ 40-60% is normal for trend-following strategies
   - ⚠️ >80% may indicate overfitting or data snooping

3. **Drawdown**: Check `Max_Drawdown_Pct`
   - ✅ Lower is better, but must be realistic
   - ⚠️ <5% drawdown with >30% returns is suspicious

**Step 4: Drill Down**

For top candidates, inspect individual backtest results:

```bash
# Navigate to individual run directory
cd output/grid_search_MACD_Trend_v4_2025-11-07_143022/run_042/

# View daily portfolio values
head portfolio_daily.csv

# View trade log
head trades.csv
```

**Step 5: Test Robustness**

**Walk-Forward Analysis**: Test if optimal parameters from 2020-2022 still work in 2023-2024
- Run grid search on training period (2020-2022)
- Pick top parameters
- Test on validation period (2023-2024) with single backtest
- Compare performance (should degrade somewhat, but not collapse)

**Different Markets**: Test top parameters on different symbols
- If QQQ-TQQQ parameters work, do they also work for SPY-SPXL?
- Robust parameters should generalize reasonably well

---

## Best Practices

### Parameter Selection

**Start Coarse, Then Refine**:

```yaml
# Round 1: Coarse grid (9 combinations)
parameters:
  ema_period: [50, 150, 250]
  atr_stop_multiplier: [2.0, 3.0, 4.0]

# Round 2: Refine around best (say ema=150, atr=3.0)
parameters:
  ema_period: [120, 150, 180]
  atr_stop_multiplier: [2.5, 3.0, 3.5]
```

**Avoid Continuous Ranges**:

❌ **Bad**:
```yaml
# 100 values = too many combinations
risk_bull: [0.01, 0.011, 0.012, ..., 0.10]
```

✅ **Good**:
```yaml
# 5 representative values
risk_bull: [0.01, 0.025, 0.05, 0.075, 0.10]
```

**Parameter Bounds**:

Use **realistic** bounds based on financial logic:
- EMA period: 10-300 (not 1-1000)
- Risk per trade: 1%-10% (not 0.1%-50%)
- ATR multiplier: 1.5-5.0 (not 0.1-20.0)

### Managing Combinatorial Explosion

**Problem**: 5 parameters × 10 values each = 100,000 combinations (impractical)

**Solutions**:

1. **Staged Optimization**: Optimize in groups

```yaml
# Stage 1: Optimize trend filter
parameters:
  ema_period: [50, 100, 150, 200, 250]
  # Keep others constant
  atr_stop_multiplier: [3.0]
  risk_bull: [0.025]

# Stage 2: Optimize risk management (using best ema from Stage 1)
parameters:
  ema_period: [150]  # Best from Stage 1
  atr_stop_multiplier: [2.0, 2.5, 3.0, 3.5, 4.0]
  risk_bull: [0.02, 0.025, 0.03]
```

2. **Parameter Importance**: Focus on high-impact parameters
   - Test sensitivity: Which parameters change results most?
   - Optimize important ones first, keep others at defaults

3. **Latin Hypercube Sampling** (future feature):
   - Sample parameter space efficiently
   - Get good coverage with fewer combinations

### Avoiding Overfitting

**Overfitting**: Parameters that work perfectly on historical data but fail on new data.

**Warning Signs**:
- ✅ Sharpe Ratio > 3.0 with < 30 trades (too good to be true)
- ✅ Win rate > 85% (unrealistic for most strategies)
- ✅ Parameters work for one symbol but fail for similar symbols
- ✅ Performance collapses in out-of-sample testing

**Prevention Strategies**:

1. **Use Walk-Forward Analysis**:
   - Train on 2020-2022, validate on 2023-2024
   - Roll forward: Train 2020-2021, test 2022; then 2021-2022, test 2023
   - Expect 20-30% performance degradation out-of-sample

2. **Test Multiple Symbol Sets**:
   - If QQQ-TQQQ works, does SPY-SPXL also work?
   - Robust parameters should generalize

3. **Prefer Simpler Parameters**:
   - ema_period = 100 vs 103 → Choose 100 (rounder number, less curve-fitting)
   - If Sharpe 1.85 vs 1.87, choose simpler/more interpretable parameters

4. **Reasonable Trade Count**:
   - Minimum 30-50 trades for statistical validity
   - More trades = more confidence in metrics

---

## Advanced Usage

### Custom Metrics Sorting

By default, grid search sorts by Sharpe Ratio. You may prefer other metrics:

**In Python**:
```python
import pandas as pd

df = pd.read_csv('summary_comparison.csv')

# Sort by Sortino Ratio (emphasizes downside risk)
top_sortino = df.nlargest(10, 'Sortino_Ratio')

# Sort by Calmar Ratio (return / max drawdown)
top_calmar = df.nlargest(10, 'Calmar_Ratio')

# Multi-criteria filtering
filtered = df[
    (df['Sharpe_Ratio'] > 1.5) &
    (df['Max_Drawdown_Pct'] < 20) &
    (df['Total_Trades'] > 30)
].nlargest(10, 'Annual_Return_Pct')
```

### Parameter Sensitivity Analysis

**Visualize** how parameters affect performance:

```python
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv('summary_comparison.csv')

# Heatmap: Sharpe Ratio vs two parameters
pivot = df.pivot_table(
    values='Sharpe_Ratio',
    index='ema_period',
    columns='atr_stop_multiplier',
    aggfunc='mean'
)

sns.heatmap(pivot, annot=True, fmt='.2f', cmap='RdYlGn')
plt.title('Sharpe Ratio Sensitivity: EMA Period vs ATR Multiplier')
plt.show()
```

### Comparing Multiple Grid Searches

Run multiple grid searches (different strategies, date ranges, symbol sets) and compare:

```python
# Load multiple results
grid1 = pd.read_csv('output/grid_search_1/summary_comparison.csv')
grid2 = pd.read_csv('output/grid_search_2/summary_comparison.csv')

# Add labels
grid1['search'] = 'Strategy_A'
grid2['search'] = 'Strategy_B'

# Combine and compare
combined = pd.concat([grid1, grid2])
comparison = combined.groupby('search')['Sharpe_Ratio'].describe()
print(comparison)
```

---

## Troubleshooting

### Common Errors

#### 1. `StrategyNotFoundError`

**Error**:
```
Error: Strategy 'macd_trend_v4' not found.
Available strategies: ['SMA_Crossover', 'ADX_Trend', 'MACD_Trend_v4']
```

**Cause**: Strategy name in YAML doesn't match class name.

**Solution**: Check exact class name (case-sensitive):
```yaml
# ❌ Wrong
strategy: macd_trend_v4

# ✅ Correct
strategy: MACD_Trend_v4
```

#### 2. `InvalidParameterError`

**Error**:
```
Error: Parameter 'unknown_param' not recognized by MACD_Trend_v4.
```

**Cause**: Parameter name in YAML doesn't match strategy's `__init__` arguments.

**Solution**: Check strategy source code for exact parameter names:
```python
# In jutsu_engine/strategies/MACD_Trend_v4.py
class MACD_Trend_v4(Strategy):
    def __init__(
        self,
        signal_symbol: str = "QQQ",
        ema_period: int = 100,  # ✅ Use this exact name
        # ...
    ):
```

#### 3. `MaxCombinationsExceeded`

**Error**:
```
Error: Total combinations (1250) exceed max_combinations limit (500).
```

**Cause**: Too many parameter combinations.

**Solution**: Either reduce parameter ranges or increase limit:
```yaml
# Option 1: Reduce ranges
parameters:
  ema_period: [100, 200]  # Was [50, 100, 150, 200, 250]

# Option 2: Increase limit
max_combinations: 2000  # Only if you have time/resources
```

#### 4. `DataNotFoundError`

**Error**:
```
Error: No data found for symbol 'TQQQ' in timeframe '1D' between 2020-01-01 and 2024-12-31.
```

**Cause**: Missing market data in database.

**Solution**: Sync data first:
```bash
jutsu sync schwab --symbol TQQQ --timeframe 1D --start 2020-01-01
```

#### 5. All Backtests Fail

**Symptom**: Grid search completes but all runs show errors.

**Debug Steps**:
1. Check logs in `output/.../logs/grid_search.log`
2. Run single backtest manually with same parameters:
   ```bash
   jutsu backtest --strategy MACD_Trend_v4 --start 2020-01-01 --end 2024-12-31
   ```
3. Common causes:
   - Missing data for symbols
   - Invalid parameter values (negative, too large, etc.)
   - Strategy initialization errors

### Performance Issues

#### Slow Execution

**Symptom**: Each backtest takes > 2 minutes.

**Causes & Solutions**:
- **Large Date Range**: 5+ years of daily data
  - Solution: Start with shorter range (1-2 years), expand if needed

- **High-Frequency Data**: Minute/tick bars
  - Solution: Use daily bars for initial optimization

- **Database Performance**: SQLite on slow disk
  - Solution: Migrate to PostgreSQL, or use SSD

#### Memory Issues

**Symptom**: System runs out of memory, grid search crashes.

**Causes & Solutions**:
- **Too Many Concurrent Backtests**: Grid search doesn't run in parallel
  - If you see memory issues, it's likely data loading problem

- **Large Portfolio Histories**: Storing millions of data points
  - Solution: Run grid search in smaller batches (checkpoint helps)

---

## Examples

### Example 1: Simple Grid (8 combinations)

**Use Case**: Quick test of new strategy

**Config** (`configs/examples/grid_search_simple.yaml`):
```yaml
strategy: MACD_Trend_v4

symbol_sets:
  - name: "SPY-SPXL"
    signal_symbol: SPY
    bull_symbol: SPXL
    defense_symbol: SPY

base_config:
  start_date: "2022-01-01"
  end_date: "2024-12-31"
  timeframe: "1D"
  initial_capital: 100000

parameters:
  ema_period: [100, 200]              # 2 values
  atr_stop_multiplier: [2.0, 3.0]     # 2 values
  risk_bull: [0.02, 0.03]             # 2 values
  # Total: 2 × 2 × 2 = 8 combinations
```

**Run**:
```bash
jutsu grid-search --config configs/examples/grid_search_simple.yaml
# Runtime: ~2-5 minutes
```

**Results**: 8 backtests, easy to analyze in Excel

---

### Example 2: Comprehensive Optimization (90 combinations)

**Use Case**: Full parameter sweep for production strategy

**Config** (`configs/examples/grid_search_macd_v4.yaml`):
```yaml
strategy: MACD_Trend_v4

symbol_sets:
  - name: "NVDA-NVDL"
    signal_symbol: NVDA
    bull_symbol: NVDL
    defense_symbol: NVDA

  - name: "QQQ-TQQQ"
    signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: QQQ

base_config:
  start_date: "2020-01-01"
  end_date: "2024-12-31"
  timeframe: "1D"
  initial_capital: 100000

parameters:
  ema_period: [50, 100, 150, 200, 250]    # 5 values
  atr_stop_multiplier: [2.0, 3.0, 4.0]    # 3 values
  risk_bull: [0.02, 0.025, 0.03]          # 3 values
  # Total: 2 symbols × (5 × 3 × 3) = 90 combinations

max_combinations: 500
checkpoint_interval: 10
```

**Run**:
```bash
jutsu grid-search --config configs/examples/grid_search_macd_v4.yaml
# Runtime: ~15-30 minutes
```

**Results**: 90 backtests across 2 symbol sets, comprehensive comparison

---

### Example 3: Multi-Stage Optimization

**Use Case**: Reduce combinations by optimizing in stages

**Stage 1: Trend Filter** (5 combinations)
```yaml
# configs/stage1_trend.yaml
strategy: MACD_Trend_v4

symbol_sets:
  - name: "QQQ-TQQQ"
    signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: QQQ

parameters:
  ema_period: [50, 100, 150, 200, 250]
  atr_stop_multiplier: [3.0]  # Keep constant
  risk_bull: [0.025]          # Keep constant
```

**Result**: Best ema_period = 150

**Stage 2: Risk Management** (9 combinations)
```yaml
# configs/stage2_risk.yaml
strategy: MACD_Trend_v4

symbol_sets:
  - name: "QQQ-TQQQ"
    signal_symbol: QQQ
    bull_symbol: TQQQ
    defense_symbol: QQQ

parameters:
  ema_period: [150]  # Use best from Stage 1
  atr_stop_multiplier: [2.0, 2.5, 3.0, 3.5]
  risk_bull: [0.02, 0.025, 0.03]
```

**Result**: Best atr = 3.0, risk = 0.025

**Total**: 5 + 9 = 14 combinations instead of 5 × 4 × 3 = 60 if done together

---

## Glossary

**Cartesian Product**: All possible combinations of parameter values
- Example: {A, B} × {1, 2} = {(A,1), (A,2), (B,1), (B,2)}

**Checkpoint**: Saved progress file allowing resume after interruption

**Symbol Set**: Group of related symbols (signal, bull, defense) tested together

**Grid Search**: Exhaustive search of all parameter combinations

**Walk-Forward Analysis**: Testing strategy on out-of-sample periods to validate robustness

**Overfitting**: Parameters that work perfectly on historical data but fail on new data

**Sharpe Ratio**: Risk-adjusted return metric (higher is better, >1.5 is good)

**Sortino Ratio**: Like Sharpe but only penalizes downside volatility

**Calmar Ratio**: Annual return divided by max drawdown (higher is better)

**Max Drawdown**: Largest peak-to-trough decline (lower is better)

**Win Rate**: Percentage of profitable trades (40-60% typical for trend strategies)

**Profit Factor**: Gross profit ÷ Gross loss (>1.5 is good)

---

## Additional Resources

**Project Documentation**:
- [README.md](../README.md): Project overview
- [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md): Architecture details
- [API_REFERENCE.md](API_REFERENCE.md): API documentation
- [BEST_PRACTICES.md](BEST_PRACTICES.md): Coding standards

**External Resources**:
- [Quantitative Trading](https://www.quantstart.com/): Parameter optimization articles
- [Better System Trader](https://bettersystemtrader.com/): Overfitting prevention
- [QuantConnect](https://www.quantconnect.com/docs/): Walk-forward analysis

---

**Version History**:
- **1.0** (2025-11-07): Initial release with GridSearchRunner module
