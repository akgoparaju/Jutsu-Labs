/**
 * ResponsiveGrid Component
 * 
 * A flexible grid layout that adapts column count based on breakpoints.
 * Uses mobile-first approach with configurable columns at each breakpoint.
 * 
 * @version 1.0.0
 * @part Responsive UI Foundation - Phase 1
 */

import { ReactNode } from 'react'
import clsx from 'clsx'

export type ColumnCount = 1 | 2 | 3 | 4 | 5 | 6

export type GapSize = 'sm' | 'md' | 'lg'

export interface ColumnConfig {
  /** Base column count (mobile) - required */
  default: ColumnCount
  /** Columns at xs breakpoint (480px+) */
  xs?: ColumnCount
  /** Columns at sm breakpoint (640px+) */
  sm?: ColumnCount
  /** Columns at md breakpoint (768px+) */
  md?: ColumnCount
  /** Columns at lg breakpoint (1024px+) */
  lg?: ColumnCount
  /** Columns at xl breakpoint (1280px+) */
  xl?: ColumnCount
}

export interface ResponsiveGridProps {
  /** Grid children */
  children: ReactNode
  /** Column configuration per breakpoint */
  columns?: ColumnConfig
  /** Gap between grid items */
  gap?: GapSize
  /** Additional CSS classes */
  className?: string
}

// Static class mappings for Tailwind JIT compatibility
const columnClasses: Record<ColumnCount, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-4',
  5: 'grid-cols-5',
  6: 'grid-cols-6',
}

const smColumnClasses: Record<ColumnCount, string> = {
  1: 'sm:grid-cols-1',
  2: 'sm:grid-cols-2',
  3: 'sm:grid-cols-3',
  4: 'sm:grid-cols-4',
  5: 'sm:grid-cols-5',
  6: 'sm:grid-cols-6',
}

const xsColumnClasses: Record<ColumnCount, string> = {
  1: 'xs:grid-cols-1',
  2: 'xs:grid-cols-2',
  3: 'xs:grid-cols-3',
  4: 'xs:grid-cols-4',
  5: 'xs:grid-cols-5',
  6: 'xs:grid-cols-6',
}

const mdColumnClasses: Record<ColumnCount, string> = {
  1: 'md:grid-cols-1',
  2: 'md:grid-cols-2',
  3: 'md:grid-cols-3',
  4: 'md:grid-cols-4',
  5: 'md:grid-cols-5',
  6: 'md:grid-cols-6',
}

const lgColumnClasses: Record<ColumnCount, string> = {
  1: 'lg:grid-cols-1',
  2: 'lg:grid-cols-2',
  3: 'lg:grid-cols-3',
  4: 'lg:grid-cols-4',
  5: 'lg:grid-cols-5',
  6: 'lg:grid-cols-6',
}

const xlColumnClasses: Record<ColumnCount, string> = {
  1: 'xl:grid-cols-1',
  2: 'xl:grid-cols-2',
  3: 'xl:grid-cols-3',
  4: 'xl:grid-cols-4',
  5: 'xl:grid-cols-5',
  6: 'xl:grid-cols-6',
}

const gapClasses: Record<GapSize, string> = {
  sm: 'gap-2 sm:gap-3',
  md: 'gap-3 sm:gap-4',
  lg: 'gap-4 sm:gap-5 md:gap-6',
}

/**
 * ResponsiveGrid - Adaptive column layout
 * 
 * @example
 * <ResponsiveGrid 
 *   columns={{ default: 1, xs: 2, md: 3, lg: 5 }}
 *   gap="md"
 * >
 *   <MetricCard />
 *   <MetricCard />
 *   <MetricCard />
 * </ResponsiveGrid>
 */
export function ResponsiveGrid({
  children,
  columns = { default: 1, sm: 2, md: 3, lg: 4 },
  gap = 'md',
  className,
}: ResponsiveGridProps) {
  return (
    <div
      className={clsx(
        'grid',
        // Base columns (mobile)
        columnClasses[columns.default],
        // Responsive columns
        columns.xs && xsColumnClasses[columns.xs],
        columns.sm && smColumnClasses[columns.sm],
        columns.md && mdColumnClasses[columns.md],
        columns.lg && lgColumnClasses[columns.lg],
        columns.xl && xlColumnClasses[columns.xl],
        // Gap
        gapClasses[gap],
        // User's additional classes
        className
      )}
    >
      {children}
    </div>
  )
}

export default ResponsiveGrid
