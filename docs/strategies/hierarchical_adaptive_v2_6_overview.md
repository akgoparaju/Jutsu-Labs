# Hierarchical Adaptive v2.6 - SQQQ Long/Short Capability

**Version**: 2.6  
**Date**: November 19, 2025  
**Status**: Implementation Complete - Awaiting Validation  
**Based On**: Hierarchical Adaptive v2.5 (Asymmetric DD Governor)

---

## Overview

Hierarchical Adaptive v2.6 extends v2.5 with **SQQQ capability** to enable long/short flexibility through 4-weight position mapping. This allows the strategy to profit from both bull and bear markets while maintaining all v2.5 improvements.

### Key Innovation

**Long SQQQ = Short QQQ Exposure** (NOT short selling)
- SQQQ is a 3x inverse ETF providing -3x QQQ exposure
- We trade SQQQ as **long-only positions** (buying SQQQ shares)
- Net short exposure achieved through portfolio allocation, not short selling
- Example: 20% SQQQ allocation = 60% net short QQQ exposure

---

## Changes from v2.5

### 1. 4-Weight Position Mapping

**v2.5** (3 weights):
```
(w_QQQ, w_TQQQ, w_cash)
```

**v2.6** (4 weights):
```
(w_QQQ, w_TQQQ, w_SQQQ, w_cash)
```

### 2. Extended Exposure Range

**v2.5**:
- E_min ∈ [0.4, 1.0] (long-only, 40% to 100% QQQ)
- E_max = 1.5 (150% leveraged long)
- Range: [0.4, 1.5] long-only

**v2.6**:
- E_min ∈ [-0.5, 1.0] (can be net short)
- E_max = 1.5 (unchanged)
- Range: [-0.5, 1.5] long and short
- Default E_min = -0.5 (50% net short capability)

### 3. New Parameter

**Added**:
- `leveraged_short_symbol: str = "SQQQ"` (5th symbol in symbol set)

**Total Parameters**: 21 (v2.5 had 20)

### 4. 4 Exposure Regions

v2.6 maps continuous exposure E_t to 4 portfolio weight regions:

#### Region 1: E_t ≤ -1.0 (Leveraged Short)
- Fully invested in QQQ + SQQQ (no cash)
- Formula:
  ```
  w_SQQQ = (1 - E_t) / 4
  w_QQQ = 1 - w_SQQQ
  w_TQQQ = 0
  w_cash = 0
  ```
- Example: E = -1.5
  - w_SQQQ = 0.625 (62.5% SQQQ)
  - w_QQQ = 0.375 (37.5% QQQ)
  - Net = 0.375 - 1.875 = -1.5 ✓

#### Region 2: -1.0 < E_t < 0 (Defensive Short)
- SQQQ + cash (no QQQ or TQQQ)
- Formula:
  ```
  w_SQQQ = -E_t / 3
  w_cash = 1 - w_SQQQ
  w_QQQ = 0
  w_TQQQ = 0
  ```
- Example: E = -0.6
  - w_SQQQ = 0.2 (20% SQQQ)
  - w_cash = 0.8 (80% cash)
  - Net = -0.6 ✓

#### Region 3: 0 ≤ E_t ≤ 1.0 (Defensive Long)
- **v2.5 logic unchanged**
- QQQ + cash (no TQQQ or SQQQ)
- Formula:
  ```
  w_QQQ = E_t
  w_cash = 1 - E_t
  w_TQQQ = 0
  w_SQQQ = 0
  ```
- Example: E = 0.6
  - w_QQQ = 0.6 (60% QQQ)
  - w_cash = 0.4 (40% cash)
  - Net = 0.6 ✓

#### Region 4: E_t > 1.0 (Leveraged Long)
- **v2.5 logic unchanged**
- QQQ + TQQQ (no cash or SQQQ)
- Formula:
  ```
  w_TQQQ = (E_t - 1) / 2
  w_QQQ = 1 - w_TQQQ
  w_cash = 0
  w_SQQQ = 0
  ```
- Example: E = 1.4
  - w_TQQQ = 0.2 (20% TQQQ)
  - w_QQQ = 0.8 (80% QQQ)
  - Net = 0.8 + 0.6 = 1.4 ✓

---

## Preserved v2.5 Features

✅ **5-Tier Exposure Engine** (unchanged)
- TIER 1: Kalman trend → T_norm
- TIER 2: Baseline exposure → E_trend
- TIER 3: Volatility modulator → S_vol
- TIER 4: VIX compression → P_VIX
- TIER 5: Drawdown governor → P_DD

