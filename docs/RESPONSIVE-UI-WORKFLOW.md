# Responsive UI Implementation Workflow

**Version:** 1.0.0
**Date:** 2026-01-14
**Source:** docs/RESPONSIVE-UI-IMPLEMENTATION.md v1.1.0
**Total Tasks:** 63 tasks across 4 phases

---

## Quick Reference

| Phase | Name | Tasks | Est. Days | Dependencies |
|-------|------|-------|-----------|--------------|
| 1 | Foundation | 15 | 3 | None |
| 2 | Navigation | 21 | 3 | Phase 1.3, 1.4 |
| 3 | Dashboard | 19 | 5 | Phase 2.4 |
| 4 | Pages + Polish | 25 | 5 | Phase 3 |

**Critical Path:** 1.1 → 1.2 → 1.3 → 1.4 → 2.1 → 2.2/2.3 → 2.4 → 3.1 → 3.2-3.7 → 4.1-4.5 → 4.6 → 4.7 → 4.8

---

## Phase 1: Foundation (Days 1-3)

### Overview
Create the responsive infrastructure: Tailwind config, CSS variables, hooks, and utility components.

### 1.1 Tailwind Configuration
**File:** `dashboard/tailwind.config.js`
**Depends on:** None
**Enables:** All subsequent tasks

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 1.1.1 | Add `xs: '480px'` breakpoint to screens | pending | Breakpoint available in classes |
| 1.1.2 | Add `3xl: '1920px'` breakpoint to screens | pending | Breakpoint available in classes |
| 1.1.3 | Configure container query breakpoints (xs-2xl) | pending | @container variants work |
| 1.1.4 | Verify existing bull/bear colors preserved | pending | No color regressions |

**Validation:** `cd dashboard && npm run build` passes

### 1.2 CSS Variables & Global Styles
**File:** `dashboard/src/index.css`
**Depends on:** 1.1 complete
**Enables:** Phase 2 and 3 components

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 1.2.1 | Add --space-page-x, --space-page-y tokens | pending | Variables in DevTools |
| 1.2.2 | Add --space-card, --space-section tokens | pending | Variables in DevTools |
| 1.2.3 | Add --text-heading-1/2/3, --text-body, --text-small | pending | Variables in DevTools |
| 1.2.4 | Add @media rules for sm/md/lg token scaling | pending | Values change at breakpoints |
| 1.2.5 | Add --vh with dvh support check | pending | iOS Safari height fix works |
| 1.2.6 | Add .touch-target utility (min 44x44px) | pending | Class applies correct sizing |

**Validation:** Variables visible in browser DevTools, values change at breakpoints

### 1.3 Core Hooks
**File:** `dashboard/src/hooks/useMediaQuery.ts` (NEW)
**Depends on:** None (can parallel with 1.1/1.2)
**Enables:** 2.2, 2.3, 3.3

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 1.3.1 | Create useMediaQuery hook | pending | Hook returns boolean |
| 1.3.2 | Add TypeScript types | pending | No TS errors |
| 1.3.3 | Add SSR safety (typeof window check) | pending | No hydration errors |
| 1.3.4 | Add cleanup on unmount | pending | No memory leaks |

**Validation:** `useMediaQuery('(max-width: 639px)')` returns true on mobile

### 1.4 Utility Components
**Directory:** `dashboard/src/components/ui/` (NEW)
**Depends on:** 1.1, 1.2 complete
**Enables:** All Phase 3 components

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 1.4.1 | Create ResponsiveCard.tsx | pending | Responsive padding works |
| 1.4.2 | Create ResponsiveGrid.tsx | pending | Column cascade works |
| 1.4.3 | Create ResponsiveText.tsx | pending | Text scales at breakpoints |
| 1.4.4 | Create MetricCard.tsx | pending | Variants work (default/baseline) |
| 1.4.5 | Create index.ts barrel export | pending | All components exportable |

**Validation:** Components render correctly at 375px, 768px, 1440px

---

## Phase 2: Navigation System (Days 4-6)

### Overview
Create the parallel v2 route structure and responsive navigation components.

### 2.1 Route Structure Setup
**Files:** `dashboard/src/App.tsx`, `dashboard/src/pages/v2/` (NEW)
**Depends on:** None
**Enables:** All v2 page development

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 2.1.1 | Create `pages/v2/` directory | pending | Directory exists |
| 2.1.2 | Create `layouts/` directory if needed | pending | Directory exists |
| 2.1.3 | Create placeholder DashboardV2.tsx | pending | File renders "V2 Dashboard" |
| 2.1.4 | Add /v2 route group to App.tsx | pending | Route registered |
| 2.1.5 | Test /v2 route accessible in browser | pending | Page loads at /v2 |

**Validation:** Navigate to `http://localhost:5173/v2` shows placeholder

