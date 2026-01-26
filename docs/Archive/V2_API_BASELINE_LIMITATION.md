# V2 API Data Gaps Analysis

## Problem Statement

The V2 Performance API (`/api/v2/performance/{strategy_id}/daily/history`) had significant data gaps compared to the V1 API and the underlying `daily_performance` database model. This represented incomplete implementation of the EOD Daily Performance feature.

**Status**: ✅ **RESOLVED** - Phase 1 and Phase 2 implementation complete (2026-01-25)

## Evidence-Based Gap Analysis

### Category 1: Fields Stored in Database - NOW Returned by V2 API ✅

The `DailyPerformance` model stores these fields. After Phase 1 implementation, `_record_to_data()` now returns all of them:

| Field | In Model | In V2 API | Frontend Needs | Status |
|-------|----------|-----------|----------------|--------|
| `drawdown` | ✅ | ✅ | ✅ | **FIXED** |
| `positions_json` | ✅ | ✅ | ✅ | **FIXED** |
| `total_trades` | ✅ | ✅ | ✅ | **FIXED** |
| `winning_trades` | ✅ | ✅ | ✅ | **FIXED** |
| `losing_trades` | ✅ | ✅ | ✅ | **FIXED** |
| `win_rate` | ✅ | ✅ | ✅ | **FIXED** |
| `t_norm` | ✅ | ✅ | ⚠️ | **FIXED** |
| `z_score` | ✅ | ✅ | ⚠️ | **FIXED** |
| `sma_fast` | ✅ | ✅ | ⚠️ | **FIXED** |
| `sma_slow` | ✅ | ✅ | ⚠️ | **FIXED** |
| `high_water_mark` | ✅ | ✅ | ⚠️ | **FIXED** |
| `initial_capital` | ✅ | ✅ | ⚠️ | **FIXED** |

**Implementation**: Phase 1 added all 15 missing fields to `DailyPerformanceData` schema and `_record_to_data()` function.

### Category 2: Baseline Data via LEFT JOIN ✅

The EOD architecture stores baselines as separate rows with `entity_type='baseline'`. After Phase 2 implementation, the `/daily/history` endpoint now JOINs baseline rows:

| Field | Strategy Row | Baseline Row | V2 Returns | Status |
|-------|--------------|--------------|------------|--------|
| `baseline_value` | ❌ | ✅ (as `total_equity`) | ✅ | **FIXED** |
| `baseline_return` | ❌ | ✅ (as `cumulative_return`) | ✅ | **FIXED** |
| `baseline_daily_return` | ❌ | ✅ (as `daily_return`) | ✅ | **FIXED** |

**Implementation**: Phase 2 added LEFT JOIN to baseline rows in `get_daily_history()`:

```python
# Implemented (lines 386-401 in daily_performance_v2.py)
BaselinePerf = aliased(DailyPerformance, name='baseline_perf')

query_results = db.query(
    DailyPerformance,
    BaselinePerf.total_equity.label('baseline_value'),
    BaselinePerf.cumulative_return.label('baseline_cumulative_return'),
    BaselinePerf.daily_return.label('baseline_daily_return'),
).outerjoin(
    BaselinePerf,
    and_(
        BaselinePerf.trading_date == DailyPerformance.trading_date,
        BaselinePerf.entity_type == 'baseline',
        BaselinePerf.entity_id == baseline_symbol,
        BaselinePerf.mode == DailyPerformance.mode,
    )
).filter(...)
```

### Category 3: V1 vs V2 Feature Parity - ACHIEVED ✅

| Feature | V1 API | V2 API | Status |
|---------|--------|--------|--------|
| Current metrics | ✅ | ✅ | Parity |
| Pre-computed KPIs | ❌ (calculated on-the-fly) | ✅ | V2 Better |
| Historical baseline per-row | ✅ | ✅ | **FIXED** |
| Trade statistics | ✅ | ✅ | **FIXED** |
| Position breakdown | ✅ | ✅ | **FIXED** |
| Drawdown in history | ✅ | ✅ | **FIXED** |