✅ **Asymmetric DD Governor** (works for negative exposure!)
- Leverage compression path (E > 1.0): same as v2.5
- Defensive preservation path (E ≤ 1.0): handles negative E correctly
- Example: E = -0.6, DD = 12%, P_DD = 0.8
  - E_raw = -0.6 * 0.8 + 1.0 * 0.2 = -0.28
  - Reduces short position during drawdown (moves toward neutral) ✓

✅ **All Parameters** (same defaults as v2.5)
- Kalman filter parameters
- Trend normalization parameters
- Volatility modulator parameters
- VIX compression parameters
- DD governor thresholds (DD_soft = 0.10, DD_hard = 0.20)

---

## Implementation Details

### Code Structure

**File**: `jutsu_engine/strategies/Hierarchical_Adaptive_v2_6.py` (820 lines)

**Key Methods**:

1. `_map_exposure_to_weights()`:
   - Returns 4 weights instead of 3
   - Implements 4-region position mapping
   - All formulas validated through Sequential MCP

2. `_execute_rebalance()`:
   - Extended to handle SQQQ trades
   - Buys SQQQ when w_SQQQ > 0 (long position)
   - Sells all SQQQ when w_SQQQ = 0

3. `_check_rebalancing_threshold()`:
   - Includes SQQQ weight drift in calculation
   - Rebalances if any weight drifts > threshold

**State Tracking**:
```python
self.current_qqq_weight: Decimal
self.current_tqqq_weight: Decimal
self.current_sqqq_weight: Decimal  # NEW in v2.6
```

---

## Configuration Files

### Grid Search

**File**: `grid-configs/grid_search_hierarchical_adaptive_v2_6.yaml`

**Key Settings**:
- Strategy: `Hierarchical_Adaptive_v2_6`
- Symbol set: `QQQ_TQQQ_SQQQ_VIX` (4 symbols)
- E_min grid: `[-0.5, 0.0, 0.4]` (tests SQQQ capability)
- Total combinations: 243 runs (3^5)
- Focus: Validate SQQQ allocation and bear market performance

**Symbol Set**:
```yaml
symbol_sets:
  - name: "QQQ_TQQQ_SQQQ_VIX"
    signal_symbol: "QQQ"
    core_long_symbol: "QQQ"
    leveraged_long_symbol: "TQQQ"
    leveraged_short_symbol: "SQQQ"  # NEW
    vix_symbol: "VIX"
```

### Walk-Forward Optimization

**File**: `grid-configs/wfo_hierarchical_adaptive_v2_6.yaml`

**Key Settings**:
- 29 windows × 16 combinations = 464 total backtests
- E_min tested: `[-0.5, 0.0]` (short vs neutral)
- T_max tested: `[50, 60]`
- k_trend tested: `[0.3, 0.5]`
- Focus: SQQQ effectiveness across market regimes

---

## Expected Performance

### vs v2.5 Improvements

**Max Drawdown**:
- v2.5: -15% to -18% (can reduce to E_min = 0.4)
- v2.6: -12% to -15% (can go net short via SQQQ)
- **Expected**: 2-3% improvement in worst-case drawdown

**Bear Market Returns**:
- v2.5: Can only reduce exposure to 40% QQQ
- v2.6: Can profit from bear markets via SQQQ
- **Expected**: Positive returns during prolonged bear markets

**Sortino Ratio**:
- v2.5: 1.6 - 2.0
- v2.6: 1.7 - 2.1 (better downside protection)
- **Expected**: +0.1 to +0.2 improvement

**Exposure Utilization**:
- v2.5: [0.4, 1.5] = 110% range (long-only)
- v2.6: [-0.5, 1.5] = 200% range (long and short)
- **Expected**: Full utilization of extended range

---

## Validation Strategy

### 1. Grid Search Validation

**Objectives**:
- ✅ Verify 4-weight position mapping correctness
- ✅ Validate SQQQ allocation in bear scenarios
- ✅ Test E_min sensitivity (-0.5 vs 0.0 vs 0.4)
- ✅ Check net exposure calculations

**Success Criteria**:
- All weights non-negative and sum to 1.0
- Net exposure matches formula in all 4 regions
- SQQQ allocated during bearish + DD conditions
- No position mapping errors

### 2. Walk-Forward Validation

**Objectives**:
- Measure SQQQ contribution to risk-adjusted returns
- Test robustness across market regimes
- Compare E_min = -0.5 vs E_min = 0.0
- Validate crisis period performance (COVID, 2022 bear)

**Success Criteria**:
- OOS Sortino ratio > 1.6 (vs v2.5 > 1.5)
- OOS max drawdown < 22% (vs v2.5 < 25%)
- SQQQ adds value in bear markets (not just complexity)
- Parameter stability across windows

