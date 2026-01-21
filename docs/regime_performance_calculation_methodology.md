# Regime Performance Calculation Methodology

**Version:** 1.0
**Last Updated:** 2026-01-20
**Author:** Jutsu Labs
**Target Audience:** Developers verifying or modifying regime performance calculations

## Overview

This document describes the methodology used to compute regime performance metrics in the Backtest Dashboard UI. The calculations transform raw daily portfolio values into per-regime performance statistics, enabling analysis of strategy behavior across different market conditions.

## Data Source

### CSV File Location

The calculation reads from a consolidated dashboard CSV file located at:

```
config/backtest/dashboard_<strategy_name>.csv
```

Example: `config/backtest/dashboard_Hierarchical_Adaptive_v3_5b.csv`

### CSV Structure

The CSV file contains two sections:

**1. Metadata Header (comment lines)**
```csv
# Backtest Dashboard Export
# strategy_name: Hierarchical_Adaptive_v3_5b
# start_date: 2010-01-01
# end_date: 2026-01-16
# initial_capital: 10000.00
# total_return: 8844.76
# annualized_return: 32.35
# sharpe_ratio: 1.18
# max_drawdown: -28.63
# alpha: 7.14
# baseline_ticker: QQQ
```

**2. Data Rows**
| Column | Type | Description |
|--------|------|-------------|
| `Date` | string | Trading date in `YYYY-MM-DD` format |
| `Portfolio_Value` | float | Portfolio value at end of day |
| `Baseline_Value` | float | Baseline (e.g., QQQ) value normalized to same start |
| `BuyHold_Value` | float | Buy-and-hold value (typically equals baseline) |
| `Regime` | string/int | Regime identifier (e.g., `1`, `2`, `3`, `4`, `6`) |
| `Trend` | string | Trend state: `BullStrong`, `Sideways`, `BearStrong` |
| `Vol` | string | Volatility state: `Low`, `High` |

### Regime Definitions

| Cell | Trend | Volatility | Market Condition |
|------|-------|------------|------------------|
| 1 | BullStrong | Low | Strong uptrend, low volatility |
| 2 | BullStrong | High | Strong uptrend, high volatility |
| 3 | Sideways | Low | Range-bound, low volatility |
| 4 | Sideways | High | Range-bound, high volatility |
| 5 | BearStrong | Low | Strong downtrend, low volatility |
| 6 | BearStrong | High | Strong downtrend, high volatility |

## Calculation Methodology

### Step 1: Date Range Filtering

When a user selects a date range (e.g., `2024-09-19` to `2026-01-15`), the data is filtered:

```python
filtered = [t for t in timeseries if start_date <= t['date'] <= end_date]
```

### Step 2: Regime Grouping

Data points are grouped by their `Regime` value:

```python
regime_data = {}
for entry in filtered:
    regime = entry['regime']
    if regime not in regime_data:
        regime_data[regime] = []
    regime_data[regime].append(entry)
```

### Step 3: Segment Identification

**Critical Concept:** A regime may occur in non-consecutive periods. For example, Cell 3 (Sideways/Low) might appear on days 1-10, disappear, then reappear on days 50-60.

To handle this, we identify **segments** - consecutive sequences of days within the same regime:

```python
GAP_THRESHOLD = 5  # days

for entry in sorted_entries:
    entry_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()

    if current_segment_start is None:
        current_segment_start = entry
    elif prev_date:
        gap = (entry_date - prev_date).days
        if gap > GAP_THRESHOLD:
            # End current segment, start new one
            segment_returns.append(calculate_segment_return())
            current_segment_start = entry

    prev_date = entry_date
```

**Why 5 days?** This threshold accounts for weekends (2 days) and typical holiday gaps (up to 3 additional days), while still detecting genuine regime discontinuities.

### Step 4: Compound Return Calculation

For each segment, we calculate a simple return ratio:

```
Segment Return Ratio = End Portfolio Value / Start Portfolio Value
```

Then we compound all segment returns:

```python
compound_multiplier = 1.0
for segment_return in segment_returns:
    compound_multiplier *= segment_return

total_return = (compound_multiplier - 1) * 100
```

