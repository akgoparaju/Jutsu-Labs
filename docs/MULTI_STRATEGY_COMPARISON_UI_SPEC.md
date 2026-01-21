# Multi-Strategy Comparison UI Specification

**Version:** 1.2.0  
**Date:** 2026-01-21  
**Status:** APPROVED  
**Author:** DASHBOARD_FRONTEND_AGENT + Sequential Thinking MCP

---

## 1. Overview

### 1.1 Purpose
Enable users to compare up to **3 trading strategies** side-by-side across all dashboard tabs, with overlaid charts and comparative metrics tables.

### 1.2 Design Principles
1. **Single-Strategy Preservation**: When only 1 strategy selected, view remains exactly as today (no comparison tables, current card layout)
2. **Charts**: Overlay multiple strategy lines on single chart (only when >1 selected)
3. **Metrics with Baseline**: Side-by-side comparison tables **always include Baseline (QQQ) column** for reference (only when >1 selected)
4. **Detailed Views**: Single strategy at a time (Regime, Trades, Positions)
5. **Accessibility**: Colorblind-friendly patterns (solid, dashed, dotted) in addition to colors
6. **Shareability**: URL-encoded strategy selection for sharing views
7. **Extensibility**: Designed for N strategies, enforced to 3 for visual clarity (configurable later)

### 1.3 Global Baseline Rule
**When comparing strategies (2+ selected), Baseline (QQQ) is ALWAYS included:**
- In **charts**: Gray long-dash line showing QQQ performance
- In **metrics tables**: Final column showing Baseline metrics for comparison
- **Purpose**: Provides market benchmark context for all strategy comparisons
- **Applies to**: Backtest, Performance, and Dashboard tabs

### 1.3 Current State
- ✅ `StrategyContext` has `compareStrategies[]`, `isCompareMode`, `toggleCompareStrategy()`
- ✅ `StrategySelector` has compare mode toggle (pill buttons)
- ✅ APIs support `strategy_id` parameter
- ❌ Charts only show single strategy
- ❌ Metrics only show single strategy
- ❌ No multi-select dropdown component

---

## 2. Strategy Multi-Selector Component

### 2.1 Component Design

```
┌─────────────────────────────────────────────────────────┐
│  Select Strategies ▼                                    │
├─────────────────────────────────────────────────────────┤
│  ☑ v3.5b (Primary)                                     │
│  ☑ v3.5d                                               │
│  ☐ v3.5c                                               │
│  ☐ v4.0                                                │
└─────────────────────────────────────────────────────────┘

Selected:
┌──────────┐  ┌──────────┐  ┌──────────┐
│ 🔵 v3.5b │  │ 🟢 v3.5d │  │ + Add    │
│     ✕    │  │     ✕    │  │          │
└──────────┘  └──────────┘  └──────────┘
```

### 2.2 Behavior
- **Default**: v3.5b selected only (preserves current single-strategy view)
- **Multi-select dropdown** with checkboxes
- **Color chips** below dropdown showing selected strategies
- **Max 3** strategies enforced (4th checkbox disabled with tooltip)
- **First selected** = Primary (shows first in comparisons)
- **Remove button (✕)** on each chip to deselect
- **Persistent** selection via `localStorage`
- **URL sync**: Selected strategies encoded in URL query params (`?strategies=v3_5b,v3_5d`)
- **View switching**: Comparison view only activates when 2+ strategies selected

### 2.3 Responsive Design
| Viewport | Behavior |
|----------|----------|
| Desktop (≥1024px) | Full dropdown + horizontal chips |
| Tablet (768-1023px) | Compact dropdown + horizontal chips |
| Mobile (<768px) | Full-width dropdown + stacked chips |

### 2.4 Color & Pattern System (Colorblind-Friendly)

| Position | Color | Hex | Line Pattern | CSS Class |
|----------|-------|-----|--------------|-----------|
| Strategy 1 | Blue | `#3b82f6` | **Solid** (━━━) | `text-blue-500`, `bg-blue-500` |
| Strategy 2 | Green | `#22c55e` | **Dashed** (- - -) | `text-green-500`, `bg-green-500` |
| Strategy 3 | Amber | `#f59e0b` | **Dotted** (···) | `text-amber-500`, `bg-amber-500` |
| Baseline | Gray | `#9ca3af` | **Long Dash** (— — —) | `text-gray-400` |

**Accessibility Notes:**
- Patterns distinguish lines even when colors are indistinguishable
- Legend shows both color swatch AND pattern preview
- Tooltips work on all line types