### 2.2 Mobile Bottom Navigation
**File:** `dashboard/src/components/navigation/MobileBottomNav.tsx` (NEW)
**Depends on:** 2.1 complete
**Enables:** 2.4 (ResponsiveLayout)

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 2.2.1 | Create navigation/ directory | pending | Directory exists |
| 2.2.2 | Implement MobileBottomNav component | pending | Component renders |
| 2.2.3 | Add 4 nav items with icons | pending | Icons + labels visible |
| 2.2.4 | Style active state (blue highlight) | pending | Active route highlighted |
| 2.2.5 | Add safe-area-inset-bottom padding | pending | No iPhone home bar overlap |
| 2.2.6 | Hide on sm: breakpoint and above | pending | Hidden on tablet+ |
| 2.2.7 | Ensure touch targets >= 44px | pending | Min height applied |

**Validation:** Bottom nav visible only < 640px, all items tappable

### 2.3 Collapsible Sidebar
**File:** `dashboard/src/components/navigation/CollapsibleSidebar.tsx` (NEW)
**Depends on:** 2.1 complete (can parallel with 2.2)
**Enables:** 2.4 (ResponsiveLayout)

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 2.3.1 | Implement CollapsibleSidebar component | pending | Component renders |
| 2.3.2 | Add hamburger toggle button | pending | Button visible on mobile/tablet |
| 2.3.3 | Implement slide-in animation (300ms) | pending | Smooth transition |
| 2.3.4 | Add backdrop overlay (bg-black/50) | pending | Overlay visible when open |
| 2.3.5 | Close on nav item click | pending | Auto-close works |
| 2.3.6 | Close on backdrop click | pending | Click outside closes |
| 2.3.7 | Always visible on lg: and above | pending | No toggle on desktop |
| 2.3.8 | Add all nav items from existing sidebar | pending | Same navigation as v1 |

**Validation:** Sidebar slides in/out smoothly, always visible on desktop

### 2.4 Responsive Layout Component
**File:** `dashboard/src/layouts/ResponsiveLayout.tsx` (NEW)
**Depends on:** 2.2, 2.3 complete
**Enables:** All Phase 3 and 4 pages

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 2.4.1 | Create ResponsiveLayout.tsx | pending | Component renders |
| 2.4.2 | Integrate CollapsibleSidebar | pending | Sidebar present |
| 2.4.3 | Integrate MobileBottomNav | pending | Bottom nav present |
| 2.4.4 | Add lg:ml-64 for sidebar spacing | pending | Content not under sidebar |
| 2.4.5 | Add pb-20 sm:pb-0 for bottom nav | pending | Content not under bottom nav |
| 2.4.6 | Add responsive content padding | pending | Proper margins at all sizes |

**Validation:** Layout adapts at 375px, 768px, 1024px correctly

### 2.5 Navigation Testing
**Depends on:** 2.4 complete
**Enables:** Phase 3

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 2.5.1 | Test mobile (375px) in DevTools | pending | Bottom nav, no sidebar |
| 2.5.2 | Test tablet (768px) in DevTools | pending | Toggle sidebar, no bottom nav |
| 2.5.3 | Test desktop (1440px) in DevTools | pending | Full sidebar, no toggle |
| 2.5.4 | Verify no horizontal overflow at any size | pending | No x-scroll |

**Validation:** All breakpoints work correctly

---

## Phase 3: Dashboard Component Migration (Days 7-11)

### Overview
Create DashboardV2 with all blocks fully responsive.

### 3.1 DashboardV2 Scaffold
**File:** `dashboard/src/pages/v2/DashboardV2.tsx`
**Depends on:** Phase 2 complete
**Enables:** All 3.2-3.7 tasks

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.1.1 | Copy Dashboard.tsx to DashboardV2.tsx | pending | File exists |
| 3.1.2 | Update imports for v2 path | pending | No import errors |
| 3.1.3 | Verify data hooks work (useStatus, etc.) | pending | Data loads |
| 3.1.4 | Verify hasPermission checks preserved | pending | Permission logic intact |
| 3.1.5 | Update App.tsx to use DashboardV2 at /v2 | pending | Route renders DashboardV2 |

**Validation:** /v2 shows same data as / with identical permission behavior

### 3.2 Portfolio Returns Block
**Depends on:** 3.1 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.2.1 | Update grid: cols-1 xs:cols-2 md:cols-3 lg:cols-5 | pending | Grid adapts |
| 3.2.2 | Make time range selector stack on mobile | pending | Buttons fit |
| 3.2.3 | Apply ResponsiveText to headings | pending | Text scales |
| 3.2.4 | Use MetricCard for 5 metrics | pending | Cards styled |
| 3.2.5 | Adjust gaps: gap-2 sm:gap-3 | pending | Spacing adapts |

**Validation:** 5 metrics display correctly at all breakpoints