**Example:**
- Segment 1: Start $100, End $110 → Ratio = 1.10
- Segment 2: Start $95, End $100 → Ratio = 1.0526
- Compound: 1.10 × 1.0526 = 1.1579
- Total Return: (1.1579 - 1) × 100 = **15.79%**

### Step 5: Annualization

Returns are annualized using **252 trading days** per year:

```python
annualized_return = ((1 + total_return / 100) ** (252 / days) - 1) * 100
```

**Formula breakdown:**
1. Convert percentage to decimal: `1 + total_return / 100`
2. Extrapolate to full year: `^ (252 / days)`
3. Convert back to percentage: `(result - 1) * 100`

**Example:**
- Total Return: 31.22% over 168 days
- Calculation: ((1 + 0.3122) ^ (252/168) - 1) × 100
- Result: **50.31%** annualized

### Step 6: Baseline Comparison

The same segment-based compound return methodology is applied to baseline values:

```python
baseline_segment_returns = []
for segment in segments:
    ratio = segment_end_baseline / segment_start_baseline
    baseline_segment_returns.append(ratio)

baseline_compound = 1.0
for ret in baseline_segment_returns:
    baseline_compound *= ret

baseline_total_return = (baseline_compound - 1) * 100
baseline_annualized = ((1 + baseline_total_return / 100) ** (252 / days) - 1) * 100
```

This ensures apples-to-apples comparison: portfolio and baseline are measured over identical time periods within each regime.

### Step 7: Summary Statistics

For each regime, we calculate:

| Metric | Formula |
|--------|---------|
| `days` | Count of trading days in regime |
| `pct_of_time` | `(days / total_filtered_days) * 100` |
| `total_return` | Compound return across all segments |
| `annualized_return` | `((1 + total_return/100) ^ (252/days) - 1) * 100` |
| `baseline_annualized` | Same formula applied to baseline values |

## Implementation Reference

The calculation is implemented in:

**File:** `jutsu_engine/api/routes/backtest.py`
**Function:** `_calculate_regime_breakdown(timeseries, start_date, end_date)`

### Key Code Sections

```python
# Lines 295-320: Segment identification loop
for entry in sorted_entries:
    entry_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()
    if current_segment_start is None:
        current_segment_start = entry
    elif prev_date:
        gap = (entry_date - prev_date).days
        if gap > 5:  # Gap threshold
            # Calculate and store segment return
            ...

# Lines 330-335: Compound return calculation
compound_multiplier = 1.0
for ret in segment_returns:
    compound_multiplier *= ret
total_return = (compound_multiplier - 1) * 100

# Lines 340-345: Annualization
if days > 0 and total_return != 0:
    annualized = ((1 + total_return / 100) ** (252 / days) - 1) * 100
```

## Verification Example

**Date Range:** 2024-09-19 to 2026-01-15

### Raw Data Points
- First day portfolio: $660,766.12
- Last day portfolio: $894,475.82
- First day baseline: $104,127.53
- Last day baseline: $133,834.55
- Trading days: 325
- Calendar days: 483

### Cell 3 (Sideways/Low) Verification
- Days in regime: 168
- Percent of time: 51.7%
- Total Return: 31.22%
- Annualized: ((1.3122) ^ (252/168) - 1) × 100 = **50.31%**
- Baseline Annualized: **40.97%**

### Period-Level Verification
- Period Return: ((894,475.82 / 660,766.12) - 1) × 100 = **35.37%**
- Annualized: ((1.3537) ^ (365/483) - 1) × 100 = **25.72%**

Note: Period-level uses 365 calendar days; regime-level uses 252 trading days.

## Edge Cases

### 1. Single-Day Segments
If a regime appears for only one day, the segment return is calculated from that day's open-to-close (or previous close to current close) movement.

### 2. Zero Return Segments
If a segment has zero return (start value = end value), it contributes a multiplier of 1.0 to the compound calculation.

### 3. Missing Regimes
Not all regimes appear in every date range. Cell 5 (BearStrong/Low) may be absent if those market conditions didn't occur.

### 4. Very Short Durations
Annualization of very short periods (e.g., 2 days) can produce extreme values. This is mathematically correct but should be interpreted with caution.

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-20 | Initial documentation |