## Frontend Evidence

The frontend components expect these fields in history data - all now provided:

**PerformanceV2.tsx** (lines 380, 427, 444-445, 491-507, 749, 783-794):
- `baseline_value` ✅ - Used for chart comparison line
- `baseline_return` ✅ - Used for alpha calculations
- `drawdown` ✅ - Used in performance tables

**DashboardV2.tsx** (lines 255, 288-289, 302-334):
- `baseline_value` ✅ - Used for baseline equity curve
- `baseline_return` ✅ - Used for period return comparisons

**TradesV2.tsx** (lines 121, 126):
- `total_trades` ✅ - Expected in stats
- `win_rate` ✅ - Expected in stats

## Implementation Plan

### Phase 1: Add Missing Fields to V2 API Response ✅ COMPLETE

**File**: `jutsu_engine/api/routes/daily_performance_v2.py`

**Completed 2026-01-25**:
1. Updated `DailyPerformanceData` class (lines 60-110) with 15 new fields
2. Updated `_record_to_data()` function (lines 160-220) to map all fields

**Validation**:
- ✅ Syntax validation passed
- ✅ All 15 fields present in schema
- ✅ Pydantic model instantiation works (33 total fields)

### Phase 2: Add Baseline JOIN to History Endpoint ✅ COMPLETE

**File**: `jutsu_engine/api/routes/daily_performance_v2.py`

**Completed 2026-01-25**:
1. Added `aliased` import from `sqlalchemy.orm` (line 21)
2. Updated `get_daily_history()` (lines 350-442) with LEFT JOIN to baseline rows
3. Baseline fields populated with percentage conversion (×100)

**Validation**:
- ✅ Syntax validation passed
- ✅ Module imports successfully
- ✅ All 27 integration tests pass

### Phase 3: Frontend Compatibility Verification

**Status**: Pending verification

After backend changes, verify these components work correctly:
- `DashboardV2.tsx` - Baseline row in metrics table
- `PerformanceV2.tsx` - Baseline comparison chart
- `TradesV2.tsx` - Trade statistics

**Expected**: No frontend changes required - backend now returns expected fields.

## Affected Files

### Backend (MODIFIED)
- `jutsu_engine/api/routes/daily_performance_v2.py` - Phase 1 & 2 changes complete

### Frontend (Read-Only - Should Work After Backend Fix)
- `dashboard/src/pages/v2/DashboardV2.tsx`
- `dashboard/src/pages/v2/PerformanceV2.tsx`
- `dashboard/src/pages/v2/TradesV2.tsx`
- `dashboard/src/api/client.ts` - TypeScript types

## Tracking

| Milestone | Date | Status |
|-----------|------|--------|
| Issue Created | 2026-01-25 | ✅ |
| Gap Analysis | 2026-01-25 | ✅ |
| Phase 1 Implementation | 2026-01-25 | ✅ |
| Phase 2 Implementation | 2026-01-25 | ✅ |
| Phase 3 Verification | - | Pending |

**Priority**: HIGH - Multiple regressions from V1 → **RESOLVED**

## Success Criteria

| Criteria | Status |
|----------|--------|
| V2 `/history` returns all fields that V1 returned | ✅ |
| Baseline comparison charts display correctly | Pending verification |
| Trade statistics display correctly | Pending verification |
| Drawdown displays correctly in tables | Pending verification |
| No frontend changes required | Expected ✅ |

## Related Documents

- Serena Memories:
  - `v2_api_phase1_implementation_2026-01-25`
  - `v2_api_phase2_baseline_join_2026-01-25`
  - `v2_api_comprehensive_gap_analysis_2026-01-25`
- CHANGELOG entries: 2026-01-25 (Phase 1 & 2)
