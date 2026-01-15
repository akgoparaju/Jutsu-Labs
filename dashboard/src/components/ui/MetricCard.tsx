/**
 * MetricCard Component
 * 
 * A card for displaying financial metrics with proper formatting and styling.
 * Supports currency, percentage, and number formats with positive/negative coloring.
 * 
 * @version 1.0.0
 * @part Responsive UI Foundation - Phase 1
 */

import clsx from 'clsx'

export type MetricFormat = 'percent' | 'currency' | 'number'
export type MetricVariant = 'default' | 'baseline' | 'neutral'

export interface MetricCardProps {
  /** Metric label */
  label: string
  /** Metric value (null/undefined shows loading or N/A state) */
  value: number | null | undefined
  /** How to format the value */
  format: MetricFormat
  /** Visual variant */
  variant?: MetricVariant
  /** Additional CSS classes */
  className?: string
  /** Show loading skeleton instead of value */
  loading?: boolean
  /** Number of decimal places (default: 2) */
  decimals?: number
  /** Show positive sign for positive values */
  showSign?: boolean
}

/**
 * Format a number based on the specified format
 */
function formatValue(
  value: number,
  format: MetricFormat,
  decimals: number,
  showSign: boolean
): string {
  const isPositive = value >= 0
  const sign = showSign && isPositive ? '+' : ''
  
  switch (format) {
    case 'percent':
      return `${sign}${value.toFixed(decimals)}%`
    case 'currency':
      return `${sign}$${Math.abs(value).toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}`
    case 'number':
    default:
      return `${sign}${value.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}`
  }
}

/**
 * MetricCard - Financial metric display
 * 
 * @example
 * <MetricCard 
 *   label="Portfolio Return" 
 *   value={12.5}
 *   format="percent"
 * />
 * 
 * <MetricCard 
 *   label="QQQ Baseline" 
 *   value={8.2}
 *   format="percent"
 *   variant="baseline"
 * />
 */
export function MetricCard({
  label,
  value,
  format,
  variant = 'default',
  className,
  loading = false,
  decimals = 2,
  showSign = true,
}: MetricCardProps) {
  const isPositive = value !== null && value !== undefined && value >= 0
  
  // Determine value color based on variant and sign
  const getValueColor = (): string => {
    if (loading || value === null || value === undefined) {
      return 'text-gray-500'
    }
    
    switch (variant) {
      case 'baseline':
        return isPositive ? 'text-amber-400' : 'text-amber-600'
      case 'neutral':
        return 'text-gray-200'
      case 'default':
      default:
        return isPositive ? 'text-green-400' : 'text-red-400'
    }
  }
  
  // Determine label color based on variant
  const getLabelColor = (): string => {
    switch (variant) {
      case 'baseline':
        return 'text-amber-400/80'
      default:
        return 'text-gray-400'
    }
  }
  
  // Determine border for baseline variant
  const getBorderClass = (): string => {
    switch (variant) {
      case 'baseline':
        return 'border border-amber-600/30'
      default:
        return ''
    }
  }

  return (
    <div
      className={clsx(
        // Base styles - responsive padding
        'bg-slate-700/50 rounded-lg p-3 sm:p-4',
        // Variant-specific border
        getBorderClass(),
        // User's additional classes
        className
      )}
    >
      {/* Label */}
      <div
        className={clsx(
          'text-xs sm:text-sm mb-1',
          getLabelColor()
        )}
      >
        {label}
      </div>
      
      {/* Value */}
      {loading ? (
        <div className="h-7 sm:h-8 md:h-9 bg-slate-600 animate-pulse rounded" />
      ) : (
        <div
          className={clsx(
            'text-lg sm:text-xl md:text-2xl font-bold tabular-nums',
            getValueColor()
          )}
        >
          {value !== null && value !== undefined
            ? formatValue(value, format, decimals, showSign)
            : 'N/A'
          }
        </div>
      )}
    </div>
  )
}

export default MetricCard