---

## 3. Backtest Tab Design

### 3.0 Single-Strategy View (DEFAULT - Unchanged from Today)

When only **1 strategy** is selected (default: v3.5b), the view remains **exactly as current implementation**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📈 Backtest Results                                                 │
│ Strategy: Hierarchical Adaptive v3.5b                               │
│                                                                     │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ Strategy: [v3.5b ▼] [+ Add to compare]                         │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ ALL-TIME PERFORMANCE (2022-01-01 to 2026-01-21)                    │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ │Initial  │ │Total    │ │CAGR     │ │Sharpe   │ │Max DD   │ │Alpha    │
│ │$100,000 │ │+245.3%  │ │+28.4%   │ │1.42     │ │-18.2%   │ │+12.3%   │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
│                                                                     │
│ EQUITY CURVE                                                        │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │  ───── Portfolio (blue solid)                                   │ │
│ │  - - - Baseline QQQ (gray dashed)                              │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ REGIME PERFORMANCE [Full table - unchanged]                         │
│ STRATEGY CONFIG [JSON pane - unchanged]                            │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Metric cards in horizontal row (current design)
- Chart shows Portfolio vs Baseline only
- No comparison table format
- "[+ Add to compare]" button enables multi-strategy mode

### 3.1 Multi-Strategy Layout Overview (2-3 strategies selected)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📈 Backtest Results                                                         │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Strategies: [🔵 v3.5b ✕] [🟢 v3.5d ✕] [+ Add ▼]                        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ═══════════════════════════════════════════════════════════════════════════ │
│ ALL-TIME METRICS COMPARISON                                                 │
│ ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│ ┌──────────────┬────────────────┬────────────────┬─────────────────┐       │
│ │ Metric       │ 🔵━ v3.5b      │ 🟢- - v3.5d    │ ⬜— Baseline    │       │
│ ├──────────────┼────────────────┼────────────────┼─────────────────┤       │
│ │ Total Return │ +245.3% ★      │ +198.7%        │ +156.2%         │       │
│ │ CAGR         │ +28.4% ★       │ +24.1%         │ +18.9%          │       │
│ │ Sharpe       │ 1.42 ★         │ 1.31           │ 0.98            │       │
│ │ Max DD       │ -18.2% ★       │ -22.1%         │ -28.4%          │       │
│ │ Alpha        │ +12.3% ★       │ +8.7%          │ —               │       │
│ └──────────────┴────────────────┴────────────────┴─────────────────┘       │
│                                                                             │
│ ═══════════════════════════════════════════════════════════════════════════ │
│ EQUITY CURVE (% Return)                              [% Return | $ Value]   │
│ ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│     ┌───────────────────────────────────────────────────────────────────┐   │
│  +300%│     ████████                                                    │   │
│       │    ██      ███                                                  │   │
│  +200%│   ██         ███ ━━━ 🔵 v3.5b (solid)                          │   │
│       │  ██            ███████                                          │   │
│  +100%│ ██      ─ ─ ─ 🟢 v3.5d (dashed)                                │   │
│       │██ ─── ─── ─── ⬜ Baseline (long dash)                           │   │
│    0% │─────────────────────────────────────────────────────────────────│   │
│       └─────────────────────────────────────────────────────────────────┘   │
│         2022        2023        2024        2025        2026               │
│                                                                             │
│ ═══════════════════════════════════════════════════════════════════════════ │
│ REGIME PERFORMANCE                        Strategy: [v3.5b ▼]              │
│ ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│ ┌─────────┬───────┬───────────┬────────────┬───────┬───────────┐           │
│ │ Regime  │ Trend │ Return    │ Annualized │ Days  │ % of Time │           │
│ ├─────────┼───────┼───────────┼────────────┼───────┼───────────┤           │
│ │ Cell 0  │ Bull  │ +45.2%    │ +32.1%     │ 245   │ 28.4%     │           │
│ │ Cell 1  │ Bear  │ -8.3%     │ -12.4%     │ 89    │ 10.3%     │           │
│ │ ...     │ ...   │ ...       │ ...        │ ...   │ ...       │           │
│ └─────────┴───────┴───────────┴────────────┴───────┴───────────┘           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Visual Elements:**
- ★ = Best performer in each row
- Pattern indicators in headers match chart line styles
- Baseline column always present in comparison mode
- Regime table remains single-strategy (dropdown selector)

### 3.2 Metrics Display Rules

