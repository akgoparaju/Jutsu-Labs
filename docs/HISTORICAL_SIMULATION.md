# Historical Trade Simulation Guide

**Created**: 2026-01-22
**Author**: Claude (Orchestrated)
**Related Script**: `scripts/simulate_historical_trades.py`

---

## Overview

The Historical Trade Simulation system allows you to generate trades and performance snapshots for a strategy **as if the scheduler had been running** from a past date. This is useful for:

- Creating comparable historical data for new strategies
- Backfilling data when a strategy wasn't tracked from the start
- Validating strategy behavior over historical periods
- Enabling apples-to-apples comparison between strategies

---

## When to Use Historical Simulation

### Use Cases

1. **New Strategy Comparison**
   When adding a new strategy (e.g., v3.5d), you want historical data to compare against existing strategies (e.g., v3.5b).

2. **Backfill Missing Data**
   If the scheduler wasn't running for a period, simulation can recreate what would have happened.

3. **Strategy Validation**
   Verify a strategy's behavior matches backtest expectations before going live.

4. **What-If Analysis**
   Explore how a strategy would have performed with different parameters or starting capital.

### When NOT to Use

- **Production live trading data** - Use actual scheduler for real trades
- **Replacing corrupted scheduler data** - Investigate root cause first
- **Rapid prototyping** - Use backtest instead (faster, no DB writes)

---

## Prerequisites

### 1. Market Data Availability

The simulation requires historical market data in the database:

```sql
-- Check data availability for your date range
SELECT
    symbol,
    MIN(timestamp) as first_date,
    MAX(timestamp) as last_date,
    COUNT(*) as bar_count
FROM market_data
WHERE timeframe = '1D'
  AND symbol IN ('QQQ', 'TQQQ', 'TLT', 'TMF', 'TMV')
GROUP BY symbol;
```

If data is missing, run data sync first:
```bash
python jutsu_engine/cli/main.py sync --symbol QQQ --start 2025-12-01
```

### 2. Strategy Registration

The strategy must be registered in `config/strategies_registry.yaml`:

```yaml
strategies:
  v3_5d:
    is_primary: false
    is_active: true
    execution_order: 2
    config_file: config/strategies/v3_5d.yaml
    state_file_path: state/strategies/v3_5d/state.json
```

### 3. Strategy Config File

The strategy must have a config file at the specified path:

```yaml
# config/strategies/v3_5d.yaml
strategy:
  name: Hierarchical_Adaptive_v3_5d
  version: "3.5d"
  universe:
    signal_symbol: QQQ
    bull_symbol: TQQQ
    bond_signal: TLT
    bull_bond: TMF
    bear_bond: TMV

execution:
  mode: offline_mock
  rebalance_threshold_pct: 5.0
```

---

## Running a Simulation

### Basic Usage

```bash
python scripts/simulate_historical_trades.py \
    --strategy-id v3_5d \
    --start-date 2025-12-04 \
    --end-date 2026-01-22 \
    --initial-capital 10000
```

### CLI Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--strategy-id` | Yes | - | Strategy identifier (e.g., `v3_5d`) |
| `--start-date` | Yes | - | Simulation start date (YYYY-MM-DD) |
| `--end-date` | No | Today | Simulation end date (YYYY-MM-DD) |
| `--initial-capital` | No | 10000 | Starting capital in dollars |
| `--dry-run` | No | False | Validate without writing to database |
| `--delete-existing` | No | False | Delete existing data before simulation |

### Examples

**Dry run (validation only)**:
```bash
python scripts/simulate_historical_trades.py \
    --strategy-id v3_5d \
    --start-date 2025-12-04 \
    --dry-run
```

**Fresh simulation (delete and recreate)**:
```bash
python scripts/simulate_historical_trades.py \
    --strategy-id v3_5d \
    --start-date 2025-12-04 \
    --delete-existing
```

**Custom capital amount**:
```bash
python scripts/simulate_historical_trades.py \
    --strategy-id v3_5d \
    --start-date 2025-12-04 \
    --initial-capital 100000
```

---

## Expected Output

### Console Output

```
================================================================================
HISTORICAL TRADE SIMULATION
================================================================================
Strategy ID: v3_5d
Start Date: 2025-12-04
End Date: 2026-01-22
Initial Capital: $10,000.00
Delete Existing: True
Dry Run: False
================================================================================

Loading strategy: Hierarchical_Adaptive_v3_5d
Found 33 trading days in simulation range

Day 1/33: 2025-12-04
  Loading market data (250 bar lookback)
  Running strategy...
  Cell: 3, Trend: sideways, Vol: normal
  Target allocation: {'TQQQ': 0.50, 'TMF': 0.50}
  Trade: BUY 35 TQQQ @ $71.20
  Trade: BUY 120 TMF @ $41.50
  Snapshot saved: equity=$10,000.00

...

Day 33/33: 2026-01-22
  Loading market data (250 bar lookback)
  Running strategy...
  Cell: 3, Trend: sideways, Vol: normal
  No trades (positions match target)
  Snapshot saved: equity=$9,805.88

================================================================================
SIMULATION COMPLETE
================================================================================
Trading Days Processed: 33
Total Trades: 10
Total Snapshots: 33
Final Equity: $9,805.88
Total Return: -1.94%
Baseline (QQQ) Return: -1.07%
================================================================================
```

