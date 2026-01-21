/**
 * StrategySelector - Component for selecting and comparing trading strategies
 *
 * Features:
 * - Dropdown/tabs for strategy selection
 * - Strategy status indicators
 * - Compare mode toggle
 * - Responsive design for mobile/desktop
 *
 * @version 1.0.0
 * @part Multi-Strategy UI - Phase 4
 */

import { useStrategy } from '../contexts/StrategyContext'
import { useQuery } from '@tanstack/react-query'
import { strategiesApi } from '../api/client'

interface StrategySelectorProps {
  /** Show compare toggle button */
  showCompare?: boolean
  /** Compact mode for mobile */
  compact?: boolean
  /** Additional CSS classes */
  className?: string
  /** Called when strategy changes */
  onChange?: (strategyId: string) => void
}

export function StrategySelector({
  showCompare = true,
  compact = false,
  className = '',
  onChange,
}: StrategySelectorProps) {
  const {
    strategies,
    selectedStrategy,
    setSelectedStrategy,
    isCompareMode,
    setCompareMode,
    compareStrategies,
    toggleCompareStrategy,
    primaryStrategyId,
    isLoading,
  } = useStrategy()

  // Fetch status for indicators
  const { data: statusData } = useQuery({
    queryKey: ['strategies-status'],
    queryFn: () => strategiesApi.getStatus().then(res => res.data),
    staleTime: 30 * 1000, // 30 seconds
    refetchInterval: 60 * 1000, // Refresh every minute
  })

  const handleStrategyChange = (strategyId: string) => {
    setSelectedStrategy(strategyId)
    onChange?.(strategyId)
  }

  const getStatusIndicator = (strategyId: string) => {
    const status = statusData?.strategies?.[strategyId]
    if (!status) return null

    const hasPositions = (status.position_count || 0) > 0
    const isActive = status.last_run !== null

    return (
      <span
        className={`inline-block w-2 h-2 rounded-full ml-2 ${
          hasPositions ? 'bg-green-500' : isActive ? 'bg-yellow-500' : 'bg-gray-400'
        }`}
        title={hasPositions ? 'Has positions' : isActive ? 'Active' : 'No data'}
      />
    )
  }

  if (isLoading) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <div className="animate-pulse bg-gray-700 rounded h-8 w-32" />
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

  // Compare mode view
  if (isCompareMode) {
    return (
      <div className={`flex flex-wrap items-center gap-2 ${className}`}>
        <span className="text-gray-400 text-sm mr-1">Compare:</span>
        <div className="flex flex-wrap gap-1">
          {strategies.map(strategy => (
            <button
              key={strategy.id}
              onClick={() => toggleCompareStrategy(strategy.id)}
              className={`
                px-3 py-1 rounded-full text-sm font-medium transition-colors
                ${compareStrategies.includes(strategy.id)
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }
              `}
            >
              {strategy.display_name.replace('Hierarchical Adaptive ', '')}
              {strategy.id === primaryStrategyId && (
                <span className="ml-1 text-xs opacity-75">(Primary)</span>
              )}
            </button>
          ))}
        </div>
        {showCompare && (
          <button
            onClick={() => setCompareMode(false)}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-full text-sm"
          >
            Exit Compare
          </button>
        )}
      </div>
    )
  }

  // Normal view - Tabs or Dropdown
  if (compact || strategies.length > 3) {
    // Dropdown for mobile or many strategies
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <span className="text-gray-400 text-sm">Strategy:</span>
        <select
          value={selectedStrategy}
          onChange={(e) => handleStrategyChange(e.target.value)}
          className="bg-gray-700 text-white rounded px-3 py-1 text-sm border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {strategies.map(strategy => (
            <option key={strategy.id} value={strategy.id}>
              {strategy.display_name.replace('Hierarchical Adaptive ', '')}
              {strategy.id === primaryStrategyId ? ' (Primary)' : ''}
            </option>
          ))}
        </select>
        {showCompare && strategies.length > 1 && (
          <button
            onClick={() => setCompareMode(true)}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm flex items-center gap-1"
            title="Compare strategies"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Compare
          </button>
        )}
      </div>
    )
  }

  // Tabs for desktop with few strategies
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <span className="text-gray-400 text-sm">Strategy:</span>
      <div className="flex gap-1 bg-gray-800 rounded-lg p-1">
        {strategies.map(strategy => (
          <button
            key={strategy.id}
            onClick={() => handleStrategyChange(strategy.id)}
            className={`
              px-4 py-1.5 rounded-md text-sm font-medium transition-all flex items-center
              ${selectedStrategy === strategy.id
                ? 'bg-blue-600 text-white shadow'
                : 'text-gray-300 hover:bg-gray-700'
              }
            `}
          >
            {strategy.display_name.replace('Hierarchical Adaptive ', '')}
            {strategy.id === primaryStrategyId && (
              <span className="ml-1 text-xs opacity-75">(P)</span>
            )}
            {getStatusIndicator(strategy.id)}
          </button>
        ))}
      </div>
      {showCompare && strategies.length > 1 && (
        <button
          onClick={() => setCompareMode(true)}
          className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-sm flex items-center gap-1"
          title="Compare strategies"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          Compare
        </button>
      )}
    </div>
  )
}

export default StrategySelector