**Critical Principle**: Single strategy view remains EXACTLY as today's UI.

| Component | Single Strategy (1 selected) | Multi-Strategy (2-3 selected) |
|-----------|------------------------------|-------------------------------|
| All-Time Metrics | 6 metric cards (current row layout) | Comparison table: Strategies + **Baseline** column |
| Period Metrics | 5 metric cards (current row layout) | Comparison table: Strategies + **Baseline** column |
| Regime Table | Full table (unchanged) | Single strategy dropdown selector |
| Config Pane | JSON view (unchanged) | Single strategy (unchanged) |

**Multi-Strategy Comparison Table Format:**
- Strategies as columns (color-coded headers with pattern indicators)
- **Baseline (QQQ) always included as final column** for reference
- Metrics as rows
- Delta indicators showing best/worst performer per metric

### 3.3 Chart Implementation

```typescript
import { LineStyle } from 'lightweight-charts'

// Color + Pattern system for colorblind accessibility
const STRATEGY_STYLES = {
  0: { color: '#3b82f6', lineStyle: LineStyle.Solid, name: 'Blue (Solid)' },
  1: { color: '#22c55e', lineStyle: LineStyle.Dashed, name: 'Green (Dashed)' },
  2: { color: '#f59e0b', lineStyle: LineStyle.Dotted, name: 'Amber (Dotted)' },
}

const BASELINE_STYLE = {
  color: '#9ca3af',
  lineStyle: LineStyle.LargeDashed,  // — — — pattern
  name: 'Baseline (QQQ)',
}

// Single strategy: Same as today (blue solid + gray baseline)
if (selectedStrategies.length === 1) {
  const series = chart.addLineSeries({
    color: '#3b82f6',
    lineWidth: 2,
    lineStyle: LineStyle.Solid,
    title: 'Portfolio',
  })
  series.setData(strategyData[selectedStrategies[0]])
  
  const baselineSeries = chart.addLineSeries({
    ...BASELINE_STYLE,
    lineWidth: 2,
    title: 'Baseline (QQQ)',
  })
  baselineSeries.setData(baselineData)
}

// Multi-strategy: Overlaid with distinct colors AND patterns
else {
  selectedStrategies.forEach((strategyId, index) => {
    const style = STRATEGY_STYLES[index]
    const series = chart.addLineSeries({
      color: style.color,
      lineStyle: style.lineStyle,
      lineWidth: 2,
      title: strategyDisplayName(strategyId),
    })
    series.setData(strategyData[strategyId])
  })

  // Baseline always included in multi-strategy view
  const baselineSeries = chart.addLineSeries({
    ...BASELINE_STYLE,
    lineWidth: 2,
  })
  baselineSeries.setData(baselineData)
}
```

### 3.4 Mobile Design (Metrics - Multi-Strategy)

```
┌─────────────────────────────┐
│ 🔵━ v3.5b (Solid)      ★    │
│ ┌─────────┬───────────────┐ │
│ │ Return  │ +245.3%       │ │
│ │ CAGR    │ +28.4%        │ │
│ │ Sharpe  │ 1.42          │ │
│ │ Max DD  │ -18.2%        │ │
│ │ Alpha   │ +12.3%        │ │
│ └─────────┴───────────────┘ │
└─────────────────────────────┘
┌─────────────────────────────┐
│ 🟢- - v3.5d (Dashed)        │
│ ┌─────────┬───────────────┐ │
│ │ Return  │ +198.7%       │ │
│ │ CAGR    │ +24.1%        │ │
│ │ Sharpe  │ 1.31          │ │
│ │ Max DD  │ -22.1%        │ │
│ │ Alpha   │ +8.7%         │ │
│ └─────────┴───────────────┘ │
└─────────────────────────────┘
┌─────────────────────────────┐
│ ⬜— Baseline (QQQ)          │
│ ┌─────────┬───────────────┐ │
│ │ Return  │ +156.2%       │ │
│ │ CAGR    │ +18.9%        │ │
│ │ Sharpe  │ 0.98          │ │
│ │ Max DD  │ -28.4%        │ │
│ │ Alpha   │ —             │ │
│ └─────────┴───────────────┘ │
└─────────────────────────────┘
```

**Mobile Notes:**
- Cards stacked vertically
- Each card shows pattern indicator in header
- Baseline card always last
- ★ indicates best overall performer

---

## 4. Performance Tab Design

### 4.1 Components Affected