### Database Records Created

**Performance Snapshots** (`performance_snapshots` table):
- One row per trading day
- `strategy_id = 'v3_5d'`
- `mode = 'offline_mock'`
- `snapshot_source = 'scheduler'`

**Trades** (`live_trades` table):
- One row per position change
- `strategy_id = 'v3_5d'`
- `mode = 'offline_mock'`
- `timestamp = 9:45 AM ET on simulation date`

---

## Validation

### Verify Snapshot Count

```sql
SELECT COUNT(*) as snapshot_count
FROM performance_snapshots
WHERE strategy_id = 'v3_5d';
-- Should match trading days in range
```

### Verify Trade Count

```sql
SELECT COUNT(*) as trade_count
FROM live_trades
WHERE strategy_id = 'v3_5d';
-- Should be > 0 if positions changed
```

### Check Equity Curve

```sql
SELECT
    DATE(timestamp AT TIME ZONE 'America/New_York') as trading_date,
    total_equity,
    daily_return
FROM performance_snapshots
WHERE strategy_id = 'v3_5d'
ORDER BY timestamp;
```

### Compare to Backtest

```sql
-- Get simulation results
SELECT
    strategy_id,
    MIN(total_equity) as min_equity,
    MAX(total_equity) as max_equity,
    (MAX(total_equity) - MIN(total_equity)) / MIN(total_equity) * 100 as total_return_pct
FROM performance_snapshots
WHERE strategy_id = 'v3_5d'
GROUP BY strategy_id;
```

Compare these metrics to the strategy's backtest results to validate accuracy.

---

## Troubleshooting

### Issue: "Strategy not found"

**Cause**: Strategy not registered in registry
**Solution**: Add to `config/strategies_registry.yaml`

### Issue: "No market data for date"

**Cause**: Data missing for simulation date
**Solution**: Run data sync to fetch missing bars

### Issue: "Duplicate key violation"

**Cause**: Data already exists for this strategy
**Solution**: Use `--delete-existing` flag or manually delete first

### Issue: "Strategy module import failed"

**Cause**: Strategy class not found
**Solution**: Verify import path matches strategy class name

```python
# Script expects:
from jutsu_engine.strategies.{StrategyName} import {StrategyName}

# Example for v3.5d:
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5d import Hierarchical_Adaptive_v3_5d
```

### Issue: "Weekend/holiday in trading days"

**Cause**: Market calendar issue
**Solution**: The script uses `pandas_market_calendars` to filter trading days. Verify calendar is up to date.

---

## Technical Details

### Simulation Logic

For each trading day in the range:

1. **Load Historical Data**
   Query `market_data` table for bars up to simulation date (250 bar lookback)

2. **Run Strategy**
   Initialize strategy with historical data and generate signals

3. **Calculate Target Positions**
   Convert allocation weights to shares based on current equity and prices

4. **Generate Trades**
   Compare current vs target positions; create trade records for differences

5. **Update State**
   Track positions, cash, and equity for next iteration

6. **Save Snapshot**
   Insert `performance_snapshot` record with all metrics

### Trade Recording

Trades are recorded with:
- **Timestamp**: 9:45 AM ET on simulation date (scheduler execution time)
- **Strategy Context**: Cell state, trend state, vol state, t_norm, z_score
- **Execution**: Fill price = target price (no simulated slippage)
- **Mode**: `offline_mock` (distinguishes from live trades)

### Snapshot Recording

Snapshots include:
- **Equity**: Cash + sum(position_value)
- **Positions**: JSON of current holdings
- **Regime Data**: From strategy's current state
- **Baseline**: QQQ value for comparison
- **Source**: `scheduler` (matching live scheduler format)

---

## Best Practices

### 1. Always Use --dry-run First

Validate the simulation before writing to the database:
```bash
python scripts/simulate_historical_trades.py \
    --strategy-id v3_5d \
    --start-date 2025-12-04 \
    --dry-run
```

### 2. Start with Short Date Ranges

Test with 5-10 days before running full simulation:
```bash
python scripts/simulate_historical_trades.py \
    --strategy-id v3_5d \
    --start-date 2026-01-15 \
    --end-date 2026-01-22
```

### 3. Backup Before --delete-existing

Export current data before deletion:
```bash
psql -c "COPY (SELECT * FROM performance_snapshots WHERE strategy_id='v3_5d') TO '/tmp/v3_5d_backup.csv' CSV HEADER"
```

### 4. Verify Against Backtest

Compare simulation results to backtest results for the same period. They should be very close (small differences expected due to execution time assumptions).

### 5. Document Your Simulations

Keep a record of when you ran simulations and with what parameters:
```
# 2026-01-22: v3_5d simulation
# Start: 2025-12-04, Initial: $10,000
# Result: 33 days, 10 trades, -1.94% return
```

---

## Related Documentation

- [Multi-Strategy Scheduler Tasks](../claudedocs/MULTI_STRATEGY_SCHEDULER_TASKS.md)
- [Live Trading Guide](./LIVE_TRADING_GUIDE.md)
- [Database Migration Guide](../claudedocs/DATABASE_MIGRATION_STAGING_TO_PRODUCTION.md)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-01-22 | Initial creation - Phase 3 of multi-strategy scheduler |
