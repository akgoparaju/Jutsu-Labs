# Grid Search CSV Formatting Standards

## Issue Summary
Fixed 3 CSV formatting issues in summary_comparison.csv to ensure Excel compatibility and professional presentation.

## Decimal Precision Rules

### Non-Percentage Values (2 decimals)
- Portfolio Balance: 47667.74
- Sharpe Ratio: 1.42
- Sortino Ratio: 1.11
- Calmar Ratio: 1.27
- Profit Factor: 0.09
- Avg Win ($): 570.74
- Avg Loss ($): -6193.47

### Integer Values (no decimals)
- Total Trades: 49

### Percentage Values (3 decimals AFTER dividing by 100)
- Total Return %: 3.767 (was 376.677)
- Annualized Return %: 0.367 (was 36.690)
- Max Drawdown: -0.289 (was -28.944)
- Win Rate %: 0.49 (was 48.979)

## Percentage Column Format (Excel Compatibility)

**Critical Rule**: ALWAYS divide percentage values by 100 before writing to CSV

**Rationale**: Excel users apply percentage formatting which multiplies by 100
- Current value in code: 376.677% (internal representation)
- Divide by 100: 3.767
- Written to CSV: 3.767
- Excel formats as %: 376.7% ✅ (CORRECT!)

**Without division**:
- Current value: 376.677
- Written to CSV: 376.677
- Excel formats as %: 37667.7% ❌ (WRONG!)

**Affected Columns**:
1. Total Return %: divide by 100, round to 3 decimals
2. Annualized Return %: divide by 100, round to 3 decimals
3. Max Drawdown: divide by 100, round to 3 decimals
4. Win Rate %: divide by 100, round to 3 decimals

## Column Ordering

**Metrics First** (columns 1-14):
1. Run ID
2. Symbol Set
3. Portfolio Balance
4. Total Return %
5. Annualized Return %
6. Max Drawdown
7. Sharpe Ratio
8. Sortino Ratio
9. Calmar Ratio
10. Total Trades
11. Profit Factor
12. Win Rate %
13. Avg Win ($)
14. Avg Loss ($)

**Parameters Last** (columns 15-22):
15. EMA Period
16. ATR Stop Multiplier
17. Risk Bull
18. MACD Fast Period
19. MACD Slow Period
20. MACD Signal Period
21. ATR Period
22. Allocation Defense

## Parameter Column Name Transformation

Convert snake_case to Title Case With Spaces:
- ema_period → EMA Period (keep EMA uppercase)
- atr_stop_multiplier → ATR Stop Multiplier (keep ATR uppercase)
- risk_bull → Risk Bull
- macd_fast_period → MACD Fast Period (keep MACD uppercase)
- macd_slow_period → MACD Slow Period
- macd_signal_period → MACD Signal Period
- atr_period → ATR Period
- allocation_defense → Allocation Defense

## Implementation Location

**File**: `jutsu_engine/application/grid_search_runner.py`
**Method**: `_generate_summary_comparison()` (lines 521-623)

**Key Changes**:
1. Format metrics with proper precision using `round()`
2. Divide percentage values by 100 before rounding
3. Use explicit column ordering list
4. Map parameter names to Title Case using dictionary

## Validation Example

**Sample CSV Row**:
```
Run ID,Symbol Set,Portfolio Balance,Total Return %,Annualized Return %,Max Drawdown,Sharpe Ratio,Sortino Ratio,Calmar Ratio,Total Trades,Profit Factor,Win Rate %,Avg Win ($),Avg Loss ($),EMA Period,ATR Stop Multiplier,Risk Bull,MACD Fast Period,MACD Slow Period,MACD Signal Period,ATR Period,Allocation Defense
001,NVDA-NVDL,47667.74,3.767,0.367,-0.289,1.42,1.11,1.27,49,0.09,0.49,570.74,-6193.47,50,2.0,0.02,12,26,9,14,0.6
```

**Verification**:
- ✅ Portfolio Balance: 2 decimals (47667.74)
- ✅ Total Return %: 3.767 (not 376.677, ready for Excel %)
- ✅ Total Trades: integer (49, not 49.0)
- ✅ Column order: Metrics first, parameters last
- ✅ Parameter names: EMA Period (not ema_period)

## User Workflow (Excel)

1. User opens CSV in Excel
2. Selects percentage columns (Total Return %, Annualized Return %, Max Drawdown, Win Rate %)
3. Formats as "Percentage" (Excel multiplies by 100)
4. Values display correctly:
   - 3.767 → 376.7%
   - 0.367 → 36.7%
   - -0.289 → -28.9%
   - 0.49 → 49.0%
