/**
 * ResponsiveText Component
 * 
 * Typography component with responsive text sizing.
 * Uses mobile-first approach with semantic variants.
 * 
 * @version 1.0.0
 * @part Responsive UI Foundation - Phase 1
 */

import { ReactNode, ElementType } from 'react'
import clsx from 'clsx'

export type TextVariant = 'h1' | 'h2' | 'h3' | 'body' | 'small' | 'metric' | 'label'

export interface ResponsiveTextProps {
  /** Text variant determining size and styling */
  variant: TextVariant
  /** Text content */
  children: ReactNode
  /** Additional CSS classes */
  className?: string
  /** HTML element to render (defaults based on variant) */
  as?: ElementType
  /** Text color class override */
  color?: string
}

// Mobile-first responsive text classes
const variantClasses: Record<TextVariant, string> = {
  h1: 'text-lg sm:text-xl md:text-2xl font-bold',
  h2: 'text-base sm:text-lg md:text-xl font-semibold',
  h3: 'text-sm sm:text-base md:text-lg font-semibold',
  body: 'text-sm sm:text-base',
  small: 'text-xs sm:text-sm',
  metric: 'text-xl sm:text-2xl md:text-3xl font-bold tabular-nums',
  label: 'text-xs sm:text-sm text-gray-400 font-medium uppercase tracking-wide',
}

// Default HTML elements for semantic markup
const defaultElements: Record<TextVariant, ElementType> = {
  h1: 'h1',
  h2: 'h2',
  h3: 'h3',
  body: 'p',
  small: 'span',
  metric: 'span',
  label: 'span',
}

/**
 * ResponsiveText - Typography with responsive sizing
 * 
 * @example
 * <ResponsiveText variant="h1">Dashboard</ResponsiveText>
 * <ResponsiveText variant="metric" className="text-green-400">+24.5%</ResponsiveText>
 * <ResponsiveText variant="label">Portfolio Value</ResponsiveText>
 */
export function ResponsiveText({
  variant,
  children,
  className,
  as,
  color,
}: ResponsiveTextProps) {
  const Component = as || defaultElements[variant]

  return (
    <Component
      className={clsx(
        variantClasses[variant],
        color,
        className
      )}
    >
      {children}
    </Component>
  )
}

export default ResponsiveText