### 3.3 Portfolio Snapshot Block
**Depends on:** 3.1, 1.3 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.3.1 | Make balance grid: cols-1 xs:cols-2 md:cols-4 | pending | Grid adapts |
| 3.3.2 | Create PositionsDisplay.tsx component | pending | Component exists |
| 3.3.3 | Implement PositionsCardView for mobile | pending | Cards render |
| 3.3.4 | Implement PositionsTableView for tablet+ | pending | Table renders |
| 3.3.5 | Add useMediaQuery for view switching | pending | Switch at 640px |
| 3.3.6 | Style position cards with P&L colors | pending | Green/red P&L |

**Validation:** Table on tablet+, cards on mobile

### 3.4 Current Regime Block
**Depends on:** 3.1 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.4.1 | Update grid: cols-1 sm:cols-3 | pending | Stacks on mobile |
| 3.4.2 | Apply responsive text sizing | pending | Readable on mobile |

**Validation:** 3 regime indicators stack/row correctly

### 3.5 Decision Tree Block
**Depends on:** 3.1 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.5.1 | Reduce padding on mobile (p-3 sm:p-4) | pending | Less cramped |
| 3.5.2 | Responsive text in classification boxes | pending | Readable |
| 3.5.3 | Treasury Overlay box responsive | pending | No overflow |

**Validation:** Decision tree readable without horizontal scroll on mobile

### 3.6 Target Allocation Block
**Depends on:** 3.1 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.6.1 | Responsive text for labels | pending | Labels readable |
| 3.6.2 | Verify progress bars work at all widths | pending | No overflow |

**Validation:** Allocation bars display correctly

### 3.7 Admin-Only Blocks
**Depends on:** 3.1 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 3.7.1 | Engine Control: responsive buttons | pending | Buttons stack/row |
| 3.7.2 | Execution Schedule: responsive grid | pending | Grid adapts |
| 3.7.3 | Scheduler Control component works | pending | No errors |
| 3.7.4 | Schwab Token Banner responsive | pending | No overflow |
| 3.7.5 | Execute Trade Modal mobile-friendly | pending | Modal fits screen |

**Validation:** Admin blocks visible to admin only, all responsive

---

## Phase 4: Other Pages + Polish (Days 12-16)

### Overview
Create remaining v2 pages, polish, test, and verify permissions.

### 4.1 Trades Page (TradesV2)
**File:** `dashboard/src/pages/v2/TradesV2.tsx` (NEW)
**Depends on:** Phase 3 patterns

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.1.1 | Create TradesV2.tsx | pending | File exists |
| 4.1.2 | Responsive trades table/cards | pending | Cards on mobile |
| 4.1.3 | Responsive filters/search | pending | Filters usable |
| 4.1.4 | Mobile-friendly pagination | pending | Touch-friendly |
| 4.1.5 | Add to /v2/trades route | pending | Route works |

### 4.2 Performance Page (PerformanceV2)
**File:** `dashboard/src/pages/v2/PerformanceV2.tsx` (NEW)

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.2.1 | Create PerformanceV2.tsx | pending | File exists |
| 4.2.2 | Responsive chart container | pending | Chart fits |
| 4.2.3 | Responsive metrics cards | pending | Cards adapt |
| 4.2.4 | Time range selector mobile-friendly | pending | Buttons fit |
| 4.2.5 | Add to /v2/performance route | pending | Route works |

### 4.3 Settings Page (SettingsV2)
**File:** `dashboard/src/pages/v2/SettingsV2.tsx` (NEW)

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.3.1 | Create SettingsV2.tsx | pending | File exists |
| 4.3.2 | Responsive form layouts | pending | Forms usable |
| 4.3.3 | 2FA settings mobile-friendly | pending | Scannable QR |
| 4.3.4 | Passkey settings mobile-friendly | pending | Touch targets |
| 4.3.5 | Add to /v2/settings route | pending | Route works |

### 4.4 Config Page (ConfigV2)
**File:** `dashboard/src/pages/v2/ConfigV2.tsx` (NEW)

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.4.1 | Create ConfigV2.tsx | pending | File exists |
| 4.4.2 | Wrap with RequirePermission | pending | Admin only |
| 4.4.3 | Responsive config forms | pending | Forms usable |
| 4.4.4 | Add to /v2/config route | pending | Route works |

### 4.5 Decision Tree Page (DecisionTreeV2)
**File:** `dashboard/src/pages/v2/DecisionTreeV2.tsx` (NEW)

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.5.1 | Create DecisionTreeV2.tsx | pending | File exists |
| 4.5.2 | Responsive visualization | pending | No overflow |
| 4.5.3 | Add to /v2/decision-tree route | pending | Route works |