| Component | Single Strategy (1 selected) | Multi-Strategy (2-3 selected) |
|-----------|------------------------------|-------------------------------|
| Strategy Selector | Single dropdown | Multi-select with chips |
| Equity Curve | Single line + baseline (unchanged) | Up to 3 lines + baseline |
| Top Metrics | 6 cards (current row layout) | Comparison table: Strategies + **Baseline** column |
| Period Metrics | 4 cards (current row layout) | Comparison table: Strategies + **Baseline** column |
| Regime Breakdown | Table for single strategy | Single strategy dropdown |
| Time Range | Dropdown | Unchanged |

### 4.2 Performance Metrics Comparison Table (Multi-Strategy)

```
┌──────────────┬────────────────┬────────────────┬─────────────────┐
│ Metric       │ 🔵━ v3.5b      │ 🟢- - v3.5d    │ ⬜— Baseline    │
├──────────────┼────────────────┼────────────────┼─────────────────┤
│ Period Return│ +8.4% ★        │ +6.2%          │ +4.1%           │
│ CAGR         │ +24.3% ★       │ +21.8%         │ +15.2%          │
│ Sharpe       │ 1.38 ★         │ 1.24           │ 0.92            │
│ Max DD       │ -12.4% ★       │ -15.8%         │ -18.2%          │
│ Alpha        │ +9.1% ★        │ +6.6%          │ —               │
│ Beta         │ 0.82           │ 0.91           │ 1.00            │
└──────────────┴────────────────┴────────────────┴─────────────────┘
```

### 4.3 Live Data Consideration
- Performance tab shows **live trading data** (not backtest)
- Only strategies with live data should be selectable
- Gray out strategies without live data in multi-selector
- Baseline column uses live QQQ data for same time period

---

## 5. Dashboard Tab Design

### 5.1 Components

| Component | Single Strategy (1 selected) | Multi-Strategy (2-3 selected) |
|-----------|------------------------------|-------------------------------|
| Key Metrics Cards | Current card layout (unchanged) | Comparison table: Strategies + **Baseline** |
| Equity Curve | Single line + baseline (unchanged) | Up to 3 lines + baseline |
| Position Table | Full table (unchanged) | Single strategy dropdown |
| Decision Tree | Full view (unchanged) | Single strategy dropdown |
| Target Allocation | Full view (unchanged) | Single strategy dropdown |
| Regime Indicator | Single view (unchanged) | Single strategy dropdown |

### 5.2 Key Metrics Comparison Table (Multi-Strategy)

```
┌──────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ Metric           │ 🔵━ v3.5b       │ 🟢- - v3.5d     │ ⬜— Baseline    │
├──────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ Total Value      │ $1,245,678 ★    │ $1,198,432      │ $1,156,200      │
│ Today's Return   │ +0.84% ★        │ +0.72%          │ +0.65%          │
│ YTD Return       │ +12.3% ★        │ +10.8%          │ +8.4%           │
│ MTD Return       │ +3.2% ★         │ +2.8%           │ +2.1%           │
│ Current Regime   │ Cell 2          │ Cell 2          │ —               │
│ Position         │ 80% TQQQ        │ 60% TQQQ        │ —               │
└──────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

**Dashboard-Specific Notes:**
- Baseline shows hypothetical buy-and-hold QQQ value with same initial capital
- Position and Regime rows show "—" for Baseline (not applicable)
- ★ indicates best performer for each metric
- Total Value comparison helps visualize dollar difference between strategies

---

## 6. Trades Tab Design

### 6.1 Design Decision: Single Strategy Only

**Rationale**: Trade lists from different strategies would be confusing if mixed. Each strategy has independent trade history.

**Implementation**:
- Keep existing single-select dropdown
- No multi-strategy overlay needed
- User switches between strategies to view trades

---

## 7. Technical Architecture

### 7.1 New Files

```
dashboard/src/
├── components/
│   └── StrategyMultiSelector.tsx    # NEW: Multi-select component
├── hooks/
│   └── useMultiStrategyData.ts      # NEW: Parallel data fetching
└── constants/
    └── strategyColors.ts            # NEW: Color system constants
```

### 7.2 Modified Files

```
dashboard/src/
├── contexts/
│   └── StrategyContext.tsx          # Add: colorForStrategy(id, index)
├── pages/v2/
│   ├── BacktestV2.tsx               # Major: Multi-strategy support
│   ├── PerformanceV2.tsx            # Major: Multi-strategy support
│   ├── DashboardV2.tsx              # Minor: Key metrics comparison
│   └── TradesV2.tsx                 # Minor: Keep single strategy
└── api/
    └── client.ts                    # Add: Batch fetch helpers
