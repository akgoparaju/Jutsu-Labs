# Responsive Dashboard UI Implementation Guide

**Version:** 1.1.0
**Date:** 2026-01-14
**Status:** Approved for Implementation

## Executive Summary

This document outlines the implementation strategy for making the Jutsu Trader dashboard fully responsive across all device types (phones, tablets, desktops) using industry-standard mobile-first design patterns with zero additional dependencies.

### Key Decisions
- **Approach:** Hybrid (Mobile-First Tailwind + Container Queries + Navigation Patterns)
- **Development Strategy:** Route-Based Toggle (parallel development with existing UI)
- **New Dependencies:** None (0 KB bundle increase)
- **Breakpoint Strategy:** Mobile-first with sm → md → lg → xl → 2xl cascade
- **Permission System:** Fully preserved (admin/viewer controls unchanged)
- **Timeline:** 4 phases, ~12-16 days estimated

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Parallel Development Strategy](#2-parallel-development-strategy)
3. [Permission System Preservation](#3-permission-system-preservation)
4. [Breakpoint Strategy](#4-breakpoint-strategy)
5. [Component Patterns](#5-component-patterns)
6. [Navigation System](#6-navigation-system)
7. [Data-Heavy Components](#7-data-heavy-components)
8. [Implementation Phases](#8-implementation-phases)
9. [Testing Strategy](#9-testing-strategy)
10. [Code Examples](#10-code-examples)

---

## 2. Parallel Development Strategy

### Overview

The responsive UI will be developed **in parallel** with the existing UI using a **Route-Based Toggle** approach. This allows:
- Zero risk to production during development
- Side-by-side comparison on the same device
- Easy rollback if issues discovered
- Comprehensive testing before switch-over

### Directory Structure

```
dashboard/src/
├── components/
│   ├── ui/                    # NEW: Shared responsive components
│   │   ├── ResponsiveCard.tsx
│   │   ├── ResponsiveGrid.tsx
│   │   ├── ResponsiveText.tsx
│   │   └── MetricCard.tsx
│   ├── navigation/            # NEW: Responsive navigation
│   │   ├── MobileBottomNav.tsx
│   │   └── CollapsibleSidebar.tsx
│   └── [existing components]  # UNCHANGED
├── pages/
│   ├── Dashboard.tsx          # EXISTING: Keep unchanged
│   ├── Trades.tsx             # EXISTING: Keep unchanged
│   ├── Performance.tsx        # EXISTING: Keep unchanged
│   └── v2/                    # NEW: Responsive versions
│       ├── DashboardV2.tsx
│       ├── TradesV2.tsx
│       └── PerformanceV2.tsx
├── layouts/
│   ├── Layout.tsx             # EXISTING: Desktop-only layout
│   └── ResponsiveLayout.tsx   # NEW: Adaptive layout
└── App.tsx                    # Updated with /v2 routes
```

### Route Configuration

```tsx
// App.tsx - Add v2 routes alongside existing routes
<Routes>
  {/* Existing routes (unchanged) */}
  <Route element={<Layout />}>
    <Route path="/" element={<Dashboard />} />
    <Route path="/trades" element={<Trades />} />
    <Route path="/performance" element={<Performance />} />
    {/* ... other existing routes */}
  </Route>
  
  {/* NEW: Responsive v2 routes */}
  <Route element={<ResponsiveLayout />}>
    <Route path="/v2" element={<DashboardV2 />} />
    <Route path="/v2/trades" element={<TradesV2 />} />
    <Route path="/v2/performance" element={<PerformanceV2 />} />
    {/* ... other v2 routes */}
  </Route>
</Routes>
```

### Switch-Over Process

| Phase | Action | Risk |
|-------|--------|------|
| 1. Development | Build v2 components at `/v2/*` routes | None |
| 2. Testing | Test v2 on all target devices | None |
| 3. Beta | Share `/v2` URLs with testers | Low |
| 4. Validation | Fix any issues found | Low |
| 5. Switch-over | Swap route paths (v2 becomes default) | Medium |
| 6. Cleanup | Remove old components after grace period | Low |

### Switch-Over Commands

```bash
# When ready to promote v2:
# 1. Rename existing pages to "legacy"
git mv src/pages/Dashboard.tsx src/pages/legacy/Dashboard.tsx

# 2. Rename v2 pages to main
git mv src/pages/v2/DashboardV2.tsx src/pages/Dashboard.tsx

# 3. Update imports in App.tsx
# 4. Test thoroughly
# 5. Deploy
```

---

## 3. Permission System Preservation

### Guarantee

**All admin/viewer permission controls will be 100% preserved.** The responsive UI changes are purely presentational and do not modify access control logic.

### How Permissions Work (Unchanged)

```typescript
// AuthContext.tsx - UNCHANGED
const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  admin: new Set(['*']),  // All permissions
  viewer: new Set([
    'dashboard:read', 'performance:read', 'trades:read',
    'config:read', 'indicators:read', 'regime:read',
    'status:read', 'self:password', 'self:2fa', 'self:passkey',
  ]),
}

// hasPermission() function - UNCHANGED
const hasPermission = (permission: string): boolean => {
  if (!user) return false
  const userRole = user.role || 'viewer'
  const permissions = ROLE_PERMISSIONS[userRole] || new Set()
  return permissions.has('*') || permissions.has(permission)
}
```

### Permission Matrix (Preserved in V2)

| Dashboard Section | Permission | Admin | Viewer | V2 Behavior |
|-------------------|------------|-------|--------|-------------|
| Execute Trade button | `trades:execute` | ✅ | ❌ | Same |
| Schwab Token Banner | `config:write` | ✅ | ❌ | Same |
| Engine Control block | `engine:control` | ✅ | ❌ | Same |
| Execution Schedule | `scheduler:control` | ✅ | ❌ | Same |
| Scheduler Control | `scheduler:control` | ✅ | ❌ | Same |
| Portfolio Returns | (public) | ✅ | ✅ | Same |
| Portfolio Snapshot | (public) | ✅ | ✅ | Same |
| Current Regime | (public) | ✅ | ✅ | Same |
| Decision Tree | (public) | ✅ | ✅ | Same |
| Target Allocation | (public) | ✅ | ✅ | Same |

### V2 Component Permission Usage

```tsx
// DashboardV2.tsx - Same permission checks as v1
import { useAuth } from '../../contexts/AuthContext'

function DashboardV2() {
  const { hasPermission } = useAuth()
  
  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Permission check IDENTICAL to v1 */}
      {hasPermission('engine:control') && (
        <ResponsiveCard>
          <h3 className="text-base sm:text-lg font-semibold">Engine Control</h3>
          {/* ... responsive layout inside ... */}
        </ResponsiveCard>
      )}
      
      {/* Public sections - same as v1 */}
      <PortfolioReturnsBlock />
      <PortfolioSnapshotBlock />
      
      {/* Permission-gated sections - same checks as v1 */}
      {hasPermission('scheduler:control') && <ExecutionScheduleBlock />}
      {hasPermission('scheduler:control') && <SchedulerControl />}
    </div>
  )
}
```

### Route Protection (Unchanged)

```tsx
// App.tsx - RequirePermission works identically for v2 routes
<Route path="/v2/config" element={
  <RequirePermission permission="config:write" redirectTo="/v2">
    <ConfigV2 />
  </RequirePermission>
} />
```

### Testing Checklist for Permissions

- [ ] Login as admin → verify all v2 sections visible
- [ ] Login as viewer → verify restricted sections hidden in v2
- [ ] Direct URL access to `/v2/config` as viewer → should redirect
- [ ] Execute Trade button only visible to admin in v2
- [ ] Engine Control only visible to admin in v2
- [ ] Scheduler controls only visible to admin in v2

---

## 1. Architecture Overview

### Current Stack
```
React 18 + Vite + TypeScript
Tailwind CSS 3.4.1 (utility-first)
TanStack Query (state management)
lightweight-charts (charting)
lucide-react (icons)
```

### Responsive Principles

1. **Mobile-First Design**
   - Default styles target mobile (320px+)
   - Progressive enhancement for larger screens
   - No `max-width` media queries

2. **Container Queries**
   - Component-level responsiveness
   - Cards adapt to their container, not viewport
   - Better for reusable components

3. **Touch-Optimized**
   - Minimum 44x44px touch targets
   - Adequate spacing between interactive elements
   - Swipe-friendly interactions where appropriate

### Device Targets

| Device | Width Range | Tailwind Prefix |
|--------|-------------|-----------------|
| Phone (small) | 320px - 479px | default (no prefix) |
| Phone (large) | 480px - 639px | default |
| Tablet (portrait) | 640px - 767px | `sm:` |
| Tablet (landscape) | 768px - 1023px | `md:` |
| Desktop | 1024px - 1279px | `lg:` |
| Desktop (large) | 1280px - 1535px | `xl:` |
| Desktop (wide) | 1536px+ | `2xl:` |

---

## 2. Breakpoint Strategy

### Tailwind Configuration

```javascript
// tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      screens: {
        // Default Tailwind breakpoints (mobile-first)
        'sm': '640px',   // Large phones / small tablets
        'md': '768px',   // Tablets
        'lg': '1024px',  // Desktops
        'xl': '1280px',  // Large desktops
        '2xl': '1536px', // Wide screens
        
        // Custom breakpoints for specific use cases
        'xs': '480px',   // Large phones
        '3xl': '1920px', // Ultra-wide
      },
      // Container query breakpoints (via plugin)
      containers: {
        'xs': '320px',
        'sm': '384px',
        'md': '448px',
        'lg': '512px',
        'xl': '576px',
        '2xl': '672px',
      },
      colors: {
        bull: {
          DEFAULT: '#22c55e',
          light: '#86efac',
          dark: '#16a34a',
        },
        bear: {
          DEFAULT: '#ef4444',
          light: '#fca5a5',
          dark: '#dc2626',
        },
      },
    },
  },
  plugins: [
    // Container queries are built into Tailwind 3.4+
    // No additional plugin needed
  ],
}
```

### CSS Variables for Responsive Spacing

```css
/* index.css additions */
:root {
  /* Responsive spacing tokens */
  --space-page-x: 1rem;
  --space-page-y: 1rem;
  --space-card: 1rem;
  --space-section: 1.5rem;
  
  /* Responsive text sizes */
  --text-heading-1: 1.25rem;
  --text-heading-2: 1.125rem;
  --text-heading-3: 1rem;
  --text-body: 0.875rem;
  --text-small: 0.75rem;
}

@media (min-width: 640px) {
  :root {
    --space-page-x: 1.5rem;
    --space-card: 1.25rem;
    --text-heading-1: 1.5rem;
    --text-heading-2: 1.25rem;
  }
}

@media (min-width: 768px) {
  :root {
    --space-page-x: 2rem;
    --space-card: 1.5rem;
    --space-section: 2rem;
    --text-heading-1: 1.75rem;
    --text-heading-2: 1.5rem;
    --text-body: 1rem;
  }
}

@media (min-width: 1024px) {
  :root {
    --space-page-x: 2.5rem;
    --text-heading-1: 2rem;
  }
}

/* Mobile viewport height fix (addresses iOS Safari issues) */
:root {
  --vh: 1vh;
}

@supports (height: 100dvh) {
  :root {
    --vh: 1dvh;
  }
}

/* Touch target minimum size */
.touch-target {
  min-height: 44px;
  min-width: 44px;
}
```

---

## 3. Component Patterns

### 3.1 ResponsiveCard Component

```tsx
// src/components/ui/ResponsiveCard.tsx
import { ReactNode } from 'react'
import clsx from 'clsx'

interface ResponsiveCardProps {
  children: ReactNode
  className?: string
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

export function ResponsiveCard({ 
  children, 
  className,
  padding = 'md' 
}: ResponsiveCardProps) {
  return (
    <div 
      className={clsx(
        'bg-slate-800 rounded-lg border border-slate-700',
        // Responsive padding
        padding === 'sm' && 'p-3 sm:p-4',
        padding === 'md' && 'p-4 sm:p-5 md:p-6',
        padding === 'lg' && 'p-5 sm:p-6 md:p-8',
        padding === 'none' && '',
        className
      )}
    >
      {children}
    </div>
  )
}
```

### 3.2 ResponsiveGrid Component

```tsx
// src/components/ui/ResponsiveGrid.tsx
import { ReactNode } from 'react'
import clsx from 'clsx'

interface ResponsiveGridProps {
  children: ReactNode
  columns?: {
    default: 1 | 2 | 3 | 4 | 5 | 6
    sm?: 1 | 2 | 3 | 4 | 5 | 6
    md?: 1 | 2 | 3 | 4 | 5 | 6
    lg?: 1 | 2 | 3 | 4 | 5 | 6
    xl?: 1 | 2 | 3 | 4 | 5 | 6
  }
  gap?: 'sm' | 'md' | 'lg'
  className?: string
}

const columnClasses = {
  1: 'grid-cols-1',
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-4',
  5: 'grid-cols-5',
  6: 'grid-cols-6',
}

export function ResponsiveGrid({ 
  children, 
  columns = { default: 1, sm: 2, md: 3, lg: 4 },
  gap = 'md',
  className 
}: ResponsiveGridProps) {
  return (
    <div 
      className={clsx(
        'grid',
        columnClasses[columns.default],
        columns.sm && `sm:${columnClasses[columns.sm]}`,
        columns.md && `md:${columnClasses[columns.md]}`,
        columns.lg && `lg:${columnClasses[columns.lg]}`,
        columns.xl && `xl:${columnClasses[columns.xl]}`,
        gap === 'sm' && 'gap-2 sm:gap-3',
        gap === 'md' && 'gap-3 sm:gap-4',
        gap === 'lg' && 'gap-4 sm:gap-5 md:gap-6',
        className
      )}
    >
      {children}
    </div>
  )
}
```

### 3.3 Responsive Text Utilities

```tsx
// src/components/ui/ResponsiveText.tsx
import { ReactNode } from 'react'
import clsx from 'clsx'

type TextVariant = 'h1' | 'h2' | 'h3' | 'body' | 'small' | 'metric'

interface ResponsiveTextProps {
  variant: TextVariant
  children: ReactNode
  className?: string
  as?: keyof JSX.IntrinsicElements
}

const variantClasses: Record<TextVariant, string> = {
  h1: 'text-lg sm:text-xl md:text-2xl font-bold',
  h2: 'text-base sm:text-lg md:text-xl font-semibold',
  h3: 'text-sm sm:text-base md:text-lg font-semibold',
  body: 'text-sm sm:text-base',
  small: 'text-xs sm:text-sm',
  metric: 'text-xl sm:text-2xl md:text-3xl font-bold',
}

export function ResponsiveText({ 
  variant, 
  children, 
  className,
  as: Component = 'span' 
}: ResponsiveTextProps) {
  return (
    <Component className={clsx(variantClasses[variant], className)}>
      {children}
    </Component>
  )
}
```

---

## 4. Navigation System

### 4.1 Navigation Architecture

```
Phone (< 640px):
├── Header (logo + hamburger for settings)
├── Main Content (scrollable)
└── Bottom Tab Bar (Dashboard, Trades, Performance, More)

Tablet (640px - 1023px):
├── Collapsible Sidebar (hamburger toggle)
├── Main Content (wider)
└── No bottom bar

Desktop (1024px+):
├── Full Sidebar (always visible)
└── Main Content (full width)
```

### 4.2 MobileBottomNav Component

```tsx
// src/components/navigation/MobileBottomNav.tsx
import { Link, useLocation } from 'react-router-dom'
import { 
  LayoutDashboard, 
  TrendingUp, 
  LineChart, 
  MoreHorizontal 
} from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/trades', icon: TrendingUp, label: 'Trades' },
  { path: '/performance', icon: LineChart, label: 'Performance' },
  { path: '/more', icon: MoreHorizontal, label: 'More' },
]

export function MobileBottomNav() {
  const location = useLocation()
  
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-slate-900 border-t border-slate-700 sm:hidden">
      <div className="flex justify-around items-center h-16 px-2 safe-area-inset-bottom">
        {navItems.map(({ path, icon: Icon, label }) => {
          const isActive = location.pathname === path
          return (
            <Link
              key={path}
              to={path}
              className={clsx(
                'flex flex-col items-center justify-center',
                'min-w-[64px] min-h-[44px] px-3 py-2 rounded-lg',
                'transition-colors duration-200',
                isActive 
                  ? 'text-blue-400 bg-blue-400/10' 
                  : 'text-gray-400 hover:text-gray-200'
              )}
            >
              <Icon className="w-5 h-5 mb-1" />
              <span className="text-xs font-medium">{label}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
```

### 4.3 CollapsibleSidebar Component

```tsx
// src/components/navigation/CollapsibleSidebar.tsx
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Menu, X, LayoutDashboard, TrendingUp, LineChart, Settings, Users, TreeDeciduous } from 'lucide-react'
import clsx from 'clsx'

interface SidebarProps {
  className?: string
}

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/trades', icon: TrendingUp, label: 'Trades' },
  { path: '/performance', icon: LineChart, label: 'Performance' },
  { path: '/decision-tree', icon: TreeDeciduous, label: 'Decision Tree' },
  { path: '/config', icon: Settings, label: 'Config' },
  { path: '/settings', icon: Users, label: 'Settings' },
]

export function CollapsibleSidebar({ className }: SidebarProps) {
  const [isOpen, setIsOpen] = useState(false)
  const location = useLocation()
  
  return (
    <>
      {/* Mobile/Tablet Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={clsx(
          'fixed top-4 left-4 z-50 p-2 rounded-lg',
          'bg-slate-800 border border-slate-700',
          'lg:hidden' // Hidden on desktop
        )}
        aria-label={isOpen ? 'Close menu' : 'Open menu'}
      >
        {isOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
      </button>
      
      {/* Overlay (mobile/tablet) */}
      {isOpen && (
        <div 
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setIsOpen(false)}
        />
      )}
      
      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed top-0 left-0 z-40 h-full',
          'bg-slate-900 border-r border-slate-700',
          'w-64 transform transition-transform duration-300 ease-in-out',
          // Mobile/Tablet: slide in/out
          isOpen ? 'translate-x-0' : '-translate-x-full',
          // Desktop: always visible
          'lg:translate-x-0 lg:static lg:z-auto',
          className
        )}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center h-16 px-4 border-b border-slate-700">
            <img src="/logo.svg" alt="Jutsu" className="h-8 w-auto" />
            <span className="ml-3 text-lg font-bold">Jutsu Trader</span>
          </div>
          
          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto p-4">
            <ul className="space-y-2">
              {navItems.map(({ path, icon: Icon, label }) => {
                const isActive = location.pathname === path
                return (
                  <li key={path}>
                    <Link
                      to={path}
                      onClick={() => setIsOpen(false)}
                      className={clsx(
                        'flex items-center px-4 py-3 rounded-lg',
                        'transition-colors duration-200',
                        'min-h-[44px]', // Touch target
                        isActive
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-400 hover:bg-slate-800 hover:text-white'
                      )}
                    >
                      <Icon className="w-5 h-5 mr-3" />
                      <span>{label}</span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </nav>
        </div>
      </aside>
    </>
  )
}
```

### 4.4 Updated Layout Component

```tsx
// src/components/Layout.tsx
import { Outlet } from 'react-router-dom'
import { CollapsibleSidebar } from './navigation/CollapsibleSidebar'
import { MobileBottomNav } from './navigation/MobileBottomNav'

export function Layout() {
  return (
    <div className="min-h-screen bg-slate-900">
      {/* Sidebar (desktop: always visible, tablet: toggle, mobile: hidden) */}
      <CollapsibleSidebar />
      
      {/* Main Content */}
      <main className={clsx(
        'min-h-screen',
        // Padding for sidebar on desktop
        'lg:ml-64',
        // Padding for bottom nav on mobile
        'pb-20 sm:pb-0',
        // Content padding
        'px-4 py-4 sm:px-6 sm:py-6 md:px-8 md:py-8'
      )}>
        <Outlet />
      </main>
      
      {/* Bottom Navigation (mobile only) */}
      <MobileBottomNav />
    </div>
  )
}
```

---

## 5. Data-Heavy Components

### 5.1 Portfolio Returns Grid (5 columns → responsive)

**Before:**
```tsx
<div className="grid grid-cols-2 md:grid-cols-5 gap-3">
```

**After:**
```tsx
<div className="grid grid-cols-1 xs:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2 sm:gap-3">
```

### 5.2 Positions Table → Card View on Mobile

```tsx
// src/components/PositionsDisplay.tsx
import { useMediaQuery } from '../hooks/useMediaQuery'

interface Position {
  symbol: string
  quantity: number
  avg_cost?: number
  market_value?: number
  unrealized_pnl?: number
  weight_pct?: number
}

interface PositionsDisplayProps {
  positions: Position[]
}

export function PositionsDisplay({ positions }: PositionsDisplayProps) {
  const isMobile = useMediaQuery('(max-width: 639px)')
  
  if (isMobile) {
    return <PositionsCardView positions={positions} />
  }
  
  return <PositionsTableView positions={positions} />
}

function PositionsCardView({ positions }: PositionsDisplayProps) {
  return (
    <div className="space-y-3">
      {positions.map((pos) => {
        const pnl = pos.unrealized_pnl ?? 0
        const pnlPositive = pnl >= 0
        
        return (
          <div 
            key={pos.symbol}
            className="bg-slate-700/50 rounded-lg p-4"
          >
            <div className="flex justify-between items-start mb-2">
              <span className="font-bold text-lg">{pos.symbol}</span>
              <span className={clsx(
                'text-lg font-bold',
                pnlPositive ? 'text-green-400' : 'text-red-400'
              )}>
                {pnlPositive ? '+' : ''}${pnl.toFixed(2)}
              </span>
            </div>
            
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span className="text-gray-400">Qty:</span>
                <span className="ml-2">{pos.quantity}</span>
              </div>
              <div>
                <span className="text-gray-400">Weight:</span>
                <span className="ml-2">{pos.weight_pct?.toFixed(1)}%</span>
              </div>
              <div>
                <span className="text-gray-400">Avg Cost:</span>
                <span className="ml-2">${pos.avg_cost?.toFixed(2)}</span>
              </div>
              <div>
                <span className="text-gray-400">Value:</span>
                <span className="ml-2">${pos.market_value?.toLocaleString()}</span>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PositionsTableView({ positions }: PositionsDisplayProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead className="text-sm text-gray-400 border-b border-slate-700">
          <tr>
            <th className="pb-3">Symbol</th>
            <th className="pb-3">Quantity</th>
            <th className="pb-3 hidden md:table-cell">Avg Cost</th>
            <th className="pb-3">Market Value</th>
            <th className="pb-3">P&L</th>
            <th className="pb-3 hidden sm:table-cell">Weight</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnl = pos.unrealized_pnl ?? 0
            const pnlPositive = pnl >= 0
            
            return (
              <tr key={pos.symbol} className="border-b border-slate-700/50">
                <td className="py-3 font-medium">{pos.symbol}</td>
                <td className="py-3">{pos.quantity}</td>
                <td className="py-3 hidden md:table-cell">
                  ${pos.avg_cost?.toFixed(2) ?? 'N/A'}
                </td>
                <td className="py-3">
                  ${pos.market_value?.toLocaleString() ?? 'N/A'}
                </td>
                <td className={clsx(
                  'py-3',
                  pnlPositive ? 'text-green-400' : 'text-red-400'
                )}>
                  {pnlPositive ? '+' : ''}${pnl.toFixed(2)}
                </td>
                <td className="py-3 hidden sm:table-cell">
                  {pos.weight_pct?.toFixed(1)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
```

### 5.3 useMediaQuery Hook

```tsx
// src/hooks/useMediaQuery.ts
import { useState, useEffect } from 'react'

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches
    }
    return false
  })
  
  useEffect(() => {
    const mediaQuery = window.matchMedia(query)
    
    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches)
    }
    
    // Modern browsers
    mediaQuery.addEventListener('change', handler)
    
    // Set initial value
    setMatches(mediaQuery.matches)
    
    return () => {
      mediaQuery.removeEventListener('change', handler)
    }
  }, [query])
  
  return matches
}
```

---

## 6. Implementation Phases

### Phase 1: Foundation (Days 1-3)

**Tasks:**
- [ ] Update `tailwind.config.js` with extended breakpoints
- [ ] Add responsive CSS variables to `index.css`
- [ ] Create `useMediaQuery` hook
- [ ] Create base responsive utility components:
  - [ ] `ResponsiveCard`
  - [ ] `ResponsiveGrid`
  - [ ] `ResponsiveText`

**Files Modified:**
- `tailwind.config.js`
- `src/index.css`
- `src/hooks/useMediaQuery.ts` (new)
- `src/components/ui/ResponsiveCard.tsx` (new)
- `src/components/ui/ResponsiveGrid.tsx` (new)
- `src/components/ui/ResponsiveText.tsx` (new)

### Phase 2: Navigation System (Days 4-6)

**Tasks:**
- [ ] Create `MobileBottomNav` component
- [ ] Create `CollapsibleSidebar` component
- [ ] Update `Layout.tsx` for responsive navigation
- [ ] Add CSS transitions for smooth animations
- [ ] Test navigation across breakpoints

**Files Modified:**
- `src/components/navigation/MobileBottomNav.tsx` (new)
- `src/components/navigation/CollapsibleSidebar.tsx` (new)
- `src/components/Layout.tsx`

### Phase 3: Dashboard Component Migration (Days 7-11)

**Tasks:**
- [ ] Migrate Portfolio Returns block
- [ ] Create `PositionsDisplay` with card/table modes
- [ ] Migrate Portfolio Snapshot block
- [ ] Migrate Current Regime block
- [ ] Migrate Decision Tree blocks
- [ ] Migrate Target Allocation block
- [ ] Migrate Engine Control block
- [ ] Migrate Execution Schedule block

**Files Modified:**
- `src/pages/Dashboard.tsx`
- `src/components/PositionsDisplay.tsx` (new)

### Phase 4: Other Pages + Polish (Days 12-16)

**Tasks:**
- [ ] Migrate Trades page
- [ ] Migrate Performance page
- [ ] Migrate Settings page
- [ ] Migrate Config page
- [ ] Add touch-friendly improvements
- [ ] Test on real devices
- [ ] Performance audit (Lighthouse)
- [ ] Bug fixes and refinements

**Files Modified:**
- `src/pages/Trades.tsx`
- `src/pages/Performance.tsx`
- `src/pages/Settings.tsx`
- `src/pages/Config.tsx`

---

## 7. Testing Strategy

### Device Testing Matrix

| Device | Screen Size | Priority | Test Method |
|--------|-------------|----------|-------------|
| iPhone SE | 375x667 | High | Real device / Simulator |
| iPhone 14 Pro | 393x852 | High | Real device / Simulator |
| iPad | 768x1024 | High | Real device / Simulator |
| iPad Pro | 1024x1366 | Medium | Simulator |
| MacBook | 1440x900 | High | Chrome DevTools |
| 4K Display | 3840x2160 | Low | Chrome DevTools |

### Testing Checklist

#### Mobile (< 640px)
- [ ] Bottom navigation visible and functional
- [ ] All touch targets >= 44px
- [ ] Text readable without zooming
- [ ] Tables display as cards
- [ ] Charts scroll horizontally if needed
- [ ] No horizontal overflow
- [ ] Safe area insets respected (iPhone notch)

#### Tablet (640px - 1023px)
- [ ] Sidebar toggle works
- [ ] 2-3 column layouts display correctly
- [ ] Tables show priority columns only
- [ ] Adequate spacing between elements

#### Desktop (1024px+)
- [ ] Full sidebar always visible
- [ ] All columns visible in grids/tables
- [ ] Optimal use of screen real estate
- [ ] No wasted space

### Performance Targets

| Metric | Target | Tool |
|--------|--------|------|
| Lighthouse Mobile Score | >= 90 | Chrome DevTools |
| First Contentful Paint | < 1.5s | Lighthouse |
| Time to Interactive | < 3.5s | Lighthouse |
| Cumulative Layout Shift | < 0.1 | Lighthouse |
| Bundle Size Increase | 0 KB | Vite build |

---

## 8. Code Examples

### Example: Fully Responsive Dashboard Block

```tsx
// Example: Portfolio Returns block with full responsiveness
<ResponsiveCard>
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-2">
    <ResponsiveText variant="h2" as="h3">
      Portfolio Returns
    </ResponsiveText>
    
    {/* Time Range Selector */}
    <div className="flex bg-slate-700/50 rounded-lg p-1">
      {(['90d', 'ytd', '1y', 'all'] as const).map((range) => (
        <button
          key={range}
          onClick={() => setTimeRange(range)}
          className={clsx(
            'px-2 sm:px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md',
            'transition-all min-h-[36px] sm:min-h-[auto]',
            timeRange === range
              ? 'bg-blue-600 text-white'
              : 'text-gray-400 hover:text-white hover:bg-slate-600/50'
          )}
        >
          {range.toUpperCase()}
        </button>
      ))}
    </div>
  </div>
  
  <ResponsiveGrid 
    columns={{ default: 1, xs: 2, md: 3, lg: 5 }}
    gap="md"
  >
    <MetricCard 
      label="Portfolio" 
      value={periodMetrics.periodReturn}
      format="percent"
    />
    <MetricCard 
      label="CAGR" 
      value={periodMetrics.annualizedReturn}
      format="percent"
    />
    <MetricCard 
      label="QQQ Baseline" 
      value={periodMetrics.periodBaselineReturn}
      format="percent"
      variant="baseline"
    />
    <MetricCard 
      label="Baseline CAGR" 
      value={periodMetrics.baselineAnnualizedReturn}
      format="percent"
      variant="baseline"
    />
    <MetricCard 
      label="Alpha" 
      value={periodMetrics.periodAlpha}
      format="percent"
      className="xs:col-span-2 md:col-span-1"
    />
  </ResponsiveGrid>
</ResponsiveCard>
```

### Example: MetricCard Component

```tsx
// src/components/ui/MetricCard.tsx
import clsx from 'clsx'

interface MetricCardProps {
  label: string
  value: number
  format: 'percent' | 'currency' | 'number'
  variant?: 'default' | 'baseline'
  className?: string
}

export function MetricCard({ 
  label, 
  value, 
  format, 
  variant = 'default',
  className 
}: MetricCardProps) {
  const isPositive = value >= 0
  
  const formatValue = () => {
    switch (format) {
      case 'percent':
        return `${isPositive ? '+' : ''}${value.toFixed(2)}%`
      case 'currency':
        return `$${value.toLocaleString()}`
      default:
        return value.toLocaleString()
    }
  }
  
  return (
    <div className={clsx(
      'bg-slate-700/50 rounded-lg p-3 sm:p-4',
      variant === 'baseline' && 'border border-amber-600/30',
      className
    )}>
      <div className={clsx(
        'text-xs sm:text-sm mb-1',
        variant === 'baseline' ? 'text-amber-400' : 'text-gray-400'
      )}>
        {label}
      </div>
      <div className={clsx(
        'text-lg sm:text-xl md:text-2xl font-bold',
        variant === 'baseline'
          ? (isPositive ? 'text-amber-400' : 'text-amber-600')
          : (isPositive ? 'text-green-400' : 'text-red-400')
      )}>
        {formatValue()}
      </div>
    </div>
  )
}
```

---

## Appendix A: Browser Support

| Browser | Version | Support Level |
|---------|---------|---------------|
| Chrome | 105+ | Full |
| Safari | 16+ | Full |
| Firefox | 110+ | Full |
| Edge | 105+ | Full |
| iOS Safari | 16+ | Full |
| Chrome Android | 105+ | Full |

Container Queries: 92%+ global support (as of Jan 2026)

---

## Appendix B: Related Documentation

- [Tailwind CSS Responsive Design](https://tailwindcss.com/docs/responsive-design)
- [Tailwind Container Queries](https://tailwindcss.com/docs/container)
- [Apple Human Interface Guidelines - Touch Targets](https://developer.apple.com/design/human-interface-guidelines/touch-target)
- [Material Design - Responsive Layout](https://material.io/design/layout/responsive-layout-grid.html)

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| Mobile-first | Design approach starting with mobile, adding complexity for larger screens |
| Container Query | CSS feature allowing styles based on container size, not viewport |
| Breakpoint | Screen width at which layout changes |
| Touch Target | Minimum tappable area (44x44px recommended) |
| dvh | Dynamic viewport height (addresses mobile browser chrome) |
| Safe Area Inset | Padding for device notches/home indicators |

---

**Document History:**
- v1.0.0 (2026-01-14): Initial document created after brainstorm session

**Authors:**
- Claude Code (AI Assistant)
- Reviewed by: [Pending User Review]