### 4.6 Polish & Refinements
**Depends on:** 4.1-4.5 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.6.1 | All buttons >= 44px touch target | pending | Measured in DevTools |
| 4.6.2 | Add hover states for desktop | pending | Visual feedback |
| 4.6.3 | Add focus states for accessibility | pending | Keyboard navigable |
| 4.6.4 | Verify smooth transitions (300ms) | pending | No jank |
| 4.6.5 | Safe-area-inset on all pages | pending | No notch overlap |

### 4.7 Testing
**Depends on:** 4.6 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.7.1 | Test on iPhone SE (375px) | pending | All pages work |
| 4.7.2 | Test on iPhone 14 Pro (393px) | pending | All pages work |
| 4.7.3 | Test on iPad (768px) | pending | All pages work |
| 4.7.4 | Test on MacBook (1440px) | pending | All pages work |
| 4.7.5 | Run Lighthouse mobile audit | pending | Score >= 90 |
| 4.7.6 | Fix any issues found | pending | No critical issues |

### 4.8 Permission Verification
**Depends on:** 4.7 complete

| Task ID | Description | Status | Acceptance Criteria |
|---------|-------------|--------|---------------------|
| 4.8.1 | Test all v2 pages as admin | pending | Full access |
| 4.8.2 | Test all v2 pages as viewer | pending | Restricted access |
| 4.8.3 | Verify restricted sections hidden | pending | Matrix matches v1 |
| 4.8.4 | Direct URL protection works | pending | Redirect to /v2 |

---

## Dependency Graph

```
Phase 1 (Foundation)
├── 1.1 Tailwind Config ────┐
├── 1.2 CSS Variables ──────┼──→ 1.4 Utility Components
├── 1.3 useMediaQuery ──────┘
│
Phase 2 (Navigation)
├── 2.1 Route Setup ────────┬──→ 2.2 MobileBottomNav ──┐
│                           └──→ 2.3 CollapsibleSidebar ┼──→ 2.4 ResponsiveLayout
│                                                       │
Phase 3 (Dashboard)                                     ↓
├── 3.1 DashboardV2 Scaffold ←──────────────────────────┘
│   ├── 3.2 Portfolio Returns
│   ├── 3.3 Portfolio Snapshot (needs 1.3)
│   ├── 3.4 Current Regime
│   ├── 3.5 Decision Tree
│   ├── 3.6 Target Allocation
│   └── 3.7 Admin Blocks
│
Phase 4 (Pages + Polish)
├── 4.1-4.5 V2 Pages (parallel) ──→ 4.6 Polish ──→ 4.7 Testing ──→ 4.8 Permissions
```

---

## Parallel Execution Opportunities

These tasks can be executed simultaneously to save time:

| Group | Tasks | Notes |
|-------|-------|-------|
| P1 | 1.1, 1.3 | Config and hook have no dependencies |
| P2 | 2.2, 2.3 | Both nav components can be built in parallel |
| P3 | 3.2, 3.3, 3.4, 3.5, 3.6, 3.7 | All blocks after scaffold |
| P4 | 4.1, 4.2, 4.3, 4.4, 4.5 | All v2 pages after patterns established |

---

## Files to Create

| Phase | File | Type |
|-------|------|------|
| 1 | src/hooks/useMediaQuery.ts | Hook |
| 1 | src/components/ui/ResponsiveCard.tsx | Component |
| 1 | src/components/ui/ResponsiveGrid.tsx | Component |
| 1 | src/components/ui/ResponsiveText.tsx | Component |
| 1 | src/components/ui/MetricCard.tsx | Component |
| 1 | src/components/ui/index.ts | Barrel |
| 2 | src/components/navigation/MobileBottomNav.tsx | Component |
| 2 | src/components/navigation/CollapsibleSidebar.tsx | Component |
| 2 | src/layouts/ResponsiveLayout.tsx | Layout |
| 2 | src/pages/v2/DashboardV2.tsx | Page |
| 3 | src/components/PositionsDisplay.tsx | Component |
| 4 | src/pages/v2/TradesV2.tsx | Page |
| 4 | src/pages/v2/PerformanceV2.tsx | Page |
| 4 | src/pages/v2/SettingsV2.tsx | Page |
| 4 | src/pages/v2/ConfigV2.tsx | Page |
| 4 | src/pages/v2/DecisionTreeV2.tsx | Page |

---

## Files to Modify

| Phase | File | Changes |
|-------|------|---------|
| 1 | tailwind.config.js | Add breakpoints, containers |
| 1 | src/index.css | Add CSS variables |
| 2 | src/App.tsx | Add /v2 routes |

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Total Tasks | 63 |
| Lighthouse Mobile Score | >= 90 |
| Bundle Size Increase | 0 KB |
| Permission Matrix Match | 100% |
| Device Compatibility | iPhone SE, iPad, MacBook |

---

**Document History:**
- v1.0.0 (2026-01-14): Initial workflow created from implementation guide