```

### 7.3 useMultiStrategyData Hook

```typescript
// Fetches data for multiple strategies in parallel
function useMultiStrategyData<T>(
  queryKeyBase: string,
  fetchFn: (strategyId: string) => Promise<T>,
  strategyIds: string[]
) {
  const queries = useQueries({
    queries: strategyIds.map(id => ({
      queryKey: [queryKeyBase, id],
      queryFn: () => fetchFn(id),
    }))
  })
  
  return {
    data: Object.fromEntries(
      queries.map((q, i) => [strategyIds[i], q.data])
    ),
    isLoading: queries.some(q => q.isLoading),
    isError: queries.some(q => q.isError),
  }
}
```

### 7.4 Strategy Color Mapping

```typescript
// constants/strategyColors.ts
export const STRATEGY_COLORS = [
  { color: '#3b82f6', name: 'Blue', tailwind: 'blue-500' },
  { color: '#22c55e', name: 'Green', tailwind: 'green-500' },
  { color: '#f59e0b', name: 'Amber', tailwind: 'amber-500' },
] as const

export function getStrategyColor(index: number) {
  return STRATEGY_COLORS[index % STRATEGY_COLORS.length]
}

// In StrategyContext.tsx
function colorForStrategy(strategyId: string): typeof STRATEGY_COLORS[number] {
  const index = compareStrategies.indexOf(strategyId)
  return getStrategyColor(index === -1 ? 0 : index)
}
```

---

## 8. Implementation Phases

### Phase 1: Foundation (1-2 days)
- [ ] Create `StrategyMultiSelector.tsx` component
- [ ] Create `strategyColors.ts` constants
- [ ] Update `StrategyContext.tsx` with color mapping
- [ ] Create `useMultiStrategyData.ts` hook

### Phase 2: Backtest Tab (2-3 days)
- [ ] Replace StrategySelector with StrategyMultiSelector
- [ ] Implement multi-strategy chart (lightweight-charts)
- [ ] Create metrics comparison table component
- [ ] Add single-strategy dropdown for regime table
- [ ] Test mobile responsiveness

### Phase 3: Performance Tab (1-2 days)
- [ ] Apply same pattern as Backtest
- [ ] Handle live data availability (gray out unavailable)
- [ ] Test time range interactions with multi-strategy

### Phase 4: Dashboard Tab (1 day)
- [ ] Key metrics comparison cards
- [ ] Position/Decision Tree single-strategy dropdowns

### Phase 5: Polish & Testing (1-2 days)
- [ ] Cross-browser testing
- [ ] Mobile testing
- [ ] Performance optimization (parallel fetches)
- [ ] Documentation

**Total Estimate: 6-10 days**

---

## 9. Design Decisions (RESOLVED)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Strategy limit | **Max 3** | Sufficient for visual clarity; can increase later |
| Colorblind support | **Yes - patterns** | Solid, dashed, dotted, long-dash for accessibility |
| Default selection | **v3.5b only** | Preserves current single-strategy view as default |
| URL sharing | **Yes** | `?strategies=v3_5b,v3_5d` format for shareability |
| Single-strategy view | **Preserve current** | No comparison tables when only 1 selected |
| Baseline in tables | **Yes - always** | Included as column when comparing strategies |

---

## 10. Appendix: UI Mockups

### A. Strategy Multi-Selector States

**Empty State:**
```
┌─────────────────────────────────┐
│ Select strategies to compare ▼  │
└─────────────────────────────────┘
```

**Single Selection:**
```
┌─────────────────────────────────┐
│ 1 strategy selected ▼           │
└─────────────────────────────────┘
  🔵 v3.5b ✕
```

**Multiple Selection:**
```
┌─────────────────────────────────┐
│ 2 strategies selected ▼         │
└─────────────────────────────────┘
  🔵 v3.5b ✕   🟢 v3.5d ✕
```

**Max Reached:**
```
┌─────────────────────────────────┐
│ 3 strategies (max) ▼            │
└─────────────────────────────────┘
  🔵 v3.5b ✕   🟢 v3.5d ✕   🟠 v4.0 ✕