### 3. v2.5 Comparison

**Head-to-Head Test**:
- Same parameter settings (T_max, k_trend, etc.)
- Same time period (2010-2025)
- Isolate SQQQ contribution
- Crisis period analysis (COVID crash, 2022 bear)

**Decision Criteria**:
- ✅ **Adopt v2.6**: Better OOS performance, SQQQ adds value consistently
- ⚠️ **Conditional**: Good in bear markets but complexity cost-benefit unclear
- ❌ **Revert to v2.5**: No improvement or degraded performance

---

## Usage

### Basic Example

```python
from jutsu_engine.strategies import Hierarchical_Adaptive_v2_6

# Create strategy with SQQQ capability
strategy = Hierarchical_Adaptive_v2_6(
    signal_symbol="QQQ",
    core_long_symbol="QQQ",
    leveraged_long_symbol="TQQQ",
    leveraged_short_symbol="SQQQ",  # Enable SQQQ
    vix_symbol="VIX",
    E_min=Decimal("-0.5"),  # Allow 50% net short
    E_max=Decimal("1.5"),   # Allow 150% net long
    # ... other parameters
)
```

### Long-Only Mode (v2.5 compatibility)

```python
# Disable SQQQ capability by setting E_min ≥ 0
strategy = Hierarchical_Adaptive_v2_6(
    # ... symbols ...
    E_min=Decimal("0.4"),  # Long-only (same as v2.5)
    # ... other parameters ...
)
# SQQQ will never be allocated (E_t never < 0)
```

### Run Grid Search

```bash
jutsu grid-search --config grid-configs/grid_search_hierarchical_adaptive_v2_6.yaml
```

### Run WFO

```bash
jutsu wfo --config grid-configs/wfo_hierarchical_adaptive_v2_6.yaml
```

---

## Implementation Notes

### SQQQ Trading Mechanics

**Important**: SQQQ trades are **LONG positions**, not short sales
- Buy SQQQ shares when w_SQQQ > 0
- Sell SQQQ shares when w_SQQQ decreases
- No short selling, no margin requirements
- Standard long-only brokerage account compatible

**Net Exposure Calculation**:
```
E_net = w_QQQ * 1.0 + w_TQQQ * 3.0 + w_SQQQ * (-3.0)
```

### Rebalancing

**Threshold Check** (includes all 4 weights):
```python
drift = abs(target_qqq - current_qqq) + 
        abs(target_tqqq - current_tqqq) + 
        abs(target_sqqq - current_sqqq)  # NEW

if drift > rebalance_threshold:
    rebalance()
```

**Potential Increase**: 4 weights may increase rebalancing frequency vs 3 weights

### Testing Requirements

**Unit Tests** (pending):
- 4-weight position mapping for all E_t values
- SQQQ allocation in negative exposure regions
- Net exposure calculation correctness
- Rebalancing with SQQQ trades
- Edge cases (E_t = 0, E_t = -1.0)

**Integration Tests** (pending):
- Full backtest with SQQQ allocation
- Crisis period behavior (COVID crash)
- Long-only mode validation (E_min ≥ 0)

---

## Next Steps

### Immediate (Validation Phase)

1. **Run Grid Search**:
   - Execute 243-run grid search
   - Validate position mapping correctness
   - Analyze SQQQ allocation patterns

2. **Run WFO**:
   - Execute 29-window WFO (464 backtests)
   - Measure SQQQ contribution by regime
   - Compare E_min = -0.5 vs 0.0

3. **Create Unit Tests**:
   - Test all 4 exposure regions
   - Validate SQQQ allocation logic
   - Test rebalancing with SQQQ

### Post-Validation

**If v2.6 validates successfully**:
- Create comprehensive documentation (hierarchical_adaptive_v2_6.md)
- Add integration tests
- Paper trading validation
- Production deployment planning

**If validation shows issues**:
- Refine position mapping formulas
- Adjust E_min default value
- Consider hybrid approaches
- Document learnings for future iterations

---

## References

- **v2.5 Specification**: `docs/strategies/hierarchical_adaptive_v2_5.md`
- **v2.5 Implementation**: `jutsu_engine/strategies/Hierarchical_Adaptive_v2_5.py`
- **v2.6 Implementation**: `jutsu_engine/strategies/Hierarchical_Adaptive_v2_6.py`
- **Grid Search Config**: `grid-configs/grid_search_hierarchical_adaptive_v2_6.yaml`
- **WFO Config**: `grid-configs/wfo_hierarchical_adaptive_v2_6.yaml`
- **CHANGELOG Entry**: `CHANGELOG.md` (Unreleased section)
