/**
 * StrategyMultiSelector - Multi-select component for strategy comparison
 *
 * Features:
 * - Multi-select dropdown with checkboxes
 * - Color-coded chips showing selected strategies
 * - Max 3 strategies enforced
 * - Accessible keyboard navigation
 * - Mobile responsive design
 *
 * @version 1.0.0
 * @part Multi-Strategy Comparison UI
 */

import { useState, useRef, useEffect } from 'react'
import { ChevronDown, X, Plus } from 'lucide-react'
import { useStrategy } from '../contexts/StrategyContext'
import {
  STRATEGY_COLOR_HEX,
  MAX_COMPARE_STRATEGIES,
  getPatternIndicator,
} from '../constants/strategyColors'

interface StrategyMultiSelectorProps {
  /** Callback when selection changes */
  onChange?: (strategyIds: string[]) => void
  /** Additional CSS classes */
  className?: string
  /** Compact mode for mobile */
  compact?: boolean
}

export function StrategyMultiSelector({
  onChange,
  className = '',
  compact = false,
}: StrategyMultiSelectorProps) {
  const {
    strategies,
    compareStrategies,
    toggleCompareStrategy,
    getStrategyDisplayName,
    isLoading,
    primaryStrategyId,
  } = useStrategy()

  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Notify parent of changes
  useEffect(() => {
    onChange?.(compareStrategies)
  }, [compareStrategies, onChange])

  const handleToggle = (strategyId: string) => {
    // If already selected, allow removal
    if (compareStrategies.includes(strategyId)) {
      toggleCompareStrategy(strategyId)
      return
    }

    // If at max, don't add more
    if (compareStrategies.length >= MAX_COMPARE_STRATEGIES) {
      return
    }

    toggleCompareStrategy(strategyId)
  }

  const handleRemove = (strategyId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    toggleCompareStrategy(strategyId)
  }

  const getDisplayName = (id: string): string => {
    const name = getStrategyDisplayName(id)
    // Shorten display names for compact view
    return name.replace('Hierarchical Adaptive ', '')
  }

  const getColorForIndex = (index: number): string => {
    return STRATEGY_COLOR_HEX[index as keyof typeof STRATEGY_COLOR_HEX] || STRATEGY_COLOR_HEX[0]
  }

  if (isLoading) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <div className="animate-pulse bg-gray-700 rounded h-10 w-48" />
      </div>
    )
  }

  if (strategies.length === 0) {
    return (
      <div className={`text-gray-400 text-sm ${className}`}>
        No strategies available
      </div>
    )
  }

  const selectionCount = compareStrategies.length
  const atMax = selectionCount >= MAX_COMPARE_STRATEGIES

  return (
    <div className={`flex flex-col gap-2 ${className}`} ref={dropdownRef}>
      {/* Dropdown trigger */}
      <div className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={`
            flex items-center justify-between gap-2 min-h-[44px]
            px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg
            border border-slate-600 transition-colors
            ${compact ? 'w-full' : 'min-w-[200px]'}
          `}
          aria-expanded={isOpen}
          aria-haspopup="listbox"
        >
          <span className="text-sm text-gray-200">
            {selectionCount === 0
              ? 'Select strategies to compare'
              : selectionCount === 1
              ? '1 strategy selected'
              : atMax
              ? `${selectionCount} strategies (max)`
              : `${selectionCount} strategies selected`}
          </span>
          <ChevronDown
            className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        </button>

        {/* Dropdown menu */}
        {isOpen && (
          <div className="absolute z-50 mt-1 w-full min-w-[250px] bg-slate-800 border border-slate-600 rounded-lg shadow-lg">
            <ul role="listbox" className="py-1 max-h-64 overflow-y-auto">
              {strategies.map((strategy) => {
                const isSelected = compareStrategies.includes(strategy.id)
                const isDisabled = !isSelected && atMax
                const selectionIndex = compareStrategies.indexOf(strategy.id)

                return (
                  <li key={strategy.id}>
                    <button
                      onClick={() => handleToggle(strategy.id)}
                      disabled={isDisabled}
                      className={`
                        w-full flex items-center gap-3 px-4 py-2 text-left
                        ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-slate-700'}
                        ${isSelected ? 'bg-slate-700/50' : ''}
                      `}
                      role="option"
                      aria-selected={isSelected}
                    >
                      {/* Checkbox */}
                      <div
                        className={`
                          w-5 h-5 rounded border-2 flex items-center justify-center
                          ${isSelected ? 'border-blue-500 bg-blue-500' : 'border-slate-500'}
                        `}
                      >
                        {isSelected && (
                          <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path
                              fillRule="evenodd"
                              d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                              clipRule="evenodd"
                            />
                          </svg>
                        )}
                      </div>

                      {/* Color indicator for selected items */}
                      {isSelected && (
                        <div
                          className="w-3 h-3 rounded-full flex-shrink-0"
                          style={{ backgroundColor: getColorForIndex(selectionIndex) }}
                        />
                      )}

                      {/* Strategy name */}
                      <span className="text-sm text-gray-200 flex-1">
                        {getDisplayName(strategy.id)}
                      </span>

                      {/* Primary badge */}
                      {strategy.id === primaryStrategyId && (
                        <span className="text-xs text-gray-500">(Primary)</span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>

            {/* Max warning */}
            {atMax && (
              <div className="px-4 py-2 text-xs text-amber-400 border-t border-slate-700">
                Maximum {MAX_COMPARE_STRATEGIES} strategies for comparison
              </div>
            )}
          </div>
        )}
      </div>

      {/* Selected strategy chips */}
      {selectionCount > 0 && (
        <div className={`flex flex-wrap gap-2 ${compact ? 'mt-1' : 'mt-2'}`}>
          {compareStrategies.map((strategyId, index) => (
            <div
              key={strategyId}
              className="flex items-center gap-2 px-3 py-1.5 bg-slate-700 rounded-full text-sm"
              style={{
                borderLeft: `4px solid ${getColorForIndex(index)}`,
              }}
            >
              {/* Color dot */}
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: getColorForIndex(index) }}
              />

              {/* Pattern indicator */}
              <span className="text-gray-500 text-xs font-mono">
                {getPatternIndicator(index)}
              </span>

              {/* Name */}
              <span className="text-gray-200">{getDisplayName(strategyId)}</span>

              {/* Remove button */}
              <button
                onClick={(e) => handleRemove(strategyId, e)}
                className="ml-1 p-0.5 hover:bg-slate-600 rounded-full transition-colors"
                aria-label={`Remove ${getDisplayName(strategyId)}`}
              >
                <X className="w-3.5 h-3.5 text-gray-400 hover:text-white" />
              </button>
            </div>
          ))}

          {/* Add button when not at max */}
          {!atMax && (
            <button
              onClick={() => setIsOpen(true)}
              className="flex items-center gap-1 px-3 py-1.5 bg-slate-700/50 hover:bg-slate-700 rounded-full text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Add
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default StrategyMultiSelector