```

### B. Comparison Table Layout (with Baseline)

**Desktop (≥1024px) - 2 Strategies + Baseline:**
```
┌──────────────┬───────────────┬───────────────┬──────────────────┐
│ Metric       │ 🔵━ v3.5b     │ 🟢- - v3.5d   │ ⬜— — Baseline   │
├──────────────┼───────────────┼───────────────┼──────────────────┤
│ Total Return │ +245.3% ★     │ +198.7%       │ +156.2%          │
│ CAGR         │ +28.4% ★      │ +24.1%        │ +18.9%           │
│ Sharpe       │ 1.42 ★        │ 1.31          │ 0.98             │
│ Max DD       │ -18.2% ★      │ -22.1%        │ -28.4%           │
│ Alpha        │ +12.3% ★      │ +8.7%         │ —                │
└──────────────┴───────────────┴───────────────┴──────────────────┘
★ = Best in row
```

**Desktop (≥1024px) - 3 Strategies + Baseline:**
```
┌──────────────┬───────────────┬───────────────┬───────────────┬─────────────────┐
│ Metric       │ 🔵━ v3.5b     │ 🟢- - v3.5d   │ 🟠··· v4.0    │ ⬜— Baseline    │
├──────────────┼───────────────┼───────────────┼───────────────┼─────────────────┤
│ Total Return │ +245.3% ★     │ +198.7%       │ +212.4%       │ +156.2%         │
│ CAGR         │ +28.4% ★      │ +24.1%        │ +25.8%        │ +18.9%          │
│ Sharpe       │ 1.42 ★        │ 1.31          │ 1.38          │ 0.98            │
│ Max DD       │ -18.2% ★      │ -22.1%        │ -19.8%        │ -28.4%          │
│ Alpha        │ +12.3% ★      │ +8.7%         │ +10.2%        │ —               │
└──────────────┴───────────────┴───────────────┴───────────────┴─────────────────┘
```

**Legend Key:**
- ━ = Solid line (Strategy 1)
- - - = Dashed line (Strategy 2)
- ··· = Dotted line (Strategy 3)
- — = Long dash (Baseline)
- ★ = Best performer in row

**Tablet (768-1023px):** Same as desktop, compressed widths

**Mobile (<768px):** Stacked cards with Baseline card at bottom (see Section 3.4)

---

## 11. Acceptance Criteria

### Must Have
- [ ] Multi-select dropdown with max 3 strategies
- [ ] Color-coded chips showing selected strategies
- [ ] **Colorblind-friendly patterns** (solid, dashed, dotted, long-dash)
- [ ] **Default to v3.5b only** - current single-strategy view preserved
- [ ] **Single-strategy view unchanged** when only 1 selected
- [ ] Overlaid equity curves on Backtest and Performance charts (when >1 selected)
- [ ] Side-by-side metrics comparison tables **with Baseline column** (when >1 selected)
- [ ] **URL-encoded strategy selection** (`?strategies=v3_5b,v3_5d`) for sharing
- [ ] Mobile-responsive layout
- [ ] Persistent selection (localStorage)

### Should Have
- [ ] Interactive chart legend (click to hide/show series)
- [ ] Regime table single-strategy dropdown
- [ ] Performance tab live data availability check (gray out unavailable)
- [ ] Best-performer indicator (★) in comparison tables

### Nice to Have
- [ ] Export comparison as image/PDF
- [ ] Keyboard shortcuts for strategy switching
- [ ] Animation on view transition (single → comparison)

---

## 12. URL Schema

### Query Parameter Format
```
https://dashboard.example.com/backtest?strategies=v3_5b,v3_5d
https://dashboard.example.com/performance?strategies=v3_5b,v3_5d,v4_0
```

### Behavior
- **No parameter**: Default to `v3_5b` (single-strategy view)
- **Single strategy**: `?strategies=v3_5d` → Single-strategy view for v3.5d
- **Multiple strategies**: `?strategies=v3_5b,v3_5d` → Comparison view
- **Invalid strategy ID**: Ignored, valid ones shown
- **>3 strategies**: First 3 used, others ignored

### URL Sync Implementation
```typescript
// Read from URL on page load
const urlParams = new URLSearchParams(window.location.search)
const strategiesParam = urlParams.get('strategies')
const strategies = strategiesParam 
  ? strategiesParam.split(',').slice(0, 3)
  : ['v3_5b']  // Default

// Update URL when selection changes
useEffect(() => {
  const params = new URLSearchParams(window.location.search)
  params.set('strategies', selectedStrategies.join(','))
  window.history.replaceState({}, '', `?${params.toString()}`)
}, [selectedStrategies])
```

---

**Document End**
