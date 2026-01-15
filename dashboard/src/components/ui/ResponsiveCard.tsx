/**
 * ResponsiveCard Component
 * 
 * A card container with responsive padding that adapts to screen size.
 * Uses mobile-first approach with consistent styling across breakpoints.
 * 
 * @version 1.0.0
 * @part Responsive UI Foundation - Phase 1
 */

import { ReactNode } from 'react'
import clsx from 'clsx'

export type CardPadding = 'none' | 'sm' | 'md' | 'lg'

export interface ResponsiveCardProps {
  /** Card content */
  children: ReactNode
  /** Additional CSS classes */
  className?: string
  /** Padding size - responsive by default */
  padding?: CardPadding
  /** Whether to show border */
  bordered?: boolean
  /** Whether the card should be interactive (hover effects) */
  interactive?: boolean
}

const paddingClasses: Record<CardPadding, string> = {
  none: '',
  sm: 'p-3 sm:p-4',
  md: 'p-4 sm:p-5 md:p-6',
  lg: 'p-5 sm:p-6 md:p-8',
}

/**
 * ResponsiveCard - Container with adaptive padding
 * 
 * @example
 * <ResponsiveCard padding="md">
 *   <h3>Title</h3>
 *   <p>Content here</p>
 * </ResponsiveCard>
 */
export function ResponsiveCard({
  children,
  className,
  padding = 'md',
  bordered = true,
  interactive = false,
}: ResponsiveCardProps) {
  return (
    <div
      className={clsx(
        // Base styles
        'bg-slate-800 rounded-lg',
        // Border
        bordered && 'border border-slate-700',
        // Responsive padding
        paddingClasses[padding],
        // Interactive states (hover/focus for desktop)
        interactive && [
          'transition-all duration-200',
          'hover:border-slate-600 hover:bg-slate-750',
          'focus-within:ring-2 focus-within:ring-blue-500/40',
        ],
        // User's additional classes
        className
      )}
    >
      {children}
    </div>
  )
}

export default ResponsiveCard
